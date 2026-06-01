# 03. Core Contracts 구현 계획

## 구현 전 필수 보강 지시

- 모든 핵심 데이터 모델은 Pydantic v2 기반으로 정의하여 타입 강제, JSON 직렬화, 테스트 fixture 생성을 안정적으로 지원한다.
- `EventBus` 계약을 반드시 포함한다. publish/subscribe 인터페이스, async queue 기반 전달, UI와 agent loop 사이의 thread-safe 경계를 명시한다.
- Core 계층은 Textual, Rich, prompt_toolkit, provider SDK를 import하지 않는다.


## 목적

모든 계층이 공유하는 가장 작은 계약을 먼저 만든다. 이 단계가 안정적이어야 이후 agent loop, tool system, TUI가 서로 결합되지 않는다.

## 우선순위

1. `core/models.py` 작성
2. `core/events.py` 작성
3. `core/errors.py` 작성
4. `core/result.py` 작성
5. 단위 테스트 작성

## 상세 수정 및 구현 내용

### 1. `core/models.py`

정의할 타입:

- `Role`: `system`, `user`, `assistant`, `tool`
- `Message`: role, content, metadata
- `ToolCall`: id, name, arguments
- `ToolResult`: call_id, name, ok, content, error, metadata
- `TurnInput`: user_prompt, workspace, mode, session_id
- `TurnState`: turn_id, phase, messages, tool_calls, token_usage, created_files, modified_files
- `AgentMode`: `all_rounder`, `router_planner`

#### 핵심 Pydantic v2 모델 명세

모델 필드는 아래 계약을 최소 기준으로 삼는다. 구현 중 필드를 추가할 수는 있지만, 같은 의미의 중복 모델을 tools 계층에 다시 만들지 않는다.

```python
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]
AgentMode = Literal["all_rounder", "router_planner"]

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class WorkspaceRef(BaseModel):
    root: str
    writable: bool = True
    label: str | None = None

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

class ToolResult(BaseModel):
    call_id: str
    name: str
    ok: bool
    content: str = ""
    error: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_final: bool = False

class Message(BaseModel):
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

설계 기준:

- 모델 응답 형식과 UI 출력 형식을 분리한다.
- `ToolCall`은 모델 provider별 raw 구조를 들고 있지 않는다.
- provider 원본 정보는 metadata에 넣되 core 로직은 metadata에 의존하지 않는다.

### 2. `core/events.py`

정의할 이벤트:

- `TurnStarted`
- `RoutingDecided`
- `ModelStreamStarted`
- `ModelTextDelta`
- `ToolCallRequested`
- `ToolExecutionStarted`
- `ToolExecutionFinished`
- `ApprovalRequested`
- `ApprovalResolved`
- `FinalAnswerReady`
- `TurnFailed`

설계 기준:

- TUI는 이 이벤트만 보고 화면을 그린다.
- Agent loop는 Rich, Textual, prompt_toolkit 같은 UI 라이브러리를 import하지 않는다.

#### AsyncEventBus 계약

`EventBus`는 UI와 agent loop의 유일한 통신 경계다.

```python
from collections.abc import Awaitable, Callable
from typing import Protocol

EventHandler = Callable[[AgentEvent], Awaitable[None]]
Unsubscribe = Callable[[], None]

class EventBus(Protocol):
    async def publish(self, event: AgentEvent) -> None: ...
    def subscribe(
        self,
        event_type: type[AgentEvent] | None,
        handler: EventHandler,
    ) -> Unsubscribe: ...
    async def close(self, *, drain: bool = True) -> None: ...
```

운영 규칙:

- `event_type=None`은 모든 이벤트 구독을 의미한다.
- 이벤트 순서는 같은 turn 안에서 publish 순서를 보장한다.
- 내부 queue 기본값은 `maxsize=1000`이다.
- queue overflow 시 중요도가 낮은 진행률 이벤트를 먼저 drop하고 `EventDropped`를 발행한다.
- `close(drain=True)`는 남은 이벤트를 처리한 뒤 종료한다.

### 3. `core/errors.py`

정의할 오류:

- `NewCliError`
- `ModelResponseError`
- `ToolExecutionError`
- `PolicyDeniedError`
- `ApprovalRequiredError`
- `ContextBudgetExceededError`

### 3.1 `core/result.py`

단일 대화 턴(turn)의 처리 결과를 표준 스키마로 수집하고 기록하는 책임을 갖는다.

```python
from typing import Literal
from pydantic import BaseModel, Field
from allCode.core.models import TokenUsage

