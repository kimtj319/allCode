# 20. Harness Agent Open-Source Completion Plan

## 목적

이 문서는 `19_open_source_completion_gap_plan.md` 이후 실제 모델 stress 재검증, 현재 코드 구조 분석, `agy --print` 토론 결과를 반영한 다음 보강 계획서다.

목표는 새 기능을 넓히는 것이 아니라, allCode가 CLI 환경의 coding agent이자 evaluation harness 대상 agent로 안정적으로 평가될 수 있도록 다음 영역을 완성하는 것이다.

- 검증 실패 후 실제 수정과 재검증으로 수렴하는 repair phase.
- 반복 tool 호출과 중복 context 소비를 줄이는 observation cache와 tool budget.
- 실패, 차단, partial 상태에서도 사용자가 이해할 수 있는 finalization gate.
- `AgentLoop`의 단일 책임 회복과 500줄 초과 구조 해소.
- stress harness를 정규 회귀 테스트와 session log 분석으로 고정.

## 적용 우선순위

이 계획은 아래 문서의 하위 보강 계약이다.

- `00_master_implementation_guide.md`: 단일 책임, 완료 근거, 테스트 실행, 파일 비대화 금지.
- `01_open_source_alignment_contracts.md`: Aider, Gemini CLI, Qwen Code, OpenHands 참조 계약.
- `04_llm_loop_plan.md`: recovery, final answer gate, timeout/retry, tool loop guard.
- `06_tool_system_plan.md`: ToolResult 표준화, EditTransaction, approval, destructive shell 차단.
- `08_context_memory_plan.md`: repo map, recent target, hierarchical memory, context compaction.
- `09_generation_workflow_plan.md`: validation/self-repair와 실제 변경 없는 완료 차단.
- `11_quality_testing_plan.md`: 품질 점수, prompt matrix, TTY/quality 회귀.
- `12_mvp_execution_plan.md`: CompletionEvidence, RecoveryState, ToolLoopSignature.
- `18_open_source_agent_hardening_plan.md`: OpenHands식 trace/stuck detector, Aider식 repo-map, Gemini/Qwen식 terminal workflow.
- `19_open_source_completion_gap_plan.md`: validation repair, preflight, no-op evidence, tool budget의 1차 보강.

충돌 시 `00`~`12`를 우선하고, 그다음 `18`, `19`, `20`을 최신 보강 계약으로 적용한다.

## 최신 평가 요약

최신 리포트는 `output/evaluation_report.md` 기준이다.

| 항목 | 값 |
|---|---:|
| 실행 일시 | 2026-06-02 13:56:00 KST |
| 모델 | `wisenut/wise-lloa-max-v1.2.1` |
| 시나리오 수 | 22 |
| 결과 | pass 18, warning 3, fail 1 |
| 평균 점수 | 97.0 |
| 최저 기준 | 기준 9 Token/Cost Efficiency 85.0 |

남은 fail/warning은 다음과 같다.

| 시나리오 | 상태 | 핵심 문제 | 우선 보강 |
|---|---|---|---|
| S004 Follow-up retention | warning | `read_file`/`search_files` 12회, 같은 파일 중복 읽기 | ObservationCache, ToolBudget, recent target reuse |
| S006 Path traversal boundary | warning | 정책 차단은 됐지만 답변에 `차단`, `워크스페이스` 안내 부족 | FinalAnswerPolicy wording gate |
| S009 Bug fix with validation | fail | 수정 요청인데 `patch_file`, `run_tests`가 관찰되지 않음 | ValidationRepairPhase, forced edit/test cycle |
| S012 Large context targeted search | warning | 큰 문서 중복 읽기 | range-first read, cached observation, budget gate |

## agy 토론 요약

`agy --print`에 현재 코드 구조, 최신 테스트 결과, 남은 리스크를 공유하고 오픈소스급 CLI coding agent 관점의 다음 수정을 토론했다. agy의 결론은 아래와 같다.

- S009는 단순 프롬프트 보강이 아니라 validation 실패 이후 phase를 코드가 강제해야 한다.
- `ValidationFailureSummary`를 만들고, 실패 직후에는 `run_tests`를 숨긴 뒤 `patch_file`/`write_file` 중심의 repair phase로 전환해야 한다.
- S004/S012는 모델 문제만이 아니라 harness 관점의 observation 재사용 부족이다. `ObservationCache`와 target 단위 `ToolBudgetTracker`가 필요하다.
- `loop.py`는 orchestration, model round, tool execution, finalization, wording gate가 섞여 있으므로 open-source급 유지보수성을 위해 분리해야 한다.
- final answer는 모델 문구에만 맡기지 말고 policy denied, path boundary, validation passed/failed, not found 같은 상태별 wording contract를 코드가 보장해야 한다.

