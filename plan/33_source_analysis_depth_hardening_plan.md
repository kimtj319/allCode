# 33. Source Analysis Depth Hardening Plan

## 목적

이 문서는 `plan/30_source_analysis_language_tooling_hardening_plan.md`,
`plan/31_terminal_paste_tool_visibility_source_analysis_plan.md`,
`plan/32_readonly_constraint_routing_repair_plan.md` 이후에도 남은 실제 모델의
read-only source 분석 답변 깊이 문제를 해결하기 위한 상세 보강 계획이다.

현재 `allcode --headless` smoke 기준으로 read-only route와 mutation 차단은
정상화되었지만, `src` 또는 `src/allCode/agent` 분석 요청에서 답변이 다음처럼
얕게 끝나는 문제가 남아 있다.

- `source_overview`가 만든 package role과 파일 목록 일부만 답변에 반영된다.
- 대표 파일을 충분히 읽기 전에 inspect finalization으로 넘어간다.
- fallback summary가 실제 `read_file` 본문에서 class/function/import/wiring을
구조화하지 않는다.
- 모델이 “소스 구조를 요약”하라는 요청을 받았을 때 대표 파일을 여러 개 읽어야
한다는 단계 지시가 약하다.

목표는 새 제품 범위를 넓히는 것이 아니라, 기존 read-only inspect workflow를
Aider식 repo-map, Qwen식 file-system tool separation, OpenHands식
action/observation evidence 원칙에 맞게 더 깊고 안정적으로 만드는 것이다.

## 우선 참조 문서와 충돌 규칙

