# 22. Remaining Risk Agy Discussion Hardening Plan

## 목적

이 문서는 최신 실제 모델 stress 결과와 `agy --print` read-only 토론 결과를 바탕으로, allCode의 남은 fail/warning을 줄이기 위한 상세 보강 계획서다.

이번 단계의 목표는 새 기능을 넓히는 것이 아니라, 현재 구현된 CLI coding agent loop를 더 안정적으로 수렴시키는 것이다. 특히 다음 영역에 집중한다.

- validation-required 구현 요청에서 test file 작성, 검증, repair, 재검증으로 수렴한다.
- 생성 workflow 이후 후속 수정 요청이 생성 산출물 target으로 정확히 이어진다.
- malformed native tool argument stream을 안전하게 복구한다.
- search 결과만 보고 답하지 않고 필요한 파일을 읽어 grounded answer를 만든다.
- 한국어/영어 최종 답변 wording을 prompt language와 tool observation에 맞게 보강한다.
- round/tool 모듈이 다시 비대해지지 않도록 책임 경계를 재정리한다.

## 참조 우선순위

이 문서는 아래 문서의 하위 보강 계약이다.

1. `plan/00_master_implementation_guide.md`
2. `plan/01_open_source_alignment_contracts.md`
3. `plan/04_llm_loop_plan.md`
4. `plan/06_tool_system_plan.md`
5. `plan/08_context_memory_plan.md`
6. `plan/09_generation_workflow_plan.md`
7. `plan/11_quality_testing_plan.md`
8. `plan/12_mvp_execution_plan.md`
9. `plan/19_open_source_completion_gap_plan.md`
10. `plan/20_harness_agent_open_source_completion_plan.md`
11. `plan/21_open_source_parity_95_hardening_plan.md`
12. 이 문서

충돌 시 `00`~`12`를 우선한다. 그다음 `19`, `20`, `21`, `22` 순서로 최신 보강 계약을 적용한다.

## agy 실행 조건과 결과

`agy --print`에는 다음 제한을 명시했다.

- read-only review only.
- 파일 생성, 수정, 삭제 금지.
- `apply_patch`, shell write, git 명령, 테스트 실행 금지.
- 코드 수정 없이 분석 텍스트만 출력.

긴 프롬프트 1차 실행은 출력 없이 멈춰 중단했고, 짧은 read-only 프롬프트로 재실행했다. agy는 실제 파일 수정 없이 구조 분석과 보강 의견만 출력했다.

## 최신 기준선

최신 실제 모델 stress 결과는 `output/evaluation_summary.json` 기준이다.

| 항목 | 값 |
|---|---:|
| 시나리오 수 | 34 |
| pass | 25 |
| warning | 4 |
| fail | 5 |
| 평균 점수 | 95.1 |
| 오픈소스 CLI coding agent 대비 추정 완성도 | 80.3% |

기준별 점수:

| 기준 | 점수 |
|---|---:|
| Tool Use & Grounding | 92.5 |
| Tool Logic Validation | 100.0 |
| Loop Execution & Convergence | 78.6 |
| Response Quality Audit | 87.6 |
| Multi-turn Context Retention | 100.0 |
| Memory Compression & Efficiency | 100.0 |
| Error Handling & Resilience | 100.0 |
| Security & Boundary Check | 100.0 |
| Token & Cost Efficiency | 92.5 |

남은 주요 이슈:

| 시나리오 | 상태 | 핵심 문제 |
|---|---|---|
| S016 | warning | impossible task에서 한국어 not-found wording 부족 |
| S024 | fail 88.0 | 기존 파일 수정은 성공 방향이나 13 round, 중복 read/patch/test |
| S025 | fail 66.0 | malformed `write_file` argument, test file/validation 수렴 실패 |
| S028 | warning | 같은 target `read_file` 중복 |
| S029 | warning | 큰 파일 후속 질문에서 같은 파일 중복 read |
| S031 | fail 66.0 | generation 후속 수정이 생성 산출물 target과 validation cwd로 안정 연결되지 않음 |
| S032 | fail 81.7 | `search_files` 이후 후보 파일을 `read_file`로 검증하지 않음 |
| S033 | warning | 설정 관련 한국어 wording 부족 |
| S034 | fail 77.0 | multi-file 구현은 일부 수행하나 validation 통과 전 수렴 실패 |

현재 구조 리스크:

| 파일 | 줄 수 | 판단 |
|---|---:|---|
| `src/allCode/agent/loop.py` | 348 | 목표 상한 근처, 유지 |
| `src/allCode/agent/round_runner.py` | 521 | 분리 필요 |
| `src/allCode/agent/tool_call_processor.py` | 347 | 분리 후보 |
| `src/allCode/agent/tool_orchestrator.py` | 165 | 유지 가능 |
| `src/allCode/agent/validation_repair.py` | 143 | 보강 가능 |
| `src/allCode/llm/response_parser.py` | 387 | parser repair 분리 필요 |
| `src/allCode/tools/builtin/file_ops.py` | 417 | read/write/patch/delete 책임 분리 필요 |

## agy 피드백 요약과 검수

agy가 제안한 우선순위:

1. S034/S031: project-level task resolution을 막는 multi-file/follow-up validation 문제를 먼저 처리한다.
2. S025: malformed native tool argument stream 복구를 강화한다.
3. S016/S033: 한국어/영어 language consistency gate를 추가한다.
4. S032/S024/S028/S029: grounding과 loop efficiency를 개선한다.

agy가 제안한 주요 수정 대상:

- `src/allCode/agent/round_runner.py`
- `src/allCode/llm/response_parser.py`
- `src/allCode/agent/finalization.py`
- `src/allCode/tools/builtin/shell.py`

Codex 검수 결과:

- 채택: parser repair 강화, nested project validation cwd resolver, language-adaptive finalization, search-result grounding gate.
- 부분 채택: tool schema를 너무 rigid하게 lock하지 말라는 제안은 수용하되, 모든 tool을 항상 노출하라는 방식은 채택하지 않는다.
- 거부: Aider처럼 write/test tools를 항상 열어 두는 방식은 allCode의 `plan/21` strict phase gate 및 safety contract와 충돌한다.
- 보정 방향: strict phase gate는 유지하되, phase를 `single action lock`이 아니라 `capability bundle`로 운영한다.

## 설계 원칙

1. 특정 scenario ID, 특정 prompt, 특정 파일명을 하드코딩하지 않는다.
2. 판단 기준은 `RoutingDecision`, `CompletionEvidence`, `ToolResult.metadata`, `RecoveryState`, `recent_targets`, workspace index에 둔다.
3. read-only, no-shell, no-network는 어떤 phase보다 우선한다.
4. validation-required 구현/수정 요청은 `validation_passed=True` 없이 success가 될 수 없다.
5. 모델이 hidden tool을 호출하면 실행하지 않고 `schema_denied` observation으로 남긴다.
6. schema gate는 안전을 위해 유지하되, repair phase에서는 필요한 read/mutate/validation capability bundle을 현실적으로 제공한다.
7. 실패한 turn도 사용자에게 빈 답변을 주지 않고, 수행한 tool evidence와 차단 이유를 요약한다.

## P0. Phase Gate v2와 Validation Repair Controller

### 문제

S025, S031, S034에서 모델이 일부 file mutation을 수행하거나 생성 산출물을 만들었지만, 다음 단계인 test 작성, validation 실행, validation 실패 수리로 안정적으로 이어지지 않는다.

현재 `RoundRunner`는 다음 문제가 있다.

- `validation_action_pending`, `validation_repair_pending`, `mutation_action_pending`이 boolean 중심이라 phase 전환 이유가 불명확하다.
- mutation-only lock이 필요한 순간에는 효과가 있지만, test file 생성과 validation 사이에서는 너무 좁거나 너무 넓게 동작한다.
- validation 실패 후 `run_tests` 재호출 금지, test file 작성 요구, repair mutation 요구가 하나의 explicit phase contract로 표현되지 않는다.

### 수정 대상

```text
src/allCode/agent/round_runner.py
src/allCode/agent/validation_repair.py
src/allCode/agent/tool_call_processor.py
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/prompt_builder.py
src/allCode/core/events.py
tests/unit/agent/test_phase_gate.py
tests/unit/agent/test_validation_repair.py
tests/integration/test_direct_edit_validation_repair.py
tests/integration/test_mock_agent_loop.py
tests/integration/test_generation_workflow.py
```

### 구현 계획

1. `RepairPhaseState`를 확장한다.
   - `normal`
   - `inspection_required`
   - `mutation_required`
   - `test_authoring_required`
   - `validation_required`
   - `validation_failed`
   - `repair_mutation_required`
   - `revalidation_required`
   - `repair_exhausted`
