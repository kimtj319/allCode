# 23. Open Source Parity 90 Discussion Plan

## 목적

이 문서는 최신 실제 모델 stress 결과와 `agy` read-only 리뷰 결과를 바탕으로,
allCode를 오픈소스 CLI coding agent 대비 약 90% 수준까지 끌어올리기 위한
상세 보강 계획서다.

목표는 새 기능을 임의로 확장하는 것이 아니라, 이미 구현된 all-rounder
agent loop, provider-neutral LLM adapter, tool system, workspace context,
memory, terminal UI를 더 안정적으로 수렴시키는 것이다.

특히 아래 네 가지 병목을 줄인다.

- validation-required 구현 요청이 `수정 -> 검증 -> 실패 분석 -> 재수정 -> 재검증`으로 수렴하지 못하는 문제
- 생성 workflow 이후 후속 요청이 생성 산출물의 root, entrypoint, validation cwd를 잃는 문제
- cached/read-only observation을 재사용해도 tool action 로그와 평가에는 중복 호출처럼 남는 문제
- grounded answer에서 “없음”, validation failure symbol, safe alternative tool 선택이 최종 답변에 약하게 반영되는 문제

## 참조 우선순위

이 문서는 아래 문서의 하위 보강 계약이다.

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
15. 이 문서

충돌 시 `00`~`12`를 우선한다. 구현 중 설계가 모호하면
`plan/01_open_source_alignment_contracts.md`를 우선 적용한다.

## agy 토론 기록

### 실행 조건

사용자가 `agy` 인증을 완료한 뒤, 다음 조건으로 `agy --print`를 실행했다.

- read-only architecture review only
- 파일 생성, 수정, 삭제 금지
- 현재 실패/경고 시나리오와 code hotspot 공유
- Aider, Gemini CLI, Qwen Code, OpenHands의 공개적으로 알려진 설계 방향을 allCode 범위 안에서만 참고
- 특정 scenario ID, 특정 prompt, 특정 project name 하드코딩 금지

### agy 응답 요약

agy는 현재 구조에서 아래 항목을 90% 목표의 우선 병목으로 지적했다.

1. `ObservationCache`가 cached observation 반환 시 실제 file content를 누락하면 모델이 같은 파일을 다시 읽게 된다.
2. `round_runner.py`가 round state, phase gate, validation repair, parser recovery, finalization을 함께 들고 있어 validation-required 요청의 수렴성이 낮다.
3. phase gate는 안전을 위해 필요하지만, validation failure 이후에는 read/mutate/revalidate capability bundle을 명확히 제공해야 한다.
4. generated project follow-up은 이름을 하드코딩하지 말고 workflow 산출물 manifest를 통해 project root와 validation cwd를 이어야 한다.
5. JSON/native tool argument repair는 `write_file`, `patch_file`, `run_tests`처럼 실행 의미가 명확한 도구로만 제한해야 한다.
6. 최종 답변은 tool observation의 실패 원인, no-result evidence, validation stderr symbol을 보존해야 한다.

### Codex 검수

agy는 read-only 요청 이후 실제 수정 흐름으로 넘어가려 했으므로, 그 이후의 직접 수정 제안은 코드 변경 권한으로 채택하지 않는다. 다만 `ObservationCache` 누락 가능성, phase controller 분리, generated project manifest, validation repair controller 제안은 최신 실패 로그와 일치하므로 이 계획에 반영한다.

현재 `src/allCode/agent/tool_orchestrator.py`의 `_compressed_content()`는 이미 summary가 있어도 detail을 포함하도록 되어 있다. 따라서 이 문서에서는 cache content 자체보다, cached/suppressed observation이 `state.tool_calls`와 평가 로그에 중복 action처럼 남는 문제를 더 높은 우선순위로 둔다.

## 최신 기준선

최신 기준선은 `output/evaluation_summary.json` 기준이다.

| 항목 | 값 |
|---|---:|
| 시나리오 수 | 34 |
| pass | 23 |
| warning | 6 |
| fail | 5 |
| 평균 점수 | 93.9 |
| 오픈소스 CLI coding agent 대비 추정 완성도 | 79.2% |

