# 41. Answer Quality, Intent Routing, and Loop Context Hardening Plan

## 0. Scope

This plan focuses on making allCode produce a useful model-authored answer for
the user's actual request. It does not implement the fallback router work; that
is explicitly deferred.

The scope is limited to five requested areas:

1. Increase explanation density for source-code analysis.
2. Improve intent routing without meaningless hardcoding.
3. For implementation work, maintain a plan and repeat a compact task brief on
   every model loop.
4. Compress user request, observations, and decision summaries in the style of
   mature CLI agents, without exposing raw hidden reasoning.
5. For general questions, answer directly when stable knowledge is sufficient;
   otherwise use web evidence and synthesize a final answer.

## 1. Non-Negotiable Constraints

- Do not route by exact test prompt, scenario ID, project name, benchmark phrase,
  or fixed user string.
- Do not treat broad Korean words such as "작성", "추가", "설명", "정리",
  "답변" as mutation intent by themselves.
- Do not expose or persist raw hidden chain-of-thought. Store only compact,
  observable decision summaries, tool observations, task obligations, and
  validation state.
- Do not bind provider SDKs into `core`.
- Do not make `prompt_builder.py` a new giant file. New prompt contracts and
  synthesis templates should live in focused modules.
- Do not expand into post-MVP features such as plugin marketplaces, swarm agents,
  cloud sandbox, or git auto-commit.

## 2. Current-Code Findings

### 2.1 Routing Contradiction

`src/allCode/agent/model_router.py` currently asks the model for a JSON route and
then `_merge_constraints()` mutates fields in a long sequence of conditionals.
The result can be internally inconsistent: a model can say the request is a
plain direct answer in `reason`, while the merged route still exposes
`mutate_file` and becomes `kind="modify"`.

Required fix: add a post-merge route consistency validator, not a new fallback
router.

### 2.2 Feature Objective Pollution

`src/allCode/agent/prompt_builder.py` calls
`feature_objectives_from_prompt(turn_input.user_prompt)` for every route. On
general-answer routes this can turn words from answer-format instructions into
implementation obligations. This was visible in previous comparison logs where
answer-language words became active feature objectives.

Required fix: only inject feature-objective obligations for mutation/generation
routes, or when the route validator confirms implementation work.

### 2.3 Source Analysis Is Evidence-Rich But Answer-Light

The inspect flow has `source_overview`, `source_probe`, inspect staging, and
source intelligence. However, final answers can still become a shallow package
list because the model is not given a strict synthesis contract that converts
observations into:

- package responsibilities,
- representative files,
- entrypoint/runtime flow,
- cross-module dependencies,
- observed facts,
- inferred roles,
- coverage gaps.

Required fix: add a dedicated source-analysis synthesis contract and evidence
brief instead of relying on generic final-answer prompting.

### 2.4 Implementation Loops Forget Obligations

`RoundRunner` and `GenerationWorkflow` have validation, repair, phase gates, and
active project obligations. They do not yet have a single compact per-round task
brief that restates the original request, accepted plan, completed artifacts,
remaining obligations, and latest validation status before every model call.

Required fix: add a `TaskLoopDigest` / `LoopBrief` layer that is regenerated from
observable state each round.

### 2.5 General Questions Can Be Over-Tooled

For direct questions, allCode should not list directories, read files, or create
documents unless the user asks for workspace evidence or implementation. Current
behavior can still expose tools when the model route JSON is inconsistent or
when broad mutation terms are over-weighted.

Required fix: direct-answer and external-answer routes need strict tool exposure
invariants.

## 3. Open-Source Design References

- Aider repo map: Aider sends a concise map with important files, symbols,
  signatures, and selected critical lines; it ranks relevant portions under a
  token budget instead of dumping entire files. Reference:
  https://aider.chat/docs/repomap.html
- Aider ask/code/architect modes: Aider separates codebase discussion from code
  editing; ask mode answers without changing files, architect mode separates
  planning from edit execution. Reference:
  https://aider.chat/docs/usage/modes.html
