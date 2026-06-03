# 26. Remaining Open-Source Parity Hardening Plan

## Purpose

This plan closes the remaining gaps after `plan/25_cross_genre_evaluation_hardening_plan.md`.
It is based on:

- current code inspection of `src/allCode/agent`, `src/allCode/core`, and `src/allCode/tools`;
- the latest real-model cross-genre result: `13 pass / 4 warning / 3 fail`, average score `94.8`;
- read-only `agy` feedback on phase gates, validation repair, patch loops, and completion evidence;
- the implementation contracts in `plan/00` through `plan/12`.

The goal is to move allCode from the current estimated **87%** open-source CLI coding-agent parity toward **90%+** without expanding MVP scope or hardcoding benchmark-specific behavior.

## Non-Negotiable Constraint: No Meaningless Hardcoding

Do not fix failures by matching scenario IDs, exact prompts, specific project names, specific generated paths, or expected benchmark terms.

Forbidden examples:

- checking for `CG09`, `CG05`, or other evaluation IDs;
- special-casing `game/rpg.py`, `mini_api`, or any benchmark workspace name;
- matching one Korean prompt sentence literally to force a route;
- injecting expected evaluation keywords into final answers;
- adding model-specific branches for `wisenut/wise-lloa-max-v1.2.1`.

Allowed generic signals:

- path-like target extraction;
- language-agnostic test artifact detection;
- prompt intent categories such as "tests requested", "validation requested", "repair requested";
- structured `ToolResult.error_type` and metadata;
- `CompletionEvidence` checklist items derived from the current prompt and observed tool results;
- route policy, phase gate, and validation state transitions that are independent of benchmark data.

## Current Findings

### F1. Test-Requested Implementation Turns Are Not Checklist-Driven

Current code:

- `src/allCode/agent/phase_gate.py`
  - `_prompt_requests_tests()` detects many English/Korean test requests.
  - `looks_like_test_artifact()` already recognizes `tests/`, `test.py`, `tests.py`, `test_*`, `_test.py`, `_test.go`, `.test.*`, and `.spec.*`.
  - `test_artifact_required()` only checks whether any changed/created path looks like a test artifact.
- `src/allCode/core/result.py`
  - `CompletionEvidence` tracks changed files, validation, project manifest, and document manifest.
  - It does not track requested artifact obligations such as "source file required", "test file required", "validation required".
- `src/allCode/agent/round_runner.py`
  - Blocks final answers when `more_mutation_before_validation` is true.
  - Still cannot express that source and test artifacts are both required before first validation.

Impact:

- Multi-turn project prompts that request code and tests together can create implementation files first, run validation too early, and carry degraded context into later turns.

### F2. Validation Repair State Does Not Explicitly Track Mutation Since Last Failed Validation

Current code:

- `src/allCode/agent/validation_controller.py`
  - Receives `mutation_since_last_validation` in `RoundStateSnapshot`.
  - Does not currently use that field as a hard guard.
- `src/allCode/agent/round_runner.py`
  - Uses local booleans such as `validation_repair_pending`, `mutation_action_pending`, and `awaiting_revalidation_after_mutation`.
  - This works for many cases but is less clear than an explicit failed-validation -> repair-mutation -> revalidation state transition.

Impact:

- The loop can spend too many rounds near validation boundaries.
- In successful cases, validation repair can still converge late and trigger near-max-round warnings.

### F3. Patch Failure Strategy Is Structured But Not Yet Stateful

Current code:

- `src/allCode/tools/builtin/file_ops.py`
  - Provides structured patch errors such as `patch_ambiguous`, `patch_not_found`, and `patch_invalid_request`.
- `src/allCode/tools/executor.py`
  - Preserves those error types and metadata in `ToolResult`.
- `src/allCode/agent/prompt_builder.py`
  - Adds generic blocked-turn wording for patch errors.
- `src/allCode/agent/round_runner.py`
  - Does not maintain a per-target patch-failure memory that forces a strategy switch after repeated patch errors.

Impact:

- The model can retry similar patch attempts on the same target instead of switching earlier to range read or whole-file rewrite.

### F4. Completion Evidence Does Not Represent Requested Artifact Coverage

Current code:

- `CompletionEvidence.has_resolution_evidence()` is file-change or safe-noop based.
- `TurnResult` success validation checks file-change and validation evidence, but not prompt-derived artifact obligations.

Impact:

- The final gate can prove "something changed", but it cannot prove "the requested source/test/document artifacts were all covered".

### F5. Evaluation Harness Gives Diagnostics But Should Drive Stable Regression Tests

Current code:

- `output/cross_genre_evaluation.py` has improved diagnostics.
- `tests/quality` has generic family/synonym scoring.
- The cross-genre harness is still under `output/`, so it is useful for real-model runs but not a stable committed regression fixture.

Impact:

- Remaining failures are visible, but not all reduced to deterministic unit/integration tests.

## agy Read-Only Feedback Summary

agy independently recommended:

1. Strengthen test artifact detection and final-answer blocking for prompts that request tests.
2. Track whether mutation happened after the last validation failure before allowing `run_tests`.
3. Use structured patch metadata to push the model toward ranged reads or whole-file rewrites after ambiguous/not-found patches.
4. Add an artifact checklist to `CompletionEvidence` and update it from successful tool results.
5. Keep all fixes generic through path heuristics, semantic intent categories, file existence checks, and structured tool metadata.

Code inspection confirms item 1 is partially implemented already, so the next work should focus on checklist-driven phase gating rather than duplicating existing path suffix checks.

## Implementation Plan

### P0. Add Requested Artifact Checklist Contracts

Target files:

- `src/allCode/core/result.py`
- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/round_runner.py`
- `src/allCode/tools/executor.py`
- `tests/unit/core/test_result.py`
- `tests/unit/agent/test_phase_gate.py`
- `tests/unit/agent/test_round_runner.py` or focused existing round tests

Data model:

Add a small typed checklist model instead of a loose dict:

```python
class RequestedArtifact(CoreModel):
    kind: Literal["source", "test", "document", "validation"]
    target: str = ""
    satisfied: bool = False
    evidence_paths: list[str] = Field(default_factory=list)
    reason: str = ""
```

Add to `CompletionEvidence`:

```python
requested_artifacts: list[RequestedArtifact] = Field(default_factory=list)
```

Rules:

- Initialize source/test/document/validation obligations from generic prompt features:
  - explicit paths and filenames;
  - "tests requested" signal from `_prompt_requests_tests()`;
  - document artifact extensions and document-generation route signals;
  - `routing.requires_validation`.
- Do not infer exact benchmark paths when no path is named.
- If tests are requested without explicit test path, create a generic `kind="test"` checklist item with empty target and satisfy it with any changed/created test artifact.
- If validation is required, satisfy `kind="validation"` only when `validation_passed is True`.

Acceptance:

- A file-change turn cannot report full success if prompt-derived required artifacts remain unsatisfied.
- The checklist is derived from prompt structure and route state, not hardcoded examples.

### P1. Make Test-First Phase Gate Checklist-Aware

Target files:

- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/validation_controller.py`
- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/prompt_builder.py`
- `tests/unit/agent/test_phase_gate.py`
- `tests/unit/agent/test_validation_controller.py`

Implementation:

1. Replace `test_artifact_required(prompt, evidence, workspace_root=...)` as the sole condition with:
   - prompt test signal;
   - unsatisfied `RequestedArtifact(kind="test")`;
   - current evidence changed/created path scan as a fallback.
2. Add a phase gate state such as `artifact_authoring_required` or extend `test_authoring_required` with metadata:
   - `missing_artifact_kinds`;
   - `required_next_action`;
   - `allowed_tool_names={read_file, search_files, list_directory, patch_file, write_file}`.
3. Update mutation recovery prompt wording:
   - "When tests are requested, write or update a relevant test artifact before validation."
   - "Do not run validation until required source/test artifacts are present."
4. Keep the final-answer block in `RoundRunner` for `more_mutation_before_validation`, but calculate it from checklist status.

Acceptance:

- A prompt requesting implementation plus tests should create/update both source and test artifacts before first validation.
- Existing read-only/direct-answer routes must not receive checklist mutation gates.

### P2. Add Explicit Failed-Validation Repair State

Target files:

- `src/allCode/agent/round_state.py`
- `src/allCode/agent/validation_controller.py`
- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/tool_call_processor.py`
- `tests/unit/agent/test_validation_controller.py`
- `tests/unit/agent/test_agent_loop_context_validation.py` or integration equivalent

Implementation:

1. Extend `RoundStateSnapshot` or add a focused repair tracker with:
   - `last_validation_failed: bool`;
   - `mutation_attempted_after_failed_validation: bool`;
   - `mutation_succeeded_after_failed_validation: bool`;
   - `last_validation_failure_symbols: list[str]`.
2. In `ToolCallProcessor` or `RoundRunner`, mark mutation attempted after any `write_file`, `patch_file`, or `delete_path` result, regardless of success.
3. In `ValidationRepairController.decide()`:
   - if validation failed and no mutation attempt happened afterward, expose only inspect/mutation tools;
   - block/invalidate `run_tests` as a phase-inappropriate action;
   - allow revalidation only after mutation attempt or successful mutation, depending on the failure type.
4. Do not inject validation near max rounds while the controller says `repair_mutation_required`.

Acceptance:

- Repeated `run_tests` without intervening mutation is blocked deterministically.
- Failed validation proceeds through inspect -> mutate -> revalidate.
- Near-max-round fallback does not waste a validation round while repair mutation is still pending.

### P3. Add Patch Failure Strategy Memory

Target files:

- `src/allCode/agent/session_state.py`
- `src/allCode/agent/tool_call_processor.py`
- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/recovery.py`
- `tests/unit/agent/test_tool_call_processor.py`
- `tests/unit/agent/test_prompt_builder.py`
- `tests/unit/tools/test_file_ops.py`

Implementation:

1. Track patch failures by `(file_path, error_type, normalized_search_hash)` for the current turn.
2. On first `patch_ambiguous`:
   - keep `read_file` with range allowed;
   - prompt for a narrower range read or full rewrite.
3. On repeated `patch_ambiguous` for the same target/search:
   - suppress repeating the same patch;
   - recommend `write_file` or a patch based on a newly read range.
4. On `patch_not_found`:
   - require a fresh read of the target before another patch attempt with the same search text.
5. Use structured metadata, not prompt text, to trigger this behavior.

Acceptance:

- The same patch search block is not retried indefinitely.
- The next model instruction names generic alternatives: range read, more specific patch, or whole-file rewrite.

### P4. Make Finalization Checklist-Grounded

Target files:

- `src/allCode/agent/turn_completion.py`
- `src/allCode/agent/completion_gate.py`
- `src/allCode/agent/finalization.py`
- `src/allCode/agent/final_reporter.py` if still used by workflow path
- `tests/unit/agent/test_completion_gate.py`
- `tests/unit/core/test_result.py`

Implementation:

1. Merge checklist state in `build_completion_evidence()`.
2. Mark checklist items as satisfied by:
   - changed/created/deleted file evidence;
   - document manifest evidence;
   - project manifest test paths;
   - passed validation.
3. In `finalize_completion()`:
   - if a mutation/implementation route has unsatisfied required artifacts, downgrade success to partial/failed;
   - include missing artifact kinds in `error_message`;
   - keep `final_answer_ready=False` for true success until required artifacts are satisfied.
4. In finalization wording:
   - report missing artifacts as remaining work;
   - do not claim tests were added or validation passed unless evidence says so.

Acceptance:

- Success is impossible when required source/test/validation checklist items remain unsatisfied.
- Partial reports are useful and name missing artifact categories without overfitting to a scenario.

### P5. Stabilize Real-Model Regression Into Deterministic Tests

Target files:

- `tests/unit/agent`
- `tests/unit/tools`
- `tests/integration`
- `tests/quality`
- optionally promote selected `output/cross_genre_evaluation.py` logic into committed test helpers

Implementation:

1. Add unit tests for checklist initialization and satisfaction.
2. Add validation-controller tests for failed-validation repair state transitions.
3. Add patch strategy tests for repeated `patch_ambiguous` and `patch_not_found`.
4. Add a fake-LLM integration test that reproduces the generic shape of "implementation + tests requested":
   - first model tries only source write;
   - loop prompts for test artifact;
   - second model writes tests;
   - validation runs only after test artifact exists.
5. Keep scenario IDs and exact benchmark prompts out of committed tests. Use generic English/Korean prompts only to test intent categories.

Acceptance:

- The remaining cross-genre failure classes are covered by deterministic tests.
- Real-model evaluation becomes a smoke/quality layer, not the only guard.

## Recommended Implementation Order

1. **P0 RequestedArtifact model and checklist helpers**
   - This gives the rest of the changes a stable contract.
2. **P1 checklist-aware phase gate**
   - Prevents early validation and final answers when tests are requested.
3. **P2 explicit validation repair state**
   - Reduces wasted rounds after failed validation.
4. **P3 patch failure strategy memory**
   - Reduces repeated target loops and improves repair convergence.
5. **P4 finalization checklist gate**
   - Prevents unsupported success claims.
6. **P5 deterministic regression tests**
   - Locks behavior before rerunning real-model matrix.

## Validation Plan

Run focused tests first:

```bash
.venv/bin/python -m pytest tests/unit/core tests/unit/agent/test_phase_gate.py tests/unit/agent/test_validation_controller.py tests/unit/tools/test_file_ops.py
```

Then broaden:

```bash
.venv/bin/python -m pytest tests/unit/agent tests/unit/tools
.venv/bin/python -m pytest tests/integration tests/quality
.venv/bin/python -m pytest
```

If network/model access is available outside the sandbox, rerun the prior real-model matrix:

```bash
.venv/bin/python output/cross_genre_evaluation.py
```

For targeted confirmation of the remaining failure classes:

```bash
CROSS_GENRE_SCENARIOS=CG05,CG09 .venv/bin/python output/cross_genre_evaluation.py
```

## Expected Outcome

Expected improvement after implementation:

- CG05-style cases should stay success/warning but reduce round count.
- CG09-style implementation-plus-tests turns should no longer fail because tests were omitted before validation.
- Type 3 multi-turn project average should improve from the current `85.8` range toward `90+`.
- Overall open-source CLI coding-agent parity estimate should move from **87%** to **90%+** if real-model behavior follows the deterministic gates.

## Remaining Risk After This Plan

- Model capability variance can still affect how quickly the agent chooses a correct patch or test design.
- Checklist extraction must remain conservative. Over-aggressive inferred artifacts can block valid simple modifications.
- Whole-file rewrite fallback must preserve existing file content and avoid destructive rewrites unless the model has enough current file context.
- Cross-provider validation is still needed to separate agent pipeline issues from one endpoint's tool-calling quality.
