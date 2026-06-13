# 45. allCode Open-Source Parity Progress Tracker

Last updated: 2026-06-12

This document tracks the current estimated implementation parity of allCode
against mature open-source CLI coding agents such as Aider, Gemini CLI, Qwen
Code, and OpenHands. The percentage is an engineering progress estimate based
on observed real-model behavior, regression tests, and source-level review. It
is not a formal benchmark score.

## Update Rules

- Update this file whenever real-model comparison, quality matrix, or
  regression testing changes a field estimate.
- Do not increase a field estimate without recording the test command or smoke
  prompt that supports the change.
- Do not use prompt-specific, project-specific, or scenario-ID-specific
  hardcoding to improve a percentage.
- A field reaches 95% only when related tests pass, real-model smoke output is
  close to agy/open-source behavior, and the implementation stays within the
  MVP contracts in `plan/00` through `plan/12`.

## Current Estimate

| Field | Current estimate | 95% target gap | Current evidence |
| --- | ---: | --- | --- |
| Model communication/config/runtime | 94% | Real provider latency/token metrics and config-source UI surfacing in normal sessions | `.venv/bin/allcode --diagnose` reports redacted config, project `.env`, selected model, and base URL; headless model call works |
| Routing/policy/intent | 92% | Broader route contradiction stress and source-analysis probe breadth | Direct, inspect, external, and mutate routes are separated; `IntentFrame` now records evidence and mutation needs |
| Source exploration/project analysis | 89-90% | Wider representative probing and model-authored architecture synthesis | 2026-06-12 agy comparison showed allCode remained too narrow for `src/allCode/agent` and summarized only a few modules |
| Tool use/observability/logging | 91% | Real TTY approval lifecycle and less noisy transcript timeline | Session JSONL evaluator shows model/tool/routing traces and one tool failure across recent parity logs |
| General knowledge answers | 90-91% | Current-knowledge grounding with configured web backend and stricter unverified-number suppression | Stable RAG/long-context answer is strong; current-knowledge answer disclosed disabled web but still included unverified concrete examples |
| Project generation/modification/validation | 92-93% | Denser multi-module generation and broader tests/reports | 2026-06-12 featureful CLI smoke passed pytest, but allCode generated 5 tests versus agy's 15 and fewer modules |
| Multiturn context/memory | 84-86% | Persisted obligations and stale repair target protection across process restarts | Active obligations, latest repair context, and source exploration ledger exist in-process |
| TUI/interactive UX | 97-98% | Minor table column padding and streaming block vertical rhythm | `plan/58`: fixed scroll-region clobber + gap + streamed block fragmentation; matched Codex turn marker (`•`+2-col indent), `›` prompt glyph, segmented `━` header + per-row `─` table rules, breathing `•` spinner (greyscale pulse, captured from real Codex), plain code blocks at body indent, removed composer rule, context footer. Verified against real Codex CLI PTY captures of the same prompts; no UI breakage |
| Final answer quality/synthesis | 89-90% | Source-analysis density, current-knowledge citations, and fallback wording reduction | allCode answers are structured, but agy comparison remains richer in architecture grouping and grounded summary shape |

Overall current estimate: 91-92%.

## 2026-06-13 Codex-benchmarked session (TUI + analysis + modify)

Direct cross-checks against the real Codex CLI (gpt-5.5) and agy on this repo:

- TUI rendering: ~80% → ~97% (turn marker `•`+indent, `›` prompt, `━` table rule,
  breathing `•` spinner, plain code blocks; see `plan/58`).
- Project analysis (③): codex-rated 30% → 70% after fixing exploration targeting
  (`.gitignore`-aware, code-first, entrypoint spine), removing scaffolding leak,
  and relaxing the broad-analysis guard so the model authors the answer
  (`plan/59`). Remaining 70→95 is body-level depth — largely bounded by the
  wise-lloa-max model summarizing at import level (~5% detailed coverage).
- Modification (④): harness now lets a modify turn read all layers before
  mutating (`plan/60`), but wise-lloa-max did not emit patch_file/write_file for a
  cross-cutting change that Codex completed — a model edit-emission limit.

Key finding: with harness issues fixed, a meaningful part of the remaining
Codex-parity gap on analysis/modification is the underlying model
(vLLM wise-lloa-max vs Codex gpt-5.5), not allCode's harness. Harness limits and
model limits should be tracked separately.

## Current Top Gaps

1. External knowledge/web synthesis: agy can perform live web-backed report
   synthesis, while allCode currently depends on configured `ALLCODE_WEB_*`
   backends and otherwise gives a qualitative answer with a backend-unavailable
   notice.
2. Deep source-flow analysis: allCode now includes body-sample anchors and
   prioritizes repo-internal edges, but the final answer still often comes from
   deterministic fallback wording instead of agy-like model-authored function
   responsibility synthesis.
