# 16. Codex Default Terminal UI Alignment Plan

## 목적

이 문서는 `15_codex_tui_alignment_plan.md` 이후 실제 Codex CLI 기본 실행을 다시 관찰한 결과를 반영해, allCode의 기본 non-headless UI를 Codex 기본 실행 방식에 맞추기 위한 상세 수정 계획서다.

중요한 정정 사항은 다음과 같다.

- Codex 기본 실행은 단순 Textual류 중앙 transcript panel + 내부 스크롤 구조가 아니다.
- 현재 환경에서 확인한 Codex 기본 실행은 terminal scroll region을 조정해 하단 composer 영역을 보호하고, 본문은 터미널 출력 흐름 안에서 위로 밀려 올라가도록 동작한다.
- `codex --no-alt-screen`은 이를 더 명시적으로 scrollback 보존 모드로 설명하지만, 기본 실행에서도 `?1049h` alternate screen 진입 없이 scroll-region 기반 UI 동작이 확인되었다.
- 따라서 allCode가 Codex 기본 실행과 같은 사용감을 목표로 한다면, `TerminalSession` 계열을 고쳐 Codex 수준으로 끌어올린 뒤 기본 UI로 승격해야 한다.

단, 기존 terminal fallback을 그대로 기본화하면 `review/after.png`와 같은 UI 회귀가 발생할 수 있다. 이 문서의 핵심은 "terminal-native UI를 바로 기본화"가 아니라, "terminal-native renderer 품질을 먼저 Codex 수준으로 올린 뒤 기본화"하는 것이다.

## 참조한 기존 계획서

이 문서는 아래 계획서를 보강하거나 일부 정정한다.

- `00_master_implementation_guide.md`: 전체 구현 순서, 모듈화 원칙, 충돌 시 우선순위.
- `10_tui_app_plan.md`: 최초 TUI 앱 구조. Textual 중심 계획이므로 이 문서와 충돌하는 기본 UI 선택 부분은 `16`을 우선한다.
- `11_quality_testing_plan.md`: TTY 테스트, 품질 matrix, UI signal clarity 평가 기준.
- `15_codex_tui_alignment_plan.md`: persistent composer, transcript cell, event/reducer 경계, streaming markdown 보강 계획. 다만 `15`의 "Textual을 기본 non-headless UI로 승격" 항목은 이 문서가 정정한다.

충돌 시 우선순위는 다음과 같다.

1. `00`의 안전, workspace, approval, secret 관련 계약.
2. 이 문서의 Codex default terminal UI 계약.
3. `15`의 persistent composer, transcript, event/reducer, markdown stream 계약.
4. `10`의 Textual 기반 TUI 구조.
5. `13`, `14`의 검토 이력 부록.

## 실제 Codex 기본 실행 관찰 요약

실제 TTY에서 다음 형태로 Codex를 실행해 확인했다.

```bash
codex -C /private/tmp -s read-only -a never "파이썬 3.12 특징에 대해 정리해서 알려줘"
```

확인된 동작:

- 시작 시 신뢰 확인 화면 이후 `>_ OpenAI Codex` 로고와 model/directory 정보가 본문 영역에 표시된다.
- 하단 composer는 `›` 입력 영역과 model/directory context line으로 구성된다.
- 작업 중에는 composer 위쪽에 `Working (Ns · esc to interrupt)` 형태의 activity line이 표시된다.
- 화면 제어는 `\x1b[1;8r`, `\x1b[1;12r`, `\x1b[1;19r` 같은 scroll-region 조정 중심이다.
- 중앙 transcript widget 자체의 독립 스크롤바가 아니라, terminal body 영역이 scroll region 안에서 위로 밀려 올라간다.
- 종료 시 scroll region을 복구하고 token usage, resume id 같은 후속 정보를 일반 terminal 출력으로 남긴다.

따라서 Codex 기본 실행의 핵심은 "full-screen TUI panel"보다 "terminal-native scroll-region shell"에 가깝다.

## 현재 allCode 상태와 문제

현재 allCode에는 두 UI 계열이 존재한다.

1. Textual 기반 `AllCodeApp`
   - 위치: `src/allCode/tui/app.py`
   - 장점: Markdown widget, layout, command palette 구현이 깔끔하다.
   - 문제: 중앙 transcript가 `overflow-y: auto`인 panel 내부 스크롤 구조다. Codex 기본 실행과 다르다.

