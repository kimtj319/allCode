# 21. Open Source Parity 95% Hardening Plan

## 목적

이 문서는 최신 stress 결과와 `agy` 토론을 바탕으로 allCode를 오픈소스 CLI coding agent 대비 약 95% 완성도까지 끌어올리기 위한 후속 보강 계획서다.

현재 상태는 기능 실패는 거의 제거되었지만, 성숙한 공개 에이전트 수준으로 보기에는 다음 구조 리스크가 남아 있다.

- phase별 tool schema가 실행 단계에서 강제되지 않고 advisory로 동작한다.
- 큰 파일이 tool 호출 전에 active file context로 과다 주입될 수 있다.
- `AgentLoop`가 orchestration, model round, tool execution, recovery, finalization을 함께 처리한다.
- 하네스가 action lifecycle event를 모두 tool call로 계산해 실제 action 수와 warning 수가 어긋날 수 있다.
- session log가 충분히 쌓이지만, 사람이 바로 읽을 diagnostic summary가 부족하다.

이 계획의 목표는 새 제품 범위를 넓히는 것이 아니라, 현재 구현된 MVP를 오픈소스급 안정성, 수렴성, 관찰성 기준으로 조이는 것이다.

## 우선 참조 문서

구현 시작 전 다음 문서를 순서대로 다시 읽는다.

1. `plan/00_master_implementation_guide.md`
2. `plan/01_open_source_alignment_contracts.md`
3. `plan/04_llm_loop_plan.md`
4. `plan/06_tool_system_plan.md`
5. `plan/08_context_memory_plan.md`
6. `plan/09_generation_workflow_plan.md`
7. `plan/11_quality_testing_plan.md`
8. `plan/12_mvp_execution_plan.md`
9. `plan/18_open_source_agent_hardening_plan.md`
10. `plan/19_open_source_completion_gap_plan.md`
11. `plan/20_harness_agent_open_source_completion_plan.md`
12. 이 문서

충돌 시 `00`~`12`를 우선하고, 그 다음 `18`, `19`, `20`, `21` 순서로 최신 보강 계약을 적용한다.

## 최신 기준선

최신 실제 모델 stress 결과는 `output/evaluation_summary.json` 기준이다.

| 항목 | 값 |
|---|---:|
| 시나리오 수 | 22 |
| pass | 20 |
| warning | 2 |
| fail | 0 |
| 평균 점수 | 98.9 |
| 최저 기준 | 기준 9 Token/Cost Efficiency 85.0 |

남은 warning은 다음과 같다.

| 시나리오 | 점수 | 관찰 |
|---|---:|---|
| S009 Bug fix with validation | 91.0 | 하네스는 15 tool call로 기록했지만 실제로는 requested/started/finished lifecycle event가 중복 집계된다. 그래도 mutation-only 라운드에서 모델이 `run_tests`를 호출하면 policy가 허용하는 strict gate 결함이 남아 있다. |
| S012 Large context targeted search | 85.0 | `docs/huge_notes.txt`가 active file context로 먼저 주입되어 첫 model request가 커진다. 검색 결과는 맞지만 context cost가 크다. |

현재 코드 규모 리스크:

| 파일 | 줄 수 | 판단 |
|---|---:|---|
| `src/allCode/agent/loop.py` | 681 | 반드시 분리 |
| `src/allCode/tools/builtin/file_ops.py` | 417 | 분리 후보, range-first 책임 축소 필요 |
| `src/allCode/agent/tool_call_processor.py` | 288 | 유지 가능하지만 strict gate 입력이 필요 |

## agy 토론 요약

`agy`에 현재 코드 구조, 최신 stress 결과, 남은 리스크를 전달하고 95% parity 목표 기준으로 토론했다. 핵심 결론은 다음과 같다.

