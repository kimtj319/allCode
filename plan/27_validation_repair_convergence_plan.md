# 27. Validation Repair Convergence Plan

## Purpose

This plan follows `plan/26_remaining_open_source_parity_hardening_plan.md` and the real-model issue report in `review/plan26_real_model_regression_issues.md`.

The Plan 26 implementation made completion stricter and correctly exposed missing test/validation evidence. However, the real-model run still produced:

- `9 pass / 8 warning / 3 fail`
- average score `92.2`
- failures concentrated in validation repair and test-authoring convergence

This plan focuses on converting advisory recovery into deterministic, evidence-driven convergence. It is based on:

- code inspection of `prompt_builder.py`, `round_runner.py`, `validation_repair.py`, `phase_gate.py`, `tool_orchestrator.py`, and `tool_call_processor.py`;
- the `review/plan26_real_model_regression_issues.md` findings;
- a read-only agy discussion on validation repair and test-authoring convergence;
- the core contracts in `plan/00` through `plan/12`.

## Non-Negotiable Constraint: No Meaningless Hardcoding

Do not repair these cases by matching scenario IDs, exact prompts, project names, expected benchmark terms, or model names.

Forbidden:

- checking for `CG01`, `CG05`, `CG09`, or any scenario ID;
- special-casing `tools/md_to_html.py`, `mini_api/router.py`, `game/rpg.py`, or generated benchmark paths;
- injecting benchmark expected terms such as `Markdown`, `auth`, or `inventory`;
- adding branches for `wisenut/wise-lloa-max-v1.2.1`;
- matching one exact Korean sentence to force test authoring.

Allowed generic signals:

- structured validation failure metadata;
- path and line extraction from stack traces, pytest output, compiler output, and tool metadata;
- `RequestedArtifact` checklist state;
- `ToolResult.error_type` such as `patch_ambiguous`, `schema_denied`, and `validation_failed`;
- route phase, allowed tool schema, and phase-gate metadata;
- recent changed files and validation failure targets.

## Current Failure Taxonomy

### F1. Ambiguous Patch Repair Does Not Switch Strategy

Observed:

- Source and test files were created.
- Validation failed.
- `patch_file` failed with `patch_ambiguous` because the search block matched many regions.
- The loop did not strongly force a range read or whole-file rewrite, so it later hit progress blocking.

Current relevant code:

- `src/allCode/tools/builtin/file_ops.py`
  - emits structured `PatchApplicationError` metadata.
- `src/allCode/agent/tool_orchestrator.py`
  - `PatchFailureTracker` only suppresses repeated identical patch search blocks.
  - It does not block a first ambiguous file from further patch attempts.
- `src/allCode/agent/prompt_builder.py`
  - patch guidance is advisory and not phase-specific.
- `src/allCode/agent/round_runner.py`
  - can still return `tool_progress_blocked` after patch failure plus repeated read.

### F2. Validation Failure Targets Are Not First-Class Repair State

Observed:

- Validation failed with syntax/test errors.
- `validation_repair.py` summarized failures, but the loop did not force repair around the exact failing file/line.
- The model kept editing or reading a repeated target until max rounds.

Current relevant code:

- `src/allCode/agent/validation_repair.py`
  - extracts `failed_files`, `failing_symbols`, and summary text.
  - does not expose a typed `RepairTarget`.
- `src/allCode/core/result.py`
  - stores `validation_failure_symbols`, but not failure file/line targets.
- `src/allCode/agent/phase_gate.py`
  - phase gate has no repair-target metadata.
- `src/allCode/agent/prompt_builder.py`
  - `validation_repair_request()` does not include structured repair targets.

### F3. Test-Authoring Gate Blocks Invalid Actions But Does Not Escalate

Observed:

- `RequestedArtifact(kind="test")` correctly remained unsatisfied.
- `run_tests` was schema-denied in `test_authoring_required`.
- The model did not respond by creating a test file; it kept selecting phase-inappropriate tools.

Current relevant code:

- `src/allCode/agent/phase_gate.py`
  - detects `test_authoring_required`.
- `src/allCode/agent/tool_call_processor.py`
  - emits `schema_denied`.
- `src/allCode/agent/round_runner.py`
  - on schema-denied in mutation/test/repair phases, it falls back to generic `mutation_action_request()`.
