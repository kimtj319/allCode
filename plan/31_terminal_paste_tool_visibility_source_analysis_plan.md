# 31. Terminal Paste, Tool Visibility, and Source Analysis Quality Plan

## 목적

이 문서는 `plan/30_source_analysis_language_tooling_hardening_plan.md` 구현 후
실제 `allcode` TTY 실행에서 확인된 잔여 문제를 닫기 위한 후속 보강 계획이다.

실제 출력에서 확인된 문제는 다음 네 가지다.

1. 사용자 입력 앞뒤에 `[200~`, `[201~`가 그대로 섞였다.
2. read-only 분석 중 `inspect`, `read_file` 도구 행과 절대 경로가 transcript에
   과하게 노출되었다.
3. 모델이 final answer 대신 reasoning-only로 끝난 경우, fallback 답변에
   `model_returned_reasoning_only_after_retry` 같은 내부 사유가 사용자에게 보였다.
4. `src` 전체 역할 분석인데 `source_overview` 1회와 `main.py` 1개 읽기에
   의존해 답변 근거가 얕고 일부 모듈 설명이 추론에 치우쳤다.

추가로, 프롬프트 입력 영역에서 일반적인 한국어 입력기 경험과 다르게 조합 중인
글자가 자연스럽게 표시/진행되지 않고 한 문자열을 모두 입력한 뒤에야 반영되는
문제가 확인되었다. 이는 한국어 IME 조합, raw mode byte reading, redraw 타이밍
사이의 경계 문제로 보고 입력 처리 Phase에서 함께 해결한다.

이 계획은 새 제품 범위를 확장하지 않는다. MCP manager, plugin marketplace,
multi-agent swarm, cloud sandbox, full LSP integration, git auto-commit,
provider-specific branching은 계속 제외한다.

## 우선순위와 계약

