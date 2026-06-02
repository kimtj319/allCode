# 25. Cross-Genre Evaluation Hardening Plan

## Purpose

This plan turns the 20-scenario cross-genre evaluation and agy read-only discussion into an implementation plan. It extends the existing allCode MVP contracts without changing the core philosophy:

- routing remains model-owned, with deterministic safety constraints only;
- core stays provider-neutral and UI-neutral;
- file mutation remains tool/evidence based;
- completion for implementation work remains gated by `CompletionEvidence`;
- fixes must not hardcode scenario IDs, specific prompts, or project names.

Relevant prior contracts:

- `plan/00_master_implementation_guide.md`
- `plan/01_open_source_alignment_contracts.md`
- `plan/04_llm_loop_plan.md`
- `plan/05_routing_policy_plan.md`
- `plan/06_tool_system_plan.md`
- `plan/08_context_memory_plan.md`
- `plan/11_quality_testing_plan.md`
- `plan/12_mvp_execution_plan.md`
- `plan/20_harness_agent_open_source_completion_plan.md`
- `plan/23_open_source_parity_90_discussion_plan.md`
- `plan/24_open_source_cli_agent_90_plus_plan.md`

## Evaluation Baseline

The real-model run used `wisenut/wise-lloa-max-v1.2.1` and isolated all artifacts under `output/cross_genre`.

| Archetype | Pass | Warning | Fail | Average Score | Average Model Rounds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Type 1: single-turn light project | 2 | 1 | 1 | 92.5 | 4.8 |
| Type 2: single-turn complex project | 2 | 1 | 1 | 92.5 | 5.2 |
| Type 3: multi-turn complex project | 0 | 2 | 2 | 75.8 | 20.2 |
| Type 4: single-turn general Q&A | 4 | 0 | 0 | 100.0 | 1.0 |
| Type 5: multi-turn general Q&A | 3 | 1 | 0 | 96.8 | 2.8 |

Key conclusion: direct-answer Q&A is strong, while multi-turn project mutation and validation repair are still the main gap against mature CLI coding agents.

## Failure Taxonomy

### F1. Conversational Follow-Up Misrouted As File Mutation

Observed in CG17 turn 2. A debate/refutation follow-up was blocked with `target_clarification_required`, even though no file mutation was requested.

Primary components:

- `src/allCode/agent/model_router.py`
- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/preflight.py`
- `src/allCode/agent/session_state.py`

Root cause:

- deterministic mutation keyword extraction can override the model's answer route;
- `_answer_followup_request` is too narrow for debate, critique, refutation, synthesis, and blog-style continuation requests;
- `PreflightPlanner._needs_target_clarification` can return true for a follow-up reference even when the final route is not an actual modify route.

### F2. Tool Budget Blocks Repair-Time Inspection

Observed in CG09 and CG12. The loop repeatedly suppressed `read_file` with `tool_budget_exceeded` while validation or patch repair required re-inspection.

Primary components:

- `src/allCode/agent/tool_orchestrator.py`
- `src/allCode/agent/tool_call_processor.py`
- `src/allCode/agent/session_state.py`
- `src/allCode/agent/round_runner.py`

Root cause:

- `ToolBudgetTracker(read_limit=1, search_limit=1)` is too strict for multi-turn repair;
- the budget key ignores `start_line`, `end_line`, and `max_bytes`, so range reads are treated like full repeated reads;
- budgets are cleared only after successful mutation, not after failed mutation attempts;
- budget lifetime spans too much session context for iterative repair.

### F3. Patch Failure Has Insufficient Error Semantics

Observed in CG01 and CG09. `patch_file` failed with duplicate search matches, but the next model round did not reliably switch to range read or whole-file rewrite.

Primary components:

- `src/allCode/tools/builtin/file_ops.py`
- `src/allCode/tools/executor.py`
- `src/allCode/agent/recovery.py`
- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/validation_repair.py`

Root cause:

- ambiguous patch search and missing patch search both surface as generic `ValueError`;
- match count, target path, and next recommended action are not standardized in `ToolResult.metadata`;
- the repair prompt cannot distinguish "patch text not found" from "patch text matched multiple regions".

### F4. Validation Repair State Machine Allows Bad Transitions

Observed in CG01, CG05, CG09, and CG12. Syntax errors were detected, but the loop sometimes injected validation too early, denied repair inspection, or reached max rounds.

Primary components:

- `src/allCode/agent/validation_controller.py`
- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/validation_repair.py`
- `src/allCode/tools/builtin/shell.py`

Root cause:

- failed validation should transition to inspect-failure-target -> mutate -> revalidate;
- a new `run_tests` call should be blocked if no successful or attempted mutation occurred after the last validation failure;
- repair inspection is sometimes blocked by mutation-only phase gates;
- test artifact detection misses some valid test paths such as `test.py`, `tests.py`, and non-Python test directories.

### F5. Document Follow-Up Target Is Less Durable Than Project Manifest

Observed in CG10 and CG11. Document updates generally succeeded, but section coverage and target continuity showed warnings.

Primary components:

- `src/allCode/core/result.py`
- `src/allCode/memory/session_store.py`
- `src/allCode/agent/context_builder.py`
- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/finalization.py`

Root cause:

- code project generation has `ProjectManifest`, but business/creative document generation lacks an equivalent durable target record;
- follow-up prompts like "앞 문서", "방금 만든 기획서", "시리즈 바이블" rely on recent file targets rather than a document-specific manifest;
- stale not-found/search fallback wording can survive after later successful file creation or mutation.

### F6. Quality Harness Is Too Brittle For Cross-Genre Evaluation

Observed in CG04, CG08, CG10, CG11, and CG17. Some warnings were real coverage issues, but some were caused by exact keyword or exact tool-name matching.

Primary components:

- `output/cross_genre_evaluation.py`
- `tests/helpers/quality.py`
- `tests/quality`

Root cause:

- expected terms do not support synonym groups or localized variants;
- expected tool checks should use capability families, not only exact tool names;
- round thresholds should scale with prompt count and scenario complexity;
- connectivity failures should be separated from model/agent quality failures.

## Detailed Implementation Plan

### P0. Fix General Q&A Follow-Up Routing

Target files:

- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/model_router.py`
- `src/allCode/agent/preflight.py`
- `tests/unit/agent/test_model_router.py`
- `tests/unit/agent/test_preflight.py`
- `tests/integration/test_followup_context_memory.py`

Implementation:

1. Extend `PromptConstraints` with a generic conversational follow-up signal such as:
   - `answer_followup_hint`
   - `argumentation_followup_hint`
   - `format_conversion_followup_hint`
2. Detect this signal using reusable intent categories, not scenario text:
   - debate/refute/counterargument/rebuttal
   - critique/revise the argument
   - summarize previous answer/conversation
   - turn into blog/report/script
   - compare the previously mentioned options
3. In `ModelRouter._merge_constraints`, calculate `answer_followup` before mutation override.
4. If `answer_followup` is true and there is no explicit path or filename target, force:
   - `kind="answer"`
   - `tool_capabilities=set()`
   - `workflow_hint="none"`
   - `target_hint=None`
   - `requires_mutation=False`
5. Keep file mutation valid when the user names a path or durable document/code target.
6. In `PreflightPlanner._needs_target_clarification`, only request target clarification when:
   - `routing.kind == "modify"`
   - `routing.requires_mutation is True`
   - no explicit target exists
   - the prompt is a follow-up reference to an artifact, not a conversational answer
7. Add regression tests for:
   - "방금 제시한 요인을 반박하고 재반박해줘" -> answer, no tools
   - "방금 만든 보고서에 리스크 섹션을 추가해줘" with recent document target -> modify
   - "그 파일을 수정해줘" without recent target -> clarification

Acceptance:

- Type 5 general Q&A keeps 0 mutation tools.
- CG17-like prompts no longer produce `target_clarification_required`.

### P1. Add Durable Document Manifest For Non-Code Artifacts

Target files:

- `src/allCode/core/result.py`
- `src/allCode/agent/session_state.py`
- `src/allCode/agent/context_builder.py`
- `src/allCode/agent/prompt_builder.py`
- `src/allCode/memory/session_store.py`
- `src/allCode/agent/finalization.py`
- `tests/unit/memory`
- `tests/unit/agent/test_context_builder.py`
- `tests/integration/test_followup_context_memory.py`

Implementation:

1. Add a focused `DocumentManifest` model, separate from `ProjectManifest`:
   - `path`
   - `title`
   - `artifact_kind`
   - `section_headings`
   - `last_requested_changes`
   - `updated_at_turn_id`
2. Add `document_manifest: DocumentManifest | None` to `CompletionEvidence`.
3. Populate it after successful `write_file` or `patch_file` for markdown/text planning artifacts.
4. Store the latest document manifest in session state and memory summary.
5. Teach context selection to resolve follow-ups such as:
   - "앞 문서"
   - "방금 만든 문서"
   - "기획서"
   - "시리즈 바이블"
   - "보고서"
6. In `PromptBuilder`, include the current document manifest as compact context instead of dumping full document contents.
7. In `finalization.py`, remove stale not-found wording when the final evidence has successful changed or created document targets.

Acceptance:

- Multi-turn document scenarios modify the intended file without repeated search loops.
- Final answer lists the document path and requested sections without stale "not found" wording.

### P2. Make Tool Budget Turn-Scoped And Repair-Aware

Target files:

- `src/allCode/agent/tool_orchestrator.py`
- `src/allCode/agent/tool_call_processor.py`
- `src/allCode/agent/session_state.py`
- `src/allCode/agent/round_runner.py`
- `tests/unit/agent/test_tool_orchestrator.py`
- `tests/unit/agent/test_tool_call_processor.py`

Implementation:

1. Raise default observation limits:
   - `read_limit=3`
   - `search_limit=3`
2. Add `reset_for_turn(turn_id: str)` or instantiate a fresh budget tracker per user turn while preserving observation cache separately.
3. Update `_budget_key`:
   - include `file_path`, `start_line`, `end_line`, `max_bytes` for `read_file`;
   - include `path` and depth-like arguments for `list_directory`;
   - include normalized query and context parameters for `search_files`.
4. Change `reset_for_mutation` into `reset_for_mutation_attempt`:
   - clear global or target-level read/search budget after any `write_file`, `patch_file`, or `delete_path` attempt;
   - include failed mutation attempts, because repair requires fresh inspection.
5. Add metadata to suppressed results:
   - `recommended_next_action`
   - `existing_observation_available`
   - `allowed_range_read_hint`
6. In `RoundRunner`, reset budget at each new turn and after validation failure repair starts.

Acceptance:

- Repair loops can read the failure target after patch or validation failure.
- Duplicate infinite loops are still suppressed after 3 equivalent reads/searches.

### P3. Standardize Patch Failure Observations

Target files:

- `src/allCode/tools/builtin/file_ops.py`
- `src/allCode/tools/executor.py`
- `src/allCode/core/models.py`
- `src/allCode/agent/recovery.py`
- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/validation_repair.py`
- `tests/unit/tools/test_file_ops.py`
- `tests/unit/agent/test_recovery.py`