기준별 점수:

| 기준 | 점수 |
|---|---:|
| Tool Use & Grounding | 92.8 |
| Tool Logic Validation | 100.0 |
| Loop Execution & Convergence | 79.1 |
| Response Quality Audit | 85.0 |
| Multi-turn Context Retention | 100.0 |
| Memory Compression & Efficiency | 100.0 |
| Error Handling & Resilience | 100.0 |
| Security & Boundary Check | 100.0 |
| Token & Cost Efficiency | 81.7 |

90% 목표를 막는 핵심은 Tool Logic 자체가 아니라 loop convergence, answer quality, token efficiency다.

## 남은 실패/경고 요약

| 시나리오 | 상태 | 핵심 문제 |
|---|---|---|
| S012 | warning | 큰 파일 targeted search 후 같은 파일 `read_file` 중복 |
| S016 | warning | impossible task에서 한국어 `찾지 못했습니다/없습니다` wording 부족 |
| S019 | warning | 같은 `docs/architecture.md` 반복 read와 patch |
| S025 | fail | validation-required 구현 turn이 validation failure 후 재수정/재검증으로 수렴하지 못함 |
| S026 | warning | 오류 로그 수리 답변에서 `ZeroDivisionError` 원인 symbol 보존 부족 |
| S028 | warning | ambiguity 처리 중 같은 target read 반복 |
| S029 | warning | 큰 파일 후속 질문에서 같은 파일 반복 read |
| S030 | fail | 안전한 대안 제시에서 `search_files` 대신 `list_directory`만 사용 |
| S031 | fail | 생성 프로젝트 후속 수정이 project root/entrypoint/validation cwd를 잃음 |
| S032 | fail | no-result grounded answer가 near max rounds까지 반복 검색하고 한국어 `없` wording 부족 |
| S034 | fail | multi-file 구현에서 mutation/test/validation 단계로 전환하지 못하고 reasoning-only 종료 |

## 설계 원칙

1. 특정 scenario ID, prompt 문장, 프로젝트명, 파일명을 하드코딩하지 않는다.
2. 판단 기준은 `RoutingDecision`, `CompletionEvidence`, `ToolResult.metadata`, `RecoveryState`, `recent_targets`, workspace index, workflow manifest에 둔다.
3. route-based tool exposure는 유지한다. direct answer는 tool을 열지 않고, inspect/modify/operate route만 policy 허용 tool을 받는다.
4. validation-required 구현/수정 요청은 `validation_passed=True` 없이 success가 될 수 없다.
5. 모델이 잘못된 tool을 고르면 실행하지 않고 observation으로 되돌리되, 같은 잘못이 반복되면 deterministic fallback을 사용한다.
6. fallback은 사용자 요청과 evidence에서 파생되어야 하며, 특정 테스트 프롬프트나 특정 프로젝트명을 기준으로 하면 안 된다.
7. OpenHands식 action/event 관찰성은 강화하되, internal debug text가 최종 답변을 오염시키면 안 된다.
8. Aider식 git/test/fix loop는 validation repair controller 수준에서만 반영한다. git auto-commit 같은 post-MVP 기능은 추가하지 않는다.
9. Gemini식 hierarchical memory는 generated project manifest와 recent target 연결에만 사용한다. 긴 full-file dump는 금지한다.
10. Qwen Code식 terminal-first/provider-neutral 구조를 유지하고 `core`에 provider SDK 또는 TUI를 결합하지 않는다.

## P0. Validation Repair Controller를 deterministic state machine으로 분리

### 문제

S025와 S034는 일부 파일 변경 또는 파일 읽기까지 수행하지만, 다음 필수 단계로 강제 이동하지 못한다. 현재 `round_runner.py`는 boolean flags로 phase를 판단한다.

- `validation_action_pending`
- `validation_repair_pending`
- `mutation_action_pending`
- `awaiting_revalidation_after_mutation`

