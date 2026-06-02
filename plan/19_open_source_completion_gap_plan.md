# 19. Open-Source Completion Gap Hardening Plan

## 목적

이 문서는 `18_open_source_agent_hardening_plan.md` 구현과 실제 모델 스트레스 재검증 이후 남은 완성도 격차를 줄이기 위한 후속 계획서다.

최신 실제 모델 평가 결과는 다음과 같다.

- 실행 리포트: `output/evaluation_report.md`
- 모델: `wisenut/wise-lloa-max-v1.2.1`
- 시나리오 수: 22
- 결과: pass 12, warning 5, fail 5
- 평균 점수: 92.1
- 주요 잔여 실패: S005, S008, S009, S011, S013
- 주요 잔여 경고: S007, S012, S015, S016, S019

목표는 MVP 범위를 임의로 확장하는 것이 아니라, 현재 allCode 구조 안에서 오픈소스급 CLI coding agent에 필요한 안정성, 수렴성, 관찰성, 비용 효율을 완성하는 것이다.

## 참조 문서와 우선순위

이 문서는 아래 계약의 하위 보강 문서다.

- `00_master_implementation_guide.md`: 모듈화, 완료 근거, 단일 책임, 테스트 실행 계약.
- `01_open_source_alignment_contracts.md`: Aider, Gemini CLI, Qwen Code, OpenHands 정렬 기준.
- `04_llm_loop_plan.md`: final answer gate, recovery, timeout/retry, tool loop guard.
- `05_routing_policy_plan.md`: router/policy/executor 책임 분리.
- `06_tool_system_plan.md`: ToolResult 표준화, approval, destructive shell 차단.
- `07_workspace_context_plan.md`: safe path, large repo full dump 금지.
- `08_context_memory_plan.md`: repo map, hierarchical memory, recent target.
- `09_generation_workflow_plan.md`: validation/self-repair.
- `11_quality_testing_plan.md`: stress matrix와 quality score.
- `12_mvp_execution_plan.md`: CompletionEvidence, RecoveryState, ToolLoopSignature.
- `17_model_routed_tool_system_remediation_plan.md`: model-routed tool lifecycle 보강.
- `18_open_source_agent_hardening_plan.md`: trace, stuck detector, repo-map search, memory visibility.

충돌 시 `00`~`12`와 안전 계약을 우선한다. 그다음 `17`, `18`, `19`를 최신 보강 계약으로 적용한다.

## agy 토론 결과 요약

`agy --print`로 현재 코드, plan 문서, 최신 스트레스 결과를 공유하고 분석을 요청했다. agy는 다음 방향을 제안했다.

- Aider 관점: validation/test repair loop와 repo-map/ranged-read 선호를 더 강하게 적용해야 한다.
- Gemini CLI 관점: hierarchical memory는 있지만 alias/refresh/show 결과가 실제 tool 선택으로 충분히 연결되지 않는다.
- Qwen Code 관점: provider-neutral CLI 상태 명령은 필요하며 `/tools`, `/model`, `/config`가 유효하다.
- OpenHands 관점: Action/Observation trace와 stuck detector는 필수이며 search/list 반복과 reasoning-only 반복을 별도 stuck으로 봐야 한다.

최신 코드 기준으로 아래 항목은 이미 구현되었으므로 재구현 대상에서 제외한다.

- session JSONL의 `trace_id`, `span_id`, `record_kind`, normalized action/observation.
- `ModelMetricsRecorded`와 request/response 문자 수 기록.
- `/tools`, `/model`, `/config`, `/memory show`, `/memory refresh` 기본 명령.
- `web_search_unavailable` evidence bundle.
- `run_command` validation command를 `run_tests`로 정규화하는 기본 경로.
- basic `ToolLoopGuard.record_observation`과 partial blocked summary.

따라서 이 계획은 남은 fail/warning을 줄이기 위한 다음 격차에 집중한다.

## 현재 구조상 즉시 해결해야 할 구조 문제

`src/allCode/agent/loop.py`가 738줄까지 커졌다. `00_master_implementation_guide.md`의 500줄 상한과 단일 책임 계약을 넘었으므로, 다음 구현은 기능 추가 전후로 loop 책임 분리를 포함해야 한다.

권장 분리:

```text
src/allCode/agent/loop.py
  - public AgentLoop assembly와 run_turn 조율만 유지

src/allCode/agent/round_runner.py
  - model round 실행, stream 수집, parser status 분기

src/allCode/agent/tool_orchestrator.py
  - tool schema 선택, tool call 정규화, ToolExecutor 호출, loop guard 연동

src/allCode/agent/finalization.py
  - LoopOutcome -> TurnResult 변환, failed/partial final answer policy

src/allCode/agent/preflight.py
  - deterministic target probe와 conditional operation probe
```

완료 기준:

- `agent/loop.py`는 350줄 이하로 줄인다.
- 새 파일도 300줄을 넘기지 않는다.
- 기존 `AgentLoop` public constructor와 `run_turn` 호출 계약은 유지한다.
- `tests/integration/test_mock_agent_loop.py`와 `tests/integration/test_agent_loop_context_validation.py`가 변경 없이 의미상 통과해야 한다.

## P0. 실제 fail 제거

### P0-1. Validation Repair Planner

영향 시나리오:

- S008 Safe validation command
- S009 Bug fix with validation

문제:

- S008은 `run_tests`를 실행했지만 validation 실패 원인을 사용자 답변에 충분히 보존하지 못하고 failed로 끝난다.
- S009는 수정 요청임에도 `run_tests` 반복 후 `patch_file`로 진입하지 못하는 실행이 남아 있다.
- 현재 repair request는 prompt text 중심이며, 실패 로그와 다음 tool 제한이 구조화되어 있지 않다.

수정 대상:

```text
src/allCode/agent/validation_runner.py
src/allCode/agent/round_runner.py
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/prompt_builder.py
src/allCode/agent/turn_completion.py
src/allCode/agent/finalization.py
tests/integration/test_direct_edit_validation_repair.py
tests/integration/test_agent_failure_convergence.py
tests/unit/agent/test_prompt_builder.py
```

구현 계획:

1. `ValidationFailureSummary` 모델을 추가한다.
   - command
   - returncode
   - failed_files
   - failing_symbols
   - traceback_excerpt
   - assertion_excerpt
   - suggested_read_targets
   - error_hash
2. `ValidationRunner._summarize_log()`를 `ValidationFailureSummary` 생성 로직과 분리한다.
3. `ToolResult` metadata에 validation failure summary를 넣는다.
4. `RoundRunner`는 validation 실패 후 다음 라운드를 repair phase로 전환한다.
5. repair phase에서는 같은 `run_tests`를 바로 다시 호출하지 못하게 한다.
   - 직전 validation 실패 이후 file mutation evidence가 없으면 `run_tests` schema를 숨긴다.
   - 허용 schema는 `read_file`, `search_files`, `patch_file`, `write_file` 중심으로 제한한다.
6. repair phase prompt는 실패 로그 요약과 다음 행동 계약을 구조화한다.
   - 먼저 실패 파일을 읽는다.
   - 기존 파일을 수정한다.
   - 그 후 `run_tests`를 재실행한다.
7. 최대 repair attempt는 2회로 제한한다.
8. repair가 실패하면 status는 `failed`를 유지하되 final answer에는 validation command, 실패 요약, 수정하지 못한 이유를 포함한다.

완료 기준:

- S008은 실패하더라도 빈 답변 또는 일반 gate 문구가 아니라 실패 원인과 validation command를 설명한다.
- S009는 `run_tests -> read_file/search_files -> patch_file/write_file -> run_tests` 순서를 관찰할 수 있어야 한다.
- validation-required 요청은 passing validation evidence 없이 success가 될 수 없다.

### P0-2. Deterministic Target Preflight

영향 시나리오:

- S005 Nonexistent file resilience
- S011 Delete to trash
- S015 Ambiguous edit should clarify or inspect
- S016 No fake success on impossible task

문제:

- 모델이 명시된 파일을 `read_file`로 확인하지 않고 `search_files`/`list_directory`만 반복한다.
- 조건부 삭제 요청에서 대상 파일이 없을 때 `delete_path` 또는 no-op evidence 없이 change evidence gate에 막힌다.
- 모호한 수정 요청에서 불필요하게 파일을 읽거나, 명확한 “어떤 파일인지 필요” 문구가 누락된다.

수정 대상:

```text
src/allCode/agent/preflight.py
src/allCode/agent/intent.py
src/allCode/agent/prompt_constraints.py
src/allCode/agent/round_runner.py
src/allCode/agent/completion_gate.py
src/allCode/tools/builtin/file_ops.py
tests/unit/agent/test_preflight.py
tests/integration/test_preflight_noop_completion.py
tests/integration/test_agent_failure_convergence.py
```

