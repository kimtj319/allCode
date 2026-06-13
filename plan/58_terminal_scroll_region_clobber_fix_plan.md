# 58. Terminal Scroll-Region Clobber Fix Plan

## 목적

interactive terminal-native UI(`allcode`)에서 실제 TTY 사용 시 화면이 깨지는
문제를 해결한다. 가장 심각한 증상은 사용자 프롬프트 줄이 어시스턴트 헤더에
덮여써져 `allCode<prompt-tail>` 형태로 글자가 겹치는 텍스트 손상이다.

이번 계획은 TUI 렌더링 경계 안에서만 수정한다. agent loop, routing, prompt
품질, tool policy, 모델 adapter는 변경하지 않는다.

## 참조 계약

- `plan/00_master_implementation_guide.md`: 파일 책임 분리, 500줄 초과 금지,
  실제 테스트 기반 완료.
- `plan/01_open_source_alignment_contracts.md`: TUI는 agent 내부 상태를 직접
  읽지 않고 event/rendering 경계만 사용.
- `plan/10_tui_app_plan.md`: user-visible transcript와 status-only 이벤트 분리.
- `plan/15_codex_tui_alignment_plan.md`, `plan/16_codex_default_terminal_ui_plan.md`:
  기본 UI는 terminal scroll-region 기반이며 raw 제어문자가 화면을 점령하면 실패.
- `plan/57_terminal_markdown_renderer_compaction_plan.md`: 직전 마크다운 compaction
  작업. 본 계획은 그 위에서 레이아웃/스크롤 영역 안정성을 다룬다.

## 재현 및 증거 수집 방법

실제 PTY로 `allcode` interactive UI를 구동해 raw 출력과 화면 상태를 캡처했다.

- `tmp_test_run/pty_driver.py`: `pty.fork`로 `.venv/bin/allcode`를 PTY에서 실행,
  100x30 창에 프롬프트를 입력하고 raw byte stream을 저장.
- `tmp_test_run/render_raw.py`: `pyte.HistoryScreen`로 raw stream을 사용자가 보는
  화면(스크롤백 포함)으로 복원.

테스트 프롬프트(plan/57과 동일):

1. `마크다운 표로만 기능/상태/비고 3열, 3행을 출력해줘.`
2. `짧은 파이썬 코드 블록 하나와 inline code 하나만 마크다운으로 출력해줘.`
3. `제목 1개, 짧은 인용문 1개, 번호 목록 2개를 마크다운으로 출력해줘.`

## 관찰된 증상

복원된 화면(`render_raw.py`)에서 확인:

```
allCode운 표로만 기능/상태/비고 3열, 3행을 출력해줘.   <- 헤더가 프롬프트를 덮어씀
기능         상태     비고
...
```
```
allCode파이썬 코드 블록 하나와 inline code 하나만 ...  <- 매 턴 동일하게 발생
```

1. (P0) 텍스트 손상: 어시스턴트 헤더 `allCode`가 사용자 프롬프트 `▌ <prompt>`의
   시작 부분을 덮어쓴다. 매 턴 재현된다.
2. (P1) 헤더 박스와 첫 본문 사이에 ~18행의 큰 빈 공백이 생긴다.
3. (P2) 코드 블록이 본문 문장과 시각적으로 구분되지 않는다.
4. (P2) 순서 목록이 `1.`이 아니라 `1`로 렌더링되는 등 사소한 마크다운 갭.

## 근본 원인 (raw escape sequence 추적으로 확정)

`tmp_test_run/t1.raw`, `t2.raw`의 제어 시퀀스를 디코딩한 결과:

1. 사용자 프롬프트 출력 시점: 예약 행 4, 스크롤 영역 `\e[1;26r`, 본문은 26행
   기준으로 출력되어 구분선이 25행에 commit된다.
2. 직후 running composer 렌더: activity(1) + spacer(1) + input(1) + footer(1) =
   line_count 4 → `needed_rows = max(4, line_count + 2) = 6`. `set_reserved_rows(6)`가
   스크롤 영역을 `\e[1;24r`로 **축소**한다 (`body_bottom` 26→24).
3. `render_bottom_frame`가 `_clear_prompt_area()`로 25~30행을 `\e[2K`로 지운다.
   이때 25행에 commit돼 있던 본문 줄이 지워진다.
4. 이후 본문 재개 시 `prepare_body_output()`가 새 `body_bottom`(24)로 이동하고,
   어시스턴트 헤더 `allCode`가 이전 프롬프트가 남아있던 행에 겹쳐 출력된다.

