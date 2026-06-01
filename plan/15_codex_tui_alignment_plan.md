# 15. Codex-Level TUI Alignment Plan

## 목적

이 문서는 `10_tui_app_plan.md`의 Textual 기반 TUI 계획을 실제 Codex CLI 수준의 사용자 경험으로 보강하기 위한 추가 구현 계획서다.

기존 `10` 문서는 Kimi Code CLI 같은 전용 TUI 앱의 큰 구조를 정의했다. 그러나 실제 Codex CLI를 실행해 확인하고 공개 `openai/codex` 소스의 TUI 구조를 검토한 결과, 단순히 하단 입력창을 고정하는 것만으로는 Codex 수준의 UI가 되지 않는다.

이 문서의 목표는 다음 네 가지를 allCode TUI의 명시적 구현 계약으로 추가하는 것이다.

1. 실행 중에도 입력 가능한 persistent composer.
2. committed transcript cell과 active streaming cell을 분리한 transcript 모델.
3. Markdown stream을 source-backed, width-aware, stable/tail 구조로 렌더링하는 방식.
4. agent loop와 UI를 event/reducer 경계로 분리하는 구조.

## 참고한 기존 계획서

이 문서는 아래 계획서의 보강 문서로 사용한다.

- `00_master_implementation_guide.md`: 전체 설계 원칙, 모듈화 원칙, 대규모 구현 절차.
- `01_open_source_alignment_contracts.md`: 공개 CLI 에이전트 참조 기반 설계 계약.
- `03_core_contracts_plan.md`: provider/UI 독립 core event 계약.
- `04_llm_loop_plan.md`: stream event와 recovery loop.
- `10_tui_app_plan.md`: Textual 기반 TUI 기본 구조.
- `11_quality_testing_plan.md`: TTY 테스트와 UI 품질 평가.
- `12_mvp_execution_plan.md`: 마일스톤, 중단/재개, 완료 기준.

충돌 시 우선순위는 다음과 같다.

1. 안전, workspace, approval, secret 관련 계약.
2. `00`의 전체 설계 원칙.
3. `15`의 Codex-level TUI 보강 계약.
4. `10`의 기본 TUI 구조.
5. `13`, `14`의 검토 이력 부록.

## 참고한 외부 소스와 관찰 결과

### 공개 소스

- OpenAI Codex repository: https://github.com/openai/codex
- Codex Rust TUI source: https://github.com/openai/codex/tree/main/codex-rs/tui/src
- `chatwidget.rs`: transcript, composer, running task 상태를 하나의 UI shell에서 조율하는 핵심 위젯.
- `markdown_stream.rs`: markdown stream을 단순 token append가 아니라 line boundary 중심으로 처리.
- `streaming/controller.rs`: stable region과 mutable tail region을 분리해 streaming answer를 관리.
- `markdown.rs`, `markdown_render.rs`: agent answer markdown을 terminal 폭에 맞게 렌더링.

### 실제 Codex CLI 실행 관찰

다음 형태로 실제 TTY에서 Codex CLI를 실행해 확인했다.

```bash
codex --no-alt-screen -C /private/tmp/codex-ui-check -s read-only -a never "Markdown 표와 Python 코드블록을 포함해서 아주 짧게 답변해줘."
```

확인된 UX 특징:

- 답변 생성 중에도 하단 `›` composer가 계속 보인다.
- footer에는 `tab to queue message`, context left, 현재 model/directory 같은 정보가 유지된다.
- 답변이 body 영역에서 진행되는 동안 composer 영역은 사라지지 않는다.
- Markdown table은 raw `| A | B |` 텍스트로만 남지 않고 terminal table 형태로 재렌더링된다.
- fenced code block은 fence 문법 자체보다 코드 본문 중심으로 렌더링된다.
- stream 중에는 raw에 가까운 tail이 잠깐 보일 수 있지만, block이 안정화되면 다시 렌더링된다.
- 실행 중 입력은 단순히 막히지 않는다. 다음 메시지 queue 또는 현재 작업 interrupt/steer의 기반이 된다.

