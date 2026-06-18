# 리팩터링 계획서 — 통합 에이전트 루프 (Unified Agent Loop, "A안")

> 브랜치: `refactor/unified-agent-loop` (base: `main`)
> 목표: Codex/Claude Code처럼 **단일 ReAct 루프 + 전체 도구 상시 노출 + 모델이 직접 판단**하는 구조로 전환한다. `RouteKind`는 *경로를 잠그는 게이트*에서 *프롬프트 강조용 소프트 힌트*로 강등한다.

---

## 1. 배경과 문제 정의

현재 allCode는 **선(先)분류 → 경로 고정** 구조다.

1. `RuleBasedRouter`(키워드) + `ModelRouter`(LLM)가 `RouteKind ∈ {answer, inspect, modify, operate}`로 분류한다.
2. 그 `kind`가 세 가지를 동시에 좌우한다:
   - **도구 필터링** — `ToolPolicy.allowed_registered_tool_names` / `tool_schemas_for_routing`가 kind에 따라 사용 가능한 도구를 잠근다.
   - **파이프라인 선택** — `modify`는 `GenerationWorkflow`(skeleton→impl→tests→validate→repair), 나머지는 round-runner 루프.
   - **phase-gate / validation 강제** — kind 기반으로 단계 전이와 검증 의무가 결정된다.

**결과적 결함**: LLM이 한 번 오분류하면(예: 실시간 주가 질문을 `inspect`로) 그 턴은 *읽기 도구만 쥔 채 웹 도구 없이* 자기 소스를 무한 probe하다 loop guard에 막힌다. **복구 경로가 없다.** 문제의 본질은 분류 유무가 아니라 분류의 **구속력(binding)과 비복구성**이다.

### 결합 범위 (이번 리팩터의 표면적)
`RouteKind / routing.kind / RoutingDecision / requires_* / tool_schemas_for_routing / allowed_registered_tool_names`를 참조하는 파일: **44개** (`src/allCode/` 기준). 기능군별 분류:

| 기능군 | 파일 |
|---|---|
| **분류/라우팅** | `router.py`, `model_router.py`, `model_router_prompt.py`, `model_router_schema.py`, `model_router_safety.py`, `route_validator.py`, `intent.py`, `intent_terms.py`, `intent_frame.py`, `preflight.py` |
| **루프 오케스트레이션** | `loop.py`, `round_runner.py`, `round_tool_handler.py`, `round_response_handler.py`, `round_text_response.py` |
| **도구 게이팅** | `policy.py`, `tool_call_processor.py`, `tool_schema_filter.py`, `tools/executor.py` |
| **phase-gate** | `phase_gate.py`, `phase_gate_artifacts.py` |
| **생성 워크플로** | `workflow.py`, `workflow_actions.py`, `workflow_digest.py`, `workflow_repair.py`, `workflow_routing.py` |
| **검증** | `validation_controller.py`, `validation_runner.py`, `validation_repair.py`, `revalidation.py`, `related_tests.py`, `completion_gate.py` |
| **답변/마무리** | `answer_policy.py`, `answer_prompt.py`, `answer_scope_guard.py`, `final_answer_format.py`, `finalization.py`, `grounding.py`, `source_answer_guard.py`, `source_package_role_guard.py`, `web_finalization.py`, `turn_completion.py` |
| **inspect/프롬프트/기타** | `inspect_staging.py`, `prompt_builder.py`, `prompt_sections.py`, `task_loop_digest.py`, `recovery.py` |

---

## 2. 목표 아키텍처

```
사용자 프롬프트
      │
      ▼
[단일 에이전트 루프 (round-runner 확장)]
  - 시스템 프롬프트가 "일반질문 / 코드분석 / 코드구현·수정 / 기타"를 모델이
    스스로 판단하도록 안내 (게이트가 아니라 안내)
  - 전체 도구 상시 노출: read_file, source_probe, search,
    write_file, patch_file, run_command, run_tests, web_search, update_plan …
  - 모델이 매 스텝 도구를 선택·교정 (ReAct). 잘못 판단해도 다음 스텝에 복구
      │
      ▼
[횡단 관심사 — 도구/이벤트 레벨로 이동]
  - 승인/샌드박스: 도구 실행 시점 (ApprovalManager, shell_sandbox) — 그대로 유지
  - 검증: 모델이 run_tests를 호출 + 턴 종료 후 항상-켜짐 경량 검증
    (compileall / pyflakes-lite) — route 의무가 아니라 도구·후처리
  - 완료 판정: 단일 finalization 경로 (어떤 도구가 돌았든 동일)
  - 진행 표시: 결정론적 TurnPlan (이미 구현됨, route kind만 소비)
```