- `allowed_tools`는 모델 프롬프트와 schema 노출만 제어하므로, 실행 단계에서 별도 `phase gate`가 필요하다.
- validation repair phase에서는 `run_tests`를 숨기는 것만으로 충분하지 않다. 숨겨진 tool을 모델이 호출하면 `schema_denied` observation으로 차단해야 한다.
- S012의 진짜 병목은 `read_file` tool보다 `ContextBuilder`가 큰 active file 본문을 model request에 먼저 싣는 구조다.
- `AgentLoop`는 현재 변경을 계속 받을 수는 있지만, 오픈소스급 유지보수성 기준으로는 `RoundRunner`, `ToolOrchestrator`, `Finalizer`로 분리해야 한다.
- 하네스는 action event lifecycle을 이해하는 metric correction이 필요하다. 실제 tool action과 event 수를 구분해야 warning이 정확해진다.
- session log는 충분하지만 사용자와 개발자가 바로 볼 수 있는 `/status last`, `/debug last` 형태의 diagnostic summary가 필요하다.

## 목표 성숙도 산정 기준

95% parity는 절대 벤치마크가 아니라 현재 allCode 계획 문서의 공개 에이전트 참조 축을 기준으로 한 내부 완성도 목표다.

| 영역 | 현재 추정 | 95% 조건 |
|---|---:|---|
| Aider식 edit/test/fix 수렴 | 86% | validation repair phase가 schema gate와 함께 강제되고 S009 warning 제거 |
| Gemini/Qwen식 provider-neutral terminal workflow | 88% | prompt/context/tool 정책이 provider와 UI에 독립적으로 유지 |
| OpenHands식 action/event 관찰성 | 85% | session analyzer와 action lifecycle metric correction 구현 |
| 대형 repo context 효율 | 80% | 큰 파일 active context 금지, search/ranged read 우선 |
| 유지보수성/SRP | 72% | `loop.py` 350줄 이하, helper 순환 import 없음 |

완료 후 목표:

- 실제 모델 stress 평균 99.0 이상.
- warning 0 또는 warning 1 이하.
- 기준 9 Token/Cost Efficiency 92 이상.
- `loop.py` 350줄 이하.
- phase-hidden tool 호출은 실행되지 않고 `schema_denied` observation으로 남음.
- 큰 active file은 본문 대신 metadata context만 주입됨.

## P0. Strict Phase Tool Gate

### 문제

현재 `tool_schemas_for_routing()`이 특정 라운드에서 `write_file`, `patch_file`만 노출하더라도 모델이 `run_tests`를 직접 호출하면 `ToolPolicy`가 route capability 기준으로 허용할 수 있다. 이 구조는 schema가 advisory에 머물러 있다는 뜻이다.

### 수정 대상

```text
src/allCode/agent/tool_call_processor.py
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/loop.py
src/allCode/agent/validation_repair.py
src/allCode/agent/policy.py
src/allCode/core/events.py
tests/unit/agent/test_strict_phase_tool_gate.py
tests/integration/test_direct_edit_validation_repair.py
tests/quality/test_stress_regression_matrix.py
```

### 구현 계획

1. `PhaseToolGate` 모델을 추가한다.
   - `allowed_tool_names`
   - `phase`
   - `reason`
   - `deny_hidden_tools`
   - `mutation_required_before_validation`
2. `AgentLoop`가 매 round마다 `tool_schemas_for_routing()` 결과를 `ToolCallProcessor`에 전달한다.
3. `ToolCallProcessor`는 policy check 전에 `PhaseToolGate`를 먼저 적용한다.
4. hidden tool 호출은 실행하지 않고 `ToolResult(ok=False, error_type="schema_denied")`로 observation을 만든다.
5. `ToolCallSuppressed`와 별도로 `ToolCallSchemaDenied` event를 추가한다.
6. validation repair phase에서 mutation 전 `run_tests` 호출은 반드시 `schema_denied`가 된다.
7. schema denied observation은 다음 model message에 "현재 단계에서는 수정 tool을 사용해야 한다"는 짧은 지시로 들어간다.
8. read-only 요청에서 mutation tool이 hidden이면 policy denied가 아니라 schema denied로 기록해, routing/policy/security 원인을 구분한다.

### 수용 기준

- mutation-only 라운드에서 모델이 `run_tests`를 호출해도 실제 command가 실행되지 않는다.
- `ToolCallSchemaDenied` event와 `schema_denied` ToolResult가 session log에 남는다.
- S009에서 action lifecycle warning이 제거되거나 실제 action 기준으로 6회 이하가 된다.
- read-only security 정책은 기존대로 mutation 차단을 유지한다.