## 기존 계획 대비 보강된 점 요약

기존 `10_tui_app_plan.md`의 부족한 점:

- `input box`가 worker running 중 disabled될 수 있다.
- transcript가 문자열 list 중심이라 active streaming block과 완료된 block을 안정적으로 구분하기 어렵다.
- Markdown stream 처리가 전체 문자열 update 또는 raw delta 출력에 치우칠 수 있다.
- status message와 answer stream이 중복되어 화면이 지저분해질 수 있다.
- `/`, `@`, `Tab`, `Esc`, `Enter`의 running-state 의미가 Codex처럼 분리되어 있지 않다.

보강 방향:

- Textual을 기본 non-headless UI로 승격하되, 단순 docked input이 아니라 Codex식 persistent composer 계약을 구현한다.
- transcript를 `HistoryCell` 기반으로 바꾼다.
- streaming answer는 `active_cell`에만 반영하고 final 시 committed cell로 consolidate한다.
- Markdown은 source-backed stream state로 관리한다.
- running 중 `Enter`는 steer, `Tab`은 queue, `Esc`는 interrupt로 분리한다.
- UI는 agent internals를 직접 보지 않고 `AgentEvent -> UIEvent -> TUIState` reducer 경계를 사용한다.

## 최종 목표 화면 계약

```text
╭─────────────────────────────────────────────╮
│ >_ allCode                                  │
│ model: gpt-compatible · approval: ask       │
│ directory: /path/to/workspace               │
╰─────────────────────────────────────────────╯

› 사용자가 입력한 요청

• 도구 실행, 상태, assistant answer, rendered markdown
  ...

──────────────────────────────────────────────
› 현재 composer draft

  Enter to steer · Tab to queue · Esc to interrupt · 96% context left
```

UI 계약:

- body transcript는 composer 위에서만 스크롤된다.
- composer는 항상 화면 하단에 남는다.
- 답변 중에도 composer는 비활성화되지 않는다.
- assistant answer stream은 active cell에서 갱신된다.
- final answer가 도착하면 active cell이 committed cell로 전환된다.
- final answer는 streaming 출력과 중복 출력되지 않는다.

## 권장 최상위 TUI 모듈 구조

```text
src/allCode/tui/
  app.py                         # Textual App lifecycle only
  styles.py                      # Codex-like layout CSS
  event_bridge.py                # AgentEvent -> UIEvent 변환
  state_reducer.py               # UIEvent -> TUIState 순수 reducer
  transcript_cells.py            # HistoryCell, UserCell, AssistantCell, ToolCell
  transcript_state.py            # committed_cells, active_cell, overlays
  transcript_view.py             # Textual widgets rendering transcript cells
  composer.py                    # persistent input composer
  composer_bindings.py           # Enter, Tab, Esc, slash, at-file key handling
  footer.py                      # footer state and text rendering
  markdown_stream_state.py       # source-backed stable/tail markdown stream state
  markdown_normalizer.py         # agent markdown normalization
  markdown_renderer.py           # width-aware markdown rendering
  table_detect.py                # markdown table detection and holdback
  command_palette.py             # slash command palette
  approval_panel.py              # approval/diff modal
  renderers.py                   # legacy compatibility shim, 점진 제거 대상
  terminal.py                    # plain terminal fallback only
```

파일 책임 기준:

- `app.py`는 agent worker 시작, event subscription, shutdown만 담당한다.
- composer 입력 처리와 key binding은 `composer.py`, `composer_bindings.py`로 분리한다.
- Markdown stream 처리와 Markdown render 처리는 같은 파일에 두지 않는다.
- reducer는 Textual widget을 import하지 않는다.
- Textual widget은 agent loop를 import하지 않는다.
- 300줄 이상이면 분리 후보로 기록하고, 500줄 이상이면 분리한다.

## P0. 실행 경로 정리

### 수정 대상

- `src/allCode/main.py`
- `src/allCode/tui/app.py`
- `src/allCode/tui/terminal.py`

### 구현 내용

