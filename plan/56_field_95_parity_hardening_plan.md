# 56. Field-Level 95% Parity Hardening Plan

## Purpose

This plan defines the next hardening cycle for bringing allcode closer to 95%
field-level parity with mature CLI coding agents such as Codex, Aider,
Gemini CLI, Qwen Code, OpenHands-style tool observability, and agy.

The goal is not to inflate benchmark scores with prompt-specific exceptions.
The goal is to improve the actual agent data flow: intent framing, route
selection, tool exposure, source exploration, synthesis, validation,
memory carryover, terminal UX, and evidence-grounded general answers.

All runtime validation for this plan must target `.venv/bin/allcode`, not a
globally installed command.

## Current Baseline

Based on the latest comparison and progress documents:

- `plan/45_parity_progress_tracker.md` records an estimated overall parity of
  about `93-94%`, with project generation and validation around `94-95%`.
- `plan/55_runtime_quality_hardening_plan.md` closes several runtime issues:
  dependency guard precision, max-round source fallback, Korean read-only
  precedence, cwd `.env` fallback, and slash-command file artifact detection.
- Remaining quality gaps are concentrated in model-authored answer depth,
  broad source explanation density, current-knowledge web grounding,
  route confidence, interactive approval continuity, and comparison automation.

The 95% target is treated as a field-by-field quality target. It must not be
reported as achieved unless repeated `.venv/bin/allcode` runs show stable
behavior across code analysis, generation, modification, validation, general
answers, multi-turn continuity, tool UX, and TTY interaction.

## Non-Negotiable Constraints

- Do not hardcode benchmark IDs, specific prompt strings, project names, or
  expected answer phrases.
- Do not bypass core contracts from `plan/00` through `plan/12`.
- Keep `core` provider-neutral and UI-neutral.
- Use `CompletionEvidence`, `ToolCall`, `ToolResult`, `AgentEvent`, and
  `TurnResult` instead of redefining equivalents.
- Preserve route-based tool exposure:
  direct answers get no tools, external answers get web evidence tools only,
  inspect routes get non-mutating tools, and modify/operate routes get only
  policy-allowed tools.
- Web search must return evidence bundles. Raw search output must not be
  forwarded as a final answer.
- Read-only requests must never mutate files.
- All terminal behavior changes must go through
  `src/allCode/tui/runtime.py` and the terminal-native runtime path.
- Every implementation phase must re-read this plan before editing, then run
  focused tests before broad regression.

## Open-Source Alignment

This plan maps current allcode gaps to practical patterns used by mature
open-source agents:

- Aider-style repo map: compact symbol-first project maps, target ranking,
  related-test discovery, and edit-focused repair loops.
- Gemini CLI-style hierarchical memory: durable project instructions,
  session summaries, recent targets, and compact carryover.
- Qwen Code-style terminal-first provider-neutral runtime: no provider SDK
  coupling in core and predictable terminal interaction.
- OpenHands-style action/event observability: every tool action has status,
  evidence, logs, and user-visible summaries.
- Codex-style final answer discipline: user language first, concise but
  complete synthesis, tool noise hidden behind useful summaries.

## Field A. Runtime Config, Model Connection, and Diagnostics

### Current Problem

Model connectivity works after `.env` and config correction, but the runtime
still lacks a strong user-facing diagnostic path for which config source was
selected. When the user starts allcode from one directory and points it at a
different workspace, project-local config discovery can be ambiguous.

### Code Locations

- `src/allCode/config/manager.py`
- `src/allCode/config/schema.py`
- `src/allCode/config/defaults.py`
- `src/allCode/llm/adapters/openai_compatible.py`
- `src/allCode/llm/factory.py`
- `src/allCode/runtime.py`
- `src/allCode/telemetry/session_logger.py`
- `src/allCode/telemetry/schema.py`
- Tests: `tests/unit/config`, `tests/unit/llm`, `tests/unit/test_entrypoint.py`

### Improvement Plan

1. Add a redacted config source diagnostic model.
   - Record model name, base URL host/path, selected config file path,
     `.env` source path, whether the API key came from env/config, and CLI
     override presence.
   - Never log raw secrets.

2. Add launch-directory config fallback as a controlled compatibility path.
   - Workspace project config keeps priority.
   - If the selected workspace has no `.allCode/config.yaml` and the launch
     cwd has one, use it as a fallback config source.
   - Emit a `config_source_report` status event so users know why it was used.

