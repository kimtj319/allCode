# Plan 55: Runtime Quality Hardening After Cleanup Smoke

## Purpose

Improve real allCode runtime quality issues found after the dead-code cleanup
without expanding MVP scope or hardcoding benchmark prompts. The target is to
preserve the current architecture and make already-collected evidence turn into
useful user-facing answers more reliably.

## Contract References

- `README.md`: current config, headless, TUI, and runtime behavior.
- `AGENTS.md`: validation, no hardcoding, feature preservation rules.
- `plan/00_master_implementation_guide.md`: modularity and no single-file agent.
- `plan/01_open_source_alignment_contracts.md`: provider-neutral loop, route
  safety, repo-map/source-evidence grounding.
- `plan/04_llm_loop_plan.md`: max-round, reasoning-only, final-answer recovery.
- `plan/05_routing_policy_plan.md`: read-only safety takes precedence over
  mutation signals.
- `plan/07_workspace_context_plan.md`: source intelligence and workspace evidence.
- `review/dead_code_cleanup_runtime_findings.md`: observed smoke failures.

## agy Analysis Summary

agy reviewed the runtime findings in code-modification-forbidden mode and agreed
with four phases:

1. Dependency guard should allow answer-only local module examples without
   allowing real third-party imports.
2. Max-round inspect fallback should keep `status="partial"` but return
   `grounded_inspect_summary` when read evidence exists.
3. Read-only Korean phrases such as "수정 없이" must be detected only as
   mutation-negation combinations, not by matching "없이" alone.
4. Config discovery should load workspace `.env` first, then launch/current
   directory `.env` as a non-overriding fallback, so isolated workspaces can still
   use the user's configured credentials.

Second-pass agy plan review confirmed the architecture as safe and added these
implementation constraints:

- Do not whitelist local modules by specific names such as `config`; parse
  generic file/module evidence instead.
- Do not let `# file: requests.py` or similar comments allow known third-party
  package names to bypass dependency constraints.
- Apply max-round source-summary fallback only for `routing.kind == "inspect"`
  and only when meaningful inspect evidence exists.
- Match Korean read-only wording as mutation-noun + negation structure only; do
  not match bare `없이`.
- When loading fallback `.env`, compare workspace and cwd `.env` paths after
  `resolve()` and skip duplicate loading when they are the same file.

## Non-Goals

- Do not change tool execution policy or approval behavior except through
  routing correctness.
- Do not weaken file mutation evidence gates.
- Do not change model provider contracts or bind provider SDKs into `core`.
- Do not hardcode test prompt strings, paths, model names, or project names.
- Do not turn failed modify/validation work into success without evidence.
- Do not add post-MVP systems such as MCP, plugin marketplace, or multi-agent
  workflows.

## Phase A: Dependency Guard Local-Module Precision

Targets:

- `src/allCode/agent/dependency_answer_guard.py`
- `tests/unit/agent/test_dependency_answer_guard.py`

Problem:

For answer-only standard-library prompts, examples can include local modules such
as `config`, `storage`, or `cli`. The current guard recognizes local roots mostly
from path-like references, so a valid local import in a self-contained code
snippet can be rejected as `dependency_constraint_non_stdlib_import`.

Implementation:

1. Extract local module candidates from code block definitions and simple local
   file references:
   - Python files named in the answer: `config.py`, `src/app/config.py`.
   - Python code blocks defining local modules in comments/headings such as
     `# config.py` or `# file: config.py`.
   - Already supported path references remain valid.
2. Allow only top-level identifiers that match those local module candidates.
3. Keep known third-party package detection unchanged.
4. Never allow known third-party names through the local-module candidate path,
   even if the answer contains a matching `requests.py`/`pytest.py` style file
   reference.
5. Do not treat arbitrary unknown imports as local merely because they are short
   or common words.
6. Improve sanitized fallback to preserve useful answer content when only local
   module examples caused a false positive.

Validation:

```bash
python -m pytest tests/unit/agent/test_dependency_answer_guard.py
```