1. non-headless 기본 실행 경로를 Textual `AllCodeApp`으로 변경한다.
2. `terminal.py`의 raw ANSI shell은 fallback으로만 유지한다.
3. 명시 옵션을 추가한다.

```text
allcode                 -> Textual Codex-like TUI
allcode --plain-terminal -> raw ANSI fallback
allcode --headless       -> headless runner
```

4. Textual 미설치 또는 terminal capability 부족 시 fallback 메시지를 출력하고 plain terminal로 내려간다.
5. `main.py`는 UI 구현체 세부를 몰라야 한다. `tui/runtime.py` 또는 `tui/factory.py`에서 UI runner를 선택한다.

### 리스크

- 기존 `terminal.py` 기반 TTY 테스트가 깨질 수 있다.
- Textual 환경이 없는 CI에서 non-headless 테스트가 실패할 수 있다.

### 완화

- `--plain-terminal` fallback 테스트를 유지한다.
- Textual 테스트는 `pytest.mark.skipif(not TEXTUAL_AVAILABLE)` 기준을 유지한다.
- 기본 실행 경로 변경 테스트와 fallback 테스트를 분리한다.

## P1. Persistent Composer와 실행 중 입력 계약

### 수정 대상

- `src/allCode/tui/composer.py`
- `src/allCode/tui/composer_bindings.py`
- `src/allCode/tui/footer.py`
- `src/allCode/tui/layout.py`
- `src/allCode/tui/app.py`

### 구현 내용

1. composer는 Textual layout에서 `dock: bottom`으로 고정한다.
2. agent worker running 중에도 input widget은 disabled하지 않는다.
3. running 상태의 입력 의미를 분리한다.

```text
Enter while idle     -> submit new turn
Enter while running  -> steer current turn
Tab while running    -> queue next turn
Esc while running    -> interrupt current turn
Alt+Enter            -> insert newline
/                     -> slash command palette
@                     -> file mention palette
```

4. `TurnSteerRequested` 또는 `UserSteerSubmitted` UI event를 추가한다.
5. agent loop가 즉시 steer를 받을 수 없으면 다음 model round에 user message로 삽입한다.
6. queue는 `queued_prompts`와 `steer_messages`를 분리해 저장한다.
7. footer는 상태에 따라 다음처럼 바뀐다.

```text
idle:      model · workspace · approval · context left
running:   Enter to steer · Tab to queue · Esc to interrupt · context left
queued:    2 queued · Enter to steer · Tab to queue
approval:  y approve · n reject · d details
```

### 리스크

- Enter가 steer인지 submit인지 혼동될 수 있다.
- agent loop가 steer event를 처리하지 못하면 입력이 누락될 수 있다.

### 완화

- running 중 입력 후 footer에 `sent to current turn` 또는 `queued`를 명확히 표시한다.
- steer event를 agent loop가 지원하지 않는 초기 단계에서는 queue로 downgrade하고 UI에 표시한다.
- `Tab` queue 동작을 명시적으로 테스트한다.

## P2. Cell 기반 Transcript 모델

### 수정 대상

- `src/allCode/tui/transcript_cells.py`
- `src/allCode/tui/transcript_state.py`
- `src/allCode/tui/transcript_view.py`
- `src/allCode/tui/layout.py`

### 구현 내용

기존 문자열 기반 transcript를 다음 구조로 대체한다.

```python
class TranscriptState:
    committed_cells: list[HistoryCell]
    active_cell: HistoryCell | None
    overlays: list[HistoryCell]
```

Cell 종류:

```text
UserCell
AssistantMarkdownCell
StreamingAssistantCell
ToolCallCell
ToolResultCell
ApprovalCell
StatusCell
ErrorCell
DiffCell
ValidationCell
```

규칙:

- user prompt는 즉시 committed cell로 들어간다.
- assistant stream은 active cell에만 들어간다.
- final answer 도착 시 active cell을 canonical assistant cell로 consolidate한다.
- tool progress는 transient status와 committed tool cell을 구분한다.
- status-only event는 transcript에 남기지 않고 footer/status 영역으로 보낸다.
- user-visible event만 transcript cell로 만든다.

