# 30. Source Analysis, Response Language, and Tool-Staging Hardening Plan

## 목적

이 문서는 `plan/29_readonly_approval_terminal_remediation_plan.md` 이후
실제 `allcode` TTY 실행에서 남은 read-only source 분석 품질 문제를 닫기 위한
상세 고도화 계획이다.

핵심 목표는 다음 세 가지다.

1. 사용자가 입력한 자연어의 주 언어에 맞춰 최종 답변, 차단 요약, 검증/복구
   보고서를 일관되게 출력한다.
2. `src` 같은 코드 트리 분석 요청에서 모델이 무의미한 `list_directory`,
   빈 `search_files`, 반복 `read_file` 루프에 빠지지 않도록 source-analysis
   전용 read-only 탐색 흐름을 제공한다.
3. 오픈소스 CLI coding agent의 검증된 패턴을 현재 allCode 구조 안에 현실적으로
   적용하되, 특정 테스트 프롬프트나 프로젝트명 하드코딩 없이 일반화된 신호만
   사용한다.

이 계획은 새 제품 범위를 확장하지 않는다. MCP manager, plugin marketplace,
multi-agent swarm, cloud sandbox, full LSP integration, full interactive diff editor,
git auto-commit은 계속 MVP 범위 밖이다.

## 우선 참조 문서

