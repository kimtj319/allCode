# 53. Risk Closure Plan: Source Analysis Guard and Dependency Constraints

## Purpose

Close the remaining high-impact risks found after the source-only 18:20 commit
without expanding allcode beyond the MVP contracts.

This plan follows:

- `plan/00_master_implementation_guide.md`
- `plan/01_open_source_alignment_contracts.md`
- `plan/05_routing_policy_plan.md`
- `plan/07_workspace_context_plan.md`
- `plan/11_quality_testing_plan.md`
- `plan/52_comparison_gap_hardening_plan.md`

AGY reviewed the current code and confirmed two realistic hardening targets:

1. `source_package_role_guard.py` re-parses prompt text instead of using the
   central routing/intent result.
2. `dependency_answer_guard.py` relies too heavily on a short third-party
   package allow/deny list and fixed installer command patterns.

## Non-Goals

- Do not add a new LLM router or model-side constraint parser in this pass.
- Do not hardcode benchmark scenario IDs, prompt strings, project names, or
  expected answer phrases.
- Do not weaken read-only safety, route-based tool exposure, or final answer
  grounding gates.
- Do not introduce post-MVP systems such as MCP managers, plugin marketplaces,
  cloud sandboxes, or multi-agent swarms.

## Phase 1. Source Analysis Intent Unification

### Problem

`source_package_role_guard.py` currently calls `_broad_source_role_request()`
and searches the raw user prompt for terms such as `src`, `role`, `structure`,
and Korean equivalents. This duplicates routing responsibility and can miss
paraphrased source-analysis prompts or over-trigger on unrelated prompts.

### Implementation

- Extend `IntentSignals` with `broad_source_analysis_requested`.
- Add a generic detector in `IntentExtractor` that uses existing path/inspect
  signals and broad scope terms. Keep it generic; do not add specific test
  prompts.
- Add `broad_source_analysis` to `RoutingDecision.flags`.
- Change `source_answer_guard.source_answer_violation()` to pass the
  `RoutingDecision` into `missing_priority_package_roles()`.
- Change `source_package_role_guard.missing_priority_package_roles()` to use:
  - `routing.flags` containing `broad_source_analysis`, or
  - strong observed source-overview evidence when routing was built by older
    tests or injected custom routes.
- Remove prompt keyword parsing from the source role guard.
- Keep function signatures explicit: `missing_priority_package_roles()` must
  receive `routing` from `source_answer_guard.py` instead of importing agent
  state or reparsing the prompt.

### Verification

- Unit test that broad source role coverage is enforced when routing has the
  `broad_source_analysis` flag.
- Unit test that observed `source_overview` package-role evidence can trigger
  coverage enforcement without relying on exact prompt words.
- Unit test that a narrow inspect route without broad flag and without broad
  overview evidence is not forced to mention all package roles.

## Phase 2. Dependency Constraint Guard Generalization

### Problem

`dependency_answer_guard.py` only catches a small fixed set of third-party
package names and Python installer commands. It misses unknown third-party
imports such as `bs4`, `paramiko`, or `redis`, and non-Python installer
suggestions such as `npm install`, `go get`, or `cargo add`.

### Implementation

- Keep static term checks only as a compatibility fallback.
- Add Python code block extraction and parse import statements with `ast`.
- Compare top-level imported modules against `sys.stdlib_module_names`,
  builtins, and inferred local package roots from answer paths.
- Wrap `ast.parse()` in `try/except SyntaxError` so incomplete model-generated
  snippets fall back to installer/static checks instead of crashing the agent.
- Treat non-stdlib, non-local imports in Python code blocks as dependency
  violations under `stdlib_only_requested`.
- Also inspect simple dynamic import calls such as
  `importlib.import_module("requests")` and `__import__("requests")` when the
  module name is a string literal.