구현 계획:

1. `PreflightPlanner`를 추가한다.
2. prompt와 routing에서 exact file target을 추출한다.
   - `missing_config.yaml`
   - `tmp/remove_me.txt`
   - `README.md`
   - `@path` 또는 path-like token
3. read/inspect 요청에서 exact file target이 있으면 첫 model round 전에 `read_file` probe를 실행한다.
4. `ReadFileTool`은 존재하지 않는 파일을 빈 성공으로 반환하지 않고 `ok=False`, `error_type="not_found"`로 반환한다.
5. conditional delete 요청을 감지한다.
   - 한국어: “있으면 삭제”, “없으면 삭제하지 말고 보고”
   - 영어: “delete if exists”, “if missing, report”
6. conditional delete에서는 `delete_path`를 한 번 실행한다.
   - target exists: deletion evidence를 기록한다.
   - target missing: `noop_evidence`를 기록하고 success/report를 허용한다.
7. `CompletionEvidence`에 no-op resolution을 표현한다.
   - 예: `noop_reason`, `noop_targets`, `safe_noop=True`
   - conditional mutation에서 no-op evidence가 있으면 file change 없이도 success/report를 허용한다.
8. 모호한 target이면 도구를 실행하지 않고 clarification answer를 구성한다.
   - “어떤 파일인지 지정해 주세요.”
   - “파일명을 알려주면 읽기/수정/삭제를 진행할 수 있습니다.”

완료 기준:

- S005에서 `read_file` observation이 반드시 남고, missing target을 명시한다.
- S011에서 target missing이면 `delete_path` not_found observation과 no-op evidence로 완료 보고한다.
- 모호한 수정 요청은 mutation tool을 호출하지 않는다.

### P0-3. Parser Recovery for Pseudo Tool Calls

영향 시나리오:

- S013 Memory compression pressure

문제:

- 실제 모델이 native tool call이 아니라 텍스트 형태의 pseudo tool call을 출력하면 현재 parser가 안전하게 실패시킨다.
- 실패 처리는 맞지만, 오픈소스급 agent는 이를 즉시 사용자 실패로 끝내기보다 “native tool calling protocol로 다시 호출”하도록 한 번 복구해야 한다.

수정 대상:

```text
src/allCode/llm/response_parser.py
src/allCode/agent/round_runner.py
src/allCode/agent/prompt_builder.py
tests/unit/llm/test_response_parser.py
tests/integration/test_pseudo_tool_call_recovery.py
```

구현 계획:

1. `ResponseParser`가 pseudo tool call을 `malformed_tool_call` 하나로만 처리하지 않고 `pseudo_tool_call` status로 분리한다.
2. pseudo tool call에서 tool name과 raw text를 metadata로 남긴다. 실행은 하지 않는다.
3. `RoundRunner`는 최초 pseudo tool call에 한해 retry prompt를 삽입한다.
   - “텍스트로 tool JSON을 쓰지 말고 provider native tool call을 사용하라.”
   - allowed tool 목록을 다시 제공한다.
4. 두 번째 pseudo tool call이면 failed 또는 partial로 수렴한다.
5. 이 복구는 external web/raw answer에는 적용하지 않는다.

완료 기준:

- pseudo tool call은 실행되지 않는다.
- 1회 retry 후 native tool call로 회복 가능하다.
- 회복 실패 시 final answer에는 parser 차단 이유가 표시된다.

## P1. Warning과 비용 효율 개선

### P1-1. Tool Budget과 Observation Compression

영향 시나리오:

- S012 Large context targeted search
- S019 Token efficiency repeated context

문제:

- 현재 stuck guard는 반복을 줄이지만, 같은 목적의 search/read가 여러 변형 인자로 반복되는 high tool count를 충분히 줄이지 못한다.
- tool result가 그대로 다음 prompt에 누적되어 모델이 이미 본 observation을 다시 확인하는 경향이 있다.

수정 대상:

```text
src/allCode/agent/recovery.py
src/allCode/agent/tool_orchestrator.py
src/allCode/agent/context.py
src/allCode/agent/prompt_builder.py
src/allCode/memory/session_summary.py
tests/unit/agent/test_tool_budget.py
tests/integration/test_tool_budget_convergence.py
```

구현 계획:

1. `ToolBudget` 모델을 추가한다.
   - max_total_tool_calls per turn
   - max_same_tool_target
   - max_search_before_read
   - max_read_same_file
