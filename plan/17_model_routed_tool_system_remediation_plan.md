# 17. Model-Routed Tool System and Web Backend Remediation Plan

## 목적

이 문서는 실제 `allcode` 실행 검증에서 발견된 tool routing, file mutation, web search backend, terminal observability 문제를 수정하기 위한 상세 보강 계획서다.

검증 대상 workspace:

```text
/Users/kimtj319/Documents/01_wisenut/01_search_engine/02_7.3_engine
```

실제 관찰된 핵심 문제:

- 단순 파일 생성 요청이 `generation workflow`로 과도하게 라우팅되어 `allcode_tool_smoke.txt` 대신 `allcode_tool_smoke_txt/README.md` scaffold를 만들었다.
- `GenerationWorkflow`가 런타임 approval 설정과 무관하게 내부 `ApprovalManager(mode="auto")`를 생성해 기본 실행 안전 계약을 우회했다.
- `patch_file`은 준비 상태까지 표시됐지만 실제 파일 변경 및 tool result 관찰로 이어지지 않았다.
- 삭제 요청은 처리되지 않았고, first-class delete tool 또는 안전한 delete transaction이 없다.
- tool loop 중 정상 진행 상태가 `Retrying`으로 표시되어 사용자에게 오류 복구처럼 보였다.
- `read_file`이 line range/size limit 없이 full-file dump를 반환해 대형 repo에서 비효율적이다.
- `web_search`는 builtin tool로 등록되어 있으나 backend 미설정 상태에서는 evidence bundle을 수집할 수 없다.

이 계획의 목표는 위 문제를 해결하되, allCode의 원래 의도를 바꾸지 않는 것이다. allCode는 OneCLI all-rounder 철학을 유지하며, 모델이 필요한 도구를 판단하되 safety, approval, workspace policy는 코드가 강제한다.

## 참조한 기존 계획서

이 문서는 아래 계획과 충돌하지 않도록 작성한다.

- `00_master_implementation_guide.md`: 모델 자유도, 작은 모듈, 단일 책임, 검증 없는 완료 금지.
- `01_open_source_alignment_contracts.md`: Aider repo map, Gemini CLI hierarchical memory, Qwen Code provider-neutral terminal agent, OpenHands action/event 관찰성.
- `03_core_contracts_plan.md`: `ToolCall`, `ToolResult`, `CompletionEvidence`, `RecoveryState`, `ToolLoopSignature` 단일 core 계약.
- `04_llm_loop_plan.md`: provider-neutral stream, heartbeat, timeout, tool loop guard.
- `05_routing_policy_plan.md`: router는 실행하지 않고 전략만 결정한다는 책임 경계.
- `06_tool_system_plan.md`: `EditTransaction`, approval preview, search/replace patch, destructive shell 차단.
- `07_workspace_context_plan.md`: safe path normalization, 대형 repo full dump 금지.
- `08_context_memory_plan.md`: recent target, repo map, context selector 책임 분리.
- `09_generation_workflow_plan.md`: skeleton-first는 신규/다중 파일 생성에만 적용하고, 실제 변경/검증 근거 없이 완료 금지.
- `10_tui_app_plan.md`, `15_codex_tui_alignment_plan.md`, `16_codex_default_terminal_ui_plan.md`: event 기반 UI, tool/status 표시, terminal-native composer.
- `11_quality_testing_plan.md`: tool appropriateness, safety compliance, final grounding 품질 점수.
- `12_mvp_execution_plan.md`: 마일스톤, final completion gate, 전체 회귀 기준.

## 외부 공개 문서 확인 결과

계획 수립 중 현재 공개 문서를 확인했다.

- Aider repo map은 repository 전체의 class/function/type/signature 중심 compact map을 LLM에 제공하고, 관련성이 높은 부분을 token budget에 맞춰 선택한다.
  - https://aider.chat/docs/repomap.html
- Qwen Code 문서는 CLI frontend와 core backend를 분리하고, core가 모델 요청에 따라 tool registration/execution을 담당하며, file/shell tool은 승인 정책을 거친다고 설명한다.
  - https://qwenlm.github.io/qwen-code-docs/en/developers/architecture/
- OpenHands tool system은 `Action -> Observation` 계약, Pydantic schema validation, registry, execution lifecycle을 분리한다.
  - https://docs.openhands.dev/sdk/arch/tool-system
