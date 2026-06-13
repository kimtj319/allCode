# 62. Edit Diff UI (코드 생성·수정 시 diff 표시)

## 요구

코드 생성/수정 결과를 일반 텍스트("modified: path")가 아니라 Codex처럼 **변경 diff**로
보여달라.

## 현황 분석

- `write_file`/`patch_file` 도구는 이미 `EditTransaction`(before/after + unified
  diff)을 `ToolResult.metadata["transaction"]["diff"]`에 기록 중 → diff 데이터는
  이미 존재. 다만 terminal-native UI는 `ToolResult.content`("modified: path")만
  dim 텍스트로 출력.
- 승인(approval) 단계에는 이미 diff 미리보기가 있으나, **실행 후 결과 표시**가 plain.

## 구현 (terminal-native 기본 UI)

1. `tui/tool_timeline.py`: `ToolTimelineEntry.diff` 필드 추가. `build_tool_timeline_entry`
   가 transaction diff에서 `---`/`+++` 파일 헤더를 제거한 hunk 본문과 +/- 카운트를
   추출(`_edit_diff`). 요약 라인에 Codex식 `(+N -M)` 통계를 덧붙임(기존 라인 포맷은
   보존 → 기존 테스트 substring 매치 유지).
2. `tui/renderers.py`: `RenderedEvent.diff` 필드 추가, `_render_tool_execution_finished`
   에서 `entry.diff` 전달.
3. `tui/terminal.py`: `_print_diff` 추가 — 도구 요약 라인 아래에 색상 unified diff를
   렌더(추가=초록, 삭제=빨강, hunk 헤더=cyan, context=dim, 2칸 들여쓰기). 대용량 diff는
   80줄에서 잘라 "... N more diff lines ..." 표기. 신규 파일 생성도 `before=""`라 전부
   `+` 라인 diff로 표시됨(코드 생성 케이스 포함).

## 검증

- `_edit_diff` 단위: `• patch_file calc.py -> ok · patched: calc.py (+2 -0)` + 헤더 없는
  hunk 본문 확인.
- TTY 세션 테스트(`test_terminal_session_renders_edit_as_diff`): 실제 `TerminalSession.run()`
  경로로 `(+2 -0)`·diff 본문 라인·`@@`가 출력에 포함됨 확인.
- forced-terminal 색상: 추가/삭제/hunk에 ANSI 32/31/36 색상 코드 방출 확인.
- 전체 776 passed(무회귀).

## 비고

- 실 PTY 인터랙티브 캡처는 bracketed-paste 입력 구동 이슈로 턴이 제출되지 않아 시각
  캡처에 실패(테스트 하니스 한계). 렌더 경로 자체는 동일 `TerminalSession` 경로의
  결정론적 테스트 + 색상 테스트로 검증됨.
- headless 배치 보고는 별도 reporter라 이번 변경 범위 밖(요구는 인터랙티브 UI).