구현 전 아래 문서를 순서대로 다시 읽는다.

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/07_workspace_context_plan.md`
6. `plan/08_context_memory_plan.md`
7. `plan/21_open_source_parity_95_hardening_plan.md`
8. `plan/30_source_analysis_language_tooling_hardening_plan.md`
9. `plan/31_terminal_paste_tool_visibility_source_analysis_plan.md`
10. `plan/32_readonly_constraint_routing_repair_plan.md`
11. 이 문서

충돌 시 `plan/00`~`12`와 `plan/01`을 우선한다. 이 문서는 Plan 30/31/32를
대체하지 않고, 그 위에 “source 분석 깊이”만 좁게 보강한다.

## 현재 코드 기준 문제 지점

### 1. `inspect_staging.py`의 조기 finalize

파일:

```text
src/allCode/agent/inspect_staging.py
```

현재 `_representative_targets()`는 `evidence.representative_read_paths`가 하나라도
있으면 즉시 빈 목록을 반환한다. 이 때문에 directory target이 넓고
`source_overview`가 여러 대표 파일 후보를 만들었더라도, 대표 파일 1개만 읽고
`_evidence_complete()`가 true가 되어 final answer 요청으로 넘어갈 수 있다.

필요한 변화:

- 대표 파일을 “1개 읽었는가”가 아니라 “요청 범위에 비례해 충분히 읽었는가”로
  판단한다.
- 충분성 기준은 prompt 문자열이나 특정 repo 이름이 아니라 다음 구조 신호를 쓴다.
  - `coverage.package_count`
  - `coverage.truncated`
  - `coverage.coverage_ratio`
  - `source_representative_candidates` 개수
  - 이미 읽은 `representative_read_paths`/`inspected_paths`
- 기본 목표는 최소 2개, 최대 4개 representative read다.
  - broad/truncated/package_count > 1이면 3~4개.
  - 작은 단일 파일/단일 package면 1~2개.
- `inspect_round_budget`을 넘지 않도록 round budget이 거의 끝나면 grounded
  fallback으로 finalize한다.

### 2. `source_overview.py`의 대표 파일 ranking이 얕음

파일:

```text
src/allCode/tools/builtin/source_overview.py
```

현재 `_representative_reads()`는 우선 파일명과 `definitions/imports` 수로 대표
파일을 고른다. 이 방식은 작고 단순하지만, 실제 agent/tool/runtime flow 분석에서는
중앙 orchestrator, public API, dependency wiring 파일을 놓칠 수 있다.

필요한 변화:

- full PageRank나 LSP는 도입하지 않는다.
- 기존 `WorkspaceIndexer`, `RepoMapBuilder`, `RepoMapEntry.definitions/imports`만
  사용해 lightweight centrality score를 계산한다.
- ranking 신호:
  - public class/function definition 수
  - import fan-out 근사치: 해당 파일의 imports 수
  - import fan-in 근사치: 다른 entry import 문자열에 path/module stem이 언급되는 횟수
  - entrypoint 후보 여부
  - package 내 유일한 public surface 여부
  - prompt target path와 group path 일치 여부
- metadata에 대표 선정 근거를 넣는다.
  - `representative_reasons`
  - `representative_scores`
  - `role_evidence`
- 사용자 답변에는 score를 그대로 노출하지 않고, summary/fallback이 “왜 이 파일이
  근거인지”를 짧게 설명하는 데만 사용한다.

### 3. `inspect_summary.py`가 read_file 본문을 구조화하지 않음

파일:

```text
src/allCode/agent/inspect_summary.py
```

현재 `grounded_inspect_summary()`는 package role metadata 중심이다. `read_file`
결과가 있더라도 파일 본문에서 핵심 class/function/import/entrypoint를 추출해
답변에 넣지 않는다.

필요한 변화:

- `read_file` tool result content를 lightweight parser로 분석한다.
- tree-sitter, LSP, 외부 parser는 도입하지 않는다.
- Python/JS/TS/Java/Go/Rust 정도의 공통 regex signature만 우선 지원한다.
- parsing 실패 시 빈 요약으로 fallback하고 전체 답변을 실패시키지 않는다.
- fallback summary에 다음 섹션을 추가한다.
  - `핵심 파일 근거`
  - `주요 클래스/함수`
  - `의존성/연결 흐름`
  - `아직 단정하지 않은 부분`
- 경로, symbol, command, class/function name은 번역하지 않는다.

### 4. `prompt_builder.py`의 targeted read 지시가 약함

파일:

```text
src/allCode/agent/prompt_builder.py
```

현재 `inspect_stage_request(stage="targeted_read")`는 대표 파일을 읽으라고만 한다.
모델이 “대표 파일 여러 개를 읽고 역할을 비교해야 한다”는 압력을 충분히 받지
못한다.

필요한 변화:

- targeted read 단계에서는 아직 읽지 않은 representative targets를 명시한다.
- “가능하면 하나만 읽고 끝내라”가 아니라 “budget 내에서 대표 파일을 순차적으로
  확인하라”는 지시를 준다.
- read-only 조건을 다시 강조한다.
- 최종 답변은 다음을 포함하라고 요구한다.
  - 확인한 파일 범위
  - package/module 역할
  - 대표 파일의 class/function/import 근거
  - 추론과 관찰의 구분

### 5. `tool_evidence.py`/`executor.py` metadata 보존 확인

파일:

```text
src/allCode/agent/tool_evidence.py
src/allCode/tools/executor.py
src/allCode/agent/finalization_helpers.py
```

Plan 31에서 지적한 것처럼 message history에서 tool result를 복원할 때
`source_overview` metadata가 손실되면 fallback summary가 얕아진다.

필요한 변화:

- `representative_reads`, `suggested_reads`, `package_roles`, `coverage`,
  `role_evidence`, 신규 `representative_reasons/scores`가 evidence 또는 tool
  message metadata에 보존되는지 확인한다.
- 복원 helper가 metadata를 버리지 않도록 테스트로 고정한다.

## Non-Negotiable Constraints

### 이전 Plan 제한사항 검토 결과

| 기준 문서 | 이 계획에서 반드시 지킬 제한 |
| --- | --- |
| `plan/00_master_implementation_guide.md` | NewCLI/allCode의 목적은 가벼운 엔터프라이즈 CLI coding agent다. source 분석 깊이 보강은 기존 MVP loop를 강화하는 범위로 제한하고, 거대한 단일 agent 파일이나 새 제품군을 만들지 않는다. |
| `plan/01_open_source_alignment_contracts.md` | Aider/Gemini/Qwen/OpenHands의 공개 설계 원칙은 repo map, hierarchical context, provider-neutral tool loop, action/observation 관찰성 보강에만 적용한다. 외부 프로젝트의 전체 기능을 복제하지 않는다. |
| `plan/03_core_contracts_plan.md` | `core`에는 provider/TUI/tool-specific 구현을 넣지 않는다. 필요한 근거는 `CompletionEvidence`, `ToolResult.metadata`, `AgentEvent` 같은 표준 모델로 전달한다. |
| `plan/04_llm_loop_plan.md` | 모델이 얕거나 reasoning-only 응답을 내도 loop가 빈 final answer로 끝나지 않게 하되, 모델별 분기나 특정 provider 보정은 금지한다. |
| `plan/05_routing_policy_plan.md` | read-only inspect route는 direct answer, external answer, modify/operate route와 분리한다. source 분석 품질을 높인다는 이유로 mutation tool을 노출하지 않는다. |
| `plan/06_tool_system_plan.md` | tool 결과는 표준 `ToolResult`와 evidence bundle로 축적한다. `source_overview` raw output을 그대로 최종 답변에 붙이지 않는다. |
| `plan/07_workspace_context_plan.md` | 대형 repo에서 full-file dump를 하지 않는다. repo map, symbol/signature, bounded inventory, representative read를 조합한다. |
| `plan/08_context_memory_plan.md` | source 분석 중 발견한 구조 정보는 session context에만 필요한 만큼 유지한다. secret/API token/raw file body를 memory에 저장하지 않는다. |
| `plan/10_tui_app_plan.md` | terminal/TUI는 agent 내부 상태를 직접 import하지 않는다. tool 진행 상태는 event/message로 표시하고, 내부 recovery code를 사용자 답변에 노출하지 않는다. |
| `plan/12_mvp_execution_plan.md` | 완료 답변은 근거가 있어야 한다. 구현/수정 요청이 아닌 read-only 분석에서는 파일 변경 근거가 아니라 관찰 근거가 completion evidence가 된다. |
| `plan/30_source_analysis_language_tooling_hardening_plan.md` | 답변 언어는 사용자 입력 언어를 따른다. symbol/path/code identifier는 번역하지 않는다. |
| `plan/31_terminal_paste_tool_visibility_source_analysis_plan.md` | terminal 입력/paste 문제와 tool visibility는 유지한다. source 분석 고도화 중 interactive startup path를 우회하지 않는다. |
| `plan/32_readonly_constraint_routing_repair_plan.md` | read-only 요청은 mutation, shell, validation, approval로 흐르지 않아야 한다. blocked approval summary를 read-only final answer로 만들지 않는다. |

### 구현 중 단계별 게이트

각 Phase를 시작하기 전에 다음을 다시 확인한다.

1. 해당 Phase가 read-only source analysis 깊이 보강에 직접 관련되는가.
2. 새 분기가 특정 테스트 prompt, scenario ID, 프로젝트명, 절대 경로에 의존하지 않는가.
3. source 분석을 위해 파일 본문을 과도하게 prompt나 final answer에 덤프하지 않는가.
4. mutation/shell/validation schema가 inspect route에 새로 열리지 않는가.
5. 새 helper가 300줄을 넘기 시작하면 분리 책임이 명확한가.
6. 테스트가 실제 모델에만 의존하지 않고 fake/tool-level deterministic assertion을 포함하는가.

금지:

- 특정 프롬프트, 특정 scenario ID, 특정 프로젝트명, 특정 repo path를 source에
  직접 하드코딩하지 않는다.
- `src`, `allCode`, `agent`, `main.py` 같은 현재 재현 경로 전용 예외를 만들지
  않는다.
- source 분석 품질을 높이기 위해 full-file dump를 만들지 않는다.
- read-only route에서 mutation, shell, validation, approval schema를 열지 않는다.
- 모델명/provider명에 따라 branch하지 않는다.
- MCP server manager, plugin marketplace, multi-agent swarm, cloud sandbox,
  full LSP integration, full PageRank graph, git auto-commit은 도입하지 않는다.
- TUI가 agent 내부 상태를 직접 import하지 않는다.
- 내부 parser status, recovery reason, raw score를 사용자 최종 답변에 그대로
  노출하지 않는다.
- 신규/수정 Python 파일은 500줄을 넘기지 않는다. 300줄을 넘기면 분리 후보로
  보고, 책임이 섞이면 별도 helper로 분리한다.

허용되는 일반화 신호:

- `RoutingDecision.kind`, `read_only_requested`, `target_hint`, `tool_capabilities`.
- `CompletionEvidence.source_overview_paths`,
  `source_representative_candidates`, `representative_read_paths`,
  `source_analysis_coverage`, `source_package_roles`, `inspected_paths`.
- `ToolResult.metadata.observation.kind`, `coverage`, `package_roles`,
  `representative_reads`, `suggested_reads`, `role_evidence`.
- `RepoMapEntry.path`, `definitions`, `imports`, `language`, `score`.
- 파일명 자체가 아니라 entrypoint/public surface/import centrality 같은 구조 신호.
- prompt에서 추출한 explicit path/symbol target.

## 목표 동작

read-only source analysis 요청이 들어오면 다음 흐름이어야 한다.

1. route는 `inspect`, `read_only_requested=True`로 유지된다.
2. 모델에게 mutation/shell/validation tool schema는 노출되지 않는다.
3. 첫 탐색은 `source_overview`, `list_tree`, `glob_files` 같은 bounded inventory
   tool로 시작한다.
4. `source_overview`가 representative targets를 만들면, agent는 최소 대표 파일
   2~4개를 budget 안에서 읽도록 `targeted_read` stage를 유지한다.
5. 대표 파일 read 결과에서 class/function/import/entrypoint 근거가
   `CompletionEvidence` 또는 fallback summary 입력으로 보존된다.
6. 모델이 정상 final answer를 만들면 그 답변을 사용하되, 답변이 얕거나
   reasoning-only fallback이 필요하면 `grounded_inspect_summary()`가 구조화된
   근거 요약을 생성한다.
7. 최종 답변은 사용자의 언어를 따른다.
8. 최종 답변은 관찰한 근거와 추론한 역할을 분리한다.
9. 실제 파일 변경은 0개다.

## Phase 0. 실패 조건 테스트 고정

### 수정 대상

```text
tests/unit/agent/test_inspect_tool_staging.py
tests/unit/agent/test_inspect_summary.py
tests/unit/tools/test_source_overview_tool.py
tests/unit/agent/test_finalization_helpers.py
tests/integration/test_readonly_source_analysis.py
tests/tty/test_terminal_readonly_source_analysis.py
```

### 추가 테스트

1. 대표 후보가 4개이고 1개만 읽은 경우 `decide_inspect_stage()`는 `finalize`가
   아니라 `targeted_read`를 유지한다.
2. 대표 후보가 충분히 읽혔거나 budget이 끝난 경우에만 `finalize`로 전환한다.
3. `source_overview`가 `representative_reasons`, `representative_scores`,
   `role_evidence` metadata를 제공한다.
4. `grounded_inspect_summary()`는 read_file content에서 추출한 class/function/import
   정보를 “핵심 파일 근거”에 포함한다.
5. 한국어 prompt에서는 summary section heading이 한국어다.
6. read-only integration에서 `write_file`, `patch_file`, `delete_path`,
   `run_tests`, `run_command`가 호출되지 않는다.
7. 실제 source 분석 integration은 최소 2개 이상의 representative read 또는 그에
   준하는 explicit target read evidence를 확보한다.

### 검증 명령

```bash
python -m pytest tests/unit/agent/test_inspect_tool_staging.py tests/unit/agent/test_inspect_summary.py
python -m pytest tests/unit/tools/test_source_overview_tool.py tests/unit/agent/test_finalization_helpers.py
python -m pytest tests/integration/test_readonly_source_analysis.py
python -m pytest tests/tty/test_terminal_readonly_source_analysis.py
```

## Phase 1. Inspect Staging의 대표 파일 충분성 기준 보강

### 수정 대상

```text
src/allCode/agent/inspect_staging.py
```

### 구현 계획

1. `_required_representative_read_count(evidence)` helper를 추가한다.
2. 계산 기준:
   - 후보가 0개면 0.
   - 단일 package 또는 coverage가 충분하면 `min(2, candidate_count)`.
   - `truncated=True`, `coverage_ratio < 0.85`, `package_count > 1`이면
     `min(4, max(2, package_count, candidate_count))`의 bounded 변형을 사용한다.
   - 최종 cap은 4.
3. `_representative_targets()`는 이미 읽은 수가 required count보다 적으면 아직
   읽지 않은 후보를 반환한다.
4. 후보 반환 개수는 한 round에서 너무 많은 tool schema pressure를 만들지 않도록
   `required_count - observed_count` 또는 최대 3개로 제한한다.
5. `_evidence_complete()`는 `source_overview_paths`만 보고 완료하지 않고,
   `_representative_targets()`와 required count를 함께 확인한다.
6. `inspect_round_budget`이 끝나면 완전하지 않아도 grounded summary로 수렴한다.

### 주의

- 대표 파일 read를 늘리되 무한 루프는 만들지 않는다.
- `representative_read_paths`와 `inspected_paths` 중복 계산을 normalize한다.
- explicit file target 요청은 기존처럼 targeted read 1회로 충분할 수 있다.

## Phase 2. Source Overview 대표 파일 ranking 고도화

### 수정 대상

```text
src/allCode/tools/builtin/source_overview.py
```

### 구현 계획

1. `_representative_reads()`를 scoring 기반으로 바꾼다.
2. 신규 helper 후보:
   - `_representative_scores(entries, groups, focus) -> dict[str, float]`
   - `_representative_reason(entry, score_inputs) -> list[str]`
   - `_module_stem(path) -> str`
   - `_fan_in_count(entry, all_entries) -> int`
3. scoring 신호:
   - definition count: public surface 근사.
   - import count: wiring/fan-out 근사.
   - fan-in count: 다른 파일이 이 모듈을 참조하는 근사.
   - preferred entrypoint names는 낮은 가중치로만 사용한다.
   - group coverage: package마다 최소 1개 대표 후보를 보장.
4. 대표 파일 선택:
   - 먼저 package/group별 top 1을 고른다.
   - 그 다음 전체 score top 파일로 채운다.
   - 최대 8개 유지.
5. metadata:
   - `representative_reads`
   - `representative_reasons`: `{path, reasons}`
   - `representative_scores`: `{path, score}`
   - `role_evidence`: 이미 있으면 유지하고 score 근거를 보강.

### 주의

- full graph PageRank는 도입하지 않는다.
- imports 문자열 매칭은 best-effort다. 틀릴 수 있으므로 confidence/score는 내부
  ranking 근거로만 사용한다.
- 사용자 최종 답변에 raw score를 표시하지 않는다.

## Phase 3. read_file 본문 기반 구조 요약 추가

### 수정 대상

```text
src/allCode/agent/inspect_summary.py
```

### 구현 계획

1. `_read_file_code_summaries(tool_results, language)` helper를 추가한다.
2. `ToolResult` 복원 기준:
   - `result.name == "read_file"`
   - `result.ok is True`
   - `content`가 존재
   - metadata의 `file_path` 또는 observation target으로 path 확인
3. lightweight signature 추출:
   - Python: `class Name`, `def name`, `async def name`, top-level imports.
   - JS/TS: `export function`, `function`, `class`, `const name =`, imports.
   - Java: `class/interface/enum`, public methods.
   - Go: `func`, `type`.
   - Rust: `fn`, `struct`, `enum`, `impl`.
4. summary line 예시:
   - ``src/allCode/agent/round_runner.py`: `RoundRunner`, `run_rounds`, `build_phase_tool_gate` 호출 흐름이 확인됨.``