구현 전 아래 순서를 다시 따른다.

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/10_tui_app_plan.md`
6. `plan/11_quality_testing_plan.md`
7. `plan/16_codex_default_terminal_ui_plan.md`
8. `plan/29_readonly_approval_terminal_remediation_plan.md`
9. `plan/30_source_analysis_language_tooling_hardening_plan.md`
10. 이 문서

충돌 시 `plan/00`~`12`와 `plan/01`의 open-source alignment 계약을 우선한다.

## 공개 오픈소스 참조 요약

- Aider repo map은 Tree-sitter 기반 definition/reference tag를 추출하고,
  reference graph ranking과 token budget을 사용해 전체 파일 dump 없이 관련
  symbol tree를 제공한다.
  - https://deepwiki.com/Aider-AI/aider/4.1-inputoutput-system
- Gemini CLI는 `GEMINI.md`를 global/project/ancestor/sub-directory 계층으로
  병합하고 `/memory show`, `/memory refresh`, `/memory add`로 활성 context를
  사용자가 확인할 수 있게 한다.
  - https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- Qwen Code는 filesystem 도구를 `list_directory`, `read_file`, `glob`,
  `grep_search`, `edit`처럼 목적별로 나누고, `glob` 결과를 제한해 context
  overflow를 방지한다.
  - https://qwenlm.github.io/qwen-code-docs/en/developers/tools/file-system/
- OpenHands는 Tool System을 `Action -> Observation` 계약으로 분리하고,
  tool result는 LLM용 observation과 UI용 visualization을 분리할 수 있는 구조로
  관리한다.
  - https://docs.openhands.dev/sdk/arch/tool-system
- OpenHands conversation runtime은 stuck detection을 마지막 이벤트 window에
  제한해 같은 action-observation 반복을 비용 낭비 전에 끊는다.
  - https://docs.openhands.dev/sdk/api-reference/openhands.sdk.conversation
- bracketed paste mode는 터미널이 paste 시작/끝을 `ESC [ 200 ~`,
  `ESC [ 201 ~`로 감싸 애플리케이션이 붙여넣기를 일반 타이핑과 구분하게 하는
  프로토콜이다. Readline도 paste를 단일 문자열로 삽입하기 위해 이 모드를 쓴다.
  - https://terminalguide.namepad.de/mode/p2004/
  - https://www.gnu.org/s/bash/manual/html_node/Readline-Init-File-Syntax.html

## agy 검토 반영 요약

agy에는 코드 수정 금지, artifact 생성 금지, 계획 검토만 요청했다. 검토 결과
현재 코드에 바로 반영해야 할 계획 누락은 다음 세 가지다.

1. `src/allCode/agent/finalization_helpers.py`의 `last_tool_results()`가 message
   history에서 tool result를 복원할 때 metadata를 충분히 보존하지 않으면,
   fallback summary와 Phase 3 coverage 개선이 `truncated`, `suggested_reads`,
   `representative_reads` 같은 근거를 잃는다.
2. `src/allCode/agent/inspect_summary.py`의 `ROLE_HINTS_EN`,
   `ROLE_HINTS_KO`는 현재 저장소 구조에 가까운 static role dictionary다.
   다른 repository 분석에서는 잘못된 역할을 말할 수 있으므로 제거하고,
   `source_overview` metadata에서 계산한 dynamic package roles를 사용해야 한다.
3. `inspect_staging`이 `targeted_read`로 전환되더라도 prompt가 “근거가 충분하면
   final answer”를 강조하면 모델이 대표 파일을 읽지 않고 조기 종료할 수 있다.
   따라서 `targeted_read` 단계에서는 `suggested_reads` 또는
   `representative_reads`를 명시해 “이 파일들을 우선 확인하라”는 단계 지시가
   필요하다.

agy가 지적한 테스트 리스크:

- Phase 2에서 tool row를 `status_only`로 낮추면 기존
  `tests/tty/test_terminal_readonly_source_analysis.py`의 compact/foldable tool row
  assertion이 깨질 수 있다. Phase 0에서 신규 테스트 추가와 함께 기존 assertion을
  동시에 정정한다.
- paste sanitizer는 keymap 내부가 아니라 입력 경계에서 적용해야 한다. 적용 지점은
  `_read_line_mode()`, `_read_interactive_line_mode()`,
  `_read_bracketed_paste()`, `PasteManager.insert_paste()`로 제한한다.

## 금지 사항

- 특정 프롬프트 문장, 특정 테스트 ID, 특정 프로젝트명, 특정 경로명을 source에
  직접 박지 않는다.
- `src`, `allCode`, `main.py` 같은 현재 재현 경로 전용 예외 코드를 만들지 않는다.
- read-only route에서 mutation, shell, approval을 열지 않는다.
- UI가 agent 내부 상태를 직접 import하지 않는다. TUI는 core event와 UI-facing
  renderer만 소비한다.
- source analysis를 위해 full-file dump를 만들지 않는다.
- 모델명 또는 provider명으로 branching하지 않는다.
- 내부 에러 코드, recovery reason, parser status를 사용자 최종 답변에 그대로
  노출하지 않는다.
- 현재 저장소의 패키지명 또는 디렉터리명을 역할 판정 dictionary로 하드코딩하지
  않는다. 역할 설명은 source overview, symbol/import/file layout evidence에서
  동적으로 도출한다.
- 모든 신규/수정 Python 파일은 반드시 500줄을 넘기지 않도록 모듈화한다.
  300줄을 넘기기 시작하면 분리 후보로 보고, 500줄에 도달하기 전에 책임 단위로
  파일을 나눈다. 테스트 파일도 과도하게 커지면 fixture/helper/data 파일로 분리한다.

허용되는 일반화 신호:

- bracketed paste delimiter sequence, raw line-mode paste marker.
- `RoutingDecision.kind`, `read_only_requested`, `target_hint`, explicit target.
- `ToolResult.metadata.observation`, `source_overview_paths`,
  `source_overview_summaries`, `suggested_reads`, `truncated`, `omitted_files`.
- `source_overview`가 계산한 `package_roles`, `representative_reads`,
  `coverage`.
- package/module inventory depth, file count, symbol count, representative file
  coverage.
- event severity와 UI render category.
- `CompletionEvidence`의 inspect observation과 read-only no-mutation evidence.

## Phase 0. 기준 재현과 회귀 조건 고정

### 목표

이번 보강은 먼저 현재 문제를 테스트로 고정한 뒤 구현한다.

### 수정 대상

- `tests/tty/test_terminal_paste_sequences.py` 신규
- `tests/tty/test_terminal_readonly_tool_visibility.py` 신규 또는 기존 TTY 테스트 보강
- `tests/unit/agent/test_inspect_summary.py` 신규
- `tests/unit/agent/test_finalization_helpers.py` 보강
- `tests/unit/tools/test_source_overview_tool.py`
- `tests/integration/test_readonly_source_analysis.py`
- 기존 `tests/tty/test_terminal_readonly_source_analysis.py` assertion 정정

### 테스트해야 할 실패 조건

1. raw-mode 입력에서 `\x1b[200~prompt\x1b[201~`를 붙여넣으면 제출 prompt에
   delimiter가 포함되지 않는다.
2. line-mode 또는 fallback 입력에서 `[200~prompt[201~`, `^[[200~prompt^[[201~`,
   `\x1b[200~prompt\x1b[201~` 형태가 들어와도 sanitizer가 제거한다.
3. read-only inspect route의 transcript에는 절대 경로를 포함한 raw tool 행이
   기본 출력되지 않는다.
4. debug log에는 tool action/observation이 남지만, user-visible transcript는
   `코드 구조 확인 중`, `대표 파일 확인 중`, `답변 정리 중`처럼 compact하다.
5. reasoning-only fallback 답변은 내부 reason code를 노출하지 않고, 사용자가
   요청한 언어로 “확인한 근거 / 요약 / 더 확인하면 좋은 항목”을 제공한다.
6. `src` 같은 directory target 분석은 top-level package별 대표 근거를 일정
   수 이상 확보한다. 특정 이름이 아니라 “directory target + source overview
   truncated + representative reads 부족”이라는 일반 조건으로 판단한다.
7. tool result message history에서 복원한 `ToolResult.metadata`가 `truncated`,
   `suggested_reads`, `representative_reads`, `package_roles`, `coverage`를
   보존한다.

### 검증 명령

```bash
python -m pytest tests/tty/test_terminal_paste_sequences.py tests/tty/test_terminal_readonly_tool_visibility.py
python -m pytest tests/unit/agent/test_inspect_summary.py tests/unit/agent/test_finalization_helpers.py tests/unit/tools/test_source_overview_tool.py
python -m pytest tests/integration/test_readonly_source_analysis.py
```

## Phase 1. Bracketed Paste 입력 방어 강화

### 현재 문제

`TerminalKeyReader`는 raw mode에서 `ESC [ 200 ~`를 파싱하지만,
escape 이후 입력 대기 시간이 짧거나 fallback/line-mode로 들어오는 경우
`[200~`, `[201~`가 prompt 본문에 남을 수 있다.

또한 한국어 입력기에서는 조합 중인 글자가 일반적인 터미널 입력처럼 즉시
보이지 않거나, 조합이 끝난 문자열 단위로만 editor buffer에 반영되는 문제가
있다. 사용자는 입력 중인 한국어 문장을 자연스럽게 확인해야 하며, Enter 제출
전까지 composer가 깨지거나 지연되어서는 안 된다.

### 수정 대상

- `src/allCode/tui/terminal_keys.py`
- `src/allCode/tui/terminal_input.py`
- `src/allCode/tui/terminal_paste.py`
- `src/allCode/tui/terminal_text_area.py`
- `src/allCode/tui/terminal_width.py`
- 신규 후보: `src/allCode/tui/terminal_paste_sanitizer.py`
- 신규 후보: `src/allCode/tui/terminal_ime.py`

### 구현 계획

1. `terminal_paste_sanitizer.py`를 추가한다.
   - public API:
     - `strip_bracketed_paste_markers(text: str) -> str`
     - `normalize_pasted_text(text: str) -> str`
   - 처리 대상:
     - `\x1b[200~`, `\x1b[201~`
     - `^[ [200~`류로 문자열화된 escape 표현
     - 선행 `[200~`, 후행 `[201~`
   - 본문 중 일반 문자열까지 과도하게 지우지 않도록 경계 조건을 둔다.
     - 시작부/끝부분 marker 제거
     - line 시작 marker 제거
     - marker가 code block 내부 일반 텍스트로 등장하는 경우는 보존
2. `TerminalKeyReader._read_bracketed_paste()`는 delimiter 수신 실패 시에도
   sanitizer를 적용한다.
3. `TerminalInputEditor._read_line_mode()`와 `_read_interactive_line_mode()`에도
   sanitizer를 적용한다.
4. `PasteManager.insert_paste()`는 sanitizer 이후 CRLF normalize를 수행한다.
5. raw mode 진입/종료 시 `?2004h`, `?2004l` 상태를 유지하되, 예외 종료에서도
   disable sequence가 flush되는지 테스트한다.
6. keymap 단계에서는 sanitizer를 호출하지 않는다. `paste:` command는 이미 정제된
   text만 받게 해 `TerminalTextArea`와 placeholder 동작을 건드리지 않는다.
7. 한국어 IME 입력을 별도 경계로 검토한다.
   - UTF-8 multibyte sequence를 문자 단위로 안전하게 조립한 뒤 `TerminalTextArea`
     에 전달한다.
   - 조합 중 문자와 확정 문자를 구분할 수 없는 환경에서는 최소한 확정된 문자열이
     즉시 redraw되고, 다음 입력/삭제/커서 이동이 깨지지 않도록 한다.
   - display width 계산은 `terminal_width.py`로 유지하되, Hangul wide character와
     combining mark가 cursor column을 밀어내지 않는지 테스트한다.
   - 구현이 커질 경우 `terminal_ime.py`에 UTF-8/IME boundary 처리를 분리해
     `terminal_keys.py`가 500줄을 넘지 않게 한다.

### 수용 기준

- 사용자가 복사/붙여넣기로 prompt를 입력해도 `[200~`, `[201~`, `^[[200~`가
  에이전트 prompt와 transcript에 남지 않는다.
- multiline paste는 여전히 한 덩어리로 들어가며, threshold 초과 시 기존
  paste placeholder 기능을 유지한다.
- 한국어 입력 시 조합/확정된 문장이 composer에 자연스럽게 표시되고, 제출된
  prompt가 글자 누락/중복/제어문자 없이 모델에 전달된다.
- 입력 처리 관련 신규/수정 파일은 500줄 미만을 유지한다.

## Phase 2. Tool Visibility와 Transcript 정책 정리

### 현재 문제

도구 사용이 user-visible transcript에 raw 행으로 출력되어, 실제 답변보다
도구 로그가 더 강하게 보인다. 절대 경로도 그대로 노출된다.

### 수정 대상

- `src/allCode/tui/renderers.py`
- `src/allCode/tui/terminal.py`
- `src/allCode/tui/event_bridge.py`
- `src/allCode/core/events.py` 필요 시 event metadata만 보강
- `tests/tty/test_terminal_readonly_tool_visibility.py`
- `tests/unit/telemetry/test_session_logger.py`

### 구현 계획

1. OpenHands의 `Action -> Observation` 분리를 allCode UI에 맞게 적용한다.
   - 로그/telemetry에는 action/observation 전체를 남긴다.
   - 사용자 transcript에는 visualization-safe 요약만 출력한다.
2. `RenderedEvent`에 `visibility_mode` 또는 `display_priority`를 추가하지 않고,
   기존 `severity`와 `transcript_role`을 먼저 활용한다.
   - `source_overview`, `list_tree`, `glob_files`, `read_file` 성공은 기본적으로
     `status_only` 또는 compact status로 렌더링한다.
   - 실패, approval, validation failure, final answer는 user-visible 유지.
3. read-only inspect route의 tool result는 다음처럼 표시한다.
   - 하단 status: `코드 구조 확인 중`, `대표 파일 확인 중`, `답변 정리 중`
   - transcript: 기본적으로 tool row 생략
   - debug/session log: 기존 action/observation 유지
4. 절대 경로는 UI 표시 전 workspace-relative로 변환한다.
5. 사용자가 debug mode를 켠 경우만 compact tool rows를 transcript에 출력할 수
   있도록 후속 확장 여지를 둔다. 이번 단계에서는 debug mode flag 추가 없이
   기본 출력을 조용하게 만든다.

### 수용 기준

- read-only source 분석 결과 화면에서 raw `• read_file /absolute/path -> ok`가
  기본 표시되지 않는다.
- session jsonl에는 tool call/result가 계속 기록된다.
- approval이 필요한 mutation tool은 기존처럼 사용자에게 명확히 표시된다.

## Phase 3. Source Analysis Evidence Coverage 보강

### 현재 문제

`source_overview`는 symbol/file inventory를 제공하지만, directory target이
크고 결과가 truncated되면 representative read가 부족해 최종 답변이 얕아진다.

### 수정 대상

- `src/allCode/tools/builtin/source_overview.py`
- `src/allCode/agent/inspect_staging.py`
- `src/allCode/agent/finalization_helpers.py`
- `src/allCode/agent/tool_evidence.py`
- `src/allCode/core/result.py`
- `src/allCode/agent/prompt_builder.py`
- `tests/unit/tools/test_source_overview_tool.py`
- `tests/unit/agent/test_finalization_helpers.py`
- `tests/unit/agent/test_inspect_tool_staging.py`
- `tests/integration/test_readonly_source_analysis.py`

### 구현 계획

1. Aider repo map 방식을 현재 구현 수준에 맞춰 강화한다.
   - full PageRank/LSP는 도입하지 않는다.
   - 기존 `WorkspaceIndexer`, `RepoMapBuilder` 결과를 사용해 package별
     representative score를 계산한다.
   - 점수 신호:
     - entrypoint 파일명
     - public class/function 정의 수
     - import fan-in/fan-out 근사치
     - package별 파일 수
     - target path와 prompt target 일치도
2. `source_overview` metadata에 다음을 추가한다.
   - `package_roles`: package path별 role hint와 confidence
   - `representative_reads`: package별 대표 파일 목록
   - `coverage`: summarized files / total source files / package count
   - `role_evidence`: role hint를 만든 근거 symbol/import/file-layout snippet
     목록. 사용자 답변에는 전체를 노출하지 않고 fallback summary와 final answer
     prompt 근거로만 사용한다.
3. `inspect_staging`에 coverage gate를 추가한다.
   - directory target + overview truncated + representative reads 미달이면
     `targeted_read`를 한 번 더 허용한다.
   - representative reads는 전체를 읽지 않고 package당 1개, 최대 N개로 제한한다.
   - N 기본값은 4~6개로 시작하고 테스트로 조정한다.
4. `PromptBuilder`는 `inspect_stage.stage == "targeted_read"`일 때
   `representative_reads` 또는 `suggested_reads`를 단계 지시로 제공한다.
   - 모델에게 “무조건 더 읽어라”가 아니라 “finalize 전에 이 후보 중 아직 확인하지
     않은 대표 파일을 우선 확인하라”라고 지시한다.
   - 이미 충분히 확인된 경우 `finalize` stage에서 도구 schema를 닫는다.
5. `last_tool_results()`는 message metadata를 복원된 `ToolResult.metadata`로
   전달한다.
   - 보존 대상은 JSON-serializable metadata 전체다.
   - 특히 `truncated`, `suggested_reads`, `representative_reads`,
     `package_roles`, `coverage`, `observation`은 테스트로 고정한다.
6. `ToolEvidenceRecorder`는 representative read coverage를
   `CompletionEvidence`에 축약 저장한다.
7. final answer request prompt에는 다음 규칙을 넣는다.
   - 확인한 근거와 추론한 역할을 분리한다.
   - overview만으로 확인되지 않은 내용은 단정하지 않는다.
   - truncated이면 “추가로 보면 좋은 대표 파일”을 제안하되 실패처럼 표현하지 않는다.

### 수용 기준

- 큰 directory 분석에서 source overview가 잘렸더라도 대표 파일 여러 개를
  근거로 삼아 package별 역할을 더 균형 있게 설명한다.
- token budget을 넘기지 않으며 full-file dump가 발생하지 않는다.
- 특정 `src/allCode` 이름에 의존하지 않는다.

## Phase 4. Reasoning-only Fallback 답변 품질 개선

### 현재 문제

빈 답변은 방지되었지만 fallback 답변이 내부 사유를 직접 보여주고,
“부분 요약”, “모델이 보이는 최종 답변을 내지 않음” 같은 시스템 설명이
사용자 경험을 떨어뜨린다.

### 수정 대상

- `src/allCode/agent/inspect_summary.py`
- `src/allCode/agent/round_response_handler.py`
- `src/allCode/agent/finalization_helpers.py`
- `src/allCode/agent/prompt_builder.py`
- `tests/unit/agent/test_inspect_summary.py`
- `tests/integration/test_readonly_source_analysis.py`

### 구현 계획

1. `grounded_inspect_summary()`의 사용자-facing template에서 내부 reason code를
   제거한다.
2. 내부 reason은 `TurnResult.error_message`, recovery state, telemetry에만 남긴다.
3. `ROLE_HINTS_EN`, `ROLE_HINTS_KO` static dictionary를 제거한다.
   - 역할은 `source_overview.metadata.package_roles`와
     `role_evidence`에서 가져온다.
   - metadata가 없는 이전 tool result나 실패 케이스에서는 path와 summary만
     근거로 보수적으로 설명한다.
4. fallback 답변은 다음 구조로 만든다.
   - `확인한 범위`
   - `구조 요약`
   - `주요 역할`
   - `추가로 확인하면 좋은 파일`
5. `남은 한계`는 실패 문구가 아니라 근거 범위 설명으로 낮춘다.
   - 예: “전체 파일 본문을 모두 읽지는 않았고, 구조 요약과 대표 파일 기준으로
     정리했습니다.”
6. Markdown table은 터미널에서 폭이 좁을 때 깨질 수 있으므로 fallback 기본은
   bullet list를 사용한다. 모델이 정상 final answer를 낸 경우에는 기존 Markdown
   renderer가 처리한다.

### 수용 기준

- 사용자 화면에 `model_returned_reasoning_only_after_retry`,
  `reasoning_only`, parser status가 보이지 않는다.
- 한국어 prompt에서는 fallback도 한국어다.
- 최종 답변은 실패 보고서처럼 보이지 않고, 근거 기반 분석 답변처럼 보인다.

## Phase 5. Loop/Cost Guard와 관찰성 정리

### 목표

source analysis가 과도한 탐색으로 늘어지지 않으면서도 충분한 근거를 모으게 한다.

### 수정 대상

- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/inspect_staging.py`
- `src/allCode/telemetry/session_analyzer.py`
- `tests/unit/telemetry/test_session_analyzer.py`

### 구현 계획

1. OpenHands stuck detection처럼 inspect route의 최근 action-observation window를
   분석한다.
2. 반복 기준:
   - 같은 directory overview 반복
   - 같은 representative file 반복 read
   - overview truncated인데 representative reads가 증가하지 않는 상태
3. 반복 감지 시:
   - 추가 도구를 닫고 finalization으로 전환한다.
   - fallback summary에 충분한 근거 범위만 반영한다.
4. telemetry metric:
   - `paste_marker_stripped_count`
   - `tool_rows_suppressed_count`
   - `source_analysis_coverage_ratio`
   - `representative_read_count`
   - `fallback_internal_reason_hidden`

### 수용 기준

- 같은 tool/target 반복이 UI와 모델 context를 오염시키지 않는다.
- jsonl 로그와 `session_analyzer`로 보강 효과를 수치 확인할 수 있다.

## Phase 6. 실제 환경 검증

### 자동 테스트

```bash
python -m pytest tests/tty/test_terminal_paste_sequences.py tests/tty/test_terminal_readonly_tool_visibility.py
python -m pytest tests/unit/agent/test_inspect_summary.py tests/unit/agent/test_inspect_tool_staging.py tests/unit/agent/test_finalization_helpers.py
python -m pytest tests/unit/tools/test_source_overview_tool.py tests/unit/telemetry/test_session_analyzer.py
python -m pytest tests/integration/test_readonly_source_analysis.py tests/integration/test_mock_agent_loop.py
python -m pytest tests/tty tests/quality
python -m pytest
```

### 실제 TTY smoke

다음 두 방식으로 확인한다.

```bash
allcode
```

프롬프트:

```text
현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다
```

그리고 bracketed paste 재현을 위해 실제 붙여넣기로 같은 문장을 입력한다.

성공 기준:

- 입력 prompt에 `[200~`, `[201~`가 남지 않는다.
- 화면에는 compact 진행 상태와 최종 답변이 보이고 raw tool 행은 기본 노출되지
  않는다.
- 최종 답변은 한국어다.
- 내부 fallback reason code가 보이지 않는다.
- mutation, shell, approval이 발생하지 않는다.
- session log에는 `source_overview`, representative reads, final answer event가
  추적 가능하게 남는다.

### Headless smoke

```bash
allcode --headless "현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다"
```

성공 기준:

- 한국어 답변 반환.
- 내부 recovery code 미노출.
- 근거 범위와 package 역할이 분리되어 있음.

## 구현 순서

1. Phase 0 테스트를 먼저 추가해 현재 문제를 실패로 고정한다.
2. Phase 1 paste sanitizer와 한국어 IME 입력 경계 처리를 구현하고 TTY 입력
   테스트만 먼저 통과시킨다.
3. Phase 2 tool visibility 정책을 구현하고 TTY transcript 테스트를 통과시킨다.
4. Phase 3 source analysis coverage를 구현하고 unit/integration 테스트를 통과시킨다.
5. Phase 4 fallback summary template를 보강한다.
6. Phase 5 telemetry metric과 loop guard를 정리한다.
7. Phase 6 전체 회귀와 실제 TTY/headless smoke를 실행한다.

각 Phase가 끝날 때 이 문서를 다시 읽고, 금지 사항과 수용 기준을 벗어나지
않았는지 확인한다.

## 남은 리스크

- 실제 터미널마다 bracketed paste sequence 전달 방식이 조금 다르다. raw escape,
  caret notation, marker-only 문자열을 모두 테스트하지만 모든 terminal emulator를
  완전히 대체하지는 못한다.
- 한국어 IME 조합 이벤트는 terminal emulator, OS, shell, tmux 여부에 따라 다르게
  전달될 수 있다. 테스트에서는 UTF-8 multibyte 입력, Hangul wide character,
  backspace/delete/cursor movement를 최소 matrix로 고정하고, 실제 macOS TTY smoke로
  반드시 검수한다.
- tool row를 숨기면 사용자가 “무엇을 했는지” 덜 볼 수 있다. 대신 status와
  session log를 유지하고, 필요 시 후속 debug mode를 별도 옵션으로 설계한다.
- representative read 수를 늘리면 답변 품질은 좋아지지만 token 비용이 증가한다.
  package당 1개, 전체 최대 N개 제한을 반드시 유지한다.
- 모델이 계속 reasoning-only를 반환하면 fallback 품질은 개선되지만, 모델의
  native final answer 품질 자체는 adapter/model 특성의 영향을 받는다.
- source overview의 role hint는 일반화된 package/file/symbol 신호로만 만든다.
  특정 테스트 경로나 특정 프로젝트 구조에 맞춘 하드코딩은 계속 금지한다.
- 500줄 제한을 지키기 위해 모듈 분리가 늘어날 수 있다. 분리는 줄 수만 맞추기
  위한 기계적 분리가 아니라 input, render, evidence, summary, telemetry 같은
  책임 경계를 기준으로 진행한다.
