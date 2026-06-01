# 12. MVP 점진적 실행 계획

## 목적

이 문서는 `00`~`12` 계획 전체를 GPT-5.5 같은 모델에게 한 번에 구현 요청으로 전달할 때 실패 가능성을 낮추기 위한 실행 전용 계획서다. 전체 구현을 한 번에 요청하더라도 모델은 내부적으로 아래 마일스톤 순서를 따라야 하며, 각 마일스톤의 검증 기준을 통과하기 전 다음 단계로 넘어가지 않는다.

## 기본 원칙

- 핵심 구현을 `pass`, `TODO`, `...`, `구현 예정`으로 대체하지 않는다.
- 한 파일에 과도한 책임을 몰지 않는다. 300줄 이상이면 분리 후보로 기록하고, 500줄 이상은 원칙적으로 허용하지 않는다.
- 파일 분리는 줄 수만 기준으로 하지 않고 단일 책임, 응집도, 단방향 의존성, 순환 import 방지를 함께 판단한다.
- 실제 파일 생성 또는 수정 없이 구현 완료 답변을 내지 않는다.
- 모든 주요 단계는 테스트 또는 명시적 검증 명령으로 확인한다.
- 대규모 프로젝트 생성은 skeleton-first 방식으로 진행한다.

## 출력 토큰 한계 대비 중단/재개 규칙

GPT-5.5가 긴 출력 한계에 도달할 수 있다는 점을 전제로 한다. 전체 구현 요청을 한 번에 받더라도 핵심 구현을 생략하지 말고 아래 규칙을 따른다.

1. 한 번의 응답에서 모든 마일스톤을 완전하게 구현하지 못하면, 마지막으로 완성 가능한 마일스톤 또는 파일까지만 완전한 코드로 작성한다.
2. 뒤쪽 마일스톤을 `pass`, `TODO`, 빈 함수, 주석 스켈레톤으로 채워 응답을 끝내지 않는다.
3. 중단이 필요하면 응답 최하단에 아래 마커를 정확히 출력한다.

```markdown
[SUSPEND_MARKER]
- CURRENT_MILESTONE: Milestone X
- COMPLETED_FILES:
  - src/allCode/example.py
- PENDING_FILES:
  - src/allCode/next_file.py
- NEXT_STEP_ACTION: 다음 턴에서 어떤 파일의 어떤 함수부터 구현할지 작성
```

4. 사용자가 “이어서 진행”이라고 요청하면 이미 완료한 파일 전문을 다시 출력하지 않는다.
5. 재개 시 `PENDING_FILES` 첫 항목부터 구현하고, 직전 테스트 실패가 있으면 해당 실패를 먼저 수정한다.

## 권장 요청 분할

가장 안정적인 구현 순서는 전체 일괄 요청이 아니라 다음 5회 분할이다.

1. 요청 1: Milestone 1 (Skeleton & Config) + Milestone 2 (Core Contracts & Event Bus)
2. 요청 2: Milestone 3 (Mock Loop & Headless) + Milestone 4 (LLM Adapter & Response Parser)
3. 요청 3: Milestone 5 (Router & Tool System) + Milestone 6 (Workspace & Context)
4. 요청 4: Milestone 7 (Context Memory)
5. 요청 5: Milestone 8 (Workflow) + Milestone 9 (Minimal TUI) + Milestone 10 (Quality Gate)

단, 사용자가 전체 구현을 한 번에 요청할 경우에도 모델은 내부적으로 위 순서와 suspend/resume 규칙을 따라야 한다.

### 1단계 완료 후 필수 보강 체크포인트

이미 Milestone 1~4의 1차 구현이 끝났더라도 다음 요청으로 넘어가기 전에 아래 보강을 반드시 적용한다. 이 체크포인트는 2단계 Tool/Policy 구현 전에 완료되어야 한다.

필수 보강:

- `core/result.py`에 `CompletionEvidence`, `RecoveryState`, `ToolLoopSignature`를 추가한다.
- `TurnResult`가 완료 근거와 복구 상태를 포함하도록 확장한다.
- 구현/수정 요청에서 실제 변경 근거 없이 `success`를 반환하지 않도록 테스트한다.
- fake LLM에 `empty_response`, `reasoning_only`, `length_cutoff`, `slow_stream`, `same_tool_three_times` 시나리오를 추가한다.
- slow model 대응은 모델명 분기가 아니라 heartbeat/status event와 timeout/retry 정책으로 처리한다.
- completion evidence가 없으면 final answer gate가 완료 답변을 차단하도록 한다.

검증:

```bash
python -m pytest tests/unit/core tests/unit/llm tests/integration/test_mock_agent_loop.py tests/integration/test_headless_runner.py
```

## MVP 범위

1차 MVP에 포함한다.

- Core model/event/error 계약
- Async event bus
- Fake LLM 기반 agent loop
- OpenAI-compatible LLM adapter 기본형
- Response parser 상태 머신
- Router와 ToolPolicy
- 파일/검색/셸/테스트 기본 도구
- Workspace root와 path resolver
- Lightweight file indexer
- Generation workflow와 completion checker
- Textual 기반 최소 TUI
- Slash command palette 기본형
- Fake LLM 기반 unit/integration test
- Context memory MVP: hierarchical memory, session summary, recent target, repo map, context compactor

## 전역 데이터 흐름

```text
User Input
  -> TUI.InputBox OR Headless.argv
  -> EventBus.publish(UserPromptSubmitted)
  -> AgentLoop.run_turn()
    -> Router.classify() -> RoutingDecision
    -> ContextBuilder.build()
    -> PromptBuilder.build()
    -> LLMClient.stream()
    -> ResponseParser.parse()
    -> ToolPolicy.check()
    -> ToolExecutor.execute()
    -> Workflow.run_step() when modify/generation
    -> CompletionChecker.check()
    -> FinalReporter.report()
  -> EventBus.publish(FinalAnswerReady)
  -> TUI.Transcript.render() OR Headless.stdout
```

## 구현 관계 규칙

- `agent/loop.py`는 workflow를 직접 구현하지 않고 `agent/workflow.py`에 위임한다.
- `agent/workflow.py`는 LLM provider를 직접 호출하지 않고 loop가 전달한 tool/context 인터페이스를 사용한다.
- `tools/executor.py`는 UI 이벤트를 직접 렌더링하지 않고 core event만 발행한다.
- `tui/*`는 agent 내부 상태를 import하지 않고 core event와 command API만 사용한다.

1차 MVP에서 제외한다.

- 고급 subagent 시스템
- 플러그인 marketplace
- 복잡한 tree-sitter 다국어 full index
- 원격 sandbox backend
- 고급 MCP 서버 관리 UI
- 장기 실행 background job browser 고도화
- provider별 고급 reasoning option 최적화

## Milestone 1. Skeleton, Configuration and Package Structure

### 생성 파일

```text
src/allCode/__init__.py
src/allCode/core/__init__.py
src/allCode/llm/__init__.py
src/allCode/llm/adapters/__init__.py
src/allCode/agent/__init__.py
src/allCode/tools/__init__.py
src/allCode/tools/builtin/__init__.py
src/allCode/workspace/__init__.py
src/allCode/memory/__init__.py
src/allCode/tui/__init__.py
src/allCode/config/__init__.py
src/allCode/config/schema.py
src/allCode/config/manager.py
src/allCode/config/defaults.py
src/allCode/main.py
src/allCode/__main__.py
tests/unit/config/test_config_manager.py
tests/unit/test_entrypoint.py
```

### 구현 내용

