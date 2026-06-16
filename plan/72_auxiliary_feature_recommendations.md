# 72. allCode 부가기능 추천 — 타 에이전트 조사 기반

> Claude Code · Codex CLI · aider · Cursor · Cline · Gemini CLI · opencode · OpenHands를
> 조사해, 핵심 편집 루프를 넘어선 "부가기능(QoL·생태계)"을 정리했다.
> allCode가 **이미 가진 기능은 제외**하고, 빈틈만 가치/노력으로 우선순위화했다.

---

## 0. allCode 현재 보유(기준선, 제외 대상)

생성 워크플로+검증/수리(고유), 세션 재개(`--continue`/`--resume`+종료 안내), 플랜 승인,
권한 allow/deny 규칙, 백그라운드 셸(job/output/kill), 체크포인트·`/rewind`, `/compact`,
`/cost`, MCP(stdio+HTTP/SSE+resources+prompts), 모델 티어링, lint/typecheck 검증,
`@file`·`@file::symbol` 멘션, AST 편집(`replace_symbol`/`apply_edits`), 병렬 read 도구,
쓰기 가능 서브에이전트(`delegate_task`)·읽기전용(`task`), 턴 중간 개입, 헤드리스
text/json/stream-json+`--image`, hooks(HookRunner), custom commands(`$ARGUMENTS`),
AGENTS.md 메모리, repo_map(`memory/repo_map.py`), 텔레메트리(`/status`·`/debug`),
`/review`(git diff), `/undo`(git), `/model` 편집·`/approval`.

---

## 1. Tier 1 — 적은 노력·큰 체감 (우선 추천)

| 기능 | 설명 | 보유 에이전트 | allCode 현황 | 노력 |
|---|---|---|---|---|
| **`/init`** | 코드베이스를 분석해 `AGENTS.md` 초안(빌드·테스트 명령, 구조, 컨벤션)을 자동 생성 | Codex·Gemini·opencode | 없음(AGENTS.md 읽기만) | 소 |
| **완료 알림** | 긴 턴 종료 시 터미널 벨/OS 알림 — 백그라운드로 돌릴 때 유용 | Codex·Cline | 없음 | 소 |
| **`/export`** | 현재 대화 트랜스크립트를 파일/클립보드로 저장 | Claude Code | 없음(JSONL만 존재) | 소 |
| **`/context`** | 컨텍스트 윈도 점유 내역(메모리/도구스키마/대화) 표시 | Claude Code | 부분(`/cost`는 토큰 총량만) | 소 |
| **`/theme`** | 다크/라이트/색약 테마 런타임 전환 | Codex·Gemini·opencode | 부분(`TerminalTheme` 존재, 전환 명령 없음) | 소 |
| **`/doctor`** | 설정·권한·엔드포인트 점검 진단 | Claude Code | 부분(`--diagnose` 있음, 슬래시 없음) | 소 |
| **커스텀 커맨드 인자 확장** | 템플릿에 `!{shell}`·`@{file}` 주입(현재 `$ARGUMENTS`만) | Gemini·opencode | 부분 | 소 |

## 2. Tier 2 — 역량 확장 (중간 노력)

| 기능 | 설명 | 보유 에이전트 | allCode 현황 | 노력 |
|---|---|---|---|---|
| **에이전트 정의 파일 + `/agents`** | `.allCode/agents/<name>.md`(역할·도구·모델)로 전문 서브에이전트 정의·관리 | Claude Code·Codex·Gemini | 없음(`task`/`delegate_task` 코드 내장만) | 중 |
| **진행 체크리스트(todo)** | 모델이 작성하는 작업 목록을 UI에 지속 표시(Focus Chain/update_plan) | Cline·Codex·Gemini | 내부 `task_plan`만, 사용자 노출 없음 | 중 |
| **PR 생성 + AI 커밋 메시지** | `gh pr create`로 PR 작성, 변경마다 Conventional-Commit 메시지 자동 생성 | aider·Cursor·Codex | 부분(auto_commit 기본 off, AI 메시지 없음) | 중 |
| **세션 이름·포크** | `-n`/`/rename`로 명명, `/branch`·`--fork`로 분기 후 다른 접근 시도 | Claude Code·Codex·opencode | 없음(resume만) | 중 |
| **TUI 이미지 붙여넣기** | 터미널에서 스크린샷/목업 붙여넣기(Ctrl+V) | Cursor·Cline·Gemini | 부분(헤드리스 `--image`만) | 중 |
| **워크트리 격리 서브에이전트** | 병렬 쓰기 작업을 별도 git worktree에서 수행해 충돌 방지 | Claude Code·Cursor·Codex | 부분(`delegate_task`는 동일 워크스페이스) | 중 |
| **자동 포맷 훅(PostToolUse)** | 편집 후 ruff/prettier 자동 정렬 | Claude Code·aider·opencode | 부분(HookRunner로 가능, 기본 미설정) | 소~중 |

