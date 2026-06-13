# 51. Claude Sonnet Review 기반 잔여 Parity 보강 계획

Last updated: 2026-06-10

## 목적

`review/allcode_progress_analysis.md`의 Claude Sonnet 리뷰와 `plan/45`,
`plan/50`의 최신 진척도 판단을 현재 코드 구조에 매핑해, allCode가 오픈소스
CLI coding agent 대비 95% 수준에 접근하기 위해 남은 구현 지점을 정리한다.

이번 문서는 **계획서**다. 코드 구현은 별도 지시가 있을 때 진행한다.

## 적용 우선순위와 불변 조건

- `plan/00`부터 `plan/12`까지의 MVP 계약을 우선한다.
- `plan/01_open_source_alignment_contracts.md`가 모호한 설계 판단의 기준이다.
- 특정 테스트 프롬프트, 특정 출력 디렉터리, 특정 프로젝트명, 특정 시나리오 ID를
  하드코딩하지 않는다.
- 기존에 400줄을 넘는 파일에는 새 책임을 더 얹지 않는다. 새 로직은 별도 모듈로
  분리하고, 모든 Python 파일은 500줄 미만을 유지한다.
- fallback 강화만으로 품질을 올리지 않는다. 정상 모델 합성 경로가 먼저 좋아져야
  하며, fallback은 모델 답변이 비거나 grounding guard를 통과하지 못한 경우의
  마지막 안전장치다.
- core는 provider/TUI 독립을 유지한다.
- TUI는 agent 내부 상태를 직접 import하지 않고 event/UI-facing model만 소비한다.
- web 검색은 MVP 범위를 넘는 브라우저 자동화나 유료 backend 내장을 목표로 하지
  않는다. 설정된 무료/HTTP backend를 evidence bundle로 안정화하는 것이 범위다.

## 외부 오픈소스 참고 원칙

- Aider repo map: 전체 repo의 중요한 class/function/signature와 정의 라인을
  token budget에 맞춰 제공하고, 필요 시 모델이 더 볼 파일을 선택하게 한다.
  allCode에서는 이미 `source_overview`, `source_probe`, AST/LSP source intelligence가
  있으므로, 다음 보강은 "근거 수집"보다 "책임/흐름 합성 중간 표현" 강화에 둔다.
  참고: https://aider.chat/docs/repomap.html
- Gemini CLI memory: `GEMINI.md` 계층 컨텍스트와 persistent memory를 세션 시작마다
  자동 주입한다. allCode에서는 `ALLCODE.md`, `SessionStore`, `ActiveProjectObligations`
  모델을 재사용해 process restart 후에도 active context가 복원되게 한다.
  참고: https://geminicli.com/docs/cli/tutorials/memory-management/
- OpenHands tool system: tool public schema와 executor 구현을 분리하고, 실행 결과는
  observation으로 표준화한다. allCode에서는 tool result/event는 유지하되 approval,
  diff preview, user-facing timeline을 event 기반으로 더 일관되게 만든다.
  참고: https://docs.openhands.dev/sdk/arch/tool-system
- Qwen Code: provider-neutral, terminal-first, provider configuration layering를
  유지한다. allCode의 web/provider/LLM 설정도 core 결합 없이 config/runtime 경계에서
  확장한다.
  참고: https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/

## Claude 리뷰와 현재 코드 매핑

