# 43. Open-Source Parity 95% Execution Plan

## 목적

이 계획은 현재 allCode의 분야별 진척도를 모두 95% 수준까지 끌어올리기 위한 반복 실행 계획이다. 기준은 Aider, Gemini CLI, Qwen Code, OpenHands의 공개 동작 방식과 현재 allCode 코드 구조다.

이 문서는 `plan/00`~`plan/12` 구현 계약을 대체하지 않는다. 충돌 시 `plan/00`~`plan/12`와 `plan/01_open_source_alignment_contracts.md`를 우선한다.

## 현재 기준선

| 분야 | 현재 추정 | 95% 목표까지 필요한 핵심 보강 |
|---|---:|---|
| 모델 통신/config/runtime | 90% | provider 설정 검증, endpoint 혼동 방지, 모델 호출 metric |
| 라우팅/정책/의도 파악 | 82% | route invariant 강화, weak lexical signal 억제, answer/inspect/modify 경계 테스트 |
| 코드 탐색/프로젝트 분석 | 78% | 대표 파일 탐색 depth, unobserved scope 보존, AST/LSP metadata 활용 강화 |
| 프로젝트 생성/검증/수리 | 82% | prompt-derived artifact 계획, editor 단계 분리, validation repair 품질 강화 |
| 일반 지식 답변/web evidence | 85% | unstable knowledge 감지, web unavailable 시 수치 단정 억제 |
| 멀티턴 컨텍스트/memory | 76% | active obligations, repair context, source exploration ledger의 우선순위 보존 |
| tool loop/관찰성/logging | 84% | OpenHands식 action/observation metric, token/decision trace, approval continuity |
| TUI/interactive UX | 80% | Codex-style composer 안정성, approval input 복구, markdown/status signal 품질 |

## 오픈소스 참조 기준

- Aider repo map: 전체 파일 dump 대신 중요한 class/function signature와 dependency graph ranking을 token budget 안에서 제공한다.
- Aider ask/code/architect: 코드 논의, 계획, 실제 편집을 분리한다. allCode는 post-MVP multi-agent가 아니라 `planner -> editor -> executor`의 단일 agent 내부 단계로만 반영한다.
- Aider lint/test loop: 변경 후 lint/test를 실행하고 non-zero 결과를 repair 입력으로 되돌린다.
- Gemini CLI hierarchical memory: global/project/directory/session instruction을 명시적으로 병합하고 `/memory`로 확인 가능하게 한다.
- OpenHands action/observation: tool input/output을 typed action/observation으로 남기고 agent는 event history와 condenser를 통해 다음 step을 결정한다.
- Qwen Code provider-neutrality: provider 설정과 credential은 core와 분리하고, secret은 env key로만 참조한다.

## agy 검토 반영

이번 계획 작성 중 `agy --print`를 분야별로 호출했다. 유효 피드백은 아래만 반영한다.

- Source analysis: 현재 구조는 적절하지만 `final_answer_context._compact_evidence_brief()`가 긴 brief를 앞에서 잘라 unobserved/limitation 섹션을 먼저 잃을 수 있다. 이 섹션은 truncation 시에도 보존해야 한다.
- Source analysis: `source_overview.py`가 500줄 제한에 가깝다. 역할 추론과 evidence formatting은 별도 모듈로 분리해야 한다.
- Generation: Aider architect/editor식 분리는 방향이 맞지만 `workflow.py`에 직접 넣으면 책임이 과도해진다. editor/repair model call은 별도 모듈로 분리한다.
- Memory: 현재 구조는 Gemini/OpenHands 방향과 맞지만 active file raw truncation, secret redaction edge case, recent target path collision을 추가 보강해야 한다.
- Source analysis follow-up: `source_overview` 이후 모델이 대표 파일 후보를 충분히 `source_probe`하지 않으면 최종 답변이 미관찰/추론 위주가 된다. `grounding.py`의 deterministic read/probe 훅을 대표 source 후보에도 확장하되, read-only inspect에서만 1라운드 1개 후보로 제한하고 inspection budget을 반드시 지킨다.
- Routing follow-up: "코드 수정 전에 해야 할 일"처럼 변경 행위 자체를 설명하는 일반 질문은 mutation route가 아니다. mutation hint는 단어 존재가 아니라 명령형 변경 요청, 구체 파일/경로 타깃, 프로젝트 생성 지시와 결합될 때만 올린다.