- 패키지 skeleton 구성: 위 명시된 모든 디렉터리에 `__init__.py` 패키지 선언 파일을 생성하여 패키지 구조와 임포트 경로 오류를 원천 차단한다.
- `AppConfig`, `ModelConfig`, `WorkspaceConfig`, `ApprovalConfig` 등 Pydantic v2 기반 설정을 구현한다.
- `~/.config/allCode/config.yaml` 로드 및 `ALLCODE_CONFIG` 환경변수 처리 계약을 완성한다.
- CLI 진입점(`main.py`, `__main__.py`)을 설계하고 argv 파싱(설정 flag 우선순위 병합) 기능을 구현한다.

### 검증

```bash
python -m pytest tests/unit/config tests/unit/test_entrypoint.py
```

---

## Milestone 2. Core Contracts and Event Bus

### 생성 파일

```text
src/allCode/core/models.py
src/allCode/core/events.py
src/allCode/core/event_bus.py
src/allCode/core/errors.py
src/allCode/core/result.py
tests/unit/core/test_models.py
tests/unit/core/test_events.py
tests/unit/core/test_event_bus.py
```

### 구현 내용

- Pydantic v2 기반 `Message`, `ToolCall`, `ToolResult`, `TurnInput`, `TurnState`, `TokenUsage`, `WorkspaceRef`를 정의한다.
- `TurnResult` 모델을 정의하여 turn의 성공, 실패, 생성/수정 파일 인벤토리, 검증 여부, 토큰 사용량을 명세한다.
- `AgentEvent` base class와 주요 이벤트 타입을 정의한다.
- `AsyncEventBus`를 구현한다. publish, subscribe, close 인터페이스를 제공한다.
- UI 라이브러리와 provider SDK는 core 계층에서 import하지 않는다.

### 검증

```bash
python -m pytest tests/unit/core
```

---

## Milestone 3. Mock Agent Loop and Headless Runner

### 생성 파일

```text
src/allCode/llm/client.py
src/allCode/llm/fake.py
src/allCode/agent/loop.py
src/allCode/agent/prompt_builder.py
src/allCode/agent/recovery.py
src/allCode/tools/base.py
src/allCode/tools/registry.py
src/allCode/headless.py
tests/integration/test_mock_agent_loop.py
tests/integration/test_headless_runner.py
```

### 구현 내용

- 실제 LLM 호출 없이 fake LLM이 텍스트 응답과 tool call 응답을 반환하도록 한다.
- agent loop는 이벤트를 발행하고 tool result를 message로 누적한다.
- 빈 응답, tool-call-only 반복, max rounds 도달을 recovery로 처리한다.
- `tools/base.py` 정의: `BaseTool`, `ToolDefinition`, `ToolContext`만 정의하며, `ToolCall`과 `ToolResult`는 `core/models.py`에서 가져와서 사용한다.
- `headless.py` 구현: TUI 화면 없이 `stdin -> config 로드 -> agent loop 실행 -> stdout 결과 및 exit code 리턴`하는 headless runner E2E 경로를 구현한다.

### 검증

```bash
python -m pytest tests/integration/test_mock_agent_loop.py tests/integration/test_headless_runner.py
```

---

## Milestone 4. LLM Adapter and Response Parser

### 생성 파일

```text
src/allCode/llm/adapters/openai_compatible.py
src/allCode/llm/response_parser.py
src/allCode/llm/settings.py
tests/unit/llm/test_response_parser.py
tests/unit/llm/test_openai_compatible_adapter.py
```

### 구현 내용

- OpenAI-compatible chat completion 형식을 표준 `ModelEvent`로 변환한다.
- 스트림 파서는 미완성 JSON, 중간에 끊긴 tool call delta, 빈 응답, length cutoff를 안전하게 분류한다.
- 실제 네트워크 테스트는 기본 unit test에서 제외하고 mock transport를 사용한다.

### 검증

```bash
python -m pytest tests/unit/llm
```

---

## Milestone 5. Router, Policy, and Tool System

### 생성 파일