New/updated tests:

- Allows `from config import Settings` when the answer references `config.py`.
- Still rejects `import redis`, `from bs4 import BeautifulSoup`, and install
  commands.
- Still rejects `import requests` even when the answer contains `# file:
  requests.py`.

## Phase B: Inspect Max-Round Evidence Fallback

Targets:

- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/inspect_summary.py`
- agent loop/recovery tests as needed.

Problem:

For read-only inspect turns, allCode may successfully run `read_file` and
`source_probe` but still reach max rounds without model finalization. The current
tail of `RoundRunner.run_rounds` returns `blocked_summary(...)`, losing the
observed evidence quality.

Implementation:

1. At max-round exit, if `routing.kind == "inspect"` and
   `has_inspect_summary_evidence(completion_evidence)` is true, return:
   - `LoopOutcome(status="partial", answer=grounded_inspect_summary(...))`
   - `error="max_rounds_reached"`
2. Preserve `partial` status so non-convergence is still visible.
3. Keep the existing blocked summary for no-evidence cases and mutation/validation
   routes.
4. Use the prompt language for fallback output.
5. Do not apply this fallback to `modify` or `operate`, even if they collected
   read evidence before failing to converge.

Validation:

```bash
python -m pytest tests/unit/agent/test_inspect_summary.py tests/integration/test_readonly_source_analysis.py
```

New/updated tests:

- A fake inspect turn with collected read/probe evidence and no final answer
  returns a grounded partial summary instead of only a max-round block.
- A modify turn with read evidence still returns the existing max-round block.

## Phase C: Read-Only Precedence for Follow-Up Generation Context

Targets:

- `src/allCode/agent/prompt_safety.py`
- `src/allCode/agent/prompt_constraint_terms.py`
- `src/allCode/agent/route_validator.py`
- `src/allCode/agent/model_router.py`
- `tests/unit/agent/test_prompt_constraints.py`
- `tests/unit/agent/test_router.py`
- `tests/unit/agent/test_model_router.py`

Problem:

Follow-up wording such as "방금 생성한 ... 코드 수정 없이 설명" can carry a
generation/mutation context while also explicitly forbidding edits. The read-only
constraint must dominate.

Implementation:

1. Add bounded Korean read-only patterns for mutation-negation combinations:
   - `수정 없이`, `변경 없이`, `편집 없이`, `삭제 없이`, `파일 변경 없이`,
     and `수정하지 않고`.
2. Do not match bare `없이`, because it appears in dependency constraints such as
   "외부 패키지 없이 구현".
3. Ensure `PromptConstraintExtractor` reports `read_only_requested=True` and
   `mutation_requested_hint=False` for these combinations.
4. Ensure model-router and route-validator sanitization keeps such prompts on
   `inspect` with no mutation, validation, shell, or delete capabilities when a
   path/workspace evidence signal exists.

Validation:

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_router.py tests/unit/agent/test_model_router.py
```

New/updated tests:

- `방금 생성한 path.py의 구조를 코드 수정 없이 설명` routes to inspect.
- `외부 패키지 없이 작은 CLI를 구현` remains a mutation/generation request when
  it asks for actual files.

## Phase D: Config Discovery Fallback for Isolated Workspaces

Targets:

- `src/allCode/config/manager.py`
- `tests/unit/config/test_config_manager.py`

Problem:

When `--workspace` points outside the project root, config loading uses that
workspace as the project root and reads only `<workspace>/.env`. This can miss
credentials configured in the launch repository `.env`, causing real smoke tests
against isolated workspaces to fail before the agent starts.

Implementation:

1. Continue loading workspace `.env` first.
2. Then load `Path.cwd() / ".env"` as a fallback only when it is different from
   the workspace `.env`.
3. Use `override=False`, so workspace `.env` and existing process env values keep
   precedence.
4. Keep the allowed-prefix filter in `env_file.py`; do not load arbitrary
   secrets.
5. Compare env file paths with `resolve()` to avoid duplicate parsing when cwd
   and workspace are the same directory.