| 리뷰 갭 | 현재 코드 위치 | 현재 상태 | 보강 방향 |
| --- | --- | --- | --- |
| 라이브 웹 검색/외부 근거 합성 | `src/allCode/tools/web_provider.py`, `src/allCode/tools/builtin/web.py`, `src/allCode/agent/answer_policy.py`, `src/allCode/agent/final_answer_context.py`, `src/allCode/agent/finalization.py`, `src/allCode/runtime.py` | `ALLCODE_WEB_*` 설정이 없으면 disabled provider가 `web_search_unavailable` 반환. `web_fetch`는 injected content만 처리. | backend preflight, evidence health, web-only final synthesis 품질 강화. backend 미설정 시에도 명확한 한계와 대체 답변을 분리. |
| 소스 플로우 분석 깊이 | `src/allCode/agent/source_answer_synthesis.py`, `source_analysis_rendering.py`, `source_final_brief.py`, `source_answer_guard.py`, `source_answer_fallback.py`, `round_text_response.py`, `inspect_staging.py` | body sample anchor와 repo-internal edge 우선순위는 있음. 그러나 최종 답변이 여전히 deterministic fallback 문체로 흐를 수 있음. | `SourceResponsibilityGraph` 같은 중간 표현을 추가해 모델 최종 합성에 함수 책임, 근거 anchor, 내부 edge, 한계가 명확히 들어가게 함. |
| 생성 수렴 밀도 | `src/allCode/agent/project_planner.py`, `workflow.py`, `workflow_editor.py`, `completion_checker.py`, `final_reporter.py`, `task_loop_digest.py`, `generation/strategies/python.py` | skeleton-first workflow와 API/document/test gate는 강함. agy 대비 테스트 수, report artifact, behavior coverage가 덜 조밀함. | prompt-derived obligations를 coverage matrix로 만들고 tests/report/doc artifact가 이를 충족하는지 completion gate에서 확인. |
| 멀티턴 persistence | `src/allCode/agent/session_state.py`, `src/allCode/memory/project_obligations.py`, `session_store.py`, `context.py`, `context_session_sections.py`, `runtime.py` | `ActiveProjectObligations`, `LatestRepairContext`, `SourceExplorationLedger`는 in-process 상태로 context에 주입됨. `SessionStore`는 turn transcript 저장 중심. | session state snapshot을 append/load하고 새 프로세스 시작 시 복원해 repair context와 obligations를 라우팅보다 먼저 주입. |
| approval/diff UX | `src/allCode/tools/approval.py`, `tools/executor.py`, `tools/diff.py`, `tui/terminal.py`, `tui/approval_panel.py`, `tui/renderers.py` | approval handler와 TTY test는 있음. diff preview는 문자열 중심이고 approval continuity/long diff UX는 부분 구현 수준. | approval request를 event와 interactive handler 양쪽에서 동일하게 보이게 하고, diff preview clipping/summary/session allow 결과를 transcript에 안정적으로 남김. |
| tool 사용 관찰성 | `src/allCode/tools/executor.py`, `tools/executor_evidence.py`, `telemetry/session_logger.py`, `tui/renderers.py`, `tui/streaming.py` | JSONL logging과 tool result 표준화는 있음. 사용자 화면에서는 긴 tool noise를 줄였지만 타임라인 품질은 더 다듬을 수 있음. | OpenHands식 action/observation 흐름을 user-visible timeline으로 축약하고, final answer가 사용한 evidence dependency를 로그에 남김. |
| 구조적 부채 방지 | `project_planner.py` 465 LOC, `finalization.py` 452 LOC, `source_answer_guard.py` 439 LOC, `workflow.py` 434 LOC, `source_answer_fallback.py` 408 LOC, `source_answer_synthesis.py` 406 LOC | 500줄 초과는 없지만 400줄대 파일 다수. | 다음 구현에서는 기존 400줄대 파일에 로직 추가 금지. helper/module extraction 선행. |

## Phase 1. Source Responsibility Synthesis 강화

목표:

- source 분석 답변을 fallback-like 구조에서 model-authored responsibility synthesis로 이동시킨다.
- Aider식 repo map의 "중요 심볼과 정의 라인" 원칙을 allCode의 `source_probe`
  body anchor와 internal edge에 결합한다.

수정 대상:

- 신규: `src/allCode/agent/source_responsibility_graph.py`
- 수정: `src/allCode/agent/source_answer_synthesis.py`
- 수정: `src/allCode/agent/source_analysis_rendering.py`
- 수정: `src/allCode/agent/source_final_brief.py`
- 수정: `src/allCode/agent/final_answer_context.py`
- 보강 테스트:
  - `tests/unit/agent/test_source_answer_synthesis.py`
  - `tests/unit/agent/test_source_answer_guard.py`
  - `tests/integration/test_readonly_source_analysis.py`
  - `tests/tty/test_terminal_readonly_source_analysis.py`