```text
src/allCode/agent/intent.py
src/allCode/agent/router.py
src/allCode/agent/policy.py
src/allCode/tools/executor.py
src/allCode/tools/approval.py
src/allCode/tools/diff.py
src/allCode/tools/builtin/file_ops.py
src/allCode/tools/builtin/search.py
src/allCode/tools/builtin/shell.py
src/allCode/tools/builtin/web.py
tests/unit/agent/test_router.py
tests/unit/agent/test_policy.py
tests/unit/tools/test_tool_executor.py
tests/unit/tools/test_file_ops.py
```

### 구현 내용

- `answer`, `inspect`, `modify`, `operate` 라우팅을 구현한다.
- ToolPolicy는 라우팅 결과에 따라 도구 사용 가능 범위를 반환한다.
- `patch_file`은 search/replace 블록 기반으로 구현하고, 0개 또는 2개 이상 매칭 시 실패한다.
- shell 도구는 timeout, cwd, destructive approval을 기본으로 가진다.
- `ToolCall`과 `ToolResult` 모델은 `core/models.py`를 단일 진실 공급원(Single Source of Truth)으로 사용한다.

### 검증

```bash
python -m pytest tests/unit/agent tests/unit/tools
```

---

## Milestone 6. Workspace and Context

### 생성 파일

```text
src/allCode/workspace/roots.py
src/allCode/workspace/indexer.py
src/allCode/workspace/path_resolver.py
src/allCode/workspace/symbol_index.py
src/allCode/agent/context.py
tests/unit/workspace/test_path_resolver.py
tests/unit/workspace/test_indexer.py
tests/unit/agent/test_context_builder.py
```

### 구현 내용

- 다중 workspace root를 관리한다.
- 프롬프트에 있는 상대/절대 경로를 안전하게 해석한다.
- symbol index는 lightweight regex parser를 기본 제공하고 외부 parser가 없어도 실패하지 않는다.
- 대형 코드베이스에서는 skeleton-only context를 사용한다.
- 기존의 중복된 `agent/memory.py` 파일은 완전히 배제하며, 모든 컨텍스트와 기억 관리는 Milestone 7의 `memory/*` 모듈군에 단방향으로 위임한다.

### 검증

```bash
python -m pytest tests/unit/workspace tests/unit/agent/test_context_builder.py
```

---

## Milestone 7. Context Memory

### 생성 파일

```text
src/allCode/memory/schema.py
src/allCode/memory/store.py
src/allCode/memory/hierarchy.py
src/allCode/memory/session_store.py
src/allCode/memory/session_summary.py
src/allCode/memory/recent_targets.py
src/allCode/memory/repo_map.py
src/allCode/memory/repo_ranker.py
src/allCode/memory/compactor.py
src/allCode/memory/selector.py
src/allCode/memory/auto_memory.py
src/allCode/memory/inbox.py
src/allCode/memory/commands.py
tests/unit/memory/test_hierarchy.py
tests/unit/memory/test_session_store.py
tests/unit/memory/test_recent_targets.py
tests/unit/memory/test_repo_map.py
tests/unit/memory/test_compactor.py
tests/unit/memory/test_auto_memory.py
tests/integration/test_followup_context_memory.py
```

### 구현 내용

- Aider식 compact repo map을 구현한다.
- Gemini CLI식 global/project/directory/session hierarchical memory를 구현한다.
- 최근 target memory로 후속 질문의 “그 파일”, “해당 함수”를 해석한다.
- session transcript와 summary를 저장/복원한다.
- context budget 비율에 따라 active file, repo map, session summary, durable memory를 압축한다.
- auto-memory는 후보를 inbox에만 저장하고 승인 전에는 active context에 넣지 않는다.
- secret/token/API key redaction을 적용한다.

### 검증

```bash
python -m pytest tests/unit/memory tests/integration/test_followup_context_memory.py
```

---

## Milestone 8. Generation Workflow

### 생성 파일

```text
src/allCode/agent/task_plan.py
src/allCode/agent/workflow.py
src/allCode/agent/completion_checker.py
src/allCode/agent/validation_runner.py
src/allCode/agent/final_reporter.py
tests/integration/test_generation_workflow.py
```

### 구현 내용