- `src/allCode/agent/prompt_builder.py`
  - lacks a dedicated `test_authoring_request()`.

## agy Discussion Summary

agy's read-only feedback agreed with the code analysis and recommended:

1. Add `RepairTarget` to `CompletionEvidence`.
2. Extract repair targets from Python tracebacks, pytest output, and generic `path:line` compiler-style messages.
3. Track `patch_ambiguous_files` in evidence or tracker state.
4. When patch ambiguity is active for a file, remove `patch_file` from the repair phase and prefer `read_file` with range or `write_file`.
5. Add `PromptBuilder.test_authoring_request()`.
6. Make `RoundRunner` escalate schema-denied actions in `test_authoring_required` and `validation_failed` phases into targeted retry prompts, not only generic mutation prompts.

## agy Open-Source Re-Review Additions

A second read-only agy review compared this plan against feasible patterns from Aider, OpenHands, Gemini CLI, and Qwen Code. The review did not recommend replacing the current allCode architecture. It recommended tightening several implementation details already compatible with existing `CompletionEvidence`, `PhaseToolGate`, `RoundRunner`, and prompt-builder boundaries.

Keep as-is:

- file-level `patch_ambiguous_files` as the Aider-style edit-strategy fallback signal;
- `RepairTarget` extraction as the validation repair input;
- targeted schema-denied escalation for `test_authoring_required` and `validation_failed`;
- Stop-style finalization blocking when artifact or validation obligations are unsatisfied;
- compact repair context instead of repeated full validation logs.

Add to the plan:

- require a **read-before-rewrite** step before `write_file` is preferred for an ambiguous target, unless the file was already read in the current repair context;
- define ambiguity reset precisely: clear a file from `patch_ambiguous_files` only after a successful `write_file` or successful `patch_file` mutation for that file, or after validation success;
- cap active repair targets injected into prompts at three, ordered by latest validation relevance;
- standardize phase-block observations so they state what was blocked, why, and the required next tool family;
- set a bounded retry budget for consecutive phase blocks before returning a partial result;
- include short, provider-neutral tool-call schema reminders in targeted retry prompts.

Continue to exclude:

- custom Aider-style diff syntax parsers;
- git-native auto-commit, rollback, or branch evaluation workflows;
- a general OpenHands-style external hook registry;
- user-facing Gemini-style memory slash commands as part of this repair plan;
- Qwen daemon, SDK mode, or provider-specific model branches;
- scenario-specific or model-specific hardcoding.

## Open-Source Pattern Review And Applicability

The following public open-source agent patterns were checked for practical applicability to the current allCode codebase.

Sources reviewed:

- Aider edit formats: https://aider.chat/docs/more/edit-formats.html
- Aider lint/test loop: https://aider.chat/docs/usage/lint-test.html
- OpenHands agent architecture: https://docs.openhands.dev/sdk/arch/agent
- OpenHands hooks: https://docs.openhands.dev/sdk/guides/hooks
- Gemini CLI hierarchical context: https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- Qwen Code repository and docs links: https://github.com/QwenLM/qwen-code

### Pattern A. Aider Search/Replace To Whole-File Fallback

Relevant observation:

- Aider supports both efficient search/replace style edits and a simpler whole-file edit format. The public docs describe whole-file edits as costly but simple, and diff/search-replace edits as efficient but dependent on exact matching.

Applicability to allCode:

- This directly maps to the `patch_ambiguous` failures.
- allCode already has `patch_file` and `write_file`; no new edit tool is needed.
- The feasible change is not to implement Aider's full edit-format system, but to add an explicit **patch-to-write fallback policy**:
  - first exact patch ambiguity marks the file as ambiguous;
  - subsequent repair on that file should prefer `read_file` range or `write_file`;
  - `patch_file` can be removed from the allowed schema for that repair target until a successful mutation clears the ambiguity.

Excluded:

- Full Aider architect/editor split is not added. It would be a larger architecture change and is not required for the observed failures.
- Git-native auto-commit/test workflows remain outside MVP scope.

### Pattern B. Aider Test-Fix Loop

Relevant observation:

- Aider can run tests after edits and expects non-zero test/lint output to be used as repair input.