구현 계획:

1. `source_responsibility_graph.py`에 다음 구조를 추가한다.
   - `SourceResponsibilityNode(path, symbol, role_hint, body_anchors, signature_anchors, incoming_edges, outgoing_edges, confidence)`
   - `SourceResponsibilityGraph(nodes, entrypoints, flows, limitations)`
2. `source_probe` observation의 `observed_symbols`, `line_ranges`,
   `outgoing_edges`, `wide_symbols`를 graph로 정규화한다.
3. graph는 정적 심볼 정의, anchor, outgoing edge 정렬 metadata 제공에 한정한다.
   cycle detection, deep dynamic call graph, runtime tracing 같은 무거운 그래프
   알고리즘은 포함하지 않는다.
4. edge target은 다음 순서로 정렬한다.
   - repo 내부 resolved target
   - workspace 상대 파일 target
   - dotted symbol target
   - stdlib/외부 import target
5. `render_source_analysis_brief()`에 "Function responsibility matrix" 섹션을
   추가한다.
   - symbol
   - 관찰된 body anchor
   - 내부 edge
   - 추론 가능한 책임
   - 직접 관찰하지 못한 한계
6. final answer call의 compact observation summary에 graph를 우선 주입한다.
7. `source_answer_fallback.py`는 실패 시에만 사용하고, fallback answer에는
   `fallback_used` metadata/log를 남기는 계획을 둔다.

수용 기준:

- source 분석 prompt에서 최종 답변이 단순 "관찰한 사실 목록"만이 아니라 함수/모듈
  책임과 흐름을 연결한다.
- 답변에 raw tool JSON 또는 tool call plan이 노출되지 않는다.
- body anchor가 관찰된 경우 하나 이상을 핵심 책임 설명에 사용한다.
- body anchor가 없으면 한계로 분리하고 body-level claim을 만들지 않는다.

금지:

- 특정 파일명, 특정 함수명, 특정 prompt 문자열로 책임을 추론하지 않는다.
- fallback template만 더 길게 만들어 품질 향상처럼 보이게 하지 않는다.

## Phase 2. Session State Persistence와 Repair Continuity

목표:

- process restart 후에도 active obligations, latest repair context, source exploration
  ledger가 복원되게 한다.
- Gemini CLI의 계층 memory 원칙처럼 세션 시작 시 필요한 compact state를 자동 주입한다.

수정 대상:

- 신규: `src/allCode/memory/session_state_store.py`
- 수정: `src/allCode/agent/session_state.py`
- 수정: `src/allCode/agent/context.py`
- 수정: `src/allCode/agent/context_session_sections.py`
- 수정: `src/allCode/runtime.py`
- 수정: `src/allCode/memory/session_store.py`
- 보강 테스트:
  - `tests/unit/agent/test_session_state.py`
  - `tests/unit/memory/test_session_store.py`
  - `tests/unit/memory/test_project_obligations.py`
  - `tests/integration/test_followup_context_memory.py`

구현 계획:

1. `SessionStateSnapshot` 모델을 추가한다.
   - `session_id`
   - `active_project_obligations`
   - `latest_repair_context`
   - `source_exploration_ledger`
   - compact file freshness metadata: workspace-relative path, exists flag, mtime
   - `updated_at`
2. `AgentSessionState`에 `to_snapshot()`과 `load_snapshot()`을 추가한다.
3. `session_state_store.py`는 `.allCode/sessions/state/{session_id}.json`에
   `redact_data`를 통과한 redacted JSON으로 저장한다.
4. `runtime.make_tui_turn_runner()`와 `run_agent_turn()`에서 같은
   `ContextBuilder`가 있으면 기존 in-process state를 우선하고, 새 프로세스에서는
   snapshot을 로드한다.
5. `remember_turn_outcome()` 이후 snapshot을 저장한다.
6. `ContextBuilder._project_state_sections()`는 현재처럼 repair context를 가장 높은
   우선순위로 유지한다.