## P1. Large File Context Suppression

### 문제

S012에서 target file이 큰데도 `ContextBuilder`가 active file로 본문을 주입한다. 모델이 search tool을 올바르게 사용해도 첫 요청이 이미 비싸다.

### 수정 대상

```text
src/allCode/agent/context.py
src/allCode/agent/preflight.py
src/allCode/agent/prompt_builder.py
src/allCode/tools/builtin/file_ops.py
src/allCode/workspace/indexer.py
tests/unit/agent/test_context_builder_large_file.py
tests/unit/agent/test_preflight_large_file.py
tests/unit/tools/test_file_ops.py
tests/integration/test_followup_context_memory.py
tests/quality/test_stress_regression_matrix.py
```

### 구현 계획

1. `ContextBuilder`에 `large_file_bytes`와 `large_file_token_estimate` 기준을 둔다.
2. 큰 active file은 full content section 대신 metadata section으로 대체한다.
   - path
   - byte size
   - estimated tokens
   - line count
   - recommended action: `search_files` then ranged `read_file`
3. named target이 큰 파일이고 사용자가 특정 symbol/key/value를 찾는 경우 첫 model prompt에 "search first" constraint를 명시한다.
4. `PreflightPlanner`는 큰 target file에 대해 preflight `read_file`을 만들지 않는다.
5. `read_file(max_bytes=...)`만으로 큰 파일 range request로 간주하지 않는다. `start_line/end_line`이 없으면 preview 또는 metadata만 반환한다.
6. `search_files` result가 line number를 제공하면 다음 round의 suggested read target에 `start_line/end_line`을 포함한다.
7. context metrics event에 `large_file_suppressed=True`와 suppressed bytes/tokens를 기록한다.

### 수용 기준

- S012 첫 `model_request_prepared.message_chars`가 10,000 이하로 감소한다.
- `context_built`에 큰 파일 full content가 들어가지 않는다.
- `TARGET_SETTING` 같은 키 검색 요청은 `search_files -> ranged read_file 또는 final answer` 순서로 수렴한다.
- 작은 파일 active context 주입은 기존 동작을 유지한다.

## P2. AgentLoop SRP Split

### 문제

`loop.py`가 681줄이며, round 실행, recovery, tool gate, final answer policy, evidence merge를 모두 관리한다. 기능이 맞아도 회귀 위험이 크다.

### 수정 대상

```text
src/allCode/agent/loop.py
src/allCode/agent/round_runner.py
src/allCode/agent/round_state.py
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/finalization.py
src/allCode/agent/finalization_helpers.py
tests/unit/agent/test_round_runner.py
tests/unit/agent/test_tool_orchestrator.py
tests/unit/agent/test_finalization.py
```

### 구현 계획

1. `RoundRunner`를 신설한다.
   - model request prepared event
   - stream collection
   - response parsing
   - empty/reasoning/pseudo tool recovery
2. `ToolOrchestrator`를 보강한다.
   - phase gate 생성
   - observation cache
   - budget tracker
   - tool result to message 변환
3. `Finalizer` 또는 `TurnFinalizer`를 분리한다.
   - `LoopOutcome` to `TurnResult`
   - `CompletionEvidence` merge
   - final answer policy 적용
4. `loop.py`는 다음만 담당한다.
   - config/context/routing/preflight setup
   - workflow branch selection
   - component wiring
   - final `TurnResult` publish
5. helper가 `loop.py`를 import하지 않게 import 방향을 고정한다.
6. public API는 `AgentLoop.run_turn()`을 유지한다.

### 수용 기준

- `src/allCode/agent/loop.py` 350줄 이하.
- 신규 agent helper 파일 각각 500줄 이하.
- 순환 import 없음.
- 기존 전체 회귀 테스트 통과.

## P3. Session Diagnostics and Harness Metric Correction

### 문제

현재 하네스는 `tool_call_requested`, `tool_execution_started`, `tool_execution_finished`를 모두 tool call로 세는 경향이 있어 실제 action count보다 경고가 커진다. session log도 사람이 직접 읽어야 한다.

