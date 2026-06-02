# 24. Open Source CLI Agent 90 Plus Plan

## 목적

이 문서는 현재 allCode 코드를 기준으로, 오픈소스 CLI coding agent 대비
90% 이상의 구현도를 달성하기 위한 보강 계획서다.

목표는 MVP 범위를 임의로 넓히는 것이 아니다. 이미 구현된
provider-neutral LLM adapter, model-owned routing, tool system, workspace
context, memory, validation/self-repair, terminal UI, session telemetry를
더 안정적으로 수렴시키고, 실제 모델 stress에서 반복적으로 드러난 실패를
줄이는 데 초점을 둔다.

## 참조 우선순위

이 문서는 아래 구현 계약의 하위 보강 계획이다.

1. `plan/00_master_implementation_guide.md`
2. `plan/01_open_source_alignment_contracts.md`
3. `plan/04_llm_loop_plan.md`
4. `plan/05_routing_policy_plan.md`
5. `plan/06_tool_system_plan.md`
6. `plan/07_workspace_context_plan.md`
7. `plan/08_context_memory_plan.md`
8. `plan/09_generation_workflow_plan.md`
9. `plan/11_quality_testing_plan.md`
10. `plan/12_mvp_execution_plan.md`
11. `plan/19_open_source_completion_gap_plan.md`
12. `plan/20_harness_agent_open_source_completion_plan.md`
13. `plan/21_open_source_parity_95_hardening_plan.md`
14. `plan/22_remaining_risk_agy_discussion_hardening_plan.md`
15. `plan/23_open_source_parity_90_discussion_plan.md`
16. 이 문서

충돌 시 `plan/00`~`plan/12`를 우선한다. 설계가 모호하면
`plan/01_open_source_alignment_contracts.md`를 우선 적용한다.

## agy 토론 조건

agy에는 아래 조건으로 read-only 코드 토론을 요청했다.

- 파일 생성, 수정, 삭제 금지
- pytest, evaluation harness, curl, network check, git command 실행 금지
- 현재 코드 구조와 hotspot 기반 분석만 수행
- Aider, Gemini CLI, Qwen Code, OpenHands, Codex-style terminal UX와 비교
- 실제 모델 테스트는 샌드박스 외부에서만 수행한다는 제약 반영
- 특정 시나리오 ID, 특정 프롬프트, 특정 프로젝트명을 하드코딩하지 않음

agy가 지적한 핵심 병목은 다음과 같다.

1. 세션 단위 observation cache와 tool budget이 turn 간에 충분히 이어지지 않는다.
2. validation repair가 명시적 상태머신이 아니라 `round_runner.py`의 boolean flag 조합에 의존한다.
3. 생성 workflow 이후 follow-up에서 project root, entrypoint, validation cwd를 잃는다.
4. no-result, not-found, validation exception symbol이 최종 답변에 일관되게 보존되지 않는다.
5. 위험 명령 거부 뒤 안전한 대안 tool 선택이 충분히 구조화되어 있지 않다.
6. `round_runner.py`, `file_ops.py`, `tool_call_processor.py`가 현재 책임 대비 크다.

## 현재 기준선

현재 신뢰 가능한 기준선은 마지막으로 endpoint가 정상일 때 수행한 전체
real-model stress 결과다.

| 항목 | 값 |
|---|---:|
| 시나리오 수 | 34 |
| pass | 23 |
| warning | 7 |
| fail | 4 |
| 평균 점수 | 94.9 |
| 오픈소스 CLI coding agent 대비 추정 구현도 | 82.2% |

그 이후 `output/evaluation_summary.json`이 6개 시나리오 retry 결과로
덮였지만, 해당 결과는 endpoint `ConnectError`로 인한 연결성 실패다. 따라서
agent 품질 기준선으로 사용하지 않는다.

최신 로컬 회귀 기준은 다음과 같다.