- Gemini CLI는 `GEMINI.md`를 global/project/directory hierarchy로 로드하고 `/memory` 명령으로 context를 관리한다.
  - https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- SearXNG는 무료 self-host metasearch engine이며, `/search?q=...&format=json` 형태의 HTTP search API를 제공한다. 단, JSON format은 instance 설정에서 활성화되어야 하며 public instance는 이를 막을 수 있다.
  - https://docs.searxng.org/
  - https://docs.searxng.org/dev/search_api.html

## 정합성 검수 결론

기존 `05_routing_policy_plan.md`에는 static rule과 LLM router 보조를 조합하는 설계가 있다. 그러나 실제 검증에서 키워드 기반 helper가 단순 파일 생성 요청을 프로젝트 생성 workflow로 잘못 보냈다.

따라서 이 문서는 `05`를 다음처럼 정정한다.

- 작업 종류 결정은 키워드 기반 static router가 아니라 모델 기반 structured router가 담당한다.
- deterministic extractor는 routing kind를 결정하지 않는다.
- deterministic extractor는 명시적 안전 제약, 경로 문법, workspace boundary, 최근 target 후보만 수집한다.
- 최종 tool 허용 여부는 여전히 `ToolPolicy`, `ApprovalManager`, `PathPolicy`가 강제한다.

이 정정은 `01`의 "모델에게 자유도를 주되 위험한 실행은 policy와 approval이 제어한다"는 계약과 일치한다.

## P0. 안전한 현상 고정과 회귀 테스트 추가

### 수정 대상

```text
tests/integration/test_realistic_tool_use_matrix.py
tests/unit/agent/test_model_router.py
tests/unit/agent/test_workflow_handoff.py
tests/unit/tools/test_file_ops.py
tests/unit/tools/test_tool_executor.py
tests/unit/tools/test_web_provider.py
tests/quality/prompt_matrix.yaml
```

### 테스트로 먼저 고정할 케이스

1. 단순 파일 생성:

```text
프로젝트 루트에 sample_note.txt 파일을 만들고 내용 한 줄을 작성해줘.
```

기대:

- `generation workflow`가 아니라 direct file mutation route.
- 실제 target은 `sample_note.txt`.
- `sample_note_txt/README.md` 같은 scaffold 금지.

2. 단순 파일 수정:

```text
sample_note.txt 첫 줄을 정확히 다른 문장으로 바꿔줘.
```

기대:

- `patch_file` 또는 `write_file` 사용.
- 변경 전후 diff와 `CompletionEvidence.changed_files` 갱신.
- 실패 시 final success 금지.

3. read-only 분석:

```text
pom.xml을 읽고 모듈 구조를 설명해줘. 파일은 수정하지 마.
```

기대:

- mutation/shell tool 금지.
- read/search tool만 허용.

4. 대형 repo 탐색:

```text
CmanagerMain 실행 진입점을 찾아서 관련 파일 5개 이하로 요약해줘.
```

기대:

- `search_files` 우선.
- 필요 파일만 `read_file` line range로 읽음.
- full-file dump 반복 금지.

5. web search:

```text
최신 공개 문서를 검색해서 SearXNG JSON API 사용법을 evidence 기반으로 요약해줘.
```

기대:

- SearXNG backend 설정 시 evidence bundle 반환.
- backend 미설정 시 명확한 `ExternalSearchUnavailable`.
- raw search result를 최종 답변으로 그대로 출력 금지.

6. 삭제:

```text
sample_note.txt 테스트 파일만 삭제해줘.
```

기대:

- first-class delete tool 또는 안전한 trash transaction 사용.
- workspace root 밖 삭제 금지.
- recursive delete는 명시 승인 없으면 금지.

### 검증 명령

```bash
python -m pytest tests/unit/agent/test_model_router.py tests/unit/agent/test_workflow_handoff.py
python -m pytest tests/unit/tools/test_file_ops.py tests/unit/tools/test_tool_executor.py tests/unit/tools/test_web_provider.py
python -m pytest tests/integration/test_realistic_tool_use_matrix.py
python -m pytest tests/quality
```

## P1. 키워드 기반 라우팅 제거와 모델 기반 structured router 도입

### 현재 문제

