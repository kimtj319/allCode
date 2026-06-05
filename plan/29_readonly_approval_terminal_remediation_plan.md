# 29. Read-only Routing, Interactive Approval, Terminal Output Remediation Plan

## 목적

이 문서는 기본 `allcode` TTY 실행에서 재현된 read-only 분석 요청 실패를
수정하기 위한 상세 계획이다. 대상 증상은 다음 여섯 가지다.

1. "코드 수정은 엄격히 금지한다" 같은 한국어 read-only 제약이 감지되지 않는다.
2. read-only 분석 요청이 `modify` route와 mutation-required phase로 오분기된다.
3. mutation tool schema가 read-only 요청에 노출된다.
4. approval `ask` 모드에서 실제 사용자 입력을 받지 않고 즉시 거부된다.
5. 실패/partial turn에 생성된 `final_answer`가 터미널에 출력되지 않는다.
6. tool 사용 내역이 Codex 스타일의 compact action row가 아니라 난잡한 raw block으로 보인다.

이 계획은 `plan/00`~`12`, `15`, `16`, `17`, `18`, `27`의 계약을 따른다.
특히 다음 규칙을 우선한다.

- read-only, no shell, no external network 같은 안전/금지 조건이 작업 동사보다 우선한다.
- TUI는 agent 내부 상태를 직접 import하지 않고 core event 또는 UI-facing callback만 소비한다.
- approval은 tool executor와 UI 사이에서 명시적인 계약으로 연결한다.
- 특정 테스트 프롬프트, 특정 시나리오 ID, 특정 프로젝트명 기반 하드코딩은 금지한다.

## 재현 근거 요약

실제 TTY 실행 쿼리:

```text
현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다
```

세션 로그에서 확인된 흐름:

- `PromptConstraintExtractor` 결과:
  - `read_only_requested=False`
  - `mutation_requested_hint=True`
  - matched: `정리해`, `수정`, `현재`
- `routing_decided`:
  - `kind=modify`
  - `requires_mutation=True`
  - `read_only_requested=False`
- round 1 tool schema:
  - `delete_path`, `patch_file`, `write_file` 포함
- phase gate:
  - later rounds에서 `mutation_required`
  - `write_file` 또는 `patch_file` 강제
- model action:
  - `write_file src/README.md` 시도
- approval:
  - `approval_requested` 발행 후 즉시 `approval_resolved` denied
  - 사용자 입력 대기 없음
- final:
  - `TurnResult.final_answer`는 존재
  - `FinalAnswerReady` 미발행
  - `TurnResultReady`는 `debug_only`라 terminal에 표시되지 않음

## agy 검토 결과

`agy --print`로 현재 코드와 계획 초안을 검토했다. agy는 코드를 수정하지 않았고,
다음 결론을 제시했다.

- 한국어 조사와 부사 때문에 `"수정 금지"` exact match가 실패한다.
- read-only 감지는 단순 term list 확장이 아니라 proximity regex로 보강해야 한다.
- `read_only_requested=True`이면 `mutation_requested_hint`, `modify_action`,
  `explicit_change_request`를 명시적으로 끄는 override가 필요하다.
- `build_phase_tool_gate`는 `inspect`/`answer` route에서도 mutation gate가
  켜지지 않도록 방어해야 한다.
- approval은 core/UI 결합 없이 `ToolExecutor`에 async approval callback 또는
  broker를 주입하는 방식이 적합하다.
- `TurnResultReady`를 그대로 user-visible로 바꾸면 중복 출력 리스크가 있으므로,
  terminal 측에서 final 출력 여부를 추적하거나 별도 user-visible result event가 필요하다.
- tool output은 한 줄 action row를 기본으로 하고 full content는 foldable/artifact로 분리해야 한다.

## 수정 원칙

### 금지

- 특정 문장 `"현재 디렉터리의 src..."`를 직접 비교하지 않는다.
- `CG01`, `CG05` 같은 시나리오 ID를 source에 넣지 않는다.
- 특정 프로젝트명, 특정 파일명, 특정 테스트 프롬프트를 예외 처리하지 않는다.
- read-only 요청을 해결하기 위해 mutation을 safe no-op으로 위장하지 않는다.
- approval 입력을 받기 위해 tools 또는 agent core가 terminal implementation을 import하지 않는다.