7. snapshot 로드 시 파일 존재 여부와 mtime을 확인한다.
   - 삭제되었거나 mtime이 달라진 repair target은 stale로 표시하고, routing context
     앞에 강제 주입하지 않는다.
   - stale 상태 자체는 compact limitation으로 남겨 모델이 같은 대상 반복 패치를
     피할 수 있게 한다.

수용 기준:

- 첫 프로세스에서 validation 실패 또는 partial turn 발생 후 세션 state snapshot이
  생성된다.
- 새 `ContextBuilder`/`AgentLoop` 인스턴스로 같은 `session_id`를 실행해도
  `repair_context`, `active_project_obligations`, `source_exploration_ledger`가
  context에 주입된다.
- secret redaction이 유지된다.
- workspace 밖 absolute path는 snapshot에 저장하지 않는다.

금지:

- 전체 transcript를 매 turn마다 그대로 prompt에 재주입하지 않는다.
- failed log 전체를 저장하지 않고, command 1개, target 3개, symbol 3개, excerpt
  1개 수준으로 제한한다.

## Phase 3. External Web Evidence 품질 강화

목표:

- live web backend가 설정된 경우 evidence synthesis 품질을 agy에 가깝게 끌어올린다.
- backend가 없는 경우에도 "웹 검색 불가"와 "모델의 일반 지식 답변"이 섞이지 않게
  사용자에게 명확히 설명한다.

수정 대상:

- 신규: `src/allCode/tools/web_health.py`
- 수정: `src/allCode/tools/web_provider.py`
- 수정: `src/allCode/tools/builtin/web.py`
- 수정: `src/allCode/agent/answer_prompt.py`
- 수정: `src/allCode/agent/final_answer_context.py`
- 수정: `src/allCode/agent/finalization.py`
- 수정: `src/allCode/config/schema.py`
- 보강 테스트:
  - `tests/unit/tools/test_web_provider.py`
  - `tests/unit/tools/test_web_tools.py`
  - `tests/unit/agent/test_answer_policy.py`
  - `tests/unit/agent/test_final_answer_context.py`

구현 계획:

1. `WebHealth` 모델을 추가한다.
   - `configured`
   - `backend`
   - `search_url_host`
   - `supports_json`
   - `last_error_type`
2. provider는 `health()` 또는 lightweight `preflight()` 계약을 선택적으로 구현한다.
3. `no_external_network`, offline mode, 사용자의 네트워크 차단 요청이 있는 경우에는
   preflight connection 자체를 수행하지 않고 fail-fast로 web unavailable evidence를
   만든다.
4. `web_search_unavailable` metadata에 설정 키, backend, host redacted 정보,
   user-actionable next step을 표준화한다.
5. final answer synthesis prompt는 다음을 분리한다.
   - evidence-backed claims
   - general/stable knowledge claims
   - web unavailable limitation
6. unstable/current question에서 evidence가 없으면 최신 수치/날짜/랭킹을 단정하지
   않도록 guard를 유지한다.

수용 기준:

- fake web provider의 evidence bundle이 최종 답변에 citation-like source label로
  반영된다.
- backend disabled 때는 raw 결과 없이 설정 안내와 답변 한계를 분리한다.
- `no external network` 또는 "검색 금지" 요청에서는 web tool이 노출되지 않는다.

금지:

- 특정 무료 public SearXNG instance를 기본값으로 하드코딩하지 않는다.
- preflight 대상 URL 또는 host를 코드 상수로 하드코딩하지 않는다. 오직 사용자 config
  또는 test-injected provider만 사용한다.
- web result raw JSON을 최종 답변으로 내보내지 않는다.

## Phase 4. Generation Density와 Report Artifact 보강

목표:

- agy 대비 부족했던 복잡 프로젝트 생성의 test/report 밀도를 높인다.
- 테스트 수를 직접 목표로 삼지 않고, prompt-derived obligations 대비 검증 가능한
  coverage를 높인다.

수정 대상:

- 신규: `src/allCode/agent/obligation_matrix.py`
- 신규: `src/allCode/agent/workflow_report_artifact.py`
- 수정: `src/allCode/agent/project_planner.py`
- 수정: `src/allCode/agent/task_loop_digest.py`
- 수정: `src/allCode/agent/workflow.py`
- 수정: `src/allCode/agent/completion_checker.py`
- 수정: `src/allCode/agent/final_reporter.py`
- 수정: `src/allCode/generation/strategies/python.py`
- 보강 테스트:
  - `tests/unit/agent/test_project_planner.py`
  - `tests/unit/agent/test_task_loop_digest.py`
  - `tests/unit/agent/test_final_reporter_language.py`
  - `tests/integration/test_generation_workflow.py`
  - `tests/unit/generation/test_strategy_paths.py`

구현 계획:

1. `ObligationMatrix`를 추가한다.
   - `source_obligations`
   - `test_obligations`
   - `doc_obligations`
   - `validation_obligations`
   - `coverage_status`
2. `ModelProjectPlanner`가 생성하는 `api_obligations`와 deterministic planner의
   artifact obligations를 matrix로 정규화한다.
3. `completion_checker`는 다음을 확인한다.
   - 각 주요 public API obligation이 최소 하나의 test artifact에서 참조됨
   - README/문서가 실제 parser/API와 drift 없음
   - final report가 matrix 상태와 validation 결과를 포함함
4. argparse AST 탐색이 실패하거나 custom wrapper로 인해 불완전하면 regex fallback을
   사용해 CLI usage 후보를 낮은 confidence로 추출한다. 낮은 confidence 후보는
   completion을 즉시 실패시키기보다 warning/repair hint로 먼저 제공한다.
5. prompt가 "보고서", "결과 정리", "report artifact"를 요구하면
   `workflow_report_artifact.py`가 별도 report file 생성을 계획에 추가한다.
   사용자가 명시적으로 문서 artifact를 요구하지 않은 경우에는 사용자 workspace root를
   오염시키지 않고 session artifact/log로만 보존한다.
6. `task_loop_digest`에는 현재 phase, 남은 obligation, 이전 repair reason을 더
   짧고 안정적으로 넣는다.

수용 기준:

- 복잡한 package CLI 생성 smoke에서 source/test/doc/report가 prompt-derived
  obligations와 연결된다.
- final report는 변경 파일, 핵심 기능, validation command/result, 남은 리스크,
  obligation coverage를 포함한다.
- validation 실패 후 repair가 matrix 미충족 항목을 우선 target으로 삼는다.

금지:

- 테스트 개수 10개 같은 숫자를 하드코딩하지 않는다.
- 특정 예제 프로젝트명 또는 taskhub 이름을 조건으로 쓰지 않는다.
- `6 passed`, `7 passed` 같은 stdout 문자열을 completion 조건으로 사용하지 않는다.
  validation은 exit code와 구조화된 `ValidationResult`/artifact 관계를 기준으로 한다.

## Phase 5. Approval, Diff Preview, Tool Timeline UX

목표:

- Claude Code/Codex류 terminal UX에 가까운 approval continuity와 diff readability를
  확보한다.
- OpenHands식 action/observation 구조를 사용자 화면에서는 축약 timeline으로 보여준다.

수정 대상:

- 신규: `src/allCode/tui/tool_timeline.py`
- 신규: `src/allCode/tools/approval_preview.py`
- 수정: `src/allCode/tools/approval.py`
- 수정: `src/allCode/tools/executor.py`
- 수정: `src/allCode/tools/diff.py`
- 수정: `src/allCode/tui/terminal.py`
- 수정: `src/allCode/tui/renderers.py`
- 수정: `src/allCode/tui/approval_panel.py`
- 보강 테스트:
  - `tests/unit/tools/test_tool_executor.py`
  - `tests/tty/test_tui_smoke.py`
  - `tests/tty/test_terminal_body_output.py`
  - `tests/tty/test_streaming_tables.py`

구현 계획:

1. `approval_preview.py`에서 diff preview를 통일한다.
   - file path
   - action
   - added/removed line count
   - clipped unified diff
   - 기본 clipping 상한: 최대 200줄 또는 10KB 중 먼저 도달하는 쪽
