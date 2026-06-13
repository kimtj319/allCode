# 52. Comparison Gap Hardening Plan

Last updated: 2026-06-11

## 목적

최근 `allcode`와 `agy` 동일 프롬프트 비교에서 드러난 품질 격차를 코드 단위로
해소한다. 목표는 평균 체감 진척률 95% 이상이지만, 특정 테스트 프롬프트나
프로젝트명을 하드코딩하지 않고 일반화 가능한 라우팅, 근거 합성, 제약 전달 로직을
보강하는 것이다.

## 우선 적용 계약

- `plan/00`부터 `plan/12`까지의 MVP 계약을 우선한다.
- 모호한 설계는 `plan/01_open_source_alignment_contracts.md`를 따른다.
- 소스 분석은 `plan/07_workspace_context_plan.md`의 full-file dump 금지와
  symbol/signature 중심 context 원칙을 유지한다.
- 설계/구현 산출물 요청은 `plan/09_generation_workflow_plan.md`의
  skeleton -> contract -> implementation -> validation 원칙을 따른다.
- `plan/51_claude_sonnet_remaining_hardening_plan.md`의 Source Responsibility
  Synthesis, Session State, Web Evidence, Obligation Matrix, Approval UX 보강을
  현재 baseline으로 간주한다.

## 비교 기반 문제 분석

### 1. 소스 분석 답변 밀도 부족

현상:

- `src/allCode/agent`, `src/allCode/tools`, `src/allCode/tui` 역할과 데이터 흐름을
  묻는 프롬프트에서 allcode는 `## 소스 분석 요약`, `관찰된 도구 근거만 기준`으로
  시작하는 fallback-like 답변을 반환했다.
- 대표 파일은 일부만 나열되고, 사용자가 요구한 "중요 파일 8개 이상" 같은 출력
  의무를 충분히 채우지 못했다.
- agy는 별도 artifact를 만들면서 더 명확한 섹션과 파일 수, 리스크 요약을 제공했다.

확정 코드 위치:

- `src/allCode/agent/round_text_response.py`
  - `source_answer_violation` 발생 후 retry가 1회만 허용되고, 재위반 시
    `safe_source_analysis_answer()`로 즉시 전환된다.
- `src/allCode/agent/source_answer_guard.py`
  - 앵커 검증은 안전을 위해 필요하지만, retry prompt가 모델에게 사용할 수 있는
    안전한 앵커 후보를 충분히 제공하지 않는다.
- `src/allCode/agent/final_answer_context.py`
  - `MAX_EVIDENCE_BRIEF_CHARS=3500` 상한으로 source responsibility graph와 anchor
    tail이 잘릴 수 있다.
- `src/allCode/agent/source_answer_fallback.py`
  - fallback은 안전하지만 evidence dump 중심이며, 사용자 출력 의무와 package
    responsibility synthesis를 충분히 충족하지 못한다.

보강 원칙:

- guard 자체를 약화하지 않는다.
- fallback만 길게 만드는 방식으로 품질 향상처럼 보이게 하지 않는다.
- 모델 retry가 성공할 수 있도록 안전한 anchor 후보와 책임 matrix를 더 잘 보존한다.
- fallback은 마지막 안전장치로 유지하되, 사용자가 요청한 파일 수/리스크/개선점
  같은 일반 출력 의무는 최대한 충족한다.

### 2. Answer-only 프로젝트 설계의 dependency constraint 누락

현상:

- `코드 수정은 금지`, `실제 파일은 만들지 말고`, `Python 표준 라이브러리만` 같은
  요청에서 라우팅은 보강 후 direct answer로 개선됐지만, 최종 답변은 `pytest`를
  테스트 도구로 제안했다.
- 이는 "프로젝트는 stdlib-only" 요청을 답변 합성 prompt가 명확히 전달하지 못한
  문제다.

확정 코드 위치:

- `src/allCode/agent/prompt_constraints.py`
  - `stdlib_only` 또는 `no third-party dependency` 제약을 보존하는 필드가 없다.
- `src/allCode/agent/answer_prompt.py`
  - direct answer route instruction은 안정적이지만, answer-only artifact의 의존성
    제약을 별도로 주입하지 않는다.