Applicability to allCode:

- allCode already has `run_tests`, `ValidationFailureSummary`, `CompletionEvidence`, and validation repair state.
- The feasible change is to make validation output a structured repair input:
  - extract `RepairTarget` file/line/symbol;
  - store it in `CompletionEvidence`;
  - force the next repair round to inspect/mutate the target before revalidation.

Excluded:

- Per-language linter registries are not added in this step. They can be added later through validation command selection, but the current failures are from repair target selection, not linter discovery.

### Pattern C. OpenHands Event-Driven Action/Observation And Blocking Hooks

Relevant observation:

- OpenHands models agent progress as an event-driven reasoning/action loop, with tools producing observations.
- Its hook docs describe blocking lifecycle points such as `PreToolUse` and `Stop`, where feedback is surfaced and the conversation continues.

Applicability to allCode:

- allCode already emits events and has phase-gated tool schemas.
- The feasible change is to treat phase gates like internal blocking hooks:
  - `test_authoring_required` blocks `run_tests` but must also feed targeted corrective context back into the loop;
  - `patch_strategy_required` should not immediately end the turn, but should act like a blocking hook that returns a reason and continues once with a targeted retry;
  - attempted finalization with unsatisfied artifacts should be handled like a `Stop` block and converted into a concrete next action.

Excluded:

- A general external hook/plugin framework is not added. That would expand MVP scope and risk duplicating existing policy/phase-gate contracts.

### Pattern D. Gemini CLI Hierarchical Context

Relevant observation:

- Gemini CLI loads layered context files and provides `/memory show`, `/memory refresh`, and `/memory add` to make context inspectable.

Applicability to allCode:

- allCode already has `ALLCODE.md` memory and context sections.
- For this plan, the useful takeaway is **compact, inspectable repair context**, not more memory infrastructure:
  - add a compact "repair context" block containing missing artifacts, repair targets, ambiguous patch files, and preferred next tools;
  - avoid dumping full validation logs repeatedly.

Excluded:

- No new memory layer or import processor is needed for validation repair convergence.

### Pattern E. Qwen Code Provider-Neutral Terminal Agent And Parser Adaptation

Relevant observation:

- Qwen Code is terminal-first, provider-configurable, and explicitly acknowledges parser-level adaptations for model/tool-call behavior.

Applicability to allCode:

- allCode already uses provider-neutral models and OpenAI-compatible adapters.
- The feasible change is to make recovery prompts and schema-denied observations more parser/model tolerant:
  - do not rely on the model intuiting phase corrections from generic schema errors;
  - convert schema-denied observations into explicit, phase-specific retry messages;
  - keep tool-call protocol unchanged.

Excluded:

- Qwen daemon mode, SDK integration, and model-provider specific branches are not relevant to these failures.

## Detailed Implementation Plan

### P0. Add RepairTarget And Patch-Ambiguity Evidence

Target files:

- `src/allCode/core/result.py`
- `tests/unit/core/test_result.py`

Add:

```python
class RepairTarget(CoreModel):
    file_path: str
    line_number: int | None = None
    symbol: str = ""
    reason: str = ""
```

Extend `CompletionEvidence`:

```python
validation_failure_targets: list[RepairTarget] = Field(default_factory=list)
patch_ambiguous_files: list[str] = Field(default_factory=list)
```

Semantics:

- `validation_failure_targets` contains files/lines extracted from validation output.
- `patch_ambiguous_files` contains files where patch search had multiple matches and patching should no longer be the default strategy.
- On validation success, clear both fields.
- On successful mutation for a file, clear ambiguity and repair targets for that file.

Acceptance:

- Core model serializes/deserializes new fields.
- Existing `TurnResult` validation remains unchanged.

### P1. Extract Structured Repair Targets

Target files:

- `src/allCode/agent/validation_repair.py`
- `src/allCode/agent/tool_call_processor.py`
- `tests/unit/agent/test_validation_repair.py` or existing validation repair tests

Implementation:

1. Extend `ValidationFailureSummary`:

```python
failing_targets: list[RepairTarget] = Field(default_factory=list)
```

2. Add `_extract_repair_targets(lines: list[str]) -> list[RepairTarget]`.

Generic patterns to support:

- Python traceback:
  - `File "src/example.py", line 45`