## 오픈소스 정렬 근거

현재 계획은 `01_open_source_alignment_contracts.md`와 `18_open_source_agent_hardening_plan.md`의 범위 안에서만 공개 agent 패턴을 적용한다.

- Aider 계열: repo map은 class/function/signature 중심 compact context를 제공하고, 큰 repo에서는 token budget에 맞게 관련 부분만 선택한다. allCode는 `repo_map`, `repo_ranker`, ranged `read_file`을 연결해 full-file dump를 억제한다.
- Aider test/fix 흐름: 변경 뒤 lint/test를 실행하고 실패 output을 모델에게 다시 제공해 수정하게 한다. allCode는 이를 `ValidationRepairPhase`로 구조화한다.
- Gemini CLI 계열: hierarchical context file과 `/memory show`, `/memory refresh` 같은 사용자 가시성을 유지한다. allCode는 `ALLCODE.md`, session summary, recent target, durable memory를 분리해 prompt에 주입한다.
- Qwen Code 계열: terminal-first command registry, provider-neutral model provider 설정, tool/model/status slash command를 유지한다. allCode는 core를 provider SDK와 분리하고 command registry 기반 TUI/headless 명령을 유지한다.
- OpenHands 계열: Action/Observation event log와 stuck detector를 중심에 둔다. allCode는 `ToolCallRequested`, `ToolExecutionFinished`, `RecoveryState`, session JSONL을 더 엄격한 phase/budget 관찰성으로 연결한다.

## 현재 코드 기준 구조 리스크

현재 구조는 이미 여러 helper로 일부 분리되었지만 `src/allCode/agent/loop.py`가 다시 600줄을 넘는 상태다. 다음 구현은 기능 보강 전에 loop 책임 분리를 포함해야 한다.

현재 확인된 관련 파일:

```text
src/allCode/agent/loop.py
src/allCode/agent/tool_call_processor.py
src/allCode/agent/stream_collector.py
src/allCode/agent/finalization_helpers.py
src/allCode/agent/preflight.py
src/allCode/agent/validation_runner.py
src/allCode/agent/turn_completion.py
src/allCode/agent/recovery.py
src/allCode/agent/prompt_builder.py
src/allCode/tools/builtin/file_ops.py
src/allCode/telemetry/session_logger.py
```

새 보강은 이 구조를 깨지 않고 다음 모듈을 추가/정리하는 방식으로 진행한다.

```text
src/allCode/agent/round_runner.py
  - 모델 요청, stream 수집, parser 결과, retry/status event 조율

src/allCode/agent/tool_orchestrator.py
  - tool schema gating, ObservationCache, ToolBudgetTracker, ToolCallProcessor 연결

src/allCode/agent/validation_repair.py
  - ValidationFailureSummary, repair phase state, forced edit/test policy

src/allCode/agent/finalization.py
  - LoopOutcome/CompletionEvidence 기반 TurnResult, status별 wording gate
```

완료 기준:

- `src/allCode/agent/loop.py`는 350줄 이하로 줄인다.
- 새 agent 모듈은 각각 300줄 이하를 목표로 하며, 500줄을 넘기지 않는다.
- `AgentLoop` public constructor와 `run_turn` 호출 계약은 유지한다.
- core 모델은 provider/TUI를 import하지 않는다.

## P0. S009 제거: ValidationRepairPhase

### 문제

S009는 기존 파일 수정 요청인데 모델이 `read_file`만 반복하고 `patch_file`, `run_tests`로 가지 않았다. 이는 답변 문구 문제가 아니라 loop phase 제어 문제다.

### 수정 대상

```text
src/allCode/agent/validation_repair.py
src/allCode/agent/validation_runner.py
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/round_runner.py
src/allCode/agent/prompt_builder.py
src/allCode/agent/turn_completion.py
src/allCode/agent/finalization.py
tests/unit/agent/test_validation_repair.py
tests/integration/test_direct_edit_validation_repair.py
tests/integration/test_agent_loop_context_validation.py
```

### 구현 계획

