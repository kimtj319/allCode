# 10. TUI App 구현 계획

## 구현 전 필수 보강 지시

- Textual을 1차 TUI 프레임워크로 확정한다. Agent loop는 Textual UI 스레드를 블로킹하지 않도록 background worker로 실행한다.
- UI와 agent loop의 통신은 Core Event를 담은 async queue/event bus를 통해서만 처리한다. UI 컴포넌트는 agent 내부 객체를 직접 호출하지 않는다.
- MVP TUI는 transcript, status bar, input box, slash palette를 먼저 구현하고 approval modal과 diff panel은 그 위에 얹는다.


## 목적

Kimi Code CLI처럼 입력창, 출력 transcript, slash command palette, approval panel, diff panel, 상태바가 하나의 TUI 앱 안에서 안정적으로 작동하도록 설계한다.

## 우선순위

1. TUI 라이브러리 선택
2. `tui/app.py` 작성
3. `tui/layout.py` 작성
4. `tui/input_box.py` 작성
5. `tui/command_palette.py` 작성
6. `tui/renderers.py` 작성
7. `tui/approval_panel.py` 작성
8. 실제 TTY 테스트 작성

## 권장 라이브러리

1순위: Textual

- 장점: full-screen TUI, 레이아웃, widget, modal, key binding, background worker 구조가 좋다.
- 단점: 의존성이 늘고 초기 설계가 필요하다.

2순위: prompt_toolkit Application 직접 구성

- 장점: 가볍고 입력 제어가 강하다.
- 단점: 제품형 panel UI를 직접 많이 구현해야 한다.

Kimi Code CLI 수준의 체감을 목표로 하면 Textual을 우선 검토한다.

## 화면 구조

```text
┌──────────────── transcript ────────────────┐
│ user prompt                                │
│ assistant stream                           │
│ tool start/result                          │
│ diff panel                                 │
│ final answer                               │
├──────────────── status ────────────────────┤
│ model · workspace · running tool · tokens  │
├──────────────── input ─────────────────────┤
│ > 사용자 입력                               │
└─────────────────────────────────────────────┘
```

## Textual Worker and Event Bus Lifecycle 계약

TUI와 agent loop의 경계는 다음 계약을 따른다.

1. Worker 시작: `App.run_worker(agent_loop_coro, exclusive=True, group="agent_run")`로 현재 turn worker를 시작한다.
2. UI 업데이트: background worker 또는 event subscriber가 UI 위젯을 변경해야 할 때는 `post_message()` 또는 `call_from_thread()`를 사용한다.
3. 취소: 사용자가 `Esc`, `/stop`, `Ctrl-C`로 취소하면 TUI는 `workers.cancel_group("agent_run")`을 호출한다.
4. 정리: Agent loop는 `asyncio.CancelledError`를 catch하고 실행 중인 shell/process tool을 종료한 뒤 `TurnFailed(cancelled=True)` 또는 `TurnCancelled` 이벤트를 발행한다.
5. 예외 격리: worker 내부 예외는 침묵 종료하지 않고 `TurnFailed(error_type="TUI_WORKER_CRASH")` 이벤트로 변환한다.
6. Backpressure: EventBus queue는 `maxsize=1000`을 기본값으로 두고, 초과 시 stream delta/progress 같은 낮은 중요도 이벤트를 drop한다.
7. 입력 복구: worker 실패 또는 취소 후 input box는 반드시 다시 활성화된다.

## 상세 수정 및 구현 내용

### 1. `tui/app.py`

담당:

- 앱 실행
- agent loop task 시작
- event bus 구독
- graceful shutdown

### 2. `tui/layout.py`

담당:

- transcript 영역
- input 영역
- status 영역
- overlay 영역

### 3. `tui/input_box.py`

담당:

- 멀티라인 입력
- 작업 중 후속 입력 큐
- `Ctrl-S` 즉시 주입
- `Esc` 취소
- placeholder 표시

### 4. `tui/command_palette.py`

담당:

- `/` 입력 시 명령어 팝업
- 실시간 필터링
- 명령 설명 표시
- 하위 명령 지원

### 5. `tui/approval_panel.py`

담당:

- 파일 diff 미리보기
- shell command preview
- 승인/거절/session allow
- 피드백 입력

### 6. `tui/renderers.py`

담당:

- tool event 렌더링
- diff 렌더링
- final answer 렌더링
- error panel 렌더링

## 대규모 프로젝트 코드 생성 절차 반영

TUI는 대규모 생성 작업 중 다음 상태를 분명히 보여줘야 한다.

1. 요구사항 분석 중
2. 스켈레톤 생성 중
3. 파일 구현 중
4. 테스트 실행 중
5. 실패 수리 중
6. 완료 요약 작성 중

각 단계는 transcript에 누적하되, 하단 status에는 현재 단계만 표시한다.

## 파일 길이 및 모듈화 원칙

- `tui/app.py`는 앱 lifecycle만 담당한다.
- 입력 처리, command palette, approval panel, renderer는 파일을 분리한다.
- 렌더링 문자열은 `tui/messages.py` 또는 message catalog로 분리한다.
- UI 컴포넌트가 agent 내부 클래스를 직접 import하지 않고 core event만 사용한다.

## 공개 오픈소스 참조 기반 보강 계약

TUI는 agent 내부 상태를 직접 읽지 않고 event stream만 구독한다.

- event severity는 `user_visible`, `status_only`, `debug_only`로 나눈다.
- `user_visible`만 transcript에 누적하고 `status_only`는 하단 상태 영역에만 표시한다.
- input box는 worker start, finish, fail, cancel 이후 항상 enabled 상태를 복원한다.
- slash command palette는 command registry에서만 후보를 가져온다.
- 긴 tool output은 foldable panel로 렌더링하고 full content는 artifact로 연결한다.
- 모델이 느리더라도 spinner/status message가 계속 갱신되어 사용자가 진행 상태를 알 수 있어야 한다.