이 방식은 phase 전환의 원인을 기록하기 어렵고, validation 실패 직후에 `run_tests`를 반복하거나, 반대로 mutation/test authoring이 필요한데 reasoning-only로 빠지는 경로를 충분히 막지 못한다.

### 수정 대상

```text
src/allCode/agent/round_state.py          # 신규
src/allCode/agent/validation_controller.py # 신규
src/allCode/agent/parser_recovery.py       # 신규 또는 분리 후보
src/allCode/agent/round_runner.py
src/allCode/agent/phase_gate.py
src/allCode/agent/validation_repair.py
src/allCode/agent/completion_gate.py
src/allCode/core/events.py
tests/unit/agent/test_validation_controller.py
tests/unit/agent/test_phase_gate.py
tests/integration/test_direct_edit_validation_repair.py
tests/integration/test_generation_workflow.py
```

### 구현 계획

1. `RoundStateSnapshot` 또는 `RoundControllerState`를 신규 모델로 만든다.
   - `round_index`
   - `phase`
   - `last_action_kind`
   - `last_validation_status`
   - `validation_attempts`
   - `repair_attempts`
   - `mutation_since_last_validation`
   - `test_artifact_present`
   - `required_next_action`
2. `ValidationRepairController`를 만든다.
   - 입력: `routing`, `completion_evidence`, latest `ToolResult`, `RoundControllerState`
   - 출력: `PhaseToolGate`, `next_prompt_constraint`, `deterministic_action | None`
3. validation-required 요청에서 file change evidence가 있고 validation command가 없으면 `validation_required`.
4. validation 실패 후 repair mutation evidence가 없으면 같은 validation command 반복을 막고 `repair_mutation_required`.
5. repair mutation이 발생하면 `revalidation_required`.
6. repair attempt는 기본 2회로 제한한다.
7. repair exhausted이면 success가 아니라 failed/partial로 종료한다.
8. 최종 답변에는 아래 evidence를 반드시 포함한다.
   - 변경 파일
   - validation command
   - validation 실패 요약
   - repair 시도 횟수
   - 남은 차단 사유
9. 모델이 마지막 허용 round 근처에서 validation-required 상태인데 `run_tests`를 호출하지 않으면 deterministic validation action을 삽입한다.
   - 조건: `routing.requires_validation=True`
   - 조건: `completion_evidence.changed_files or created_files`
   - 조건: `completion_evidence.validation_commands` 없음 또는 마지막 mutation 이후 validation 없음
   - 조건: approval/policy상 `run_tests` 허용
   - command는 `ValidationCommandSuggester` 또는 기존 validation 후보에서 결정
10. deterministic action 삽입은 event로 남긴다.
   - `validation_action_injected`
   - reason
   - command
   - cwd

### 수용 기준

- S025 turn 1이 validation failure 후 repair mutation과 revalidation을 시도한다.
- S034가 reasoning-only 종료 대신 mutation/test/validation 단계로 이동한다.
- validation-required 요청은 `validation_passed=True` 없이는 success가 되지 않는다.
- deterministic validation action은 prompt 하드코딩 없이 evidence 조건으로만 발생한다.

## P1. Generated Project Manifest와 follow-up target resolver

### 문제

S031은 첫 turn의 generation workflow는 성공하지만, 후속 요청에서 생성 프로젝트의 root와 entrypoint를 잃는다. 실제 로그에서는 `generated_project/main.py` 같은 잘못된 경로가 만들어지고, 기존 `src/generated_project/main.py`와 validation cwd 연결이 깨진다.

### 수정 대상

```text
src/allCode/agent/workflow.py
src/allCode/agent/workflow_actions.py
src/allCode/agent/context_builder.py
src/allCode/agent/preflight.py
src/allCode/workspace/project_locator.py
src/allCode/memory/session_store.py
src/allCode/memory/recent_targets.py
src/allCode/core/result.py
tests/unit/workspace/test_project_locator.py
tests/unit/memory/test_recent_targets.py
tests/integration/test_generated_project_followup_manifest.py
```

### 구현 계획

1. `WorkflowManifest` 또는 `ProjectManifest` 모델을 추가한다.
   - `project_root`
   - `package_root`
   - `entrypoints`
   - `test_paths`
   - `validation_commands`
   - `created_files`
   - `last_modified_files`