```bash
.venv/bin/python -m pytest tests/unit tests/integration tests/quality tests/tty -q
```

결과:

```text
261 passed
```

현재 hotspot은 다음 파일이다.

| 파일 | 줄 수 | 문제 |
|---|---:|---|
| `src/allCode/agent/round_runner.py` | 647 | round orchestration, phase gate, validation repair, parser recovery, finalization 책임 집중 |
| `src/allCode/tools/builtin/file_ops.py` | 417 | read/write/patch/delete 구현 집중 |
| `src/allCode/agent/tool_call_processor.py` | 393 | schema gate, budget, cache, approval, execution, evidence recording 집중 |
| `src/allCode/agent/loop.py` | 366 | turn assembly와 fallback 일부 집중 |
| `src/allCode/llm/response_parser.py` | 346 | parser와 recovery hook 집중 |

## 90% 이상 달성 기준

90% 이상 구현도는 단순 체감 수치가 아니라 아래 기준을 동시에 만족해야 한다.

1. 전체 로컬 회귀 테스트가 통과한다.
   - `python -m pytest`
2. 샌드박스 외부 real-model stress 34개 이상 시나리오에서 아래 기준을 넘는다.
   - fail <= 1
   - warning <= 3
   - average score >= 96
   - estimated open-source parity >= 90
3. Loop Execution & Convergence >= 90
4. Response Quality Audit >= 90
5. Token & Cost Efficiency >= 90
6. validation-required 구현/수정 요청은 변경 근거와 검증 근거 없이 success가 되지 않는다.
7. 특정 테스트 프롬프트, 특정 시나리오 ID, 특정 프로젝트명을 source code에 하드코딩하지 않는다.
8. 500줄 초과 또는 책임 과밀 파일은 분리 계획이 있거나 실제로 분리되어야 한다.

## 구현 원칙

- routing은 모델이 담당한다. 키워드 기반 라우팅은 안전 가드, evidence 보정,
  capability 제한에만 사용한다.
- fallback은 사용자 요청과 tool evidence에서 파생되어야 한다.
- `core`는 provider/TUI 독립을 유지한다.
- tool result와 event는 core 표준 모델을 사용한다.
- file mutation은 tool execution과 edit transaction evidence를 통해서만 수행한다.
- 실제 변경/검증 근거가 없으면 완료 답변을 반환하지 않는다.
- web search가 실패하면 raw error가 아니라 evidence bundle로 최종 답변에 반영한다.
- 샌드박스 네트워크 실패를 agent 품질 실패로 기록하지 않는다.

## P0. Real-Model 평가 안정화와 결과 보존

### 문제

샌드박스 안에서는 네트워킹이 불가능하거나 불안정하다. endpoint 장애 시
6개 retry 결과가 기존 전체 stress summary를 덮으면 실제 agent 품질과
연결성 실패가 섞인다.

### 수정 대상

```text
output/evaluation_harness.py
src/allCode/telemetry/session_analyzer.py
src/allCode/telemetry/session_logger.py
docs 또는 README의 real-model test 절차
```

### 구현 계획

1. real-model 평가 시작 전 connectivity preflight를 분리한다.
   - `/v1/models` 확인
   - minimal `/chat/completions` 확인
   - 실패 시 본 평가를 시작하지 않는다.
2. preflight 실패 결과는 `output/connectivity_check.json` 또는
   `output/evaluation_attempts/{timestamp}/connectivity.json`에 기록한다.
3. preflight 실패만으로 `output/evaluation_summary.json`을 덮지 않는다.
4. stress summary에는 `quality_run=true`, `connectivity_only=false` 같은
   metadata를 기록한다.
5. session analyzer는 아래 카운트를 분리한다.
   - `model_requested_tools`
   - `executed_tools`
   - `reused_observations`
   - `suppressed_tools`
   - `policy_denied_tools`
   - `schema_denied_tools`
