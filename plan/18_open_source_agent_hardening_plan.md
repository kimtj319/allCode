# 18. Open-Source Agent Pattern Hardening Plan

## 목적

이 문서는 `17_model_routed_tool_system_remediation_plan.md` 이후 현재 `src/allCode/` 코드 상태를 기준으로, 공개 CLI/코딩 에이전트의 검증된 패턴을 allCode에 현실적으로 추가 적용하기 위한 보강 계획서다.

핵심 목표는 새 기능 범위를 무리하게 늘리는 것이 아니라, 이미 구현된 구조를 더 안정적인 production-grade agent pipeline으로 굳히는 것이다.

- 모델이 라우팅과 tool 선택을 주도하되, safety/policy/approval/path boundary는 코드가 강제한다.
- 대형 코드베이스에서는 full-file dump 대신 repo map, search, ranged read, recent target을 조합한다.
- 모든 agent 동작은 action/observation/event/log로 추적 가능해야 한다.
- 실패, validation error, web unavailable, approval denied, stuck loop는 빈 답변이 아니라 사용자에게 설명 가능한 수렴 결과를 남긴다.
- 구현 범위는 현재 allCode 모듈과 테스트 구조 안에서 처리 가능한 수준으로 제한한다.

## 참조한 기존 계획서

이 문서는 아래 계약의 하위 보강 문서로 사용한다.

- `00_master_implementation_guide.md`: allCode의 목표, 모듈화, 단일 책임, 검증 없는 완료 금지.
- `01_open_source_alignment_contracts.md`: Aider, Gemini CLI, Qwen Code, OpenHands 기반 설계 계약.
- `03_core_contracts_plan.md`: core model/event/result가 provider/TUI에서 독립되어야 한다는 계약.
- `04_llm_loop_plan.md`: stream parser, heartbeat, timeout/retry, final answer gate, tool loop guard.
- `05_routing_policy_plan.md`: router는 실행하지 않고 strategy만 결정한다는 책임 경계.
- `06_tool_system_plan.md`: ToolResult 단일화, EditTransaction, approval preview, destructive shell 차단.
- `07_workspace_context_plan.md`: workspace boundary, safe path normalization, large repo full dump 금지.
- `08_context_memory_plan.md`: repo map, session summary, recent target, hierarchical memory 책임 분리.
- `09_generation_workflow_plan.md`: 신규/다중 파일 생성 workflow와 validation/self-repair 계약.
- `10_tui_app_plan.md`, `15_codex_tui_alignment_plan.md`, `16_codex_default_terminal_ui_plan.md`: terminal-native UI와 event rendering 계약.
- `11_quality_testing_plan.md`: quality score와 stress/e2e 평가 기준.
- `12_mvp_execution_plan.md`: milestone, completion evidence, 전체 회귀 검증 기준.
- `17_model_routed_tool_system_remediation_plan.md`: model-routed tool system, file/search/web/approval 보강안.

충돌 시 우선순위는 `00`~`12`와 안전 계약이 최상위이고, 그다음 `15`~`18`의 최신 보강 계약을 적용한다.

## 공개 문서 확인 결과

계획 작성 중 현재 공개 문서를 확인했다.

- Aider repo map은 전체 repository의 주요 class/function/type/signature를 compact map으로 제공하고, 대형 repo에서는 graph ranking과 token budget으로 관련 부분만 선택한다.
  - https://aider.chat/docs/repomap.html
- Aider lint/test workflow는 변경 후 lint/test command를 실행하고, non-zero exit output을 다시 모델에게 제공해 수리하도록 설계되어 있다.
  - https://aider.chat/docs/usage/lint-test.html
- Gemini CLI의 `GEMINI.md`는 global, project/ancestor, sub-directory 계층으로 context를 로드하고 `/memory show`, `/memory refresh`, `/memory add`로 관리한다.
  - https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- Qwen Code는 terminal-first agent이며, `modelProviders` 설정과 `envKey`를 통해 provider와 secret을 분리하고 `/tools`, `/auth`, `@file` 같은 terminal workflow를 제공한다.
  - https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/model-providers.md
  - https://qwenlm.github.io/qwen-code-docs/en/users/features/commands/