- Add generic installer detection for common ecosystems:
  - Python: `pip install`, `uv add`, `poetry add`, `pipenv install`
  - JavaScript: `npm install`, `yarn add`, `pnpm add`, `bun add`
  - Go: `go get`
  - Rust: `cargo add`
  - General dependency files: positive dependency edits in
    `requirements.txt`, `pyproject.toml`, `package.json`, `go.mod`, or
    `Cargo.toml`
- Preserve negated/rejected mentions, especially lines like
  "requests는 사용하지 말고 urllib.request를 사용".
- Apply the same negation/rejection check to generic installer commands such as
  "do not run npm install".
- Keep fallback sanitization conservative: remove violating lines, not entire
  useful answers.

### Verification

- Unit tests for unknown third-party imports: `bs4`, `paramiko`, `redis`.
- Unit tests for stdlib and local package imports being allowed.
- Unit tests for installer commands outside Python.
- Existing dependency guard tests must keep passing.

## Phase 3. Constraint Extraction Tightening

### Problem

`STDLIB_ONLY_TERMS` is still a static phrase list. A full model-side parser is
larger than this pass, but the current terms miss common Korean/English variants.

### Implementation

- Add a small pure helper in prompt constraint detection for dependency
  constraint intent:
  - detect "no/without/exclude/avoid" near "third-party/external/package/
    dependency/library/module".
  - detect Korean combinations of "외부/서드파티/추가" near
    "패키지/모듈/라이브러리/의존성" and negation/exclusion terms.
  - detect "내장/기본/표준" near "모듈/라이브러리" when paired with
    "만/only".
- Bound proximity checks to the same sentence or a short token window so
  unrelated mentions of dependency terms do not activate the constraint.
- Use this helper in both `PromptConstraintExtractor` and, if appropriate,
  the router flag path.
- Avoid adding prompt-specific sentences as detectors.

### Verification

- Unit tests for natural variants such as "기본 라이브러리만" and
  "no third party libraries".
- Unit tests that unrelated "dependency" discussion in a general answer does
  not force `stdlib_only_requested`.

## Phase 4. Regression and Real TTY Comparison

### Commands

Run targeted tests first:

```bash
python -m pytest tests/unit/agent/test_dependency_answer_guard.py tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_source_answer_guard.py tests/unit/agent/test_model_router.py
```

Then run the broader relevant suites:

```bash
python -m pytest tests/unit/agent tests/integration/test_readonly_source_analysis.py tests/tty
```

Finally run full regression if targeted tests pass:

```bash
python -m pytest
```

### TTY / Agent Comparison Prompts

Use the same prompts with `allcode` and `agy`, with code modification strictly
forbidden:

1. Broad source analysis paraphrase:
   "코드 수정은 금지한다. 현재 작업공간의 src 아래 프로젝트 뼈대와 레이어 구성을 한국어로 정리해줘."
2. Dependency-constrained artifact answer:
   "코드 수정은 금지한다. Python 기본 라이브러리만 사용해서 HTML fetch/parse CLI 설계를 답변으로 작성해줘. 외부 패키지는 쓰지 말고 실제 파일은 만들지 마."
3. Stable general question:
   "좋은 CLI 코딩 에이전트가 코드 수정 전에 반드시 해야 하는 일을 4가지로 정리해줘."

### Pass Criteria

- allcode does not mutate files for read-only prompts.
- allcode source-analysis answer mentions observed package/layer roles without
  raw tool JSON or ungrounded path claims.
- allcode dependency-constrained answer does not suggest third-party imports or
  installer commands.
- allcode direct general answer avoids unnecessary tool loops.

## Remaining Risks

- A future LLM-side intent/constraint parser may still be needed for ambiguous
  natural language, but it should be added only with confidence thresholds and
  schema validation.
- AST import detection only evaluates code that appears in answer text; prose
  package recommendations are still handled by installer/term fallbacks.
- TTY comparisons depend on the configured model endpoint and may vary with
  model quality or network latency.