6. 평가 하네스는 실제 실행된 tool만 duplicate execution으로 본다.
   재사용/차단 이벤트는 별도 효율성 지표로 기록한다.

### 샌드박스 외부 실행 방식

Codex 세션에서 실제 테스트가 필요하면 승인된 unsandboxed command로 실행한다.
프로젝트 설정 계층은 `.env`를 자동 로드하므로 `source .env`를 필수 단계로
만들지 않는다. CI 또는 별도 shell에서 자동 로딩을 쓰지 못하는 경우에만
`ALLCODE_` 변수들을 직접 export한다.

```bash
.venv/bin/python output/evaluation_harness.py
```

또는 특정 실패 후보만 먼저 검증한다.

```bash
EVALUATION_SCENARIOS="S012,S016,S019,S025,S026,S028,S029,S030,S031,S032,S034" \
  .venv/bin/python output/evaluation_harness.py
```

### 수용 기준

- endpoint `ConnectError`가 전체 quality summary를 덮지 않는다.
- full stress 결과와 connectivity 실패 결과가 명확히 분리된다.
- duplicate tool penalty가 실제 재실행과 observation reuse를 구분한다.

## P1. Session-Level Observation Cache와 Tool Budget 유지

### 문제

현재 `runtime.run_agent_turn()`은 turn마다 `AgentLoop`를 새로 만들지만,
Textual/terminal runner는 `ContextBuilder`를 공유한다. 이 구조를 활용하면
세션 단위 cache와 budget을 `ContextBuilder` 또는 별도 session runtime state에
보관할 수 있다. 현재는 turn 간 read/search observation reuse가 안정적으로
보장되지 않아 multi-turn에서 같은 파일을 다시 읽는 경향이 남는다.

### 수정 대상

```text
src/allCode/agent/context.py
src/allCode/agent/loop.py
src/allCode/agent/tool_call_processor.py
src/allCode/agent/tool_orchestrator.py
src/allCode/telemetry/session_analyzer.py
tests/unit/agent/test_tool_orchestrator.py
tests/integration/test_followup_context_memory.py
tests/quality 또는 output harness 관련 테스트
```

### 구현 계획

1. `ContextBuilder` 또는 신규 `AgentSessionState`에 아래 객체를 둔다.
   - `ObservationCache`
   - `ToolBudgetTracker`
   - `ToolActionLedger`
2. `AgentLoop.__init__()`은 외부 session state가 있으면 이를 사용한다.
3. mutation tool 성공 시 touched file 기준으로 cache를 무효화한다.
4. budget은 target 단위로 유지하되, mutation 이후 해당 target budget은
   재검증 읽기가 가능하도록 완화한다.
5. cached observation은 모델에게 충분한 content/detail을 제공하되, telemetry에서는
   `tool_observation_reused`로 기록한다.
6. `state.tool_calls`에는 실제 실행된 tool만 넣는다.
7. suppressed/reused/denied action은 `ToolActionLedger`와 event에만 남긴다.

### 수용 기준

- 같은 세션의 follow-up에서 동일 read-only target을 반복 실행하지 않는다.
- 평가 하네스에서 repeated read warning이 감소한다.
- mutation 후에는 stale cache를 사용하지 않는다.

## P2. Validation Repair State Machine 분리

### 문제

`round_runner.py`는 현재 647줄이고, round 실행, parser recovery, phase gate,
tool processing, validation fallback, finalization을 함께 담당한다.
validation-required 요청에서는 `수정 -> 검증 -> 실패 분석 -> 재수정 -> 재검증`
순서가 보장되어야 하지만, boolean flag 조합만으로는 수렴성이 약하다.

### 수정 대상