2. `PhaseToolGate`를 추가한다.
   - `phase`
   - `allowed_tool_names`
   - `required_next_action`
   - `deny_hidden_tools=True`
   - `reason`
3. `CompletionEvidence`와 prompt constraints로 test artifact 필요 여부를 판단한다.
   - 사용자가 테스트를 추가/포함/검증 요청했고 변경 파일 중 test artifact가 없으면 `test_authoring_required`.
   - test artifact 판단은 경로/파일명 패턴 기반이다.
   - scenario ID나 특정 prompt text를 사용하지 않는다.
4. phase별 tool bundle을 정의한다.
   - `inspection_required`: `read_file`, `search_files`, `list_directory`
   - `mutation_required`: `patch_file`, `write_file`, 필요 시 `read_file`
   - `test_authoring_required`: `write_file`, `patch_file`, 필요 시 `read_file`
   - `validation_required`: `run_tests`
   - `validation_failed`: `read_file`, `search_files`, `patch_file`, `write_file`
   - `revalidation_required`: `run_tests`
5. hidden tool 호출은 `ToolCallSchemaDenied`와 `ToolResult(error_type="schema_denied")`로 남긴다.
6. schema denied observation에는 다음 행동을 짧게 포함한다.
   - 예: “현재 단계에서는 test file 작성이 필요하므로 write_file 또는 patch_file을 사용해야 합니다.”
7. validation 실패 직후 mutation evidence가 없으면 `run_tests` 재호출을 막는다.
8. mutation 후 validation_required 상태로 전환되며, validation command가 없으면 `run_tests` 기본 명령 추론을 허용한다.
9. repair attempt는 기본 2회로 제한한다.
10. repair exhausted이면 success가 아니라 failed/partial로 종료하고 final answer에 validation command, 실패 요약, 수정 시도 파일을 포함한다.

### 수용 기준

- S025에서 `write_file source -> write_file test -> run_tests` 흐름이 관찰된다.
- S031 후속 수정에서 생성 산출물 target을 읽은 뒤 `patch_file/write_file -> run_tests`로 간다.
- S034에서 source mutation 후 test file 작성 또는 validation 실행으로 이어지고, 실패 시 repair mutation 후 revalidation한다.
- validation-required 요청은 `validation_passed=True` 없이 success가 되지 않는다.
- read-only 요청은 phase gate보다 먼저 mutation을 차단한다.

## P1. Tolerant Native Tool Argument Repair v2

### 문제

S025에서 실제 모델이 multiline `write_file` arguments를 native tool-call stream으로 내보내지만 JSON escaping이 깨져 parser가 `malformed_tool_call`로 종료한다.

현재 repair는 `write_file`의 좁은 형태만 복구한다. content가 마지막 field가 아니거나, boolean/hash field 순서가 바뀌거나, model endpoint가 raw newline을 섞는 경우 복구율이 낮다.

### 수정 대상

```text
src/allCode/llm/response_parser.py
src/allCode/llm/tool_argument_repair.py
src/allCode/core/events.py
tests/unit/llm/test_response_parser.py
tests/unit/llm/test_tool_argument_repair.py
tests/integration/test_mock_agent_loop.py
```

### 구현 계획

1. `ToolArgumentRepairer` 모듈을 분리한다.
2. repair 대상은 명확히 제한한다.
   - `write_file`
   - `patch_file`
   - `run_tests` command/cwd 누락 또는 key alias
3. `write_file` repair는 다음을 지원한다.
   - `file_path`와 `content` field 순서 변경.
   - raw newline 포함 content.
   - content 뒤에 `overwrite`, `create_only`, `expected_hash`가 오는 형태.
   - escaped quote와 backslash가 섞인 형태.
4. `patch_file` repair는 다음을 지원한다.
   - patches array가 깨졌지만 search/replace pair가 명확히 반복되는 경우.
   - patch block 수가 1개 이상이고 search/replace가 모두 non-empty일 때만 복구.
5. repair confidence를 기록한다.
   - `high`: strict field extraction 성공.
   - `medium`: raw content tail repair.
   - `low`: 복구하지 않고 malformed 유지.
6. 복구된 tool call도 일반 policy, approval, path policy를 그대로 통과해야 한다.
7. repair event를 `ModelResponseParsed.data` 또는 새 `ToolArgumentRepaired` event에 기록한다.
8. 복구 실패 시 기존처럼 안전 실패로 처리하되, final answer에는 parser 차단 사유를 남긴다.

### 수용 기준