- path/line messages:
  - `src/example.py:45: SyntaxError`
  - `tests/test_example.py:12`
- pytest failed item:
  - `FAILED tests/test_example.py::test_case`
- JavaScript/TypeScript/Go/Rust style path line markers where possible:
  - `src/app.ts:10:5`
  - `main.go:18`

3. In `ToolCallProcessor._record_validation_failure_symbols()` or a new helper:

- copy `validation_failure.failing_targets` into `CompletionEvidence.validation_failure_targets`;
- keep existing symbol extraction;
- deduplicate by `(file_path, line_number, symbol)`.

Acceptance:

- Validation failure metadata includes typed repair targets.
- Evidence carries repair targets into later rounds.

### P2. Make PhaseToolGate Carry Repair And Missing-Artifact Metadata

Target files:

- `src/allCode/agent/phase_gate.py`
- `tests/unit/agent/test_phase_gate.py`

Extend `PhaseToolGate`:

```python
missing_artifacts: list[str] = Field(default_factory=list)
repair_targets: list[RepairTarget] = Field(default_factory=list)
patch_ambiguous_files: list[str] = Field(default_factory=list)
preferred_next_tools: list[str] = Field(default_factory=list)
```

Rules:

- `test_authoring_required` includes `missing_artifacts=["test"]`.
- `validation_failed` includes `repair_targets=evidence.validation_failure_targets`.
- If any repair target file is in `patch_ambiguous_files`, set:
  - `allowed_tool_names={"read_file", "write_file"}` for repair mutation phase;
  - optionally include `run_tests` only when revalidation is actually allowed;
  - `preferred_next_tools=["read_file", "write_file"]`;
  - exclude `patch_file` until a successful mutation clears ambiguity.
- If no ambiguity is active, keep current inspect/mutation tools.

Acceptance:

- Phase gate output tells the model and logger which artifact/repair target is missing.
- Ambiguous patch state changes available tool schema rather than only adding advisory text.

### P3. Promote Patch Ambiguity To File-Level Strategy State

Target files:

- `src/allCode/agent/tool_orchestrator.py`
- `src/allCode/agent/tool_call_processor.py`
- `tests/unit/agent/test_tool_orchestrator.py`
- `tests/unit/agent/test_tool_call_processor.py`

Implementation:

1. Extend `PatchFailureTracker` with file-level ambiguity:

```python
self._ambiguous_files: set[str] = set()
```

2. In `record_result()`:

- if `patch_file` fails with `patch_ambiguous`, add normalized `file_path` to `_ambiguous_files`;
- if `write_file` or successful `patch_file` mutates that file, clear it;
- still keep current search-hash based repeated-failure protection.

3. In `repeated_failure()`:

- if target file is in `_ambiguous_files`, return `ToolResult(error_type="patch_strategy_required")` immediately;
- metadata should recommend `read_file` with range or `write_file`.

4. In `ToolCallProcessor`, also mirror ambiguity into `completion_evidence.patch_ambiguous_files`.

5. Apply the Aider-inspired patch-to-write fallback policy:

- when a file has active ambiguity, suppress `patch_file` for that file before execution;
- recommend `read_file` with `start_line`/`end_line` if a repair line target exists;
- recommend `write_file` only when the file has already been read in the current repair context or ambiguity repeats after a targeted range read;
- clear ambiguity only after successful `write_file`, successful `patch_file`, or validation success for that file.

Acceptance:

- First ambiguous patch failure changes future behavior for that file.
- A repeated patch on an ambiguous file is suppressed before execution.
- A successful mutation clears the ambiguous state.
- Whole-file rewrite is not requested without current file context.

### P4. Add Dedicated Test-Authoring And Repair Prompts

Target files:

- `src/allCode/agent/prompt_builder.py`
- `tests/unit/agent/test_prompt_builder.py`

Add:

```python
def test_authoring_request(
    self,
    messages: Sequence[Message],
    *,
    missing_artifacts: Sequence[str] = (),
    recent_source_paths: Sequence[str] = (),
) -> list[Message]:
    ...
```

Prompt requirements:

- Say that a required test artifact is missing.
- Instruct the model to call `write_file` or `patch_file`.
- Tell it not to run validation until the test artifact has changed.
- If recent source paths are available, mention them generically as files that should be covered by tests.
- Do not invent scenario-specific test filenames.
- Include a short provider-neutral tool-call reminder: choose one allowed tool and provide arguments that match its schema.

Update `validation_repair_request()` to accept:

```python
repair_targets: Sequence[RepairTarget] = ()
patch_ambiguous_files: Sequence[str] = ()
preferred_next_tools: Sequence[str] = ()
```

Prompt requirements:

- Include detected repair targets with file and optional line.
- If patch ambiguity is active, explicitly say:
  - do not repeat the same patch;
  - use `read_file` with a line range or `write_file`;
  - prefer full rewrite when exact patch search is ambiguous.
- If a phase block occurred, include one compact line with:
  - blocked tool family;
  - blocking reason;
  - required next tool family.
- Include at most three repair targets, three failure symbols, and three ambiguous files.

Acceptance:

- Prompt tests assert the wording includes the missing artifact or repair target.
- No specific benchmark paths or scenario terms appear in source.
- The prompt should include a compact OpenHands-style blocking reason: what was blocked, why it was blocked, and the required next tool family.
- The prompt does not append historical validation logs beyond the latest failure excerpt and parsed metadata.

### P5. Escalate Schema-Denied Actions In RoundRunner

Target files:

- `src/allCode/agent/round_runner.py`
- `tests/unit/agent/test_harness_completion_controls.py`
- possible focused fake-LLM integration test

Current behavior:

- If all results are `schema_denied` in mutation/test/repair phases, `RoundRunner` calls generic `mutation_action_request()`.

New behavior:

1. If `phase_gate.phase == "test_authoring_required"`:

- call `PromptBuilder.test_authoring_request()`;
- keep `mutation_action_pending=True`;
- do not count this as ordinary mutation retry if the model selected `run_tests`.

2. If `phase_gate.phase in {"validation_failed", "repair_mutation_required"}`:

- call `PromptBuilder.validation_repair_request()` with:
  - `completion_evidence.validation_failure_targets`;
  - `completion_evidence.patch_ambiguous_files`;
  - `phase_gate.preferred_next_tools`.

3. If `patch_strategy_required` is returned:

- do not immediately return partial;
- append repair prompt with patch ambiguity context once, then continue.

4. Treat unsatisfied-artifact finalization as a Stop-style block:

- if the model tries to finish while `RequestedArtifact(kind="test")` is unsatisfied, append `test_authoring_request()`;
- if the model tries to finish while validation repair targets exist, append `validation_repair_request()`;
- only return partial after the bounded retry budget is exhausted.

5. Retry budget:

- allow at most two consecutive schema-denied or Stop-style phase blocks for the same phase/reason pair;
- after the budget is exhausted, return a partial result that includes the exact blocked obligation and current evidence state;
- do not reset the budget unless a successful mutation, successful validation, or phase transition occurs.

6. Keep existing generic fallback for other mutation phases.

Acceptance:

- A model that calls `run_tests` during `test_authoring_required` receives a targeted retry that asks for a test artifact.
- A model that repeats ambiguous patching receives a stronger repair prompt and/or loses `patch_file` from allowed tools for that target.
- Consecutive phase-block retries are bounded and observable.

### P6. Make Validation Repair Target Selection Deterministic

Target files:

- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/grounding.py` if target reads are injected there
- `tests/unit/agent`

Implementation:

- If validation failed and repair targets exist, prefer reading the first target range:
  - `start_line=max(1, line_number-20)`
  - `end_line=line_number+20`
- Do not full-file dump large files.
- If the target is already read with relevant range, move to mutation prompt.
- If target file is in `patch_ambiguous_files`, suppress patch and prefer `write_file`.
- Keep the repair context compact:
  - at most three repair targets;
  - at most three failure symbols;
  - at most three ambiguous files;
  - no repeated full validation log unless the model explicitly needs a new range.
- Prefer latest validation output over older logs when selecting targets.
- Use language-neutral target extraction before language-specific heuristics.

Acceptance:

- Repair loop is inspect target -> mutate -> revalidate, not arbitrary repeated reads.

### P7. Regression Tests

Add deterministic tests that do not depend on scenario IDs:

1. `test_validation_repair_extracts_file_line_targets`
   - Input: generic traceback and pytest output.
   - Assert `RepairTarget` file/line extraction.

2. `test_phase_gate_excludes_patch_for_ambiguous_repair_target`
   - Evidence has failed validation target and patch ambiguity for same file.
   - Assert `patch_file` is not allowed and `write_file` is preferred.

3. `test_patch_failure_tracker_blocks_file_after_first_ambiguous_patch`
   - First ambiguous patch result records file.
   - Next patch to same file returns `patch_strategy_required`.

4. `test_round_runner_escalates_test_authoring_schema_denial`
   - Fake model calls `run_tests` while test artifact is missing.
   - Assert next prompt uses test-authoring request and later `write_file` can satisfy artifact.

5. `test_round_runner_repair_prompt_mentions_targets`
   - Failed validation summary includes a target.
   - Assert repair prompt includes that generic target.

6. `test_no_scenario_hardcoding_still_passes`
   - Existing no-hardcoding test must include plan 27-sensitive source files.

7. `test_stop_style_block_for_unsatisfied_artifacts`
   - Fake model returns a final answer before writing tests.
   - Assert the loop converts this into `test_authoring_request()` instead of success.

8. `test_patch_ambiguity_removes_patch_schema_for_target`
   - Evidence has repair target and active ambiguous file.
   - Assert `patch_file` is excluded from the phase gate and `write_file` is preferred.

9. `test_patch_ambiguity_requires_recent_read_before_write`
   - Evidence has an ambiguous target that has not been read in the current repair context.
   - Assert the next preferred tool is range `read_file`, not immediate `write_file`.

10. `test_phase_block_retry_budget_returns_partial_after_limit`
   - Fake model repeats a schema-denied phase action.
   - Assert the loop retries with targeted prompts only within the budget and then returns partial with evidence.

11. `test_repair_context_caps_targets_and_logs`
   - Validation output contains many paths and long logs.
   - Assert prompt context contains only the latest excerpt and at most three targets.

## Applicability Decisions

Adopt now:

- Aider-style patch-to-write fallback after ambiguous search/replace.
- Aider-style validation output as the primary repair input.
- OpenHands-style phase blocking feedback that continues the conversation instead of ending the turn too early.
- Gemini-style compact repair context rather than repeated full logs.
- Qwen-style parser/model-tolerant retry prompts for schema-denied tool choices.

Do not adopt now:

- Aider architect/editor split.
- Git auto-commit or git-native repair workflow.
- General OpenHands external hook/plugin framework.
- New Gemini memory layers or memory import processors.
- Qwen daemon/SDK/provider-specific behavior.

## Implementation Order

1. Core contracts:
   - `RepairTarget`
   - `CompletionEvidence.validation_failure_targets`
   - `CompletionEvidence.patch_ambiguous_files`
2. Failure extraction:
   - `validation_repair.py`
   - `tool_call_processor.py`
3. Patch strategy:
   - `tool_orchestrator.py`
   - `phase_gate.py`
4. Prompt escalation:
   - `prompt_builder.py`
   - `round_runner.py`
5. Deterministic tests.
6. Full regression.
7. Real-model rerun:

```bash
.venv/bin/python output/cross_genre_evaluation.py
```

Targeted rerun:

```bash
CROSS_GENRE_SCENARIOS=CG01,CG05,CG09 .venv/bin/python output/cross_genre_evaluation.py
```

## Expected Outcome

- CG09-style missing-test turns should no longer stall after schema-denied `run_tests`.
- CG01-style ambiguous patch failures should switch to range read or whole-file rewrite.
- CG05-style validation syntax failures should focus repair on extracted failing files/lines.
- Overall real-model average should recover above the Plan 26 result and move toward the prior best `94.8+`.
- Open-source CLI coding-agent parity should move from the current estimated `86%` back toward `89-90%`.

## Remaining Risks

- The model may still ignore structured repair prompts; phase gate must enforce enough tool schema pressure without over-restricting valid repair strategies.
- File/line extraction must be conservative. False repair targets can hurt convergence.
- Whole-file rewrite after ambiguity must be grounded in a current file read to avoid destructive content loss.
- More deterministic repair can increase prompt length; prompt builder should keep target lists compact.