3. Complex generation convergence: featureful package CLI generation now
   validates with non-trivial tests and README/parser consistency checks, but
   agy still tends to produce denser tests and a richer report artifact.
4. Multiturn continuity: in-process source exploration ledger now exists, but
   process restart persistence and stale repair-target freshness checks remain.

## Latest Validation Snapshot

```bash
python -m pytest
# 622 passed, 7 skipped

python -m pytest tests/unit/agent tests/unit/tools tests/integration/test_generation_workflow.py
# 412 passed

python -m pytest tests/unit/agent tests/unit/tools tests/unit/generation tests/integration/test_generation_workflow.py
# 420 passed

python -m pytest -q output/parity95_round17_taskhub/tests
# 6 passed

python -m pytest
# 640 passed, 7 skipped

python -m pytest -q output/parity95_round52_taskhub/tests
# 7 passed

python -m pytest
# 723 passed, 7 skipped

.venv/bin/allcode --diagnose
# Redacted config source diagnostics printed; model wisenut/wise-lloa-max-v1.2.1,
# base_url http://211.39.140.164:30100/v1, project .env API key present,
# web backend disabled.

python tests/quality/evaluate_parity.py \
  /Users/kimtj319/.allcode/session/2026/06/12/20260612_015817-03_newcli-4f6ad1b4.jsonl \
  /Users/kimtj319/.allcode/session/2026/06/12/20260612_015913-03_newcli-662fe769.jsonl \
  /Users/kimtj319/.allcode/session/2026/06/12/20260612_015940-03_newcli-150424ef.jsonl \
  /Users/kimtj319/.allcode/session/2026/06/12/20260612_020031-allcode_parity_allcode-720e103d.jsonl
# overall_score 96; field_scores observability=100, routing_trace=100,
# token_trace=100, approval_continuity=100, error_control=90,
# tool_reliability=85.
```

## 2026-06-08 Iteration Notes

- Added source-analysis answer outline guidance to the evidence brief and final
  synthesis prompt.
- Added task loop digest propagation into model-backed file generation and
  repair calls.
- Added in-session source exploration ledger context.
- Added mutated test-file evidence so generated tests satisfy related-test
  discovery before validation.
- Added generic document artifact detection so README/document requests cannot
  be reported complete without a changed document file.
- Real source-analysis smoke returned a direct model answer with observed facts,
  inferred roles, module flow, and limitations separated.
- Real generation smoke for `./output/parity_digest_demo3` created `cli.py`,
  `tests/test_cli.py`, and `README.md`, then reported validation passed.
- Comparison-driven cleanup from `plan/46` and `plan/47`:
  - Same source-flow prompt against allCode and agy showed allCode now returns
    observed facts, inferred roles, and exactly three requested bottleneck items
    without incidental read-only/schema/config suffix noise.
  - Same planning prompt showed the previous incidental "file not found" suffix
    is no longer appended to substantial planning answers.
  - Same executive-report prompt showed unverified percentages and duration/team
    examples are removed after retry when web evidence is unavailable.
  - Remaining gap: agy can search current public material and include sourced
    metrics; allCode only does this when a web backend is configured.

## 2026-06-09 Iteration Notes

- `plan/48` comparison round found two 95%-blocking regressions:
  - source-flow answers had bounded evidence but lacked body-level density.
  - Python package CLI generation could falsely pass validation or fall into
    flat tool-loop layout instead of generation workflow.
- Implemented bounded `source_probe` body samples for wide symbols and child
  methods without full-file dumps.
- Added AST syntax completion gate and repairable syntax completion failures.
- Added Python package layout normalization in the project planner.
- Hardened Korean output-directory handoff for prompts using `안에`.
- Hardened source-analysis fallback to include requested body evidence,
  candidate bottlenecks, and improvements when model retry fails.
- Hardened source-answer retry context hygiene so invalid anchored answers are
  not re-injected before retry.
- Real allCode generation smoke for `./output/parity95_round6_cli` entered
  generation workflow and direct `pytest` passed.
- Same general knowledge prompt against allCode and agy produced comparable
  balanced answers without unnecessary tool use.
- Same source-flow prompt now produced a model-authored Korean analysis with
  scope, roles, execution flow, evidence table, 3 bottlenecks, and 3
  improvements.
- Remaining source-analysis gap: allCode still occasionally uses broad
  structure-based performance claims where agy tends to cite more precise
  function responsibilities and line ranges.
- `plan/49` generation hardening added:
  - validation failure + completion obligation unification;
  - TypeVar/typing helper public API noise filtering;
  - preferred repair target files;
  - requirement-covering planner prompt and `api_obligations` path
    normalization;
  - weak-test and documentation-drift completion gates;
  - validation-first repair context ordering;
  - literal public API repair guidance;
  - contract-preserving model editor output;
  - stronger deterministic Python featureful CLI scaffold.