5. 한국어/영어 heading:
   - KO: `핵심 파일 근거`, `주요 클래스/함수`, `의존성/연결 흐름`
   - EN: `Key File Evidence`, `Main Classes/Functions`, `Dependency/Wiring Clues`
6. 너무 긴 content는 parser 입력을 앞부분/중요 line 위주로 제한한다.
7. 추출 실패 시 summary를 비우고 기존 package role summary만 반환한다.

### 주의

- 이 parser는 correctness-critical compiler가 아니다. best-effort summary helper다.
- AST parser 의존성은 추가하지 않는다.
- code block 전체를 답변에 덤프하지 않는다.

## Phase 4. Evidence Recorder와 metadata 보존 검수

### 수정 대상

```text
src/allCode/agent/tool_evidence.py
src/allCode/tools/executor.py
src/allCode/agent/finalization_helpers.py
src/allCode/core/result.py
```

### 구현 계획

1. 현재 `CompletionEvidence`에 이미 있는 필드를 우선 사용한다.
2. 꼭 필요한 경우에만 다음 필드를 추가한다.
   - `source_representative_reasons: list[dict[str, object]]`
   - `source_representative_scores: dict[str, float]`
3. `ToolEvidenceRecorder._record_source_overview()`가 신규 metadata를 보존한다.
4. `ToolExecutor._update_completion_evidence()`와 중복 기록이 발생하면
   `ToolEvidenceRecorder` 쪽으로 단일화하거나 dedupe helper를 사용한다.
