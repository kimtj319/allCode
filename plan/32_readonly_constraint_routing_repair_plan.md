# 32. Read-only Constraint Routing Repair Plan

## 목적

이 문서는 실제 `allcode --headless`와 `agy --print`에 동일한 읽기 전용 소스
분석 프롬프트를 입력해 비교한 결과, allCode가 read-only 요청을 `modify`
route로 오분기하고 `write_file`을 시도한 결함을 수정하기 위한 계획이다.

이번 계획의 분석 기준은 “아래 수정 방향대로 현재 코드를 고쳤을 때, read-only
분석 요청이 의도한 대로 inspect-only 흐름으로 수렴하는가”이다. 단순히 마지막
policy layer가 쓰기를 막는 것만으로는 성공으로 보지 않는다. 의도한 상태는
mutation tool schema가 모델에 노출되지 않고, artifact obligation도 생성되지
않으며, 최종 답변이 approval blocked summary가 아니라 근거 기반 분석 요약으로
나오는 것이다.

이 계획은 기존 MVP 범위를 확장하지 않는다. git 자동 커밋, MCP manager,
plugin marketplace, multi-agent, cloud sandbox, full LSP integration은 제외한다.

## 참조 계약

- `plan/00_master_implementation_guide.md`
- `plan/01_open_source_alignment_contracts.md`
- `plan/05_routing_policy_plan.md`
- `plan/06_tool_system_plan.md`
- `plan/31_terminal_paste_tool_visibility_source_analysis_plan.md`

충돌 시 `plan/00`~`12`와 `plan/01`을 우선한다.

## 공개 오픈소스 참조 기준

- Aider repo map은 전체 파일 본문을 덤프하지 않고 repository structure와 symbol
  중심 map으로 코드베이스 이해를 시작한다.
  - https://aider.chat/docs/repomap.html
- Qwen Code는 `list_directory`, `read_file`, `glob`, `grep_search`, `edit`처럼
  file-system tool 목적을 분리하고 root directory 경계 안에서 동작시킨다.
  - https://qwenlm.github.io/qwen-code-docs/en/developers/tools/file-system/
- OpenHands는 tool system을 `Action -> Observation` 계약으로 분리해 agent layer가
  action/event를 관찰 가능하게 관리한다.
  - https://docs.openhands.dev/sdk/arch/tool-system

allCode에 적용할 결론은 다음과 같다.

1. 읽기 전용 분석은 Aider식 bounded source overview/read flow로 수렴해야 한다.
2. 쓰기 action은 OpenHands식 action 단계로도 진입하지 않아야 한다.
3. Qwen Code처럼 read/search/mutation tool 목적 경계를 route schema 단계에서
   분리해야 한다.

## agy 검토 반영 요약

agy에는 코드 수정 금지, repository artifact 생성 금지, 계획 검토만 요청했다.
검토 결과 원 계획에 다음 누락이 있음을 확인했다.

1. read-only invariant를 강화해도 `PromptConstraintExtractor`가 한국어 복합
   나열형 부정문을 놓치면 하위 guard가 모두 작동하지 않는다.
   - 예: “소스 코드 수정, 파일 생성, 파일 삭제, 포맷팅 변경, 커밋은 엄격히
     금지한다”
   - `수정`과 `금지`가 가까이 붙어 있지 않아 단순 term/pattern 기반 감지가
     실패할 수 있다.
2. `ToolSchemaFilter`에서 schema 노출을 닫아도 모델이 pseudo tool-call text 또는
   schema-denied native call을 계속 출력할 수 있다. 따라서 실제 tool execution
   boundary인 `ToolCallProcessor`/`ToolExecutor`에도 read-only runtime block이
   필요하다.
3. `ModelRouter`의 structured decision에도 read-only 판단 필드를 추가해,
   deterministic extractor와 model interpretation의 OR 조건으로 최종
   `read_only_requested`를 계산하는 것이 안전하다.
4. `mutation_artifact_required()`와 `test_artifact_required()`가 routing 없이
   호출되는 경로가 남으면 read-only 요청에서도 artifact obligation이 재생성될
   수 있으므로 signature 또는 호출부 guard를 같이 보강해야 한다.
5. read-only prompt instruction은 영어 문장만으로는 부족하다. 한국어 요청에는
   “파일로 만들지 말고 최종 답변에 직접 작성”이라는 한국어 지시를 함께 넣어야
   모델의 문서 생성 오해를 줄일 수 있다.

