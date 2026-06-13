# 42. Open-Source Dataflow Remediation Plan

## 목적

동일 프롬프트 비교에서 allCode는 agy 대비 세 가지 영역에서 뒤처졌다.

1. read-only 복잡한 코드베이스 분석에서 대표 파일 근거가 얕고 일부 추론이 부정확했다.
2. 복잡한 프로젝트 생성 요청에서 실제 파일을 만들지 않고 코드 블록 형태의 설명만 반환했다.
3. 복잡한 일반 질문에서 구조는 맞았지만, 외부 근거가 필요한 수치와 경영 판단을 단정적으로 제시했다.

이 문서는 위 문제를 특정 프롬프트 하드코딩 없이 데이터 흐름에서 고치는 계획이다. 구현 시
`plan/00`부터 `plan/12`, 특히 `plan/01_open_source_alignment_contracts.md`,
`plan/05_routing_policy_plan.md`, `plan/07_workspace_context_plan.md`,
`plan/09_generation_workflow_plan.md`, `plan/39_readonly_source_analysis_parity_plan.md`,
`plan/40_reasoning_final_answer_hardening_plan.md`, `plan/41_answer_quality_routing_context_plan.md`를
우선한다.

## 오픈소스 참고 근거

- Aider repo map: 대형 repo에서는 전체 파일 dump가 아니라 dependency graph와 token budget으로
  가장 관련 높은 repo map 부분만 보낸다.
  - https://aider.chat/docs/repomap.html
- Aider ask/code/architect mode: 코드 논의와 파일 변경 모드를 분리하고, architect/editor 흐름으로
  계획과 실제 편집을 분리한다.
  - https://aider.chat/docs/usage/modes.html
- Aider lint/test loop: 파일 변경 뒤 lint/test를 실행하고 non-zero 결과를 수리 입력으로 다시 넣는다.
  - https://aider.chat/docs/usage/lint-test.html
- Aider edit formats: search/replace diff가 효율적이지만 실패 시 whole-file edit가 단순하고 안정적인
  fallback이다.
  - https://aider.chat/docs/more/edit-formats.html
- OpenHands agent architecture: LLM query, response parsing, action execution, observation event를
  event-driven loop로 분리한다.
  - https://docs.openhands.dev/sdk/arch/agent
- OpenHands condenser: head/tail을 보존하고 middle event를 summary로 압축하는 threshold 기반
  context condensation을 사용한다.
  - https://docs.openhands.dev/sdk/arch/condenser
- Gemini CLI memory: `GEMINI.md` 계층 메모리를 `/memory list`, `/memory refresh`, `/memory show`로
  명시적으로 관리한다.
  - https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/commands.md
- Qwen Code model providers: provider-neutral 설정과 envKey 기반 secret 처리를 유지한다.
  - https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/

allCode 적용 결론:

- Aider식 repo map은 `source_overview`/`source_probe`의 target coverage와 representative budget
  보강으로 반영한다.
- Aider ask/code 분리는 allCode의 route invariant로 반영한다. read-only/answer route는 mutation tool을
  절대 노출하지 않는다.
- Aider lint/test loop는 `GenerationWorkflow`의 실제 file mutation, validation, repair evidence gate에
  반영한다.
- OpenHands action/observation은 기존 event/tool result 흐름을 유지하되, phase block이 다음 모델 호출의
  구체 지시로 이어지게 한다.
- OpenHands condenser와 Gemini memory는 raw transcript가 아니라 compact digest/brief를 모델 호출 직전에
  넣는 방식으로 반영한다.
- Qwen Code provider-neutrality 원칙에 따라 특정 모델명, 특정 endpoint, 특정 프롬프트 예외 분기는 금지한다.

## agy 토론 결과 요약

agy에 코드 수정 금지 조건으로 현재 분석과 오픈소스 참고 결론을 전달했다. agy는 다음 보강 방향이
현실적이라고 검토했다.

- 새 `RoutingIntentProfile`를 크게 도입하기보다 기존 `PromptConstraints`/`IntentSignals`에 구조화 신호를
  확장하는 편이 테스트 파손과 중복을 줄인다.
- `GenerationWorkflow` 진입은 `workflow_hint`에만 의존하지 말고, `route_validator`가 명백한 디렉터리
  target + 생성 의도 + 다중 산출물 신호를 보정해야 한다.