```text
src/allCode/agent/round_state.py              # 신규
src/allCode/agent/validation_controller.py    # 신규
src/allCode/agent/parser_recovery.py          # 신규 분리 후보
src/allCode/agent/finalization_controller.py  # 신규 분리 후보
src/allCode/agent/round_runner.py
src/allCode/agent/phase_gate.py
src/allCode/agent/validation_repair.py
src/allCode/agent/completion_gate.py
src/allCode/core/events.py
tests/unit/agent/test_validation_controller.py
tests/unit/agent/test_phase_gate.py
tests/integration/test_generation_workflow.py
```

### 구현 계획

1. `RoundStateSnapshot`을 만든다.
   - `round_index`
   - `phase`
   - `last_action_kind`
   - `mutation_since_last_validation`
   - `validation_attempts`
   - `repair_attempts`
   - `last_validation_status`
   - `required_next_action`
2. `ValidationRepairController`를 만든다.
   - 입력: routing decision, completion evidence, latest tool results, round state
   - 출력: allowed tool bundle, prompt constraint, deterministic fallback action
3. validation-required 요청에서 file change evidence가 있고 validation command가
   없으면 `validation_required` phase로 전환한다.
4. validation failure 후 repair mutation이 없으면 같은 validation command 반복을 막고
   `repair_mutation_required`로 전환한다.
5. repair mutation 이후에는 `revalidation_required`로 전환한다.
6. repair attempt는 기본 2회로 제한한다.
7. 마지막 round 근처에서 validation action이 필요한데 모델이 호출하지 않으면
   deterministic validation action을 삽입한다.
8. deterministic action 삽입은 이벤트로 남긴다.
   - `phase_transitioned`
   - `validation_action_injected`
   - `repair_attempt_exhausted`
9. repair exhausted 상태에서는 success가 아니라 partial/failure final answer를 낸다.

### 수용 기준

- validation-required 구현 요청이 validation 없이 완료되지 않는다.
- validation failure가 발생하면 실패 원인 분석 후 재수정 또는 명확한 partial failure로 종료한다.
- 동일 validation command만 반복하는 루프가 없다.
- `round_runner.py`는 orchestration 중심으로 축소된다.

## P3. Generated Project Manifest와 Follow-Up Resolver

### 문제

신규 프로젝트 생성 후 후속 요청이 들어오면 생성된 root, package root,
entrypoint, test path, validation cwd를 잃을 수 있다. Gemini CLI의
hierarchical memory 개념을 allCode 범위에 맞게 적용하려면 durable memory가
아니라 세션 manifest와 recent target을 함께 사용해야 한다.

### 수정 대상

```text
src/allCode/core/result.py
src/allCode/agent/workflow.py
src/allCode/agent/workflow_actions.py
src/allCode/agent/context.py
src/allCode/agent/preflight.py
src/allCode/workspace/project_locator.py
src/allCode/memory/session_store.py
src/allCode/memory/recent_targets.py
tests/integration/test_generation_workflow.py
tests/integration/test_followup_context_memory.py
```

### 구현 계획

1. `ProjectManifest` 또는 `WorkflowManifest` 모델을 추가한다.
   - `project_root`
   - `package_root`
   - `entrypoints`
   - `test_paths`
   - `validation_commands`
   - `validation_cwd`
   - `last_modified_files`
   - `language`
   - `confidence`
2. generation workflow 성공 시 manifest를 `CompletionEvidence`와 session memory에 저장한다.
3. follow-up preflight는 manifest path가 실제 존재하는지 확인한 뒤 target hint에 반영한다.
4. manifest path가 사라졌거나 rename된 경우 workspace scan으로 fallback한다.
5. context builder는 “방금 만든”, “해당 프로젝트”, “그 파일” 같은 후속 표현을
   recent target과 manifest로 해석한다.
6. final reporter는 manifest 기반으로 생성/수정 파일과 검증 cwd를 출력한다.

### 수용 기준

- 생성 프로젝트 후속 수정이 기존 project root 내부에서 수행된다.
- validation cwd가 생성 프로젝트 root로 유지된다.
- manifest가 stale이면 standard project locator로 fallback한다.