2. terminal-native `TerminalSession`
   - 위치: `src/allCode/tui/terminal.py`, `terminal_screen.py`, `terminal_input.py`
   - 장점: Codex처럼 scroll-region과 하단 composer를 구현할 수 있는 구조가 있다.
   - 문제: 현재 상태를 그대로 기본화하면 `review/after.png`처럼 Markdown, table, `<br>`, 강조 문법, composer 배경이 깨질 수 있다.

따라서 기본 UI 전환은 마지막 단계에서만 수행한다.

## 최종 UI 계약

allCode 기본 실행은 아래 계약을 만족해야 한다.

```text
╭─────────────────────────────────────────────╮
│ >_ allCode                                  │
│ model: ...                                  │
│ directory: ...                              │
╰─────────────────────────────────────────────╯

› 사용자 요청

• 작업 상태 또는 도구 사용 내역

allCode
답변 본문...

──────────────────────────────────────────────
⠋ Working (3s · esc to interrupt)

› composer draft
  model · workspace · approval
```

상세 계약:

- 로고는 일반 본문 출력이어야 한다. 고정 header로 남지 않는다.
- 본문은 terminal scroll-region 안에서 위로 밀려 올라가야 한다.
- 중앙 panel 전용 스크롤바를 사용하지 않는다.
- composer는 하단에 고정된다.
- idle 상태에서는 `입력 대기 중`을 강하게 표시하지 않는다.
- 작업 중에만 spinner와 activity message를 표시한다.
- activity line과 composer 사이에는 최소 1줄 여백을 둔다.
- Markdown은 final answer 기준으로 raw 문법이 대량 노출되지 않아야 한다.
- `review/after.png`처럼 `<br>`, `**bold**`, raw table이 그대로 화면을 점령하면 실패다.

## 비목표

이번 작업에서 하지 않는 것:

- agent loop, routing, tool policy 자체 변경.
- LLM prompt 품질 정책 변경.
- Textual UI 완전 제거.
- 복잡한 diff/approval modal 재설계.

Textual UI는 당장 제거하지 않는다. Codex 기본 UI와 다른 모드로 남기되, 기본 실행 경로에서는 사용하지 않는 방향으로 정리한다.

## P0. UI 회귀 기준 고정

### 수정 대상

- `review/after.png`
- `tests/tty/test_terminal_body_output.py`
- `tests/tty/test_terminal_bottom_pane.py`
- 신규 후보: `tests/tty/test_terminal_codex_default_ui.py`

### 작업 내용

1. `after.png`에서 확인된 문제를 명시적 회귀 조건으로 고정한다.
2. ANSI snapshot 또는 virtual TTY 출력 기반으로 다음 실패 조건을 테스트한다.
   - `<br>`가 최종 답변에 그대로 노출됨.
   - `**강조**`가 대량 raw text로 노출됨.
   - Markdown table이 터미널 폭을 무시하고 깨짐.
   - idle 상태에서 `입력 대기 중`이 composer 바로 위에 붙어 있음.
   - composer가 전체 폭 회색 막대처럼 렌더링됨.
   - status line과 composer 사이 여백이 없음.
3. 기존 slash command, prompt input, body output 테스트는 유지한다.

### 검증

```bash
.venv/bin/python -m pytest tests/tty/test_terminal_body_output.py tests/tty/test_terminal_bottom_pane.py
```

### 리스크

- 이미지 자체를 테스트에 직접 쓰면 brittle하다.
- 따라서 이미지는 사람이 확인하는 기준으로 두고, 테스트는 ANSI/text 특징을 기준으로 작성한다.

## P1. Terminal UI 모듈 경계 재정의

### 수정 대상

- `src/allCode/tui/terminal.py`
- `src/allCode/tui/terminal_screen.py`
- `src/allCode/tui/terminal_frame.py`
- 신규 후보:
  - `src/allCode/tui/terminal_activity.py`
  - `src/allCode/tui/terminal_composer_renderer.py`
  - `src/allCode/tui/terminal_answer_renderer.py`
  - `src/allCode/tui/terminal_stream_renderer.py`

### 작업 내용

`TerminalSession`이 모든 렌더링을 직접 처리하지 않도록 책임을 나눈다.

권장 책임:

- `terminal.py`: session lifecycle, prompt loop, slash command dispatch, agent event dispatch.
- `terminal_screen.py`: cursor 이동, scroll-region, bottom reserved rows, clear/redraw primitives.
- `terminal_frame.py`: bottom pane render DTO.
- `terminal_activity.py`: spinner frame, elapsed time, status message policy.
- `terminal_composer_renderer.py`: activity, spacer, input, footer를 조합해 bottom frame 생성.
- `terminal_answer_renderer.py`: final answer Markdown normalization/rendering.
- `terminal_stream_renderer.py`: streaming 중 안전한 line-buffer 출력.

### 리스크

- 모듈 분리 중 raw mode 입력, slash completion, EOF 처리 동작이 깨질 수 있다.

### 완화

- 분리 직후 `tests/tty/test_slash_exit.py`, `tests/tty/test_terminal_bottom_pane.py`, `tests/tty/test_terminal_body_output.py`를 먼저 실행한다.

## P2. Composer Frame을 Codex 기본 실행 방식으로 재설계

### 수정 대상

- `src/allCode/tui/terminal_frame.py`
- `src/allCode/tui/terminal_bottom_pane.py`
- `src/allCode/tui/terminal_screen.py`
- `src/allCode/tui/terminal_footer.py`
- `src/allCode/tui/terminal_input.py`

### 작업 내용

현재 `TerminalFrame`은 input, overlay, footer 중심이다. 이를 다음 구조로 확장한다.

```python
@dataclass(frozen=True)
class TerminalFrame:
    activity_lines: list[StyledLine]
    input_lines: list[StyledLine]
    overlay_lines: list[StyledLine]
    footer_lines: list[StyledLine]
    cursor_row: int
    cursor_col: int
```

렌더링 순서:

1. top separator.
2. activity line. running 상태일 때만 표시.
3. spacer blank line.
4. input lines.
5. overlay lines. slash/path completion.
6. footer/context line.

idle 상태:

```text
────────────────────────────────────────

› Ask allCode
  model · workspace · approval
```

running 상태:

```text
────────────────────────────────────────
⠋ Working (3s · esc to interrupt)

› Ask allCode
  model · workspace · approval
```

### 리스크

- 작은 터미널 높이에서 reserved rows가 너무 커져 본문이 사라질 수 있다.

### 완화

- `max_reserved_rows`를 유지한다.
- height가 작은 경우 activity/footer 중 덜 중요한 줄을 생략한다.
- 입력 줄은 최소 1줄 보장한다.

## P3. Idle Status와 Activity Status 분리

### 수정 대상

- `src/allCode/tui/messages.py`
- `src/allCode/tui/footer.py`
- `src/allCode/tui/terminal_footer.py`
- `src/allCode/tui/renderers.py`

### 작업 내용

1. `READY_STATUS = "입력 대기 중"` 값 자체는 유지하되, terminal UI 표시에서는 숨긴다.
2. idle 상태에서는 context footer만 표시한다.
3. running 상태에서는 activity line만 표시한다.
4. activity label은 Codex 스타일로 짧고 직접적으로 유지한다.

권장 표시:

- `Working (0s · esc to interrupt)`
- `Running tool: read_file`
- `Waiting for model`
- `Validating`
- `Repairing`

한국어 모델/설정이어도 UI control label은 Codex와 맞추기 위해 짧은 영어 중심으로 유지할 수 있다. 단, 오류 메시지와 최종 답변은 사용자 언어를 따른다.

### 리스크

- 사용자가 idle 상태를 인지하기 어려울 수 있다.

### 완화

- composer placeholder와 cursor를 명확히 표시한다.
- footer context line을 유지한다.

## P4. Markdown Final Renderer 보강

### 수정 대상

- `src/allCode/tui/terminal.py`
- `src/allCode/tui/terminal_markdown.py`
- `src/allCode/tui/markdown_normalizer.py`
- 신규 후보: `src/allCode/tui/terminal_answer_renderer.py`

### 작업 내용

1. final answer 출력 전 항상 `normalize_agent_markdown()`을 적용한다.
2. `<br>`, `<br/>`, `<br />`는 줄바꿈으로 변환한다.
3. 긴 Markdown table은 terminal 폭 기준으로 아래 중 하나로 처리한다.
   - Rich Markdown table이 안전하게 렌더링 가능한 경우 table로 출력.
   - 폭이 부족하면 compact bullet list로 변환.
4. code fence는 fence marker보다 코드 본문 가독성을 우선한다.
5. streaming 중 출력과 final 출력이 중복되지 않도록 stream lifecycle을 명확히 한다.

### 리스크

- table을 list로 바꾸면 원본 구조가 일부 손실될 수 있다.

### 완화