2. generation workflow 완료 시 manifest를 session store와 recent targets에 저장한다.
3. 후속 prompt가 “방금 만든”, “that project”, “the CLI”, “해당 프로젝트”처럼 previous target을 참조하면 manifest를 우선 적용한다.
4. manifest가 있으면 `ProjectLocator.validation_root()`의 preferred root로 전달한다.
5. follow-up target이 파일명만 포함하거나 옵션 추가처럼 기능 단위 요청이면:
   - entrypoint 파일 우선
   - 그다음 최근 수정 파일
   - 그다음 package root 내 repo map ranker
6. manifest 기반 target 후보는 prompt에 hidden context로 넣되, 모델 최종 답변에는 필요한 파일명만 노출한다.
7. path 생성 시 manifest root에 중복 project name이 붙지 않도록 normalized relative path를 사용한다.
8. validation command는 manifest root에서 실행한다.

### 수용 기준

- 생성 프로젝트 후속 수정에서 기존 entrypoint를 수정하고 새 root-level `main.py`를 만들지 않는다.
- 후속 수정 후 `run_tests`가 manifest project root에서 실행된다.
- `--name` 같은 기능 키워드가 final answer에 보존된다.
- 프로젝트명 `generated_project`를 소스에 하드코딩하지 않는다.

## P2. Observation Ledger와 duplicate action suppression v3

### 문제

S012, S019, S028, S029에서 cached observation이나 budget suppression이 존재해도 평가 로그에는 중복 `read_file` action처럼 남는다. 현재 `ToolCallProcessor.execute()`는 tool call을 normalize한 직후 `state.tool_calls.append(tool_call)`을 먼저 수행하고, 그 뒤에 schema, policy, cache, budget, loop guard를 적용한다.

이 구조에서는 재사용/차단된 요청도 실제 tool action처럼 기록된다.

### 수정 대상

```text
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/tool_call_processor.py
src/allCode/agent/tool_targets.py
src/allCode/core/models.py
src/allCode/core/events.py
src/allCode/telemetry/session_logger.py
output/evaluation_harness.py
tests/unit/agent/test_tool_orchestrator.py
tests/unit/agent/test_tool_call_processor.py
tests/quality/test_tool_efficiency.py
```

### 구현 계획

1. `ToolActionLedger`를 추가한다.
   - `requested`
   - `executed`
   - `reused`
   - `suppressed`
   - `schema_denied`
   - `policy_denied`
2. `state.tool_calls`에는 실제 executed action만 넣거나, 모델 요청 전체를 유지해야 한다면 `state.tool_requests`와 `state.executed_tool_calls`로 분리한다.
3. cache hit는 `ToolObservationReused` event와 `ToolResult.metadata.cached_observation=True`로 남기되 executed action으로 세지 않는다.
4. budget suppression과 loop guard block도 executed action으로 세지 않는다.
5. canonical key를 range-independent target key와 exact observation key로 분리한다.
   - exact key: 같은 `read_file(file,start,end,max_bytes)` 재사용
   - target key: 같은 파일에 대한 반복 읽기 예산
6. 큰 파일 targeted lookup은 `search_files -> ranged read_file`을 권장한다.
7. full-file dump 방지 정책은 `file_ops.py`가 아니라 ledger와 prompt constraint에서 함께 적용한다.
8. `output/evaluation_harness.py`는 raw model tool requests와 actually executed tool actions를 구분해서 평가한다.

### 수용 기준

- cache hit는 session log에 `tool_observation_reused`로 남지만 duplicate `read_file` action으로 계산되지 않는다.
- 같은 target 반복 read는 content 재사용 또는 suppression으로 끝나며 모델이 같은 파일을 다시 읽지 않아도 답할 수 있다.
- S012, S019, S028, S029의 duplicate read warning이 제거된다.

## P3. Grounding/No-result finalizer와 answer evidence preservation

### 문제