## P4. Validation Failure Classifier와 Repair Hint

### 문제

validation failure가 final answer에는 남더라도, repair prompt가 원인을
구조적으로 전달하지 못하면 모델이 동일 실패를 반복하거나 reasoning-only로 종료한다.

### 수정 대상

```text
src/allCode/agent/validation_repair.py
src/allCode/agent/validation_runner.py
src/allCode/agent/prompt_builder.py
src/allCode/agent/tool_call_processor.py
src/allCode/core/result.py
tests/unit/agent/test_validation_repair.py
tests/integration/test_direct_edit_validation_repair.py
```

### 구현 계획

1. `ValidationFailureClassifier`를 추가한다.
   - syntax error
   - import/path error
   - assertion mismatch
   - missing symbol
   - runtime exception
   - command/cwd error
2. `RepairHint`를 만든다.
   - `failure_type`
   - `symbols`
   - `likely_files`
   - `recommended_tools`
   - `must_not_repeat`
3. `CompletionEvidence.validation_failure_symbols`를 final answer와 repair prompt에 모두 연결한다.
4. Python import/cwd 오류는 생성 프로젝트 manifest의 `validation_cwd`와 비교한다.
5. 실패 원인이 특정 파일/함수로 매핑되면 `read_file` range-first 또는 `search_files`
   action을 권장한다.
6. 같은 실패 signature가 2회 반복되면 더 이상 같은 validation만 반복하지 않는다.

### 수용 기준

- `ZeroDivisionError` 같은 핵심 exception symbol이 최종 답변에 보존된다.
- validation failure 후 repair prompt가 실패 유형과 다음 action을 명확히 담는다.
- repair loop는 최대 시도 횟수를 지키고 partial failure로 탈출한다.

## P5. Model-Owned Routing 유지와 Safety Capability Reconciliation

### 문제

사용자는 keyword routing을 원하지 않는다. 다만 모델이 위험 명령이나
잘못된 route를 선택할 때는 policy와 preflight가 capability를 제한해야 한다.
이 제한은 keyword로 “답을 결정”하는 것이 아니라, 안전한 tool surface를 보정하는
역할이어야 한다.

### 수정 대상

```text
src/allCode/agent/model_router.py
src/allCode/agent/preflight.py
src/allCode/agent/policy.py
src/allCode/agent/prompt_constraints.py
src/allCode/tools/approval.py
src/allCode/tools/builtin/shell.py
tests/unit/agent/test_model_router.py
tests/unit/agent/test_policy.py
tests/unit/tools/test_shell.py
```

### 구현 계획

1. model router의 1차 판단은 LLM routing decision을 유지한다.
2. preflight는 아래 safety marker만 계산한다.
   - destructive shell requested
   - local workspace request
   - external knowledge required
   - validation required
   - mutation required
3. route reconciliation은 marker와 policy로 capability bundle만 제한한다.
4. destructive 요청이 거부되면 read-only 대안 tool bundle을 열어준다.
   - `search_files`
   - `list_directory`
   - `read_file`
5. final answer에는 “위험한 명령은 실행하지 않았고, 대신 안전한 분석을 수행했다”는
   사용자 친화 문구를 evidence 기반으로 출력한다.
6. 특정 위험 문구 목록을 계속 늘리는 방식은 금지한다. shell policy의 command AST,
   destructive pattern, approval mode를 기준으로 판단한다.

### 수용 기준

- destructive shell은 실행되지 않는다.
- 거부 후 read-only 분석으로 전환할 수 있다.
- direct answer route에는 tool을 열지 않는다.
- external answer route에는 web evidence tool만 열린다.

## P6. Web Evidence Backend 표준화

### 문제

무료 web backend는 환경 의존성이 크다. public SearXNG instance는 불안정할 수 있고,
샌드박스 내부에서는 실제 네트워크 검증이 불가능하다.

### 수정 대상