- Gemini CLI hierarchical context: Gemini CLI loads global and project
  `GEMINI.md` context hierarchically and supports memory commands, making
  durable instructions explicit rather than repeated ad hoc in every prompt.
  Reference:
  https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- OpenHands agent architecture: OpenHands models the loop as LLM query, response
  parsing, action execution, and observations in an event-driven architecture.
  Reference:
  https://docs.openhands.dev/sdk/arch/agent
- OpenHands condenser: OpenHands compresses long histories with thresholded
  condensers, preserving critical information while reducing context size.
  Reference:
  https://docs.openhands.dev/sdk/arch/condenser
- Qwen Code provider-neutrality: Qwen Code documents OpenAI-compatible providers
  and multi-provider setup, reinforcing that route/prompt/tool logic should stay
  provider-neutral. Reference:
  https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/model-providers.md

## 4. AGY Review Summary

AGY was asked to review each item without editing files. Four review calls
returned useful design feedback. One review call for context compression
attempted to proceed into code editing despite the review-only instruction; that
process was stopped and its generated code was removed. Only the design feedback
below is incorporated.

### 4.1 Source Analysis Density

AGY agreed that source-analysis answers should be driven by a structured
evidence brief, not by generic summary instructions. It recommended:

- stronger final synthesis sections for observed facts, inferred flows, and
  unobserved targets,
- signature-map context instead of recent full-file dumps,
- representative target scoring that favors orchestrator and dependency wiring
  files,
- final answer text that explicitly reports coverage gaps.

### 4.2 Intent Routing

AGY recommended a route consistency layer after model JSON parsing:

- `answer` must not expose file/shell/mutation tools,
- read-only requests must never retain mutation, deletion, shell, or validation
  capability,
- model route contradictions must be repaired or rejected through structured
  invariants,
- broad Korean words must be treated as weak signals unless combined with
  structured targets, imperative edit intent, or artifact obligations.

### 4.3 Implementation Loop Brief

AGY recommended a dedicated loop brief model that contains:

- original goal summary,
- completed steps and changed files,
- remaining objectives and missing artifacts,
- validation status and latest failure excerpt,
- next required action.

This must be injected as a transient model message before each round, while the
runtime transcript remains available for logging and evidence.

### 4.4 Context Compression

AGY recommended a rolling context strategy similar to OpenHands/Gemini, but the
actual implementation must be carefully designed in allCode rather than patched
in ad hoc:

- keep system and current-turn messages verbatim,
- preserve recent observations,
- summarize middle/old turns into explicit decision summaries,
- strip raw hidden reasoning,
- keep user constraints and task obligations high priority.

### 4.5 General Question Behavior

AGY recommended:

- stable general knowledge routes should be `answer` with no tools,
- current/latest/external evidence routes should be `answer` with only web
  capabilities,
- local workspace tools must not be exposed for external questions,
- web-unavailable cases should produce a natural final answer explaining the web
  backend state.

## 5. Target Architecture

### 5.1 New Module: `agent/route_validator.py`

Purpose: validate and repair model routes after `_merge_constraints()` without
using hardcoded prompt strings.

Inputs:

- `ModelRoutingDecision`
- `PromptConstraints`
- merged `RoutingDecision`
- derived structured signals:
  - has workspace target,
  - has explicit mutation command,
  - has project generation hint,
  - read-only requested,
  - no-shell/no-network requested,
  - external knowledge required,
  - answer follow-up,
  - local workspace evidence requested.

Core invariants:

- `kind == "answer"`:
  - no `read_file`, `search_workspace`, `mutate_file`, `delete_file`,
    `run_shell`, or `run_validation`,
  - web capability allowed only when `requires_external_knowledge` is true,
  - `workflow_hint` must be `none`, `direct_answer`, or `external_research`.
- `read_only_requested`:
  - remove mutation, deletion, shell, validation,
  - allow `inspect` only when workspace evidence is structurally required.