Implementation:

1. Introduce structured patch failure error types:
   - `patch_not_found`
   - `patch_ambiguous`
   - `patch_invalid_request`
2. Return metadata:
   - `file_path`
   - `match_count`
   - `search_preview`
   - `recommended_next_tools`: `["read_file", "patch_file"]` or `["read_file", "write_file"]`
   - `must_not_repeat_same_patch`: true
3. In `PatchFileTool._apply_patches`, raise or return a typed internal error object instead of plain `ValueError`.
4. In `ToolResult` handling, preserve the typed error and metadata for prompt construction.
5. In recovery prompt text, tell the model:
   - ambiguous match -> read the relevant range, then use a more specific patch or whole-file rewrite;
   - not found -> read current file before retrying;
   - never repeat the same failed patch unchanged.

Acceptance:

- Patch duplicate-match failures no longer loop on the same patch string.
- Validation repair has enough context to guide exact next action.

### P4. Harden Validation Repair State Transitions

Target files:

- `src/allCode/agent/validation_controller.py`
- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/validation_repair.py`
- `src/allCode/agent/validation_runner.py`
- `tests/unit/agent/test_validation_controller.py`
- `tests/unit/agent/test_phase_gate.py`
- `tests/integration/test_generation_workflow.py`
- `tests/integration/test_agent_loop_context_validation.py`

Implementation:

1. Extend `ValidationRepairController` state with:
   - `last_validation_failure_hash`
   - `mutation_attempted_since_validation`
   - `mutation_succeeded_since_validation`
   - `failure_target_paths`
   - `repair_attempt_count`
2. Use this transition graph:
   - `validation_failed` -> allow `read_file`, `search_files`, `patch_file`, `write_file`
   - after inspection, remain `repair_mutation_required`
   - after mutation attempt, switch to `revalidation_required`
   - after passing validation, allow final answer
   - after max repair attempts, return partial with validation evidence
3. Block `run_tests` when there has been no mutation attempt after the last failed validation.
4. Do not inject deterministic validation while `repair_mutation_required` is active.
5. Keep inspection tools available during validation repair, even if ordinary mutation phase would hide them.
6. Improve `looks_like_test_artifact`:
   - accept `test.py`
   - accept `tests.py`
   - accept files under `test/`, `tests/`, `__tests__/`
   - accept language variants such as `.test.js`, `.spec.ts`, `_test.go`
7. Add a fallback validation command only when the workspace has no explicit command:
   - Python: `python -m pytest -q`, then `python -m unittest discover`
   - JavaScript: package script if present
   - otherwise report validation unavailable without pretending success

Acceptance:

- Validation-required implementation requests cannot finish as success without passing validation.
- Syntax errors are followed by inspection and mutation before revalidation.
- Multi-turn project scenarios do not hit max rounds due to repeated validation or denied reads.

### P5. Improve Prompt Builder For Cross-Genre Structure

Target files:

- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/context_builder.py`
- `src/allCode/agent/final_reporter.py`
- `tests/unit/agent/test_prompt_builder.py`
- `tests/integration/test_generation_workflow.py`