Validation:

```bash
python -m pytest tests/unit/config tests/unit/test_entrypoint.py
```

New/updated tests:

- Workspace `.env` wins over cwd `.env`.
- Cwd `.env` fills `ALLCODE_API_KEY` when isolated workspace has no `.env`.
- Non-`ALLCODE_` variables remain ignored.

## Phase E: Runtime Comparison Validation

After Phases A-D:

```bash
python -m pytest tests/unit/config tests/unit/agent tests/integration/test_readonly_source_analysis.py tests/tty
python -m pytest
```

Then run real command smoke:

1. allCode and agy: read-only source/file analysis.
2. allCode and agy: standard-library-only CLI design answer.
3. allCode and agy: general knowledge answer.
4. allCode only: isolated workspace generation with launch `.env` fallback.

Pass criteria:

- Standard-library-only answer is not blocked for local module examples.
- Read-only inspect prompts do not call mutation tools.
- Read-only inspect evidence yields a useful partial/final answer, not only
  `max_rounds_reached`.
- Isolated workspace can start with credentials loaded from launch cwd `.env`
  unless an explicit workspace/user env overrides it.

## Phase F: Slash-Separated Command Names Must Not Become File Artifacts

Targets:

- `src/allCode/agent/prompt_constraint_detection.py`
- `src/allCode/agent/phase_gate_artifacts.py`
- `src/allCode/agent/project_planner.py`
- `tests/unit/agent/test_prompt_constraints.py`
- `tests/unit/agent/test_phase_gate.py`
- `tests/unit/agent/test_project_planner.py`

Problem:

Runtime comparison found that prompts such as "add/list 명령" were parsed as a
workspace file path `add/list`. This polluted both path hints and requested
artifact obligations. The phase gate then forced `source:add/list`, causing the
agent to create an unnecessary file instead of treating `add` and `list` as CLI
subcommands.

agy reviewed the issue and confirmed that filtering only `path_hints` is
insufficient because `phase_gate_artifacts.ensure_requested_artifacts()` also
called `extract_prompt_paths()` directly.

Implementation:

1. Add a shared agent-level `prompt_path_hint_allowed()` predicate.
2. Keep file-like paths:
   - paths whose basename has an extension,
   - common extensionless artifacts such as `README`, `LICENSE`, `Makefile`,
     `Dockerfile`, `Procfile`, and `justfile`,
   - common workspace or output roots,
   - extensionless directory paths only when nearby wording says directory,
     folder, path, under, inside, `아래`, `안에`, or similar.
3. Use this predicate in both:
   - `path_hints()`, and
   - `ensure_requested_artifacts()`.
4. Add a planner-level file artifact guard so an LLM-generated plan can still
   drop command-like file items even if they appear in model JSON.
5. Do not hardcode `add/list`; the rule applies to slash-separated command
   pairs such as `create/read`, `import/export`, and `signin/signout`.

Validation:

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_phase_gate.py tests/unit/agent/test_project_planner.py
python -m pytest
```

Runtime validation:

- `.venv/bin/allcode --headless ... --workspace /private/tmp/allcode_quality_smoke_fixed`
  created only `notes_cli.py` and `tests/test_notes_cli.py`.
- `/private/tmp/allcode_quality_smoke_fixed` passed `python -m pytest -q`.
- The latest session log contains no `source:add/list` requested artifact or
  `write_file` target.

## Remaining Risks

- Dependency import analysis is heuristic. It must remain stricter for unknown
  imports than for explicitly named local modules.
- Max-round fallback can hide model finalization weakness if marked success.
  Therefore this plan keeps `partial` status.
- Source-analysis answers are still more evidence-list oriented than agy. A
  future phase should improve final answer synthesis density, not tool recall.
- Read-only Korean phrasing has many variants; only structural
  mutation-negation combinations should be added.
- Cwd `.env` fallback can surprise users in nested shells. `override=False` and
  workspace-first loading are required to avoid overriding intentional workspace
  config.