### 수정 대상

```text
output/evaluation_harness.py
src/allCode/telemetry/session_analyzer.py
src/allCode/tui/status_commands.py
src/allCode/tui/slash_commands.py
tests/unit/telemetry/test_session_analyzer.py
tests/quality/test_stress_regression_matrix.py
```

### 구현 계획

1. 하네스 metric을 event count와 logical action count로 분리한다.
2. logical action은 `tool_call_requested` 또는 normalized action id 기준으로 한 번만 센다.
3. `SessionAnalyzer`를 추가한다.
   - logical tool action count
   - repeated target count
   - schema denied count
   - suppressed/reused observation count
   - validation failure without mutation
   - request chars by round
   - large file suppressed stats
4. `/status last`는 사용자 친화 요약을 출력한다.
5. `/debug last`는 session analyzer의 raw diagnostic summary를 출력한다.
6. 실제 모델 stress는 계속 선택 실행으로 유지하되, fake replay regression은 일반 pytest에 포함한다.

### 수용 기준

- S009의 action count가 lifecycle event 중복 없이 산출된다.
- S012의 request char spike와 large-file suppression 여부를 analyzer가 보고한다.
- TUI slash command가 agent internals를 직접 import하지 않고 telemetry summary만 읽는다.

## P4. Completion and Safety Gate Tightening

### 문제

기존 completion gate는 많이 보강되었지만, 95% 목표에서는 no-op, approval-required, schema-denied, validation-failed 같은 상태가 success와 partial을 더 엄격히 구분해야 한다.

### 수정 대상

```text
src/allCode/agent/completion_gate.py
src/allCode/agent/turn_completion.py
src/allCode/agent/finalization.py
src/allCode/tools/builtin/file_ops.py
src/allCode/tools/builtin/shell.py
src/allCode/tools/approval.py
tests/unit/agent/test_completion_gate.py
tests/unit/agent/test_finalization.py
tests/integration/test_agent_failure_convergence.py
```

### 구현 계획

1. mutation-required 요청에서 `schema_denied`만 있고 change evidence가 없으면 success 금지.
2. validation-required 요청에서 validation failed 이후 mutation 없이 final answer가 오면 partial 또는 failed.
3. delete target이 이미 없는 경우에는 요청 의미가 "없으면 삭제하지 않아도 됨"으로 해석 가능한 경우에만 `safe_noop=True`.
4. approval-required 또는 approval-denied는 반드시 차단 이유와 안전 대안을 final answer에 포함한다.
5. final answer policy는 원문을 덮어쓰지 않고 필수 상태 문단을 append한다.

### 수용 기준

- 실제 변경/검증 근거 없는 구현 완료 success 없음.
- safe no-op은 metadata와 final answer 근거가 있을 때만 success.
- policy/approval/schema denial은 final answer에 상태가 명시된다.

## P5. Minimal Git-Native Workflow

### 범위 제한

이 단계는 Aider식 git/test/fix 흐름의 일부만 적용한다. 자동 commit, branch 관리, 원격 push, plugin, cloud sandbox는 범위 밖이다.

### 수정 대상

```text
src/allCode/workspace/git_state.py
src/allCode/tools/builtin/file_ops.py
src/allCode/agent/finalization.py
tests/unit/workspace/test_git_state.py
tests/integration/test_generation_workflow.py
```

### 구현 계획

1. workspace가 git repo인지 감지한다.
2. turn 시작 시 touched target의 pre-change git status를 기록한다.
3. final report에 changed files와 git dirty summary를 포함한다.
4. rollback은 기존 EditTransaction을 우선 사용하고, git checkout/reset은 사용하지 않는다.
5. 사용자가 명시하지 않은 commit/push는 수행하지 않는다.

### 수용 기준

- git repo에서 수정 후 final answer가 changed files와 dirty summary를 제공한다.
- destructive git command는 실행하지 않는다.
- non-git workspace에서는 조용히 비활성화된다.

## P6. Regression Matrix

### 수정 대상

```text
tests/quality/test_stress_regression_matrix.py
tests/integration/test_direct_edit_validation_repair.py
tests/integration/test_large_file_targeted_search.py
tests/unit/agent/test_strict_phase_tool_gate.py
tests/unit/agent/test_context_builder_large_file.py
```

