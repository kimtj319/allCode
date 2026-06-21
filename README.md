# allcode

allCode는 가벼운 all-rounder CLI coding agent입니다. 에이전트형 코딩
도우미의 핵심 구조는 유지하되, 거대한 단일 파일 구조를 피하기 위해
provider-neutral model event, core contract, routing/policy, tool execution,
workspace context, memory, generation workflow, TUI/headless entrypoint를
각각 별도 패키지로 나누어 구현합니다.

현재 MVP는 로컬 개발과 테스트 가능한 agent 동작을 목표로 합니다.
headless와 TUI 실행 경로는 설정된 OpenAI-compatible 모델로 바로 통신하고,
unit/integration test는 명시적으로 주입한 fake LLM 또는 mock transport를
사용합니다.

## 주요 기능

- routing, recovery, tool loop detection, final answer gate를 갖춘
  all-rounder agent loop.
- provider-neutral LLM protocol과 OpenAI-compatible chat completions adapter.
- 단일 `ConfigManager` 진입점을 통한 config/env 기반 설정.
- `allcode --headless` 기반 headless 실행. headless도 runtime builtin tool
  registry와 route policy를 사용합니다.
- 기본 `allcode` 실행 시 Codex-style terminal-native UI를 사용합니다.
  일반 터미널 scrollback 위에 답변을 출력하고, 하단 composer만 고정합니다.
- 선택 실행 가능한 Textual UI: `allcode --textual`.
- Markdown answer rendering, status/spinner, input recovery, slash command
  registry, history/completion, paste placeholder, folded tool output renderer.
- registry, executor, approval check, core 표준 `ToolCall`/`ToolResult`,
  edit transaction을 사용하는 tool calling contract.
- route 기반 tool 노출. 일반 답변에는 tool schema를 숨기고, inspect,
  modify, operate, external answer route에 필요한 tool만 모델에 전달합니다.