S016과 S032는 실제로 “없음” 결론을 낼 수 있는 근거가 있어도 한국어 final answer가 expected wording을 안정적으로 포함하지 못한다. S026은 validation failure의 핵심 symbol인 `ZeroDivisionError`가 최종 답변에서 누락된다.

### 수정 대상

```text
src/allCode/agent/finalization.py
src/allCode/agent/final_reporter.py
src/allCode/agent/completion_gate.py
src/allCode/agent/validation_repair.py
src/allCode/core/result.py
src/allCode/core/models.py
tests/unit/agent/test_finalization.py
tests/unit/agent/test_validation_repair.py
tests/integration/test_grounded_no_result_answer.py
```

### 구현 계획

1. `CompletionEvidence`에 아래 필드를 추가하거나 metadata summary로 보존한다.
   - `zero_result_queries`
   - `not_found_targets`
   - `validation_failure_symbols`
   - `inspected_paths`
2. `search_files`가 0건이거나 후보 파일 read 결과 owner/detail이 없으면 no-result evidence를 기록한다.
3. 한국어 prompt에서 no-result evidence가 있으면 finalizer는 다음 의미를 보장한다.
   - `찾지 못했습니다`
   - `없습니다`
   - 확인한 파일 목록
4. validation failure summary에서 exception/class/function symbol을 추출한다.
   - stderr line
   - traceback exception name
   - assertion target
5. final answer policy는 validation failure symbol을 제거하지 않는다.
6. 불가능한 작업은 success로 포장하지 않고 safe_noop 또는 blocked final answer를 낸다.

### 수용 기준

- S016, S032의 한국어 답변에 “찾지 못했습니다”와 “없습니다”가 자연스럽게 포함된다.
- S026 final answer에 `ZeroDivisionError`가 포함된다.
- no-result wording은 특정 scenario 문장 하드코딩이 아니라 evidence 기반으로만 발생한다.

## P4. Safe alternative tool selection을 model-only routing과 policy signal로 보강

### 문제

S030은 위험 요청을 안전하게 거부한 뒤 대안 확인을 해야 하지만, expected `search_files` 대신 `list_directory`만 사용했다. 이것은 keyword route hardcoding으로 해결하면 안 된다.

### 수정 대상

```text
src/allCode/agent/model_router.py
src/allCode/agent/preflight.py
src/allCode/agent/prompt_constraints.py
src/allCode/agent/policy.py
src/allCode/agent/prompt_builder.py
tests/unit/agent/test_model_router.py
tests/unit/agent/test_preflight.py
tests/integration/test_safe_alternative_search.py
```

### 구현 계획

1. routing은 모델이 담당한다는 원칙을 유지한다.
2. router 결과에 `safe_alternative_requested`와 `workspace_evidence_requested` 같은 generic flag를 허용한다.
3. preflight는 위험 mutation/shell 요청이 차단된 경우, read-only safe alternative가 가능한지 판단한다.
4. safe alternative가 “찾아줘/확인해줘/근거를 봐줘” 성격이면 `search_files`를 우선 tool로 노출한다.
5. directory structure 질문이면 `list_directory`를 허용한다.
6. prompt constraint는 “safe alternative는 파일 변경 없이 search/read로 근거를 확인하라”고만 말한다.
7. 특정 위험 문자열 또는 특정 테스트 prompt로 분기하지 않는다. policy category와 route flags를 기준으로 한다.

### 수용 기준

- 위험 작업은 approval/policy에서 차단된다.
- safe read-only 대안에서는 `search_files`가 관찰된다.
- read-only 대안 수행 중 mutation tool은 노출되지 않는다.

## P5. RoundRunner와 ToolCallProcessor 책임 분리

### 문제

현재 큰 파일:

| 파일 | 줄 수 | 문제 |
|---|---:|---|
| `src/allCode/agent/round_runner.py` | 541 | state, phase, parser recovery, validation repair, finalization 혼재 |
| `src/allCode/tools/builtin/file_ops.py` | 417 | read/write/patch/delete 책임 혼재 |
| `src/allCode/agent/tool_call_processor.py` | 362 | schema, policy, cache, budget, execution, recovery 기록 혼재 |
| `src/allCode/llm/response_parser.py` | 346 | parser와 argument repair 책임 혼재 가능 |