- OpenHands SDK는 type-safe `Action -> Observation` tool contract, append-only event log, hook, observability, stuck detector를 production agent의 기본 축으로 둔다.
  - https://docs.openhands.dev/sdk/arch/tool-system
  - https://docs.openhands.dev/sdk/arch/events
  - https://docs.openhands.dev/sdk/guides/hooks
  - https://docs.openhands.dev/sdk/guides/agent-stuck-detector

## 현재 코드 기준 적용 가능성

현재 allCode에는 아래 기반이 이미 있다.

- `src/allCode/agent/model_router.py`: structured JSON 기반 model router와 safe fallback.
- `src/allCode/agent/prompt_constraints.py`: deterministic constraint extractor.
- `src/allCode/tools/base.py`: `ToolDefinition`에 `risk`, `side_effects`, `output_mode`, `idempotent` 필드 존재.
- `src/allCode/tools/executor.py`: policy, approval, execution, evidence update, tool/validation event 발행.
- `src/allCode/tools/builtin/file_ops.py`: range-aware `read_file`, `write_file`, `patch_file`, `delete_path`.
- `src/allCode/tools/builtin/search.py`: `rg` 우선 검색과 structured `metadata.matches`.
- `src/allCode/tools/web_provider.py`: disabled/http/SearXNG provider와 `WebEvidence`.
- `src/allCode/memory/repo_map.py`, `repo_ranker.py`, `recent_targets.py`, `selector.py`: repo map과 memory selector 기반.
- `src/allCode/telemetry/session_logger.py`: JSONL session log 기반.
- `src/allCode/tui/terminal_*`: terminal-native composer와 stream rendering 기반.
- `output/evaluation_report.md`: 22개 stress scenario의 실제 실패/경고 분석.

따라서 이 계획은 MCP manager, cloud sandbox, multi-agent delegation, browser automation 같은 대형 확장은 제외한다. 대신 현재 모듈을 보강해 실패율을 낮추는 변경만 포함한다.

## P0. Stress Evaluation을 회귀 테스트로 승격

### 문제

`output/evaluation_report.md`의 S004~S019 실패/경고는 실제 모델과 실제 agent loop에서 나온 값이지만, 현재 정규 pytest 회귀로 완전히 고정되어 있지 않다. 기능 수정 후 같은 종류의 퇴행이 재발할 수 있다.

### 수정 대상

```text
output/evaluation_harness.py
tests/quality/test_stress_regression_matrix.py
tests/integration/test_agent_failure_convergence.py
tests/integration/test_existing_file_repair_routing.py
tests/unit/agent/test_model_router.py
tests/unit/agent/test_prompt_builder.py
tests/unit/tools/test_web_provider.py
```

### 구현 계획

1. `output/evaluation_harness.py`의 scenario 정의를 테스트에서 재사용 가능한 순수 데이터 구조로 분리한다.
2. 네트워크와 실제 모델이 없어도 재현 가능한 fake LLM scenario를 추가한다.
3. S005/S010/S011/S019의 `reasoning_only -> partial blocked summary` 경로를 integration test로 고정한다.
4. S008의 validation failure가 `failed` status를 유지하면서도 실패 원인을 final answer에 보존하는지 검증한다.
5. S009의 `calculator.py` 같은 기존 파일 target이 generation workflow로 넘어가지 않는지 검증한다.
6. S014의 web backend disabled가 `web_search_unavailable`과 설정 안내를 포함하는지 검증한다.
7. 실제 모델 stress는 선택 실행으로 유지하되, summary threshold를 정한다.

### 완료 기준

