# 28. Open-Source Warning Reduction Plan

## Purpose

This plan follows `plan/27_validation_repair_convergence_plan.md` and the
latest real-model cross-genre regression:

- `CG05`: pass, 100.0
- `CG09`: warning, 78.0
- remaining warnings: near max-round behavior, high logical tool action count,
  and missing feature/objective wording in the final answer.

The goal is not to add new post-MVP features. The goal is to reduce avoidable
rounds and improve final answer grounding while preserving the current
provider-neutral loop, phase gates, and `CompletionEvidence` contracts.

## Non-Negotiable Constraints

- Do not match scenario IDs, exact prompts, project names, benchmark terms, or
  model names.
- Do not branch on `wisenut/wise-lloa-max-v1.2.1` or any provider-specific
  behavior.
- Do not append synthetic "expected terms" to pass a test. Any final-answer
  objective wording must come from generic prompt-derived obligations and actual
  file-change/validation evidence.
- Do not relax success gates. Validation-required work still cannot succeed
  without `validation_passed=True`.
- Keep changes inside current contracts: parser recovery, phase gating,
  session obligations, and final-answer policy.

## Open-Source Patterns Applied

### Aider: edit-format fallback and test-fix loop

Aider documents multiple edit formats. Search/replace and unified diff formats
are efficient, while whole-file edits are simpler but costlier. For allCode this
maps to `patch_file` first, then `read_file`/`write_file` fallback when patching
becomes ambiguous. Aider also emphasizes running tests and using failures as
repair input.

Applied direction:

- remove arbitrary parser repair limits that fail on larger patch payloads;
- once a patch target is ambiguous, prefer target reads and `write_file` rather
  than broad search/list loops;
- keep validation output as the repair source.

### OpenHands: action/observation blocking hooks

OpenHands exposes lifecycle hooks such as `PreToolUse` and `Stop`; blocking
feedback prevents unsafe or incomplete actions while surfacing a reason back to
the conversation.

Applied direction:

- treat phase gates as internal blocking hooks;
- if a tool is blocked in a phase, feed a concrete next-tool family back to the
  model;
- keep the block retry budget bounded so the agent does not burn max rounds.

### Gemini CLI: hierarchical context and inspectable memory

Gemini CLI loads layered `GEMINI.md` context and exposes memory inspection and
refresh commands. allCode already has `ALLCODE.md` and session obligations.

Applied direction:

- reuse compact session obligations rather than dumping full files/logs;
- track prompt-derived project objectives as session state;
- include those objectives in final-answer grounding without hardcoding terms.

### Qwen Code: provider-neutral terminal agent configuration

Qwen Code is terminal-first and provider-configurable through OpenAI-compatible
model providers and session commands such as `/compress` and `/summary`.

Applied direction:

- keep parser/tool adaptation provider-neutral;
- improve last-mile native tool argument repair instead of adding model-specific
  branches;
- preserve compact summaries to control token/round growth.

## Implementation Plan

### P1. Parser last-mile tool argument repair

Target files:

- `src/allCode/llm/tool_argument_repair.py`
- `src/allCode/llm/response_parser.py`
- `tests/unit/llm/test_tool_argument_repair.py`
- `tests/unit/llm/test_response_parser.py`

Changes:

1. Replace the hard `.{0,400}?` patch search/replace extraction limit with
   ordered key scanning so larger patch payloads can be recovered.
2. On stream completion, if a supported tool argument buffer is non-empty but
   incomplete, try `ToolArgumentRepairer.repair()` before returning
   `malformed_tool_call`.
3. Only recover tool names with explicit repair handlers (`write_file`,
   `patch_file`, `run_tests`). Unknown tools must remain malformed.

Tests:

- large `patch_file` search/replace gap is repaired;
- incomplete final `write_file` JSON is recovered at stream end;
- unknown incomplete tool JSON still returns `malformed_tool_call`.

### P2. Phase target locking and retry tightening