1. `ValidationFailureSummary` 모델을 추가한다.
   - `command`
   - `returncode`
   - `failed_files`
   - `failing_symbols`
   - `traceback_excerpt`
   - `assertion_excerpt`
   - `suggested_read_targets`
   - `error_hash`
2. `ValidationRunner`는 raw log만 넘기지 말고 summary를 `ToolResult.metadata["validation_failure"]`에 저장한다.
3. `RepairPhaseState`를 둔다.
   - `normal`
   - `validation_failed`
   - `repair_required`
   - `mutation_done`
   - `revalidation_required`
   - `repair_exhausted`
4. validation 실패 직후 파일 변경 evidence가 없으면 다음 라운드에서 같은 `run_tests` schema를 숨긴다.
5. repair phase에서 허용 tool은 `read_file`, `search_files`, `patch_file`, `write_file` 중심으로 제한한다.
6. 이미 target file을 읽었고 같은 파일을 다시 읽으려 하면 cached observation을 제공하고 mutation tool을 요구한다.
7. provider가 tool choice 강제를 지원하면 `patch_file` 또는 `write_file`을 우선 강제한다.
8. provider가 tool choice를 지원하지 않으면 diff-only repair prompt를 사용하고, parser가 unified diff를 `patch_file` transaction으로 변환한다.
9. mutation evidence가 생긴 뒤에만 `run_tests`를 다시 노출한다.
10. repair attempt는 기본 2회로 제한한다.
11. attempt를 모두 써도 수정이 없으면 success가 아니라 `failed` 또는 `partial`로 종료하고 실패 command, 실패 요약, 시도한 파일을 답변에 포함한다.

### 수용 기준

- S009에서 `read_file/search_files -> patch_file/write_file -> run_tests` 흐름이 관찰된다.
- validation-required 요청은 `validation_passed=True` 없이는 success가 될 수 없다.
- final answer에는 `pytest` 같은 실행 command와 `통과` 또는 실패 원인이 포함된다.
- 특정 파일명, 특정 프로젝트명, 특정 테스트 prompt를 하드코딩하지 않는다.

## P1. S004/S012 제거: ObservationCache와 ToolBudgetTracker

### 문제

현재 모델이 같은 파일과 같은 검색 질의를 반복해도 loop가 매번 실제 tool을 실행한다. large context와 follow-up 시나리오에서 비용 점수가 떨어진다.

### 수정 대상

```text
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/tool_call_processor.py
src/allCode/agent/recovery.py
src/allCode/tools/builtin/file_ops.py
src/allCode/tools/builtin/search.py
src/allCode/core/events.py
tests/unit/agent/test_tool_orchestrator.py
tests/unit/agent/test_recovery.py
tests/unit/tools/test_file_ops.py
tests/integration/test_followup_context_memory.py
tests/quality/test_stress_regression_matrix.py
```

### 구현 계획

1. `ObservationCache`를 turn/session scoped로 구현한다.
2. cache key는 다음 값으로 만든다.
   - tool name
   - normalized workspace path
   - `start_line`, `end_line`, `max_bytes`
   - search query hash
   - file content hash 또는 mtime/size snapshot
3. `patch_file`, `write_file`, `delete_path` 성공 시 관련 file/path cache를 무효화한다.
4. cache hit 시 실제 tool 실행 대신 `ToolObservationReused` 또는 `ToolCallSuppressed` event를 남긴다.
5. 모델에게는 이전 observation의 짧은 summary와 “이미 확인한 대상”이라는 synthetic observation을 제공한다.
6. `ToolBudgetTracker`를 추가한다.
   - 같은 target full `read_file`: turn당 1회.
   - 같은 target ranged `read_file`: 서로 다른 range만 허용.
   - 같은 query `search_files`: turn당 1회, follow-up에서는 recent target 우선.
   - repair phase에서는 mutation 전 validation 반복 금지.
7. budget 초과 시 무조건 종료하지 말고 phase에 따라 다음 행동을 강제한다.
   - inspect phase: final answer 또는 clarification.
   - repair phase: mutation tool.
   - validation phase: failure summary.

### 수용 기준

- S004의 tool call count가 10회 미만으로 줄고 같은 `read_file` target 중복 경고가 없어야 한다.
- S012에서 큰 파일 전체를 반복 읽지 않는다.
- 정상적인 다른 range read나 다른 query search는 budget에 의해 오탐 차단되지 않는다.

## P2. S006 제거: FinalAnswerPolicy와 Wording Gate

### 문제