- fake 기반 stress 회귀는 일반 `python -m pytest tests/quality tests/integration`에 포함된다.
- 실제 모델 stress는 `ALLCODE_RUN_REAL_MODEL_EVAL=1`일 때만 실행한다.
- 기준 평균 목표는 다음과 같다.
  - fail 0
  - warning 3 이하
  - 평균 94점 이상
  - 기준 3 Loop Execution과 기준 4 Response Quality 각각 90점 이상

## P1. OpenHands식 Action/Observation 로그를 session log에 정규화

### 문제

현재 `AgentSessionLogger`는 event JSONL을 남기지만, 한 turn 안에서 어떤 user prompt가 어떤 route, model request, tool action, observation, recovery, final result로 이어졌는지 사람이 한눈에 묶어 보기 어렵다.

OpenHands의 event 문서는 action, observation, error, condensation 같은 이벤트를 append-only log로 남기고, source와 LLM role을 구분한다. allCode도 이미 event class가 있으므로 새 런타임을 만들 필요 없이 session log schema를 보강하면 된다.

### 수정 대상

```text
src/allCode/core/events.py
src/allCode/core/models.py
src/allCode/tools/executor.py
src/allCode/agent/loop.py
src/allCode/telemetry/schema.py
src/allCode/telemetry/session_logger.py
tests/unit/telemetry/test_session_logger.py
tests/integration/test_session_log_trace.py
```

### 구현 계획

1. 모든 turn event에 `turn_id`, `trace_id`, 선택적 `span_id`, `parent_span_id`를 넣는다.
2. `ToolCallRequested`는 `action` log type으로, `ToolExecutionFinished`는 `observation` log type으로 normalized view를 저장한다.
3. policy denied, approval denied, tool not found, parser error는 `agent_error_observation`으로 저장해 모델 복구 가능 오류와 runtime terminal error를 구분한다.
4. `ModelRequestPrepared`, `ModelResponseParsed`, `ModelMetricsRecorded`를 하나의 model span으로 묶는다.
5. log record에는 raw provider payload를 저장하지 않고, 현재 redaction 경로를 통과한 primitive metadata만 저장한다.
6. session log 파일 경로는 기존 계약대로 `~/.allcode/session/{year}/{month}/{day}/{session_name}.jsonl`을 유지한다.

### 완료 기준

- 한 tool call마다 action record와 observation record가 같은 `span_id`로 연결된다.
- failure/partial turn도 final `turn_result_ready` record를 남긴다.
- token/char/request duration이 model span에 기록된다.
- secret/API key/token은 session log에 남지 않는다.

## P2. OpenHands Stuck Detector 패턴을 현재 ToolLoopGuard에 확장

### 문제

현재 `ToolLoopGuard`는 tool name과 canonical arguments 반복을 잡지만, 실제 실패 사례에서는 `list_directory` 반복 후 `reasoning_only`가 이어지는 식의 복합 stuck pattern도 발생했다.

OpenHands stuck detector는 action-observation 반복, action-error 반복, agent monologue를 semantic content 기준으로 탐지한다. allCode에는 이미 `RecoveryState`, `ToolLoopSignature`, `ModelResponseParsed`가 있으므로 lightweight detector로 확장 가능하다.

### 수정 대상

```text
src/allCode/agent/recovery.py
src/allCode/agent/loop.py
src/allCode/core/result.py
tests/unit/agent/test_recovery.py
tests/integration/test_agent_failure_convergence.py
```

### 구현 계획

1. `ToolLoopGuard`에 `record_observation(tool_call, tool_result)`를 추가한다.
2. signature는 tool name, canonical target, normalized error_type, observation summary를 사용한다.
3. 다음 패턴을 별도로 판정한다.
   - same action + same observation 3회
   - same action + same error 2회
   - final-answer request 이후 reasoning-only 2회
   - search/list만 반복하고 target tool로 진전이 없는 경우
4. stuck 발생 시 `RecoveryState(reason="tool_loop" | "reasoning_only" | "no_progress", blocked=True)`를 기록한다.
5. stuck 상태에서는 같은 tool schema를 다시 노출하지 않고, final answer request 또는 clarification request로 전환한다.