주의: 한 `agy` 검토는 review-only 지시에도 실제 수정을 시도했다. 이후 적용은 반드시 Codex가 diff를 검토하고, allCode 계약에 맞는 부분만 수동 병합한다.

## 2026-06-08 적용 기록

- Phase 1 구조 건전성: `phase_gate.py`의 artifact helper를 `phase_gate_artifacts.py`로 분리했다. 공개 함수는 re-export/기존 import 호환을 유지했고 `phase_gate.py`는 218 LOC, `phase_gate_artifacts.py`는 294 LOC로 유지한다.
- Phase 2 코드 탐색: `source_overview` 대표 후보 중 아직 읽히지 않은 후보를 `grounding.py`에서 deterministic `source_probe`로 1개씩 자동 주입한다. `source_probe`를 inspection budget에 포함하고, final evidence brief의 unread representative limitation은 required coverage gap만 표시한다.
- Phase 3 라우팅: `prompt_constraints.py`의 mutation hint를 직접 변경 명령/파일 타깃/프로젝트 생성 지시 중심으로 좁혔다. 일반 조언 질문의 `수정`, `코드` 단어만으로 `modify`가 되는 경로를 차단한다.
- Phase 3 구조: `prompt_constraints.py`를 public schema/orchestration만 남기고 `prompt_constraint_terms.py`, `prompt_constraint_detection.py`로 분리했다. 기존 `PromptConstraints`/`PromptConstraintExtractor` import 경로는 유지한다.
- Phase 2 수렴: source overview 이후 대표 파일 근거가 부족한데 모델이 텍스트 답변을 먼저 반환하면 최종 성공으로 받아들이지 않고 추가 inspect request를 주입한다. 단, policy-denied mutation 이후 근거 수집이 시작되지 않은 read-only 자연어 답변은 막지 않는다.
- Phase 2 대표 후보: `source_ranking.py`에 architecture role bucket diversity를 추가했다. package/group 대표 후보를 먼저 유지하고, 그 다음 `router`, `loop/runner`, `context/prompt`, `recovery/validation`, `workflow/plan`, `tool/executor` 역할 후보를 generic filename/symbol signal로 보강한다. 특정 프롬프트나 프로젝트명은 매칭하지 않는다.
- Phase 2 probe precision: `source_probe.py`가 큰 class/function span을 전체 body로 넘기지 않고 `symbol_header` + `child_signature` bounded slice로 제한한다. `wide_symbols` metadata를 observation과 final evidence brief에 보존해 모델이 "헤더/시그니처만 관찰됨"을 알 수 있게 했다.
- Phase 2 coverage budget: `source_inspection_budget.py`를 추가해 `grounding.py`, `inspect_staging.py`, `source_answer_synthesis.py`, `round_runner.py`에 흩어진 대표 파일 required-count 계산을 통합했다. 단일 대형 패키지에서도 대표 후보 수가 많으면 coverage_ratio가 1.0이어도 4~5개 이상의 architecture representative를 요구한다.
- Phase 6 recent target safety: `RecentTargetMemory`와 `PathResolver`가 같은 basename의 최근 타깃을 하나로 조용히 선택하지 않고 ambiguity를 보존하도록 했다. semantic recent match가 동률일 때도 `recent[0]` fallback으로 잘못 붙지 않는다.
- Phase 6 active file context: `context_source_summary.py`를 추가해 큰 active file 또는 truncation 상황에서 raw prefix 대신 AST/regex 기반 source skeleton, definitions/imports, range-first recommended action을 주입한다.
- Phase 1 구조 건전성: `round_response_handler.py`에서 text answer gate를 `round_text_response.py`로 분리했다. 기존 parser status dispatch와 malformed/reasoning recovery는 원 파일에 유지하고, 조기 text answer 차단/validation gate/source-inspect premature gate는 전용 handler로 옮겼다. `round_response_handler.py`는 354 LOC, `round_text_response.py`는 146 LOC다.
- Phase 7 구조 건전성: `tool_call_processor.py`에서 test-authoring target denial을 `tool_phase_target.py`로 분리하고, policy-denied observation 생성은 `policy_denied_tool_result()`로 표준화했다. processor 본체는 392 LOC로 내려갔고, 실행/예산/loop guard orchestration 중심으로 남겼다.
- Phase 1/3 구조 건전성: `prompt_builder.py`에서 routing/context/feature objective/repair target section rendering을 `prompt_sections.py`로 분리했다. public `PromptBuilder` API와 문자열 계약은 유지했고, 본체는 382 LOC, section renderer는 122 LOC다.
- Phase 4 구조 건전성: `validation_repair.py`에서 validation log parser와 repair target ranking을 각각 `validation_failure_parser.py`, `repair_target_ranking.py`로 분리했다. 기존 `validation_repair` public import는 `__all__` facade로 유지했고, 본체는 39 LOC, parser는 312 LOC, ranking은 79 LOC다.
- Phase 1/2 구조 건전성: `round_runner.py`에서 inspect-stage flow, inspect budget 계산, repair flag/snapshot 계산을 각각 `round_inspect_flow.py`, `round_inspection_budget.py`, `round_repair_state.py`로 분리했다. runner 본체는 395 LOC로 내려갔고, 테스트 호환 private wrapper는 유지한다.
- Phase 4 구조 건전성: `workflow.py`에서 `GenerationWorkflowResult`와 normal/exception result construction을 `workflow_result.py`로 분리했다. event publishing은 workflow orchestration에 남겼고, `workflow.py`는 364 LOC, `workflow_result.py`는 104 LOC다.
- Phase 3 구조 건전성: `model_router.py`에서 schema, routing prompt construction, JSON extraction, read-only route sanitizer를 각각 `model_router_schema.py`, `model_router_prompt.py`, `model_router_json.py`, `model_router_safety.py`로 분리했다. `ModelRouter` 공개 API는 유지했고 본체는 272 LOC다.
- Phase 3 구조 건전성: `intent.py`에서 static term/regex catalog를 `intent_terms.py`로 분리했다. `IntentExtractor`의 기존 class attribute 접근 계약은 유지했고, 본체는 190 LOC, term catalog는 258 LOC다.
- Phase 6 구조 건전성: `context.py`에서 session/manifest section rendering을 `context_session_sections.py`로, recent/active file section rendering을 `context_file_sections.py`로 분리했다. `ContextBuilder` 공개 API와 private compatibility wrapper는 유지했고, 본체는 227 LOC다.
- Phase 1/6 구조 건전성: `loop.py`에서 artifact obligation seeding, target hint existence, generation workflow result memory update를 `loop_obligations.py`로 분리했다. `AgentLoop.run_turn()` orchestration은 유지했고, 본체는 396 LOC다.
- 현재 검증: `python -m pytest` 기준 558 passed, 7 skipped. 실제 모델 headless smoke에서 `src/allCode/agent` 분석은 `context.py`, `router.py`, `loop.py`, `workflow.py`, `context_condensation.py`를 라인 근거로 포함했다. Phase 6 memory 보강은 `tests/unit/memory`, `tests/unit/workspace/test_path_resolver.py`, `tests/unit/agent/test_context_builder.py`, `tests/integration/test_followup_context_memory.py`에서 검증했다. Phase 1/2/3/4/6/7 구조 분리는 `tests/unit/agent`, `tests/unit/tools`, `tests/integration/test_mock_agent_loop.py`, `tests/integration/test_headless_runner.py`, `tests/quality/test_quality_matrix.py`에서 검증했다. 특정 프롬프트/시나리오 하드코딩 스캔은 `src/allCode`에서 추가 발견이 없었고, `src/allCode`의 Python 파일 중 400줄 이상 파일은 남아 있지 않다. 95% 목표의 다음 병목은 실모델 allCode/agy 동일 프롬프트 비교에서 source analysis/generation/general answer 품질을 다시 측정하는 것이다.
- Phase 2 source-analysis grounding: `source_probe_edges.py`를 추가해 Python import/reference edge를 workspace-local path로 해석하고, `source_probe.py` observation에 `resolved_target`을 보존한다. `source_answer_synthesis.py`는 resolved edge를 우선 사용한다.
- Phase 2 inspect target enforcement: `inspect_staging.py`는 명시 파일 타깃을 `list_tree`/후보 목록만으로 완료 처리하지 않고 실제 `source_probe`/`read_file` 관찰을 요구한다. `tool_phase_target.py`는 inspect stage의 `target_paths` 밖 `source_probe/read_file/source_overview` 호출을 schema-denied로 막는다.
- Phase 2 source-answer grounding gate: `source_answer_guard.py`를 추가해 최종 source-analysis 답변의 `path:Lx-Ly(reason:symbol)` 앵커, 읽지 않은 파일 내부 주장, 관찰되지 않은 dotted symbol 주장을 검증한다. 첫 위반은 모델 재작성으로 돌리고, 재작성 후에도 실패하면 `source_answer_fallback.py`가 관찰된 tool evidence만으로 deterministic safe summary를 반환한다.
- Phase 2 실제 모델 검증: 동일 headless 프롬프트에서 이전에는 `src/allCode/agent`를 충분히 관찰하지 않고 답변하거나 잘못된 line anchor를 관찰 사실로 사용했다. 보강 후 실제 `allcode --headless`는 `source_probe.py`, `context.py`, `router.py`, `loop.py`, `context_condensation.py`, `workflow.py` 관찰 근거를 수집했고, 모델 재작성 실패 시 안전 fallback으로 grounded summary를 반환했다. 품질은 hallucination safety 기준으로는 95%에 근접하지만, agy식 자연어 연결 설명 밀도는 아직 88~90% 수준으로 남아 다음 반복에서 deterministic brief를 더 answer-like하게 렌더링해야 한다.
- 현재 검증 갱신: `python -m pytest` 기준 587 passed, 7 skipped. `python -m pytest tests/unit/agent tests/unit/tools tests/integration/test_readonly_source_analysis.py` 기준 364 passed. `python -m py_compile`로 변경 파일 구문 검증을 완료했다. `src/allCode` 400줄 이상 Python 파일 스캔과 특정 scenario/prompt 하드코딩 스캔은 추가 발견이 없었다.
- Phase 2 query-aware source exploration: `ToolContext.user_prompt`를 통해 `source_overview`가 원 사용자 요청을 대표 파일 랭킹에 반영한다. `source_query_relevance.py`와 `source_ranking_roles.py`를 추가해 한국어/영어 범용 architecture token을 path/symbol/import 토큰과 매칭하되, 후보 집합 대부분에 공통으로 나타나는 토큰은 제거한다. `grounding.py`는 `source_overview`가 만든 후보 순서를 보존해 query-relevant 대표 파일을 먼저 probe한다. `source_answer_guard.py`는 raw tool/action JSON을 최종 답변으로 통과시키지 않는다. 실제 headless smoke에서 raw action final은 차단됐지만, 넓은 `src/allCode` overview에서는 fallback이 아직 `source_answer_synthesis.py`/`source_final_brief.py`까지 충분히 관찰하지 못하는 경우가 남아 있다.
- Phase 2 source-analysis continuation: `inspect_tool_normalization.py`가 broad `source_overview`/tree/glob 요청을 명시 타깃 디렉터리로 좁히고, 이미 타깃 하위 경로를 보고 있을 때만 보존한다. `inspect_staging.py`는 `source_overview`의 query-aware 대표 후보 순서를 다시 점수 정렬로 뒤집지 않고 target group 안에서 유지한다. `source_overview.py`는 모델이 보낸 좁은 query와 원 사용자 요청을 결합해 대표 후보 랭킹에 반영한다. `source_answer_fallback.py`는 관찰된 대표 파일을 기반으로 파일명/심볼 토큰 기반의 일반 역할 신호를 사용자 언어로 렌더링한다. agy read-only 검토에서 특정 에이전트 내부 단계처럼 보일 수 있는 표현은 외부 프로젝트 분석에서 부정확할 수 있다는 지적을 받아, `모델 라운드 오케스트레이션` 같은 단정 표현을 `실행/반복 제어`, `소스 탐색 또는 근거 수집`, `출력 또는 응답 구성` 같은 generic role signal로 낮췄다. 실제 headless smoke에서 `source_probe.py`, `round_runner.py`, `loop.py`, `source_analysis_rendering.py`, `round_response_handler.py`, `source_answer_synthesis.py`, `source_final_brief.py`, `round_tool_handler.py`, `round_inspect_flow.py`가 확인 범위에 포함됐고, fallback 최종 답변은 확인 근거/연결 흐름/추론/한계를 분리했다.