class TurnResult(BaseModel):
    """단일 turn의 최종 결과."""
    turn_id: str
    status: Literal["success", "partial", "failed", "cancelled"]
    final_answer: str = ""
    created_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    validation_passed: bool | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    error_message: str | None = None
```

#### 1.5단계 보강 계약: 완료 근거와 복구 상태

1단계 구현이 끝난 뒤 2단계로 넘어가기 전에 아래 모델을 반드시 보강한다. 이 항목은 새 기능이 아니라 후속 Tool, Workspace, TUI가 의존할 core 계약이다.

```python
from typing import Literal
from pydantic import BaseModel, Field

CompletionStatus = Literal[
    "not_started",
    "changed",
    "validated",
    "reported",
    "blocked",
]

RecoveryReason = Literal[
    "empty_response",
    "reasoning_only",
    "length_cutoff",
    "tool_loop",
    "slow_stream",
    "validation_failed",
    "external_tool_failed",
]

class CompletionEvidence(BaseModel):
    """사용자에게 완료를 보고하기 전에 반드시 확인할 근거."""
    changed_files: list[str] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    validation_passed: bool | None = None
    final_answer_ready: bool = False

class RecoveryState(BaseModel):
    """빈 응답, 반복 도구 호출, 느린 스트림 같은 복구 경로 상태."""
    reason: RecoveryReason
    attempts: int = 0
    last_error: str | None = None
    blocked: bool = False

class ToolLoopSignature(BaseModel):
    """같은 도구/같은 인자 반복을 감지하기 위한 canonical signature."""
    tool_name: str
    arguments_hash: str
    count: int = 1
```

`TurnResult`는 `CompletionEvidence`와 `RecoveryState`를 포함하도록 확장한다.

완료 판단 규칙:

- 구현/수정 요청에서 `created_files`, `modified_files`, `changed_files`가 모두 비어 있으면 `success`가 될 수 없다.
- 검증이 필요한 요청에서 `validation_passed is not True`이면 `success`가 될 수 없다.
- final answer는 `CompletionEvidence.final_answer_ready=True`일 때만 반환한다.
- read-only 요청은 mutation 근거가 없어도 되지만, 읽은 파일/검색 근거가 event 또는 metadata에 남아야 한다.

### 4. 테스트

- `tests/unit/core/test_models.py`
- `tests/unit/core/test_events.py`
- `tests/unit/core/test_errors.py`
- `tests/unit/core/test_result.py`

검증 기준:

- 모든 모델은 직렬화 가능해야 한다.
- 이벤트는 UI 없이 생성 가능해야 한다.
- 도구 결과 실패와 성공 구조가 동일한 형태로 처리되어야 한다.
- 구현/수정 요청에서 실제 변경 근거 없이 `TurnResult.status="success"`가 되지 않아야 한다.
- `CompletionEvidence`, `RecoveryState`, `ToolLoopSignature`가 JSON 직렬화되어 session store에 저장 가능해야 한다.

## 대규모 프로젝트 코드 생성 절차 반영

이 단계에서는 스켈레톤과 계약만 만든다. 실제 모델 호출, 도구 실행, TUI 렌더링은 작성하지 않는다. 먼저 함수 시그니처와 데이터 흐름을 고정한 뒤, 다음 단계에서 각 계약을 사용해 구현한다.

## 파일 길이 및 모듈화 원칙

- `models.py`가 300줄을 넘으면 `messages.py`, `tools.py`, `turn.py`로 분리한다.
- `events.py`가 250줄을 넘으면 `event_types.py`, `event_bus.py`로 분리한다.
- 오류 타입은 `errors.py`에 유지하되, 복구 정책은 agent 계층에서 작성한다.

## 공개 오픈소스 참조 기반 보강 계약

Core 계층은 Aider, Gemini CLI, Qwen Code, OpenHands처럼 provider와 UI에서 독립된 안정 계약이어야 한다.

- 모든 core Pydantic 모델은 `model_config = ConfigDict(extra="forbid")`를 기본으로 한다.
- provider raw payload는 `llm/adapters/*` 내부에서만 다루고 core 모델에 직접 넣지 않는다.
- `metadata`에는 JSON 직렬화 가능한 primitive, list, dict만 허용한다.
- `ToolResult`는 `core/models.py`의 단일 모델만 사용하고 tools 계층에서 동명 모델을 재정의하지 않는다.
- event payload는 UI가 바로 표시할 수 있는 형태와 debug artifact용 상세 데이터를 분리한다.