핵심 원칙 (Codex/Claude의 교훈):
- **P1. 경로를 잠그지 않는다.** 도구는 항상 전부 노출.
- **P2. 분류는 모델의 행위다.** 별도 게이트가 아니라 모델이 도구를 고르는 것 자체가 분류.
- **P3. 모든 단계에서 그린 유지.** strangler-fig: 새 경로를 플래그 뒤에 두고, 단계별로 구(舊) 경로를 흡수→삭제.
- **P4. 횡단 관심사는 도구/이벤트 레벨로.** 승인·샌드박스·검증·완료판정을 route에서 분리.

---

## 3. 전환 전략 (Strangler-Fig + 피처 플래그)

- 신규 설정 `config.agent.unified_loop: bool = False` 추가. 개발 중에는 구·신 경로가 공존, 단계별로 신 경로가 구 경로를 흡수.
- 각 Phase 종료 시 **전체 테스트 그린**이 불변식. 신 경로는 플래그-ON 테스트로, 구 경로는 기존 테스트로 동시에 검증.
- Phase 0에서 **특성화(characterization) 테스트**를 먼저 깔아, 8개 카테고리 프롬프트의 현재 동작을 골든으로 고정 → 신 경로의 **행위 동등성(parity)** 을 증명.
- 마지막 Phase에서 기본값을 ON으로 뒤집고, 구 경로·죽은 코드·플래그를 제거.

---

## 4. 단계별 상세 계획 (우선순위 순)

각 Phase: **목적 → 변경 파일 → 작업 항목 → 리스크 → 테스트 → 종료 기준(Exit)**.

### Phase 0 — 안전망 & 스캐폴딩 (선행 필수)
**목적**: 동등성 증명 기반과 플래그를 먼저 깐다. 행위 변경 0.
- 변경: `config/schema.py`(`AgentConfig.unified_loop` 추가), `docs/`(본 문서), `tests/`(특성화 테스트 신설).
- 작업:
  1. `config.agent.unified_loop` 플래그 추가 (기본 False), `runtime.py`에서 읽어 `AgentLoop`에 전달할 통로만 마련.
  2. 8개 카테고리(일반질문/멀티턴/웹서치/대형분석/멀티턴분석/대형수정/대형생성/멀티턴생성) + 이번 주가 프롬프트에 대한 **라우팅·턴 결과 골든 테스트** 작성 (현재 동작 스냅샷).
  3. 통합 시스템 프롬프트 초안 + 4-범주 안내 문구 초안 작성 (`prompt_sections.py`에 신규 섹션, 플래그-ON일 때만).
- 리스크: 낮음 (행위 무변경).
- 테스트: 신규 골든 테스트가 현재 동작을 통과. 전체 스위트 그린.
- Exit: 플래그 존재, 골든 베이스라인 확보.

### Phase 1 — 도구 잠금 해제 (최고 레버리지·최저 리스크)
**목적**: route가 도구를 잠그지 않게 한다. 이 하나로 "inspect가 웹 못 씀 / 무한 probe" 버그군이 해소된다.
- 변경: `policy.py`, `tool_schema_filter.py`, `tool_call_processor.py`(`tool_schemas_for_routing`), `tools/executor.py`, `round_runner.py`(allowed_only 사용처).
- 작업:
  1. 플래그-ON일 때 `tool_schemas_for_routing`가 **등록된 전체 도구**(검증 probe 포함)를 반환하도록. route별 `allowed_registered_tool_names` 필터를 우회.
  2. `web_search`(외부 지식 도구)를 answer/inspect/operate 모든 모드에서 상시 노출.
  3. 도구 노출 변경이 phase-gate의 `allowed_tool_names`와 충돌하지 않도록, 플래그-ON에서는 phase-gate의 도구 제한을 "권고"로만 (Phase 4의 사전 작업).
- 리스크: 중. 도구가 많아지면 모델이 산만해질 수 있음 → 시스템 프롬프트로 모드별 권장 도구를 *안내*.
- 테스트: 플래그-ON에서 주가 프롬프트가 source_probe 루프 대신 web_search/answer로 가는지; 기존 inspect/modify 골든이 깨지지 않는지.
- Exit: 오분류해도 도구 차원에서 self-correct 가능.