## 3. Tier 3 — 큰 노력·장기 (선택)

| 기능 | 설명 | 보유 에이전트 | 비고 |
|---|---|---|---|
| **LSP 통합** | 정밀 "정의로 이동/참조 찾기" + 진단 피드로 검색 대신 심볼 기반 분석 | opencode·Claude Code | 설정 플래그(`lsp_enabled`)만, 미구현. 고노력·고가치 |
| **Skills(자동 호출 능력)** | 상황에 맞게 자동 로드되는 재사용 지침/워크플로 | Claude Code·Codex·OpenHands | 현재 custom commands(수동 호출)만 |
| **파일 워치 / 인라인 AI 코멘트** | 에디터에서 `AI!`/`AI?` 주석 감지해 자동 작업 | aider(고유) | watch 루프 필요 |
| **GitHub Action / `@멘션` 트리거** | CI에서 헤드리스 실행, 이슈/PR 코멘트로 작업 트리거 | 전부 | infra·플랫폼 연동 |
| **OS 샌드박스 강화** | Seatbelt/Bubblewrap 격리 실행(현재 shell_sandbox 부분) | Codex·Gemini·Cursor | 부분 보강 |
| **브라우저 자동화 / 음성 입력 / IDE 확장 / 클라우드·스케줄 작업** | 시각 테스트·음성·VS Code 연동·예약 실행 | 각 일부 | 범위 큼, 후순위 |

---

## 3-b. 추가 요청 — 슬래시 추천 화살표 탐색 (Tier 1)

- **기능**: 슬래시 명령 추천 오버레이가 떠 있을 때 **↑/↓ 화살표**로 후보를 위아래로 이동(wrap-around) 후 Tab/Enter로 선택. 현재는 Tab 순환만 가능.
- **현황**: `tui/terminal_completion.py`의 `CompletionState`는 `current()`/순환 인덱스를 갖고, `tui/terminal_input.py`가 Tab으로 사이클. 화살표 키는 오버레이가 떠 있어도 후보 탐색에 연결돼 있지 않음.
- **구현 방향**: 입력 에디터의 키 처리에서 완성 오버레이 활성 상태일 때 `up`/`down` 키를 `CompletionState`의 이전/다음 후보 이동으로 라우팅(오버레이 비활성 시에는 기존 히스토리/커서 이동 동작 유지). `CompletionState.move(delta)` 또는 `previous()`/`next()` 추가.
- **검증**: 단위 테스트로 ↑/↓가 선택 인덱스를 wrap하며 이동하고, 오버레이 비활성 시 화살표가 기존 동작을 유지하는지 확인.

- **A. 온보딩·진단 묶음**: `/init` + `/doctor` + `/context` — 신규 사용자 체감 즉시 향상, 노력 소.
- **B. 세션 QoL 묶음**: `/export` + 세션 이름/포크 + 완료 알림 — 장시간 작업 흐름 보완.
- **C. 확장성 묶음**: 에이전트 정의 파일(`.allCode/agents/`) + 커스텀 커맨드 인자 확장 — 생태계/재사용성.
- **D. 협업 묶음**: PR 생성 + AI 커밋 메시지 + 진행 체크리스트 — 실제 개발 파이프라인 통합.

## 5. 교차 관찰(조사 요약)

- `AGENTS.md`·MCP 클라이언트·shadow-git 체크포인트·hooks·서브에이전트·plan/act 모드·구조화 헤드리스 출력은 이제 **사실상 표준**(1년 전엔 차별점). allCode는 대부분 보유.
- **git 철학 두 갈래**: aider는 실제 repo에 자동 커밋, Cursor/Cline/Gemini는 shadow-git 체크포인트로 `.git` 미오염. allCode는 후자(체크포인트)+선택적 auto_commit으로 양쪽 절충.
- **달러 비용 미터**는 드묾(aider·Cline만). allCode는 토큰 미터(`/cost`)에 달러 추정만 더하면 동급.
- **MCP 서버(에이전트를 서버로 노출)**는 희귀(Codex만 확인). 후순위.

> (최초 작성 시) 본 문서는 추천 정리였다. 아래 6절은 이후 실제 구현 현황이다.

---