5. `last_tool_results()`가 message metadata를 복원할 때 신규 metadata를 잃지 않는지
   테스트한다.

### 주의

- `metadata`에는 JSON-safe primitive/list/dict만 넣는다.
- core model에 provider raw payload를 넣지 않는다.
- evidence field를 늘릴 때 final reporter나 session logger가 깨지지 않는지 본다.

## Phase 5. PromptBuilder targeted read 지시 강화

### 수정 대상

```text
src/allCode/agent/prompt_builder.py
```

### 구현 계획

1. `inspect_stage_request(stage="targeted_read")` 지시를 강화한다.
2. 포함할 내용:
   - 아직 읽지 않은 representative target을 우선 확인.
   - 각 파일에서 public class/function, import wiring, runtime entrypoint를 관찰.
   - 이미 읽은 파일은 반복하지 않음.
   - read-only 조건 유지.
   - 충분한 representative evidence 후 final answer.
3. final answer request에는 source 분석 답변 형식을 보강한다.
   - 확인한 범위
   - 패키지/모듈 역할
   - 대표 파일 근거
   - 아직 단정하지 않은 부분

### 주의

- 프롬프트만으로 동작을 보장하지 않는다. Phase 1~4의 deterministic evidence
  gating이 주 방어다.
- 한국어 요청에는 한국어 최종 답변을 유지한다.