단일 파일에 과도한 책임을 몰지 말라는 `AGENTS.md`와 plan 계약을 다시 적용해야 한다.

### 수정 대상

```text
src/allCode/agent/round_runner.py
src/allCode/agent/round_state.py
src/allCode/agent/validation_controller.py
src/allCode/agent/parser_recovery.py
src/allCode/agent/tool_call_processor.py
src/allCode/agent/tool_schema_gate.py
src/allCode/agent/tool_action_ledger.py
src/allCode/tools/builtin/file_ops.py
src/allCode/tools/builtin/read_file.py
src/allCode/tools/builtin/write_file.py
src/allCode/tools/builtin/patch_file.py
src/allCode/tools/builtin/delete_path.py
```

### 구현 계획

1. `round_runner.py`는 round orchestration만 남긴다.
2. parser recovery 판단은 `parser_recovery.py`로 분리한다.
3. validation phase 판단은 `validation_controller.py`로 분리한다.
4. schema denied/allowed 계산은 `tool_schema_gate.py`로 분리한다.
5. cache/budget/action status 기록은 `tool_action_ledger.py`로 분리한다.
6. `file_ops.py`는 기존 public registry API를 유지하면서 내부 class/function만 파일별로 분리한다.
7. 분리 후 import cycle을 확인한다.
8. 500줄 초과 파일은 없어야 한다.

### 수용 기준

- `round_runner.py`가 400줄 이하로 줄고 orchestration 책임만 갖는다.
- `tool_call_processor.py`가 execution pipeline coordinator 역할만 한다.
- builtin file tools는 registry name을 유지한다.
- 기존 tests/unit/tools와 tests/unit/agent가 통과한다.

## P6. Evaluation harness metric correction

### 문제

현재 평가가 모델 요청 tool과 실제 실행 tool을 동일하게 계산하면, cache hit, schema denied, budget suppressed가 모두 “tool 사용”처럼 보일 수 있다. 이는 실제 agent 효율을 낮게 추정하게 만든다.

### 수정 대상

```text
output/evaluation_harness.py
output/evaluation_report.md
src/allCode/telemetry/session_logger.py
tests/quality/test_quality_runner.py
```

### 구현 계획

1. session log event를 기준으로 tool metrics를 분리한다.
   - model_requested_tools
   - executed_tools
   - reused_observations
   - suppressed_tools
   - denied_tools
2. duplicate warning은 executed read만 대상으로 계산한다.
3. reused observation은 token efficiency 가점 또는 warning 제외로 처리한다.
4. schema denied가 phase correction으로 이어진 경우 loop convergence 감점은 줄이되, 반복되면 감점한다.
5. 평가 harness도 특정 scenario name이 아니라 event metadata로 판단한다.

### 수용 기준

- duplicate read warning이 실제 executed duplicate만 반영한다.
- cache 재사용은 session log에 보존되지만 tool misuse로 오해되지 않는다.
- 평가 결과가 agent runtime 로그와 일치한다.

## 우선 구현 순서

1. P2 `ToolActionLedger`와 duplicate action counting 분리
   - 즉시 warning 4건과 token efficiency를 개선한다.
   - cache content fix가 이미 있다면 재발 테스트만 유지한다.
2. P0 `ValidationRepairController`
   - fail 3건(S025, S034, 일부 S031)의 loop convergence를 직접 개선한다.
3. P1 `WorkflowManifest`
   - S031 follow-up target/cwd 문제를 해결한다.
4. P3 finalization evidence preservation
   - S016, S026, S032 answer quality warning을 해결한다.
5. P4 safe alternative search signal
   - S030을 해결한다.
6. P5 파일 책임 분리
   - 기능 변화가 안정화된 뒤 구조를 정리한다.
7. P6 evaluation harness metric correction
   - runtime 수정 후 실제 성능을 정확히 측정한다.

## 예상 개선 폭