핵심: **턴 진행 중 `set_reserved_rows`가 예약 영역을 키우면서 스크롤 영역을
축소하는데, 이미 scrollback에 commit된 본문 줄을 보존하지 않고 잘라낸다.**

빈 공백(P1)의 원인: `TerminalScreen.prepare_body_output()`가 매 본문 출력마다
무조건 `body_bottom;1H`로 점프한다. 헤더가 상단(1~6행)에 출력된 직후 본문이
하단(26행)에서 시작되므로 그 사이가 비어 보인다.

원인 위치:

- `src/allCode/tui/terminal_screen.py`
  - `set_reserved_rows()` — 영역 축소 시 내용 비보존.
  - `prepare_body_output()` — 무조건 `body_bottom` 점프 (gap 유발).
  - `render_bottom_frame()` — `needed_rows` 계산 후 `_clear_prompt_area()`.
- `src/allCode/tui/terminal.py`
  - 본문 출력(`_print_user_prompt`, `_print_assistant_block`,
    `_print_assistant_stream_chunk`)과 running composer 렌더가 같은 예약 영역을
    공유.

## codex 피드백 반영 (2026-06-12)

read-only codex 검토에서 다음을 확인/보강했다.

- 근본 원인 분석은 정확함(`render_bottom_frame` → `set_reserved_rows` →
  `_clear_prompt_area`가 commit된 본문 줄을 지우는 시퀀스).
- Phase 1의 scroll-up 보존은 방향이 맞지만 **커서 상태에 민감**하므로 옛
  `body_bottom` 값으로 계산한 뒤에 `reserved_rows`를 변경하고, `\e[{delta}S`보다
  이식성 높은 newline/IND를 옛 영역 하단에서 emit한다.
- **턴 중 영역 리사이즈 자체를 피하는 편이 더 견고**하다. 러닝 컴포저 높이를
  high-water mark로 잡아 한 번 키운 뒤 세션 동안 줄이지 않는다(grow/shrink 반복
  점프 제거).
- Phase 2의 "화면 모델 내부 상태만으로 본문 행 추적"은 Rich가 stdout에 직접
  쓰고 wrapping이 있어 취약하다. 행 추적이 필요하면 **capture된 출력의 물리
  줄 수**(console.width 기준 wrapping 포함)로 정확히 센다.
- 창 리사이즈 대비로 마지막 적용 `body_bottom`/height를 저장한다.
- 테스트는 시퀀스 단정만으로 부족하며 pyte 렌더 화면 단정을 추가한다.

## 개선 방향 (원칙)

- scroll-region 기반 기본 UI 구조는 유지한다(plan/16 계약).
- 한 번 scrollback에 commit된 본문 줄은 어떤 경우에도 지우거나 덮어쓰지 않는다.
- **턴 중에는 예약 영역 크기를 바꾸지 않는다.** 러닝 컴포저 높이를 high-water로
  미리 확보하고, 키울 때만 내용 보존 scroll-up으로 처리하며, 줄이지 않는다.
- 본문 행 추적이 필요하면 capture 기반 물리 줄 수로만 계산한다.
- 특정 프롬프트/답변 문자열/테스트 케이스 이름을 하드코딩하지 않는다.
- 변경을 TUI 계층 내부로 제한하고 agent/core/provider와 결합하지 않는다.

## Phase 1. 안정 예약 높이 + 내용 보존 성장 (P0, 텍스트 손상 제거)

수정 대상: `src/allCode/tui/terminal_screen.py`

구현 내용:

1. `set_reserved_rows(rows)`를 **high-water + 내용 보존 성장**으로 변경한다.
   - 예약 행은 한 번 커지면 세션 동안 줄어들지 않는다(`reserved_rows`는
     단조 증가). 이로써 매 턴 4↔6 thrash와 그에 따른 점프/클로버가 사라진다.
   - 예약 행이 **증가**할 때만 동작한다. 변경 전 옛 `body_bottom`을 계산하고,
     옛 영역(`\e[1;{old_body_bottom}r`)을 보장한 뒤 커서를 `{old_body_bottom};1H`로
     옮기고 `\n` * delta를 emit해 본문을 위로 밀어 하단 delta행을 빈 행으로
     확보한다. 그 다음 `reserved_rows`를 갱신하고 새 영역을 적용한다.
   - 마지막 적용 `body_bottom`/height를 저장해 창 리사이즈 시 전체 레이아웃
     재설정으로 처리한다.