- malformed multiline `write_file`이 명확한 `file_path/content`를 가진 경우 native tool call로 복구된다.
- 복구 대상이 불명확하면 실행하지 않는다.
- `pseudo tool call` text는 여전히 직접 실행하지 않는다.
- S025의 parser fail이 제거된다.

## P2. Generated Project Follow-up Target and Validation Cwd Resolver

### 문제

S031은 신규 프로젝트 생성 첫 turn은 성공하지만, 후속 “방금 만든 CLI가 --name 옵션을 받도록 보강하고 검증”에서 target/cwd 연결이 불안정하다.

필요한 것은 특정 `generated_project` 이름 하드코딩이 아니라, workflow 산출물 manifest와 recent target을 기반으로 후속 요청 target을 찾는 것이다.

### 수정 대상

```text
src/allCode/agent/workflow.py
src/allCode/agent/final_reporter.py
src/allCode/agent/context.py
src/allCode/memory/recent_targets.py
src/allCode/agent/preflight.py
src/allCode/tools/builtin/shell.py
src/allCode/workspace/project_locator.py
tests/unit/workspace/test_project_locator.py
tests/integration/test_generation_workflow.py
tests/integration/test_followup_context_memory.py
```

### 구현 계획

1. generation workflow가 산출물 manifest를 기록한다.
   - project root
   - source entrypoints
   - test files
   - validation command
   - package metadata file