- `RequestedArtifact.kind` 리터럴을 크게 바꾸기보다, 우선 `_same_artifact_target()`와
  `satisfy_requested_artifacts()`에서 디렉터리 하위 파일 생성이 target 만족으로 인정되게 하는 편이
  안전하다.
- read-only source analysis는 예산을 늘리기만 하면 loop 낭비가 커지므로, explicit scope coverage와
  package bucket별 최소 representative evidence를 기준으로 bounded하게 강화해야 한다.
- 일반 질문의 web route는 너무 넓히면 과도구화가 생기므로, 불안정 지식 범주와 수치/법률/시장/규정
  신호를 구조적으로 감지해야 한다.
- `TaskLoopDigest`는 ReAct modify loop에는 이미 들어가므로, generation workflow의 planning/repair model
  call에도 같은 compact task state를 넣는 방향으로 확장한다.

## 현재 데이터 흐름과 문제 발생 시점

### 1. Source Analysis 흐름

현재 흐름:

```text
runtime.run_agent_turn
-> AgentLoop.run_turn
-> ContextBuilder.build
-> ModelRouter.classify
-> RouteValidator/AnswerPolicy
-> PromptBuilder.initial_messages
-> RoundRunner.run_rounds
-> decide_inspect_stage
-> source_overview/source_probe/read_file
-> source_analysis_final_answer_request
-> final_answer_call_messages
-> model final answer
```

문제 발생 시점:

- `inspect_staging._evidence_complete()`가 explicit scope가 넓은 경우에도 `source_overview_paths`,
  `search_candidate_paths`, `inspect_observation_count` 같은 일반 신호로 finalize를 열 수 있다.
- `source_answer_synthesis.build_source_analysis_brief()`는 존재하지만, final answer model call에
  rendered brief가 강하게 주입되지 않는다.
- `final_answer_context._tool_observation_summary()`는 tool observation을 compact하게 나열하지만,
  source analysis 전용 섹션과 coverage gap, representative file evidence를 별도 계약으로 전달하지 않는다.

### 2. Project Generation 흐름

현재 흐름:

```text
ModelRouter.classify
-> PromptConstraintExtractor(project_generation_hint)
-> RouteValidator
-> AgentLoop.should_use_generation_workflow
-> GenerationWorkflow.run
-> ModelProjectPlanner or StrategyRegistry
-> WorkflowActions.write_file
-> ValidationRunner
-> FinalReporter
```

문제 발생 시점:

- `workflow_routing.should_use_generation_workflow()`는 `routing.kind == modify`와
  `routing.workflow_hint == multi_file_generation`이 모두 참이어야 한다.
- 한국어 생성 요청이 `project_generation_hint` 또는 model `workflow_hint`를 놓치면 일반 ReAct/answer 흐름으로
  빠지고, 파일 생성 없이 코드 블록 답변을 반환할 수 있다.
- `phase_gate._artifact_kind_for_path()`는 확장자 없는 `./output/...` target을 source로 본다.
- `_same_artifact_target()`은 하위 파일이 생성되어도 부모 디렉터리 target 만족으로 인정하지 않는다.

### 3. General/External Answer 흐름

현재 흐름:

```text
PromptConstraintExtractor.external_knowledge_hint
-> ModelRouter._merge_constraints
-> RouteValidator
-> AnswerPolicy
-> answer route direct or web_only
-> RoundRunner final answer
```

문제 발생 시점:

- `EXTERNAL_TERMS`가 최신/현재/오늘/공개 문서 중심이라, 경영/법률/시장/가격/KPI 같은 불안정 지식 질문에서
  direct answer가 선택된다.
- direct answer 자체는 빠르지만, 수치/규정/시장 판단을 근거 없이 단정할 위험이 있다.
- web backend가 없거나 결과가 비어 있을 때, 최종 답변에는 근거 한계와 수치 단정 금지 지시가 더 명확해야 한다.

## 최종 수정 계획

### Phase 1. Routing Constraint 신호 보강

수정 대상:

- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/intent.py`
- `src/allCode/agent/model_router.py`
- `src/allCode/agent/route_validator.py`
- `src/allCode/agent/workflow_routing.py`

작업:

1. 기존 `PromptConstraints`를 유지하되, 구조화 신호를 추가한다.
   - `directory_output_hint`: 명시 target이 확장자 없는 디렉터리 또는 `./output/...`류 output root인지.
   - `multi_artifact_hint`: CLI/config/tests/README/plugins/modules 같은 여러 artifact 범주가 요구되는지.
   - `project_output_hint`: output directory + project/platform/app/package 생성 신호.
   - `unstable_knowledge_hint`: 시장, 법률, 규정, 가격, 비용, KPI, 벤치마크, 버전, 2025/2026 등 외부 근거가 필요한 신호.
2. `IntentExtractor`의 한국어 명령 패턴을 확장한다.
   - 허용: 생성/구현/작성/수행/진행/완성/구축 같은 일반 작업 동사와 output path/artifact obligation의 조합.
   - 금지: 특정 프롬프트 문장, 특정 프로젝트명, 특정 테스트 path 직접 매칭.
3. `ModelRouter._merge_constraints()`는 위 구조화 신호를 route flags에 보존한다.
4. `RouteValidator`는 다음 invariant를 적용한다.
   - read-only이면 mutation/workflow 보정 금지.
   - concrete file target이면 `direct_file_edit` 우선.
   - directory output + multi artifact + mutation intent이면 `kind=modify`,
     `workflow_hint=multi_file_generation`, `mutate_file`, `run_validation` 보정.
   - unstable external knowledge + local workspace target 없음이면 `kind=answer`,
     `workflow_hint=external_research`, `tool_capabilities={web_search}`.
5. `workflow_routing.should_use_generation_workflow()`는 `workflow_hint` 외에도 route validator가 붙인 구조화 flag를
   확인하되, 단일 파일 생성/기존 파일 수정은 제외한다.

검증:

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_route_validator.py tests/unit/agent/test_answer_policy.py
```

### Phase 2. Directory Target Artifact Satisfaction

수정 대상:

- `src/allCode/agent/phase_gate.py`
- `src/allCode/core/result.py`는 필요 시에만 확장한다. 우선 `RequestedArtifact.kind` 변경은 피한다.

작업:

1. `_same_artifact_target()`에 디렉터리 target 만족 규칙을 추가한다.
   - `normalized_target`이 확장자 없는 디렉터리이고 `normalized_path.startswith(normalized_target + "/")`이면 만족.
   - target이 `output/foo`이고 생성 파일이 `output/foo/README.md`, `output/foo/pkg/mod.py`이면 해당 target artifact 만족.
2. `satisfy_requested_artifacts()`에서 explicit directory target은 최소 하나 이상의 하위 파일 생성만으로 source/document/test 전체를 덮었다고 보지 않는다.
   - directory target 자체는 만족하되, prompt가 tests/README/config를 요구하면 별도 generic artifact obligation은 유지한다.
3. `unsatisfied_artifact_labels()`가 directory target을 사용자에게 파일 미발견처럼 표현하지 않도록 reason을 명확히 한다.

검증:

```bash
python -m pytest tests/unit/agent/test_phase_gate.py tests/integration/test_generation_workflow.py
```

### Phase 3. GenerationWorkflow 진입과 Plan 품질 보강

수정 대상:

- `src/allCode/agent/workflow.py`
- `src/allCode/agent/project_planner.py`
- `src/allCode/agent/task_loop_digest.py`
- `src/allCode/agent/workflow_actions.py`
- `src/allCode/agent/final_reporter.py`

작업:

1. `GenerationWorkflow.run()` 시작 시 `TaskLoopDigest`를 생성해 model planner 호출에 주입한다.
   - 원 요청 요약
   - target root
   - required artifact categories
   - 외부 패키지 금지/표준 라이브러리 제한 같은 constraints
   - validation required 여부
2. `ModelProjectPlanner._messages()`는 단순 schema 지시가 아니라 artifact obligation 기반으로 계획을 요구한다.
   - CLI entrypoint, config, registry, runner, logger, plugins, tests, README 같은 요구가 있으면 각각 파일 또는 기능으로 반영.
   - 하드코딩된 특정 프로젝트명은 금지하고, prompt-derived obligation만 사용한다.
3. `_repair_until_valid()`와 `_repair_completion_check()`에서 deterministic strategy repair 전후로 compact digest와 validation failure를 모델에 전달할 수 있는 경로를 정리한다.
   - 단, MVP 범위를 넘는 architect/editor 이중 모델 구조는 만들지 않는다.