현재 `src/allCode/agent/intent.py`와 `workflow_routing.py`는 `MODIFY_TERMS`, `INSPECT_TERMS`, `OPERATE_TERMS`, `GENERATION_MARKERS`, `PROJECT_TERMS` 같은 키워드 목록을 사용해 routing kind와 workflow handoff를 결정한다.

이 방식은 다음 문제를 만든다.

- "파일을 만들라"와 "프로젝트를 만들라"를 안전하게 구분하지 못한다.
- 한국어/영어 동사의 조합이 늘어날수록 keyword list가 커진다.
- 모델이 tool 선택을 담당한다는 all-rounder 철학과 어긋난다.
- 특정 테스트 문구에 맞춘 회귀성 규칙이 생기기 쉽다.

### 새 구조

```text
UserPrompt
  -> PromptConstraintExtractor
  -> ContextBuilder + RecentTargetResolver
  -> ModelRouter.classify(...)
  -> RoutingDecision
  -> ToolPolicy.allowed_registered_tool_names(...)
  -> LLM loop with allowed tool schemas
  -> ToolExecutor + Approval + PathPolicy
```

### 새 파일/수정 파일

```text
src/allCode/agent/prompt_constraints.py
src/allCode/agent/model_router.py
src/allCode/agent/router.py
src/allCode/agent/workflow_routing.py
src/allCode/agent/prompt_builder.py
tests/unit/agent/test_model_router.py
tests/unit/agent/test_prompt_constraints.py
```

### `PromptConstraintExtractor`

이 모듈은 route kind를 결정하지 않는다. 다음만 추출한다.

- 명시적 금지/제약: read-only, no shell, no network, destructive 금지.
- 명시적 path 후보: backtick path, slash 포함 path, 확장자 포함 file name.
- 후속 질문 후보: recent target resolver에 넘길 pronoun/context marker.
- 사용자 지정 validation phrase는 route가 아니라 `constraints.validation_requested_hint`로만 보관.

작업 종류는 절대 여기서 `answer/inspect/modify/operate`로 분류하지 않는다.

### `ModelRouter`

모델에게 아래 JSON schema로 routing을 맡긴다.

```python
class ModelRoutingDecision(CoreModel):
    kind: Literal["answer", "inspect", "modify", "operate"]
    confidence: float
    tool_capabilities: set[Literal[
        "read_file",
        "search_workspace",
        "mutate_file",
        "delete_file",
        "run_shell",
        "run_validation",
        "web_search",
    ]]
    workflow_hint: Literal[
        "none",
        "direct_answer",
        "direct_file_edit",
        "single_file_create",
        "multi_file_generation",
        "validation_repair",
        "external_research",
    ]
    target_hint: str | None
    requires_validation: bool
    requires_external_knowledge: bool
    reason: str
```

운영 규칙:

- 라우팅 모델은 같은 `LLMClient`를 사용하되 non-stream structured completion으로 호출한다.
- provider가 strict JSON schema를 지원하지 않으면 JSON repair parser를 사용하되, 실패 시 safe inspect로 fallback한다.
- 모델 routing 결과가 안전 제약과 충돌하면 안전 제약이 이긴다.
- confidence `< 0.45` 또는 schema invalid이면 mutation/shell/web을 노출하지 않고 clarification 또는 safe inspect로 전환한다.
- route가 `answer`라도 모델이 `web_search` capability를 명시하면 web tool만 허용한다.
- route가 `modify`라도 `read_only_requested=True`이면 mutation capability를 제거한다.

### 제거/축소 대상

- `IntentExtractor.MODIFY_TERMS`, `INSPECT_TERMS`, `OPERATE_TERMS`, `EXTERNAL_TERMS`를 routing 결정에서 제거한다.
- `workflow_routing.should_use_generation_workflow(prompt, routing)`의 keyword 기반 handoff를 제거한다.
- `RoutingDecision.needs_llm_router`는 model router가 기본이 되므로 의미를 바꾼다. static confidence threshold는 fallback 진단용으로만 유지한다.

## P2. Workflow handoff를 모델 결정 + preflight 검증으로 변경

### 현재 문제

`should_use_generation_workflow()`가 prompt keyword를 사용해 generation workflow를 시작한다. 이 때문에 단순 파일 생성 요청이 project scaffold로 오분류됐다.