- `src/allCode/agent/final_answer_context.py`
  - final synthesis system guard에도 dependency constraint가 포함되지 않는다.

보강 원칙:

- 일반 지식 direct answer에는 불필요한 dependency 지침을 넣지 않는다.
- code/project artifact 요청이면서 stdlib-only/no third-party 신호가 있을 때만
  테스트와 예시 코드에 native tooling을 쓰도록 지시한다.
- 특정 프로젝트명(`taskhub`)이나 특정 서브커맨드를 하드코딩하지 않는다.

### 3. 일반 지식 direct answer 회귀 방지

현상:

- 일반 지식 질문은 tool 없이 direct answer를 반환했고 품질도 안정적이었다.

보강 원칙:

- 새 constraint 필드는 route kind나 tool exposure를 불필요하게 바꾸면 안 된다.
- `answer_policy`의 web-only/direct answer 분리는 유지한다.

## Phase 1. Source Answer Retry Context 보강

수정 대상:

- 신규: `src/allCode/agent/source_answer_retry_context.py`
- 수정: `src/allCode/agent/source_answer_guard.py` (helper 호출만 추가, 새 책임 금지)
- 수정: `src/allCode/agent/round_text_response.py`
- 테스트: `tests/unit/agent/test_source_answer_guard.py`

구현:

1. 관찰된 source probe 결과에서 안전한 anchor 후보를 compact list로 만든다.
   - path
   - reason
   - symbol
   - line range
   - body sample 여부
2. `source_answer_retry_messages()`에 anchor 후보를 함께 전달해 모델이 재시도 때
   관찰된 앵커만 사용할 수 있게 한다.
3. `round_text_response.py`의 source answer retry 예산을 1회에서 2회로 늘린다.
   - 단, 같은 위반 reason/excerpt가 반복되면 더 이상 반복하지 않고 fallback으로 간다.
   - retry count와 반복 위반 판정은 신규 helper에 둔다.
4. retry 예산은 source 분석에만 적용하고 일반 answer/direct route에는 영향을 주지
   않는다.

수용 기준:

- source answer violation 발생 시 retry prompt에 safe anchor candidates가 포함된다.
- 2회까지 복구 기회를 주되 무한 반복하지 않는다.
- guard의 unobserved anchor/path/symbol 차단은 유지된다.

## Phase 2. Source Fallback Output Obligation 보강

수정 대상:

- 신규: `src/allCode/agent/source_answer_requirements.py`
- 수정: `src/allCode/agent/source_answer_fallback.py` (requirements helper 사용만 추가)
- 수정: `src/allCode/agent/source_analysis_rendering.py`
- 테스트: `tests/unit/agent/test_source_answer_fallback.py`,
  `tests/unit/agent/test_source_answer_synthesis.py`

구현:

1. 사용자 프롬프트에서 일반화 가능한 출력 의무를 추출한다.
   - 중요한 파일/대표 파일/핵심 파일 N개
   - 리스크/개선점/병목 N개
   - 한국어/영어는 기존 language detection을 따른다.
2. fallback 답변은 observed paths, package roles, representative files,
   responsibility graph nodes를 합쳐 요청된 파일 수에 최대한 맞춘다.
3. 파일별 설명은 "관찰 근거"와 "추론 역할"을 분리해 과장하지 않는다.
4. source analysis rendering의 answer outline에도 요청된 파일 수/리스크 수를
   반영해 모델 정상 합성 경로가 먼저 좋아지게 한다.

수용 기준:

- "중요 파일 8개 이상" 요청에서 관찰된 후보가 충분하면 8개 이상 파일 역할을
  출력한다.
- 후보가 부족하면 부족 사유를 limitation으로 쓴다.
- raw tool JSON이나 tool plan은 노출하지 않는다.

## Phase 3. Dependency Constraint Extraction and Answer Prompt

수정 대상:

- 수정: `src/allCode/agent/prompt_constraint_terms.py`
- 수정: `src/allCode/agent/prompt_constraints.py`
- 수정: `src/allCode/agent/intent.py`
- 수정: `src/allCode/agent/model_router.py`
- 수정: `src/allCode/agent/answer_prompt.py`
- 신규: `src/allCode/agent/dependency_answer_guard.py`
- 수정: `src/allCode/agent/round_text_response.py`
- 테스트: `tests/unit/agent/test_prompt_constraints.py`,
  `tests/unit/agent/test_answer_policy.py`,
  `tests/unit/agent/test_model_router.py`,
  `tests/unit/agent/test_dependency_answer_guard.py`