## 반복 종료 기준

각 분야는 아래 조건을 모두 만족할 때 95% 도달로 본다.

1. 관련 unit/integration/quality/tty 테스트가 통과한다.
2. 실모델 smoke에서 동일 프롬프트 기준 agy 대비 답변 품질이 90~95% 이상이다.
3. read-only 요청에서 mutation/shell/validation tool이 노출되지 않는다.
4. 구현 요청에서 실제 변경/검증 근거 없는 완료가 없다.
5. 특정 프롬프트, scenario ID, 프로젝트명, path를 코드에 직접 매칭하지 않는다.
6. Python source file은 500줄을 넘지 않고, 300줄 이상 파일은 분리 후보로 기록한다.

## Phase 1. 구조 건전성 및 계획 고정

대상:

- `plan/43_open_source_parity_95_execution_plan.md`
- `src/allCode/agent/workflow.py`
- `src/allCode/agent/workflow_editor.py`
- `src/allCode/tools/builtin/source_overview.py`
- `src/allCode/tools/builtin/source_overview_roles.py`
- `src/allCode/generation/strategies/python.py`

작업:

1. 계획서를 저장소에 남긴다.
2. `workflow.py`에서 model editor/repair helper를 분리한다.
3. `source_overview.py`에서 역할 추론 helper를 분리한다.
4. Python strategy에서 더 이상 호출되지 않는 scenario-specific private template을 제거한다.
5. 줄 수 제한을 다시 확인한다.