또한 `GenerationWorkflow`는 내부에서 자체 `ToolExecutor(approval=ApprovalManager(mode="auto"))`를 만들어 런타임 approval을 우회한다.

### 수정 대상

```text
src/allCode/agent/workflow_routing.py
src/allCode/agent/workflow.py
src/allCode/agent/workflow_actions.py
src/allCode/agent/loop.py
src/allCode/agent/task_plan.py
src/allCode/agent/completion_checker.py
tests/unit/agent/test_workflow_handoff.py
tests/integration/test_generation_workflow.py
```

### 새 handoff 규칙

Generation workflow는 다음 조건을 모두 만족할 때만 시작한다.

1. `ModelRoutingDecision.kind == "modify"`.
2. `workflow_hint == "multi_file_generation"` 또는 `workflow_hint == "validation_repair"`.
3. model route가 `ProjectPlan` 초안을 반환하거나, 다음 round에서 `create_project_plan` 형태의 planning output을 제공한다.
4. target root가 안전한 relative path다.
5. 단일 파일 생성/수정이면 workflow가 아니라 일반 tool loop로 처리한다.

### 단순 파일 작업 규칙

- `single_file_create`: `write_file` 직접 사용.
- `direct_file_edit`: `read_file`로 현재 내용 확인 후 `patch_file` 우선, 필요 시 `write_file`.
- `delete_file`: `delete_path` 또는 `trash_path` tool 사용.
- path가 명확하지 않으면 repo map/recent target/search로 후보를 찾고, 다중 후보면 clarification.

### approval 수정

- `GenerationWorkflow.__init__`는 자체 `ApprovalManager(mode="auto")`를 만들지 않는다.
- `AgentLoop`가 주입한 runtime `ToolExecutor`를 그대로 사용한다.
- `--approval auto` 또는 `ALLCODE_APPROVAL_MODE=auto`일 때만 file mutation이 자동 허용된다.
- `ask` 모드에서는 terminal/TUI approval responder가 실제 사용자 입력을 받아야 한다.
- headless `ask`는 approval 필요 시 `partial` 또는 non-zero exit로 종료하고, `--approval auto` 안내를 출력한다.

## P3. OpenHands식 Action/Observation tool lifecycle 적용

### 적용 원칙

OpenHands의 tool system처럼 allCode tool도 명확한 lifecycle을 가진다.

```text
ToolCall(JSON)
  -> argument validation
  -> policy check
  -> risk classification
  -> preview / dry-run
  -> approval
  -> transaction open
  -> execute
  -> observation normalize
  -> evidence update
  -> event publish
```

### 수정 대상

```text
src/allCode/tools/base.py
src/allCode/tools/executor.py
src/allCode/tools/approval.py
src/allCode/tools/diff.py
src/allCode/core/models.py
src/allCode/core/events.py
tests/unit/tools/test_tool_executor.py
```

### `ToolDefinition` 확장

```python
class ToolDefinition(CoreModel):
    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool
    group: str
    aliases: list[str] = []
    risk: Literal["low", "medium", "high"] = "low"
    side_effects: list[Literal["filesystem", "process", "network"]] = []
    output_mode: Literal["evidence", "diff", "log", "artifact"] = "evidence"
    idempotent: bool = False
```

### `ToolObservation` 추가

`ToolResult`는 core 단일 모델로 유지하되, metadata 구조를 표준화한다.

```text
metadata.observation:
  kind: file_read | file_write | file_patch | file_delete | search | shell | validation | web
  target: path/url/command
  summary: short human summary
  artifacts: optional full logs
  evidence: structured evidence list
  risk: low/medium/high
```

### 이벤트 정책

- `ToolCallRequested`: 모델이 어떤 도구를 원했는지.
- `ApprovalRequested`: preview와 risk 포함.
- `ToolExecutionStarted`: 실제 실행 시작.
- `ToolExecutionFinished`: `ToolResult`와 observation 포함.
- `ToolExecutionSkipped`: approval denied, policy denied, route mismatch.

`Retrying`이라는 상태 문구는 실제 retry에만 사용하고, tool result 후 다음 모델 round를 기다리는 정상 상태는 `Waiting for model` 또는 `Continuing with tool result`로 표시한다.

## P4. File tool 정밀화

### 수정 대상