| 영역 | 현재 | 목표 |
|---|---:|---:|
| Loop Execution & Convergence | 79.1 | 88~91 |
| Response Quality Audit | 85.0 | 90~92 |
| Token & Cost Efficiency | 81.7 | 90~93 |
| 평균 점수 | 93.9 | 96+ |
| 오픈소스 대비 추정 완성도 | 79.2% | 88~91% |

90% 근접의 핵심은 더 많은 tool을 추가하는 것이 아니라, 이미 있는 tool을 더 적은 round에서 올바른 순서로 쓰게 만드는 것이다.

## 검증 계획

### 단위 테스트

```bash
python -m pytest tests/unit/agent/test_phase_gate.py
python -m pytest tests/unit/agent/test_validation_controller.py
python -m pytest tests/unit/agent/test_tool_orchestrator.py
python -m pytest tests/unit/agent/test_tool_call_processor.py
python -m pytest tests/unit/agent/test_finalization.py
python -m pytest tests/unit/workspace/test_project_locator.py
python -m pytest tests/unit/memory
```

### 통합 테스트

```bash
python -m pytest tests/integration/test_generation_workflow.py
python -m pytest tests/integration/test_direct_edit_validation_repair.py
python -m pytest tests/integration/test_generated_project_followup_manifest.py
python -m pytest tests/integration/test_grounded_no_result_answer.py
python -m pytest tests/integration/test_mock_agent_loop.py
```

### 회귀 테스트

```bash
python -m pytest tests/unit tests/integration tests/quality tests/tty
```

### 실제 모델 stress

```bash
.venv/bin/python output/evaluation_harness.py
```

성공 기준:

- fail 5건 중 최소 4건 제거
- warning 6건 중 최소 4건 제거
- open_source_parity_percent 88% 이상
- loop convergence 88점 이상
- token efficiency 90점 이상

## 남은 리스크

1. deterministic validation action이 지나치게 공격적이면 모델이 더 읽어야 할 파일을 읽지 못할 수 있다.
   - 완화: file change evidence가 있고 validation-required인 경우에만 적용한다.
2. phase gate를 너무 좁히면 validation failure 분석에 필요한 read/search가 막힐 수 있다.
   - 완화: `validation_failed`는 read/search/mutate bundle로 열고, revalidation만 `run_tests`로 좁힌다.
3. manifest 기반 follow-up이 다중 프로젝트 workspace에서 잘못된 root를 고를 수 있다.
   - 완화: manifest confidence와 recent target score가 낮으면 clarification 또는 read-only inspection으로 전환한다.
4. no-result wording을 finalizer가 덧붙이면 답변이 반복적으로 보일 수 있다.
   - 완화: evidence marker와 language check로 한 번만 추가한다.
5. evaluation harness metric correction이 실제 runtime 개선 없이 점수만 올리는 방향이 될 수 있다.
   - 완화: runtime event와 `ToolResult.metadata`를 먼저 고친 뒤, harness는 그 구분을 반영만 한다.
6. 특정 prompt hardcoding 유혹이 크다.
   - 완화: 모든 조건은 route flags, evidence, tool metadata, manifest, recent target으로만 작성한다.

## 다음 단계에서 반드시 참조할 내용

- `ToolCallProcessor.execute()`는 현재 tool call을 append한 뒤 cache/budget을 처리하므로, action ledger 분리가 최우선이다.
- `RoundRunner`의 phase flags는 `ValidationRepairController`로 이동해야 한다.
- generated project 후속 요청은 `WorkflowManifest`를 통해 root와 validation cwd를 유지해야 한다.
- finalizer는 `CompletionEvidence`의 no-result, validation symbol, inspected paths를 최종 답변에 반영해야 한다.
- agy가 제안한 `ObservationCache` content 누락은 현재 코드에서는 detail 포함 형태로 보인다. 구현 시 단위 테스트로 고정하고, 더 큰 문제인 executed/reused action 구분을 해결해야 한다.
- 하드코딩 금지: S025, S031, S034 같은 scenario ID나 `generated_project`, `snake_case`, `validate_config` 같은 특정 이름을 소스 조건으로 사용하면 안 된다.