검증:

```bash
python -m pytest tests/unit/agent/test_project_planner.py tests/unit/generation/test_strategy_paths.py
python -m pytest tests/unit/tools/test_source_overview_tool.py
```

## Phase 2. 코드 탐색/프로젝트 분석 95%

대상:

- `src/allCode/agent/inspect_staging.py`
- `src/allCode/agent/source_answer_synthesis.py`
- `src/allCode/agent/final_answer_context.py`
- `src/allCode/tools/builtin/source_probe.py`
- `src/allCode/workspace/source_intelligence/*`

작업:

1. broad/truncated source overview에서는 package bucket별 representative `source_probe`를 확보한다.
2. `unobserved`, `coverage gaps`, `limitations`는 evidence brief truncation 후에도 보존한다.
3. 최종 답변 합성 지시에 확인 범위, 대표 파일 근거, observed/inferred/unobserved 분리를 강제한다.
4. AST/LSP metadata는 optional enrichment로만 사용하고 실패 시 regex fallback으로 내려간다.
5. source 분석 중 full-file dump를 금지하고 line/symbol slice 중심으로 유지한다.

검증:

```bash
python -m pytest tests/unit/agent/test_inspect_tool_staging.py tests/unit/agent/test_source_answer_synthesis.py tests/unit/agent/test_final_answer_context.py
python -m pytest tests/unit/tools/test_source_probe_tool.py tests/unit/workspace/test_source_intelligence_python_ast.py tests/unit/workspace/test_source_intelligence_graph.py
python -m pytest tests/integration/test_readonly_source_analysis.py
```