4. `WorkflowActions.write_file()` 결과가 `CompletionEvidence`와 directory target satisfaction을 즉시 갱신하는지 확인한다.
5. `FinalReporter`는 생성/수정 파일, 검증 명령, 검증 결과, 남은 리스크를 prompt 언어로 출력한다.

검증:

```bash
python -m pytest tests/integration/test_generation_workflow.py tests/unit/agent/test_phase_gate.py
```

실모델 smoke:

```bash
allcode --workspace /private/tmp/allcode_compare_allcode --config .allCode/config.yaml --approval auto --headless "현재 작업 디렉터리의 ./output/complex_ops_platform 아래에 Python 표준 라이브러리만 사용한 작은 운영 자동화 플랫폼 프로젝트를 생성하라. 요구사항: CLI entrypoint, config loader, task registry, job runner with retry/backoff, JSONL audit logger, plugin-like command modules, pytest tests for retry/logging/config, README. 외부 패키지 사용 금지. 기존 파일 수정 금지, ./output 하위만 수정하라. 생성 후 가능한 검증 명령을 실행하고 결과를 보고하라."
```

성공 기준:

- `/private/tmp/allcode_compare_allcode/output/complex_ops_platform` 하위 실제 파일 생성.
- 생성 파일 목록과 검증 결과가 final answer에 포함.
- 파일 생성 없이 코드 블록만 반환하는 경로 차단.

### Phase 4. Source Analysis Coverage Gate와 Brief Injection

수정 대상:

- `src/allCode/agent/inspect_staging.py`
- `src/allCode/agent/source_answer_synthesis.py`
- `src/allCode/agent/final_answer_context.py`
- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/inspect_summary.py`
- `src/allCode/agent/round_runner.py`

작업:

1. `inspect_staging._evidence_complete()`를 explicit scope 기준으로 강화한다.
   - explicit directory target이 있으면 해당 target별 `source_overview_targets` 또는 observed path coverage 필요.
   - broad/truncated overview에서는 package bucket별 representative probe 최소치를 요구.
   - 단, `inspect_round_budget`에 가까워지면 bounded finalize로 전환한다.
2. `_required_representative_read_count()`는 package count와 prompt complexity를 반영하되 hard cap을 유지한다.
   - 기본 2개, broad package 4~8개, explicit multi-target은 target별 최소 1개.
3. `source_answer_synthesis.render_source_analysis_brief()` 결과를 final answer model call에 명시적으로 주입한다.
   - `final_answer_context.final_answer_call_messages()`에 optional `evidence_brief` 또는 별도 helper 추가.
   - `RoundRunner`가 inspect finalization gate를 열 때 tool results + evidence로 brief를 만들고 outgoing message에만 주입.
   - runtime transcript는 원본을 유지한다.
4. 최종 답변 지시에는 다음 섹션을 강제한다.
   - 확인한 범위
   - 패키지/디렉터리별 역할
   - 핵심 실행 흐름
   - 모듈 간 연결
   - 대표 파일 근거
   - 관찰하지 못한 범위와 한계
5. fallback summary도 같은 관찰/미관찰 범위를 표시한다.

검증:

```bash
python -m pytest tests/unit/agent/test_inspect_tool_staging.py tests/unit/agent/test_final_answer_context.py tests/unit/agent/test_inspect_summary.py
```

실모델 smoke:

```bash
allcode --headless "현재 디렉터리의 src/allCode 코드베이스를 복잡한 프로젝트 관점에서 분석하라. 코드 수정은 엄격히 금지한다. 최소한 CLI 진입점, agent loop, routing/policy, tool execution, workspace/context, memory, generation workflow, telemetry/session logging, TUI 흐름을 나누어 설명하고, 각 영역의 대표 파일과 모듈 간 호출 흐름, 설계상 강점과 리스크를 근거 중심으로 정리하라."
```

성공 기준:

- `agent`, `tools`, `workspace`, `memory`, `llm`, `tui`, `telemetry` 중 요청된 주요 영역의 대표 파일 근거 포함.
- 관찰하지 않은 영역을 관찰한 것처럼 단정하지 않음.
- 오래된 CLI flag나 추론성 설명을 observed fact로 쓰지 않음.

### Phase 5. General Answer와 Web Evidence Policy

수정 대상:

- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/intent.py`
- `src/allCode/agent/answer_policy.py`
- `src/allCode/agent/final_answer_context.py`
- `src/allCode/tools/builtin/web.py`