### 구현 계획

1. S009를 fake replay로 고정한다.
   - validation failed
   - hidden `run_tests` attempt
   - schema denied
   - patch
   - revalidation pass
2. S012를 fake replay로 고정한다.
   - 큰 active file metadata only
   - first round request chars threshold
   - search first
3. S004 follow-up을 recent target + observation reuse 테스트로 고정한다.
4. S006 safety wording을 finalization unit test로 고정한다.
5. 실제 모델 하네스는 3회 반복 옵션을 둔다.

### 검증 명령

```bash
python -m py_compile $(find src/allCode -name '*.py' -print)
python -m pytest tests/unit/agent tests/unit/tools tests/unit/core tests/unit/telemetry
python -m pytest tests/integration/test_agent_failure_convergence.py tests/integration/test_agent_loop_context_validation.py tests/integration/test_direct_edit_validation_repair.py tests/integration/test_large_file_targeted_search.py
python -m pytest tests/quality tests/tty
python -m pytest tests/unit tests/integration tests/quality tests/tty
ALLCODE_RUN_REAL_MODEL_EVAL=1 .venv/bin/python output/evaluation_harness.py
```

## 구현 순서

1. P6의 fake regression skeleton을 먼저 추가한다.
2. P0 strict phase gate를 구현한다.
3. P1 large-file context suppression을 구현한다.
4. P2 `AgentLoop` SRP split을 수행한다.
5. P3 session analyzer와 harness metric correction을 구현한다.
6. P4 completion/safety gate를 보강한다.
7. P5 minimal git-native summary를 추가한다.
8. 전체 회귀 테스트와 실제 모델 stress를 실행한다.

이 순서에서 P2를 너무 먼저 수행하면 behavior change와 구조 변경이 섞인다. 먼저 P0/P1의 회귀 테스트와 동작을 고정한 뒤 구조 분리를 진행한다.

## 완료 기준

- `python -m pytest tests/unit tests/integration tests/quality tests/tty` 통과.
- 실제 모델 stress 결과 fail 0.
- warning 0 또는 1 이하.
- 평균 점수 99.0 이상.
- 기준 9 Token/Cost Efficiency 92 이상.
- `loop.py` 350줄 이하.
- 큰 active file full content prompt 주입 없음.
- hidden tool 실행 없음.
- session analyzer가 S009/S012 원인을 사람이 읽을 수 있게 요약.
- 특정 테스트 prompt, 특정 파일명, 특정 프로젝트명 하드코딩 없음.

## 남은 리스크와 완화책

| 리스크 | 설명 | 완화책 |
|---|---|---|
| strict gate 과차단 | 모델이 합리적인 validation을 조금 일찍 호출해도 차단될 수 있음 | phase state를 명확히 하고, mutation evidence가 생긴 직후 validation을 다시 노출한다 |
| large-file metadata만으로 답변 품질 저하 | 모델이 파일 본문 없이 답하려 할 수 있음 | final answer gate가 tool evidence 없이 targeted answer success를 금지한다 |
| loop split 회귀 | 구조 분리 중 기존 recovery edge case가 깨질 수 있음 | P6 fake replay를 먼저 추가하고 단계별로 regression 실행 |
| harness metric 변경으로 과거 점수 비교 어려움 | 기존 리포트와 새 리포트의 tool count 정의가 다름 | event count와 logical action count를 모두 기록한다 |
| git summary 범위 확장 위험 | git integration이 commit/push로 확장될 수 있음 | status summary만 구현하고 destructive git command 금지 |

## 다음 단계에서 반드시 참조할 내용

- `output/evaluation_report.md`의 S009, S012.
- `output/session_logs/2026/06/02/S009.jsonl`, `S012.jsonl`.
- `src/allCode/agent/loop.py`의 round 실행과 finalization 부분.
- `src/allCode/agent/tool_call_processor.py`의 policy check 순서.
- `src/allCode/agent/context.py`의 active file section 생성 로직.
- `src/allCode/tools/builtin/file_ops.py`의 large file read 처리.
