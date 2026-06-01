# 14. agy 2차 토론 및 review 반영 요약

## 입력 자료

- `review/plan_review_report.md`
- `plan/00` ~ `plan/09`
- `plan/13_agy_review_feedback.md`

## agy 2차 판단

agy는 review 보고서의 P0/P1/P2가 대체로 타당하다고 판단했다. 특히 다음 항목은 전체 구현 성공률에 직접 영향을 주므로 계획에 반영해야 한다고 보았다.

1. 출력 토큰 한계 대비 중단/재개 규칙
2. Textual worker lifecycle과 EventBus backpressure 계약
3. Pydantic 모델 필드와 EventBus Protocol 명세
4. `patch_file` search/replace schema
5. pyproject, config, entrypoint 계약
6. session persistence, partial JSON parsing, path sandboxing

## 반영 내용

- `00_master_implementation_guide.md`: pyproject, config, OneCLI 참조 패턴 매핑 추가
- `03_core_contracts_plan.md`: Pydantic v2 필드 계약과 EventBus Protocol 추가
- `04_llm_loop_plan.md`: partial JSON parsing과 loop detection pseudocode 추가
- `05_routing_policy_plan.md`: RoutingDecision 계약 추가
- `06_tool_system_plan.md`: patch schema와 shell 실행 계약 추가
- `07_workspace_context_plan.md`: workspace state event와 PathPolicy 계약 추가
- `10_tui_app_plan.md`: Textual worker lifecycle 계약 추가
- `12_mvp_execution_plan.md`: suspend/resume 규칙, 분할 요청 전략, 전체 데이터 흐름 추가
- `02_config_entrypoint_plan.md`: config, entrypoint, dependency 실행 계획 추가

## 최종 권고

GPT-5.5에게 한 번에 구현 요청을 넣을 때는 `00`~`12` 전체를 전달하되, `12_mvp_execution_plan.md`의 suspend/resume 규칙과 권장 요청 분할을 최상위 지시로 둔다. 실제 구현은 여전히 Milestone 1+2, 3+4, 5+6, 7, 8+9+10 순서로 나누는 방식이 가장 안전하다.
