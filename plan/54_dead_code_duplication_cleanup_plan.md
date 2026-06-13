# Plan 54: Dead Code and Duplicate Responsibility Cleanup

## Purpose

Remove code that is not used by the actual allCode runtime while preserving every
current feature: terminal-native UI, optional Textual UI, headless runner, routing,
tool execution, workspace/source analysis, memory, validation, and telemetry.

This plan is intentionally conservative. Static "unused" signals are not enough
to delete public contracts, event types, optional adapter contracts, or documented
runtime paths.

## Required Contract References

- `README.md`: current user-facing runtime behavior.
- `AGENTS.md`: repository modification and validation rules.
- `plan/00_master_implementation_guide.md`: enterprise modularity and MVP scope.
- `plan/01_open_source_alignment_contracts.md`: provider-neutral, terminal-first,
  repo-map/tool-loop alignment.
- `plan/03_core_contracts_plan.md`: core events/errors/results are stable contracts.
- `plan/07_workspace_context_plan.md`: workspace and source intelligence contracts.
- `plan/10_tui_app_plan.md`: TUI behavior and UI/agent separation.
- `plan/11_quality_testing_plan.md`: regression and quality test expectations.

## Audit Summary

The current audit used:

- File/LOC scan of `src/allCode`.
- Entrypoint reachability from `allCode.main`, `allCode.__main__`,
  `allCode.runtime`, `allCode.headless`, and `allCode.tui.runtime`.
- `rg` reference checks across `src`, `tests`, README, AGENTS, and plans.
- AST-based import graph and definition occurrence scan.
- `python -m py_compile` over all `src/allCode/**/*.py`.
- agy review in code-modification-forbidden mode.

Findings:

- `src/allCode` has 259 Python modules.
- No Python source file currently exceeds 500 LOC.
- The largest files remain below the hard ceiling:
  `agent/source_answer_guard.py` 476 LOC, `agent/project_planner.py` 467 LOC,
  `agent/finalization.py` 452 LOC, `agent/workflow.py` 434 LOC.
- Confirmed tracked source files with no source imports and no test references:
  `src/allCode/tui/terminal_ime.py`,
  `src/allCode/workspace/source_intelligence/lsp_registry.py`.
- Confirmed helper-level single-occurrence candidates:
  `streaming_assistant_cell`,
  `summarize_code`,
  `package_role_paths`,
  `validation_repair_phase_gate`.
- `src/allCode/quality` contains only ignored `__pycache__` artifacts, not tracked
  source.

## agy Review Summary

agy agreed that cleanup should be conservative:

- Safe cleanup candidates:
  `terminal_ime.py`, `lsp_registry.py`, `summarize_code`, and generated
  `quality/__pycache__` artifacts.
- Keep or treat carefully:
  `core/events.py` and `core/errors.py` contract types.
- Do not remove only because static references are sparse:
  optional UI compatibility, public event/error classes, source-intelligence
  contracts.
- Suggested consolidation:
  use `streaming_assistant_cell` from `transcript_state.py` instead of duplicating
  the assistant-stream cell construction inline.
- Second-pass agy review confirmed the seven planned decisions as safe or
  conditionally safe. It requested two refinements:
  preserve streaming-cell render semantics with a focused test, and explicitly
  document that deleting `lsp_registry.py` removes only currently disconnected
  automatic LSP discovery, not the injected `SourceLspClient` contract.

## Non-Goals

- Do not change routing behavior.
- Do not change model prompts, final-answer gates, source-analysis quality gates,
  or tool exposure policy.
- Do not remove optional Textual runtime support.
- Do not remove core event/error classes merely because current runtime does not
  instantiate every contract type.
- Do not delete tests, docs, plan appendices, or ignored local output directories
  as part of source cleanup.
- Do not introduce hardcoded prompt strings, benchmark IDs, or project-specific
  special cases.

## Phase 1: Safe TUI Helper Consolidation

Target:

- `src/allCode/tui/transcript_state.py`
- `src/allCode/tui/transcript_cells.py`

Work:

1. Replace the inline construction
   `assistant_cell("").model_copy(update={"kind": "assistant_stream", ...})`
   with the existing `streaming_assistant_cell("")` helper.
2. Keep `streaming_assistant_cell`; after this change it is no longer dead code.

Validation:

```bash
python -m pytest tests/unit/tui tests/tty
```

Guardrail:

- Do not change transcript cell schema or rendered labels.
- Add or update a focused test proving the active assistant stream cell remains
  `kind="assistant_stream"`, `title="allCode"`, and `transient=True`.