정책/경계 차단 자체는 동작하지만, 사용자 답변에서 차단 이유와 워크스페이스 경계가 명확하지 않아 warning이 남는다.

### 수정 대상

```text
src/allCode/agent/finalization.py
src/allCode/agent/finalization_helpers.py
src/allCode/agent/turn_completion.py
src/allCode/agent/completion_gate.py
src/allCode/tools/approval.py
tests/unit/agent/test_finalization.py
tests/integration/test_agent_failure_convergence.py
```

### 구현 계획

1. `FinalAnswerPolicy`를 추가한다.
2. final answer는 모델 답변을 그대로 반환하기 전에 `CompletionEvidence`, `RecoveryState`, policy/tool observations를 검사한다.
3. 상태별 필수 문구를 코드가 보장한다.
   - workspace/path boundary: `차단`, `워크스페이스`, 안전한 대안.
   - destructive command denied: `위험`, `승인`, `차단`.
   - validation passed: 실행 command, `통과`.
   - validation failed: 실행 command, 실패 요약, 다음 수정 필요.
   - not found: 대상 path와 찾지 못했다는 설명.
   - evidence missing: 완료가 아니라 추가 확인 또는 partial.
4. 문구 보강은 하드코딩된 시나리오명이 아니라 상태와 event type을 기준으로 한다.
5. headless와 TUI가 같은 `TurnResult.final_answer`를 사용하도록 통합한다.

### 수용 기준

- S006 답변에 `차단`과 `워크스페이스`가 포함된다.
- policy denied 또는 approval required가 빈 성공 답변으로 끝나지 않는다.
- finalization module만 문구 gate를 담당하고 router/tool executor는 답변을 생성하지 않는다.

## P3. Loop SRP Refactor

### 문제

기능이 추가될수록 `AgentLoop`가 model round, tool schema, recovery, finalization, telemetry를 모두 처리하고 있다. 이 상태에서는 평가 harness에서 발견된 특정 결함을 고쳐도 회귀 위험이 높다.

### 수정 대상

```text
src/allCode/agent/loop.py
src/allCode/agent/round_runner.py
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/validation_repair.py
src/allCode/agent/finalization.py
tests/unit/agent/test_round_runner.py
tests/unit/agent/test_tool_orchestrator.py
tests/unit/agent/test_finalization.py
```

### 구현 계획

1. `AgentLoop.run_turn()`은 turn setup, component wiring, 최종 `TurnResult` 반환만 담당한다.
2. `RoundRunner`는 다음 책임만 가진다.
   - model request 준비.
   - stream collector 호출.
   - parser 결과 분기.
   - timeout/retry/status event 발행.
3. `ToolOrchestrator`는 다음 책임만 가진다.
   - phase에 맞는 tool schema 선택.
   - tool call 정규화.
   - cache/budget 검사.
   - `ToolCallProcessor` 호출.
   - observations를 next model messages로 변환.
4. `ValidationRepairController`는 validation 실패 이후 phase 전환과 schema gating hint를 제공한다.
5. `Finalization`은 model answer, evidence, recovery state를 `TurnResult`로 변환한다.
6. 분리 후 import 방향은 `loop -> helpers`, `helpers -> core/tools`이고 helper가 `loop`를 import하지 않는다.

### 수용 기준

- `loop.py` 350줄 이하.
- 순환 import 없음.
- 기존 public API 유지.
- 기존 unit/integration/quality/tty 테스트 통과.

## P4. Stress Harness 정규화와 Session Diagnostic

### 문제

실제 모델 평가 결과는 `output`에 남지만, fail/warning 원인을 코드 변경마다 빠르게 재현하려면 fake replay와 session log analyzer가 필요하다.

### 수정 대상

```text
output/evaluation_harness.py
tests/quality/test_stress_regression_matrix.py
src/allCode/telemetry/session_analyzer.py
src/allCode/tui/status_commands.py
tests/unit/telemetry/test_session_analyzer.py
```

### 구현 계획

1. stress scenario 정의를 테스트 재사용 가능한 data fixture로 분리한다.
2. S004/S006/S009/S012를 fake LLM 회귀로 고정한다.
3. 실제 모델 평가는 `ALLCODE_RUN_REAL_MODEL_EVAL=1`일 때만 실행한다.
4. `SessionAnalyzer`를 추가한다.
   - repeated tool target.
   - reasoning-only retry.
   - validation failure without mutation.
   - hidden schema/budget suppression event.
   - token/char estimate summary.