## Phase 6. Integration 및 실제 모델 smoke

### 테스트 명령

```bash
python -m pytest tests/unit/agent/test_inspect_tool_staging.py tests/unit/agent/test_inspect_summary.py
python -m pytest tests/unit/tools/test_source_overview_tool.py tests/unit/agent/test_finalization_helpers.py
python -m pytest tests/integration/test_readonly_source_analysis.py
python -m pytest tests/unit/agent tests/unit/tools
python -m pytest tests/tty/test_terminal_readonly_source_analysis.py tests/tty/test_terminal_readonly_tool_visibility.py
python -m pytest
```

### 실제 smoke

```bash
allcode --headless "읽기 전용 분석이다. 소스 코드 수정, 파일 생성, 파일 삭제, 포맷팅 변경, 커밋은 엄격히 금지한다. 현재 디렉터리의 src 내 코드들이 어떤 역할을 하는지 한국어로 정리해줘."
allcode --headless "읽기 전용 분석이다. 소스 코드 수정, 파일 생성, 파일 삭제, 포맷팅 변경, 커밋은 엄격히 금지한다. src/allCode/agent 패키지의 루프, 라우팅, 툴 실행 흐름을 한국어로 요약해줘."
find src -name 'SUMMARY_KR.md' -o -name 'README_KR.md'
```