### 리스크

- 기존 `TUIStateController.state.transcript: list[str]`에 의존하는 테스트가 깨질 수 있다.

### 완화

- `transcript_to_markdown()` 호환 adapter를 임시 제공한다.
- 기존 테스트는 adapter를 통해 통과시키고, 신규 테스트는 cell 모델을 직접 검증한다.
- `renderers.py`는 바로 삭제하지 않고 `event_bridge.py`로 점진 이전한다.

## P3. Source-backed Markdown Streaming

### 수정 대상

- `src/allCode/tui/markdown_stream_state.py`
- `src/allCode/tui/markdown_normalizer.py`
- `src/allCode/tui/markdown_renderer.py`
- `src/allCode/tui/table_detect.py`
- `src/allCode/tui/transcript_view.py`

### 구현 내용

Codex의 `markdown_stream.rs`, `streaming/controller.rs` 흐름을 Python/Textual 구조에 맞게 구현한다.

상태 모델:

```python
class MarkdownStreamState:
    raw_source: str
    committed_source_len: int
    stable_source_len: int
    mutable_tail_start: int
    open_fence: bool
    table_holdback_start: int | None
```

처리 규칙:

1. delta를 `raw_source`에 추가한다.
2. newline boundary가 생기기 전에는 stable commit하지 않는다.
3. code fence가 열려 있으면 fence가 닫힐 때까지 tail로 보류한다.
4. table header와 delimiter가 감지되면 table block 전체를 holdback한다.
5. stable source만 committed rendering으로 보낸다.
6. mutable tail은 active cell 안에서만 갱신한다.
7. final 시 전체 source를 normalize 후 canonical render한다.
8. terminal width 변경 시 raw source에서 다시 렌더링한다.

Markdown normalization:

- `md` 또는 `markdown` code fence 안에 table이 있으면 fence를 벗긴다.
- `python`, `bash`, `json`, `yaml` 등 실제 code fence는 유지한다.
- 닫히지 않은 fence는 final 시 안전하게 닫아 렌더링한다.
- 과도하게 긴 table은 width-aware wrapping 또는 key/value fallback을 적용한다.

### 리스크

- Markdown parser를 직접 과도하게 구현하면 버그가 늘어날 수 있다.
- Textual Markdown 위젯 전체 update가 잦으면 성능이 떨어질 수 있다.

### 완화

- 완전한 Markdown parser를 만들지 않는다.
- source holdback, fence/table 감지만 직접 구현한다.
- 실제 rendering은 Textual Markdown 또는 Rich renderable에 위임한다.
- update throttle을 둔다. 기본 50~100ms 단위 flush.

## P4. UI Event Bridge와 Reducer 분리

### 수정 대상

- `src/allCode/tui/event_bridge.py`
- `src/allCode/tui/state_reducer.py`
- `src/allCode/tui/app.py`
- `src/allCode/tui/renderers.py`

### 구현 내용

현재 구조가 `AgentEvent -> RenderedEvent -> controller`로 바로 이어지는 경우, UI 정책과 agent event 해석이 섞일 수 있다.

보강 구조:

```text
AgentEvent
  -> TUIEventBridge
  -> UIEvent
  -> TUIStateReducer
  -> TUIState
  -> Textual widgets
```

UIEvent 예:

```text
UserPromptCommitted
AssistantStreamStarted
AssistantDeltaReceived
AssistantFinalized
ToolStatusUpdated
ToolResultCommitted
ApprovalOpened
ApprovalResolved
ValidationStatusUpdated
TurnFailedVisible
FooterStatusChanged
```

규칙:

- bridge는 agent event를 UI 의미로 변환한다.
- reducer는 순수 함수로 상태만 변경한다.
- Textual App은 reducer 결과를 렌더링만 한다.
- agent loop 내부 객체를 TUI가 직접 import하지 않는다.

### 리스크

- 이벤트 계층이 하나 늘어나 초기 구현량이 증가한다.

### 완화