2. tool call 전 budget을 확인한다.
3. budget 초과 시 새 tool execution 대신 compressed observation을 삽입한다.
   - “이미 같은 파일을 읽었습니다.”
   - “이미 같은 query에서 0건을 확인했습니다.”
4. `PromptBuilder.append_tool_results()`는 긴 observation을 summary + stable metadata로 압축한다.
5. final answer request에는 “이미 관찰한 결과를 재사용하라”는 지시를 넣는다.

완료 기준:

- S012, S019 tool call count가 10 미만으로 내려간다.
- 기존 grounding accuracy가 떨어지지 않는다.

### P1-2. Repo Map and Memory Search Preference

영향 시나리오:

- S013 Memory compression pressure
- S004 follow-up regression 방지

문제:

- alias memory가 symbol-like token으로 연결되어도 모델이 `search_files` 대신 직접 `read_file`을 선택할 수 있다.
- repo map, recent target, durable memory가 context에 들어가지만 tool strategy로 충분히 강제되지 않는다.

수정 대상:

```text
src/allCode/memory/selector.py
src/allCode/memory/repo_ranker.py
src/allCode/agent/context.py
src/allCode/agent/prompt_builder.py
tests/unit/memory/test_selector.py
tests/integration/test_followup_context_memory.py
tests/integration/test_memory_alias_search_preference.py
```

구현 계획:

1. memory alias가 symbol/path-like token을 가리키면 `ContextBundle`에 `tool_strategy_hint`를 추가한다.
2. hint 예시:
   - `search_first: TARGET_SETTING`
   - `recent_target: src/alpha/service.py`
   - `read_range_preferred`
3. `PromptBuilder._context_instruction()`은 strategy hint를 별도 섹션으로 출력한다.
4. `RepoRanker`는 memory alias hit와 recent target hit를 점수에 반영한다.
5. `search_files` metadata에 `memory_alias_hit`와 `rank_reason`을 남긴다.

완료 기준:

- memory alias 기반 질문에서 `search_files`가 먼저 관찰된다.
- “그 파일”, “해당 함수” 후속 질문은 recent target을 유지한다.

### P1-3. Wording Gate for Safety and Blocked Answers

영향 시나리오:

- S007 Shell approval safety
- S015 Ambiguous edit should clarify or inspect
- S016 Impossible task wording

문제:

- 안전 정책 자체는 동작하지만 final answer에 평가 기준상 필요한 단어가 누락된다.
- 위험 shell 요청에는 “승인”, “위험”, “차단” 같은 사용자 친화 상태 문구가 필요하다.
- impossible task는 “찾지 못했다/없다”를 명시해야 한다.

수정 대상:

```text
src/allCode/agent/final_reporter.py
src/allCode/agent/finalization.py
src/allCode/agent/turn_completion.py
src/allCode/tools/approval.py
tests/unit/agent/test_final_reporter.py
tests/integration/test_safety_wording_gate.py
tests/quality/test_quality_matrix.py
```

구현 계획:

1. `FinalAnswerPolicy`를 추가한다.
2. policy denied, approval required, destructive command blocked에는 표준 문구를 결합한다.
3. ambiguous target에는 “어떤 파일인지”가 포함된 clarification sentence를 결합한다.
4. search/read not_found에는 “찾지 못했습니다”, “없습니다”를 포함한다.
5. 템플릿은 final answer를 덮어쓰지 않고 누락된 상태 설명만 앞 또는 뒤에 붙인다.

완료 기준:

- S007, S015, S016이 warning 없이 통과한다.
- 강제 문구가 success claim처럼 보이지 않는다.

## P2. 회귀 평가와 운영성

### P2-1. Stress Regression Matrix를 pytest로 승격

문제:

- `output/evaluation_harness.py`는 실제 모델 평가에는 유용하지만, 일반 pytest 회귀에 완전히 포함되어 있지 않다.
- 실제 모델 결과는 변동성이 있으므로 fake replay와 real optional evaluation을 분리해야 한다.

수정 대상:

```text
tests/quality/stress_cases.py
tests/quality/test_stress_regression_matrix.py
output/evaluation_harness.py
```

구현 계획:

1. `output/evaluation_harness.py`의 scenario definitions를 `tests/quality/stress_cases.py`로 복제하지 않고 import 가능한 순수 데이터로 이동한다.
2. fake LLM replay case를 추가한다.
3. real model test는 `ALLCODE_RUN_REAL_MODEL_EVAL=1`일 때만 실행한다.
4. summary threshold를 명시한다.
   - fail 0
   - warning 3 이하
   - average score 94 이상
   - criteria 3, 4, 9 각각 90 이상
5. 리포트는 `output/` 아래에만 쓴다.

완료 기준:

- `python -m pytest tests/quality`가 fake stress regression을 포함한다.
- real stress는 선택 실행이며 secret을 로그에 남기지 않는다.

### P2-2. Session Log Analyzer

문제:

- JSONL trace는 생겼지만 실패 원인 분석은 아직 사람이 `rg`로 로그를 열어야 한다.
- 오픈소스급 CLI agent는 session replay/diagnostics가 있어야 한다.

수정 대상:

```text
src/allCode/telemetry/analyzer.py
src/allCode/tui/status_commands.py
tests/unit/telemetry/test_session_analyzer.py
tests/tty/test_status_commands.py
```

구현 계획:

1. session JSONL을 읽어 turn별 summary를 만든다.
2. action/observation count, repeated target, validation failure, parser recovery, blocked reason을 계산한다.
3. `/status last` 또는 `/debug last` 명령으로 최근 turn diagnostics를 보여준다.
4. secret redaction을 analyzer 입력/출력 모두에 적용한다.

완료 기준:

- 실패 시나리오 로그를 사람이 직접 파싱하지 않아도 주요 원인을 볼 수 있다.
- TUI는 agent 내부 상태를 직접 import하지 않고 telemetry service만 호출한다.

## 구현 권장 순서

1. `AgentLoop` 책임 분리부터 진행한다.
   - 이후 기능 추가가 `loop.py`를 더 키우지 않게 한다.
2. P0-1 validation repair planner를 구현한다.
   - S008/S009를 먼저 줄인다.
3. P0-2 deterministic target preflight와 no-op evidence를 구현한다.
   - S005/S011/S015를 줄인다.
4. P0-3 pseudo tool call recovery를 구현한다.
   - S013 parser failure 재발을 막는다.
5. P1-1 tool budget과 observation compression을 구현한다.
   - S012/S019 high tool count를 줄인다.
6. P1-2 memory search preference를 구현한다.
   - alias/recent target의 tool selection 안정성을 높인다.
7. P1-3 wording gate를 구현한다.
   - 경고성 wording issue를 마무리한다.
8. P2 stress regression과 session analyzer를 구현한다.

## 검증 명령

각 단계별 최소 검증:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/agent tests/unit/tools tests/unit/memory tests/unit/telemetry
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_agent_failure_convergence.py tests/integration/test_agent_loop_context_validation.py tests/integration/test_followup_context_memory.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest tests/quality tests/tty
```

전체 회귀:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit tests/integration tests/quality tests/tty
```

실제 모델 선택 검증:

```bash
PYTHONDONTWRITEBYTECODE=1 HOME=/Users/kimtj319/Documents/02_personal/01_project/03_newcli/output/home PYTHONPATH=src .venv/bin/python output/evaluation_harness.py
```

## 완료 기준

- 전체 pytest가 통과한다.
- 실제 모델 stress 결과가 최소 다음 기준을 만족한다.
  - fail 0
  - warning 3 이하
  - average score 94 이상
  - criteria 3, 4, 9 각각 90 이상
- `src/allCode/agent/loop.py`가 350줄 이하로 분리된다.
- 새 파일 중 500줄 초과 파일이 없다.
- CompletionEvidence 없이 구현/수정 요청이 success가 되는 경로가 없다.
- conditional no-op은 명시적인 no-op evidence가 있을 때만 success/report가 가능하다.
- secret/API key/token은 session log, memory, final answer에 저장되지 않는다.

## 남은 리스크

- 실제 모델의 tool 선택 변동성은 prompt만으로 완전히 제거하기 어렵다. deterministic preflight와 schema gating을 함께 적용해야 한다.
- too-aggressive tool budget은 복잡한 조사 작업을 조기 차단할 수 있다. read-only 분석과 mutation/validation repair의 threshold를 분리해야 한다.
- no-op evidence 허용은 fake success와 혼동될 수 있다. conditional intent와 concrete target evidence가 모두 있을 때만 허용해야 한다.
- pseudo tool call recovery는 안전을 위해 절대 텍스트 JSON을 실행하지 않고, native tool call retry만 허용해야 한다.
