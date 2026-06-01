# ac

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
- `ac --headless` 기반 headless 실행.
- Codex-style transcript, Markdown answer rendering, status, input recovery,
  slash command palette, approval panel primitive, folded tool output renderer를
  포함한 Textual 기반 TUI shell.
- registry, executor, approval check, core 표준 `ToolCall`/`ToolResult`,
  edit transaction을 사용하는 tool calling contract.
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

config 파일에는 API key 값을 저장하지 않고, API key가 들어 있는 환경 변수명만
저장합니다.

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
ac --model gpt-4o-mini --base-url https://api.openai.com/v1 --headless "Explain this repo"
```

로컬 OpenAI-compatible endpoint 예시:

```bash
export ALLCODE_API_KEY="local-token"
ac --model local-model --base-url http://127.0.0.1:8000/v1 --headless "Summarize src/allCode"
```

Wisenut Wise LLOA endpoint 예시:

```bash
export ALLCODE_API_KEY="<API token>"
ac --model wisenut/wise-lloa-max-v1.2.1 --base-url http://210.180.82.135:9023/v1 --headless "간단히 자기소개해줘."
```

주의: API token은 README나 config 파일에 저장하지 마세요. `ALLCODE_BASE_URL`
또는 config의 `model.base_url`을 지정하면 CLI/headless/TUI 실행 경로는
`OpenAICompatibleClient`로 실제 모델에 요청합니다. `base_url`을 생략하면
OpenAI 기본 API root인 `https://api.openai.com/v1`을 사용합니다.

## 실행 방법

`pip install -e .` 이후 console script를 사용할 수 있습니다.

```bash
ac --help
ac --headless "Hello from allCode"
echo "Explain the current workspace" | ac --headless
ac --workspace /path/to/project --headless "Inspect src"
ac --config /path/to/config.yaml --headless "Use this config"
ac --approval auto --headless "Create a small Python project named demo_app with tests"
```

설치하지 않고 repository root에서 실행할 수도 있습니다.

```bash
PYTHONPATH=src python -m allCode --help
PYTHONPATH=src python -m allCode --headless "Hello"
```

TUI shell:

```bash
ac
```

TUI는 Textual이 필요합니다. 현재 TUI는 Codex-style dark transcript,
Markdown answer rendering, status handling, input recovery, command palette,
event renderer를 제공하며, 기본 `ac` 실행 경로는 설정된 모델을 호출하는
turn runner에 연결되어 있습니다. transcript는 `USER`, `ALLCODE`, `TOOL`,
`STATUS` 블록으로 분리해 표시합니다.

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
- `src/allCode/tui`: Textual app shell, state controller, input box,
  command palette/registry, approval panel, renderer, UI message model.
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
python -m pytest tests/unit/workspace tests/unit/agent/test_context_builder.py
python -m pytest tests/unit/memory tests/integration/test_followup_context_memory.py
python -m pytest tests/integration/test_generation_workflow.py
python -m pytest tests/integration/test_mock_agent_loop.py tests/integration/test_headless_runner.py
```

문서 작성 시점의 마지막 로컬 검증:

- `python -m pytest tests/unit tests/integration tests/quality tests/tty`
- `python -m pytest`
- `PYTHONPATH=src python -m allCode --help`
- `PYTHONPATH=src python -m allCode --headless "Hello from docs quickstart"`

## 개발 원칙

- 한 파일에 과도한 책임을 몰지 않습니다.
- `core`는 provider SDK, Textual, Rich, 구체 UI 구현에 독립적이어야 합니다.
- 계층 간 데이터는 표준 core `ToolCall`, `ToolResult`, `AgentEvent`,
  `TurnResult` 모델을 사용합니다.
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
- headless 일반 model tool call은 기본 빈 tool registry를 사용합니다.
  project generation workflow는 자체 workflow와 built-in tool을 사용합니다.
- Textual TUI는 실제 모델 runner와 연결되어 있지만, Codex 수준의 rich
  markdown/diff transcript UI는 아직 최소 구현입니다.
- web tool은 evidence-bundle tool입니다. MVP에서는 live network search를
  직접 수행하지 않고, 호출자가 주입한 result/page data를 사용합니다.
- 실제 모델 통합 테스트는 선택 사항이며 기본 test suite에 포함되지 않습니다.
  unit test는 mock transport와 fake LLM scenario를 사용합니다.
- non-headless fullscreen TUI smoke는 실행 환경에 의존합니다. 자동 TTY smoke
  test는 TUI state/rendering contract를 검증합니다.
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
- non-interactive 환경에서는 `ac --headless "prompt"`를 사용하세요.

테스트 실패:

- `tests/unit`, `tests/integration`, `tests/quality`, `tests/tty` 중 실패한
  범위부터 좁혀 확인하세요.
- config/entrypoint 문제는 `src/allCode/config`와
  `tests/unit/config/test_config_manager.py`를 확인하세요.
- completion gate 문제는 `src/allCode/agent/completion_gate.py`,
  `src/allCode/core/result.py`,
  `tests/integration/test_mock_agent_loop.py`를 확인하세요.
