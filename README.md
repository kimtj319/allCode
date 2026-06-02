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
- `ALLCODE_WEB_SEARCH_URL`: provider-neutral HTTP JSON web search endpoint.
- `ALLCODE_WEB_SEARCH_API_KEY_ENV`: web search endpoint token을 담은 환경 변수명.
- `ALLCODE_WEB_SEARCH_TIMEOUT`: web search timeout seconds.

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
workspace:
  root: .
  extra_roots: []
  sandbox_enabled: true
approval:
  mode: ask
  session_allow: []
```

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
  symbol extraction.
- `src/allCode/memory`: hierarchical memory, store, session store/summary,
  recent target, repo map/ranker, selector, compactor, auto-memory inbox,
  `/memory` command backend.
- `src/allCode/tui`: default terminal-native UI, optional Textual app,
  terminal composer/keymap/history/completion/paste handling, Markdown
  normalization/rendering, transcript state/reducer/view, command registry,
  approval panel state, event renderer, UI message model.
- `src/allCode/config`: config schema, defaults, precedence-aware loader.
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
- web search는 `web.search_url`이 설정된 HTTP JSON provider가 있을 때만 live
  search를 수행합니다. `web_fetch`는 MVP에서 실제 URL fetch가 아니라 호출자가
  주입한 page content를 evidence bundle로 정규화합니다.
- 기본 `approval.mode=ask`에서는 file mutation과 일반 shell command가
  approval_required 결과로 중단됩니다. 자동 코딩/검증 smoke에는
  `--approval auto` 또는 session allow rule이 필요할 수 있습니다.
- 실제 모델 통합 테스트는 선택 사항이며 기본 test suite에 포함되지 않습니다.
  unit test는 mock transport와 fake LLM scenario를 사용합니다.
- non-headless 실제 PTY smoke는 실행 환경에 의존합니다. 자동 TTY smoke test는
  terminal-native/Textual state와 rendering contract를 검증합니다.
- git auto-commit, plugin marketplace, MCP server manager, multi-agent swarm,
  cloud sandbox, PageRank-style repo ranking, full interactive diff editor는
  `docs/future_work.md`에 post-MVP 항목으로 기록되어 있습니다.

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