- mutation:
  - requires explicit mutation intent or project generation hint,
  - requires target path, artifact obligation, or generation workflow hint,
  - broad lexical terms alone are insufficient.
- external knowledge:
  - with no local workspace target, use answer + web-only tools,
  - never expose workspace mutation tools.
- workflow hint:
  - `multi_file_generation` requires project generation/artifact signals,
  - existing concrete file paths should prefer `direct_file_edit`.

Outputs:

- normalized `RoutingDecision`,
- `RouteValidationReport` with applied repairs and reasons for logging/tests.

Integration:

- Call from `ModelRouter._merge_constraints()` just before return.
- Keep `_safe_fallback()` unchanged except for reusing the same validator when
  fallback work resumes later.

Tests:

- model says `modify` but reason/tool intent is direct answer -> normalized to
  answer with no tools,
- Korean explanatory prompt with "정리/설명/답변" -> answer or inspect depending
  only on workspace evidence,
- read-only source analysis -> inspect with read/search only,
- general latest/current question -> answer + web only,
- implementation prompt with artifact output path -> modify + generation hint.

### 5.2 New Module: `agent/source_analysis_synthesis.py`

Purpose: transform inspect observations into a dense final-answer contract.

Data model:

```python
class SourceAnalysisBrief(CoreModel):
    requested_scope: str
    observed_paths: list[str]
    representative_files: list[RepresentativeFile]
    package_roles: list[PackageRole]
    entrypoints: list[SourceFact]
    cross_module_edges: list[SourceEdge]
    inferred_flows: list[str]
    unobserved_scopes: list[str]
    confidence_notes: list[str]
```

Rules:

- Use `source_overview`, `source_probe`, and bounded `read_file` evidence.
- Prefer signatures, imports, public classes/functions, and orchestration files.
- Do not dump full files.
- Separate observed facts from inference.
- If coverage is partial, state it as a limitation rather than hallucinating.

Integration:

- `RoundRunner` inspect-finalization path should request a final answer with a
  rendered `SourceAnalysisBrief`.
- `PromptBuilder.inspect_stage_request()` should be shortened and moved toward
  this structured synthesis contract.
- `inspect_summary.py` should provide a deterministic backup summary only when
  the model fails to produce a usable final answer.

Answer shape:

- "확인한 범위"
- "디렉터리/패키지별 역할"
- "핵심 실행 흐름"
- "모듈 간 연결"
- "주요 파일별 근거"
- "관찰하지 못한 범위와 한계"

Tests:

- fake `source_overview` + `source_probe` observations produce package roles and
  cross-module edges,
- source analysis of `src/allCode` includes `agent`, `tools`, `llm`, `core`,
  `workspace`, `memory`, `tui` when observed,
- final answer does not claim full coverage when inventory is truncated.

### 5.3 New Module: `agent/task_loop_digest.py`

Purpose: provide a compact task state to every implementation loop round.

Data model:

```python
class TaskLoopDigest(CoreModel):
    user_goal: str
    route_kind: str
    accepted_plan: list[str]
    completed_artifacts: list[str]
    changed_files: list[str]
    created_files: list[str]
    remaining_obligations: list[str]
    validation_status: Literal["not_required", "pending", "failed", "passed"]
    last_failure_excerpt: str | None
    next_required_action: str
```

Builder inputs:

- original user prompt,
- `RoutingDecision`,
- `CompletionEvidence`,
- `RecoveryState`,
- `ActiveProjectObligations`,
- latest tool observations,
- latest validation result.

Integration:

- `RoundRunner.run_rounds()` builds the digest at the start of each round and
  passes a transient digest message to the model request.
- `GenerationWorkflow` injects the same digest into skeleton, implementation,
  test, validation, and repair steps.
- `CompletionChecker` uses remaining obligations and `CompletionEvidence` to
  block premature final answers.

Important: the digest is not raw reasoning. It is a compact operational state
derived from observable events and evidence.

Tests:

- second implementation round still includes original user constraints,
- model tries final answer with missing files -> gate rejects and digest asks for
  the missing artifact,
- validation failure excerpt survives into repair round,
- digest redacts secrets before injection/logging.

### 5.4 New Module: `agent/context_condensation.py`

Purpose: implement commercial-agent-style context compression as a focused,
testable component. Do not patch this directly into `RoundRunner` until tests
are in place.

Context priority order:

1. system/developer contract summaries,
2. current user request,
3. active task digest,
4. latest repair context,
5. latest validation failure,
6. recent tool observations,
7. recent assistant final answer summaries,
8. durable memory and project instructions,
9. older condensed event summaries.

Compression policy:

- keep first system messages and current turn verbatim,
- keep last N actionable events verbatim,
- summarize middle events into a `CondensedContext` object,
- preserve constraints, decisions, artifacts, failures, and open questions,
- strip raw hidden reasoning markers and provider-specific reasoning fields,
- truncate large tool outputs to headers, file paths, status, and relevant error
  excerpts.

Integration:

- `ContextBuilder` contributes hierarchical memory sections.
- `RoundRunner` applies condensation only to the outgoing model view, not to the
  stored event/session log.
- `SessionStore` persists compact summaries, not raw secrets.

Tests:

- long multi-turn session keeps the first user constraints,
- old tool output is summarized but recent validation error remains verbatim,
- memory import boundaries remain valid,
- no raw token/API key is persisted.

### 5.5 New Module: `agent/answer_policy.py`

Purpose: decide whether an answer route should use no tools or web-only tools.

Structured signals:

- stable conceptual question,
- latest/current/recent/version-sensitive question,
- explicit web/search request,
- no-network constraint,
- local workspace target,
- user requested code/file mutation.

Rules:

- stable knowledge + no workspace evidence -> direct answer, no tools.
- current/latest/external evidence -> answer route with web-only tools.
- if web is unavailable -> final answer states the search limitation and answers
  from available context only if safe.
- local source analysis -> inspect, not web.
- implementation -> modify/generation, not answer.

Integration:

- `ModelRouter` uses the policy after model route validation.
- `PromptBuilder` imports a compact `answer_route_instruction()` from a focused
  module rather than embedding long instructions inline.
- `ToolPolicy` should already enforce answer/web-only if route is correct; add
  tests to lock that contract.

Tests:

- RSA/quantum/general philosophy answer -> no tool call,
- "2026 latest ..." -> web only,
- "현재 디렉터리의 src ..." -> inspect read-only, no web,
- "output에 프로젝트 구현" -> modify/generation, not answer,
- web unavailable -> natural final answer, no raw tool JSON.

## 6. Implementation Phases

### Phase 1: Route Consistency and Direct Answer Protection

Files:

- add `src/allCode/agent/route_validator.py`
- modify `src/allCode/agent/model_router.py`
- modify `src/allCode/agent/prompt_builder.py` only to avoid feature objective
  injection on non-mutation routes
- add/extend `tests/unit/agent/test_route_validator.py`
- extend `tests/unit/agent/test_model_router.py`
- extend `tests/unit/agent/test_policy.py`

Exit criteria:

- direct-answer routes expose no tools,
- external-answer routes expose only web,
- read-only routes never expose mutation/shell/validation,
- implementation routes still reach mutation/generation when structural targets
  or artifact obligations exist.

### Phase 2: Dense Source Analysis Finalization

Files:

- add `src/allCode/agent/source_analysis_synthesis.py`
- adjust `src/allCode/agent/inspect_staging.py` representative target scoring
- adjust `src/allCode/agent/inspect_summary.py` deterministic backup summary
- lightly adjust `PromptBuilder.inspect_stage_request()`
- add/extend read-only source-analysis tests

Exit criteria:

- source-analysis answers contain role, flow, evidence, and limitation sections,
- final answers are grounded in observed paths,
- no full-file dump is required.

### Phase 3: Implementation Loop Digest

Files:

- add `src/allCode/agent/task_loop_digest.py`
- modify `src/allCode/agent/round_runner.py`
- modify `src/allCode/agent/workflow.py`
- modify `src/allCode/agent/completion_checker.py` only if required to consume
  digest obligations
- add `tests/unit/agent/test_task_loop_digest.py`
- add integration regression for implementation prompt misrouting/no-file output

Exit criteria:

- every implementation model call includes compact user goal, plan state,
  completed artifacts, remaining obligations, and validation state,
- no final success without changed/created files for implementation work.

### Phase 4: Hierarchical Context Condensation

Files:

- add `src/allCode/agent/context_condensation.py` or
  `src/allCode/memory/condenser.py` after tests are written first,
- modify `ContextBuilder` and `RoundRunner` through a narrow outgoing-view API,
- add memory/context condensation tests.

Exit criteria:

- long sessions preserve constraints and active obligations,
- old tool output is compressed,
- recent repair and validation evidence remain visible,
- raw hidden reasoning is not persisted or sent as a reasoning transcript.

### Phase 5: General Answer and Web Synthesis

Files:

- add `src/allCode/agent/answer_policy.py`
- add `src/allCode/agent/answer_prompt.py`
- adjust `PromptBuilder._routing_instruction()` to delegate answer wording
- adjust web evidence finalization if raw search output can leak
- add direct/web answer tests.

Exit criteria:

- stable questions get a direct natural answer,
- current/latest questions use web-only evidence,
- unavailable web backend is reported clearly,
- no workspace mutation is attempted for general questions.

### Phase 6: Actual Prompt Matrix

Run the same observed comparison prompts after unit/integration tests:

1. `현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다`
2. `./output` target project implementation prompt with multiple loops.
3. General knowledge question in Korean.
4. Current/latest external knowledge question.
5. Multi-turn implementation follow-up.

Quality targets:

- source analysis reaches at least 85% of agy-level depth by manual review,
- implementation creates files and validates in the target output workspace,
- general stable answer uses no tools and returns a final answer,
- external current answer uses only web tools and synthesizes evidence,
- no meaningless hardcoded prompt exceptions are introduced.

## 7. Validation Commands

Run narrow tests first:

```bash
python -m pytest tests/unit/agent/test_model_router.py tests/unit/agent/test_policy.py
python -m pytest tests/unit/agent/test_route_validator.py tests/unit/agent/test_task_loop_digest.py
python -m pytest tests/unit/workspace tests/unit/memory tests/unit/agent/test_context_builder.py
python -m pytest tests/integration/test_generation_workflow.py
python -m pytest tests/integration/test_mock_agent_loop.py tests/integration/test_headless_runner.py
```

Then broaden:

```bash
python -m pytest tests/unit tests/integration tests/quality tests/tty
```

Finally run real-model prompt checks outside the sandbox when networking is
needed:

```bash
allcode --headless --prompt "현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다"
allcode --headless --workspace ./output --approval auto --prompt "<complex implementation prompt>"
allcode --headless --prompt "<stable general knowledge prompt>"
allcode --headless --prompt "<latest/current external knowledge prompt>"
```

## 8. Remaining Risks

- A very weak routing model can still emit contradictory JSON repeatedly. The
  validator must make the final route safe and useful even when the model route
  is inconsistent.
- Dense source analysis increases token use. The synthesis brief must use
  signatures, imports, and representative files instead of full content dumps.
- Web availability depends on configured backend. The agent must still produce a
  clear final answer when web is unavailable.
- Context compression can accidentally remove repair clues. Recent validation
  failures, explicit user constraints, and active obligations must stay above
  ordinary old transcript messages.
- Korean intent extraction is morphology-sensitive. The solution must combine
  structured constraints, targets, route model output, and validation
  invariants, not raw keyword lists.

## 9. Next Step

Implement Phase 1 first. It directly addresses the most damaging failure mode:
general or explanatory prompts becoming mutation routes. Do not start fallback
router work until direct answer, route validation, and answer/web tool exposure
are stable.