## Phase 3. 라우팅/정책 95%

대상:

- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/intent.py`
- `src/allCode/agent/model_router.py`
- `src/allCode/agent/route_validator.py`
- `src/allCode/agent/answer_policy.py`
- `src/allCode/agent/policy.py`

작업:

1. direct answer route는 tool schema를 완전히 숨긴다.
2. external answer route는 web evidence tool만 노출한다.
3. read-only inspect route는 read/search/source_overview/source_probe만 허용한다.
4. broad Korean verbs는 단독 mutation 근거로 사용하지 않고 target/artifact obligation과 결합할 때만 보정한다.
5. route validation report를 session log에 남겨 후속 분석이 가능하게 한다.

검증:

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_route_validator.py tests/unit/agent/test_answer_policy.py tests/unit/agent/test_policy.py tests/unit/agent/test_readonly_tool_boundary.py
```

## Phase 4. 생성/검증/수리 95%

대상:

- `src/allCode/agent/project_planner.py`
- `src/allCode/agent/workflow.py`
- `src/allCode/agent/workflow_editor.py`
- `src/allCode/agent/workflow_actions.py`
- `src/allCode/agent/completion_checker.py`
- `src/allCode/agent/validation_repair.py`
- `src/allCode/agent/final_reporter.py`

작업:

1. model planner는 파일 내용을 한 번에 과도하게 만들지 않고 artifact obligation 중심의 실행 가능한 `ProjectPlan`을 만든다.
2. editor 단계는 파일별 raw content 생성만 담당하고 tool executor가 실제 write를 수행한다.
3. editor 출력은 파일 유형별 최소 유효성 검사로 거르고, 부적절한 일반 문장은 기존 plan content로 fallback한다.
4. validation failure는 traceback/test item/changed file 순으로 repair target을 정렬한다.
5. repair loop는 동일 failure signature 반복 시 중단한다.