- 기존 `renderers.py`를 즉시 제거하지 않는다.
- 먼저 bridge가 기존 renderer와 동일 출력을 만들게 한 뒤 점진적으로 cell 기반 이벤트로 이전한다.
- reducer unit test를 먼저 작성한다.

## P5. Status, Tool, Approval Cell UX 정리

### 수정 대상

- `src/allCode/tui/transcript_cells.py`
- `src/allCode/tui/footer.py`
- `src/allCode/tui/approval_panel.py`
- `src/allCode/tui/diff_panel.py`
- `src/allCode/tui/tool_panel.py`

### 구현 내용

Codex-like UI에서는 모든 내부 상태를 transcript에 쌓지 않는다.

표시 정책:

- `model_stream_started`, heartbeat: footer/status only.
- `tool_call_requested`: compact tool status cell 또는 footer.
- `tool_execution_finished`: 짧은 결과는 compact cell, 긴 결과는 folded cell.
- approval: modal/panel 우선, transcript에는 요약 cell만 남김.
- validation: 현재 단계는 footer, 최종 결과는 validation cell.
- final answer: assistant cell.
- debug-only event: 화면 출력 금지.

Tool cell 규칙:

- tool name, target, duration, success/failure만 기본 표시.
- stdout/stderr는 20줄 또는 1200자까지만 preview.
- full output은 artifact path 또는 expandable panel로 연결.

### 리스크

- 정보가 너무 숨겨져 사용자가 도구 결과를 추적하기 어려울 수 있다.

### 완화

- `details` 키 또는 command palette action으로 folded panel을 열 수 있게 한다.
- debug log에는 full event와 full tool output을 남긴다.

## P6. Slash Command와 File Mention Palette

### 수정 대상

- `src/allCode/tui/command_palette.py`
- `src/allCode/tui/composer_bindings.py`
- `src/allCode/tui/file_mention_palette.py`
- `src/allCode/workspace/indexer.py`

### 구현 내용

- `/` 입력 시 command registry 기반 command palette를 하단 composer 위에 표시한다.
- `@` 입력 시 workspace file mention palette를 표시한다.
- running 중 slash command는 세 종류로 나눈다.

```text
immediate: /stop, /help, /memory show
queued:    /run, /test 같은 작업성 명령
blocked:   approval flow 중 충돌하는 명령
```

- file mention은 최근 target과 repo map ranking을 우선한다.
- 너무 큰 workspace에서는 index limit을 적용하고 결과가 너무 많으면 검색어 입력을 요구한다.

### 리스크

- command palette와 file palette가 동시에 열리는 상태 충돌.

### 완화

- overlay state는 하나만 active로 둔다.
- `/`와 `@` 모드를 명시적으로 분리한다.
- overlay reducer 테스트를 작성한다.

## P7. 테스트 및 검증 계획

### Unit tests

추가 테스트:

```text
tests/unit/tui/test_transcript_cells.py
tests/unit/tui/test_tui_event_bridge.py
tests/unit/tui/test_state_reducer.py
tests/unit/tui/test_markdown_stream_state.py
tests/unit/tui/test_markdown_normalizer.py
tests/unit/tui/test_table_detect.py
tests/unit/tui/test_composer_bindings.py
```

검증 기준:

- running 중 Enter는 steer event를 만든다.
- running 중 Tab은 queue event를 만든다.
- Esc는 interrupt event를 만든다.
- stream delta는 active cell만 갱신한다.
- final answer는 active cell을 committed cell로 이동한다.
- final answer 중복 출력이 없다.
- markdown table fence unwrap이 md/markdown fence에서만 작동한다.

### TTY/Textual tests

추가 테스트:

```text
tests/tty/test_codex_like_persistent_composer.py
tests/tty/test_codex_like_streaming_markdown.py
tests/tty/test_codex_like_queue_and_steer.py
tests/tty/test_codex_like_command_palette.py
tests/tty/test_codex_like_status_lifecycle.py
```

검증 기준:

- 답변 중 composer가 사라지지 않는다.
- input widget이 running 중 disabled되지 않는다.
- footer에 queue/steer/interrupt hint가 표시된다.
- Markdown table이 raw pipe table로만 남지 않는다.
- code fence가 raw fence 문법 중심으로 출력되지 않는다.
- tool status와 answer stream이 중복 출력되지 않는다.

### 실제 TTY smoke

최소 프롬프트:

```text
1. Markdown 표와 Python 코드블록을 포함해서 짧게 답변해줘.
2. 답변 중 다음 질문을 입력하고 Tab으로 queue한다.
3. 답변 중 추가 지시를 Enter로 넣는다.
4. /help를 입력해 command palette와 명령 결과를 확인한다.
5. @src 입력으로 file mention 후보를 확인한다.
6. 긴 코드 분석 요청을 보내 body scroll과 composer 고정을 확인한다.
```

성공 기준:

- body 영역만 스크롤된다.
- 하단 composer는 계속 보인다.
- footer hint가 현재 상태와 맞다.
- Markdown raw leakage가 눈에 띄지 않는다.
- 종료 후 terminal 상태가 깨지지 않는다.

## P8. 구현 순서

권장 순서:

1. `transcript_cells.py`, `transcript_state.py`를 먼저 작성한다.
2. `state_reducer.py` unit test를 작성하고 통과시킨다.
3. `event_bridge.py`를 작성해 기존 `AgentEvent`를 UIEvent로 변환한다.
4. `markdown_stream_state.py`, `markdown_normalizer.py`, `table_detect.py`를 작성한다.
5. `transcript_view.py`를 작성해 cell을 Textual widget으로 표시한다.
6. `composer.py`, `composer_bindings.py`, `footer.py`를 작성한다.
7. `app.py`를 얇게 정리하고 Textual 기본 실행 경로로 승격한다.
8. `/`, `@`, approval, tool folded output을 연결한다.
9. 기존 `layout.py`, `renderers.py`의 책임을 축소한다.
10. raw `terminal.py`는 fallback으로만 남기고 기본 경로 테스트에서 제외한다.
11. unit test -> Textual test -> 실제 TTY smoke 순서로 검증한다.

각 단계 완료 후 다음을 보고해야 한다.

- 생성/수정 파일 목록.
- 통과한 테스트 명령.
- 깨진 테스트와 원인.
- 다음 단계에서 참고해야 할 리스크.

## P9. GPT-5.5 구현 요청 시 추가 문구

이 문서를 구현 요청에 포함할 때 아래 문구를 반드시 추가한다.

```text
TUI 구현은 단순히 입력창을 화면 하단에 배치하는 것으로 끝내지 않는다.
Codex CLI처럼 답변 생성 중에도 composer가 사라지지 않아야 하며, running 중 Enter는 현재 turn steer, Tab은 다음 메시지 queue, Esc는 interrupt로 동작해야 한다.
Transcript는 문자열 배열이 아니라 committed cell과 active streaming cell을 분리한 구조로 구현한다.
Markdown stream은 raw token append가 아니라 newline boundary, table holdback, code fence 상태를 고려한 source-backed renderer로 구현한다.
Textual App은 agent loop 내부 상태를 직접 읽지 않고 AgentEvent -> UIEvent -> reducer -> widget 경로만 사용한다.
모든 구현은 테스트 가능한 완전한 코드로 작성하고, pass/TODO/구현 예정으로 핵심 로직을 생략하지 않는다.
```

## 완료 기준

이 계획은 아래 기준을 모두 만족해야 완료로 본다.

- Textual이 non-headless 기본 UI로 사용된다.
- running 중 composer가 disabled되지 않는다.
- running 중 Enter/Tab/Esc 의미가 분리되어 있다.
- transcript가 committed cell과 active cell을 가진다.
- Markdown stream이 source-backed state를 가진다.
- table, code fence, heading, list가 raw leakage 없이 렌더링된다.
- final answer가 streaming answer와 중복 출력되지 않는다.
- UI와 agent loop는 event/reducer 경계로 분리되어 있다.
- 실제 TTY에서 Codex CLI와 유사한 body scroll + persistent composer UX가 확인된다.