구현 전 다음 문서를 순서대로 다시 읽는다.

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/05_routing_policy_plan.md`
6. `plan/06_tool_system_plan.md`
7. `plan/07_workspace_context_plan.md`
8. `plan/08_context_memory_plan.md`
9. `plan/11_quality_testing_plan.md`
10. `plan/12_mvp_execution_plan.md`
11. `plan/17_model_routed_tool_system_remediation_plan.md`
12. `plan/18_open_source_agent_hardening_plan.md`
13. `plan/21_open_source_parity_95_hardening_plan.md`
14. `plan/27_validation_repair_convergence_plan.md`
15. `plan/29_readonly_approval_terminal_remediation_plan.md`
16. 이 문서

충돌 시 `plan/00`~`12`를 우선한다. 이 문서는 `29`의 read-only/approval
수정을 이어받아 source 분석 품질과 최종 답변 언어 정책을 좁게 보강한다.

## 공개 오픈소스 참조 요약

계획 작성 시 현재 공개 문서를 다시 확인했다.

- Aider repo map은 전체 repository의 핵심 class/function/type/signature와
  정의 라인을 compact map으로 모델에 제공하고, 대형 repo에서는 graph ranking과
  token budget으로 관련 부분만 선택한다.
  - https://aider.chat/docs/repomap.html
- Gemini CLI는 `GEMINI.md`를 global/project/ancestor/sub-directory 계층으로
  로드하고, footer 및 `/memory show`, `/memory refresh`, `/memory add`로
  활성 context를 사용자가 확인할 수 있게 한다.
  - https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- Qwen Code는 file-system tool을 `list_directory`, `read_file`, `glob`,
  `grep_search`, `edit`처럼 목적별로 분리한다. 특히 `glob`은 패턴 기반 파일
  인벤토리에, `grep_search`는 내용 검색에 사용하고 결과 수를 제한해 context
  overflow를 방지한다.
  - https://qwenlm.github.io/qwen-code-docs/en/developers/tools/file-system/
- OpenHands는 tool system을 `Action -> Observation` 구조로 표준화하고,
  Pydantic schema, registry, execution lifecycle, tool annotation을 분리한다.
  - https://docs.openhands.dev/sdk/arch/tool-system
- OpenHands event 문서는 user/agent/environment source와 LLM role을 분리하고,
  ActionEvent와 ObservationEvent를 LLM message로 변환 가능한 단위로 관리한다.
  - https://docs.openhands.dev/sdk/arch/events
- OpenHands stuck detector는 같은 action-observation 반복, action-error 반복,
  agent monologue, alternating pattern을 탐지해 무한 루프와 비용 낭비를 막는다.
  - https://docs.openhands.dev/sdk/guides/agent-stuck-detector

## 실제 재현 및 현재 문제 분석

최근 TTY session log:

```text
~/.allcode/session/2026/06/04/20260604_051435-03_newcli-d28bb7ea.jsonl
```

실제 입력:

```text
현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다
```

확인된 개선점:

- `PromptConstraintExtractor`와 `ModelRouter` 보강 이후 route는 `inspect`로
  결정되었다.
- `read_only_requested=True`가 유지되었다.
- mutation, shell, approval 경로로 넘어가지 않았다.

남은 문제:

1. `inspect` route의 tool schema가 `list_directory`, `read_file`,
   `search_files`만 제공되어, 코드 트리 역할 요약 같은 inventory 요청에서도
   모델이 얕은 directory listing을 반복하거나 broad search를 시도한다.
2. `search_files`는 현재 빈 query를 거부하지 않아 `query=""` 같은 요청이
   대량 결과 또는 무의미한 검색으로 이어질 수 있다.
3. `list_directory`는 한 단계 listing만 제공하고 structured metadata를
   반환하지 않아, 모델이 전체 `src/allCode` 패키지 역할을 파악하려면 여러
   round를 반복해야 한다.
4. `source_overview` 또는 `glob_files` 같은 파일 인벤토리/요약 전용 도구가
   없어 Aider식 repo map을 tool observation으로 직접 사용할 수 없다.
5. `RoundRunner`에는 inspect action/round budget은 있으나, source overview나
   충분한 grounded evidence 이후 도구를 닫고 final answer로 수렴시키는
   source-analysis finalization gate가 없다.
6. `PromptBuilder.final_answer_request()`는 English-only이고,
   `PromptBuilder.summarize_blocked_turn()`은 Korean-only다.
   `agent/finalization.py`에는 `_prompt_language()`가 있지만 이 로직이
   `prompt_builder`, `final_reporter`, `revalidation`, `finalization_helpers`와
   공유되지 않는다.
7. `FinalReporter`는 generation report를 항상 English heading으로 만든다.
8. 최종 답변이 실제로 읽은 근거보다 넓게 추론해 README 내용이나 package 이름을
   일반화하는 경향이 있다. read-only source 분석에서는 “확인한 근거”와
   “추론한 역할”을 분리해야 한다.

## agy 검토 요약

`agy --print`로 read-only 계획 검토를 요청했다. 첫 실행은 timeout으로
종료되었고, 두 번째 실행은 저장소 파일은 수정하지 않았으나 Antigravity 내부
brain 경로에 검토 artifact를 생성했다. 검토만 요청했음에도 외부 artifact를
만든 점은 절차 리스크로 기록한다.

agy의 적용 가능한 피드백:

- `agent/language.py`는 현재 구조에 자연스럽게 들어맞는다.
- `search_files` 빈 query guard는 낮은 위험의 즉시 수정 대상이다.
- `glob_files`, `list_tree`, `source_overview`는 builtin read-only tool로
  추가하고 registry에 등록하면 현재 ToolExecutor 구조와 맞는다.
- `source_overview`는 기존 `memory/repo_map.py`와 workspace index/symbol
  extractor를 재사용해야 한다.
- staged inspect는 명시 파일 경로 또는 `target_hint`가 있을 때 discovery
  round를 우회하고 바로 `read_file`을 허용해야 한다.
- discovery에서 target을 찾지 못하면 content-only로 고정하지 말고 discovery
  tool을 한 번 더 허용해야 한다.
- early finalization gate 조건은 명확해야 한다.
  - read-only inspect route
  - source overview 성공 또는 명시 target 확인
  - 필요한 prompt target이 read/list/search observation으로 grounded 됨
- `list_tree`와 `source_overview`는 depth, file count, symbol count, char count
  제한을 tool 계층에서 강제해야 한다.
- mixed-language prompt는 우선 단순하고 예측 가능한 CJK/Hangul detection으로
  시작하고, 설정 기반 locale은 후속 확장으로 둔다.

## Non-Negotiable Constraints

금지:

- 특정 프롬프트 문장, 특정 scenario ID, 특정 프로젝트명, 특정 파일명을 source에
  박아 우회하지 않는다.
- `query == ""`를 특정 테스트만 통과시키는 방식으로 처리하지 않는다.
- source overview를 위해 full-file dump를 만들지 않는다.
- read-only route에서 mutation, shell, validation, approval이 열리지 않게 한다.
- TUI가 agent 내부 상태를 직접 import하지 않는다.
- provider/model 이름에 따라 branching하지 않는다.
- 새 대형 기능인 MCP, LSP, plugin marketplace, git auto-commit을 추가하지 않는다.

허용되는 일반화 신호:

- `RoutingDecision.kind`, `read_only_requested`, `tool_capabilities`,
  `target_hint`, `flags`.
- Prompt에서 추출된 명시 path/file/symbol 후보.
- ToolResult metadata의 `observation.kind`, `target`, `evidence_count`,
  `truncated`, `suggested_reads`.
- `CompletionEvidence.inspected_paths`, `search_candidate_paths`,
  `zero_result_queries`, 신규 source overview evidence.
- 반복 action-observation signature, empty-query denied count, inspect budget.
- language detector가 반환하는 target response language.

## 목표 아키텍처

### 1. Shared Response Language Layer

신규 파일:

```text
src/allCode/agent/language.py
```

역할:

- 사용자 prompt에서 최종 응답 주 언어를 판정한다.
- prompt builder, final reporter, revalidation, blocked summary, finalization
  policy가 같은 언어 판정과 template을 쓰게 한다.
- code identifier, path, command, error symbol은 번역하지 않는다는 규칙을
  명시한다.

권장 public API:

```python
ResponseLanguage = Literal["ko", "en"]