검증:

```bash
python -m pytest tests/unit/agent/test_project_planner.py tests/integration/test_generation_workflow.py tests/unit/agent/test_validation_repair.py tests/unit/agent/test_completion_checker.py
```

## Phase 5. 일반 답변 및 web evidence 95%

대상:

- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/answer_policy.py`
- `src/allCode/agent/final_answer_context.py`
- `src/allCode/agent/finalization.py`
- `src/allCode/tools/builtin/web.py`

작업:

1. stable knowledge는 direct answer로 즉시 답한다.
2. 최신/현재/법률/가격/시장/KPI/성능 수치가 필요한 질문은 web-only answer route로 보낸다.
3. web backend가 없으면 일반 원칙과 검증 필요 항목을 분리하고 수치 단정을 금지한다.
4. local workspace 질문과 external knowledge 질문을 섞지 않는다.

검증:

```bash
python -m pytest tests/unit/agent/test_answer_policy.py tests/unit/tools/test_web_provider.py tests/unit/tools/test_web_tools.py
python -m pytest tests/quality
```

## Phase 6. Memory/Multiturn 95%

대상:

- `src/allCode/agent/context.py`
- `src/allCode/agent/context_condensation.py`
- `src/allCode/agent/session_state.py`
- `src/allCode/memory/project_obligations.py`
- `src/allCode/memory/recent_targets.py`
- `src/allCode/memory/redaction.py`
- `src/allCode/memory/hierarchy.py`

작업:

1. active project obligations와 latest repair context를 routing context보다 먼저 주입한다.
2. source exploration ledger를 session summary에 compact하게 남긴다.
3. active file truncation은 raw slice 대신 skeleton/signature fallback을 우선한다.
4. redaction은 현재 config/env key 값도 함께 고려한다.
5. recent target basename collision은 후보가 여러 개면 자동 선택하지 않고 clarification/safe inspect로 전환한다.

검증:

```bash
python -m pytest tests/unit/memory tests/unit/agent/test_context_builder.py tests/unit/agent/test_context_condensation.py tests/integration/test_followup_context_memory.py
```

## Phase 7. Tool/Observability 95%

대상:

- `src/allCode/tools/executor.py`
- `src/allCode/agent/tool_call_processor.py`
- `src/allCode/agent/tool_evidence.py`
- `src/allCode/telemetry/session_logger.py`
- `src/allCode/telemetry/session_analyzer.py`

작업:

1. OpenHands식 action/observation record kind를 더 명확히 남긴다.
2. route decision, tool schema exposure, approval, validation, repair를 한 session timeline에서 추적 가능하게 한다.
3. token usage가 provider에서 오면 그대로 기록하고, 없으면 payload/message char metric을 보조 지표로 남긴다.
4. approval requested 상태에서 TUI/headless가 끊기지 않도록 event와 handler contract를 검증한다.

검증:

```bash
python -m pytest tests/unit/tools tests/unit/telemetry tests/integration/test_agent_session_logging.py
```

## Phase 8. TUI/Interactive 95%

대상:

- `src/allCode/tui/runtime.py`
- `src/allCode/tui/terminal.py`
- `src/allCode/tui/terminal_input.py`
- `src/allCode/tui/terminal_answer_renderer.py`
- `src/allCode/tui/renderers.py`

작업:

1. Codex-style terminal scrollback + fixed composer 원칙을 유지한다.
2. 한국어 입력/paste/IME 흐름이 submit 전 문자열을 깨뜨리지 않게 한다.
3. approval prompt는 입력을 받고 agent loop로 정확히 반환한다.
4. markdown table/code block은 문장 단위 streaming 중에도 깨지지 않게 buffer/render한다.
5. tool output은 짧은 status만 보여주고 상세 내용은 fold/artifact로 분리한다.

검증:

```bash
python -m pytest tests/tty tests/unit/tui
```

## 반복 평가

각 phase 후 아래 실모델/비교 prompt를 최소 3종 실행한다.

1. 복잡한 프로젝트 전체 코드 분석.
2. `./output` 하위에 복잡한 프로젝트 생성.
3. 일반 지식/비즈니스 질문.

각 prompt는 allCode와 agy에 동일하게 전달하되, 두 agent 모두 source 변경 금지 조건을 명확히 둔다. 구현/생성 prompt는 allCode 전용 임시 workspace와 `./output` 하위에서만 수행한다.

결과 보고는 분야별 pass/warning/fail과 agy 대비 근접도를 함께 작성한다.

## 2026-06-08 반복 적용 결과

이번 반복에서 반영한 범위:

1. router/model router/context/loop 계층의 400줄 미만 구조 분리를 유지했다.
2. direct answer에서 `external_knowledge_suppressed` 신호를 route flags까지 전파했다.
3. 일반 원칙/evergreen 답변에 대해 구체 수치, 비용, 지연 시간, 후보군 크기, 모델 크기 같은 미근거 metric 생성을 금지하는 prompt instruction을 추가했다.
4. 모델이 instruction을 무시하는 경우를 대비해 `answer_scope_guard`를 추가하고, 위반 시 한 번만 qualitative rewrite를 요청하도록 했다.
5. Python generation repair 경로가 `output/foo` 전체를 패키지명으로 오인하지 않고 마지막 path segment만 사용하도록 수정했다.

agy 검토 반영:

1. `answer_scope_guard`는 특정 프롬프트/벤치마크 ID를 보지 않고 route flag와 generic metric suffix/range pattern으로 동작하므로 하드코딩 위험이 낮다는 피드백을 받았다.
2. citation range, 사용자 제공 숫자 substring, storage/rate/CPU 단위 누락 리스크를 추가로 지적받아 즉시 보강했다.
3. retry는 `answer_scope_violation` recovery reason으로 1회만 수행하므로 무한 루프 위험은 낮다.

검증 결과:

```bash
python -m pytest
# 571 passed, 7 skipped