```text
src/allCode/tools/builtin/file_ops.py
src/allCode/tools/diff.py
src/allCode/workspace/path_resolver.py
tests/unit/tools/test_file_ops.py
```

### `read_file` 개선

새 schema:

```json
{
  "file_path": "path",
  "start_line": 1,
  "end_line": 120,
  "max_bytes": 20000,
  "include_line_numbers": true
}
```

규칙:

- default는 전체 파일이 아니라 안전한 최대 크기 내 head/tail summary.
- 직접 target file이 작을 때만 full read 허용.
- 256KB 초과 파일은 기본적으로 range read만 허용하고 `truncated=True` metadata를 붙인다.
- 결과에는 `content_hash`, `line_count`, `returned_range`, `truncated`를 포함한다.

### `write_file` 개선

- `file_path`를 그대로 사용한다. 모델이 `.txt`를 요청했으면 `.txt` 파일을 생성해야 하며 디렉터리 scaffold로 변환하지 않는다.
- `create_only`, `overwrite`, `expected_hash` 옵션을 추가한다.
- parent directory 생성은 허용하되, 요청 path를 임의로 project root로 해석하지 않는다.
- 성공 시 `created_files`, `changed_files`, `transaction.diff`를 반드시 갱신한다.

### `patch_file` 개선

- 현재 search/replace schema는 유지한다.
- `expected_hash`를 추가해 오래된 파일 기반 patch를 방지한다.
- 0회/2회 이상 match는 실패하며 파일을 변경하지 않는다.
- 성공/실패 모두 `ToolExecutionFinished` event를 발행한다.
- patch 준비 후 조용히 입력 대기로 돌아가는 경로를 금지한다.

### `delete_path` 추가

삭제는 shell `rm`이 아니라 first-class tool로 제공한다.

```json
{
  "path": "sample_note.txt",
  "recursive": false,
  "expected_hash": "optional",
  "move_to_trash": true
}
```

규칙:

- 기본은 file delete만 허용한다.
- directory delete는 `recursive=true`와 explicit approval 필요.
- delete 전 `EditTransaction`에 rollback payload 또는 trash path를 기록한다.
- workspace root 밖 삭제 금지.
- `.git`, workspace root 자체, home directory는 항상 금지.

## P5. Search tool 성능 개선

### 수정 대상

```text
src/allCode/tools/builtin/search.py
src/allCode/workspace/indexer.py
src/allCode/memory/repo_map.py
tests/unit/tools/test_search_tool.py
```

### 개선 방향

- 가능하면 `rg` executable을 사용한다.
- `rg`가 없으면 현재 Python fallback을 사용한다.
- ignore 규칙은 `07` 계약과 맞춘다: `.git`, `.venv`, `node_modules`, `dist`, `build`, `target`, `__pycache__` 제외.
- `max_results`, `context_lines`, `glob`, `file_types`, `case_sensitive`를 지원한다.
- 결과는 raw text만이 아니라 structured rows를 metadata에 넣는다.

```text
metadata.matches:
  - path
    line
    preview
```

### Aider repo map 연동

검색 전후에 repo map ranking을 활용한다.

- query에 symbol-like token이 있으면 repo map의 definitions를 먼저 검색한다.
- 검색 결과가 많으면 ranker로 상위 파일을 압축한다.
- 모델이 필요 파일을 고를 수 있게 file path + signature + short preview를 제공한다.

## P6. Shell/validation tool 안정화

### 수정 대상

```text
src/allCode/tools/builtin/shell.py
src/allCode/tools/approval.py
src/allCode/agent/validation_runner.py
tests/unit/tools/test_shell_tool.py
```

### 개선 방향

- `run_tests`는 validation event를 발행하는 별도 경로로 유지한다.
- `run_command`는 기본 `ask` approval 대상이다.
- parsed argv 실행을 우선하고, shell string 실행은 `shell=true` 또는 explicit approval이 있을 때만 허용한다.
- interactive/background command, daemon, `rm -rf`, `sudo`, disk-level command는 high risk로 분류한다.
- stdout/stderr는 preview와 artifact를 분리한다.
- full log는 transcript에 직접 넣지 않고 `.allCode/artifacts/{turn_id}/...`에 저장한다.

## P7. 무료 web search backend로 SearXNG 도입