## 6. 구현 현황 (이 플랜 기준)

### ✅ 구현 완료 (테스트 포함, 커밋·푸시)

| 항목 | 명령/모듈 |
|---|---|
| `/init` | `workspace/project_init.py` — AGENTS.md 초안 자동 생성(있으면 `/init force`) |
| `/doctor` | 설정·API 키·base_url·AGENTS.md·config 점검 |
| `/export [경로]` | 트랜스크립트 마크다운 저장(`ConversationStore`) |
| `/context` | 컨텍스트 토큰 사용량 표시 |
| `/theme dark\|light` | 런타임 테마 전환(`TerminalTheme.named`) |
| 완료 알림 | 10초 초과 턴 종료 시 터미널 벨 |
| 커스텀 커맨드 인자 확장 | `@{file}`·`!{shell}` 주입(`custom_commands.expand_command`) |
| `/agents` + 정의 파일 | `workspace/agent_definitions.py`(`.allCode/agents/*.md`) |
| `/pr` + 스마트 커밋 메시지 | `git_ops.create_pull_request`·`derive_commit_message`(자동 커밋도 사용) |
| 세션 이름/포크 | `--name`/`--resume <name>`/`--fork`(`ConversationStore.set_name/resolve/fork`) |
| 진행 체크리스트(todo) | 플랜 프리뷰에 "작업 단계" 체크리스트 추가 |
| GH Action / 포맷 훅 / 템플릿 | `examples/`(github-action.yml, auto-format-hook.yaml, agent-and-command-templates.md) |

### ⏳ 의도적으로 보류 (사유 명시)

| 항목 | 보류 사유 |
|---|---|
| TUI 이미지 붙여넣기 | 헤드리스 `--image`는 이미 지원. TUI 전송은 turn_runner 시그니처(이미지 인자) 변경 + 터미널 bracketed-paste 이미지 처리가 필요해 위험/노력 대비 효용 낮음. |
| 워크트리 격리 서브에이전트 | `delegate_task`는 이미 쓰기 가능. 별도 worktree는 변경분 머지백 단계가 추가돼 복잡·오류 위험이 큼(현 체크포인트로 롤백은 가능). |
| LSP 통합 | 언어서버 수명관리·진단 피드 연동은 대형 작업. 별도 plan 필요. |
| 자동 호출 Skills | 현재 수동 호출 custom commands로 대체. 자동 로딩은 에이전트 루프 변경 필요. |
| 파일 워치 / 인라인 AI 코멘트 | `--watch` 루프 모드 필요(별도 작업). |
| 브라우저 자동화 / 음성 / IDE 확장 / 클라우드·스케줄 | repo 내 파이썬 변경 범위를 벗어나는 외부/인프라 작업. |

요약: plan/72 Tier1 전부 + Tier2 대부분(에이전트 정의·PR·세션 이름/포크·todo)을 테스트와 함께 구현했고, in-repo로 가능한 Tier3(예시 워크플로/훅/템플릿)를 추가했다. 외부 인프라·대형 작업 항목은 사유와 함께 보류로 명시했다. 전체 테스트 938 passed, 3 skipped.

### ✅ 실제 환경 검증 완료 (2026-06-16)

실제 `allcode` 바이너리 + 라이브 vLLM 엔드포인트 + 실제 git 저장소에서 전 기능을 구동 검증했다.

| 기능 | 실측 |
|---|---|
| `/doctor` | API 키/AGENTS.md/모델 점검 출력 확인 |
| `/init` (생성/거부/force) | AGENTS.md 실제 작성(Python·pytest 감지) |
| `/theme light` / `/context` | 전환 메시지 / 컨텍스트 안내 출력 |
| `/agents` | frontmatter(description/model/tools) 파싱·목록 |
| 커스텀 커맨드 `@{}`/`!{}` | `STAT-OK`(셸)+파일내용+`$ARGUMENTS`가 실제 모델 프롬프트에 주입되어 응답 |
| `/export` | 트랜스크립트 파일 작성 확인 |
| `--name`/`--resume <이름>` | 이름→id 매핑(`_names.json`), 대화 복원 |
| `--fork` | 복제 세션 진행 + 복제 jsonl 생성 |
| `derive_commit_message` / `/pr` | `docs: update README.md` / 기본 브랜치 PR 거부 |

검증 중 `allcode --fork`의 런타임 `NameError`(ConversationStore 미임포트)를 발견·수정하고
회귀 테스트(`tests/unit/test_fork_session.py`)를 추가했다(커밋 `fda7b93`). 재검증 후 전 항목 정상.
