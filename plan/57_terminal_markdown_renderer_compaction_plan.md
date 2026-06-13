# 57. Terminal Markdown Renderer Compaction Plan

## 목적

interactive terminal-native UI에서 최종 답변 Markdown이 Codex 스타일에 가깝게
읽히도록 코드 블록, 인용문, 표 렌더링의 과한 여백과 혼동되는 기호를 줄인다.

이번 계획은 출력 형태 개선만 다룬다. agent loop, routing, prompt 품질,
tool policy, 모델 adapter는 변경하지 않는다.

## 참조 계약

- `plan/00_master_implementation_guide.md`: 파일 책임 분리, 500줄 초과 금지,
  실제 테스트 기반 완료.
- `plan/01_open_source_alignment_contracts.md`: TUI는 agent 내부 상태를 직접
  읽지 않고 event/rendering 경계만 사용.
- `plan/10_tui_app_plan.md`: user-visible transcript와 status-only 이벤트 분리.
- `plan/15_codex_tui_alignment_plan.md`: Markdown stream은 source-backed,
  width-aware, stable/tail 구조를 유지.
- `plan/16_codex_default_terminal_ui_plan.md`: 기본 UI는 terminal scroll-region
  기반이며, raw Markdown 문법이나 과한 panel UI가 화면을 점령하면 실패.

## 현재 문제 분석

실제 `.venv/bin/allcode` interactive TTY 테스트에서 아래 문제가 확인되었다.

1. 코드 블록
   - `rich.markdown.Markdown` 기본 렌더링이 코드 블록 위아래에 넓은 공백 행을
     만든다.
   - 코드 블록이 명확한 compact block처럼 보이지 않고 단순 본문처럼 보인다.

2. 인용문
   - Rich 기본 blockquote가 `▌` 기호를 사용한다.
   - allCode는 사용자 입력 transcript에도 `▌`를 사용하므로 assistant 인용문과
     사용자 프롬프트가 시각적으로 충돌한다.

3. 표
   - Rich 기본 table 렌더링이 표 위아래에 space-only row를 둔다.
   - raw PTY 로그에는 padding 공백이 크게 남고, 실제 화면에서도 표 위아래가
     다소 느슨하다.

4. heading
   - Rich 기본 heading은 가운데 정렬과 underline이 강하게 적용된다.
   - Codex 스타일 terminal transcript에서는 답변 안의 heading이 본문 흐름을
     과도하게 깨지 않는 편이 낫다.

현재 원인 위치:

- `src/allCode/tui/terminal_answer_renderer.py`
  - `TerminalAnswerRenderer.render()`가 normalized Markdown을
    `Console.print(Markdown(normalized))`로 직접 출력한다.
- `src/allCode/tui/terminal.py`
  - `_print_assistant_block()`, `_print_assistant_stream_chunk()`가 위 renderer를
    호출한다.
- `src/allCode/tui/markdown_normalizer.py`
  - `<br>` 및 table fence 보정만 담당하며 시각 렌더링 정책은 없다.

## 개선 방향

Rich Markdown 전체를 제거하지 않는다. 대신 terminal-native 최종 답변용으로
작은 block renderer를 추가한다.

원칙:

- source Markdown은 유지하고, renderer 단계에서만 compact하게 표시한다.
- fenced code, Markdown table, blockquote, heading만 명시 처리한다.
- 나머지 문단/목록/inline code/bold는 Rich Markdown에 계속 맡긴다.
- 특정 프롬프트, 특정 답변 문자열, 테스트 케이스 이름을 하드코딩하지 않는다.
- TUI 계층 내부 변경으로 제한하고 agent/core/provider와 결합하지 않는다.

## Phase 1. Compact Markdown Block Renderer 추가

수정 대상:

- 신규: `src/allCode/tui/terminal_markdown_blocks.py`
- 수정: `src/allCode/tui/terminal_answer_renderer.py`

구현 내용:

1. Markdown source를 line 단위 block으로 분해한다.
2. fenced code block은 `rich.syntax.Syntax` 또는 plain `Text`로 조밀하게 출력한다.
   - 상하 공백 행을 추가하지 않는다.
   - language가 있으면 syntax highlight를 적용한다.
   - language가 없어도 코드 본문은 그대로 유지한다.
3. Markdown table block은 파이프 테이블을 파싱해 compact `rich.table.Table`로
   출력한다.
   - `box=None`, `show_edge=False`, `padding=(0, 1)` 정도의 조밀한 설정 사용.
   - 표 앞뒤 빈 행을 renderer가 추가하지 않는다.
   - separator alignment marker는 표시하지 않는다.
   - 현재 `Console.width`를 받아 폭이 좁거나 표가 너무 넓은 경우에는
     key-value bullet list fallback으로 전환한다.
