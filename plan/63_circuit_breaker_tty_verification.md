# 63. CircuitBreaker 생성 — 실 TTY 검증 + no-tests false-pass 수정

## 실 TTY 검증 (2026-06-13)

서킷 브레이커 프로젝트 생성 프롬프트를 **실제 PTY**(pyte 렌더)로 실행해 처리과정·UI를
확인. 입력 주입은 **chunked bracketed-paste**로 해결(1.5KB 프롬프트를 단일 write로
보내면 pty 입력 버퍼에서 os.write가 블록됨 → paste 영역 안에서 청크 단위로 drain).

### 의도한 UI 수정 — 정상 동작 확인
- **diff UI**: 모든 `write_file`가 요약 라인 `• write_file … -> ok · created/modified: X (+N -M)`
  아래에 **색상 unified diff**(`@@` cyan, `+` 초록, `-` 빨강, context dim, 2칸 들여쓰기)로
  렌더. 신규 파일 생성도 전부 `+` diff로 표시. (raw 캡처에서 `@@` hunk·ANSI 32/31/36 확인)
- **이모지 0개**, 간결 스타일.
- **단계 표시**: 스켈레톤→구현→테스트 작성→검증→repair→final_report.
- **경로 준수**: 산출물이 모두 `output/circuit_breaker/` 하위.

### 발견한 문제
- **A (모델)**: 스펙 파일명(`breaker.py`/`test_breaker.py`) 대신 기본 스캐폴드
  (`src/circuit_breaker/main.py`, `tests/test_main.py`)로 생성.
- **B (모델)**: `test_main.py`에 테스트 함수 0개 — 구현 코드가 복사됨(README.md도 코드 덤프).
- **C (하니스 false-pass, 회귀)**: 실제 `pytest`는 "no tests ran"인데 allCode가 "검증 성공"
  보고. 원인 체인: 모델이 테스트 파일에 구현 복사 → pytest 0건 수집 → shell.py no-tests
  완화로 `validation_passed=True` → completion_checker 토큰 커버리지도 (복사된 구현 심볼로)
  통과 → 성공 마감.

## C 수정 (completion_checker)

- `completion_checker.py`에 `_test_function_errors` 추가: 계획(`plan.required_paths()`)에
  포함된 **Python 테스트 파일에 `test*` 함수가 0개**면 completion 에러
  ("required test file defines no test functions: …"). AST로 `FunctionDef`/`AsyncFunctionDef`
  중 이름이 `test`로 시작하는 것을 탐지(모듈 함수·`Test*` 클래스 메서드 모두 포함).
  구문 오류 파일은 별도 검사(`_python_syntax_errors`)에 맡기고 여기선 중복 플래그 안 함.
- **범위 한정**: 계획에 테스트 파일이 있는 경우(=테스트가 요구된 generation)만 발동.
  계획에 테스트 파일이 없으면 무발동 → **modify/축④ no-tests 완화와 무관**(회귀 없음).
- 이 run의 `test_main.py`에 대해 `has test functions=False`로 정확히 탐지; 정상 테스트
  파일/클래스형은 True. 전체 777 passed.

## 남은 모델-측 격차(후속, 하니스 밖)
- A(스펙 파일명 미준수), B(테스트 파일에 구현 복사)는 모델 행동. C 수정으로 B는 이제
  성공으로 마감되지 못하게 차단됨(검증 단계에서 실패 노출). A는 프롬프트의 명시 파일명을
  스캐폴드보다 우선하도록 유도하는 별도 과제.