Implementation:

1. Add compact genre-neutral output requirements when a document artifact is requested:
   - preserve requested sections;
   - use headings for each required section;
   - if a requested item cannot be satisfied, state the gap explicitly.
2. Keep this generic. Do not encode scenario labels, expected terms, or exact prompts.
3. For implementation requests, keep skeleton -> implementation -> tests -> validation -> repair.
4. For non-code document generation, avoid unnecessary validation commands but still require changed/created file evidence when a file output is requested.
5. For multi-turn answer-only sessions, summarize prior user/assistant turns into logic slots:
   - claim
   - counterargument
   - rebuttal
   - requested output format

Acceptance:

- Type 2 and Type 3 business/content documents include requested sections more reliably.
- General Q&A follow-ups preserve prior claims and requested final format.

### P6. Make Quality Harness Less Brittle And More Diagnostic

Target files:

- `output/cross_genre_evaluation.py`
- `tests/helpers/quality.py`
- `tests/quality`

Implementation:

1. Support expected term groups:
   - each required concept may include synonyms and localized variants;
   - pass if at least one term in the group appears.
2. Evaluate tool families:
   - mutation family: `write_file`, `patch_file`, `delete_path`
   - validation family: `run_tests`
   - inspection family: `read_file`, `search_files`, `list_directory`
   - external family: `web_search`, `fetch_url`
3. Scale round thresholds:
   - single-turn light project: <= 6 preferred, <= 9 warning
   - single-turn complex project: <= 10 preferred, <= 12 warning
   - multi-turn project: <= `8 * turn_count` preferred, <= `10 * turn_count` warning
   - Q&A: <= `turn_count + 1`
4. Separate these failure types:
   - connectivity/model endpoint failure
   - routing failure
   - tool execution failure
   - validation failure
   - final answer quality failure
5. Add report fields for:
   - first failing turn
   - phase at failure
   - repeated tool signatures
   - validation failure symbols
   - stale finalization wording

Acceptance:

- The harness reports actionable failures without rewarding brittle prompt-specific behavior.
- Warnings reflect real missing structure, not only synonym mismatch.

## Implementation Order

1. P0 routing/preflight fix
2. P2 tool budget reset and range-aware keys
3. P3 patch failure error semantics
4. P4 validation repair transition hardening
5. P1 document manifest and follow-up target memory
6. P5 prompt/context structure improvements
7. P6 quality harness diagnostics

This order addresses the high-severity failures first while minimizing broad architectural churn.

## Verification Plan

Run the smallest relevant tests first:

```bash
python -m pytest tests/unit/agent/test_model_router.py tests/unit/agent/test_preflight.py
python -m pytest tests/unit/agent/test_tool_orchestrator.py tests/unit/agent/test_tool_call_processor.py
python -m pytest tests/unit/tools/test_file_ops.py
python -m pytest tests/unit/agent/test_validation_controller.py tests/unit/agent/test_phase_gate.py
python -m pytest tests/unit/agent tests/unit/tools
python -m pytest tests/integration/test_followup_context_memory.py tests/integration/test_generation_workflow.py tests/integration/test_agent_loop_context_validation.py
python -m pytest tests/quality
python -m pytest
```

Then run the real-model cross-genre suite outside the sandbox:

```bash
.venv/bin/python output/cross_genre_evaluation.py
```

## Target Outcomes

After implementation, the target metrics are:

- Type 4 general Q&A remains 100% pass with no mutation tools.
- Type 5 multi-turn Q&A reaches 100% pass or only quality warnings, with no target-clarification false positives.
- Type 3 multi-turn project reaches at least 3 pass and 1 warning, with zero fail.
- Overall average score reaches at least 96.
- Average Type 3 model rounds drops below 14.
- No implementation source references scenario IDs, specific generated project names, or exact dataset prompts.

## Risks

- Increasing read/search budget can reintroduce tool loops if target signatures are not normalized well.
- DocumentManifest must not become a second project-generation system; it should only preserve document target and section context.
- More permissive conversational follow-up detection must not hide tools for real artifact mutation requests.
- Structured patch errors require tests across both builtin tools and executor-level patch behavior.
- The cross-genre harness is under `output/`; if promoted to permanent test infrastructure later, it should be moved into `tests/quality` with stable fixtures.