4. blockquote는 사용자 프롬프트 기호 `▌`와 겹치지 않도록 dim `│` prefix로
   출력한다.
5. ATX heading(`#`, `##`)은 왼쪽 정렬 bold 텍스트로 출력한다.
   - 가운데 정렬/underline을 피한다.
6. compact renderer에서 예외가 발생하면 UI가 크래시하지 않도록 기존
   `rich.markdown.Markdown` 렌더링으로 graceful fallback한다.

## Phase 2. Existing Normalization과 Stream Contract 유지

수정 대상:

- `src/allCode/tui/terminal_answer_renderer.py`

구현 내용:

1. `normalize_terminal_markdown()`은 기존처럼 `<br>` 제거와 fence close를 유지한다.
2. `TerminalAnswerRenderer.render()`만 compact renderer를 사용한다.
3. streaming chunk는 현재처럼 `MarkdownStreamBuffer`가 table holdback을 처리하고,
   renderer는 들어온 chunk를 독립 block으로 렌더링한다.

주의:

- streaming 중 incomplete fence가 들어와도 normalizer가 fence를 닫아준다.
- table block이 분할 출력되지 않도록 기존 `MarkdownStreamBuffer` 테스트를
  유지한다.
- streaming 중에는 불완전한 code/table block을 적극적으로 새 box로 렌더링하지
  않는다. 기존 `MarkdownStreamBuffer`의 문장/표 holdback을 유지하고, compact
  renderer는 들어온 source의 완성된 block만 조밀하게 표시한다.
- 추후 streaming flicker가 발견되면 renderer가 아니라 `MarkdownStreamBuffer` 또는
  `MarkdownStreamState`의 stable/tail 경계에서 해결한다.

## Phase 3. TTY 회귀 테스트 추가

수정 대상:

- `tests/tty/test_terminal_body_output.py`

테스트 항목:

1. 코드 블록 렌더링 결과에 과한 Rich 기본 blank frame이 남지 않는지 확인.
2. blockquote 출력이 `▌` 대신 `│` prefix를 쓰는지 확인.
3. Markdown table 출력이 separator row를 노출하지 않고 table content를 보존하는지
   확인.
4. heading이 가운데 정렬/underline 기본 스타일에 의존하지 않고 텍스트를 보존하는지
   확인.
5. 폭이 좁은 터미널에서는 표가 화면을 과하게 밀지 않고 fallback 형식으로 렌더링되는지
   확인.

테스트는 특정 프롬프트 문장 전체를 하드코딩하지 않고, 렌더링 구조 특성만 검증한다.

## Phase 4. 검증

우선 실행:

```bash
python -m pytest tests/tty/test_terminal_body_output.py tests/tty/test_streaming_tables.py
```

확대 실행:

```bash
python -m pytest tests/tty
```

수동 검증:

```bash
.venv/bin/allcode
```

interactive TTY에서 아래 프롬프트를 직접 입력한다.

1. `마크다운 표로만 기능/상태/비고 3열, 3행을 출력해줘.`
2. `짧은 파이썬 코드 블록 하나와 inline code 하나만 마크다운으로 출력해줘.`
3. `제목 1개, 짧은 인용문 1개, 번호 목록 2개를 마크다운으로 출력해줘.`

관찰 기준:

- 표 앞뒤에 space-only blank row가 과도하게 보이지 않는다.
- 코드 블록 위아래에 큰 빈 영역이 생기지 않는다.
- blockquote가 사용자 prompt marker와 혼동되지 않는다.
- 답변이 일반 terminal scrollback 흐름 안에서 자연스럽게 출력된다.

## 남은 리스크

- Rich Markdown의 모든 문법을 직접 구현하지 않는다. 복잡한 nested Markdown은
  기존 Rich fallback이 더 안전할 수 있다.
- compact table parser는 일반 파이프 테이블만 대상으로 한다. HTML table,
  escaped pipe가 많은 고급 표는 Rich fallback이 필요할 수 있다.
- streaming chunk 단위 출력에서는 완성된 최종 답변보다 block 경계가 덜 안정적일 수
  있다. 기존 `MarkdownStreamBuffer` holdback으로 table만 우선 보호한다.
- 좁은 폭 fallback은 표 의미를 보존하는 데 초점을 둔다. 원본 Markdown table과
  시각적으로 완전히 동일한 표를 보장하지 않는다.