구현:

1. `STDLIB_ONLY_TERMS`를 추가한다.
   - `standard library only`, `stdlib-only`, `no third-party`, `without external packages`
   - `표준 라이브러리만`, `외부 패키지 없이`, `서드파티 없이`, `추가 의존성 없이`
2. `PromptConstraints`에 `stdlib_only_requested`를 추가한다.
3. `RoutingDecision.flags`에 `stdlib_only_requested`를 보존한다.
4. `answer_route_instruction()`은 다음 조건에서만 dependency instruction을 추가한다.
   - `answer_artifact` 또는 `code_artifact` 성격의 direct answer
   - `stdlib_only_requested` flag 존재
5. Python 테스트 예시에는 `unittest`, `tempfile`, `subprocess` 등 표준 라이브러리
   도구를 우선 권고하게 한다.
6. direct answer는 completion checker를 거치지 않으므로 soft validation을 추가한다.
   - stdlib-only direct answer에서 `pytest`, `requests`, `click`, `typer` 등
     서드파티 사용/권고가 감지되면 1회 재생성을 요청한다.
   - 이 guard는 `stdlib_only_requested` flag가 있을 때만 동작한다.

수용 기준:

- stdlib-only answer artifact 요청에서 `pytest`, third-party package 추천이 나오지
  않도록 system instruction이 명시된다.
- 일반 지식 direct answer에는 stdlib-only 지침이 섞이지 않는다.
- 모델이 여전히 서드파티를 제안하면 retry prompt가 한 번 발행된다.

## Phase 4. Comparison Regression Matrix

수정 대상:

- 신규/수정: `tests/integration/test_comparison_prompt_regressions.py`
  또는 기존 agent unit tests.

구현:

1. fake LLM 또는 routing-level 테스트로 다음을 고정한다.
   - read-only source analysis는 inspect route와 read/search capability 유지.
   - answer-only artifact는 direct answer route 유지.
   - stdlib-only answer artifact는 dependency flag와 prompt instruction 유지.
   - 일반 지식은 no-tool direct answer 유지.
   - stdlib-only flag가 없는 일반 지식 질문은 dependency guard를 타지 않는다.
   - source answer 동일 위반 반복 시 retry loop가 무한 반복하지 않고 fallback으로
     수렴한다.
2. 실제 model/TUI 비교는 자동 테스트에 하드코딩하지 않고 review/수동 검증으로만
   기록한다.

검증 명령:

```bash
.venv/bin/python -m pytest tests/unit/agent/test_source_answer_guard.py tests/unit/agent/test_source_answer_fallback.py tests/unit/agent/test_source_answer_synthesis.py
.venv/bin/python -m pytest tests/unit/agent/test_prompt_constraints.py tests/unit/agent/test_answer_policy.py tests/unit/agent/test_model_router.py tests/unit/agent/test_router.py
.venv/bin/python -m pytest
```

## 수동 비교 프롬프트

1. 복잡한 소스 분석:
   - 코드 수정 금지.
   - `src/allCode/agent`, `src/allCode/tools`, `src/allCode/tui` 역할과 데이터 흐름.
   - 중요한 파일 8개 이상과 개선 리스크 포함.
2. answer-only 프로젝트 설계:
   - 코드 수정 금지.
   - Python 표준 라이브러리만.
   - 실제 파일 생성 금지.
   - 파일 구조, 핵심 코드 초안, 테스트 전략, 검증 명령 후보.
3. 일반 지식 direct answer:
   - 코드 수정/파일 탐색 불필요.
   - planning, tool grounding, memory compaction 설명.

## 남은 리스크

- source guard를 유지하는 한 모델이 앵커를 계속 잘못 쓰면 fallback은 여전히 발생할
  수 있다.
- evidence brief를 늘리면 토큰/지연 시간이 증가할 수 있다.
- CLI 전역 `allcode`가 editable venv가 아니라 `/opt/homebrew/bin/allcode`를 가리키면
  최신 작업트리 검증과 사용자 실행 결과가 달라질 수 있다.
