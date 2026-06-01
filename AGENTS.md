# Agent Instructions for allcode

This repository is a lightweight enterprise CLI coding agent. Work in this repo
must preserve the MVP architecture and the implementation contracts in `plan/`.

## Required Reading Order

Before making non-trivial changes, read:

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. The plan document directly related to the change:
   - config/entrypoint: `plan/02_config_entrypoint_plan.md`
   - core contracts: `plan/03_core_contracts_plan.md`
   - LLM loop/parser: `plan/04_llm_loop_plan.md`
   - routing/policy: `plan/05_routing_policy_plan.md`
   - tools/approval: `plan/06_tool_system_plan.md`
   - workspace/context: `plan/07_workspace_context_plan.md`
   - memory: `plan/08_context_memory_plan.md`
   - generation workflow: `plan/09_generation_workflow_plan.md`
   - TUI: `plan/10_tui_app_plan.md`
   - quality/testing: `plan/11_quality_testing_plan.md`
   - MVP milestones: `plan/12_mvp_execution_plan.md`

`plan/00` through `plan/12` are implementation contracts. `plan/13` and
`plan/14` are review appendices; if they conflict, follow `plan/00` through
`plan/12`. If design details are ambiguous, prefer
`plan/01_open_source_alignment_contracts.md`.

## Code Modification Rules

- Inspect the actual code before changing behavior. Do not rely only on plan
  text.
- Keep changes scoped to the relevant package boundary.
- Add or update tests with behavior changes.
- For large implementation work, move in this order:
  skeleton -> contract -> implementation -> validation.
- Keep files focused. Do not recreate a large single-file agent.
- Keep `core` provider-neutral and UI-neutral.
- Use `core.models.ToolCall`, `core.models.ToolResult`,
  `core.events.AgentEvent`, and `core.result.TurnResult` instead of redefining
  equivalents in feature packages.
- File mutation must go through tool execution and edit transaction evidence.
- Completion for implementation/modification work must be grounded in
  `CompletionEvidence`.
- Prefer workspace/path policy helpers over ad hoc path handling.

## Prohibited Changes

- Do not replace core implementation with `pass`, `TODO`, placeholder stubs, or
  "implemented later" comments.
- Do not report completion without actual file changes when a change was
  requested.
- Do not hardcode secrets, API keys, or bearer tokens.
- Do not store raw secrets in config or memory.
- Do not bind provider SDKs directly into `core`.
- Do not make TUI code import agent internals directly; TUI consumes events and
  UI-facing message/state models.
- Do not hardcode specific test prompts or project names into source code.
- Do not implement post-MVP expansion items unless explicitly requested:
  git auto-commit, plugin marketplace, MCP server manager, multi-agent swarm,
  cloud sandbox, PageRank repo ranking, or full interactive diff editor.

## Validation Rules

Run the smallest relevant test first, then broaden as needed.

Config and entrypoint:

```bash
python -m pytest tests/unit/config tests/unit/test_entrypoint.py
```

Core contracts:

```bash
python -m pytest tests/unit/core
```

LLM parser and adapter:

```bash
python -m pytest tests/unit/llm
```

Routing, policy, and tools:

```bash
python -m pytest tests/unit/agent tests/unit/tools
```

Workspace and context:

```bash
python -m pytest tests/unit/workspace tests/unit/agent/test_context_builder.py
```

Memory:

```bash
python -m pytest tests/unit/memory tests/integration/test_followup_context_memory.py
```

Generation workflow:

```bash
python -m pytest tests/integration/test_generation_workflow.py
```

Headless and mock agent loop:

```bash
python -m pytest tests/integration/test_mock_agent_loop.py tests/integration/test_headless_runner.py
```

TUI and quality:

```bash
python -m pytest tests/tty tests/quality
```

Full regression:

```bash
python -m pytest
```

For README or AGENTS changes, verify that documented commands still match
`allcode --help`, `pyproject.toml`, and the actual test layout.

## Documentation Rules

- Prefer actual implementation over plan text when documenting current behavior.
- If current behavior is narrower than the plan, record it under
  `Current Limitations` in `README.md`.
- Keep `requirements.txt` aligned with `pyproject.toml` if it exists. The
  pyproject file is canonical.
- Runtime CLI/headless/TUI paths select the real OpenAI-compatible LLM adapter
  by default. Use fake LLMs only through explicit test injection.

## Final Response Rules

When reporting completed work, include:

1. Modified files
2. Test commands run
3. Test results
4. Remaining risks
5. Next-step notes