### 허용 신호

- read-only/negative mutation proximity pattern.
- `RoutingDecision.read_only_requested`, `kind`, `requires_mutation`.
- tool definition의 `read_only`, `requires_approval`, `side_effects`, `risk`.
- approval decision의 `risk`, `preview`, `tool_name`, `session_allow` rule.
- `TurnResult.status`, `final_answer`, `completion_evidence`.
- event severity와 user-visible UI event.

## Phase 1. Read-only 제약 추출 보강

### 수정 대상

- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/intent.py`
- `tests/unit/agent/test_prompt_constraints.py`
- `tests/unit/agent/test_intent.py` 또는 관련 라우팅 테스트

### 구현 내용

1. exact term list는 유지하되, read-only 판정에 proximity regex를 추가한다.
2. 한국어는 조사와 부사를 허용한다.

권장 패턴 방향:

```python
READ_ONLY_PATTERNS = (
    re.compile(r"(?:코드\s*)?(?:파일\s*)?(?:수정|변경|편집|삭제|작성|생성)(?:은|는|이|가|도|만)?\s*(?:절대\s*)?(?:엄격히\s*)?(?:금지|불가|하지\s*마|하지마|마라|않)", re.I),
    re.compile(r"(?:do\s+not|don't|never|no)\s+(?:modify|edit|change|update|delete|write|create)", re.I),
    re.compile(r"(?:read[- ]only|analysis\s+only|inspect\s+only|no\s+file\s+changes?)", re.I),
)
```

3. `PromptConstraintExtractor.extract()`에서 `read_only_requested`가 true이면:
   - `mutation_requested_hint=False`
   - `project_generation_hint=False`
   - validation hint는 유지할 수 있으나 shell/no-shell 정책과 별도 판단
4. `IntentExtractor`에서도 같은 override를 적용한다.
   - `modify_action=False`
   - `explicit_change_request=False`
5. matched constraints에는 `"read_only_pattern"` 같은 일반 이름만 남긴다.
   특정 원문 전체를 저장하지 않는다.

### 검증

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_intent.py
```

추가 케이스:

- `코드 수정은 엄격히 금지한다`
- `파일 변경은 하지 말고 구조만 설명해줘`
- `read-only로 src를 분석해줘`
- `do not edit files, summarize src`
- `app.py는 수정하지 말고 문제 원인만 찾아줘`

## Phase 2. Router merge와 schema 노출 방어

### 수정 대상

- `src/allCode/agent/model_router.py`
- `src/allCode/agent/router.py`
- `src/allCode/agent/policy.py`
- `src/allCode/agent/tool_schema_filter.py`
- `tests/unit/agent/test_model_router.py`
- `tests/unit/agent/test_policy.py`

### 구현 내용

1. `ModelRouter._merge_constraints()`에서 `constraints.read_only_requested`가 true이면
   model decision과 capabilities를 강제로 inspect/read-only로 정규화한다.

정규화 규칙:

```text
kind = inspect if workspace evidence is needed else answer
capabilities -= mutate_file, delete_file, run_shell, run_validation
requires_mutation = False
requires_shell = False
workflow_hint = none
flags += read_only_requested
```

2. `if not constraints.read_only_requested and capabilities.intersection(...)` 같은
   후속 mutation 재승격 조건이 read-only override 뒤에 다시 kind를 변경하지 못하게 한다.
3. `RuleBasedRouter`도 동일 우선순위를 유지한다.
4. `ToolPolicy`와 `ToolSchemaFilter`에서 route가 `answer` 또는 `inspect`이면
   mutation category tool은 schema 노출과 실행 모두 차단한다.
5. read-only route에서 모델이 숨겨진 mutation tool을 호출하면
   `policy_denied` 또는 `schema_denied`로 표준 observation을 남기되, mutation phase로 전환하지 않는다.

### 검증