2. manifest는 `CompletionEvidence.metadata` 또는 session memory/recent target에 저장한다.
3. 후속 질문에서 “방금 만든”, “그 CLI”, “해당 프로젝트” 같은 follow-up reference가 있으면 manifest를 우선 target source로 사용한다.
4. `ProjectLocator`를 추가한다.
   - 특정 path에서 상위로 올라가며 `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `settings.gradle`을 찾는다.
   - workspace root 아래 여러 package가 있으면 recent target과 changed_files 기준으로 rank한다.
5. `run_tests` default cwd는 workspace root가 아니라 `ProjectLocator`가 찾은 project root를 우선한다.
6. validation command가 workflow manifest에 있으면 그 command를 우선 사용한다.
7. target_hint가 absolute path여도 workspace root 아래면 relative-safe path로 정규화해 prompt와 tool arguments에 제공한다.

### 수용 기준

- 생성 workflow 후속 수정에서 target file과 project cwd가 유지된다.
- `run_tests`가 생성 프로젝트의 package root에서 실행된다.
- 특정 프로젝트명이나 특정 fixture명을 하드코딩하지 않는다.

## P3. Search Result Grounding Gate

### 문제

S032에서 `search_files`는 실행됐지만 후보 파일을 `read_file`로 확인하지 않아 “grounded answer” 기준을 만족하지 못했다.

검색 preview만으로 답해도 되는 경우가 있지만, 사용자가 “문서에서 찾아줘”, “확인한 파일을 적어줘”, “없으면 없다고 말해줘”처럼 근거 파일을 요구하면 후보 파일을 읽어야 한다.

### 수정 대상

```text
src/allCode/agent/completion_gate.py
src/allCode/agent/round_runner.py
src/allCode/agent/tool_targets.py
src/allCode/agent/prompt_builder.py
src/allCode/core/result.py
tests/unit/agent/test_grounding_gate.py
tests/integration/test_mock_agent_loop.py
tests/quality/test_quality_matrix.py
```

### 구현 계획

1. `CompletionEvidence` 또는 별도 `GroundingEvidence`에 다음을 기록한다.
   - search result candidate paths.
   - read_file inspected paths.
   - final answer required grounding 여부.
2. grounding-required signal은 generic prompt constraints로 추출한다.
   - “확인한 파일”
   - “문서에서”
   - “근거”
   - “없으면”
   - “actual file”
   - “cite checked files”
3. inspect route에서 grounding이 필요하고 search result candidate가 있는데 read_file이 없으면 final answer 전 recovery를 요청한다.
4. recovery prompt는 후보 path를 구체적으로 제시하되 scenario-specific phrase를 쓰지 않는다.
5. 검색 preview에 exact answer와 line number가 충분한 경우에는 optional read로 두되, “확인한 파일을 적어줘” 요청은 read_file을 요구한다.

### 수용 기준

- S032에서 `search_files -> read_file -> final answer` 흐름이 관찰된다.
- 불가능한 task는 fake success 없이 not-found evidence를 final answer에 포함한다.
- 검색 결과가 없으면 read_file을 강제하지 않는다.

## P4. Language-Adaptive Finalization Policy

### 문제

S016과 S033은 기능적으로는 큰 문제가 없지만 한국어 prompt에 대해 “찾지 못했습니다”, “설정” 같은 사용자가 기대하는 표현이 누락된다.

이를 특정 시나리오 단어로 맞추면 하드코딩이 되므로, prompt language와 tool observation state 기반 wording policy로 처리한다.

### 수정 대상

```text
src/allCode/agent/finalization.py
src/allCode/agent/finalization_helpers.py
src/allCode/agent/turn_completion.py
src/allCode/core/result.py
tests/unit/agent/test_finalization.py
tests/integration/test_agent_failure_convergence.py
```

### 구현 계획

1. `PromptLanguage` helper를 추가한다.
   - Hangul range가 있으면 Korean.
   - Latin-only면 English.
   - mixed prompt는 user-visible command language를 우선한다.
2. `FinalAnswerPolicy`는 상태별 bilingual suffix를 가진다.
   - not_found
   - workspace_boundary_denied
   - policy_denied
   - validation_failed
   - validation_passed
   - evidence_missing
   - web_unavailable
3. suffix는 모델 답변을 대체하지 않고 부족한 필수 상태 표현만 append한다.
4. 상태 판단은 `ToolResult.error_type`, `CompletionEvidence`, `RecoveryState`를 사용한다.
5. Korean prompt에서 not_found 상태면 “찾지 못했습니다” 또는 “없습니다” 중 하나를 보장한다.
6. Korean prompt에서 config/setting 관련 observation이 있으면 “설정” 표현을 보장한다.
7. English prompt에는 Korean suffix를 붙이지 않는다.

### 수용 기준

- S016 warning이 제거된다.
- S033 warning이 제거된다.
- 한국어가 아닌 prompt에는 한국어 보강 문구가 붙지 않는다.

## P5. Loop Efficiency and Observation Reuse v2

### 문제

S024, S028, S029는 기능 성공 또는 부분 성공에도 같은 target read/search가 반복되어 near max-round 또는 duplicate read warning이 발생한다.

현재 ObservationCache와 ToolBudgetTracker는 있지만, semantic duplicate나 phase별 budget 전환이 충분하지 않다.

### 수정 대상

```text
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/tool_call_processor.py
src/allCode/agent/recovery.py
src/allCode/agent/round_runner.py
src/allCode/workspace/path_resolver.py
tests/unit/agent/test_tool_orchestrator.py
tests/unit/agent/test_recovery.py
tests/integration/test_followup_context_memory.py
```

### 구현 계획

1. cache key를 absolute path만이 아니라 normalized relative path와 semantic target으로도 비교한다.
2. `read_file` 중복 기준:
   - 같은 file full read는 turn당 1회.
   - 다른 line range는 허용.
   - content hash가 mutation 후 달라지면 cache invalidate.
3. `search_files` 중복 기준:
   - 같은 query/path/glob은 turn당 1회.
   - query가 alias 관계이면 semantic duplicate로 판단한다.
4. budget 초과 시 phase별 response를 다르게 한다.
   - inspect: final answer 또는 clarification.
   - mutation: patch/write 요구.
   - validation_failed: repair mutation 요구.
5. `ToolObservationReused` event를 모델 메시지에 충분히 전달한다.
6. repeated schema denied는 곧바로 stuck으로 보지 말고 phase instruction을 더 강하게 만든다.
7. 2회 이상 same target denial이면 final answer가 아니라 action-required recovery prompt로 전환한다.

### 수용 기준

- S024 model rounds가 10 미만으로 감소한다.
- S028/S029 duplicate read warning이 제거된다.
- 정상적인 ranged read는 차단되지 않는다.

## P6. Module Responsibility Split

### 문제

`round_runner.py`, `response_parser.py`, `file_ops.py`, `tool_call_processor.py`가 다시 커지고 있다. `loop.py`는 348줄로 목표 상한을 맞췄지만, helper 모듈이 다음 비대화 지점이다.

### 수정 대상과 분리 계획

```text
src/allCode/agent/round_runner.py
  -> round_runner.py              # public round orchestration only
  -> round_state.py               # phase state, counters, allowed tool bundle
  -> parser_recovery.py           # empty/reasoning/pseudo/malformed recovery branch
  -> validation_controller.py     # validation/repair phase transition
  -> phase_gate.py                # PhaseToolGate model and allowed tools