### 선택

무료로 사용할 수 있고 allCode의 provider-neutral 계약에 가장 잘 맞는 기본 web backend 후보는 SearXNG로 한다.

선정 근거:

- 무료 open-source metasearch engine이다.
- 여러 search service를 aggregation한다.
- self-host 가능하다.
- `/search` endpoint와 `format=json` API가 있다.
- privacy/no tracking 방향이 allCode의 local-first coding agent 성격과 맞다.

제약:

- public instance는 JSON format을 비활성화할 수 있다.
- 안정적인 coding agent 용도에는 self-host instance를 권장한다.

### 수정 대상

```text
src/allCode/config/schema.py
src/allCode/config/defaults.py
src/allCode/config/manager.py
src/allCode/tools/web_provider.py
src/allCode/tools/builtin/web.py
tests/unit/tools/test_web_provider.py
tests/integration/test_web_search_optional.py
README.md
```

### Config 확장

```yaml
web:
  backend: searxng
  search_url: http://127.0.0.1:8080/search
  api_key_env: null
  timeout_seconds: 15
  default_language: ko-KR
  default_categories:
    - general
```

환경변수:

```text
ALLCODE_WEB_SEARCH_BACKEND=searxng
ALLCODE_WEB_SEARCH_URL=http://127.0.0.1:8080/search
ALLCODE_WEB_SEARCH_API_KEY_ENV=
ALLCODE_WEB_SEARCH_TIMEOUT=15
```

### `SearxngSearchProvider`

요청:

```text
GET {search_url}?q={query}&format=json&language={language}&categories={categories}
```

또는 instance 설정에 따라 POST form도 지원한다.

응답 normalization:

```python
class WebEvidence(CoreModel):
    title: str
    url: str
    snippet: str
    source: str | None
    published_at: str | None
    rank: int
```

규칙:

- raw JSON을 final answer에 직접 출력하지 않는다.
- `ToolResult.content`는 "Collected N web evidence item(s)" 같은 요약만 담는다.
- 세부 evidence는 `metadata.evidence_bundle`에만 넣는다.
- public instance 403 또는 JSON disabled는 `ExternalSearchUnavailable`로 명확히 반환한다.

### `web_fetch` 개선

현재 `web_fetch`는 content injection이 없으면 사용할 수 없다. 다음처럼 실제 HTTP fetch를 지원한다.

- `httpx.AsyncClient`로 GET.
- content-type이 HTML이면 title, main text, headings, code snippets 일부만 추출.
- max_chars 기본 8,000.
- binary/content-too-large는 실패 observation.
- redirect limit과 timeout 적용.
- robots/terms 정책은 backend 문서에 따르며, 무분별한 crawling은 하지 않는다.

## P8. Approval UI와 headless 정책 정리

### 수정 대상

```text
src/allCode/tools/approval.py
src/allCode/tools/executor.py
src/allCode/tui/terminal.py
src/allCode/tui/approval_panel.py
src/allCode/headless.py
tests/tty/test_terminal_approval.py
tests/integration/test_headless_approval.py
```

### Terminal/TUI ask mode

`ask` mode에서는 approval event만 발행하고 자동 deny로 끝내지 않는다. terminal/TUI가 다음 선택을 제공한다.

```text
y approve once
n deny
a allow this tool for session
d show diff/details
```

### Headless ask mode

Headless는 interactive approval을 받을 수 없으므로 다음 중 하나로 명확히 종료한다.

- mutation/shell 필요: `status=partial`, exit code non-zero, "rerun with --approval auto" 안내.
- read-only/web only: 정상 실행.

### Auto mode

`--approval auto`는 명시 선택일 때만 mutation을 허용한다. workflow 내부에서 몰래 auto를 만들 수 없다.

## P9. CompletionEvidence와 final gate 강화

### 수정 대상

```text
src/allCode/core/result.py
src/allCode/agent/completion_checker.py
src/allCode/agent/final_reporter.py
src/allCode/agent/turn_completion.py
src/allCode/tools/executor.py
```

### 강화 규칙