- 새 프로젝트 또는 다중 파일 생성 요청에서 skeleton-first 절차를 적용한다.
- completion checker는 실제 파일 변경, 필수 파일 존재, 비어 있지 않은 파일, 검증 실행 여부를 확인한다.
- self-repair는 동일 에러 해시 2회 연속 또는 총 5회 시도 시 중단한다.
- edit transaction snapshot과 rollback 지점을 둔다.

### 검증

```bash
python -m pytest tests/integration/test_generation_workflow.py
```

---

## Milestone 9. Minimal Textual TUI

### 생성 파일

```text
src/allCode/tui/app.py
src/allCode/tui/layout.py
src/allCode/tui/input_box.py
src/allCode/tui/command_palette.py
src/allCode/tui/renderers.py
src/allCode/tui/approval_panel.py
tests/tty/test_tui_smoke.py
```

### 구현 내용

- Textual 기반 transcript, status bar, input box를 구현한다.
- Agent loop는 Textual background worker에서 실행한다.
- UI와 agent loop는 event bus로만 통신한다.
- slash palette는 `/` 입력 시 후보를 표시한다.

### 검증

```bash
python -m pytest tests/tty/test_tui_smoke.py
```

## Milestone 10. End-to-End Quality Gate

### 생성 파일

```text
tests/quality/prompt_matrix.yaml
tests/quality/test_quality_matrix.py
tests/helpers/fake_llm_scenarios.py
```

### 구현 내용

- 일반 질문, 코드 분석, 파일 수정, 신규 프로젝트 생성, 오류 수리, 웹 검색 시나리오를 fake LLM으로 검증한다.
- 답변 직접성, 도구 적합성, 반복 도구 호출, final report 품질을 점수화한다.
- 실제 LLM 연결 테스트는 선택 실행으로 분리한다.

### 검증

```bash
python -m pytest tests/quality
```

## 전체 구현 요청 시 모델 지시문

GPT-5.5에게 전체 구현을 요청할 때는 다음 원칙을 함께 전달한다.

1. 이 문서의 마일스톤 순서를 내부 실행 순서로 사용한다.
2. 각 마일스톤이 끝날 때 테스트를 실행한다.
3. 실패하면 다음 마일스톤으로 넘어가지 말고 수정한다.
4. 핵심 구현을 생략하지 않는다.
5. 생성 파일과 검증 결과를 최종 답변에 반드시 포함한다.
6. 파일이 과도하게 길어지면 역할 기준으로 분리한다.
7. 특정 테스트 프롬프트나 특정 프로젝트명을 하드코딩하지 않는다.
8. 구현 중 설계가 모호하면 임의로 확장하지 말고 `01_open_source_alignment_contracts.md`의 계약을 우선 적용한다.

## 최종 완료 기준

- `python -m pytest tests/unit tests/integration tests/quality`가 통과한다.
- TUI smoke test가 통과한다.
- 파일 변경 요청에서 실제 파일 변경 없이 완료되지 않는다.
- read-only 요청에서 mutation 도구가 실행되지 않는다.
- 대규모 프로젝트 생성 요청에서 skeleton, implementation, validation, repair, final report 단계가 관찰된다.
- 500줄 초과 파일이 없거나 분리 계획이 문서화되어 있다.

## 공개 오픈소스 참조 기반 보강 계약

MVP 실행은 Aider식 repo map, Gemini CLI식 context memory, OpenHands식 event/action 관찰성, Qwen Code식 provider-neutral adapter를 순서대로 붙이는 방식으로 진행한다.

- Milestone 7은 선택 사항이 아니라 대형 코드베이스와 멀티턴 품질을 위한 필수 단계다.
- 각 요청 단위는 독립적으로 테스트 가능해야 하며, 이전 요청 산출물이 없어도 실패 원인이 명확히 드러나야 한다.
- 전체 구현 요청을 한 번에 넣더라도 내부적으로는 5회 분할과 동일한 체크포인트를 통과해야 한다.