- 내장 file, search, shell/validation, evidence-only web tool.
- **온디맨드 스킬**: `.allCode/skills`에 정의한 작업 지침을 모델이 필요할 때
  `skill` tool로 로드 (Claude Code 방식 progressive disclosure). → [스킬](#스킬-allcodeskills)
- **MCP 서버 관리**: `/mcp` 슬래시 명령과 `allcode mcp` CLI로 config 직접 수정
  없이 MCP 서버를 추가/조회/삭제. → [MCP 서버 관리](#mcp-서버-관리)
- **세션 이어가기**: `/resume`으로 이전 세션 목록 확인 및 현재 세션으로 대화
  맥락 로드. → [슬래시 명령어](#슬래시-명령어)
- workspace root, safe path resolution, indexing, symbol extraction.
- hierarchical `ALLCODE.md` style memory, session summary, recent target,
  repo map, context compaction, auto-memory inbox, redaction.
- skeleton-first project generation workflow와 validation/self-repair.
- functional success, tool use, context continuity, self-healing,
  final answer grounding, UI signal clarity, safety를 점수화하는 quality test.

## 설치

allCode는 Python 3.11 이상이 필요합니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

개발과 테스트에 필요한 optional dev dependency는 `pyproject.toml` 기준으로
설치합니다.

```bash
python -m pip install -e ".[dev]"
```

`requirements.txt`는 `requirements.txt` 기반 설치를 기대하는 환경을 위한
호환 설치 파일입니다. 패키지 정의의 기준은 `pyproject.toml`입니다.

```bash
python -m pip install -r requirements.txt
```

## 모델 설정

설정은 아래 우선순위로 병합됩니다.

1. CLI flag
2. Environment variable
3. Project config: `<workspace>/.allCode/config.yaml`
4. User config: `~/.config/allCode/config.yaml`
5. Built-in defaults

지원하는 환경 변수:

- `ALLCODE_CONFIG`: user config 파일 경로.
- `ALLCODE_MODEL`: 모델명.
- `ALLCODE_BASE_URL`: OpenAI-compatible API base URL.
- `ALLCODE_API_KEY`: API key 값. 이 값이 있으면 allCode는
  `ALLCODE_API_KEY`라는 환경 변수명을 key source로 사용합니다.
- `ALLCODE_API_KEY_ENV`: API key를 담고 있는 다른 환경 변수명.
- `ALLCODE_WORKSPACE`: workspace root.
- `ALLCODE_APPROVAL_MODE`: `ask`, `auto`, `rules`.
- `ALLCODE_WEB_SEARCH_BACKEND`: `duckduckgo_html`, `searxng`, `http_json`,
  `disabled`. 기본값은 별도 토큰이 필요 없는 `duckduckgo_html`입니다.
- `ALLCODE_WEB_SEARCH_URL`: web search endpoint. `duckduckgo_html` 기본값은
  `https://html.duckduckgo.com/html/`입니다.
- `ALLCODE_WEB_SEARCH_API_KEY_ENV`: web search endpoint token을 담은 환경 변수명.
- `ALLCODE_WEB_SEARCH_TIMEOUT`: web search timeout seconds.
- `ALLCODE_WEB_SEARCH_LANGUAGE`: SearXNG backend에서 사용할 기본 언어.

config 파일에는 API key 값을 저장하지 않고, API key가 들어 있는 환경 변수명만
저장합니다.
프로젝트 루트의 `.env` 파일도 자동으로 읽습니다. 이때 `ALLCODE_`로 시작하는
변수만 반영하며, 이미 셸에 설정된 환경 변수는 `.env` 값으로 덮어쓰지 않습니다.
따라서 repository root에서 실행할 때는 `.env`에 `ALLCODE_API_KEY=...`를
두는 것만으로 충분합니다. `source .env`를 쓸 경우에도 `export` 없이 정의한
변수는 셸 하위 프로세스에 전달되지 않을 수 있으므로, allCode의 자동 `.env`
loader를 기준으로 생각하는 편이 안전합니다.

```yaml
model:
  model_name: gpt-4o-mini
  base_url: https://api.openai.com/v1
  api_key_env: ALLCODE_API_KEY
  timeout_seconds: 120
  max_output_tokens: 8192
  context_window_tokens: 0   # 모델 컨텍스트 윈도(토큰). >0이면 대화가 윈도에 맞게 자동 압축
workspace:
  root: .
  extra_roots: []
  sandbox_enabled: true
approval:
  mode: ask
  session_allow: []
agent:
  # 코드 분석 커버리지/깊이 예산. 값이 클수록 한 번의 분석에서 더 많은 파일을
  # 살펴보지만 지연/토큰 사용이 늘어납니다. 아래는 기본값입니다.
  max_rounds: 40              # 턴당 모델↔도구 라운드 수
  inspect_action_budget: 24  # 검사(read/probe/search) 액션 수
  inspect_round_budget: 24   # 검사 라운드 수
  context_token_budget: 24000  # 답변까지 유지되는 컨텍스트 번들 예산
  max_active_file_bytes: 131072  # 컨텍스트에 싣는 파일당 바이트(128KB)
  system_prompt_append: ""    # 출력 스타일/페르소나 등 시스템 프롬프트에 덧붙일 사용자 지침
```

`model.context_window_tokens`를 실제 모델 윈도(예: 32768)로 설정하면, 긴
세션에서 대화가 윈도에 맞게 자동 압축되어 오버플로를 막고(작은 윈도) 더 많은
근거를 보존합니다(큰 윈도). `agent.system_prompt_append`에 어조·형식·상시 지침을
적으면 매 턴에 적용됩니다(캐시 친화적 정적 영역에 배치).

전체 코드베이스 분석의 커버리지가 부족하면 위 `agent` 예산을 더 키우고, 지연이
부담되면 줄이세요. 모델 컨텍스트 윈도가 작다면 `context_token_budget`을 낮춥니다.

대형 코드 분석의 구조 커버리지는 `source_overview`가 한 번에 요약하는 파일 수
(`max_files`, 기본 600·최대 2000)로 결정됩니다 — 커버리지 ≈ `요약 파일 수 /
전체 소스 파일 수`. 기본값에서 수백~수천 파일 규모 저장소도 대부분 한 번의
개요로 커버합니다(요약은 시그니처 위주라 토큰 비용이 작습니다). 더 큰 저장소는
프롬프트에서 `max_files`를 직접 올려 호출할 수 있습니다.

OpenAI-compatible endpoint 예시:

```bash
export ALLCODE_API_KEY="sk-..."
allcode --model gpt-4o-mini --base-url https://api.openai.com/v1 --headless "Explain this repo"
```

로컬 OpenAI-compatible endpoint 예시:

```bash
export ALLCODE_API_KEY="local-token"
allcode --model local-model --base-url http://127.0.0.1:8000/v1 --headless "Summarize src/allCode"
```

Wisenut Wise LLOA endpoint 예시:

```bash
export ALLCODE_API_KEY="<API token>"
allcode --model wisenut/wise-lloa-max-v1.2.1 --base-url http://210.180.82.135:9023/v1 --headless "간단히 자기소개해줘."
```

주의: API token은 README나 config 파일에 저장하지 마세요. `ALLCODE_BASE_URL`
또는 config의 `model.base_url`을 지정하면 CLI/headless/TUI 실행 경로는
`OpenAICompatibleClient`로 실제 모델에 요청합니다. `base_url`을 생략하면
OpenAI 기본 API root인 `https://api.openai.com/v1`을 사용합니다.

## 실행 방법

`pip install -e .` 이후 console script를 사용할 수 있습니다.

```bash
allcode --help
allcode --headless "Hello from allCode"
echo "Explain the current workspace" | allcode --headless
allcode --workspace /path/to/project --headless "Inspect src"
allcode --config /path/to/config.yaml --headless "Use this config"
allcode --approval auto --headless "Create a small Python project named demo_app with tests"
```

설치하지 않고 repository root에서 실행할 수도 있습니다.

```bash
PYTHONPATH=src python -m allCode --help
PYTHONPATH=src python -m allCode --headless "Hello"
```

TUI shell:

```bash
allcode
allcode --textual
allcode --plain-terminal
```

기본 `allcode`는 Textual fullscreen 앱이 아니라 terminal-native UI를
실행합니다. 본문 출력은 일반 터미널 scrollback을 사용하고, 하단 composer만
고정해 입력, history, completion, paste placeholder, runtime status/spinner를
표시합니다. Enter/LF는 제출이고, multiline 입력은 Alt+Enter를 사용합니다.

`allcode --textual`은 선택형 Textual UI입니다. Textual이 설치되지 않았으면
terminal-native UI로 fallback합니다. `--plain-terminal`은 기본
terminal-native UI를 명시하는 compatibility alias입니다.

## 슬래시 명령어

TUI에서 `/`로 시작하는 명령으로 세션을 제어합니다. 입력 중 `/`를 누르면 팔레트
자동완성이 뜨고, 인자를 받는 명령은 선택 가능한 옵션을 함께 제안합니다.

| 명령어 | 설명 |
| --- | --- |
| `/help`, `/commands` | 전체 슬래시 명령 목록 표시 |
| `/model [<name>\|impl <name>\|base <url>]` | 모델·구현 모델·base URL 조회/변경 (config.yaml 저장) |
| `/approval [auto\|ask]` | 승인 모드 조회/설정 |
| `/permissions [allow\|deny <rule>]` | 허용/거부 권한 규칙 조회/저장 |
| `/thinking [on\|off]` | 모델 reasoning 채널 표시 토글 |
| `/tools` | 사용 가능한 tool 목록 |
| `/mcp [list\|add <name> <cmd...>\|remove <name>]` | MCP 서버 추가/조회/삭제 (config.yaml, 다음 실행부터 적용) |
| `/skills` | 모델이 로드할 수 있는 스킬 목록 (`.allCode/skills`) |
| `/agents` | 정의된 서브에이전트 목록 (`.allCode/agents`) |
| `/resume [<id\|name>]` | 최근 세션 목록, 또는 이전 세션 대화를 현재 세션으로 로드 |
| `/memory show\|add <text>\|refresh` | 활성 메모리 조회/추가/리로드 |
| `/compact` | 대화 컨텍스트 요약·압축 |
| `/cost` | 이번 세션의 토큰·컨텍스트 사용량 |
| `/status [last]` | 사용량 게이지·세션 상태 (`last`는 진단 정보) |
| `/config` | 활성 런타임 설정 표시 |
| `/init [force]` | 프로젝트에서 `AGENTS.md` 초안 생성 |
| `/doctor` | 설정·API 키·환경 진단 |
| `/review`, `/diff` | 커밋되지 않은 변경 (git diff) |
| `/undo` | allCode의 마지막 git 자동 커밋 되돌리기 (히스토리 레벨) |
| `/rewind` | 마지막 턴 체크포인트로 파일 복원 (워킹트리 레벨, 미커밋 변경도 되돌림) |
| `/export [path]` | 대화 transcript를 파일로 저장 |
| `/pr [title]` | 커밋·푸시 후 GitHub PR 생성 (`gh`) |
| `/theme [dark\|light]` | 색상 테마 전환 |
| `/clear` | 화면(transcript) 정리 |
| `/stop` | 진행 중인 턴 취소 |
| `/exit` | allCode 종료 |

> `/undo`와 `/rewind`의 차이: `/undo`는 git 히스토리에서 마지막 자동 커밋을
> 되돌리고, `/rewind`는 마지막 턴 시작 시점의 파일 스냅샷(체크포인트)으로 워킹
> 트리를 복원합니다(커밋되지 않은 편집도 되돌림).

`.allCode/commands/*.md`에 정의한 커스텀 명령도 같은 팔레트에 등록되어 슬래시로
실행할 수 있습니다.

## 스킬 (.allCode/skills)

스킬은 자주 쓰는 작업 절차를 모델이 필요할 때만 불러오는 재사용 지침입니다.
이름과 한 줄 설명은 항상 모델에 노출되고, 본문 지침은 모델이 `skill(<name>)`을
호출할 때 로드됩니다(progressive disclosure). 토큰을 아끼면서도 관련 작업에서만
상세 지침이 컨텍스트에 들어옵니다.

두 가지 형식을 지원합니다.

```
.allCode/skills/<name>/SKILL.md   # 디렉터리 형식 (보조 파일 동봉 가능)
.allCode/skills/<name>.md         # 단일 파일 형식
```

각 파일은 frontmatter의 `description`과 본문 지침으로 구성합니다.

```markdown
---
description: 코드 리뷰 체크리스트
---
1. 경계 조건과 입력 검증을 확인한다.
2. 에러 처리와 로깅을 확인한다.
3. 변경에 대응하는 테스트가 있는지 확인한다.
```

스킬이 하나라도 있으면 `skill` tool이 자동 등록되고, `/skills`로 목록을 확인할 수
있습니다. 관련 작업 시 모델이 알맞은 스킬을 먼저 로드하도록 통합 프롬프트가
안내합니다.

바로 쓸 수 있는 예시 스킬을 [`examples/skills/`](examples/skills/)에 제공합니다
(code-review, commit-message, pr-description, debug, test-author,
security-review). `cp examples/skills/*.md .allCode/skills/`로 설치하세요.

## MCP 서버 관리

[Model Context Protocol](https://modelcontextprotocol.io) 서버를 config 파일을
직접 편집하지 않고 추가/조회/삭제할 수 있습니다. 변경은 `.allCode/config.yaml`의
`mcp.servers`에 저장되며 다음 실행부터 적용됩니다.

TUI 슬래시 명령:

```
/mcp                                  # 등록된 서버와 이번 세션 활성 MCP tool 수
/mcp add fs npx -y server-filesystem  # stdio 서버 추가
/mcp add remote --http https://example.com/mcp   # http 서버 추가
/mcp remove fs                        # 서버 삭제
```

CLI(헤드리스/스크립트):

```bash
allcode mcp list
allcode mcp add fs npx -y server-filesystem
allcode mcp add remote --http https://example.com/mcp
allcode mcp remove fs
```

stdio 전송은 `command`가, http/sse 전송은 `url`이 필요하며 저장 전에 검증됩니다.

자주 쓰는 서버(filesystem, git, fetch, context7, playwright, github 등)의 추가
명령은 [`examples/mcp-servers.md`](examples/mcp-servers.md) 카탈로그를 참고하세요.

## 프로젝트 구조

- `src/allCode/core`: strict Pydantic core model, event, event bus,
  result evidence, error, shared path pattern.
- `src/allCode/llm`: provider-neutral client protocol, fake LLM scenario,
  response parser, model settings, OpenAI-compatible adapter.
- `src/allCode/agent`: intent extraction, routing, policy, prompt building,
  agent loop, recovery, context builder, completion checker, validation runner,
  final reporter, generation workflow orchestration.
- `src/allCode/tools`: tool contract, registry, executor, approval logic,
  edit transaction, 내장 file/search/shell/web tool.
- `src/allCode/workspace`: workspace root, safe path resolution, indexing,
  symbol extraction, agent definition/skill 로더.
- `src/allCode/memory`: hierarchical memory, store, session store/summary,
  recent target, repo map/ranker, selector, compactor, auto-memory inbox,
  `/memory` command backend.
- `src/allCode/tui`: default terminal-native UI, optional Textual app,
  terminal composer/keymap/history/completion/paste handling, Markdown
  normalization/rendering, transcript state/reducer/view, command registry,
  approval panel state, event renderer, UI message model.
- `src/allCode/config`: config schema, defaults, precedence-aware loader,
  MCP 서버 관리(`mcp_admin`).
- `src/allCode/generation`: language strategy registry와 Python, Node, Go,
  Rust, Java, generic project strategy.
- `tests`: unit, integration, quality, TTY smoke, helper scenario.
- `docs`: backlog과 post-MVP future work note.
- `plan`: MVP 구현 계약. `plan/00`부터 `plan/12`까지가 authoritative
  contract이고, `plan/13`, `plan/14`는 review appendix입니다.

## 테스트

집중 테스트:

```bash
python -m pytest tests/unit
python -m pytest tests/integration
python -m pytest tests/quality
python -m pytest tests/tty
```

전체 테스트:

```bash
python -m pytest
```

유용한 범위별 명령:

```bash
python -m pytest tests/unit/config tests/unit/test_entrypoint.py
python -m pytest tests/unit/core
python -m pytest tests/unit/llm
python -m pytest tests/unit/agent tests/unit/tools
python -m pytest tests/unit/tools tests/unit/agent/test_policy.py tests/integration/test_mock_agent_loop.py tests/integration/test_agent_loop_context_validation.py
python -m pytest tests/unit/workspace tests/unit/agent/test_context_builder.py
python -m pytest tests/unit/memory tests/integration/test_followup_context_memory.py
python -m pytest tests/integration/test_generation_workflow.py
python -m pytest tests/integration/test_mock_agent_loop.py tests/integration/test_headless_runner.py
python -m pytest tests/tty
```

문서 작성 시점의 마지막 로컬 검증:

- `python -m pytest tests/unit tests/integration tests/quality tests/tty`
- `python -m pytest`
- `allcode --help`
- `PYTHONPATH=src python -m allCode --help`
- `PYTHONPATH=src python -m allCode --headless "Hello from docs quickstart"`

## 개발 원칙

- 한 파일에 과도한 책임을 몰지 않습니다.
- `core`는 provider SDK, Textual, Rich, 구체 UI 구현에 독립적이어야 합니다.
- 계층 간 데이터는 표준 core `ToolCall`, `ToolResult`, `AgentEvent`,
  `TurnResult` 모델을 사용합니다.
- 모델에 전달하는 tool schema는 route policy로 제한합니다. direct answer
  route에는 tool을 노출하지 않고, external answer route에는 web evidence
  tool만 노출합니다.
- 실제 `CompletionEvidence` 없이 구현/수정 완료를 보고하지 않습니다.
- 파일 변경은 tool execution과 edit transaction evidence를 거쳐야 합니다.
- config 파일에는 secret을 저장하지 않고 환경 변수명만 저장합니다.
- memory 저장 전 secret/API key/token 유사 값은 redaction합니다.
- provider SDK 또는 HTTP 세부사항은 `llm/adapters` 아래에 두어
  provider-neutral adapter 구조를 유지합니다.

## Current Limitations

- CLI/headless/TUI 기본 실행 경로는 실제 OpenAI-compatible adapter를
  사용합니다. 개발/테스트에서 fake LLM이 필요하면 test helper나
  `run_headless_sync(..., llm_client=FakeLLMClient...)`처럼 명시적으로
  주입해야 합니다.
- headless, terminal-native UI, Textual UI 모두 runtime builtin tool registry를
  사용합니다. 단, route policy가 모델에 노출되는 tool schema를 제한합니다.
- terminal-native UI는 Codex-style scroll-region/composer 구조와 Markdown
  rendering을 제공합니다. Codex와 완전히 동일한 editor 기능이나 diff review
  UX는 아직 구현 범위 밖입니다.
- Textual UI는 선택형 fallback UI입니다. 기본 UX 기준은 terminal-native UI입니다.
- web search는 기본적으로 `duckduckgo_html` backend가 활성화되어 live search를
  시도합니다. `searxng` 또는 `http_json` backend로 교체할 수 있고, 명시적으로
  `disabled`를 설정하면 검색을 끌 수 있습니다. 네트워크 차단 환경이나 검색
  결과 파싱 실패 시에는 raw HTML을 출력하지 않고 unavailable/error evidence로
  처리합니다.
- `web_fetch`는 backend가 `disabled`가 아닐 때 실제 URL fetch를 시도하며, HTML은
  script/style/markup을 제거한 evidence bundle로 정규화합니다.
- 기본 `approval.mode=ask`에서는 file mutation과 일반 shell command가
  approval_required 결과로 중단됩니다. 자동 코딩/검증 smoke에는
  `--approval auto` 또는 session allow rule이 필요할 수 있습니다.
- 실제 모델 통합 테스트는 선택 사항이며 기본 test suite에 포함되지 않습니다.
  unit test는 mock transport와 fake LLM scenario를 사용합니다.
- non-headless 실제 PTY smoke는 실행 환경에 의존합니다. 자동 TTY smoke test는
  terminal-native/Textual state와 rendering contract를 검증합니다.
- plugin marketplace, multi-agent swarm, cloud sandbox, PageRank-style repo
  ranking, full interactive diff editor는 `docs/future_work.md`에 post-MVP
  항목으로 기록되어 있습니다. (git auto-commit, MCP server manager, on-demand
  skill 시스템은 구현되어 본 문서에 반영되었습니다.)

## 변경 내역

최근 업데이트(refactor/unified-agent-loop 브랜치 기준):

- **하네스 기능 보강 (다른 코딩 에이전트 대비 격차 해소)**:
  - *모델 윈도 인지 자동 압축* — `model.context_window_tokens` 기반으로 대화를
    윈도에 맞게 자동 압축(출력+보존 프리픽스 제외, 85% 안전·6K 하한). 0이면
    레거시 고정 예산.
  - *프롬프트 캐시 친화 정렬* — 정적 가이드를 시스템 메시지 선두로, 턴별 변동을
    뒤로 → vLLM 자동 prefix 캐시 적중률↑.
  - *헤드리스 JSON 출력* — `--output-format text|json|stream-json` (CI/스크립트용).
  - *서브에이전트 병렬 fan-out* — 독립 read-only `task`를 한 응답에 emit하면
    동시 실행(동시성 상한 8).
  - *OS 데스크톱 알림* — 긴 턴 종료 시 OSC 9 알림(+벨); 더 풍부한 알림은 `stop` 훅.
  - *출력 스타일 커스터마이즈* — `agent.system_prompt_append`로 어조/페르소나/상시 지침.
- **코드 분석 커버리지 확대 (대형 코드베이스 최대 적용)** — 한 번의 프로젝트
  분석에서 살펴보는 파일 수를 크게 늘렸습니다. `source_overview`가 한 번에
  요약하는 파일 수를 기본 600(최대 2000)으로 올려, 수백~수천 파일 저장소도
  기본값으로 구조의 대부분(예: allCode 자체 294파일 중 245파일=83%, 나머지는
  `__init__` 등 사소 파일)을 한 번에 커버합니다. 함께 라운드 한계(12→40),
  검사 예산(7/6→24/24, 유효 캡 9→64), 컨텍스트 번들 예산(4K→24K 토큰),
  대표 읽기(8/12/16→32/48/64), read_file 기본 바이트(12K→32K), source_probe
  범위(4→6, 캡 8→16)를 상향했고, 통합 프롬프트가 전체 분석 시 모든 주요 모듈을
  폭넓게 커버하도록 안내합니다. 라운드·검사·컨텍스트 예산은 `agent` 설정으로,
  구조 커버리지는 `source_overview`의 `max_files`로 조정합니다.
- **MCP 서버 관리** — `/mcp` 슬래시 명령과 `allcode mcp` CLI로 MCP 서버를
  추가/조회/삭제. stdio·http·sse 전송을 저장 전에 검증하고 `.allCode/config.yaml`에
  영속화. → [MCP 서버 관리](#mcp-서버-관리)
- **온디맨드 스킬 시스템** — `.allCode/skills/<name>/SKILL.md`(또는 단일 파일)에
  정의한 지침을 모델이 `skill` tool로 필요할 때 로드. 이름·설명만 항상 노출하는
  progressive disclosure 방식이며, `/skills`로 목록 확인. → [스킬](#스킬-allcodeskills)
- **인-세션 `/resume`** — 실행 시 `--resume` 플래그뿐 아니라 세션 도중에도
  `/resume`으로 최근 세션 목록을 보고 `/resume <id|name>`으로 이전 대화 맥락을
  현재 세션에 로드해 이어갈 수 있음.
- **`/undo`·`/rewind` 구분 명확화** — `/undo`는 git 자동 커밋(히스토리 레벨),
  `/rewind`는 마지막 턴 체크포인트(워킹트리 레벨)로 역할을 분리해 도움말에 명시.
- **통합 에이전트 루프(unified loop)** — 라우팅을 advisory로 두고 모델이 전체
  toolset을 직접 선택. grounding/edit/verify/delegation/anti-loop 가이드를
  통합 프롬프트로 제공.
- **TUI 개선** — 턴 사이 구분선, 다중모달 이미지 입력(`@image.png` 멘션),
  동적 모델 표시 footer, 슬래시 명령 결과 패널 타이틀.

## Troubleshooting

API key가 사용되지 않는 경우:

- `ALLCODE_API_KEY`를 설정하거나, `ALLCODE_API_KEY_ENV`에 실제 key를 담은
  환경 변수명을 설정하세요.
- raw secret을 `config.yaml`에 넣지 마세요.

`base_url` 오류:

- OpenAI-compatible API root를 지정하세요. 예:
  `https://api.openai.com/v1`, `http://127.0.0.1:8000/v1`.
- 로컬 모델 서버는 `/v1/chat/completions` 형식과 SSE streaming 응답을
  지원해야 합니다.

모델 timeout 또는 느린 응답:

- config의 `model.timeout_seconds`를 늘리세요.
- agent loop는 모델명 분기 대신 slow stream heartbeat/status event와
  timeout/retry policy를 사용합니다.

TUI가 시작되지 않는 경우:

- `python -m pip install -e .` 또는
  `python -m pip install -r requirements.txt`로 dependency를 설치하세요.
- 기본 `allcode`는 terminal-native UI입니다. Textual UI를 명시적으로 확인하려면
  `allcode --textual`을 사용하세요.
- non-interactive 환경에서는 `allcode --headless "prompt"`를 사용하세요.

테스트 실패:

- `tests/unit`, `tests/integration`, `tests/quality`, `tests/tty` 중 실패한
  범위부터 좁혀 확인하세요.
- config/entrypoint 문제는 `src/allCode/config`와
  `tests/unit/config/test_config_manager.py`를 확인하세요.
- completion gate 문제는 `src/allCode/agent/completion_gate.py`,
  `src/allCode/core/result.py`,
  `tests/integration/test_mock_agent_loop.py`를 확인하세요.