```text
src/allCode/tools/web_provider.py
src/allCode/tools/builtin/web.py
src/allCode/agent/finalization.py
src/allCode/config/schema.py
tests/unit/tools/test_web.py
tests/quality 또는 output harness web scenario
```

### 구현 계획

1. MVP 기본 무료 backend는 SearXNG-compatible provider로 유지한다.
2. self-hosted SearXNG endpoint를 권장 설정으로 문서화한다.
3. web unavailable은 `web_search_unavailable` evidence bundle로 반환한다.
4. final answer는 raw backend error 대신 아래를 포함한다.
   - 검색 backend 사용 불가
   - 검색을 완료하지 못함
   - 로컬 지식만으로 답변할 수 있는 범위
5. sandbox 평가에서는 mock web provider를 사용한다.
6. real web 평가는 unsandboxed에서만 수행한다.

### 수용 기준

- web 실패가 agent loop 전체 실패로 번지지 않는다.
- final answer가 web backend 상태를 사용자에게 명확히 알린다.
- raw HTML/error dump가 최종 답변에 노출되지 않는다.

## P7. Final Answer Grounding 강화

### 문제

no-result search, not-found target, validation exception, policy-denied tool이
있어도 모델 답변이 이를 빠뜨릴 수 있다. completion evidence를 최종 근거로 쓰는
계약을 강화해야 한다.

### 수정 대상

```text
src/allCode/agent/finalization.py
src/allCode/agent/final_reporter.py
src/allCode/agent/completion_gate.py
src/allCode/core/result.py
tests/unit/agent/test_finalization.py
tests/unit/agent/test_completion_gate.py
```

### 구현 계획

1. `apply_final_answer_policy()`를 evidence 기반으로 강화한다.
2. 아래 evidence가 있으면 최종 답변에 누락되지 않게 한다.
   - `zero_result_queries`
   - `not_found_targets`
   - `validation_failure_symbols`
   - `policy_denied_tools`
   - `web_search_unavailable`
3. 한국어 요청에서는 `없습니다`, `찾지 못했습니다`, `검증 실패`, `실행하지 않았습니다`
   같은 사용자 친화 표현을 보장한다.
4. 이미 의미상 같은 표현이 있으면 중복 append하지 않는다.
5. final answer가 completion gate를 우회하지 못하게 한다.

### 수용 기준

- impossible/no-result 요청에서 “없음/찾지 못함” 의미가 명확히 출력된다.
- validation 실패 답변에 핵심 exception symbol이 포함된다.
- policy-denied 요청은 실행하지 않은 사실과 대안을 함께 말한다.

## P8. Responsibility Split

### 문제

현재 일부 파일은 500줄에 가깝거나 초과했고, 책임이 과밀하다. 계획상
NewCLI/allCode는 OneCLI식 거대 단일 파일을 반복하지 않아야 한다.

### 수정 대상

```text
src/allCode/agent/round_runner.py
src/allCode/agent/tool_call_processor.py
src/allCode/tools/builtin/file_ops.py
src/allCode/llm/response_parser.py
```

### 구현 계획

1. `round_runner.py` 분리
   - round state: `round_state.py`
   - validation control: `validation_controller.py`
   - parser recovery: `parser_recovery.py`
   - finalization handoff: `finalization_controller.py`
2. `tool_call_processor.py` 분리
   - schema gate: `tool_schema_gate.py`
   - budget/cache decision: `tool_execution_policy.py`
   - result/evidence recorder: `tool_result_recorder.py`
3. `file_ops.py` 분리
   - `read_file.py`
   - `write_file.py`
   - `patch_file.py`
   - `delete_path.py`
   - registry compatibility wrapper 유지
4. `response_parser.py`는 parser와 repair helper를 분리한다.
5. 공개 import 경로와 registry API는 유지한다.

### 수용 기준

- `round_runner.py`가 400줄 이하로 줄어든다.
- 분리 후 기존 unit/integration 테스트가 통과한다.
- tool registry의 외부 API가 깨지지 않는다.