### 성공 기준

- 실제 파일 변경 0개.
- final answer에 `확인한 범위`, `주요 역할` 또는 이에 준하는 구조화 섹션이 있다.
- 대표 파일 근거가 최소 2개 이상 포함된다. 단일 파일 target이면 1개도 허용한다.
- class/function/import 또는 runtime wiring 근거가 답변에 포함된다.
- 내부 reason code, raw score, recovery status가 사용자 답변에 노출되지 않는다.
- `write_file`, `patch_file`, `delete_path`, `run_command`, `run_tests` 호출이 없다.
- 전체 pytest 통과.

## 남은 리스크

- 대표 read cap을 높이면 답변 품질은 좋아지지만 latency와 token 비용이 증가한다.
  기본 cap은 4로 제한한다.
- regex signature parser는 언어별 문법을 완벽히 이해하지 못한다. 답변에서는
  “확인된 signature 근거”로만 사용하고 semantic behavior를 단정하지 않는다.
- 실제 모델이 targeted read 지시를 무시하고 final answer를 바로 내면
  deterministic inspect staging이 다시 도구 schema를 열어야 한다.
- 대형 monorepo에서는 package_count가 커도 대표 read를 4개로 제한하므로 전체
  분석은 “요약”에 머문다. 더 깊은 분석은 후속 질문으로 좁혀야 한다.
- full LSP/PageRank를 넣지 않으므로 Aider와 동일한 ranking 정확도는 목표가 아니다.
  현재 MVP에서는 lightweight repo-map ranking까지만 목표로 한다.

## 다음 구현 시 주의사항

- Phase 0 테스트를 먼저 추가하고 실패를 확인한 뒤 구현한다.
- read-only invariant는 Plan 32 기준을 유지한다.
- source 분석 고도화 중 mutation/tool approval 경로를 건드리지 않는다.
- 답변 깊이를 높이려다 full-file dump를 만들지 않는다.
- 파일이 300줄을 넘기 시작하면 책임 분리 여부를 검토한다.
- tests 디렉터리가 `.gitignore`에 포함되어 있으므로 테스트 파일 커밋 필요 여부는
  작업 전에 따로 확인한다.