2. executor는 approval requested/resolved event에 preview summary와 action을
   표준 metadata로 넣는다.
3. terminal approval prompt는 body output을 준비한 뒤 preview를 보여주고, 입력 후
   반드시 running composer를 복구한다.
4. tool timeline renderer는 다음 형식으로 축약한다.
   - `• read src/... -> ok · 12 symbols`
   - `• patch src/... -> approval requested · medium risk`
   - `• validation pytest -> failed · 2 targets`
5. 긴 diff와 긴 tool output은 transcript 본문을 오염시키지 않고 foldable/summary
   형태 metadata로 남긴다.

수용 기준:

- ask mode에서 file mutation approval이 끊기지 않고 사용자 입력을 받아
  approve_once/deny/allow_session을 처리한다.
- approval denied는 final answer에서 "실행하지 않았음"과 이유를 명확히 말한다.
- read-only 요청은 approval/mutation 경로에 들어가지 않는다.

금지:

- TUI가 `AgentLoop`, `AgentSessionState` 같은 agent internals를 직접 import하지 않는다.
- tools/core 레이어는 `rich`, `textual`, terminal widget을 import하지 않는다. TUI는
  text/markdown metadata를 받아 렌더링만 담당한다.
- approval을 우회하거나 auto mode로 몰래 바꾸지 않는다.

## Phase 6. 구조적 부채 방지 리팩터링

목표:

- 500줄 초과를 방지하고, 다음 보강으로 400줄대 파일이 500줄을 넘지 않게 한다.

우선 분리 후보:

- `src/allCode/agent/project_planner.py`
  - artifact obligation detection을 `project_plan_obligations.py`로 분리
  - path/layout normalization을 `project_plan_normalization.py`로 분리
- `src/allCode/agent/finalization.py`
  - web unavailable/config/budget/schema wording을 `finalization_wording.py`로 분리
  - source answer retry/fallback glue는 기존 source modules로 이동
- `src/allCode/agent/source_answer_guard.py`
  - anchor parsing을 `source_anchor_guard.py`로 분리
  - body evidence requirement를 `source_body_evidence.py`로 분리
- `src/allCode/agent/workflow.py`
  - phase orchestration helper를 기존 `workflow_*` 모듈로 이동

검증:

```bash
find src/allCode -name '*.py' -print0 | xargs -0 wc -l | sort -nr | head -20
```

수용 기준:

- 500줄 이상 파일 0개.
- 새 파일도 단일 책임을 갖고 300줄 이하를 목표로 한다. 400줄은 절대 상한이다.
- public import/API 호환성은 유지한다.

## 검증 계획

단계별 집중 테스트:

```bash
python -m pytest tests/unit/agent/test_source_answer_synthesis.py tests/unit/agent/test_source_answer_guard.py tests/integration/test_readonly_source_analysis.py
python -m pytest tests/unit/memory/test_session_store.py tests/unit/agent/test_session_state.py tests/integration/test_followup_context_memory.py
python -m pytest tests/unit/tools/test_web_provider.py tests/unit/tools/test_web_tools.py tests/unit/agent/test_answer_policy.py tests/unit/agent/test_final_answer_context.py
python -m pytest tests/unit/agent/test_project_planner.py tests/unit/agent/test_final_reporter_language.py tests/integration/test_generation_workflow.py
python -m pytest tests/unit/tools/test_tool_executor.py tests/tty
```

확장 회귀:

```bash
python -m pytest tests/unit/agent tests/unit/tools tests/unit/memory tests/integration tests/quality tests/tty
python -m pytest
```

실제 동일 프롬프트 비교:

1. 복잡한 코드 분석:
   - "코드 수정은 엄격히 금지한다. src/allCode/agent와 src/allCode/tools의 라우팅,
     툴 실행, 최종 답변 생성 흐름을 실제 파일 근거 기준으로 깊게 분석해줘. 핵심
     함수 본문 근거, 모듈 간 호출 흐름, 병목 3개, 개선점 3개를 포함해줘."
