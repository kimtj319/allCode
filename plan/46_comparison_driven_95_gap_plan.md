# 46. Comparison-Driven 95% Gap Plan

## 목적

이 문서는 동일 프롬프트를 allCode와 agy에 실행해 드러난 95% 미달 지점을
정리하고, 오픈소스 CLI coding agent의 실제 동작 원칙을 allCode에 현실적으로
적용하기 위한 계획이다. `plan/44`와 `plan/45`를 이어받으며, `plan/00`~`12`
계약을 우선한다.

## 비교 프롬프트 결과 요약

### 1. 코드 흐름 분석

프롬프트:

```text
코드 수정은 엄격히 금지한다. 현재 프로젝트의 src/allCode/agent와 src/allCode/tools가 사용자 요청을 라우팅하고 툴을 실행한 뒤 최종 답변을 만드는 전체 흐름을 분석해줘. 확인한 파일 근거와 추론을 분리하고, 핵심 병목을 3개만 제시해줘.
```

결과:

- allCode: 관찰 근거는 안전하게 제시했지만 fallback 요약 형태로 내려갔고, 사용자가
  요구한 "핵심 병목 3개"를 직접 충족하지 못했다.
- agy: 세부 분석을 외부 아티팩트로 작성하고 대화 본문은 요약/링크 중심으로 반환했다.

gap:

- allCode의 fallback source-analysis answer가 사용자 요청의 출력 의무를 충분히
  반영하지 못한다.

### 2. 복잡 프로젝트 구현 계획

프롬프트:

```text
파일 수정은 엄격히 금지한다. ./output/parity95_compare_service 라는 Python 패키지형 CLI 프로젝트를 만든다고 가정하고, 표준 라이브러리만 사용해서 config, command registry, retry, JSONL logging, pytest 테스트를 포함하려면 어떤 파일 구조와 구현 순서가 좋은지 상세 계획을 작성해줘.
```

결과:

- allCode: 상세 계획을 본문에 직접 작성했다. 다만 마지막에 "요청한 파일은 찾지
  못했습니다"라는 workspace/tool 후미 문구가 섞였다.
- agy: 계획을 아티팩트로 작성하고 대화 본문에는 요약과 의사결정 질문을 반환했다.

gap:

- read-only/계획형 답변에서 no-result/not-found tool wording이 final answer에
  과도하게 붙을 수 있다.

### 3. 일반 지식/경영 보고

프롬프트:

```text
생성형 AI 기반 사내 코드 에이전트를 도입할 때 보안, 비용, 개발자 생산성, 품질관리 관점의 장단점을 경영진에게 보고하는 형식으로 정리해줘. 최신 수치가 필요하면 웹 검색이 필요하다고 명확히 말하고, 확인되지 않은 수치는 단정하지 마.
```

결과:

- allCode: 보고서 구조는 좋았지만 미검증 `20%~30%`, `10%~30%` 수치를 포함했다.
- agy: 본문은 짧았지만 도입 형태, FinOps, 검증 프로세스 같은 의사결정 쟁점을
  수치 단정 없이 제시했다.

gap:

- 외부 지식 route에서도 사용자가 명시한 "미확인 수치 단정 금지" 제약은
  metric guard를 켜야 한다.

## 오픈소스 동작 원칙 반영

- Aider: repo map/source analysis에서는 읽은 근거와 추론을 분리하고, 사용자의
  요청 형식에 맞춰 직접 답변한다. allCode fallback도 관찰 근거만 나열하지 말고
  prompt obligations를 반영해야 한다.
- Aider architect/editor: 계획/분석 요청은 실제 파일 탐색 실패 문구보다 계획
  산출물을 우선한다. no-result wording은 파일 찾기 요청일 때만 붙어야 한다.
- Gemini CLI memory/context: 사용자가 명시한 제약은 후속 final answer policy까지
  유지되어야 한다.
- OpenHands action/observation: tool observation은 final answer의 근거지만,
  observation 실패가 사용자 의도를 압도해서는 안 된다.
- Qwen Code provider-neutrality: guard는 특정 모델명이나 provider에 묶이지 않고
  prompt/routing/evidence 기반으로 동작해야 한다.

## Phase 1. Source-Analysis Fallback Obligation Closure

대상:

- `src/allCode/agent/source_answer_fallback.py`
- `src/allCode/agent/source_answer_synthesis.py`
- `tests/unit/agent/test_source_answer_fallback.py`

작업:

1. fallback이 사용자 prompt에서 "병목 3개", "리스크 N개", "단계 N개" 같은
   generic output obligation을 감지하면 별도 섹션으로 충족한다.
2. 특정 프롬프트 문자열이나 프로젝트명을 보지 않고, count + category noun 기반의
   일반 pattern만 사용한다.
3. 근거가 부족하면 "관찰 근거 기준 후보 병목"처럼 한계를 명확히 표시한다.

agy 검토 반영:

- count/category 추출은 regex 기반으로 시작하되, 한국어/영어 혼합 표현을 모두
  완벽히 처리하려고 과도하게 확장하지 않는다.
- 특정 프롬프트 문장이나 scenario ID를 직접 매칭하지 않는다.

## Phase 2. Final Wording Scope Tightening

대상:

- `src/allCode/agent/finalization.py`
- `tests/unit/agent/test_finalization_policy.py`

작업:

1. `_apply_not_found_wording`과 `_apply_no_search_results_wording`은 사용자의
   핵심 의도가 파일 찾기/검색일 때만 final answer에 문구를 덧붙인다.
2. 계획/일반 답변/분석 답변이 이미 충분한 본문을 제공했으면 tool no-result가
   후미 문구로 붙지 않게 한다.
3. 실제 missing explicit file target은 계속 알린다.

agy 검토 반영:

- `finalization.py`는 이미 `routing`을 받으므로, 새 provider/model dependency 없이
  prompt/routing/evidence 기반으로 no-result suffix를 억제한다.

## Phase 3. Explicit Metric Caution Guard

대상:

- `src/allCode/agent/answer_scope_guard.py`
- `tests/unit/agent/test_answer_scope_guard.py`

작업:

1. `확인되지 않은 수치`, `검증되지 않은 숫자`, `do not assert unverified
   numbers`, `needs web search` 같은 generic constraint를 감지한다.
2. 외부 지식 route라도 해당 constraint가 있으면 bracket citation이나 사용자
   제공 숫자가 아닌 concrete metric을 재작성 대상으로 잡는다.
3. 웹 근거가 없는 상태에서 최신 수치처럼 보이는 metric을 단정하지 못하게 한다.

agy 검토 반영:

- 향후 웹 근거가 있는 경우 number grounding을 search result message와 비교할 수
  있지만, 이번 반복에서는 "명시적 미검증 수치 금지 + citation/user-supplied
  number 예외"를 우선 고정한다.

## 검증 계획

```bash
python -m pytest tests/unit/agent/test_answer_scope_guard.py \
  tests/unit/agent/test_finalization_policy.py \
  tests/unit/agent/test_source_answer_fallback.py

python -m pytest tests/unit/agent tests/integration/test_readonly_source_analysis.py
python -m pytest
```

실제 비교:

1. 코드 흐름 분석 prompt.
2. 복잡 프로젝트 구현 계획 prompt.
3. 일반 지식/경영 보고 prompt.

각 결과는 `plan/45_parity_progress_tracker.md`에 반영한다.