### 완료 기준

- 반복 tool call은 무한 round로 가지 않고 partial/blocked summary로 수렴한다.
- 사용자에게 “무엇을 시도했고 왜 막혔는지”가 표시된다.
- 정상적인 서로 다른 파일 range read나 다른 search query는 stuck으로 오탐하지 않는다.

## P3. Aider식 Repo Map을 Search Tool 선택 전에 사용

### 문제

`search_files`는 `rg`를 우선 사용하지만, 대형 repo에서는 query가 넓을 경우 너무 많은 결과를 만들 수 있다. Aider repo map처럼 symbol/signature map이 먼저 후보 파일을 줄이고, 그다음 ranged read로 들어가야 token/cost가 안정된다.

### 수정 대상

```text
src/allCode/memory/repo_map.py
src/allCode/memory/repo_ranker.py
src/allCode/memory/selector.py
src/allCode/tools/builtin/search.py
src/allCode/agent/context.py
src/allCode/agent/prompt_builder.py
tests/unit/memory/test_repo_map.py
tests/unit/tools/test_search_tool.py
tests/integration/test_large_repo_context_selection.py
```

### 구현 계획

1. `SearchFilesTool` 결과 metadata에 `rank_reason`, `repo_map_hit`, `symbol_hit`를 추가한다.
2. `ContextMemorySelector`가 prompt에서 symbol-like token을 찾으면 repo map compact text를 먼저 포함한다.
3. `RepoRanker`는 recent target, symbol definition, import/reference hit, path similarity를 점수화한다.
4. 검색 결과가 `max_results`를 초과하면 repo ranker로 상위 파일만 남긴다.
5. `PromptBuilder`는 “search_files -> ranged read_file -> final” 순서를 명확히 넣되, 하드코딩된 파일명/테스트명은 넣지 않는다.
6. repo map cache invalidation은 `WorkspaceIndex`의 path, mtime, size 기반으로 유지한다.

### 완료 기준

- 대형 repo 시나리오에서 첫 context는 full-file dump가 아니라 repo map/search summary다.
- 모델이 “해당 함수” 후속 질문을 받으면 recent target과 repo map을 함께 사용한다.
- `read_file`은 기본적으로 필요한 range만 읽고, 큰 파일 전체 출력은 final transcript에 들어가지 않는다.

## P4. Gemini CLI식 Hierarchical Memory의 사용자 가시성 강화

### 문제

현재 `ALLCODE.md` 기반 memory store는 존재하지만, 사용자가 어떤 global/project/directory/session memory가 실제로 모델 입력 전에 들어갔는지 확인하기 어렵다. Gemini CLI는 footer와 `/memory show/refresh/add`로 context 적용 상태를 노출한다.

### 수정 대상

```text
src/allCode/memory/store.py
src/allCode/memory/hierarchy.py
src/allCode/memory/selector.py
src/allCode/memory/commands.py
src/allCode/tui/slash_commands.py
src/allCode/tui/command_registry.py
src/allCode/tui/terminal_activity.py
tests/unit/memory/test_hierarchy.py
tests/unit/memory/test_commands.py
tests/tty/test_terminal_memory_commands.py
```

### 구현 계획

1. memory load 결과에 `scope`, `path`, `redacted`, `token_estimate`를 포함한다.
2. `/memory show`는 active context에 들어간 memory만 보여주고, secret redaction 여부를 표시한다.
3. `/memory refresh`는 `~/.allcode/ALLCODE.md`, workspace `.allCode/ALLCODE.md`, directory `.allCode/ALLCODE.md`, session summary를 다시 로드한다.
4. terminal footer/status에 “memory N files / repo map M entries” 같은 짧은 상태를 제공한다.
5. auto-memory는 기존 계약대로 inbox에만 저장하고 승인 전 active memory에 넣지 않는다.

### 완료 기준