- file mutation tool 성공 시 `created_files`, `changed_files`, `transactions`를 evidence에 기록한다.
- delete tool 성공 시 `deleted_files`를 추가한다.
- validation tool 성공/실패 모두 `validation_commands`에 기록한다.
- direct file mutation 요청에서 `changed_files/created_files/deleted_files`가 비어 있으면 success 금지.
- validation-required 요청에서 `validation_passed is not True`면 success 금지.
- web search 요청에서 `evidence_bundle`이 비어 있으면 grounded final answer 금지.
- read-only 코드 분석 요청은 읽은 파일/search evidence가 metadata에 남아야 한다.

## P10. Tool result 화면 출력과 observability 정리

### 수정 대상

```text
src/allCode/tui/renderers.py
src/allCode/tui/event_bridge.py
src/allCode/tui/terminal_activity.py
src/allCode/tui/terminal_answer_renderer.py
src/allCode/tui/transcript_cells.py
tests/tty/test_terminal_body_output.py
tests/tty/test_terminal_codex_default_ui.py
```

### 표시 정책

- 정상 next-round 상태: `Waiting for model` 또는 `Continuing with tool result`.
- 실제 retry: `Retrying after empty response`, `Retrying after timeout`처럼 원인 포함.
- tool result preview는 20줄 또는 1,200자 이하.
- 긴 output은 folded/artifact로 분리.
- `read_file` full content가 transcript를 오염시키지 않게 접힌 tool cell로 표시.
- final answer와 streaming answer 중복 출력 금지.

## P11. 구현 순서

권장 순서:

1. P0 회귀 테스트를 먼저 추가한다.
2. `PromptConstraintExtractor`와 `ModelRouter`를 추가하고 기존 keyword router를 fallback으로 격리한다.
3. `workflow_routing`의 keyword handoff를 제거하고 model `workflow_hint` 기반으로 바꾼다.
4. `GenerationWorkflow`가 runtime `ToolExecutor`와 `ApprovalManager`를 주입받게 수정한다.
5. file tools의 `read_file`, `write_file`, `patch_file`, `delete_path`를 정밀화한다.
6. search tool을 `rg` 우선으로 개선하고 repo map ranking과 연결한다.
7. SearXNG provider와 config를 추가한다.
8. approval ask mode의 terminal/headless 동작을 정리한다.
9. TUI/terminal status 문구와 folded tool output을 정리한다.
10. quality matrix에 실제 검증 프롬프트를 추가한다.
11. unit -> integration -> quality -> 실제 TTY smoke 순서로 검증한다.

## P12. 완료 기준

아래 기준을 모두 만족해야 이 보강이 완료된다.

- 특정 키워드 목록으로 `answer/inspect/modify/operate`를 결정하는 경로가 제거된다.
- 모델 router가 structured `RoutingDecision`을 만들고, schema invalid 시 safe inspect로 fallback한다.
- 단순 파일 생성 요청이 project scaffold로 변하지 않는다.
- `GenerationWorkflow`가 내부 auto approval을 만들지 않는다.
- 기본 `ask` mode에서 mutation은 실제 approval 없이는 실행되지 않는다.
- `--approval auto`에서는 file mutation, patch, validation이 `CompletionEvidence`를 갱신한다.
- `patch_file` 성공/실패가 항상 tool result와 event로 관찰된다.
- `read_file`은 line range/size limit을 지원한다.
- `search_files`는 `rg` 우선이며 대형 repo에서 full scan을 최소화한다.
- `web_search`는 SearXNG backend 설정 시 evidence bundle을 반환한다.
- web backend 미설정/JSON disabled는 명확한 오류로 드러난다.
- 삭제는 shell `rm`이 아니라 first-class safe delete tool 또는 explicit high-risk approval shell로만 가능하다.
- tool loop 중 정상 진행 상태가 `Retrying`으로 표시되지 않는다.
- 다음 명령이 통과한다.

```bash
python -m pytest tests/unit/agent tests/unit/tools
python -m pytest tests/integration
python -m pytest tests/quality
python -m pytest tests/tty
```

## MVP 이후로 미룰 항목

다음은 이번 보강의 직접 목표가 아니다.

- MCP server manager.
- multi-agent delegation.
- cloud sandbox backend.
- full browser automation.
- provider별 advanced reasoning option tuning.
- commercial search API 연동.

단, SearXNG provider 구조는 이후 Brave, Tavily, Serper 같은 상용/무료 tier backend를 adapter로 추가할 수 있도록 provider-neutral interface를 유지한다.