5. `/status last` 또는 headless diagnostic report에서 마지막 turn의 phase, tool count, suppressed calls, final gate reason을 볼 수 있게 한다.

### 수용 기준

- 일반 pytest에서 실제 모델/API 없이 남은 fail/warning 유형을 재현한다.
- 실제 모델 stress는 선택 실행이며 결과 summary를 markdown/json으로 남긴다.
- session log만으로 “왜 답변이 멈췄는지”, “왜 tool이 숨겨졌는지”를 추적할 수 있다.

## 구현 순서

1. `AgentLoop` 책임 분리 scaffold를 먼저 만든다.
2. `ValidationFailureSummary`와 `ValidationRepairPhase`를 구현한다.
3. repair phase schema gating과 diff-to-patch fallback을 연결한다.
4. `ObservationCache`와 `ToolBudgetTracker`를 `ToolOrchestrator`에 붙인다.
5. `FinalAnswerPolicy`를 추가해 S006과 validation wording을 고정한다.
6. stress regression fake tests와 session analyzer를 추가한다.
7. 실제 모델 stress를 이전과 동일하게 다시 실행한다.

## 검증 명령

문서 계획을 구현한 뒤 다음 순서로 검증한다.

```bash
python -m py_compile $(find src/allCode -name '*.py' -print)
python -m pytest tests/unit/agent tests/unit/tools tests/unit/core
python -m pytest tests/integration/test_agent_failure_convergence.py tests/integration/test_agent_loop_context_validation.py tests/integration/test_direct_edit_validation_repair.py
python -m pytest tests/quality tests/tty
python -m pytest tests/unit tests/integration tests/quality tests/tty
ALLCODE_RUN_REAL_MODEL_EVAL=1 python output/evaluation_harness.py
```

실제 모델 평가에는 `.env`의 `NEWCLI_API_KEY` 또는 `ALLCODE_API_KEY`, `NEWCLI_MODEL`, `NEWCLI_BASE_URL` 설정을 사용한다. secret 값은 로그와 plan 문서에 기록하지 않는다.

## 최종 완료 기준

- 실제 모델 stress 결과 fail 0.
- warning 2 이하.
- 평균 점수 98.0 이상.
- 기준 9 Token/Cost Efficiency 90점 이상.
- S009는 3회 반복 실행에서 모두 `patch_file/write_file`과 `run_tests`를 관찰한다.
- `loop.py` 350줄 이하, 새 파일 500줄 이하.
- 특정 테스트 prompt, 특정 파일명, 특정 프로젝트명 하드코딩 없음.
- provider SDK가 core에 직접 결합되지 않음.
- validation-required 요청은 검증 근거 없이 success가 될 수 없음.

## 남은 리스크와 완화책

| 리스크 | 설명 | 완화책 |
|---|---|---|
| budget 오탐 | 복잡한 디버깅에서 같은 파일을 여러 range로 읽어야 할 수 있음 | range와 content hash를 key에 포함하고 phase별 budget을 다르게 둔다 |
| forced repair 과잉 | 모델이 아직 충분히 이해하지 못했는데 mutation을 강제할 수 있음 | read/search 최소 1회 이후에만 mutation gate를 적용한다 |
| diff parser 위험 | provider가 native tool call을 실패하면 텍스트 diff를 patch로 변환해야 함 | EditTransaction preview, workspace path 검증, validation 후 evidence 기록 |
| 실제 모델 비결정성 | 같은 prompt라도 tool call이 달라질 수 있음 | fake replay 테스트와 실제 모델 3회 반복 기준을 분리한다 |
| final wording 과도한 개입 | 모델의 자연스러운 답변을 망칠 수 있음 | 필수 상태 문구만 append/repair하고 일반 답변 내용은 유지한다 |

## 다음 단계에서 반드시 참조할 내용

- 구현 시작 전 `plan/00_master_implementation_guide.md`, `plan/01_open_source_alignment_contracts.md`, `plan/18_open_source_agent_hardening_plan.md`, `plan/19_open_source_completion_gap_plan.md`, 이 문서를 순서대로 다시 읽는다.
- `output/evaluation_report.md`의 S004, S006, S009, S012 로그를 먼저 재확인한다.
- 보강 구현은 코드 추가보다 `AgentLoop` 책임 분리를 먼저 완료한다.
- 완료 보고 시 생성/수정 파일, 실행 테스트, 실제 stress 결과, 남은 리스크, 다음 단계 참조 사항을 반드시 포함한다.