2. 부작용(커서 이동/스크롤)을 가지므로 보존 성장 경로는 `render_bottom_frame`
   내부 호출에 한정하고, 호출 직후 컴포저를 다시 그린다.
3. `_clear_prompt_area()`는 현재 예약 영역 안에서만 동작하며, 보존 성장 덕분에
   그 행에는 commit된 본문이 없음을 보장한다.

검증: PTY 재현에서 `allCode<prompt-tail>` 겹침이 사라지고 사용자 프롬프트 줄과
어시스턴트 헤더가 별도 행으로 분리되는지, 매 턴 점프가 없는지 확인.

## Phase 2. 헤더-본문 공백 제거 (P1, capture 기반 정확 추적)

수정 대상: `src/allCode/tui/terminal_screen.py`, `src/allCode/tui/terminal.py`

구현 내용:

1. `TerminalScreen`이 본문 커서 행 `_body_row`를 정수로 추적한다.
   - `enter()`/`clear_all()` 후 본문 시작 행으로 초기화(헤더 출력 줄 수 반영).
   - 본문 출력은 capture된 문자열의 물리 줄 수(`\n` 개수, console.width wrapping
     포함)만큼 `_body_row`를 증가시키며 `body_bottom`에서 clamp한다.
   - Phase 1의 보존 성장으로 본문이 위로 delta만큼 밀리면 `_body_row -= delta`.
2. `prepare_body_output()`는 `body_bottom`이 아니라 `_body_row`로 이동한다.
   본문이 아직 영역을 채우지 않았으면 헤더 직후부터 이어지고, 영역을 채운
   뒤에는 `body_bottom`과 같아져 기존 scroll 동작을 유지한다.
3. capture 측정과 실제 출력이 어긋날 위험이 있으면 보수적으로 `body_bottom`
   fallback을 사용한다(텍스트 손상보다 공백이 안전).

주의: 모든 본문 출력이 capture를 통과해야 줄 수 계산이 정확하다. 현재
`terminal_markdown_blocks._print_renderable_compact`는 이미 capture를 쓰므로,
헤더/프롬프트/스트림 청크 출력도 동일 경로로 줄 수를 합산한다.

## Phase 3. 코드 블록/마크다운 시각 보강 (P2)

수정 대상: `src/allCode/tui/terminal_markdown_blocks.py`

구현 내용:

1. fenced code block을 본문과 구분되도록 좌측 dim gutter(예: `▏`) 또는 옅은
   배경으로 조밀하게 출력한다. 상하 과한 공백은 추가하지 않는다(plan/57 유지).
2. 순서 목록은 `1.` 형태의 마커를 보존한다.
3. 변경은 compact renderer 내부에 한정하고, 예외 시 기존 Rich fallback을 유지한다.

(Phase 3는 P0/P1 검증 후 codex 피드백을 반영해 범위를 확정한다.)

## Phase 4. 회귀 테스트

수정 대상: `tests/tty/test_terminal_bottom_pane.py`,
`tests/tty/test_terminal_session_smoke.py`

테스트 항목:

1. 예약 행이 증가할 때 commit된 본문 줄이 `\e[2K`로 지워지지 않는지(또는 보존
   scroll-up 시퀀스가 선행되는지) 시퀀스 수준에서 검증.
2. 멀티턴 세션에서 어시스턴트 헤더가 사용자 프롬프트와 같은 행에 출력되지 않는지
   검증.
3. 짧은 답변에서 헤더 박스와 본문 사이 빈 행 수가 과도하지 않은지 검증.

테스트는 특정 프롬프트 문장 전체를 하드코딩하지 않고 렌더링 구조 특성만 검증한다.

## Phase 5. 검증

```bash
python -m pytest tests/tty
```

수동 검증(PTY 하니스):

```bash
source .venv/bin/activate
python tmp_test_run/pty_driver.py --cols 100 --rows 30 --out v1 \
  "마크다운 표로만 기능/상태/비고 3열, 3행을 출력해줘."
python tmp_test_run/render_raw.py v1.raw 100 30
```

관찰 기준:

- 사용자 프롬프트와 어시스턴트 헤더가 겹치지 않는다.
- 헤더 박스 직후 본문이 과도한 공백 없이 이어진다.
- 표/코드/인용문이 plan/57 기준대로 조밀하게 보인다.

## 구현 결과 (2026-06-12)

PTY 하니스(`tmp_test_run/pty_driver.py` + `render_raw.py`)로 실모델 검증 완료.