## Phase 2: Remove Confirmed Dead Source Helpers

Targets:

- `src/allCode/tui/terminal_ime.py`
- `src/allCode/workspace/source_intelligence/lsp_registry.py`
- `src/allCode/agent/source_structure.py`
- `src/allCode/agent/source_package_role_guard.py`
- `src/allCode/agent/phase_gate.py`

Work:

1. Delete `terminal_ime.py`; current terminal input uses
   `terminal_width.display_width` directly and no module imports `terminal_ime`.
2. Delete `lsp_registry.py`; current source-intelligence runtime accepts an
   injected `SourceLspClient` and defaults to `DisabledLspClient`, with no
   registry discovery call path.
3. Remove unused helper functions:
   `summarize_code`, `package_role_paths`, and `validation_repair_phase_gate`,
   after one final `rg` check confirms no references.

Validation:

```bash
python -m pytest tests/unit/agent tests/unit/workspace tests/tty
python -m py_compile $(find src/allCode -name '*.py')
```

Guardrails:

- Do not remove `SourceLspClient`, `DisabledLspClient`, or `StaticLspClient`.
- Do not remove `SourceIntelligenceService`.
- Do not remove core events or errors.
- Do not remove `input_box.py`; it is optional Textual input-state compatibility
  and agy flagged input-state removal as a higher-risk cleanup.
- Treat `lsp_registry.py` removal as source cleanup only. If automatic LSP
  discovery becomes a requested feature later, reintroduce it through
  `SourceIntelligenceService` wiring and tests instead of keeping disconnected
  registry code.

## Phase 3: Duplicate Responsibility Review Without Behavior Change

Targets:

- Prompt constraint modules:
  `prompt_constraint_detection.py`, `prompt_constraint_terms.py`,
  `prompt_constraints.py`, `intent.py`, `model_router_signals.py`.
- Source-answer guard modules:
  `source_answer_guard.py`, `source_package_role_guard.py`,
  `source_answer_requirements.py`, `source_answer_synthesis.py`,
  `source_answer_fallback.py`.

Work:

1. Re-run reference and LOC scans after Phase 2.
2. Do not merge modules in this phase unless there is a pure helper with a single
   clear owner and existing tests.
3. Record remaining duplication candidates for future work instead of performing
   risky semantic refactors.

Validation:

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_router.py tests/unit/agent/test_model_router.py
python -m pytest tests/unit/agent/test_source_answer_guard.py tests/unit/agent/test_source_answer_synthesis.py
```

Guardrail:

- Source-analysis answer quality and route safety recently improved; avoid broad
  guard rewrites during dead-code cleanup.

Phase 3 implementation note:

- After Phase 2, `src/allCode` Python modules decreased from 259 to 257.
- No source/test references remain for `terminal_ime`, `lsp_registry`,
  `summarize_code`, `package_role_paths`, or `validation_repair_phase_gate`.
- A repeated single-occurrence definition scan now reports only core event/error
  contract classes. These are intentionally preserved under `plan/03`.
- Prompt-constraint and source-answer modules still have conceptual overlap, but
  they encode active routing/safety semantics and are not dead code. They should
  be handled by a separate behavior-preserving design refactor, not by this
  cleanup.

## Phase 4: Full Regression and Runtime Smoke

Commands:

```bash
python -m pytest
python -m py_compile $(find src/allCode -name '*.py')
```

Runtime prompt checks through the actual `allcode` command:

1. Read-only source analysis:
   "현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다"
2. General knowledge direct answer:
   "양자역학의 코펜하겐 해석과 다세계 해석 차이를 쉬운 비유로 설명해줘."
3. Dependency-constrained design answer:
   "외부 패키지 없이 Python 표준 라이브러리만 사용해서 작은 CLI를 설계하는 방법을 알려줘."
4. Lightweight generation in an isolated temporary directory.
5. Follow-up question after a prior answer.

Pass criteria:

- No regressions in pytest.
- `allcode` still starts normally.
- Read-only prompts do not mutate files.
- General answers do not enter unnecessary tool loops.
- Source-analysis answer still contains grounded package roles and limitations.

## Remaining Risks

- Static reachability cannot prove external API use. Therefore public contracts
  in `core/events.py`, `core/errors.py`, and source-intelligence schema/client
  contracts must remain.
- `input_box.py` has no current source import but overlaps with optional Textual
  input-state design. Remove only if Textual app is explicitly migrated to the
  state model with tests.
- `src/allCode/quality/__pycache__` can be cleaned locally, but because it is not
  tracked source it must not be represented as product refactoring.