작업:

1. `unstable_knowledge_hint`를 추가하거나 `external_knowledge_hint`를 더 구조화한다.
   - 현재/최신/오늘/공개문서 외에 법률, 규정, 가격, 비용, 시장, 점유율, 벤치마크, KPI, 실적,
     로드맵, 2025/2026 같이 변동 가능성이 높은 범주를 감지.
   - 단순 "비교", "장단점", "설명"만으로 web route를 열지 않는다.
2. `AnswerPolicy`는 answer route를 세 가지로 분리한다.
   - stable direct answer: tools 없음.
   - external web-supported answer: web_search만 노출.
   - web unavailable answer: web unavailable evidence를 받은 뒤 한계를 명시하고 임의 수치 단정 금지.
3. web backend가 비활성화된 경우 final answer 지시에 다음을 넣는다.
   - 외부 검색을 수행하지 못했다는 한계.
   - 실시간 수치/법률/가격/시장 데이터를 확정하지 않기.
   - 안정적인 일반 원칙과 검증 필요 항목을 분리.

검증:

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_answer_policy.py tests/unit/tools/test_web_provider.py
```

실모델 smoke:

```bash
allcode --headless "복잡한 일반 질문이다. 조직이 사내 AI 코딩 에이전트를 도입할 때 개발 생산성, 보안/컴플라이언스, 지식재산권, 품질보증, 조직문화, 비용통제 관점에서 생길 수 있는 장단점을 균형 있게 분석하고, 경영진에게 제안할 90일 도입 로드맵과 핵심 KPI를 제시하라. 코드 수정이나 파일 생성은 하지 말고 최종 답변만 작성하라."
```

성공 기준:

- workspace/file tools 미노출.
- 근거 없는 수치 단정 감소.
- 웹 backend가 없으면 한계 명시.
- 웹 backend가 있으면 evidence bundle 기반으로 종합.

## 적용 후 데이터 흐름 시뮬레이션

### 시뮬레이션 A: 복잡한 프로젝트 생성

입력:

```text
./output/complex_ops_platform 아래에 표준 라이브러리 기반 운영 자동화 플랫폼 프로젝트를 생성...
```

예상 흐름:

```text
PromptConstraintExtractor
  -> directory_output_hint=True
  -> multi_artifact_hint=True
  -> project_generation_hint=True
  -> validation_requested_hint=True
ModelRouter
  -> 모델이 workflow_hint를 놓쳐도 route flags 유지
RouteValidator
  -> kind=modify
  -> workflow_hint=multi_file_generation
  -> mutate_file/run_validation capability 보정
AgentLoop
  -> should_use_generation_workflow=True
GenerationWorkflow
  -> TaskLoopDigest 포함한 ProjectPlan 생성
  -> skeleton/implementation/tests 파일 write_file 실행
  -> directory target satisfied by 하위 파일
  -> validation 실행 및 repair
FinalReporter
  -> 생성 파일, 검증 명령, 결과, 리스크 보고
```

검토 결과:

- 단일 파일 생성은 `Path(target_hint).suffix` 조건으로 `direct_file_edit`에 남는다.
- read-only가 있으면 route validator가 workflow 보정을 하지 않는다.
- 실제 파일 변경 없이 final answer만 반환하는 경로는 completion evidence gate가 차단한다.

### 시뮬레이션 B: read-only 전체 src 분석

입력:

```text
src/allCode 코드베이스를 복잡한 프로젝트 관점에서 분석. 수정 금지.
```

예상 흐름:

```text
PromptConstraintExtractor
  -> read_only_requested=True
  -> workspace_evidence_requested=True
  -> path_hints=["src", "src/allCode"...]
RouteValidator
  -> kind=inspect
  -> read/search/source overview only
RoundRunner
  -> inspect_stage source_discovery
  -> source_overview target coverage 확인
  -> targeted_read source_probe package bucket별 수행
  -> source_analysis brief 생성
  -> final answer call에 rendered brief 주입
Model final answer
  -> 관찰 범위/역할/흐름/상호작용/한계 분리
