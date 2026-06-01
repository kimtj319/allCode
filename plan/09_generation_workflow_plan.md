# 09. Project Generation Workflow 구현 계획

## 구현 전 필수 보강 지시

- 동일 에러 메시지 해시가 2회 연속 관찰되거나 총 수리 시도가 5회를 넘으면 수리 루프를 중단하고 사용자 개입 상태로 전환한다.
- 파일 변경 전에는 edit transaction snapshot을 남기고, 검증 최종 실패 시 rollback 가능해야 한다.
- 실제 파일 생성 또는 수정 없이 최종 답변을 내는 것을 금지한다. completion checker가 이를 차단해야 한다.


## 목적

신규 프로젝트 생성, 다중 파일 수정, 테스트/수리 반복을 안정적으로 처리하는 워크플로우를 구현한다. 이 계획은 대규모 프로젝트 코드 생성을 위한 핵심 절차를 명시한다.

## 우선순위

1. `agent/workflow.py` 작성
2. `agent/task_plan.py` 작성
3. `agent/completion_checker.py` 작성
4. `agent/validation_runner.py` 작성
5. `agent/final_reporter.py` 작성
6. 대규모 생성 E2E 테스트 작성

## 상세 수정 및 구현 내용

### 1. `agent/task_plan.py`

정의:

- `TaskItem`: id, description, status, evidence
- `ProjectPlan`: target_root, files, validation_commands, constraints
- `GenerationStep`: skeleton, implementation, integration, validation, repair, summary

### 2. `agent/workflow.py`

담당:

- 라우팅 결과가 `modify`이고 새 프로젝트 또는 다중 파일 작업이면 generation workflow 시작
- 모델에게 한 번에 모든 파일을 만들라고 하지 않고 단계별로 진행
- 각 단계 후 실제 파일 존재 여부 확인

### 3. `agent/completion_checker.py`

완료 조건:

- 요청된 대상 경로가 존재한다.
- 필수 파일이 생성되었다.
- 파일 내용이 비어 있지 않다.
- 사용자가 요구한 금지 파일이 생성되지 않았다.
- 테스트 또는 문법 검사가 실행되었다.
- 실패가 있으면 수리 루프가 실행되었다.
- 최종 답변에 생성물과 검증 결과가 포함되었다.

### 4. `agent/validation_runner.py`

담당:

- 언어별 검증 명령 후보 생성
- pytest, npm test, go test, cargo test, javac, gradle 등 지원
- 실패 로그를 요약해 loop에 전달

### 5. `agent/final_reporter.py`

최종 답변 형식:

- 구현 위치
- 생성/수정 파일
- 핵심 기능
- 검증 명령과 결과
- 남은 리스크
- 다음에 바로 실행할 명령

## 대규모 프로젝트 코드 생성 절차

모든 신규 프로젝트 생성은 다음 절차를 반드시 따른다.

1. 목표와 제약사항 추출
2. target root 확정
3. 파일 트리 설계
4. 스켈레톤 파일 생성
5. 타입/인터페이스/함수 시그니처 작성
6. 핵심 구현 작성
7. 모듈 간 import와 엔트리포인트 연결
8. 테스트 작성
9. 의존성 파일 작성
10. 검증 실행
11. 실패 원인 분석
12. 수리 patch 적용
13. 재검증
14. 최종 산출물 보고

## 파일 길이 및 모듈화 원칙

- 생성 workflow는 `workflow.py`에만 몰지 않는다.
- plan 모델, 완료 검사, 검증 실행, 최종 보고를 별도 파일로 둔다.
- 프로젝트별 scaffold는 하드코딩하지 않는다. 필요하면 language strategy로 분리한다.
- 한 파일에 400줄 이상 구현이 쌓이면 즉시 responsibility split을 수행한다.

## 공개 오픈소스 참조 기반 보강 계약

Generation workflow는 모델이 만든 계획을 실행 가능한 단계로 관리하되, 실제 파일 생성은 tool executor를 통해서만 수행한다.

- workflow는 `ProjectPlan`과 `GenerationStep`만 관리한다.
- 언어별 기본값은 `generation/strategies/*.py`로 분리한다.
- MVP strategy는 Python, Node/TypeScript, Go, Rust, Java까지만 제공한다.
- 알 수 없는 언어는 generic file plan으로 처리하고 임의 dependency를 설치하지 않는다.
- final answer 전에는 생성 파일 인벤토리와 검증 결과를 완료 조건으로 확인한다.
- 실제 파일 변경이 없으면 구현 완료 final answer를 반환하지 않는다.