- 사용자가 `ALLCODE.md`가 반영됐는지 slash command로 확인할 수 있다.
- secret/token/API key는 memory show와 session log에 노출되지 않는다.
- workspace와 memory는 순환 import 없이 `agent/context.py`를 통해서만 결합된다.

## P5. Qwen Code식 Provider Profile과 Tool Visibility 정리

### 문제

allCode는 OpenAI-compatible adapter와 env/config 기반 모델 설정을 갖고 있지만, 사용자가 현재 어떤 provider/model/tool set으로 실행 중인지 명확히 보기 어렵다. Qwen Code는 provider 설정을 `modelProviders`와 `envKey`로 관리하고 `/tools`, `/auth`, `/model` 같은 terminal workflow를 제공한다.

MVP에서 새 auth wizard를 만들 필요는 없다. 대신 현재 config와 command registry에 맞는 최소 상태 확인 기능을 추가한다.

### 수정 대상

```text
src/allCode/config/schema.py
src/allCode/config/manager.py
src/allCode/llm/settings.py
src/allCode/tui/command_registry.py
src/allCode/tui/slash_commands.py
src/allCode/tools/registry.py
src/allCode/main.py
README.md
tests/unit/config/test_config_manager.py
tests/tty/test_terminal_slash_commands.py
```

### 구현 계획

1. `/tools` command가 현재 route와 무관한 전체 등록 tool list를 group/risk/read_only/approval 기준으로 보여준다.
2. `/model` command는 현재 model name, base URL host, api key env name, live/fake mode를 표시한다. 실제 secret 값은 출력하지 않는다.
3. `/config` command는 config 파일 경로, workspace, approval mode, web backend 상태를 표시한다.
4. config schema는 provider profile 확장 여지를 갖되, MVP에서는 기존 `ALLCODE_MODEL`, `ALLCODE_BASE_URL`, `ALLCODE_API_KEY` 우선순위를 유지한다.
5. provider-specific option tuning은 MVP 이후로 미룬다.

### 완료 기준

- 사용자는 `allcode` 실행 후 slash command만으로 모델/도구/설정 상태를 확인할 수 있다.
- fake LLM fallback은 명시 설정 또는 테스트에서만 사용되고, 기본 실행은 사용자가 설정한 모델을 사용한다.
- secret은 README, session log, slash command output에 노출되지 않는다.

## P6. Aider식 Validation/Fix Loop를 기존 Workflow와 Direct Edit 모두에 적용

### 문제

generation workflow에는 validation/self-repair가 있지만, direct file edit tool loop에서는 validation 실패 후 어떤 수리 행동으로 이어질지 provider 응답에 많이 의존한다. Aider lint/test workflow처럼 non-zero validation output을 compact하게 모델에게 다시 제공하는 표준 루프가 필요하다.

### 수정 대상

```text
src/allCode/agent/validation_runner.py
src/allCode/agent/prompt_builder.py
src/allCode/agent/loop.py
src/allCode/agent/completion_checker.py
src/allCode/agent/final_reporter.py
tests/integration/test_direct_edit_validation_repair.py
tests/integration/test_generation_workflow.py
```

### 구현 계획

1. direct edit route에서 validation_required이면 file change 후 `run_tests` 결과를 `ValidationResult`로 표준화한다.
2. validation 실패 로그는 전체 stdout/stderr가 아니라 실패 line, traceback, assertion, command, exit code 중심으로 요약한다.
3. validation 실패 후 모델에게 `validation_repair_request`를 보내되, 같은 error_hash가 반복되면 더 이상 반복하지 않는다.
4. final answer는 success가 아니어도 실패 원인, 실행한 명령, 다음 조치를 포함한다.
5. workflow와 direct edit 모두 `CompletionEvidence.validation_commands`와 `validation_passed`를 동일하게 사용한다.

### 완료 기준

- 기존 파일 수정 요청은 변경, 검증, 실패 로그 요약, repair, 재검증 흐름을 관찰 가능하게 남긴다.
- validation_required 요청에서 validation_passed가 True가 아니면 success가 되지 않는다.
- 실패 final answer는 빈 문자열이 아니며 사용자가 다음 행동을 판단할 수 있다.