이 피드백에 따라 아래 구현 계획은 extractor, router, phase gate, preflight,
schema filter에 더해 runtime boundary와 pseudo tool-call recovery까지 포함한다.

## 재현 결과 요약

### 프롬프트 A

```text
읽기 전용 분석이다. 소스 코드 수정, 파일 생성, 파일 삭제, 포맷팅 변경, 커밋은 엄격히 금지한다. 현재 디렉터리의 src 내 코드들이 어떤 역할을 하는지 한국어로 정리해줘.
```

- agy: 읽기 전용 분석으로 수렴. `src` 구조와 패키지 역할을 한국어로 정리.
- allCode: `routing_decided.kind = modify`.
- allCode tool call: `write_file` target `src/allCode/SUMMARY_KR.md`.
- allCode final status: `partial`, approval/policy blocked summary.

### 프롬프트 B

```text
읽기 전용 분석이다. 소스 코드 수정, 파일 생성, 파일 삭제, 포맷팅 변경, 커밋은 엄격히 금지한다. src/allCode/agent 패키지의 루프, 라우팅, 툴 실행 흐름을 한국어로 요약해줘.
```

- agy: 읽기 전용 분석으로 수렴. `loop.py`, `round_runner.py`,
  `router.py`, `tool_call_processor.py`를 근거로 요약.
- allCode: `routing_decided.kind = modify`.
- allCode tool call: `write_file` target `src/allCode/agent/README_KR.md`.
- allCode final status: `partial`, blocked summary.

## 현재 코드에서 확인된 원인 후보

### 1. ModelRouter의 read-only override가 충분히 구조화되어 있지 않음

파일: `src/allCode/agent/model_router.py`

현재 `PromptConstraintExtractor`는 `read_only_requested=True`를 잡고,
`ModelRouter._merge_constraints()`도 mutation capability를 제거한다. 하지만 실제
세션에서는 모델 routing 결과가 `kind=modify`로 남았다. 즉 read-only invariant가
최종 route object 전체를 정규화하는 단일 함수로 보장되지 않는다.

필요한 변화:

- `ModelRoutingDecision`에 `read_only_requested: bool = False`를 추가한다.
- 최종 read-only 여부는 `constraints.read_only_requested or
  model_decision.read_only_requested`로 계산한다.
- read-only constraint는 최종 merge의 마지막 단계에서 반드시 route 전체를
  sanitize해야 한다.
- sanitize 결과는 다음 불변식을 만족해야 한다.
  - `read_only_requested=True`
  - `kind in {"inspect", "answer"}`. workspace evidence/path hint가 있으면 `inspect`
  - `requires_mutation=False`
  - `requires_shell=False`
  - `requires_validation=False`
  - `workflow_hint="none"`
  - `tool_capabilities`에서 `mutate_file`, `delete_file`, `run_shell`,
    `run_validation` 제거
  - workspace evidence/path hint가 있으면 `read_file`, `search_workspace` 추가

### 2. read-only 요청에서도 artifact obligation이 만들어질 수 있음

파일:

- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/completion_gate.py`
- `src/allCode/agent/loop.py`

로그에 “아직 충족되지 않은 요청된 산출물: source:src/allCode/agent”가 나타났다.
이는 read-only 분석 요청에서도 source artifact obligation이 생겼다는 뜻이다.
read-only 분석의 `src/allCode/agent`는 생성해야 할 산출물이 아니라 읽어야 할
분석 대상이다.

필요한 변화:

- `ensure_requested_artifacts()`는 routing이 read-only이거나 `kind in {"answer",
  "inspect"}`이면 즉시 return해야 한다.
- `completion_gate.build_completion_evidence()`에서 artifact obligation 생성 전에도
  같은 guard를 둔다.
- `loop._seed_session_artifact_obligations()`도 read-only routing에서는 source/test
  artifact obligation을 seed하지 않도록 한다.

### 3. Preflight가 modify route를 받은 뒤 search/read 흐름을 시작하고, 이후 mutation
force로 이어질 수 있음

파일: `src/allCode/agent/preflight.py`

현재 `PreflightPlanner.plan()`은 routing.kind가 `modify`이면 mutation discovery
search를 수행할 수 있다. read-only 오분기가 발생하면 preflight가 수정 요청처럼
context를 구성하고, 이후 `should_force_mutation_after_inspection()`가 mutation action
prompt를 넣을 수 있다.

필요한 변화:

- route sanitize가 주된 해결책이다.
- 추가 방어로 `PreflightPlanner.plan()` 시작 시 `routing.read_only_requested`이면
  mutation discovery, conditional delete, force mutation 관련 분기를 모두 건너뛰고
  inspect용 preflight만 허용한다.
- `should_force_mutation_after_inspection()`는 `routing.read_only_requested`이면
  항상 False를 반환해야 한다.

### 4. Tool schema filter는 policy 결과에 의존하지만 read-only invariant를 별도
검증하지 않음

파일: `src/allCode/agent/tool_schema_filter.py`

현재 policy가 잘 동작하면 mutation schema가 닫히지만, 이번 결함은 더 앞단에서
route가 `modify`로 남은 데서 시작된다. safety invariant를 schema exposure 직전에도
검증하면 비슷한 회귀를 더 빨리 차단할 수 있다.

필요한 변화:

- `schemas_for_routing()`에서 `routing.read_only_requested`이면 `write_file`,
  `patch_file`, `delete_path`, `run_command`, `run_tests`를 강제로 제거한다.
- 이 guard는 policy의 중복이 아니라 schema exposure invariant다.

### 5. PromptBuilder가 read-only 분석과 문서 작성 요청의 경계를 충분히 강제하지 않음

파일: `src/allCode/agent/prompt_builder.py`

모델은 “정리해줘/요약해줘”를 “README_KR.md 또는 SUMMARY_KR.md 작성”으로 해석했다.
read-only route에서는 “answer in chat, do not create summary files”가 명시되어야
한다.

필요한 변화:

- routing instruction에서 `read_only_requested`이면 다음을 명시한다.
  - “Return the summary in the final answer, not as a new file.”
  - “Do not create README/SUMMARY/report files.”
  - “Only read/search/source overview tools may be used.”
- 단, 특정 파일명이나 프로젝트명을 하드코딩하지 않는다. `README`, `SUMMARY` 같은
  일반적인 report/document artifact 유형을 예시로 다루되, rule logic에는 직접
  path 예외를 넣지 않는다.

### 6. PromptConstraintExtractor가 한국어 나열형 금지 문장을 놓칠 수 있음

파일:

- `src/allCode/agent/prompt_constraints.py`
- `src/allCode/agent/prompt_safety.py`

현재 read-only 감지는 term matching과 pattern matching을 조합한다. 그러나
“수정, 생성, 삭제, 커밋은 금지”처럼 여러 금지 대상이 나열된 경우, 첫 금지 대상과
부정 종결 표현 사이가 길어져 단순 패턴이 실패할 수 있다.

필요한 변화:

- 금지 대상 token set:
  - 한국어: `수정`, `변경`, `편집`, `삭제`, `제거`, `작성`, `생성`, `커밋`,
    `포맷`, `포맷팅`, `파일 변경`, `파일 생성`
  - 영어: `edit`, `modify`, `change`, `write`, `create`, `delete`, `remove`,
    `commit`, `format`
- 부정/금지 종결 token set:
  - 한국어: `금지`, `불가`, `하지 마`, `하지마`, `마라`, `않`, `안 됨`,
    `안됨`
  - 영어: `do not`, `don't`, `no`, `must not`, `never`
- 한 문장 또는 clause 안에서 금지 대상 1개 이상과 부정/금지 종결이 함께 나타나면
  read-only로 본다.
- 이 로직은 특정 테스트 문장을 하드코딩하지 않고 token set + clause window 기반
  helper로 구현한다.
- 오타까지 과도하게 커버하려고 fuzzy matching을 도입하지 않는다. 허용 범위는
  일반적인 띄어쓰기/쉼표/조사 변형까지로 제한한다.

### 7. Runtime boundary에서 read-only mutation 실행을 마지막으로 차단해야 함

파일:

- `src/allCode/agent/tool_call_processor.py`
- `src/allCode/tools/executor.py`
- `src/allCode/agent/round_response_handler.py`

현재 policy가 마지막 방어를 수행하지만, 계획 목표는 mutation action이 실제 실행
경계에도 도달하지 않는 것이다. 그래도 안전상 실행 경계에서 한 번 더 차단해야 한다.

필요한 변화:

- `ToolCallProcessor.execute()` 초기에 `routing.read_only_requested`이고 tool category가
  mutation/shell/validation이면 즉시 schema-denied 또는 policy-denied `ToolResult`를
  반환한다.
- `ToolExecutor.execute()`도 defense-in-depth로 동일 조건을 확인한다. 이 단계는
  정상 경로에서는 실행되지 않아야 하며, 실행되면 telemetry에 invariant violation을
  남긴다.
- `RoundResponseHandler._pseudo_tool_call()`은 read-only routing에서 pseudo mutation
  call text가 반복되면 blocked approval summary 대신 read-only final answer request
  또는 grounded inspect summary로 회복한다.
- 차단 메시지는 사용자에게 “위험한 요청”이라고 단정하지 않는다. 사용자는 이미
  read-only를 요청했으므로 “파일 생성/수정 요청으로 해석된 도구 호출을 무시하고
  읽기 전용 분석으로 계속 진행한다”에 가깝게 표현한다.

## 수정 목표 상태

read-only source analysis prompt가 들어오면 다음 흐름이어야 한다.

1. `PromptConstraintExtractor`가 `read_only_requested=True`,
   `workspace_evidence_requested=True`, `path_hints`를 추출한다.
2. `ModelRouter`가 모델 응답이 `modify`여도 최종 `RoutingDecision`을 `inspect`로
   sanitize한다.
3. `RoutingDecided` 이벤트에는 `kind=inspect`, `requires_mutation=False`,
   `tool_capabilities={"read_file", "search_workspace"}`가 남는다.
4. preflight 또는 inspect staging은 `source_overview`, `list_tree`, `glob_files`,
   `read_file`, `search_files`만 사용한다.
5. 모델이 `write_file`, `patch_file`, `delete_path`, `run_command`, `run_tests`를
   호출하려 해도 해당 schema는 노출되지 않는다. 잘못된 tool-call text가 나와도
   runtime block 또는 schema denial 후 read-only finalization으로 회복한다.
6. `CompletionEvidence.requested_artifacts`에는 source/test/document/validation
   obligation이 생성되지 않는다.
7. 최종 답변은 한국어 source 분석 요약이다. approval blocked summary가 아니다.
8. 실제 파일 변경은 0개다.

## 구현 계획

### Phase 0. 회귀 테스트로 실패 조건 고정

수정 대상 테스트:

- `tests/unit/agent/test_model_router.py`
- `tests/unit/agent/test_prompt_constraints.py`
- `tests/unit/agent/test_phase_gate.py`
- `tests/unit/agent/test_preflight.py`
- `tests/unit/agent/test_tool_schema_filter.py` 신규 또는 기존 보강
- `tests/unit/agent/test_tool_call_processor_readonly.py` 신규 후보
- `tests/integration/test_readonly_source_analysis.py`
- `tests/quality` 또는 prompt matrix read-only scenario 보강

추가 테스트:

1. 모델 router가 `modify + mutate_file` JSON을 반환해도, prompt에 read-only와
   workspace evidence가 있으면 최종 route는 `inspect`다.
2. 한국어 “정리해줘/요약해줘/작성해줘”가 있어도 “수정/생성/삭제 금지”가 함께 있으면
   `mutation_requested_hint=False`, `requires_mutation=False`다.
3. 한국어 나열형 부정문 “수정, 생성, 삭제, 커밋은 금지”가
   `read_only_requested=True`로 추출된다.
4. `ensure_requested_artifacts()`는 read-only routing에서 artifact를 추가하지 않는다.
5. `PreflightPlanner.plan()`은 read-only routing에서 delete/write/mutation discovery
   preflight를 만들지 않는다.
6. `ToolSchemaFilter.schemas_for_routing()`은 read-only routing에서 mutation, shell,
   validation schema를 노출하지 않는다.
7. `ToolCallProcessor`는 read-only routing에서 mutation native tool call이 들어오면
   실행하지 않고 invariant-denied result를 반환한다.
8. integration: fake model이 read-only 요청에서 `write_file`을 호출하려 해도
   실제 실행되지 않고, 최종 답변은 blocked approval summary가 아니라 read-only 분석
   summary 또는 schema-denied 회복 답변이다.

### Phase 1. RoutingDecision sanitizer 추가

수정 대상:

- `src/allCode/agent/model_router.py`
- 필요 시 신규 `src/allCode/agent/route_safety.py`

구현:

- `sanitize_read_only_route(decision, constraints)` 같은 작은 pure function을 만든다.
- `_merge_constraints()`와 `_safe_fallback()`의 return 직전에 동일하게 호출한다.
- 가능하면 `RoutingDecision`을 만든 뒤 sanitize하는 방식으로 구현해 중복 조건을 줄인다.
- sanitizer는 provider/model 결과와 무관하게 safety invariant를 최종 적용한다.
- `ModelRoutingDecision`의 `read_only_requested`와 `PromptConstraints`의
  `read_only_requested`를 OR로 병합한다.

주의:

- 특정 문장, 특정 파일명, 특정 테스트 프롬프트를 검사하지 않는다.
- `read_only_requested`가 False인 실제 modify 요청의 direct_file_edit,
  multi_file_generation 흐름을 깨지 않는다.

### Phase 2. Artifact obligation guard

수정 대상:

- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/completion_gate.py`
- `src/allCode/agent/loop.py`

구현:

- `ensure_requested_artifacts()` 시작부:
  - routing이 있고 `routing.read_only_requested`이면 return
  - routing.kind가 `answer` 또는 `inspect`이면 return
- `mutation_artifact_required()`와 `test_artifact_required()`도 read-only route를
  받을 수 있는 helper로 확장하거나, 호출부에서 guard한다.
- `loop._seed_session_artifact_obligations()`은 routing을 인자로 받거나 호출 전 guard해
  read-only turn에는 session artifact obligation을 seed하지 않는다.

주의:

- 기존 modify/generation/test-authoring obligation은 유지해야 한다.
- source path가 언급됐다는 이유만으로 read-only 분석 대상이 생성 산출물이 되면 안 된다.

### Phase 3. Preflight read-only guard

수정 대상:

- `src/allCode/agent/preflight.py`

구현:

- `PreflightPlanner.plan()`에서 `routing.read_only_requested`일 때는 inspect-safe
  preflight만 허용한다.
- `should_force_mutation_after_inspection()`는 `routing.read_only_requested`이면 False.

주의:

- read-only inspect에서 target file read preflight는 유지 가능하다.
- conditional delete, mutation discovery search, force mutation prompt는 금지한다.

### Phase 4. Tool schema exposure invariant

수정 대상:

- `src/allCode/agent/tool_schema_filter.py`
- 필요 시 `src/allCode/agent/policy.py` 테스트 보강

구현:

- `routing.read_only_requested`이면 schema list에서 mutation/shell/validation tool을
  강제 제거한다.
- 이 invariant는 policy와 중복되지만, 모델이 사용할 수 있는 schema 자체를 줄이기
  위한 별도 방어다.

주의:

- read-only인데 external knowledge가 필요한 경우 web_search는 no-network가 없으면
  유지 가능하다.
- local workspace request이면 web_search보다 source_overview/read/search를 우선한다.

### Phase 5. Prompt instruction 보강

수정 대상:

- `src/allCode/agent/prompt_builder.py`

구현:

- `routing.read_only_requested` branch에 “chat answer로 요약하라, 파일을 만들지 말라”
  지시를 추가한다.
- inspect route branch에도 “source analysis 결과는 final answer로 반환한다”를
  명시한다.
- 한국어 prompt로 감지되면 한국어 지시도 추가한다.
  - “파일로 생성하지 말고 최종 답변에 직접 작성하십시오.”
  - “파일 생성, 수정, 삭제 도구를 호출하지 마십시오.”

주의:

- 프롬프트만으로 안전을 보장하지 않는다. Phase 1~4의 code invariant가 주 방어다.

### Phase 6. Runtime boundary와 pseudo tool-call recovery 보강

수정 대상:

- `src/allCode/agent/tool_call_processor.py`
- `src/allCode/tools/executor.py`
- `src/allCode/agent/round_response_handler.py`
- `src/allCode/core/events.py` 필요 시 debug/status event 추가

구현:

- `ToolCallProcessor.execute()`에서 read-only invariant violation을 실행 전에 거부한다.
- `ToolExecutor.execute()`에서도 같은 조건을 방어적으로 거부한다.
- 거부 결과 metadata에는 `read_only_invariant_violation=True`,
  `blocked_tool=<tool_name>`, `category=<category>`를 남긴다.
- `RoundResponseHandler`는 read-only pseudo mutation call 반복을 일반 approval
  failure가 아니라 inspect finalization recovery로 처리한다.

주의:

- 사용자가 read-only라고 했는데 모델이 write_file을 호출한 상황은 사용자의 위험한
  요청이 아니다. 사용자-facing 문구는 “요청하신 읽기 전용 조건 때문에 파일 변경
  도구 호출을 무시했습니다”로 표현한다.
- telemetry/debug에는 violation을 남긴다.

### Phase 7. Integration/real-model 검증

검증 명령:

```bash
python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_model_router.py tests/unit/agent/test_phase_gate.py tests/unit/agent/test_preflight.py
python -m pytest tests/unit/agent/test_tool_schema_filter.py tests/unit/agent/test_policy.py tests/unit/agent/test_tool_call_processor_readonly.py
python -m pytest tests/integration/test_readonly_source_analysis.py tests/integration/test_mock_agent_loop.py
python -m pytest tests/unit/agent tests/unit/tools
python -m pytest
```

실제 headless smoke:

```bash
allcode --headless "읽기 전용 분석이다. 소스 코드 수정, 파일 생성, 파일 삭제, 포맷팅 변경, 커밋은 엄격히 금지한다. 현재 디렉터리의 src 내 코드들이 어떤 역할을 하는지 한국어로 정리해줘."
allcode --headless "읽기 전용 분석이다. 소스 코드 수정, 파일 생성, 파일 삭제, 포맷팅 변경, 커밋은 엄격히 금지한다. src/allCode/agent 패키지의 루프, 라우팅, 툴 실행 흐름을 한국어로 요약해줘."
```

성공 기준:

- 세션 로그의 `routing_decided.kind`가 `inspect`다.
- `write_file`, `patch_file`, `delete_path`, `run_command`, `run_tests` action이 없다.
- `requested_artifacts`가 비어 있거나 read-only evidence만 포함한다.
- 최종 답변은 한국어 분석 요약이다.
- final status는 모델이 정상 final answer를 내면 `success`, reasoning-only fallback이면
  `partial`일 수 있으나 blocked approval summary는 실패로 본다.
- 모델이 pseudo mutation call을 출력해도 최종 답변은 read-only 분석 흐름으로
  회복한다.
- `git status --short`에서 테스트 실행 산출물 외 실제 source 변경이 없어야 한다.

## 남은 리스크

- 실제 모델이 계속 pseudo tool-call text로 `write_file`을 출력할 수 있다. schema를
  닫아도 parser가 pseudo tool-call로 처리하면 recovery prompt 품질이 중요하다.
  Phase 6에서 이 경로를 별도 회귀 테스트로 고정한다.
- `작성해줘`는 한국어에서 “문서 파일 작성”과 “답변 작성”을 모두 의미한다.
  read-only 금지가 있으면 답변 작성으로 해석해야 하지만, 금지가 없으면 기존
  generation/document creation 흐름을 깨면 안 된다.
- read-only + “테스트 결과를 알려줘” 같은 요청은 shell/validation 금지와 정보 요구가
  충돌한다. 이 경우 실행하지 않고 “실행은 금지되어 있으므로 기존 근거만 확인”하는
  답변으로 수렴해야 한다.
- 현재 모델 adapter 특성상 reasoning-only fallback이 남을 수 있다. 이 계획은
  routing/tool exposure 문제를 닫는 것이며 모델 native final answer 품질은 별도
  보강 대상이다.
- `ModelRoutingDecision.read_only_requested`를 추가해도 모델 판단을 신뢰하지 않는다.
  deterministic extractor와 최종 sanitizer가 authoritative source다.
- 한국어 오타나 매우 완곡한 금지 표현은 여전히 놓칠 수 있다. MVP에서는 일반
  띄어쓰기/쉼표/나열형 부정문까지를 수용 범위로 둔다.

## agy 검토 요청 포인트

agy에는 코드 수정 금지, artifact 생성 금지, 계획 검토만 요청한다.

검토 요청:

1. 위 수정 방향이 현재 코드 구조에서 read-only 오분기를 실제로 막는가?
2. sanitizer를 ModelRouter 하나에만 두는 것이 충분한가, 아니면 schema/filter와
   phase gate에도 invariant가 필요한가?
3. read-only 요청에서 artifact obligation을 막을 때 generation workflow나 test
   authoring 회귀가 생길 가능성이 있는가?
4. 더 좋은 테스트 수용 기준이 있는가?