### Phase 2 — 분류를 4-범주 소프트 힌트로 통합
**목적**: 사용자가 요청한 "모델이 직접 4분류"를 1급으로 만들되 *비구속*.
- 변경: `model_router.py`, `model_router_prompt.py`, `model_router_schema.py`, `model_router_safety.py`, `route_validator.py`, `router.py`, `intent*.py`, `loop.py`.
- 작업:
  1. 분류 출력 스키마를 `{general | analyze | implement | other}` 4-범주 + 신뢰도로 재정의 (기존 4 kind와 1:1 매핑: answer→general, inspect→analyze, modify→implement, operate→other).
  2. 분류 결과를 **프롬프트 강조 + 진행표시(TurnPlan)** 용도로만 사용. 도구·파이프라인 결정에서 분리.
  3. `loop.py:209-215`의 좁은 inspect→answer 교정 가드 제거(통합 루프에선 불필요). 구 경로용으로만 잔존.
  4. (구 경로 호환) `RuleBasedRouter`/`intent_terms`는 플래그-OFF 경로의 텔레메트리·크로스체크로만 유지.
- 리스크: 중. 분류 품질이 곧 프롬프트 강조 품질 → 회귀 테스트로 카테고리 정확도 추적.
- 테스트: 4-범주 분류 정확도 테스트(8 카테고리 + 주가/실시간 프롬프트). 분류가 틀려도 턴이 성공하는지(P1 덕분).
- Exit: 분류는 힌트, 도구는 자유.

### Phase 3 — 파이프라인 단일화 (가장 큰 작업)
**목적**: `modify`(GenerationWorkflow)와 inspect/operate/answer를 **하나의 루프**로 수렴.
- 변경: `workflow.py`, `workflow_actions.py`, `workflow_digest.py`, `workflow_repair.py`, `workflow_routing.py`, `loop.py`(`should_use_generation_workflow` 분기), `round_runner.py`, `round_tool_handler.py`.
- 작업:
  1. GenerationWorkflow의 단계(skeleton/impl/tests/validate/repair)를 **통합 루프 안에서 모델이 호출하는 도구·행위**로 재구성: 파일 쓰기=`write_file`, 검증=`run_tests`, 리페어=루프 반복.
  2. "신규 다중 파일 생성"의 강점(계획→스캐폴드→테스트우선→수렴)은 **선택적 헬퍼 도구**(예: `scaffold_project` 또는 planner 호출)로 노출 — 모델이 *필요하면* 부른다. 강제 파이프라인 아님.
  3. 플래그-ON: 모든 turn이 통합 루프로. 플래그-OFF: 기존 `should_use_generation_workflow` 분기 유지.
  4. N-best planner·수렴 로직(이미 구현)은 헬퍼 도구 내부로 이전.
- 리스크: 높음. 대형 생성 품질 회귀 위험 → Phase 0 골든 + 라이브 생성 평가(headless)로 가드.
- 테스트: 대형 생성/멀티턴 생성 카테고리의 산출물 동등성(파일 수·테스트 통과·완료판정). 기존 `tests/integration/test_generation_workflow.py` 플래그-ON 버전.
- Exit: 단일 루프가 생성·분석·수정·답변을 모두 처리.

### Phase 4 — phase-gate / validation을 도구·후처리로 강등
**목적**: 단계 전이·검증 의무를 route가 아니라 증거/도구가 끌도록.
- 변경: `phase_gate.py`, `phase_gate_artifacts.py`, `validation_controller.py`, `validation_runner.py`, `validation_repair.py`, `revalidation.py`, `related_tests.py`, `completion_gate.py`.
- 작업:
  1. phase-gate의 하드 route-keyed 전이를 **소프트 넛지**(시스템 프롬프트 + 경량 완료 체크)로 대체. "mutation 후 read 강제" 같은 규칙은 권고로.
  2. 검증은 (a) 모델이 `run_tests`를 호출 + (b) 턴 종료 후 **항상-켜짐 경량 검증**(compileall/pyflakes-lite, 이미 존재)으로. route별 검증 의무 제거.
  3. 완료 판정(`completion_gate`)을 route 독립적으로: "요청이 충족됐는가"를 증거 기반으로 판단.
- 리스크: 높음. 수정/생성의 "검증 누락" 회귀 위험 → 후처리 검증을 항상-켜짐으로 두어 안전망 유지.
- 테스트: 수정/생성 턴이 검증 단계를 여전히 거치는지(도구 호출 또는 후처리). repair 루프 동작.
- Exit: 검증·완료가 route와 무관하게 동작.

### Phase 5 — 답변/마무리 경로 단일화
**목적**: 어떤 도구가 돌았든 동일한 finalization.
- 변경: `answer_policy.py`, `answer_prompt.py`, `answer_scope_guard.py`, `final_answer_format.py`, `finalization.py`, `grounding.py`, `source_answer_guard.py`, `source_package_role_guard.py`, `web_finalization.py`, `turn_completion.py`, `inspect_staging.py`.
- 작업:
  1. inspect 전용 마무리(`inspect_staging`, source 답변 가드)와 web 전용 마무리(`web_finalization`)와 일반 답변(`answer_*`)을 **하나의 finalization**으로 수렴. 증거(읽은 파일/웹 결과/수정 내역)를 통합 근거로.
  2. route-keyed 가드들을 "증거 종류"-keyed로 전환 (소스 근거가 있으면 소스 인용, 웹 근거가 있으면 출처 등).