Target files:

- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/tool_call_processor.py`
- `tests/unit/agent/test_phase_gate.py`
- `tests/unit/agent/test_harness_completion_controls.py`

Changes:

1. When `test_authoring_required` has known target paths, keep mutation tools
   exposed and block mutation attempts against unrelated files.
2. When validation repair has concrete targets, keep broad directory/search
   tools hidden unless no target exists.
3. Keep the existing bounded retry behavior, but make phase-denied observations
   specific enough to prevent repeated broad exploration.

Tests:

- known test target blocks unrelated source mutation;
- targeted validation repair does not expose `list_directory`;
- broad search remains available only when there is no repair target.

### P3. Prompt-derived feature objective summaries

Target files:

- `src/allCode/core/result.py`
- `src/allCode/memory/project_obligations.py`
- `src/allCode/agent/session_state.py`
- `src/allCode/agent/loop.py`
- `src/allCode/agent/finalization.py`
- `tests/unit/agent/test_finalization_policy.py`
- `tests/unit/memory/test_project_obligations.py`

Changes:

1. Add `CompletionEvidence.feature_objectives: list[str]`.
2. Extract compact objectives from user prompts using generic structural
   signals:
   - backticked terms and paths are ignored for feature wording unless they are
     plain non-path symbols;
   - English identifiers longer than three characters;
   - Korean noun-like terms around action markers such as add/create/implement,
     `추가`, `구현`, `연동`, `보강`, `검증`.
3. Store deduplicated objectives in `ActiveProjectObligations`.
4. When final evidence exists, append a short "핵심 기능" / "Feature summary"
   block if the final answer omits tracked objectives.
5. Do not append feature summaries for failed turns with no file-change or
   validation evidence.

Tests:

- objectives are extracted generically and stored in obligations;
- final answer policy appends missing tracked objectives only when there is
  change or validation evidence;
- no summary is appended for read-only or failed/no-evidence answers.

### P4. Feature-obligation continuity and evidence-derived public symbols

Target files:

- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/phase_block.py`
- `src/allCode/agent/session_state.py`
- `src/allCode/agent/tool_evidence.py`
- `tests/unit/agent/test_prompt_builder.py`
- `tests/unit/agent/test_tool_evidence.py`
- `tests/unit/agent/test_session_state.py`

Changes:

1. Treat prompt-derived feature objectives as implementation obligations, not
   benchmark keywords. Initial prompts and test-authoring repair prompts should
   remind the model to implement visible behavior/API and tests for active
   objectives.
2. Preserve feature objectives from partial or failed turns in session state
   and merge them with later turns instead of replacing them with the latest
   test-only evidence.
3. Add compact pending-feature context to active project obligations after a
   partial/failed mutation turn, so follow-up test requests cannot silently
   forget unfinished feature work.
4. Extract public Python class/function symbols from successful mutation diffs
   and add them to `CompletionEvidence.feature_objectives`. This is
   evidence-derived and must not scan absolute paths, scenario IDs, or expected
   benchmark terms.

Tests:

- current-turn objectives are visible in initial model instructions;
- test-authoring retries mention active objectives;
- partial-turn objectives remain in session obligations;
- public symbols from mutation diffs are added to completion evidence without
  path noise.

## Verification

Run in order:

```bash
.venv/bin/python -m pytest tests/unit/llm tests/unit/agent tests/unit/memory tests/unit/tools
.venv/bin/python -m pytest tests/integration/test_agent_loop_context_validation.py::test_agent_loop_blocks_validation_required_success_without_passing_validation tests/integration/test_generation_workflow.py
env CROSS_GENRE_SCENARIOS=CG05,CG09 .venv/bin/python output/cross_genre_evaluation.py
```

Success expectation:

- unit/integration tests pass;
- real-model stress has no fail;
- CG09 may remain warning if the model still emits poor edits, but warning
  causes should move from hard failures to efficiency-only diagnostics.