- Real allCode generation smoke for `./output/parity95_round17_taskhub`
  produced `TaskStore`, `CommandRegistry`, retry, add/list/done/export, README,
  and pytest coverage; direct pytest returned 6 passed.
- Real allCode source-flow smoke remained structured and Korean, but still
  relied too much on import/definition anchors and broad inferred bottlenecks.
- Real allCode general RAG/long-context knowledge prompt answered directly
  without unnecessary tool calls and produced a practical mitigation table.
- `plan/50` source/doc consistency hardening added:
  - source final-answer guard now requires observed body-sample anchors when
    the user asks for function/method body evidence;
  - source brief range trimming prioritizes `symbol_body_sample` and
    `child_body_sample` anchors;
  - source flow synthesis prioritizes repo-internal edges over standard-library
    import noise;
  - completion checker compares README CLI usage against observed `argparse`
    commands/options and parser `prog` names;
  - workflow editor rejects model-generated source files that drop literal
    `api_obligations`;
  - model plan acceptance rejects featureful Python CLI plans whose declared
    API obligations are not present in planned source content.
- Real allCode source-flow smoke now includes body evidence and repo-internal
  edges first. Remaining gap: answer shape is still deterministic/fallback-like
  compared with agy's natural source-flow summary.
- Real allCode generation smoke for `./output/parity95_round52_taskhub`
  succeeded and direct pytest returned 7 passed. Same agy prompt created a
  comparable package with 10 passing tests and a separate report artifact.

## 2026-06-12 Comparison Notes

- Implemented `IntentFrame`, redacted config diagnostics, web fetch
  sanitization, model metric payloads, `ProjectPlanQualityGate`, and a
  JSONL-backed parity evaluator.
- Full regression after the hardening cycle passed:
  `python -m pytest` returned `723 passed, 7 skipped`.
- Runtime diagnostics through `.venv/bin/allcode --diagnose` confirmed the
  expected model endpoint and redacted `.env` API-key discovery. Web backend is
  still disabled, so current-knowledge web evidence cannot be counted as
  complete parity.
- Same source-analysis prompt:
  `현재 디렉터리의 src/allCode/agent 내 주요 모듈이 어떤 책임을 갖는지 아키텍처 관점에서 정리해줘. 코드 수정은 엄격히 금지한다.`
  - allCode produced a safe Korean answer with line anchors, but covered only a
    few modules (`context.py`, `grounding.py`, `source_responsibility_graph.py`)
    and explicitly left many modules unobserved.
  - agy produced a broader six-layer architecture summary covering loop,
    routing, policy, context/source intelligence, generation/repair, and
    evidence/finalization.
  - Result: source-analysis estimate was lowered to `89-90%` until broad
    package probing and source synthesis are less sparse.
- Same stable general-answer prompt:
  `RAG와 긴 컨텍스트 윈도우 접근법의 장단점을 실무 관점에서 비교해줘. 웹 검색은 필요하지 않으면 하지 말고, 한국어로 답해줘.`
  - allCode answered directly in Korean with a detailed comparison table.
  - agy answered more compactly and practically.
  - Result: stable general answers are usable, but allCode should reduce
    unverified concrete examples and keep the answer denser.
- Same current-knowledge prompt:
  `2026년 현재 오픈소스 LLM이 상용 폐쇄형 모델을 위협할 수 있는 요인을 최신 동향 기준으로 정리해줘. 한국어로 답하고, 현재 정보가 필요하면 웹 근거를 사용해줘.`
  - allCode correctly disclosed `web_search` backend unavailability, but still
    included concrete current-looking claims without citations.
  - agy produced a more confident current-trend answer, but also did not expose
    citation URLs in the terminal response.
  - Result: configure SearXNG or another web backend before raising this field;
    meanwhile allCode needs stricter current-knowledge uncertainty handling.
- Same generation prompt in isolated temp workspaces:
  `표준 라이브러리만 사용해서 ./output/parity56_taskhub 안에 Python CLI 프로젝트를 생성해줘. 기능: add/list/done/export, JSON 저장소, retry helper, README, pytest 테스트, 검증까지 수행. 최종 보고서에 생성 파일과 테스트 결과를 포함해줘.`
  - allCode generated `pyproject.toml`, `src/parity56_taskhub/main.py`,
    README, and one pytest file; direct pytest returned `5 passed`.
  - agy generated a more modular package (`cli.py`, `storage.py`, `utils.py`,
    `__main__.py`), README, requirements, and `15 passed`.
  - Result: allCode generation succeeds but remains less modular and less
    test-dense than agy.