- 리스크: 중. 답변 품질 회귀 → 카테고리별 답변 골든.
- 테스트: 일반/웹/분석 답변의 형식·근거 동등성.
- Exit: 단일 finalization.

### Phase 6 — RouteKind 하드 결합 제거 & 데드코드 정리
**목적**: 잠금형 분기·구 파이프라인·죽은 가드 삭제.
- 변경: 위 전 기능군에서 플래그-OFF 전용 코드 제거. `RouteKind`는 (유지한다면) 순수 힌트 enum으로 축소.
- 작업:
  1. `should_use_generation_workflow`, route별 도구 필터, inspect/operate 전용 분기 제거.
  2. `intent_terms.py`/`RuleBasedRouter`는 분류 힌트로만 남기거나 제거(LLM 분류로 일원화 시).
  3. pyflakes-lite로 데드 import/심볼 정리.
- 리스크: 중(삭제 위험). 단계적 삭제 + 그린 유지.
- 테스트: 전체 스위트 그린, 정적 검사 0건.
- Exit: 구 경로 코드 부재.

### Phase 7 — 기본값 전환 & 마무리
**목적**: 통합 루프를 기본으로.
- 작업:
  1. `unified_loop` 기본값 True로.
  2. 8 카테고리 + 실시간 프롬프트 **라이브 평가**(headless) 통과 확인.
  3. 플래그 및 잔존 분기 제거, 문서/AGENTS.md 갱신.
- Exit: 통합 루프가 유일 경로, 플래그 제거.

---

## 5. 의존성·순서 근거
- **P1(도구 잠금 해제)** 이 가장 먼저인 이유: 단독으로 관측된 버그를 해소하고, 이후 단계가 "도구는 이미 자유"라는 전제 위에서 안전해진다.
- **P3(파이프라인 단일화)** 와 **P4(검증 강등)** 가 가장 무겁고 위험 → 중반에 배치하고 항상-켜짐 검증을 안전망으로.
- **P5/P6** 는 정리 단계로 후반.
- 모든 단계는 플래그로 격리되어 **언제든 main 머지 가능**(부분 진행 상태도 그린).

## 6. 리스크 & 완화
| 리스크 | 완화 |
|---|---|
| 대형 생성 품질 회귀 | Phase 0 골든 + headless 라이브 평가 + 생성 헬퍼 도구로 강점 보존 |
| 검증 누락 | 항상-켜짐 후처리 검증(compileall/pyflakes-lite)을 route와 무관하게 유지 |
| 도구 과다로 모델 산만 | 시스템 프롬프트의 모드별 권장 도구 안내(게이트 아님) |
| 대규모 삭제 사고 | strangler-fig + 단계별 그린 + 플래그 롤백 |
| 분류 정확도 저하 | 4-범주 회귀 테스트, 단 오분류해도 self-correct(P1) |

## 7. 테스트 전략
- **특성화(골든)**: Phase 0에서 8 카테고리 + 주가 프롬프트 동작 고정.
- **단위**: 각 Phase 변경 모듈의 단위 테스트(플래그-ON/OFF 양쪽).
- **통합**: 라우팅 회귀(주가/실시간 포함), 생성 워크플로 동등성, 검증/리페어 루프.
- **라이브(headless)**: Phase 3/4/7에서 실제 모델로 대형 분석·수정·생성 스모크.
- 불변식: 매 커밋 `pytest tests/unit tests/integration` 그린 + pyflakes-lite 0건.

## 8. 롤백
- 각 Phase는 독립 커밋. 문제가 생기면 `unified_loop=False`로 즉시 구 경로 복귀(코드 삭제 전 Phase 6까지는 무손실 롤백 가능).
- Phase 6 이후엔 브랜치 revert로 롤백.

## 9. 산출물 체크리스트
- [ ] Phase 0: 플래그 + 골든 베이스라인
- [ ] Phase 1: 전체 도구 상시 노출
- [ ] Phase 2: 4-범주 소프트 분류
- [ ] Phase 3: 단일 루프(생성 흡수)
- [ ] Phase 4: 검증/게이트 강등
- [ ] Phase 5: finalization 단일화
- [ ] Phase 6: RouteKind 결합 제거
- [ ] Phase 7: 기본값 전환 + 플래그 제거