완료 항목:

- Phase 1 (P0): `set_reserved_rows`를 high-water + 내용 보존 성장으로 변경.
  어시스턴트 헤더가 사용자 프롬프트를 덮어쓰던 텍스트 손상이 사라졌고,
  매 턴 4↔6 thrash 점프가 제거됨.
- Phase 2 (P1): `_BodyRowCounter`로 본문 개행을 세어 `prepare_body_output`이
  추적된 본문 행으로 이동. 헤더 박스와 첫 본문 사이 ~18행 공백이 제거됨.
- Phase 3 (P2, codex 피드백 반영 확대):
  - 스트리밍 코드 펜스 holdback(`code`/`code_candidate` 모드)으로 코드 블록
    줄 단편화/이중 공백 제거.
  - 제목/인용문 라인 holdback(`block_line` 모드)으로 문장 경계 단편화 방지.
  - `_consume_quote` 후행 빈 줄 처리 수정으로 빈 `│` 줄 아티팩트 제거.
  - 순서 목록 `1.` 마커 보존, `_inline_markup`으로 표 셀/목록/인용문의
    인라인 코드·굵게·기울임 렌더(백틱/별표 누출 제거).
  - 블록(code/table/quote/heading) 주변 여백을 절제된 수준으로 추가(스트리밍
    청크 경계에서 문단 중간 분리가 생기지 않도록 `emitted`/`last_offset` 상태
    전파).
  - 사용자 프롬프트 과한 full-width 구분선 제거, 턴 사이 빈 줄로 분리.
  - `allCode` 라벨을 bold→dim으로 톤 다운.
  - 실행 중 푸터를 "Working · type /stop to cancel" 대신 모델/워크스페이스
    컨텍스트로 변경(활동 줄이 이미 working 상태 표시).

## Phase 4 (실제 Codex 레퍼런스 대조, 2026-06-13)

사용자 지시로 실제 Codex CLI(`codex --sandbox read-only`)를 동일 프롬프트로 PTY
구동(`tmp_test_run/codex_pty_driver.py`)해 렌더링 스타일을 직접 캡처·비교했다.
Codex는 alt-screen을 쓰므로 종료 전 가시 화면을 pyte로 덤프해 관찰했다.

관찰된 Codex 스타일과 allCode 정렬 작업:

- 사용자 프롬프트 마커 `▌` → `›` (Codex와 동일).
- 어시스턴트 턴을 `allCode` 텍스트 라벨 대신 dim `•` 마커 + 답변 본문 2칸
  들여쓰기로 렌더(`TerminalAnswerRenderer`가 scratch console로 렌더 후 줄마다
  들여쓰기, 첫 본문 줄은 `•` 마커). 비터미널 콘솔에서는 plain `• `.
- 표에 헤더 `━`(SIMPLE_HEAVY) 규칙 적용, 세로/외곽 보더 없음.
- 코드 블록 2칸 들여쓰기로 본문과 구분.
- 컴포저 위 full-width `────` 구분선 제거(Codex는 여백만).
- 실행 중 푸터를 모델/워크스페이스 컨텍스트로(활동 줄이 working 표시).

검증:

- `python -m pytest` → 772 passed, 3 skipped(마커/`›` 변경으로 TTY 테스트 3건
  업데이트).
- codex(read-only) 평가 추이: 80-83% → 90-92% → **94-95%**, "진짜 UI 깨짐 없음".
- 남은 차이(낮은 우선순위, Rich 한계/픽셀 튜닝): 표 per-column 규칙·행 구분선,
  블록 간 수직 리듬, dot-style 스피너 글리프.

참고: `마크다운으로 출력해줘` 류 프롬프트에서 모델이 마크다운 소스를 ```markdown
코드 펜스로 감싸 보여주는 경우가 있는데, 이때 `#`/`>`가 코드로 그대로 보이는
것은 의도된 코드 블록 렌더이며 UI 버그가 아니다(Syntax 하이라이팅 색상으로 확인).

## 남은 리스크

- scroll-up 기반 보존은 일부 터미널에서 scrollback 동작 차이가 있을 수 있다.
  실제 PTY(pyte) 및 수동 검증으로 확인한다.
- 본문 행 추적은 Rich 출력 줄 수와 어긋날 수 있어 보수적 fallback이 필요하다.
- 본 계획은 레이아웃 안정성에 집중하며, 색/테마 단위의 미세 parity는 후속 계획에서
  다룬다.
```