3. Strengthen model request metrics.
   - Capture prompt character count, response character count, finish reason,
     retry count, provider latency, and token usage when the endpoint returns
     it.
   - Persist the metrics in session JSONL.

4. Add a safe diagnostic command.
   - Extend existing slash/status command plumbing with a config summary that
     prints only redacted values.
   - Keep it out of core and route it through UI-facing command registry.
   - Add a headless diagnostic flag such as `--diagnose` or `--check` so users
     can verify config/model selection without entering a session.

5. Add redaction regression tests.
   - Unit tests must verify that API keys, bearer tokens, and raw secret
     values never appear in diagnostic status, session logs, or CLI output.

### Expected 95% Effect

Runtime failures become inspectable without leaking secrets. Model connection
problems no longer look like answer-quality problems, and comparisons against
agy become fairer because both agents run against the intended endpoint.

## Field B. Intent Framing, Routing, and Policy

### Current Problem

Routing has improved, but route confidence can still depend too much on
distributed lexical checks. Broad user intent should be represented as a
structured frame before route selection, so direct answers, source inspection,
external knowledge, generation, modification, and operation are separated
without prompt-specific hardcoding.

### Code Locations

- `src/allCode/agent/intent.py`
- `src/allCode/agent/router.py`
- `src/allCode/agent/model_router.py`
- `src/allCode/agent/model_router_schema.py`
- `src/allCode/agent/model_router_signals.py`
- `src/allCode/agent/route_validator.py`
- `src/allCode/agent/prompt_constraint_detection.py`
- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/read_only_guard.py`
- `src/allCode/agent/answer_scope_guard.py`
- Tests: `tests/unit/agent/test_router*.py`,
  `tests/unit/agent/test_route_validator*.py`

### Improvement Plan

1. Introduce an `IntentFrame` normalization layer.
   - Fields: `task_kind`, `scope`, `artifact_need`, `evidence_need`,
     `mutation_allowed`, `validation_need`, `external_freshness_need`,
     `workspace_target_hints`, and `confidence_reasons`.
   - The frame must be generic and evidence-based, not keyed to benchmark
     phrases.
   - This frame must consolidate or wrap existing `IntentSignals` and
     `PromptConstraints`; it must not create a second competing intent parser.

2. Make route validation consume `IntentFrame`.
   - Direct general answers: no tools.
   - Current or externally grounded general answers: web evidence tools only.
   - Source analysis: inspect/source tools only.
   - Modify/generate: mutation tools only after policy and evidence gates.
   - Operate: shell only through approval and destructive-command policy.

3. Add route contradiction detection.
   - Example: read-only request plus mutation route becomes inspect route.
   - Example: external freshness need plus direct-answer route becomes
     external-answer route if web is configured.
   - Contradiction resolution must be deterministic boolean logic over the
     `IntentFrame`, not an expanding list of lexical exceptions.

4. Add decision traces for logs.
   - Persist compact reasons such as `read_only=true`,
     `freshness_need=current`, `workspace_scope=src`, and
     `tools_allowed=inspect`.

### Expected 95% Effect

General questions stop entering unnecessary tool loops, external-knowledge
questions gain web grounding, and read-only source analysis remains safe while
still collecting enough evidence.

## Field C. Broad Source Analysis and Explanation Density

### Current Problem

For prompts such as "explain what the code under src does", allcode often
collects useful tool observations but the final answer can remain closer to an
evidence list than to a high-density architectural explanation. agy-style
answers tend to synthesize role, flow, entry points, major packages, and risk
areas more aggressively.

### Code Locations

- `src/allCode/tools/builtin/source_overview.py`
- `src/allCode/tools/builtin/source_overview_metadata.py`
- `src/allCode/tools/builtin/source_overview_roles.py`
- `src/allCode/tools/builtin/source_probe.py`
- `src/allCode/tools/builtin/source_probe_edges.py`
- `src/allCode/tools/builtin/source_ranking.py`
- `src/allCode/workspace/source_intelligence/service.py`
- `src/allCode/workspace/source_intelligence/python_ast.py`
- `src/allCode/workspace/source_intelligence/tree_sitter_parser.py`
- `src/allCode/agent/source_final_brief.py`
- `src/allCode/agent/source_responsibility_graph.py`
- `src/allCode/agent/source_analysis_rendering.py`
- `src/allCode/agent/source_answer_synthesis.py`
- `src/allCode/agent/source_answer_fallback.py`
- `src/allCode/agent/inspect_summary.py`
- Tests: `tests/unit/tools/test_source_*`,
  `tests/unit/agent/test_source_answer_*`

### Improvement Plan

1. Upgrade broad source analysis to a three-stage map/probe/synthesize flow.
   - Stage 1: `source_overview` creates a package inventory, entrypoint list,
     symbol density map, and likely responsibility clusters.
   - Stage 2: `source_probe` reads representative files per cluster, not only
     top files globally.
   - Stage 3: `source_final_brief` builds a compact model-facing brief with
     module roles, runtime flow, key contracts, and limitations.

2. Add representative probe minimums for broad source questions.
   - For `src` or package-wide analysis, choose representatives dynamically
     from the package/responsibility clusters returned by `source_overview`.
   - Do not require allcode-specific package names such as `agent`, `tools`,
     `memory`, or `tui`; those are valid only when discovered in the target
     repository.
   - Keep full-file dumps forbidden; use AST/tree-sitter summaries and bounded
     excerpts.
   - Enforce a strict per-file token/character budget during AST and symbol
     summary extraction.

3. Strengthen answer synthesis contracts.
   - Final answer must include:
     direct summary, package role table, runtime flow, tool/context/memory
     interaction, important files, and limitations.
   - The answer must be in the user's language.
   - Fallback rendering must use the same report schema instead of a raw
     evidence list.

4. Add source-analysis quality gates.
   - If the model returns `reasoning_only` or a thin answer after rich source
     evidence exists, retry once with a compact critique:
     "turn observations into architecture-level explanation".
   - If retry still fails, deterministic fallback produces a structured
     source report.

### Expected 95% Effect

allcode source analysis becomes closer to agy/Codex: it explains architecture,
responsibilities, and data flow rather than merely listing observed files.

## Field D. Tool Use, Evidence, and User-Facing Observability

### Current Problem

Tool execution is logged, but the interactive display can still feel noisy
when many inspection tools are used. Approval flows have also had continuity
issues in TTY sessions. The agent needs OpenHands-style action/event
observability internally and Codex-style compact summaries externally.

### Code Locations

- `src/allCode/tools/executor.py`
- `src/allCode/tools/executor_evidence.py`
- `src/allCode/tools/approval.py`
- `src/allCode/tools/approval_preview.py`
- `src/allCode/agent/tool_call_processor.py`
- `src/allCode/agent/tool_evidence.py`
- `src/allCode/agent/tool_action_ledger.py`
- `src/allCode/agent/round_tool_handler.py`
- `src/allCode/tui/tool_timeline.py`
- `src/allCode/tui/terminal_activity.py`
- `src/allCode/tui/terminal_answer_renderer.py`
- `src/allCode/telemetry/session_logger.py`
- Tests: `tests/unit/tools`, `tests/tty`

### Improvement Plan

1. Separate internal logs from user-visible tool summaries.
   - JSONL keeps every action, arguments redacted as needed, duration,
     outcome, and evidence IDs.
   - Terminal output shows compact lines such as
     `inspect src -> ok · 100 files · 816 symbols`.

2. Add per-turn `ToolTimeline` condensation.
   - Group repeated reads/searches by target.
   - Fold long outputs by default.
   - Preserve full details in session logs.

3. Harden approval lifecycle.
   - Approval request, preview, user decision, tool execution, and final
     result must be linked by one action ID.
   - The TTY prompt must return to editable input after approval cancellation,
     denial, or execution.
   - The action ID should be a unique transaction UUID generated by approval
     orchestration to prevent async state overlap between concurrent or
     repeated approval flows.

4. Add policy-denied answer synthesis.
   - Denied destructive requests should produce a clear user-facing safety
     explanation and safe alternatives.
   - Do not expose internal policy debug text.

### Expected 95% Effect

Tool use remains transparent but no longer overwhelms the user. Approval
requests become reliable in real terminal sessions.

## Field E. General Knowledge Answers with Web Evidence

### Current Problem

allcode already has a web provider abstraction and `web_search` tool, but the
default backend is disabled and current-knowledge general answers cannot always
retrieve external evidence. To reach 95% parity, the agent needs a practical
web evidence path while preserving provider neutrality and raw-output
isolation.

### Code Locations

- `src/allCode/config/schema.py`
- `src/allCode/config/defaults.py`
- `src/allCode/tools/web_provider.py`
- `src/allCode/tools/web_health.py`
- `src/allCode/tools/builtin/web.py`
- `src/allCode/tools/builtin/__init__.py`
- `src/allCode/runtime.py`
- `src/allCode/agent/route_validator.py`
- `src/allCode/agent/answer_prompt.py`
- `src/allCode/agent/finalization.py`
- Tests: `tests/unit/tools/test_web_*`,
  `tests/unit/agent/test_route_validator*.py`,
  `tests/integration/test_headless_runner.py`

### Improvement Plan

1. Make web evidence routing explicit.
   - Add `external_freshness_need` to intent framing.
   - If a general question depends on current, recent, local-regulation,
     market, product, API, or versioned facts, route to external answer.
   - If no web backend is configured, answer with a clear limitation and ask
     the user to configure web search only when the missing evidence matters.

2. Implement a practical free/local web backend option.
   - Support SearXNG as a first-class backend through config:
     `web.backend=searxng`, `web.search_url`, timeout, max results.
   - Do not hardcode public instance URLs.
   - Preserve existing `http_json` backend for testability and custom
     gateways.

3. Add optional HTTP fetch provider.
   - `web_fetch` should be able to fetch URLs through the configured provider
     when network is allowed.
   - It must strip scripts, styles, markup noise, tracking boilerplate, and
     oversized content before truncating by character/token budget.
   - It must return a citation-ready evidence bundle.
   - It must fail closed with `web_fetch_unavailable` when disabled.
   - It must honor network policy flags such as `ALLCODE_NO_NETWORK` if
     present, plus configured timeout and result limits.

4. Strengthen final answer grounding.
   - Final answers must cite evidence titles/domains or state that web search
     was unavailable.
   - Raw result JSON must never be printed as the answer.
   - The final text must be in the user's language.

### Expected 95% Effect

General knowledge answers remain direct when stable, and gain evidence when
freshness is required. This closes the biggest non-coding answer gap.

## Field F. Project Generation, Modification, and Validation

### Current Problem

Recent generation tests improved, but agy-style quality still tends to be
stronger in dense task decomposition, generated test breadth, and final report
specificity. allcode must make model planning and validation less permissive
without hardcoding prompt cases.

### Code Locations

- `src/allCode/agent/project_planner.py`
- `src/allCode/agent/workflow.py`
- `src/allCode/agent/workflow_editor.py`
- `src/allCode/agent/workflow_actions.py`
- `src/allCode/agent/workflow_completion.py`
- `src/allCode/agent/workflow_repair.py`
- `src/allCode/agent/completion_checker.py`
- `src/allCode/agent/completion_gate.py`
- `src/allCode/agent/validation_runner.py`
- `src/allCode/agent/final_reporter.py`
- `src/allCode/generation/strategies/*.py`
- Tests: `tests/integration/test_generation_workflow.py`,
  `tests/unit/agent/test_completion*`,
  `tests/unit/agent/test_project_planner*`

### Improvement Plan

1. Add a `ProjectPlanQualityGate`.
   - Verify that requested artifacts, commands, tests, docs, and validation
     obligations are represented before generation begins.
   - Reject vague plans and retry once with missing obligations listed.
   - Verify that functions, classes, CLI commands, and public interfaces
     extracted into `api_obligations` are mapped to tests or executable
     validation commands.

2. Require test density by obligation, not by prompt name.
   - If the request exposes CLI behavior, require CLI smoke validation.
   - If public functions/classes are created, require unit tests or documented
     executable smoke checks.
   - If docs are requested, verify command consistency against generated files.

3. Strengthen repair loop targeting.
   - Validation failures should rank targets by traceback/test item,
     changed-file evidence, related tests, then package proximity.
   - Repair must stop after bounded attempts and preserve failure summary in
     final answer if unresolved.
   - Proposed validation commands must execute from the generated or modified
     project root, not from an unrelated launch directory.

4. Improve final reports.
   - Report created/modified files, validation commands, result, repaired
     issues, remaining risks, and how to run the project.
   - Use `CompletionEvidence` as the source of truth.

### Expected 95% Effect

Generation work becomes more comparable to mature agents because allcode stops
accepting under-specified model plans and produces denser validation-backed
deliverables.

## Field G. Multi-Turn Context, Memory, and Repair Carryover

### Current Problem

Session memory supports summaries, recent targets, and project obligations,
but long multi-turn work can still lose active obligations or previous
validation failures if they are not injected early enough in the next turn.

### Code Locations

- `src/allCode/memory/project_obligations.py`
- `src/allCode/memory/session_state_store.py`
- `src/allCode/memory/session_summary.py`
- `src/allCode/memory/recent_targets.py`
- `src/allCode/memory/selector.py`
- `src/allCode/agent/context_factory.py`
- `src/allCode/agent/context_session_sections.py`
- `src/allCode/agent/context_condensation.py`
- `src/allCode/agent/loop_obligations.py`
- `src/allCode/agent/session_state.py`
- Tests: `tests/unit/memory`,
  `tests/integration/test_followup_context_memory.py`

### Improvement Plan

1. Persist an active project state section in the existing session snapshot.
   - Track requested artifacts, generated files, tests, latest validation
     command, unresolved failures, recent edit targets, and source-analysis
     ledger entries.
   - Prefer extending the existing `SessionStateSnapshot` and memory store
     schema over adding a disconnected state class.

2. Inject compact carryover before route selection.
   - Repair context should include at most one command, three targets, three
     symbols, and one failure excerpt.
   - Failure excerpt storage should stay below a strict budget, approximately
     500 tokens or an equivalent character cap.
   - The injection must be earlier than normal route-context construction so
     routing sees unresolved obligations.

3. Add staleness and redaction.
   - Carryover should expire or downgrade when the workspace target changes.
   - Secrets must be redacted before memory writes.

4. Add multi-turn quality tests.
   - Generation -> test addition -> validation repair.
   - Source analysis -> follow-up "that function/file" references.
   - General Q&A -> summary follow-up without tool loops.

### Expected 95% Effect

allcode maintains project continuity across turns like Gemini-style
hierarchical memory while avoiding context bloat.

## Field H. Terminal UX, Input, Approval, and Markdown Streaming

### Current Problem

The terminal-native UI is closer to Codex than the earlier Textual default,
but real TTY quality still depends on reliable input restoration, Korean text
entry, approval interaction, markdown block flushing, and concise status.

### Code Locations

- `src/allCode/tui/runtime.py`
- `src/allCode/tui/terminal.py`
- `src/allCode/tui/terminal_input.py`
- `src/allCode/tui/terminal_text_area.py`
- `src/allCode/tui/terminal_bottom_pane.py`
- `src/allCode/tui/terminal_answer_renderer.py`
- `src/allCode/tui/terminal_activity.py`
- `src/allCode/tui/terminal_markdown.py` if added, otherwise
  `src/allCode/tui/markdown.py`
- `src/allCode/tui/markdown_stream_state.py`
- `src/allCode/tui/tool_timeline.py`
- `src/allCode/tui/approval_panel.py`
- Tests: `tests/tty`

### Improvement Plan

1. Add a TTY composer state regression suite.
   - Normal Korean input, pasted Korean text, bracketed paste, multi-line edit,
     Ctrl-C recovery, and approval cancel/deny/accept.
   - Include IME-like multi-byte cursor movement and paste cases so Korean
     text is not corrupted by terminal editing operations.

2. Harden markdown streaming.
   - Buffer tables until structurally complete.
   - Stream fenced code blocks line-by-line with incremental formatting rather
     than waiting for the closing fence.
   - Stream prose by sentence or paragraph, not per character.
   - Keep final rendered transcript scrollable through terminal-native output.

3. Make status lines Codex-style.
   - Show current phase, compact tool action, retry/recovery message, and
     final-answer gate status.
   - Hide internal reasoning/debug fields.

4. Keep prompt input fixed and everything else terminal-scrollable.
   - Only the input composer stays anchored.
   - Transcript should behave like normal terminal output.

### Expected 95% Effect

The interactive path becomes reliable enough for real use and no longer masks
agent-quality improvements behind UI friction.

## Field I. Final Answer Quality and Language Alignment

### Current Problem

When model output is thin, reasoning-only, or fallback-driven, allcode can
produce answers that are technically grounded but less polished than agy. Final
answer quality needs route-specific contracts and lightweight critique/retry.

### Code Locations

- `src/allCode/agent/finalization.py`
- `src/allCode/agent/finalization_helpers.py`
- `src/allCode/agent/final_answer_format.py`
- `src/allCode/agent/final_answer_context.py`
- `src/allCode/agent/answer_prompt.py`
- `src/allCode/agent/language.py`
- `src/allCode/agent/source_answer_synthesis.py`
- `src/allCode/agent/source_answer_fallback.py`
- `src/allCode/agent/final_reporter.py`
- Tests: `tests/unit/agent/test_final*`,
  `tests/unit/agent/test_language*`,
  `tests/quality`

### Improvement Plan

1. Define route-specific final answer contracts.
   - Direct answer: concise user-language answer first.
   - External answer: answer plus cited evidence and freshness note.
   - Source analysis: architecture summary, package roles, flows,
     limitations.
   - Modify/generate: files changed, validation, result, risks.

2. Add an `AnswerQualityGate`.
   - Reject empty, reasoning-only, raw-observation-only, wrong-language,
     or missing-required-section answers.
   - Retry once with compact critique and the same evidence.
   - Fall back to deterministic structured renderer only when the model still
     fails.

3. Add user-language preservation.
   - Detect Korean/English/mixed language once per turn.
   - Inject the language requirement into final synthesis prompts.
   - Validate final output language at a coarse heuristic level.
   - Strip markdown fenced code blocks and code identifiers before
     Hangul/English density checks so code-heavy answers do not skew language
     detection.

4. Reduce fallback visibility.
   - Fallback should sound like a normal final answer, not an internal failure
     report, while still disclosing evidence limitations when relevant.
   - Deterministic fallback renderers must use the same response schema as
     model-authored route-specific answers.

### Expected 95% Effect

The same tool evidence results in answers that feel closer to agy/Codex rather
than implementation traces.

## Field J. Quality Evaluation and Progress Tracking

### Current Problem

Unit tests are strong, but real quality comparisons against agy and
`.venv/bin/allcode` need a stable, repeatable rubric. Manual estimates have
shifted because fields were not separated consistently.

### Code Locations

- `tests/quality`
- `tests/tty`
- `src/allCode/telemetry/session_analyzer.py`
- `review/`
- `docs/parity_progress.md`
- `plan/45_parity_progress_tracker.md`
- New/updated plan tracker after each comparison cycle.

### Improvement Plan

1. Create a comparison matrix.
   - Prompt categories: broad source analysis, focused bug fix, project
     generation, validation repair, general stable Q&A, current-knowledge Q&A,
     multi-turn project, multi-turn general discussion, TTY approval.

2. Score by field, not only overall impression.
   - Routing precision
   - Tool efficiency
   - Evidence use
   - Answer density
   - Validation correctness
   - Memory continuity
   - UX stability
   - Safety compliance

3. Persist progress after each run.
   - Update a progress document whenever tests change the estimate.
   - Record model, endpoint, config source, command path
     `.venv/bin/allcode`, and agy command used.

4. Add a session-log based parity evaluator.
   - Add an evaluation helper such as `tests/quality/evaluate_parity.py`.
   - Aggregate JSONL metrics for API calls, token usage when available, tool
     run counts, approval decisions, route changes, retries, and errors.

5. Keep generated evaluation artifacts isolated.
   - Use `output/` or `review/` for comparison outputs.
   - Do not commit bulky runtime logs unless intentionally summarized.

### Expected 95% Effect

Progress claims become traceable and less dependent on a single manual run.

## Implementation Order

### Phase 1. Measurement and Diagnostics Foundation

Fields: A, J

1. Add config source diagnostics and model metrics.
2. Add comparison-matrix scaffolding and progress update format.
3. Verify with config, LLM, telemetry, and entrypoint tests.

Exit criteria:

- `.venv/bin/allcode` reports redacted config source information.
- Session logs contain latency and token/character metrics when available.
- Progress estimates can be updated per field.

### Phase 2. Routing and Web Evidence

Fields: B, E

1. Add `IntentFrame`.
2. Route current/external general answers to web evidence tools.
3. Add SearXNG backend configuration and web unavailability handling.
4. Verify with route validator and web tool tests.

Exit criteria:

- Stable knowledge questions can answer directly.
- Fresh/current questions use web evidence when configured.
- Disabled web backend produces a useful limitation instead of raw failure.

### Phase 3. Source Analysis Depth

Fields: C, I

1. Upgrade map/probe/synthesize flow.
2. Add source-analysis answer contract and quality gate.
3. Improve deterministic fallback report schema.
4. Verify with broad source-analysis tests and `.venv/bin/allcode` TTY prompt.

Exit criteria:

- Broad `src` analysis includes roles, flow, evidence, and limitations.
- The final answer is model-authored when possible and structured fallback
  only when needed.

### Phase 4. Generation, Validation, and Repair

Fields: F, G

1. Add project plan quality gate.
2. Strengthen obligation-based test/validation requirements.
3. Persist active project state and repair carryover.
4. Verify with generation workflow and multi-turn memory tests.

Exit criteria:

- Generated projects include adequate tests and validation commands.
- Failed validation context is available in the next turn.

### Phase 5. Tool UX and Terminal Reliability

Fields: D, H

1. Add tool timeline condensation.
2. Harden approval lifecycle.
3. Expand TTY composer and markdown streaming regression tests.
4. Verify with real PTY smoke and `tests/tty`.

Exit criteria:

- Tool use is compact in the transcript and detailed in JSONL.
- Approval prompts do not break input.
- Korean input and markdown streaming behave reliably.

### Phase 6. Cross-Field Parity Review

Fields: all

1. Run the same prompt categories against `.venv/bin/allcode` and agy.
2. Score field-level parity.
3. Update the progress tracker.
4. If any field remains below 95%, create the next focused plan from the
   failing code path and repeat.

Exit criteria:

- The average field score reaches at least 95%.
- No individual critical field is below 93%.
- Remaining differences are documented as model/provider limitations or
  explicit post-MVP scope.

## Validation Commands

Focused tests by phase:

```bash
python -m pytest tests/unit/config tests/unit/llm tests/unit/test_entrypoint.py
python -m pytest tests/unit/agent tests/unit/tools
python -m pytest tests/unit/workspace tests/unit/memory tests/unit/agent/test_context_builder.py
python -m pytest tests/integration/test_generation_workflow.py tests/integration/test_followup_context_memory.py
python -m pytest tests/tty tests/quality
```

Full regression:

```bash
python -m pytest
```

Runtime checks must use:

```bash
.venv/bin/allcode
```

## Agy Review Process

This plan must be reviewed in two passes:

1. Field-by-field review:
   - Share each field's problem, code locations, and proposed improvement.
   - Accept feedback that improves data flow, correctness, or testability.
   - Reject feedback that introduces prompt-specific hardcoding or post-MVP
     expansion.

2. Final integrated review:
   - Share the revised full plan.
   - Apply only feedback consistent with `plan/00` through `plan/12` and the
     no-meaningless-hardcoding rule.

## Plan Acceptance Checklist

- Every field has code-level target locations.
- General knowledge web evidence is included.
- Tool use remains route- and policy-bound.
- Source analysis depth improves through map/probe/synthesis, not full dumps.
- Final answers are language-aligned and evidence-grounded.
- Multi-turn context carries obligations and repair context.
- TTY approval and input reliability are explicitly tested.
- Progress tracking is per field and tied to `.venv/bin/allcode`.

## Agy Review Outcome

The plan was reviewed by agy in two passes.

Field-by-field feedback accepted into this document:

- Add redacted config diagnostics and regression tests.
- Consolidate intent parsing through `IntentFrame` instead of adding another
  competing parser.
- Remove allcode-specific package names from broad source-analysis probe
  requirements and use dynamic responsibility clusters.
- Link approval request, decision, and result by a unique transaction UUID.
- Sanitize fetched web content before truncation and honor network policy.
- Map `api_obligations` to tests or executable validation commands.
- Extend the existing session snapshot for active project state instead of
  adding disconnected memory state.
- Stream fenced code blocks incrementally while buffering tables only.
- Strip code blocks before final-answer language-density checks.
- Add a JSONL-backed parity evaluator for objective progress tracking.

Final integrated review result:

- No remaining hardcoding pattern was found in the plan.
- Web evidence routing and raw-output isolation were judged consistent with
  MVP constraints.
- Code-level targets and phase ordering were judged realistic.
- The remaining operational risk is SearXNG or other web backend availability;
  this is intentionally handled through explicit config and unavailable-state
  fallbacks rather than hardcoded public endpoints.