src/allCode/llm/response_parser.py
  -> response_parser.py           # event aggregation only
  -> tool_argument_buffer.py      # stream buffer
  -> tool_argument_repair.py      # tolerant repair
  -> pseudo_tool_parser.py        # pseudo tool text detection

src/allCode/tools/builtin/file_ops.py
  -> file_ops.py                  # re-export builtin file tools
  -> file_read.py                 # read/list/range-first
  -> file_write.py                # write transaction
  -> file_patch.py                # patch transaction
  -> file_delete.py               # delete/no-op evidence

src/allCode/agent/tool_call_processor.py
  -> tool_call_processor.py       # high-level execute loop
  -> schema_gate.py               # hidden tool denial
  -> tool_normalizer.py           # run_command->run_tests, aliases
  -> tool_result_recorder.py      # target/evidence/cache update
```

### 수용 기준

- 각 신규 파일은 300줄 이하를 목표로 하고 500줄을 넘지 않는다.
- 순환 import가 없다.
- `AgentLoop.run_turn()` public API는 유지한다.
- 전체 pytest 회귀가 통과한다.

## 테스트 계획

### Unit

```bash
python -m pytest \
  tests/unit/agent/test_phase_gate.py \
  tests/unit/agent/test_validation_repair.py \
  tests/unit/agent/test_grounding_gate.py \
  tests/unit/agent/test_finalization.py \
  tests/unit/llm/test_tool_argument_repair.py \
  tests/unit/workspace/test_project_locator.py \
  tests/unit/tools/test_file_ops.py
```

### Integration

```bash
python -m pytest \
  tests/integration/test_mock_agent_loop.py \
  tests/integration/test_generation_workflow.py \
  tests/integration/test_followup_context_memory.py \
  tests/integration/test_agent_failure_convergence.py
```

### Full Regression

```bash
python -m pytest tests/unit tests/integration tests/quality tests/tty
```

### Actual Model Stress

우선 남은 이슈만 집중 재검증한다.

```bash
EVALUATION_SCENARIOS=S016,S024,S025,S028,S029,S031,S032,S033,S034 .venv/bin/python output/evaluation_harness.py
```

이후 전체 stress를 재실행한다.

```bash
.venv/bin/python output/evaluation_harness.py
```

## 단계별 실행 순서

1. P1 parser repair를 먼저 구현한다.
   - S025의 hard failure를 제거한다.
2. P0 phase gate v2와 validation repair controller를 구현한다.
   - S025/S034의 test-authoring/validation/repair 수렴을 개선한다.
3. P2 generated project follow-up target/cwd resolver를 구현한다.
   - S031을 개선한다.
4. P3 grounding gate를 구현한다.
   - S032를 개선한다.
5. P4 language-adaptive finalization을 구현한다.
   - S016/S033 warning을 제거한다.
6. P5 observation reuse v2를 구현한다.
   - S024/S028/S029 warning과 near max round를 줄인다.
7. P6 module split을 적용한다.
   - 신규 보강이 안정화된 뒤 책임 분리를 마무리한다.

## 기대 결과

1차 수용 목표:

- 실제 모델 stress fail 5 -> 2 이하.
- warning 4 -> 2 이하.
- open-source parity 80.3% -> 88% 이상.
- Loop Execution & Convergence 78.6 -> 88 이상.
- Response Quality 87.6 -> 92 이상.

2차 수용 목표:

- 실제 모델 stress fail 0 또는 1 이하.
- warning 1 이하.
- open-source parity 92~95% 범위.
- S025/S031/S034가 모두 pass 또는 최소 warning으로 격상.

## 남은 리스크

- 현재 모델 endpoint가 native tool call argument escaping을 일관되게 제공하지 않을 수 있다. parser repair는 안전 범위 내에서만 허용해야 한다.
- phase gate를 과도하게 열면 safety와 read-only contract가 약해질 수 있다. 모든 permissive 변경은 read-only/no-shell/no-network보다 낮은 우선순위여야 한다.
- generated project follow-up은 workspace에 여러 package가 있을 때 target ambiguity가 생길 수 있다. 이 경우 clarification을 허용해야 한다.
- language-adaptive suffix가 모델 답변을 과도하게 덧붙이면 답변 품질이 떨어질 수 있다. 상태별 필수 표현만 최소 append한다.
- module split은 기능 보강 후 진행해야 한다. 먼저 분리하면 디버깅 비용이 커질 수 있다.