def detect_response_language(prompt: str) -> ResponseLanguage: ...
def language_instruction(language: ResponseLanguage) -> str: ...
def final_answer_request_text(language: ResponseLanguage) -> str: ...
def blocked_summary_labels(language: ResponseLanguage) -> BlockedSummaryLabels: ...
def generation_report_labels(language: ResponseLanguage) -> GenerationReportLabels: ...
```

초기 판정 규칙:

- Hangul 문자가 1개 이상이고, prompt의 자연어 비중이 code/path보다 크면 `ko`.
- Hangul이 없으면 `en`.
- mixed prompt에서는 code identifier, path, command는 원문 유지하되 설명 문장은
  `ko`를 우선한다.
- locale config는 이번 단계에서 추가하지 않는다. 추후 필요하면
  `ALLCODE_RESPONSE_LANGUAGE=auto|ko|en`로 확장할 수 있게 함수 boundary만 둔다.

수정 대상:

```text
src/allCode/agent/prompt_builder.py
src/allCode/agent/final_reporter.py
src/allCode/agent/finalization.py
src/allCode/agent/finalization_helpers.py
src/allCode/agent/revalidation.py
```

세부 변경:

- `PromptBuilder.final_answer_request(messages, response_language=...)`로 확장한다.
- `summarize_blocked_turn(..., response_language=...)`로 확장한다.
- `FinalReporter.build(..., response_language=...)`로 확장한다.
- `evidence_final_answer(..., response_language=...)`가 생성/수정/검증/리스크
  heading을 언어별로 만든다.
- `apply_final_answer_policy()`는 기존 `_prompt_language()` 대신 shared
  `detect_response_language()`를 사용한다.

수용 기준:

- 한국어 prompt의 최종 답변과 blocked summary는 한국어다.
- 영어 prompt의 최종 답변과 blocked summary는 영어다.
- file path, module name, class/function name, validation command는 원문을
  보존한다.

### 2. Empty Search Guard

수정 대상:

```text
src/allCode/tools/builtin/search.py
src/allCode/agent/recovery.py
src/allCode/agent/tool_orchestrator.py
tests/unit/tools/test_search_tool.py
tests/unit/agent/test_recovery.py
```

변경:

- `search_files.query`가 빈 문자열 또는 whitespace-only이면 실행하지 않고
  `ToolResult(ok=False, error_type="invalid_query")`를 반환한다.
- error message는 provider-neutral하고 짧게 작성한다.
  - 한국어/영어 localizing은 final answer에서 처리하고, tool error는 기술적
    observation으로 둔다.
- metadata:

```json
{
  "invalid_query": true,
  "required_next_action": "Use glob_files/list_tree/source_overview for file inventory, or provide a non-empty literal/regex search query.",
  "observation": {
    "kind": "search_invalid",
    "target": "...",
    "summary": "search_files requires a non-empty query",
    "risk": "low"
  }
}
```

- 같은 empty search가 2회 이상 발생하면 `ToolLoopGuard` 또는 recovery가
  source overview/list tree로 전환하는 targeted retry prompt를 넣는다.
- 빈 query 거부는 exact prompt 대응이 아니라 tool schema 유효성 검증이다.

수용 기준:

- `query=""`와 `query="   "`는 workspace scan을 수행하지 않는다.
- `search_files`가 inventory 용도로 오용될 때 모델은 `glob_files`,
  `list_tree`, `source_overview` 중 하나로 전환한다.

### 3. Glob/List Tree Tools

신규 파일:

```text
src/allCode/tools/builtin/glob.py
src/allCode/tools/builtin/tree.py
```

수정:

```text
src/allCode/tools/builtin/__init__.py
src/allCode/runtime.py
src/allCode/agent/policy.py
src/allCode/agent/tool_schema_filter.py
src/allCode/agent/phase_gate.py
```

`glob_files` schema:

```json
{
  "pattern": "src/**/*.py",
  "path": ".",
  "max_results": 100,
  "include_dirs": false
}
```

규칙:

- workspace root 하위만 허용한다.
- `.git`, `.venv`, `node_modules`, `dist`, `build`, `target`, `__pycache__`,
  cache/output artifact directory는 기본 제외한다.
- `.gitignore` respect는 가능하면 `rg --files -g` 또는 Python fallback에서
  ignore set을 적용한다. 완전한 gitignore parser는 이번 단계에서 필수 아님.
- 결과는 path, kind, size, mtime, extension을 metadata에 포함한다.
- 기본 `max_results=100`, hard cap `300`.

`list_tree` schema:

```json
{
  "path": "src",
  "max_depth": 2,
  "max_entries": 160,
  "include_hidden": false
}
```

규칙:

- directory inventory 요청에는 `list_directory`보다 `list_tree`를 우선한다.
- output은 사람이 읽는 compact tree와 structured metadata를 모두 제공한다.
- truncation이 발생하면 `truncated=true`, `omitted_count`, `next_suggested_tool`을
  metadata에 넣는다.
- binary/generated/vendor directory는 기본 제외한다.

수용 기준:

- `src` 역할 요약 요청에서 모델은 얕은 `list_directory` 반복 없이
  `list_tree` 또는 `source_overview`로 전체 패키지 후보를 얻는다.
- tool output이 terminal transcript를 오염시키지 않도록 long content는
  foldable/artifact renderer가 사용할 수 있는 metadata를 포함한다.

### 4. Source Overview Tool

신규 파일:

```text
src/allCode/tools/builtin/source_overview.py
```

재사용 대상:

```text
src/allCode/workspace/indexer.py
src/allCode/workspace/symbol_extractor.py
src/allCode/memory/repo_map.py
src/allCode/memory/repo_ranker.py
src/allCode/memory/selector.py
```

schema:

```json
{
  "path": "src",
  "focus": "package_roles",
  "max_files": 80,
  "max_symbols": 120,
  "max_depth": 3
}
```

지원 focus:

```text
package_roles
entrypoints
symbols
tests
recent_targets
```

초기 MVP에서는 focus를 hint로만 사용하고, 내부적으로는 같은 bounded overview
pipeline을 실행한다. focus별 복잡한 ranking은 후속 확장이다.

output content 예:

```text
Source overview for src:
- packages: allCode
- top modules:
  - src/allCode/agent: routing, prompt building, round execution, recovery
  - src/allCode/tools: registry, approval, builtin tools
  - src/allCode/core: provider/UI-neutral models, events, results