```

검토 결과:

- source_probe cap과 round budget으로 무한 탐색 방지.
- broad overview에서 최소 representative evidence를 확보하므로 main.py 한두 파일 추론으로 끝나는 경로 감소.
- 관찰하지 않은 영역은 limitation으로 남아 hallucination이 줄어든다.

### 시뮬레이션 C: 복잡한 일반 질문

입력:

```text
사내 AI 코딩 에이전트 도입의 장단점, 90일 로드맵, KPI
```

예상 흐름:

```text
PromptConstraintExtractor
  -> unstable_knowledge_hint=True for KPI/cost/business roadmap
  -> local_workspace_request=False
RouteValidator/AnswerPolicy
  -> kind=answer
  -> workflow_hint=external_research
  -> web_search only
RoundRunner
  -> web evidence 있으면 evidence 기반 synthesis
  -> web unavailable이면 stable principle + limitation + verification checklist
Final answer
  -> 수치 단정 대신 KPI 후보/측정 방법/검증 필요 항목 분리
```

검토 결과:

- 단순 개념 질문에는 `unstable_knowledge_hint`가 없으면 direct answer 유지.
- local workspace path가 있으면 web이 아니라 inspect가 우선한다.
- web backend unavailable이어도 mutation/shell/local search는 열리지 않는다.

## 구현 순서

1. Phase 1 + Phase 2를 먼저 구현한다.
   - 이유: 프로젝트 생성 실패는 라우팅과 artifact satisfaction에서 끊긴다.
2. Phase 4를 구현한다.
   - 이유: read-only 분석 품질은 stage coverage와 final synthesis 연결 문제다.
3. Phase 5를 구현한다.
   - 이유: 일반 질문 품질 개선은 routing side effect가 크므로 마지막에 안정화한다.
4. Phase 3의 dynamic repair 확장은 마지막에 적용한다.
   - 이유: `GenerationWorkflow`가 먼저 진입하고 artifact gate가 정상화되어야 repair 품질을 판단할 수 있다.

## 테스트 계획

집중 회귀:

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_route_validator.py tests/unit/agent/test_phase_gate.py
python -m pytest tests/unit/agent/test_inspect_tool_staging.py tests/unit/agent/test_final_answer_context.py tests/unit/agent/test_inspect_summary.py
python -m pytest tests/unit/agent/test_answer_policy.py tests/unit/tools/test_web_provider.py
python -m pytest tests/integration/test_generation_workflow.py
```

단계별 확장:

```bash
python -m pytest tests/unit/agent tests/unit/tools
python -m pytest tests/integration
python -m pytest
```

실모델 비교:

```bash
allcode --headless "<complex source analysis prompt>"
agy --print "<same prompt>"

allcode --workspace /private/tmp/allcode_compare_allcode --config .allCode/config.yaml --approval auto --headless "<complex project generation prompt>"
agy --print "<same prompt>"

allcode --headless "<complex general question prompt>"
agy --print "<same prompt>"
```

## 금지 사항

- 특정 테스트 프롬프트, scenario ID, 프로젝트명, `complex_ops_platform` 같은 path를 코드에 직접 매칭하지 않는다.
- 특정 모델명 또는 Wisenut endpoint 전용 분기 금지.
- read-only route에서 mutation/shell/validation tool 노출 금지.
- single-file create/edit을 multi-file generation으로 보내지 않는다.
- source analysis를 full-file dump로 해결하지 않는다.
- web backend가 없을 때 가짜 검색 결과나 근거 없는 수치를 만들지 않는다.
- `prompt_builder.py`, `round_runner.py`, `workflow.py`가 500줄을 넘는 방향의 책임 추가 금지.

## 남은 리스크

- web route 확장으로 일부 안정 지식 질문이 web-only로 갈 수 있다. `unstable_knowledge_hint`는 범주 조합과
  수치/시점 신호를 함께 보는 식으로 false positive를 줄여야 한다.
- source analysis depth를 올리면 비용과 라운드가 늘어난다. package bucket 최소치와 hard cap이 함께 필요하다.
- generation workflow에 모델 planner 의존을 늘리면 잘못된 JSON plan fallback이 늘 수 있다.
  deterministic strategy fallback은 유지해야 한다.
- agy는 검토 중 자체 테스트 실행과 파일 외부 산출을 시도할 수 있다. 비교 평가에서는 repo source 변경 여부를
  별도로 확인해야 한다.