## P7. OpenHands Hook 패턴을 allCode 내부 Event Hook으로 축소 적용

### 문제

OpenHands hooks는 logging, auditing, policy enforcement를 core loop 외부에서 붙이게 한다. allCode에 shell hook 시스템을 그대로 추가하면 범위가 커진다. 대신 event hook registry를 내부 Python callback으로만 제공하면 현재 구조에서 현실적으로 관찰성과 정책 확장이 가능하다.

### 수정 대상

```text
src/allCode/core/event_bus.py
src/allCode/telemetry/session_logger.py
src/allCode/tools/executor.py
src/allCode/config/schema.py
tests/unit/core/test_event_bus.py
tests/unit/tools/test_tool_executor.py
```

### 구현 계획

1. `AsyncEventBus`에 subscriber failure가 agent loop를 깨지 않도록 error isolation을 명확히 테스트한다.
2. `ToolExecutor`에는 pre-tool/post-tool Python hook list를 선택적으로 받게 한다.
3. pre-tool hook은 `allow/block/reason/additional_context`만 반환할 수 있다.
4. hook block은 `policy_denied`와 구분되는 `hook_denied` ToolResult로 기록한다.
5. 외부 shell hook, plugin hook, MCP hook은 MVP 이후로 미룬다.

### 완료 기준

- telemetry hook 실패는 agent 실행을 중단하지 않는다.
- policy/approval/hook denial은 서로 다른 error_type으로 관찰된다.
- hook 결과는 session log에 남고 TUI에는 사용자 친화 문구로 표시된다.

## P8. Web Search는 SearXNG Evidence Quality를 높이고 Raw 출력 금지 유지

### 문제

SearXNG provider는 이미 존재하지만, evidence quality와 disabled fallback의 최종 답변 품질을 더 고정해야 한다. web 결과는 raw JSON이 아니라 evidence bundle이어야 한다는 `17` 계약을 유지한다.

### 수정 대상

```text
src/allCode/tools/web_provider.py
src/allCode/tools/builtin/web.py
src/allCode/agent/prompt_builder.py
tests/unit/tools/test_web_provider.py
tests/integration/test_web_search_optional.py
tests/quality/test_stress_regression_matrix.py
```

### 구현 계획

1. `WebEvidence`에 `display_domain`, `snippet_hash`, `retrieved_at` metadata를 추가한다.
2. evidence item은 title/url/snippet 중 최소 url 또는 title이 있어야 유효하다.
3. SearXNG 403/406/non-JSON은 `web_search_unavailable`로 표준화한다.
4. `ToolResult.content`는 짧은 summary만 담고, raw response는 metadata에도 저장하지 않는다.
5. final answer prompt에는 “evidence가 없으면 최신 사실처럼 단정하지 말라”는 규칙을 유지한다.

### 완료 기준

- backend disabled 상태에서도 사용자는 무엇을 설정해야 하는지 알 수 있다.
- backend enabled 상태에서는 answer가 evidence title/url/snippet 기반으로 작성된다.
- web search 결과 raw JSON이 final transcript에 직접 노출되지 않는다.

## P9. Terminal UI에 Agent Progress를 더 명확히 연결

### 문제

사용자 피드백에서 “요청이 진행 중인지 답변 작성 중인지 알 방법이 없다”는 문제가 반복됐다. 현재 terminal UI는 많은 모듈로 분리되어 있으므로 대형 UI 재작성 대신 event-to-status mapping을 강화한다.

### 수정 대상

```text
src/allCode/tui/renderers.py
src/allCode/tui/terminal_activity.py
src/allCode/tui/terminal_answer_renderer.py
src/allCode/tui/terminal_input.py
src/allCode/tui/messages.py
tests/tty/test_terminal_body_output.py
tests/tty/test_terminal_codex_default_ui.py
```

### 구현 계획

