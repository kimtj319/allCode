# 11. Quality and Testing 구현 계획

## 구현 전 필수 보강 지시

- 통합 테스트와 회귀 테스트는 실제 LLM API와 물리 TTY 없이도 실행 가능해야 한다. fake LLM, fake tool, virtual TTY를 기본 fixture로 제공한다.
- 품질 테스트는 pass/fail뿐 아니라 답변 직접성, 도구 적합성, 반복 도구 호출 여부, 최종 근거 품질을 점수화한다.
- 대규모 프로젝트 생성 테스트에서는 skeleton-first, validation, repair, final report가 모두 확인되어야 한다.


## 목적

새 프로젝트가 실제 코딩 에이전트처럼 동작하는지 검증한다. 단순 테스트 통과가 아니라 답변 품질, 도구 선택, 컨텍스트 유지, TUI 사용성까지 확인한다.

## 우선순위

1. unit test 체계 작성
2. fake model integration test 작성
3. tool execution test 작성
4. TTY interaction test 작성
5. 품질 평가 matrix 작성
6. 회귀 로그 저장 및 분석 도구 작성

## 테스트 계층

### 1. Unit tests

대상:

- core models
- event types
- router
- policy
- response parser
- path resolver
- tool registry

### 2. Integration tests

대상:

- fake LLM이 tool call을 반환했을 때 tool executor가 실행되는지
- tool result가 다음 model message로 들어가는지
- 빈 응답 복구가 작동하는지
- read-only 요청에서 mutation tool이 차단되는지
- **Headless 모드 E2E 실행 검증**: TUI 렌더링을 완전히 배제하고 `ac --headless "질문"` 형식을 모의 실행하여, stdin 입력에 대해 올바른 `TurnResult`가 반환되는지, stdout으로 markdown 답변이 최종 출력되는지, 실행 결과에 따라 성공(0) 또는 실패(비영) exit code가 올바르게 전파되는지 검증 (`tests/integration/test_headless_runner.py`로 정의)

### 3. TTY tests

대상:

- `/` command palette
- `@` path completion
- 작업 중 후속 입력 큐
- 승인 패널
- diff 패널
- final answer rendering

### 4. Quality tests

프롬프트 유형:

- 일반 질문
- 코드 분석
- 특정 파일 함수 분석
- 후속 질문
- 신규 프로젝트 생성
- 기존 코드 수정
- 오류 로그 기반 디버깅
- 외부 지식 검색
- DevOps 작업
- 데이터 변환 작업

품질 기준:

- 요청에 직접 답한다.
- 필요한 도구를 사용한다.
- 같은 파일을 의미 없이 반복해서 읽지 않는다.
- 파일 변경 요청에서 실제 변경 없이 완료하지 않는다.
- 최종 답변에 근거와 검증 결과를 포함한다.
- read-only 요청에서는 파일 변경이 없다.

## 대규모 프로젝트 코드 생성 절차 검증

대규모 생성 테스트에서는 다음을 확인한다.

1. 스켈레톤이 먼저 생성되는가.
2. 필요한 함수와 타입이 설계되는가.
3. 파일 간 import가 맞는가.
4. 테스트가 작성되는가.
5. 검증 명령이 실행되는가.
6. 실패 시 자가 수리하는가.
7. 최종 보고가 충분한가.
8. 하나의 파일에 과도한 코드가 몰리지 않는가.

## 파일 길이 및 모듈화 원칙

- 테스트 helper는 `tests/helpers/`로 분리한다.
- TTY 테스트 runner는 unit test와 분리한다.
- 품질 matrix는 JSON 또는 YAML 데이터로 관리하고 테스트 코드에 직접 박지 않는다.
- 회귀 프롬프트는 카테고리별 파일로 분리한다.

## 완료 기준

- unit test 통과
- integration test 통과 (TUI 없는 headless runner의 exit code 및 출력 정합성 검증 완료 포함)
- 최소 30개 실제 프롬프트 TTY smoke test 통과
- 실패 케이스는 모두 원인과 수정 계획이 기록됨
- 코드 파일 중 500줄 초과 파일이 없거나 명확한 분리 계획이 존재함

## 공개 오픈소스 참조 기반 보강 계약

품질 평가는 테스트 통과 여부와 답변 품질을 함께 본다.

```text
functional_success: 35
tool_appropriateness: 20
context_continuity: 15
self_healing: 10
final_answer_grounding: 10
ui_signal_clarity: 5
safety_compliance: 5
```

- 85점 이상이면 pass다.
- 70~84점은 warning으로 기록하고 수정 후보에 올린다.
- 70점 미만은 fail이다.
- 구현 요청에서 실제 파일 변경이 없으면 functional_success는 0점이다.
- read-only 요청에서 mutation tool이 실행되면 safety_compliance는 0점이다.