find src/allCode -name '*.py' -print0 | xargs -0 wc -l | awk '$1 >= 400 && $2 != "total" {print}'
# output 없음

rg -n "CG[0-9]+|complex_ops_platform|parity_smoke_tool|parity_95_diff_smoke|현재 디렉터리의 src|5문장으로|표로만 정리|JSON 객체로만|bullet 3개" src/allCode
# match 없음
```

실모델 확인:

1. 일반 RAG reranker trade-off 질문은 web route로 새지 않고 direct answer로 처리되었다.
2. 첫 답변에서 구체 수치가 포함되면 `answer_scope_violation` recovery가 발생했고, 재작성 답변은 정성적 기준과 의사결정 흐름 중심으로 개선되었다.
3. `./output/parity_95_sample_app_fix` 생성 프롬프트는 올바른 패키지 경로(`src/parity_95_sample_app_fix`)를 생성하고 `python -m pytest` 2 passed로 검증되었다.

현재 진척도 추정:

| 분야 | agy/open-source 대비 추정 | 근거 | 95%까지 남은 주요 갭 |
| --- | ---: | --- | --- |
| 구조/모듈화 | 95% | 400줄 이상 Python 파일 없음, router/context/loop 책임 분리 | 장기적으로 신규 파일 비대화 방지 CI 필요 |
| 일반 답변 라우팅/품질 | 91% | evergreen 질문 direct route, scope violation retry 동작 | 더 다양한 장르의 수치/출처 제약 benchmark 필요 |
| 프로젝트 생성/수정 | 91-92% | path basename repair, workflow validation 통과 | 대형 멀티모듈 생성의 iterative planning 품질 추가 검증 필요 |
| 소스 분석 | 85-88% | source_overview/source_probe 기반 답변은 개선됐으나 agy보다 파일 탐색 깊이 낮음 | 대표 파일 탐색 예산과 cross-module flow synthesis 강화 |
| 멀티턴/메모리 | 86-88% | active obligations/context split 유지 | 장기 세션에서 실패 맥락 압축/재주입 stress 추가 필요 |
| Tool/관찰성 | 89-90% | session log, route/tool evidence 유지 | approval interactive path와 tool timeline UX 추가 검증 |
| TUI/interactive | 82-85% | TTY 테스트 통과, 기본 terminal UI 유지 | 실제 IME/approval/긴 markdown scrollback 수동 검증 필요 |

다음 반복 우선순위:

1. 소스 분석 95%: `source_overview` representative 후보를 더 많이/깊게 읽되 full-file dump 없이 AST/LSP symbol graph와 import/call relation 중심으로 압축한다.
2. 멀티턴 95%: previous failure, active artifacts, source exploration ledger를 session context에 더 안정적으로 재주입한다.
3. TUI 95%: 실제 TTY에서 approval 입력과 한국어 IME/paste/composer 복구를 수동-자동 혼합으로 검증한다.