## 구현 순서

1. P0 real-model 평가 안정화
   - 연결성 실패와 품질 실패를 분리해야 이후 수치가 신뢰 가능하다.
2. P1 session cache/budget 유지
   - token efficiency와 multi-turn 중복 경고를 먼저 줄인다.
3. P2 validation state machine
   - 가장 큰 fail 원인인 loop convergence를 해결한다.
4. P3 generated project manifest
   - 신규 프로젝트 후속 요청 실패를 줄인다.
5. P4 validation failure classifier
   - repair quality와 final answer quality를 함께 올린다.
6. P5 safety capability reconciliation
   - 위험 명령 거부 후 안전 대안 수행을 안정화한다.
7. P7 final answer grounding
   - no-result/not-found/validation symbol 누락을 줄인다.
8. P6 web backend 표준화
   - 외부 검색 품질과 실패 메시지를 정리한다.
9. P8 responsibility split
   - 기능 안정화 이후 파일 구조를 정리한다.

## 테스트 계획

### 로컬 회귀

```bash
python -m pytest tests/unit/agent tests/unit/tools
python -m pytest tests/integration/test_generation_workflow.py
python -m pytest tests/integration/test_followup_context_memory.py
python -m pytest tests/quality tests/tty
python -m pytest
```

### 샌드박스 외부 real-model smoke

네트워크가 필요한 테스트는 샌드박스 외부에서만 실행한다.
프로젝트 `.env` 자동 로딩을 사용한다.

```bash
.venv/bin/allcode --headless "한 문장으로 allCode가 무엇인지 답해줘."
```

### 샌드박스 외부 targeted stress

```bash
EVALUATION_SCENARIOS="S012,S016,S019,S025,S026,S028,S029,S030,S031,S032,S034" \
  .venv/bin/python output/evaluation_harness.py
```

### 샌드박스 외부 full stress

```bash
.venv/bin/python output/evaluation_harness.py
```

## 예상 개선 폭

| 보강 | 기대 효과 |
|---|---:|
| P0 평가 안정화 | 수치 신뢰도 회복 |
| P1 session cache/budget | token efficiency +2~3 |
| P2 validation state machine | loop convergence +5~7 |
| P3 project manifest | follow-up generation fail -1 |
| P4 repair classifier | response quality +2~3 |
| P5 safety reconciliation | safety 대안 scenario 안정화 |
| P7 final grounding | no-result/error wording warning 감소 |

현재 신뢰 가능한 기준선 82.2%에서 P1~P7이 성공하면 90~92% 수준까지
상승할 것으로 예상한다. 95% 이상은 full interactive diff, 더 정교한 repo map
ranking, 장기 durable memory, 더 강한 real shell sandbox 등 post-MVP 요소가
필요할 수 있다.

## 남은 리스크

1. endpoint 품질과 연결성이 낮으면 실제 stress 결과가 코드 개선과 무관하게 흔들릴 수 있다.
2. deterministic validation fallback을 과하게 적용하면 모델 자율성이 줄고 token cost가 늘 수 있다.
3. project manifest가 stale해지면 follow-up target을 잘못 잡을 수 있다.
4. final answer post-processing을 과하게 하면 문장이 반복되거나 부자연스러워질 수 있다.
5. 파일 분리 중 public import 경로가 깨질 수 있다.

## 다음 단계

1. P0을 먼저 구현해 real-model 평가 결과 보존 방식을 안정화한다.
2. P1과 P2를 연속으로 구현해 multi-turn/token efficiency와 validation convergence를 개선한다.
3. targeted stress를 샌드박스 외부에서 실행해 fail/warning 변화를 확인한다.
4. 결과가 88% 이상으로 올라오면 P3~P7을 적용한다.
5. full stress에서 90% 이상이 확인되면 P8 구조 분리를 진행한다.