1. `ModelRequestPrepared`: “모델에 요청 중”.
2. 첫 `ModelTextDelta`: “답변 작성 중”.
3. `ToolCallRequested`: “도구 준비 중: {tool}”.
4. `ToolExecutionStarted`: “도구 실행 중: {tool}”.
5. `ToolExecutionFinished`: “도구 결과를 반영 중”.
6. `ModelStreamHeartbeat`: slow stream spinner 유지.
7. `RecoveryStateUpdated`: 내부 debug 문구 대신 “응답을 다시 요청 중” 또는 “검증 근거 부족으로 추가 확인 중”.
8. final answer gate 차단은 완료처럼 보이지 않게 partial/blocked 상태로 표시한다.

### 완료 기준

- 실제 PTY smoke에서 질문 제출 후 model/tool/final 단계가 사용자에게 구분된다.
- long tool output은 folded/artifact로 남고 transcript를 오염시키지 않는다.
- markdown table은 기존 holdback/flush 정책을 유지해 문장 단위 또는 block 단위로 안정 출력된다.

## P10. 구현 순서

1. P0 회귀 테스트를 먼저 추가해 현재 실패 축을 고정한다.
2. P1 session log trace/span normalization을 구현한다.
3. P2 stuck detector를 `ToolLoopGuard`에 확장한다.
4. P6 direct edit validation/fix loop를 보강한다.
5. P3 repo map 기반 search/context ranking을 보강한다.
6. P4 memory visibility와 `/memory` 상태 출력을 보강한다.
7. P5 `/tools`, `/model`, `/config` 상태 command를 보강한다.
8. P8 web evidence quality를 보강한다.
9. P9 terminal status mapping을 보강한다.
10. unit -> integration -> quality -> tty -> optional real-model stress 순서로 검증한다.

## 검증 명령

기본 회귀:

```bash
python -m pytest tests/unit tests/integration tests/quality tests/tty
```

보강 영역별:

```bash
python -m pytest tests/unit/agent tests/integration/test_agent_failure_convergence.py
python -m pytest tests/unit/tools tests/integration/test_direct_edit_validation_repair.py
python -m pytest tests/unit/memory tests/integration/test_large_repo_context_selection.py
python -m pytest tests/unit/telemetry tests/integration/test_session_log_trace.py
python -m pytest tests/tty
```

선택 실제 모델 stress:

```bash
ALLCODE_RUN_REAL_MODEL_EVAL=1 PYTHONPATH=src .venv/bin/python output/evaluation_harness.py
```

## 완료 기준

- `output/evaluation_report.md`의 S004~S019 실패/경고 유형이 fake regression test로 고정된다.
- 실제 모델 stress 재실행 시 fail 0, warning 3 이하, 평균 94점 이상을 목표로 한다.
- action/observation/session log가 turn 단위 trace로 연결된다.
- 반복 tool/action/error/reasoning-only stuck은 partial/blocked summary로 수렴한다.
- 대형 repo context는 repo map/search/ranged read 중심으로 구성된다.
- memory 적용 상태는 slash command와 status에서 확인할 수 있다.
- provider/model/tool/config 상태는 secret 없이 확인할 수 있다.
- validation failure는 success가 아니지만 사용자에게 원인과 다음 조치를 남긴다.
- web search는 evidence bundle 기반이고 raw JSON을 final answer에 직접 출력하지 않는다.
- terminal UI는 모델 요청, 도구 실행, 복구, final gate 상태를 사용자가 구분할 수 있게 표시한다.

## MVP 이후로 미룰 항목

다음 항목은 현재 코드 기준에서 범위가 커서 이번 보강 대상에서 제외한다.

- 외부 shell hook/plugin hook 시스템.
- MCP server manager와 remote MCP auth flow.
- cloud/docker sandbox backend.
- multi-agent review/delegation.
- git auto-commit/PR 생성 자동화.
- browser automation과 long-running background job UI.
- provider별 advanced reasoning option 자동 튜닝.