2. 복잡한 프로젝트 생성:
   - `./output/parity_next_taskhub` 하위에 표준 라이브러리 Python package CLI,
     command registry, JSON store, retry/backoff, tests, README, 결과 report를
     요구한다.
3. 일반 지식/외부 지식:
   - 최신성이 없는 복잡 일반 질문은 no-tool direct answer.
   - 최신성이 있는 질문은 configured fake/real web backend로 web-only evidence route.
4. 멀티턴 repair:
   - 1턴에서 일부 validation 실패를 만들고, 새 프로세스/같은 session id에서 이어서
     수리하도록 한다.
5. approval:
   - ask mode에서 file mutation approval prompt가 입력을 기다리고 처리하는지 PTY로
     확인한다.

진척도 갱신:

- `plan/45_parity_progress_tracker.md`는 실제 테스트와 agy/allCode 동일 프롬프트
  비교 후에만 갱신한다.
- 95% 도달 판단은 다음을 모두 만족할 때만 기록한다.
  - 관련 pytest 통과
  - 실제 모델 smoke에서 답변 품질이 agy와 유사
  - 하드코딩 없이 prompt-derived obligations/observed evidence만 사용
  - MVP 계약과 provider-neutral 설계 유지

## 예상 리스크와 완화

- 모델별 편차: source responsibility graph는 deterministic evidence를 제공하되,
  최종 문장은 모델이 합성하게 한다. 모델 실패 시에만 fallback을 사용한다.
- web backend 안정성: public instance 기본값을 넣지 않고, fake provider unit test와
  설정된 real backend smoke를 분리한다.
- context 비대화: persisted session state는 compact snapshot만 주입하고 transcript
  전체 재주입은 금지한다.
- completion checker 과잉 차단: obligation matrix는 prompt-derived artifact와 실제
  observed file/test/doc 관계만 검사하고, 특정 용어 목록을 과도하게 늘리지 않는다.
- TUI 회귀: terminal-native 경로를 기본으로 유지하고 Textual은 event bridge 기준으로
  보조 검증한다.

## agy 검토 요청 전 초안 상태

이 문서는 Claude 리뷰와 현재 코드 기준으로 작성한 초안이다. 다음 절차로 agy 검토를
진행한다.

1. agy에 코드 수정 금지를 명시한다.
2. 이 계획이 현재 코드 구조에 적용 가능한지 검토받는다.
3. MVP 계약, 하드코딩 금지, provider-neutral/TUI-neutral 경계를 위반하는 제안은
   반영하지 않는다.
4. 타당한 피드백만 "agy 검토 반영" 섹션에 통합한다.

## agy 검토 반영

agy에 "코드 수정 금지, 계획 검토만" 조건으로 검토를 요청했다. 피드백 중 현재
MVP 계약과 충돌하지 않고, 하드코딩 없이 구현 가능한 항목을 다음과 같이 반영했다.

1. Phase 1에 `SourceResponsibilityGraph`의 범위를 경량 정적 graph metadata로 제한하는
   문장을 추가했다. cycle detection, runtime tracing, heavy call graph는 배제한다.
2. Phase 2에 session snapshot redaction, workspace-relative path 저장, mtime/exists
   기반 staleness 검증을 추가했다. stale repair target은 다음 턴에 강제 주입하지 않고
   limitation으로만 전달한다.
3. Phase 3에 offline/no-network 상태에서 web preflight를 건너뛰는 fail-fast 경로와,
   public search host 하드코딩 금지를 추가했다.
4. Phase 4에 argparse AST 실패 시 regex fallback을 낮은 confidence 후보로 처리하는
   계획을 추가했다. 또한 사용자가 report artifact를 명시하지 않은 경우 workspace root를
   오염시키지 않고 session artifact/log로만 보존하도록 범위를 좁혔다.
5. Phase 5에 diff preview clipping 상한(200줄 또는 10KB)과 tools/core 레이어의
   TUI dependency 금지 문장을 추가했다.

agy 피드백 중 MCP server manager, browser automation, vector RAG, public backend 기본값
지정처럼 MVP 범위를 넘을 수 있는 방향은 계획에 추가하지 않았다.