- 폭이 충분한 경우 table 유지.
- 폭이 부족하거나 column 수가 많은 경우에만 compact 변환.

## P5. Streaming Renderer 안정화

### 수정 대상

- `src/allCode/tui/terminal_markdown.py`
- 신규 후보: `src/allCode/tui/terminal_stream_renderer.py`

### 작업 내용

1. streaming 중에는 token 단위 raw 출력 대신 line boundary 중심으로 출력한다.
2. Markdown table 후보는 최소 header + separator가 확인될 때까지 holdback한다.
3. code block은 fence state를 추적한다.
4. final answer 도착 시 stream buffer를 flush하고, 최종 renderer가 정돈된 답변을 책임진다.

### 리스크

- holdback이 과하면 모델이 답변 중인데 화면 변화가 적어 답답해 보일 수 있다.

### 완화

- 300~500ms 이상 holdback되면 안전한 plain line으로 flush한다.
- activity spinner는 계속 갱신한다.

## P6. Scroll-region 기반 본문 출력 보강

### 수정 대상

- `src/allCode/tui/terminal_screen.py`
- `src/allCode/tui/terminal.py`

### 작업 내용

1. `enter()`는 화면 전체를 무조건 alt-screen처럼 다루지 않는다.
2. 하단 composer reserved rows만 보호한다.
3. body output 전에는 composer 영역을 지우고 scroll-region의 마지막 줄로 커서를 이동한다.
4. body output 후에는 composer를 다시 그린다.
5. exit 시 scroll-region을 반드시 `\x1b[r`로 복구한다.
6. 로고와 transcript는 일반 본문 출력으로 남긴다.

### 리스크

- 터미널별 ANSI 호환성 차이가 있다.

### 완화

- 실제 iTerm2, macOS Terminal, VSCode terminal 중 최소 한 곳에서 실사용 검증한다.
- virtual TTY 테스트에는 escape sequence 존재 여부를 검증한다.

## P7. 기본 UI 전환

### 수정 대상

- `src/allCode/main.py`
- `src/allCode/tui/runtime.py`
- `tests/unit/test_entrypoint.py`
- `tests/tty/test_tui_smoke.py`

### 작업 내용

품질 개선과 테스트가 통과한 뒤에만 기본 UI를 전환한다.

권장 CLI:

```text
allcode            -> Codex-like terminal-native UI
allcode --textual  -> Textual UI fallback/experimental
allcode --headless -> non-interactive headless runner
```

`--plain-terminal`은 기존 호환을 위해 당분간 alias로 유지한다.

### 리스크

- 기존 Textual 기반 테스트와 문서가 기본 실행을 잘못 설명할 수 있다.

### 완화

- README와 AGENTS 문서에서 기본 UI와 Textual optional UI를 분리해 설명한다.
- 테스트 파일명을 terminal/textual 기준으로 분리한다.

## P8. 실제 TTY 검증

### 검증 프롬프트

최소 아래 프롬프트를 실제 TTY에서 실행한다.

```text
파이썬 3.12 특징에 대해 정리해서 알려줘
```

```text
현재 디렉터리의 src 구조를 설명해줘. 코드 수정은 하지 마.
```

```text
간단한 FastAPI ping 서버를 workspace에 만들어줘.
```

```text
/help
```

```text
/exit
```

### 성공 기준

- 로고가 고정되지 않고 본문과 함께 위로 밀린다.
- 중앙 panel 전용 스크롤바가 없다.
- 하단 composer는 작업 중에도 유지된다.
- 작업 중 activity line에 spinner가 보인다.
- idle 상태에서 `입력 대기 중`이 과하게 노출되지 않는다.
- activity line과 composer 사이 여백이 있다.
- Markdown이 `after.png`처럼 깨지지 않는다.
- slash command와 exit가 정상 동작한다.

## 권장 실행 순서

1. P0 회귀 기준 테스트 작성.
2. P1 terminal UI 모듈 경계 정리.
3. P2 composer frame 재설계.
4. P3 idle/activity status 분리.
5. P4 final Markdown renderer 보강.
6. P5 streaming renderer 안정화.
7. P6 scroll-region 본문 출력 보강.
8. P8 실제 TTY 검증.
9. 모든 기준 통과 후 P7 기본 UI 전환.
10. README, AGENTS, 테스트 문서 업데이트.

이 순서를 지키지 않고 P7을 먼저 수행하면 `review/after.png` 형태의 UI 회귀가 재발할 가능성이 높다.