- suggested reads:
  - src/allCode/main.py
  - src/allCode/agent/loop.py
  - src/allCode/tools/executor.py
```

metadata:

```json
{
  "observation": {
    "kind": "source_overview",
    "target": "src",
    "summary": "Summarized N files, M symbols under src",
    "risk": "low"
  },
  "overview_paths": ["src/allCode/agent", "src/allCode/tools"],
  "suggested_reads": ["src/allCode/main.py"],
  "file_count": 80,
  "symbol_count": 120,
  "truncated": true,
  "omitted_files": 34
}
```

중요 규칙:

- source overview는 file content 전체를 반환하지 않는다.
- symbol/signature/docstring/import 중심 skeleton summary만 반환한다.
- 큰 repo에서도 hard caps를 tool layer에서 강제한다.
- workspace와 memory 사이 순환 import를 만들지 않는다.
  - tool은 workspace root/indexer/repo_map builder를 호출하되, agent loop를 import하지
    않는다.
- source overview 실패는 agent를 막지 않고 `list_tree` 또는 `glob_files` fallback
  observation을 제공한다.

수용 기준:

- read-only source 분석 prompt에서 `source_overview` 1회로 패키지별 역할 초안을
  만들 수 있다.
- final answer는 “도구로 확인한 구조”와 “역할 추론”을 분리한다.
- source overview가 실패하더라도 안전하게 `glob_files`/`list_tree` fallback으로
  진행한다.

### 5. Source Analysis Tool Staging

수정 대상:

```text
src/allCode/agent/policy.py
src/allCode/agent/tool_schema_filter.py
src/allCode/agent/phase_gate.py
src/allCode/agent/round_runner.py
src/allCode/agent/prompt_builder.py
```

신규 또는 확장 모델:

```python
class InspectToolStage(CoreModel):
    stage: Literal["direct_answer", "source_discovery", "targeted_read", "finalize"]
    allowed_tool_names: set[str]
    reason: str
    target_paths: list[str] = []
    evidence_complete: bool = False