```bash
python -m pytest tests/unit/agent/test_model_router.py tests/unit/agent/test_policy.py tests/unit/agent/test_tool_schema_filter.py
```

## Phase 3. Phase gate mutation 강제 방어

### 수정 대상

- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/completion_gate.py`
- `src/allCode/agent/round_runner.py`
- `tests/unit/agent/test_phase_gate.py`
- `tests/unit/agent/test_completion_gate.py`

### 구현 내용

1. `build_phase_tool_gate()` 초입에서 아래 route는 mutation gate를 만들지 않는다.

```python
if getattr(routing, "read_only_requested", False):
    return PhaseToolGate()
if getattr(routing, "kind", "") in {"answer", "inspect"}:
    return PhaseToolGate()
if getattr(routing, "requires_external_knowledge", False):
    return PhaseToolGate()
```

2. `requires_change_evidence()`는 routing이 있으면 routing 값을 신뢰하되,
   read-only 또는 inspect route에서는 항상 false를 반환한다.
3. read-only inspect 답변은 `changed_files`가 없어도 실패로 처리하지 않는다.
   대신 grounding이 필요한 경우 `inspected_paths`, `search_candidate_paths`,
   `zero_result_queries` 같은 evidence를 완료 근거로 사용한다.

### 검증

```bash
python -m pytest tests/unit/agent/test_phase_gate.py tests/unit/agent/test_completion_gate.py
```

## Phase 4. Interactive approval handshake 추가

### 수정 대상

- `src/allCode/tools/approval.py`
- `src/allCode/tools/executor.py`
- `src/allCode/tools/base.py`
- `src/allCode/agent/loop.py`
- `src/allCode/agent/tool_call_processor.py`
- `src/allCode/runtime.py`
- `src/allCode/tui/terminal.py`
- `src/allCode/tui/approval_panel.py`
- `tests/unit/tools/test_tool_executor.py`
- `tests/tty/test_terminal_approval.py` 신규 또는 기존 TTY 테스트 확장

### 설계

core/tools는 UI를 모른다. 대신 `ToolExecutor`에 optional async approval
handler를 주입한다.

권장 타입:

```python
ApprovalAction = Literal["approve_once", "deny", "allow_session"]

class ApprovalRequest(CoreModel):
    tool_name: str
    decision: ApprovalDecision
    preview: str
    risk: str
    call: ToolCall

ApprovalHandler = Callable[[ApprovalRequest], Awaitable[ApprovalAction]]
```

### 실행 규칙

1. `ApprovalManager`는 risk/preview/기본 decision만 만든다.
2. `ToolExecutor._check_approval()`:
   - `auto` 또는 session allow면 즉시 허용.
   - `ask`이고 `approval_handler`가 있으면:
     - `ApprovalRequested(user_visible)` 발행.
     - handler를 await.
     - `approve_once`: 현재 call만 허용.
     - `allow_session`: `ApprovalManager.session_allow`에 tool 또는 command prefix 추가 후 허용.
     - `deny`: `approval_required` ToolResult 반환.
     - `ApprovalResolved(user_visible/status_only)` 발행.
   - `ask`이고 handler가 없으면 기존 headless fail-fast 유지.
3. `TerminalSession`은 approval handler를 제공한다.
   - composer를 임시 approval prompt로 바꾼다.
   - `y`: approve once.
   - `n` 또는 Esc: deny.
   - `a`: allow session.
   - diff preview는 compact하게 보여주고 긴 diff는 접는다.
4. headless에서는 interactive stdin을 요구하지 않는다.
   - `--approval auto` 또는 config rules가 없으면 fail-fast.
   - 이 동작은 README Current Limitations에 이미 맞는 방향으로 문서화 가능.

### 주의점

- approval handler는 terminal raw input과 agent event loop가 서로 deadlock되지 않게
  같은 thread에서 await 가능한 방식으로 구현한다.
- approval 대기 중에도 `/stop` 또는 Ctrl-C가 cancel로 이어져야 한다.
- session allow는 너무 넓은 wildcard가 아니라 tool name 또는 command prefix 단위로 제한한다.

### 검증

```bash
python -m pytest tests/unit/tools/test_tool_executor.py tests/tty/test_terminal_approval.py
```

## Phase 5. 실패/partial final answer 표시 보강

### 수정 대상

- `src/allCode/core/events.py`
- `src/allCode/agent/loop.py`
- `src/allCode/tui/terminal.py`
- `src/allCode/tui/renderers.py`
- `src/allCode/tui/event_bridge.py`
- `tests/tty/test_terminal_body_output.py`
- `tests/integration/test_mock_agent_loop.py`

### 구현 선택지

권장안: 기존 `TurnResultReady` severity를 전면 user-visible로 바꾸지 않고,
사용자에게 보여줄 수 있는 final text가 있는 경우 별도 이벤트를 발행한다.

신규 이벤트 후보:

```python
class TurnFinalized(AgentEvent):
    event_type: Literal["turn_finalized"] = "turn_finalized"
    severity: EventSeverity = "user_visible"
    status: Literal["success", "partial", "failed", "cancelled"]
    final_answer: str = ""
