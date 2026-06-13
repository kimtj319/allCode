# 47. Comparison Iteration 2 Cleanup Plan

## 목적

`plan/46` 구현 후 동일 프롬프트 비교에서 개선은 확인했지만 평균 95% 기준에는
아직 미달인 잔여 품질 문제를 닫는다. 이 문서는 `plan/44`~`46`을 이어받으며,
`plan/00`~`12` 계약과 하드코딩 금지 원칙을 우선한다.

## 비교 후 남은 문제

### 1. 재작성 후 잔여 미검증 수치

일반 지식/경영 보고 프롬프트에서 allCode는 큰 미검증 수치 단정을 제거했지만,
`1~2팀` 같은 작은 숫자 예시가 남았다. 사용자가 "확인되지 않은 수치는 단정하지
마"라고 명시한 경우, 외부 근거가 없으면 두 번째 재작성까지 허용해야 한다.

오픈소스 참고 원칙:

- Aider/Codex 계열은 사용자의 명시 제약을 final answer 직전까지 유지하고, 답변이
  제약을 위반하면 재작성한다.
- Gemini CLI의 memory/context 원칙처럼 사용자 제약은 단일 프롬프트 조각이 아니라
  턴 전체의 hard constraint로 유지해야 한다.

구현:

1. `answer_scope_retry_used`를 고정 boolean이 아니라 제한 횟수 기반으로 확장한다.
2. `round_text_response.py`에서 metric/scope 위반은 최대 2회까지 재작성 요청한다.
3. 무한 루프 방지를 위해 2회를 넘기면 기존처럼 더 이상 재요청하지 않는다.
   이 경우 이번 iteration에서는 강제 문자열 삭제 sanitizer를 적용하지 않고,
   다음 단계에서 별도 safe qualitative fallback 설계를 검토한다.
4. 특정 수치나 테스트 문장을 제거하는 deterministic sanitizer는 적용하지 않는다.

대상:

- `src/allCode/agent/answer_scope_guard.py`
- `src/allCode/agent/round_text_response.py`
- `tests/unit/agent/test_answer_scope_guard.py`

### 2. 완성된 read-only 분석 답변의 schema-denied 후미 노이즈

source-analysis 비교에서 allCode는 구조화된 분석과 병목 3개를 제대로 냈지만,
마지막에 "읽기 전용 조건 때문에..." 문구가 붙었다. 이 문구는 hidden write/shell
tool이 차단됐다는 상태 정보로는 유용하지만, 이미 충분한 read-only 분석 본문이
있고 답변 자체가 수정 금지를 준수한 경우 최종 답변 품질을 떨어뜨린다.

오픈소스 참고 원칙:

- OpenHands는 action/observation을 이벤트로 남기되, 실패 observation이 완성된
  사용자 답변을 무조건 덮어쓰지 않는다.
- Qwen Code/Gemini CLI처럼 사용자가 보는 답변은 핵심 산출물을 우선하고 내부
  safety/status noise는 필요한 경우에만 노출한다.

구현:

1. `_apply_schema_denied_wording`은 read-only 라우팅에서만 추가 억제 조건을 둔다.
2. 답변이 충분히 구조화되어 있고 실제 읽기 근거(`inspected_paths`,
   `representative_read_paths`, `source_overview_paths`, `search_candidate_paths` 등)가
   존재하면 schema-denied 문구를 최종 답변에 덧붙이지 않는다.
3. 짧은 답변이나 정책 차단 사실을 전혀 언급하지 않은 답변에는 기존 문구를 유지한다.
4. 길이 기준만으로 판단하지 않고 heading/bullet/table 같은 구조 신호와 evidence
   존재를 함께 사용한다.

agy 검토 반영:

- read-only 준수 표현을 특정 한국어/영어 문자열 목록으로 과도하게 판별하지 않는다.
- 단순히 긴 답변이거나 markdown 구조가 있다는 이유만으로 문구를 억제하지 않는다.
  실제 읽기 evidence가 있어야 한다.
- schema-denied가 분석 실패의 중요한 원인일 수 있으므로, evidence가 없거나 답변이
  짧으면 기존 안내 문구를 유지한다.

대상:

- `src/allCode/agent/finalization.py`
- `tests/unit/agent/test_finalization_policy.py`

## 검증 계획

```bash
python -m pytest tests/unit/agent/test_answer_scope_guard.py \
  tests/unit/agent/test_finalization_policy.py \
  tests/unit/agent/test_source_answer_fallback.py

python -m pytest tests/unit/agent tests/integration/test_readonly_source_analysis.py
```

실제 비교:

1. source-flow 분석 프롬프트: 병목 3개 유지, read-only 후미 노이즈 감소 확인.
2. 경영 보고 프롬프트: 웹 근거 없이 남는 미검증 숫자 예시 감소 확인.

## 현재 제외

- 웹 검색 backend 자동 선택/무료 backend 번들링은 별도 인프라 설정과 네트워크
  안정성 문제가 있어 이번 소규모 cleanup에 포함하지 않는다.
- agy처럼 외부 아티팩트 파일을 자동 생성하는 답변 방식은 현재 allCode의
  headless final answer 품질 목표와 다르므로 도입하지 않는다.

## 구현 결과

2026-06-08 실행:

- `answer_scope_retry_used`를 횟수 기반으로 확장하고, scope/metric 위반 재작성은
  최대 2회까지 허용했다.
- explicit unverified metric caution이 있는 외부 지식 route에서 기간/팀 규모/인원
  같은 일반 수치 예시도 재작성 대상으로 잡도록 metric unit 범위를 확장했다.
- source-analysis fallback이 요청된 병목/리스크 개수보다 후보가 적을 때도
  관찰 근거의 한계를 명시한 generic 후보로 요청 개수를 채우도록 보강했다.
- finalization에서 계획형 답변의 incidental not-found/search-miss 문구, source 분석의
  incidental config 문구, evidence가 있는 구조화된 read-only 분석 답변의
  schema-denied 후미 노이즈를 억제했다.
- web unavailable 문구는 본문에서 이미 웹 검색 비활성을 설명한 경우 중복으로
  붙이지 않게 했다.

검증:

```bash
python -m pytest tests/unit/agent/test_answer_scope_guard.py \
  tests/unit/agent/test_finalization_policy.py \
  tests/unit/agent/test_source_answer_fallback.py
# 41 passed

python -m pytest tests/unit/agent tests/integration/test_readonly_source_analysis.py
# 344 passed

python -m pytest
# 615 passed, 7 skipped
```

실제 비교 결과:

- source-flow 분석: allCode가 요청한 핵심 병목 3개를 유지하고 read-only/config
  후미 노이즈 없이 출력했다.
- 복잡 프로젝트 계획: allCode의 이전 incidental not-found suffix가 사라졌다.
- 경영 보고: allCode가 미검증 수치/기간 예시를 제거하고, 웹 검색 backend 부재를
  한 번만 명시했다.

잔여 95% 미달 원인:

- agy는 live web search로 최신 자료 기반 수치를 합성할 수 있지만, allCode는
  `ALLCODE_WEB_*` backend 설정이 없으면 정성 답변으로 제한된다.
- agy는 같은 source-flow 분석에서 더 많은 실제 파일 본문과 라인 링크를 읽어
  병목을 더 구체화한다. allCode는 안전 fallback일 때 아직 header/signature
  중심 요약에 의존한다.