```

stage 결정 규칙:

1. `routing.kind != "inspect"`이면 적용하지 않는다.
2. `routing.read_only_requested=True` 또는 `routing.requires_tools=True`인 inspect에만
   적용한다.
3. prompt나 `target_hint`에 명시 file path가 있으면 round 1부터 `read_file`을
   허용한다.
4. prompt가 directory/module inventory, package role, 구조 요약이면 round 1에는
   `source_overview`, `list_tree`, `glob_files`를 우선 노출한다.
5. `source_overview` 또는 `list_tree`에서 `suggested_reads`가 나오면 round 2부터
   `read_file`을 허용하되, 최대 2~3개 대표 파일로 제한한다.
6. discovery 실패 또는 zero-result이면 discovery tool을 1회 더 허용한다.
7. 같은 discovery action-observation 반복은 OpenHands stuck detector 패턴처럼
   stuck으로 보고 finalize/partial summary로 전환한다.
8. mutation/shell/validation/web 도구는 read-only local source analysis에서 계속
   숨긴다.

source-analysis prompt guidance:

- directory inventory에는 `search_files(query="")`를 사용하지 말고
  `source_overview`, `list_tree`, `glob_files`를 사용한다.
- source code 역할 요약은 full-file read가 아니라 overview 후 대표 file/range만
  확인한다.
- 이미 overview가 있으면 추가 listing을 반복하지 말고 final answer로 수렴한다.
- 최종 답변에는 확인한 경로, 주요 패키지 역할, 근거 부족 또는 truncation을
  명시한다.

수용 기준:

- read-only source 분석에서 allowed tool schema가 stage별로 좁아진다.
- 명시 file path 요청은 불필요한 discovery round 없이 직접 `read_file` 가능하다.
- directory/source overview 요청은 `source_overview` 또는 `list_tree`를 먼저 쓴다.

### 6. Inspect Finalization Gate

수정 대상:

```text
src/allCode/agent/round_runner.py
src/allCode/agent/round_response_handler.py
src/allCode/agent/finalization.py
src/allCode/agent/completion_gate.py
src/allCode/core/result.py
src/allCode/agent/tool_evidence.py
```

CompletionEvidence 확장 후보:

```python
source_overview_paths: list[str] = Field(default_factory=list)
source_overview_summaries: list[str] = Field(default_factory=list)
source_overview_truncated: bool = False
inspect_observation_count: int = 0
```

finalization gate 조건:

```text
route.kind == inspect
and route.read_only_requested or route.requires_tools
and no mutation required
and (
  source_overview_paths exists
  or explicit target path has read/list observation
  or search_candidate_paths exists and at least one selected file was read
)
and no active policy/schema/tool error requiring retry
```

동작:

- gate가 true이면 다음 model round에서 tool schema를 숨기고
  `PromptBuilder.final_answer_request(..., response_language=...)`만 추가한다.
- final answer 요청 이후 reasoning-only가 반복되면 `summarize_blocked_turn()`이
  아닌 grounded source-analysis partial summary를 생성한다.
- inspect budget 근처에서 gate가 아직 false이면:
  - 확인한 observation 기반으로 partial answer를 만들고,
  - 부족한 근거와 다음 안전한 확인 단계만 적는다.
- `max_rounds_reached`를 사용자에게 그대로 노출하지 않고, 사용자 작업 언어로
  “확인한 범위와 남은 한계”를 정리한다.

수용 기준:

- read-only source analysis는 보통 2~4 model round 안에 final answer로 수렴한다.
- final answer가 없거나 빈 답변이면 success가 아니다.
- source overview 또는 read/search/list evidence 없이 workspace 구조를 단정하지
  않는다.

### 7. Tool Evidence and Telemetry

수정 대상:

```text
src/allCode/agent/tool_evidence.py
src/allCode/core/events.py
src/allCode/telemetry/session_logger.py
src/allCode/telemetry/session_analyzer.py
tests/unit/telemetry/test_session_logger.py
tests/unit/telemetry/test_session_analyzer.py
```

추가할 event/metadata:

- `source_overview_collected`
- `empty_search_denied`
- `inspect_stage_selected`
- `inspect_finalization_gate_opened`

session analyzer metric:

```text
source_overview_count
list_tree_count
glob_files_count
empty_search_denied_count
inspect_round_count
logical_read_action_count
repeated_inspect_target_count
final_answer_language
```

목표:

- 사람이 session log만 보고 어떤 도구로 어떤 근거를 모았고 왜 final answer로
  수렴했는지 알 수 있어야 한다.
- TUI는 이 event를 compact action row로 렌더링하고 raw JSON을 transcript에
  흘리지 않는다.

### 8. TUI/Terminal Rendering 보강

수정 대상:

```text
src/allCode/tui/renderers.py
src/allCode/tui/event_bridge.py
src/allCode/tui/terminal_activity.py
src/allCode/tui/status_commands.py
```

동작:

- `source_overview`는 `inspect src · 80 files · 120 symbols` 같은 compact row로
  표시한다.
- `empty_search_denied`는 debug-only 또는 status-only로 남기고 사용자를 놀라게
  하지 않는다. 반복될 때만 “검색어가 비어 있어 구조 탐색 도구로 전환 중” 정도의
  사용자 친화 메시지를 표시한다.
- finalization gate가 열리면 status에 “근거 정리 중”을 표시한다.
- approval UI는 이번 계획의 주요 대상은 아니지만, read-only source analysis에서는
  approval event가 발생하지 않아야 한다.

수용 기준:

- source 분석 과정이 Codex-style compact tool activity로 보인다.
- 긴 overview output이 transcript를 오염시키지 않는다.
- 최종 답변은 user-visible event로 출력된다.

## 단계별 구현 계획

### Phase 0. 회귀 테스트 먼저 고정

추가/수정 테스트:

```text
tests/unit/agent/test_language.py
tests/unit/agent/test_prompt_builder_language.py
tests/unit/agent/test_final_reporter_language.py
tests/unit/tools/test_search_tool.py
tests/unit/tools/test_glob_tree_tools.py
tests/unit/tools/test_source_overview_tool.py
tests/unit/agent/test_inspect_tool_staging.py
tests/integration/test_readonly_source_analysis.py
tests/tty/test_terminal_readonly_source_analysis.py
```

테스트 케이스:

- 한국어 read-only source 분석 요청:
  - route inspect
  - mutation/shell/approval 없음
  - `source_overview` 또는 `list_tree` 사용
  - 빈 `search_files` 없음
  - 4 model round 이하
  - final answer 한국어
- 영어 read-only source 분석 요청:
  - final answer 영어
- 명시 파일 요청:
  - round 1에서 `read_file` 허용
  - discovery-only 강제 없음
- 일반 Q&A:
  - direct answer route에서 도구 노출 없음
- source overview truncation:
  - hard cap 적용
  - metadata에 truncation 명시
- empty query:
  - `invalid_query` 반환
  - workspace scan 없음

### Phase 1. Shared Language Layer

순서:

1. `agent/language.py` 추가.
2. 기존 `finalization._prompt_language()`를 wrapper 또는 import로 대체.
3. `PromptBuilder.final_answer_request()`와 `summarize_blocked_turn()` 확장.
4. `FinalReporter`와 `revalidation.evidence_final_answer()` 확장.
5. language unit tests 실행.

검증:

```bash
python -m pytest tests/unit/agent/test_language.py tests/unit/agent/test_prompt_builder_language.py tests/unit/agent/test_final_reporter_language.py
```

### Phase 2. Search Guard and Inventory Tools

순서:

1. `search_files` 빈 query guard 추가.
2. `glob_files` 추가.
3. `list_tree` 추가.
4. runtime builtin registry 등록.
5. ToolPolicy/tool schema filter에 read-only search capability 매핑 추가.
6. unit tests 실행.

검증:

```bash
python -m pytest tests/unit/tools/test_search_tool.py tests/unit/tools/test_glob_tree_tools.py tests/unit/agent/test_policy.py
```

### Phase 3. Source Overview Tool

순서:

1. 기존 repo map/indexer/symbol extractor API 확인.
2. 순환 import 없이 read-only `SourceOverviewTool` 구현.
3. hard cap, ignore dirs, fallback behavior 구현.
4. ToolEvidence 업데이트.
5. unit/integration tests 실행.

검증:

```bash
python -m pytest tests/unit/tools/test_source_overview_tool.py tests/unit/memory/test_repo_map.py tests/unit/workspace
```

### Phase 4. Inspect Tool Staging and Finalization Gate

순서:

1. inspect stage 결정 helper 추가.
2. `RoundRunner`에서 source-analysis stage별 allowed tools 적용.
3. 명시 target path는 round 1 `read_file` 허용.
4. source overview evidence complete 조건 추가.
5. final answer request에 response language 전달.
6. inspect budget 초과 전 grounded partial summary 생성.
7. integration tests 실행.

검증:

```bash
python -m pytest tests/unit/agent/test_inspect_tool_staging.py tests/integration/test_readonly_source_analysis.py
```

### Phase 5. Telemetry and Terminal Rendering

순서:

1. source overview/inspect stage event 추가.
2. session logger/analyzer metric 추가.
3. terminal renderer compact action row 추가.
4. TTY smoke 추가.

검증:

```bash
python -m pytest tests/unit/telemetry/test_session_logger.py tests/unit/telemetry/test_session_analyzer.py tests/tty/test_terminal_readonly_source_analysis.py
```

### Phase 6. 회귀 및 실제 모델 검증

기본 회귀:

```bash
python -m pytest tests/unit/agent tests/unit/tools tests/unit/workspace tests/unit/memory
python -m pytest tests/integration
python -m pytest tests/tty tests/quality
python -m pytest
```

실제 모델 smoke:

```bash
allcode
```

테스트 prompt 범주:

- 일반 질문.
- read-only source 분석.
- 명시 파일 분석.
- 후속 질문.
- 신규 프로젝트 생성.
- 기존 파일 수정.
- 오류 로그 기반 수리.

read-only source 분석 수용 기준:

- approval 요청 없음.
- mutation/shell tool 없음.
- source overview/list tree/glob/search/read evidence가 session log에 남음.
- `search_files(query="")` 없음.
- final answer가 사용자 입력 언어와 일치.
- 최종 답변이 “확인한 근거”와 “추론한 역할”을 구분.
- 4 model round 이하를 목표로 하고, 대형 repo truncation 시 partial summary와
  추가 확인 경로를 명시.

## 품질 기준

`plan/11_quality_testing_plan.md`의 100점 기준을 유지한다. 이번 계획의
추가 평가 항목은 다음과 같다.

```text
source_analysis_grounding: 10
response_language_alignment: 10
inspect_loop_efficiency: 10
```

이 항목은 기존 quality score를 대체하지 않고 source-analysis scenario의
보조 metric으로 기록한다.

목표:

- read-only source analysis scenario: 90점 이상.
- 일반 Q&A direct answer route: tool call 0 유지.
- 전체 cross-genre stress: fail 0, warning 2 이하.
- open-source parity 추정: source-analysis/tool-staging 영역 90% 이상.

## 리스크와 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| 너무 엄격한 staging으로 명시 파일 분석도 overview를 거침 | round 낭비 | prompt/target_hint에 명시 file path가 있으면 round 1 `read_file` 허용 |
| source_overview가 큰 repo에서 과도한 output 생성 | token/cost 증가 | tool layer hard cap, truncation metadata, suggested_reads 제한 |
| empty search guard 후 모델이 empty query를 반복 | round 낭비 | invalid_query 반복을 recovery budget에 반영하고 source_overview/list_tree retry prompt 삽입 |
| 언어 판정이 mixed prompt에서 흔들림 | 답변 언어 불일치 | Hangul 포함 prompt는 설명 문장 한국어 우선, code/path는 원문 유지 |
| repo map/symbol extractor가 특정 언어에서 약함 | overview 품질 저하 | lightweight fallback으로 path/import/header 중심 summary 제공 |
| finalization gate가 너무 빨리 열림 | 근거 부족 답변 | source_overview 또는 explicit target observation을 최소 조건으로 둠 |
| finalization gate가 너무 늦게 열림 | max rounds | inspect budget 75% 지점에서 grounded partial summary로 수렴 |
| TUI renderer가 새 event를 몰라 raw output 표시 | UX 저하 | new event에 compact renderer와 debug-only fallback 추가 |

## 구현 시 금지되는 잘못된 해결책

- `"현재 디렉터리의 src"` 문장을 직접 매칭해 source overview를 강제하지 않는다.
- `"코드 수정은 엄격히 금지한다"` exact string만으로 read-only를 판단하지 않는다.
- `src/allCode`만 특별 취급하지 않는다.
- 특정 모델 응답 패턴에 맞춘 provider/model branch를 만들지 않는다.
- search empty query를 자동으로 `src` tree listing으로 바꾸지 않는다. 잘못된
  tool argument는 명시적으로 invalid observation이 되어야 한다.
- source overview를 README 복붙으로 대체하지 않는다.

## 최종 완료 조건

- 새 source-analysis 경로가 unit/integration/tty/quality 테스트로 고정된다.
- 한국어 prompt의 최종 답변은 한국어로 출력된다.
- read-only source 분석에서 mutation/shell/approval이 발생하지 않는다.
- source overview/list tree/glob/search/read evidence가 structured ToolResult로
  남는다.
- inspect loop가 반복 listing/search로 max rounds에 도달하지 않는다.
- 세션 로그와 terminal transcript에서 어떤 근거로 답변했는지 확인 가능하다.
- 전체 회귀 테스트가 통과하거나, 실패가 있으면 `review/`에 코드 위치와 원인을
  남긴 뒤 수정한다.