```

### 실행 규칙

1. `FinalAnswerReady`는 성공 final answer 전용으로 유지한다.
2. `TurnResultReady`는 telemetry/debug contract로 유지한다.
3. `AgentLoop`는 `TurnResult` 생성 후:
   - `FinalAnswerReady`가 이미 발행되지 않았고
   - `result.final_answer.strip()`이 있으면
   - `TurnFinalized(user_visible)`를 발행한다.
4. `TerminalSession`은 `_final_answer_rendered` 플래그를 둔다.
   - stream final과 result final 중 하나만 출력한다.
   - failed/partial이면 status prefix는 짧게 표시하되 answer 본문은 숨기지 않는다.

### 검증

```bash
python -m pytest tests/tty/test_terminal_body_output.py tests/integration/test_mock_agent_loop.py
```

## Phase 6. Codex-style compact tool rendering

### 수정 대상

- `src/allCode/tui/renderers.py`
- `src/allCode/tui/terminal.py`
- `src/allCode/tui/event_bridge.py`
- `src/allCode/tui/transcript_cells.py`
- `tests/tty/test_terminal_body_output.py`
- `tests/tty/test_status_commands.py`

### 구현 내용

1. `tool_call_requested`는 body transcript가 아니라 activity/status row로만 표시한다.
2. `tool_execution_finished`는 기본적으로 한 줄 action row를 출력한다.

예시:

```text
• search_files src -> 20 matches
• read_file src/allCode/agent/model_router.py -> ok
• write_file src/README.md -> approval required
```

3. 긴 output은 transcript에 raw dump하지 않는다.
   - preview: 최대 1~3줄.
   - full content: foldable object 또는 session log artifact.
4. approval required/error는 `✕`나 `!` 스타일의 짧은 row로 표시한다.
   단, ASCII 환경 호환이 필요하면 `x`/`!` fallback을 제공한다.
5. Markdown answer renderer와 tool renderer를 분리한다.
   tool output을 Markdown code block으로 감싸서 본문을 오염시키지 않는다.

### 검증

```bash
python -m pytest tests/tty
```

## Phase 7. 회귀 테스트와 실제 재현 테스트

### 단위 테스트

```bash
python -m pytest tests/unit/agent tests/unit/tools
```

필수 추가/수정 테스트:

- Korean read-only spaced negation extraction.
- English read-only negation extraction.
- read-only + mutation term 충돌 시 read-only 우선.
- model router가 read-only constraint를 받으면 modify로 승격하지 않음.
- inspect route에 mutation schema가 노출되지 않음.
- phase gate가 inspect/answer route에서 mutation_required를 만들지 않음.
- ask approval + handler approve/deny/allow_session.
- ask approval + handler 없음이면 headless fail-fast.

### TTY 테스트

```bash
python -m pytest tests/tty
```

필수 검증:

- approval 요청 시 terminal이 입력을 기다리고, `y/n/a`에 따라 결과가 달라진다.
- failed/partial final answer가 화면에 보인다.
- tool output은 compact row로 표시되고 long output이 본문을 오염시키지 않는다.
- 입력창은 approval, fail, cancel 뒤에도 복구된다.

### 실제 모델 재현

환경:

```bash
allcode
```

프롬프트:

```text
현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다
```

성공 기준:

- route가 `inspect` 또는 read-only answer로 남는다.
- mutation tool schema가 모델에 노출되지 않는다.
- `write_file`, `patch_file`, `delete_path` 요청이 발생하지 않는다.
- 필요한 경우 `list_directory`, `search_files`, `read_file`만 compact row로 표시된다.
- 최종 답변이 terminal body에 출력된다.
- git status에 파일 변경이 없어야 한다.

## 예상 리스크와 완화

### Negation false positive

문제:

- "app.py는 수정하고 test.py는 수정하지 마" 같은 혼합 요청을 전체 read-only로
  오분류할 수 있다.

완화:

- 우선 MVP에서는 전역 read-only 표현과 target-specific negative 표현을 구분한다.
- 전역 표현: "코드 수정은 금지", "파일 변경 금지", "read-only".
- target-specific 표현은 path target deny list로 확장 가능하게 설계하되,
  이번 보강에서는 전체 route 차단보다 policy deny metadata에 남기는 방향을 검토한다.

### Approval deadlock

문제:

- agent loop가 approval handler를 await하는 동안 terminal input loop가 막힐 수 있다.

완화:

- terminal-native UI는 같은 `TerminalSession`에서 approval prompt read를 동기적으로 처리하되,
  async wrapper로 감싼다.
- Textual은 app message/future 기반으로 응답을 돌려준다.
- headless는 handler를 제공하지 않아 기존 fail-fast를 유지한다.

### Duplicate final answer

문제:

- stream으로 이미 출력한 답변과 result final event가 중복 출력될 수 있다.

완화:

- `TerminalSession._final_answer_rendered`와 stream buffer flush 상태를 기준으로 하나만 출력한다.
- 테스트에 "stream + final duplicate 없음" 케이스를 추가한다.

### Tool row 정보 부족

문제:

- compact row만 표시하면 사용자가 tool 결과를 검토하기 어렵다.

완화:

- row에는 tool name, target, ok/error, summary를 넣는다.
- full content는 foldable/artifact/session log에서 접근 가능하게 유지한다.

## 남은 리스크 추적 항목

이 섹션의 항목은 구현 중 "완료 후 확인"이 아니라 각 phase가 끝날 때마다
반드시 확인해야 하는 gate로 취급한다.

### R1. Read-only regex 일반화 실패

위험:

- regex가 좁으면 `"코드 수정은 엄격히 금지"` 같은 표현을 다시 놓친다.
- regex가 넓으면 `"app.py는 수정하고 test.py는 수정하지 마"` 같은 혼합 요청을
  전체 read-only로 잘못 막을 수 있다.

추적 방법:

- 전역 read-only 표현과 target-specific negative 표현을 테스트에서 분리한다.
- read-only override는 `PromptConstraints`와 `IntentSignals` 양쪽에서 검증한다.
- source에는 특정 재현 문장 전체를 비교하는 예외 분기를 넣지 않는다.

완료 gate:

- read-only 충돌 케이스에서 `requires_mutation=False`가 된다.
- 혼합 요청은 적어도 전체 요청을 침묵 실패로 만들지 않고, target-level deny 또는 clarification으로 이어진다.

### R2. Approval 입력 대기 deadlock

위험:

- `ToolExecutor`가 approval handler를 await하는 동안 terminal input loop가 멈추거나,
  Ctrl-C/Esc가 먹히지 않을 수 있다.
- approval prompt가 하단 composer 상태를 깨뜨려 다음 입력이 복구되지 않을 수 있다.

추적 방법:

- headless는 approval handler를 제공하지 않는 fail-fast 경로를 유지한다.
- terminal-native는 `y/n/a/Esc/Ctrl-C` 각각에 대한 TTY 테스트를 둔다.
- approval 완료, 거부, 취소 후 composer가 다시 입력 가능 상태인지 확인한다.

완료 gate:

- ask 모드 TTY에서 approval 요청이 실제로 사용자 입력을 기다린다.
- deny/cancel 시 파일 변경이 없고, approve 시에만 tool이 실행된다.
- approval 이후 다음 일반 프롬프트를 입력할 수 있다.

### R3. Final answer 중복 또는 미출력

위험:

- `FinalAnswerReady`와 result-final event를 모두 렌더링해 답변이 두 번 보일 수 있다.
- 반대로 failed/partial result의 `final_answer`를 계속 숨겨 사용자는 빈 화면만 볼 수 있다.

추적 방법:

- terminal session에 final answer 렌더링 여부를 추적하는 단일 플래그를 둔다.
- success streaming, success non-streaming, partial, failed 각각의 출력 테스트를 분리한다.

완료 gate:

- 성공 답변은 한 번만 출력된다.
- failed/partial이어도 사용자에게 보여줄 `final_answer`가 있으면 출력된다.
- `TurnResultReady` telemetry/debug 기록은 유지된다.

### R4. Compact tool row가 원인 분석 정보를 숨김

위험:

- Codex-style compact row로 바꾸면서 tool 실패 원인, approval preview, search/read 결과 요약이
  너무 많이 생략될 수 있다.

추적 방법:

- row에는 tool name, target, status, 짧은 observation summary를 반드시 포함한다.
- 긴 본문은 transcript에 직접 덤프하지 않되 session log/foldable full text로 보존한다.
- approval required/error row는 사용자가 다음 행동을 알 수 있는 문구를 포함한다.

완료 gate:

- 긴 `read_file`/`search_files` 결과가 transcript를 오염시키지 않는다.
- 실패 tool row만 보고도 실패 종류와 대상은 알 수 있다.
- full content는 session log 또는 foldable payload에 남는다.

### R5. 회귀 테스트가 실제 TTY 문제를 못 잡음

위험:

- unit test는 통과하지만 실제 `allcode` TTY에서 여전히 final answer가 보이지 않거나
  approval 입력이 끊길 수 있다.

추적 방법:

- unit/tty 테스트 이후 실제 TTY에서 동일 read-only prompt를 재실행한다.
- session JSONL에서 route, allowed tools, approval, final event를 같이 확인한다.
- `git status --short`로 read-only 실행 후 파일 변경이 없음을 확인한다.

완료 gate:

- 실제 재현 프롬프트에서 mutation tool call이 발생하지 않는다.
- 화면에 compact tool rows와 최종 답변이 보인다.
- 실행 후 작업 트리에 의도하지 않은 파일 변경이 없다.

## 구현 순서

1. `prompt_constraints.py`, `intent.py` read-only override와 테스트.
2. `model_router.py`, `router.py`, `policy.py`, `tool_schema_filter.py` schema 노출 방어.
3. `phase_gate.py`, `completion_gate.py` mutation gate 방어.
4. `tools/approval.py`, `tools/executor.py`, `agent/loop.py`, `runtime.py` approval handler 계약 추가.
5. `tui/terminal.py`, `tui/approval_panel.py` terminal approval 입력 구현.
6. `core/events.py`, `agent/loop.py`, `tui/renderers.py`, `tui/event_bridge.py` failed/partial final 표시.
7. `tui/renderers.py`, `terminal.py` compact tool row 렌더링.
8. 관련 unit/tty/integration 테스트 실행.
9. 실제 `allcode` TTY에서 동일 프롬프트 재현.

## 완료 기준

- read-only 요청에서 mutation tool이 모델 schema와 실행 경로 모두에서 차단된다.
- approval `ask` 모드는 interactive TTY에서 실제로 사용자 입력을 기다린다.
- headless `ask` 모드는 명확한 approval-required 결과를 반환하고 침묵하지 않는다.
- 실패/partial final answer가 터미널에 표시된다.
- tool 사용 내역이 compact action row로 보인다.
- 동일 재현 프롬프트에서 최종 답변이 출력되고 파일 변경이 없다.
- 특정 프롬프트/프로젝트명/시나리오 ID 하드코딩 없이 일반화된 신호로 동작한다.
