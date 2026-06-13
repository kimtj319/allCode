# 49. 95% Parity: Generation Repair Context Plan

## 목적

`plan/45`의 현재 평균 추정 진척도는 92%다. 2026-06-09 동일 프롬프트 비교에서
source 분석은 개선됐지만, 복잡한 Python package CLI 생성에서 allCode가 agy보다
크게 뒤처지는 사례가 재현되었다.

## 재현 프롬프트

```text
./output/parity95_round9_taskhub 안에 표준 라이브러리만 사용하는 Python 패키지형 CLI를 실제로 생성해줘.
기능은 task tracker다. command registry, add/list/done/export 명령, JSON 저장소,
retry helper, pytest 테스트, README를 포함해야 한다. 생성 후 검증을 실행하고
최종 보고서에는 생성 파일과 검증 결과를 포함해줘.
```

## 관찰 결과

- agy:
  - `taskhub/cli.py`, `storage.py`, `retry.py`, `__main__.py`로 역할을 분리했다.
  - pytest 14개와 수동 smoke를 실행해 성공을 보고했다.
- allCode:
  - package layout과 테스트 파일은 만들었지만 구현 파일 `main.py`는 generic `greet()`
    skeleton에 머물렀다.
  - 직접 pytest는 `ImportError: cannot import name 'main'`로 실패했다.
  - 최종 결과는 completion check failure로 정확히 실패했지만, repair loop가 충분히
    수렴하지 못했다.

## 오픈소스 참고 원칙

- Aider: test/fix loop에서는 실패한 test output과 관련 파일 내용을 다음 모델 라운드에
  직접 제공한다.
- OpenHands: action 결과는 observation이고, 실패 observation은 다음 action 선택의
  feedback으로 들어간다.
- Qwen Code: coding task는 todo/tool workflow로 구조화하고, 모델에게 남은 작업을
  명시한다.
- Gemini CLI: 긴 작업에서는 계층 context와 compact state를 매 라운드에 주입해
  사용자의 원래 의도와 현재 실패를 함께 보존한다.

## Phase 1. Validation + Completion Failure Unification

대상:

- `src/allCode/agent/workflow.py`
- `src/allCode/agent/workflow_repair.py`
- `tests/integration/test_generation_workflow.py`

문제:

- validation 실패와 completion/API obligation 실패가 서로 다른 시점에 처리된다.
- validation이 실패하면 `completion_check_repairable`이 `validation_passed is True` 조건에
  막혀 API obligation repair가 실행되지 않는다.
- 그래서 `ImportError`와 `public API obligation missing`이 동시에 있는 상황에서 모델
  repair prompt가 충분한 의무 정보를 받지 못한다.

구현:

1. validation 실패 직후에도 completion checker를 `validation_required=False`로 실행해
   missing public API, missing file, syntax error를 수집한다.
2. validation failure summary와 completion errors를 하나의 repair failure log로 합쳐
   repair model/strategy에 전달한다.
3. 이 합성은 특정 테스트명, 출력 경로, 프로젝트명을 보지 않고 `CompletionCheck.errors`와
   `ValidationResult.summary/error`만 사용한다.

## Phase 2. Editor Repair Prompt Strengthening

대상:

- `src/allCode/agent/workflow_editor.py`
- `tests/unit/agent/test_workflow_editor.py` 또는 integration test

문제:

- model editor가 invalid/weak implementation을 반환하면 현재 구현은 조용히 skeleton
  content로 fallback한다.
- repair prompt는 allowed files와 failure log를 주지만, tests가 기대하는 public API와
  command obligation을 구조화해서 강조하지 않는다.

구현:

1. editor/repair prompt에 다음을 명시한다.
   - tests are executable contracts.
   - If tests import missing functions/classes, implement them in source files.
   - Do not keep placeholder/sample functions when the user requested a real CLI.
2. failure log에 `public API obligation missing ...`이 있으면 source implementation file을
   우선 수정 대상으로 안내한다.
3. `_looks_valid_for_path`에 특정 sample 함수명 차단 같은 휴리스틱을 추가하지 않는다.
   skeleton 감지는 오탐 위험이 크므로, AST/API obligation checker가 산출한 누락 목록을
   repair feedback으로 주입하는 방식으로 해결한다.

agy 검토 반영:

- `repair_until_valid`에 `CompletionChecker`를 주입하고, validation 실패 시점마다
  `validation_required=False`로 completion check를 실행한다.
- failure log에 pytest/import error와 API obligation errors를 같이 넣는다.
- `greet`, `hello`, 특정 task 이름 같은 sample-only 휴리스틱은 하드코딩 위험 때문에
  구현하지 않는다.

## Phase 3. Generation Smoke Regression

대상:

- `tests/integration/test_generation_workflow.py`

구현:

1. fake editor가 처음에는 skeleton implementation을 만들고 tests는 public API를 요구하는
   케이스를 추가한다.
2. validation failure와 completion check errors가 합쳐진 repair log를 받은 editor가
   implementation 파일을 고쳐 성공하는지를 검증한다.
3. 검증은 `CompletionEvidence.validation_passed`, final report, changed files를 함께 본다.

## Phase 4. Comparison and Tracker Update

검증:

```bash
python -m pytest tests/integration/test_generation_workflow.py
python -m pytest tests/unit/agent tests/unit/tools tests/integration/test_generation_workflow.py
python -m pytest
```

실제 비교:

1. 같은 task tracker generation prompt를 allCode와 agy에 다시 실행한다.
2. allCode 산출물을 직접 `python -m pytest -q <target>/tests`로 검증한다.
3. pytest가 통과하고 최종 보고서가 생성/검증 결과를 정확히 담으면 `plan/45`의
   project generation estimate를 갱신한다.

## 금지

- 특정 output 디렉터리명(`parity95_*`)이나 테스트 프롬프트 문자열을 조건문으로 보지 않는다.
- task tracker 전용 구현을 allCode 본체에 넣지 않는다.
- validation 실패를 숨기거나 success로 바꾸지 않는다.
- file mutation evidence와 validation evidence 없이 final report success를 반환하지 않는다.

## Phase 5. Public API Obligation Noise Reduction

대상:

- `src/allCode/agent/api_obligation_checker.py`
- `src/allCode/agent/workflow_repair.py`
- `src/allCode/agent/workflow_editor.py`
- `tests/unit/agent/test_api_obligation_checker.py`

문제:

- 모델이 생성한 계획 파일에 `T = TypeVar("T")`, `R = TypeVar("R")` 같은 typing helper가
  포함되면 현재 AST 기반 public symbol 추출기가 이를 사용자-facing 공개 API obligation으로
  잘못 분류한다.
- 이 노이즈는 실제로 고쳐야 할 `TaskStore`, `retry`, command 함수 같은 실행 계약을 흐리게
  만들어 repair prompt의 초점을 약화시킨다.

구현:

1. Python public symbol 추출에서 `typing.TypeVar`, `ParamSpec`, `TypeVarTuple`, `NewType` 호출로
   생성된 module-level helper 이름은 공개 API obligation에서 제외한다.
2. 이 필터는 특정 변수명(`T`, `R`)이나 특정 프로젝트명을 보지 않고 AST 호출 형태만 본다.
3. repair failure log에는 public API 오류가 가리키는 파일 경로를 "preferred repair target"으로
   요약해 모델이 테스트/obligation을 만족해야 할 implementation 파일을 바로 보게 한다.
4. repair prompt에는 placeholder를 유지하지 말라는 특정 이름 기반 규칙 대신, 누락 API가 있는
   허용 파일은 전체 파일 교체로 고쳐도 된다는 일반 규칙을 추가한다.

## Phase 6. Requirement-Covering Test Plan Enforcement

대상:

- `src/allCode/agent/project_planner.py`
- `tests/unit/agent/test_project_planner.py`

문제:

- 실제 생성 테스트에서 allCode는 repair를 통해 기능 구현은 성공했지만, planner가 만든 테스트가
  사용자 요청의 주요 기능을 검증하지 않고 generic `greet()` smoke에 머무는 사례가 있었다.
- 이는 pytest 통과를 실제 기능 완성으로 오인하게 만들고, agy처럼 command/storage/retry 등
  요청된 책임을 검증하는 산출물과 비교했을 때 품질 격차를 만든다.

오픈소스 참고 원칙:

- Aider의 test/fix 루프는 사용자가 요구한 실패/테스트를 실제 수정 계약으로 사용한다.
- OpenHands의 action/observation 구조는 검증 결과를 다음 행동의 근거로 삼는다.
- Qwen Code류 terminal-first agent는 작업을 todo로 쪼개고 각 todo를 검증 가능한 명령/테스트와
  연결한다.

구현:

1. planner JSON schema 안내에 `api_obligations`를 명시해 모델이 공개 함수/클래스/command
   계약을 구조화해 반환할 수 있게 한다.
2. prompt-derived artifact obligations가 있는 경우, tests stage 파일은 sample smoke가 아니라
   해당 obligations를 실행 가능한 방식으로 검증해야 한다고 명시한다.
3. 테스트가 요청되거나 검증이 implied된 경우, validation command는 tests stage 파일을 실행해야
   하며 tests file content에는 주요 implementation API/command 경로를 import 또는 호출하는
   assertions가 포함되어야 한다고 안내한다.
4. 구현은 특정 기능명이나 프로젝트명을 강제하지 않고, 이미 추출된 artifact obligations와 plan
   schema를 활용한다.

agy 검토 반영:

- `ProjectPlan`에는 이미 `api_obligations`가 있으므로 planner schema 안내에 포함해도 기존
  Pydantic 계약과 호환된다.
- `api_obligations`의 `path`도 `files`와 동일하게 target_root/original_root 접두사를 제거하고
  safe relative path로 정규화해야 한다.
- planner prompt는 tests stage 파일이 `api_obligations`에 정의된 public class/function/method를
  import/call/assert하도록 지시해야 한다.
- internal helper, private symbol, TypeVar 같은 typing helper는 `api_obligations`에 넣지 않도록
  일반 규칙으로 안내한다.

## Phase 7. Completion Gate for Weak Tests and Documentation Drift

대상:

- `src/allCode/agent/completion_checker.py`
- `src/allCode/agent/workflow_completion.py`
- `tests/integration/test_generation_workflow.py`

문제:

- planner/editor prompt 강화만으로는 모델이 generic smoke test를 생성하는 경로를 완전히 차단하지
  못한다.
- 실제 round12 산출물은 기능 구현은 있었지만 tests가 `greet()`만 검증했고 README는 존재하지 않는
  파일 구조(`cli.py`, `storage.py`, `utils/retry.py`)를 언급했다.

구현:

1. CompletionChecker는 tests stage 파일이 있으면 planned/explicit public API obligations 중
   의미 있는 symbol을 실제 test file content가 참조하는지 확인한다.
2. 테스트가 하나의 placeholder API만 참조하고 주요 public API obligations를 전혀 다루지 않으면
   `test coverage does not exercise public API obligations` 오류로 완료를 차단한다.
3. 이 오류는 repair 가능한 completion failure로 취급해 tests와 source를 함께 고칠 수 있게 한다.
4. README/문서 파일에 존재하지 않는 `.py` 경로가 project structure나 import 예시로 등장하면
   `documentation references missing file` 오류로 완료를 차단한다.
5. 이 게이트는 특정 샘플 함수명, 프로젝트명, 벤치마크명을 보지 않고 plan/source/test/doc의 구조적
   관계만 검사한다.

## Phase 8. Validation-First Repair Context Ordering

대상:

- `src/allCode/agent/workflow_repair.py`
- `tests/integration/test_generation_workflow.py`

문제:

- validation 실패와 documentation drift가 동시에 repair prompt에 들어가면 모델이 README만 고치거나
  테스트 실패를 고치던 구현 파일을 다시 약화시키는 사례가 있다.

구현:

1. validation 실패를 수리하는 `repair_until_valid` 단계에서는 public API, syntax, test coverage,
   validation failure를 우선 제공한다.
2. `documentation references missing file ...` 오류는 validation 실패 단계에서는 제외하고,
   validation이 통과한 뒤 `repair_completion_check` 단계에서 처리한다.
3. 실패를 숨기지 않는다. 최종 completion check에서는 documentation drift를 계속 차단한다.
4. 특정 README 문구나 파일명을 하드코딩하지 않고 오류 prefix와 단계 상태만 기준으로 분리한다.

## Phase 9. Literal Public API Repair Guidance

대상:

- `src/allCode/agent/workflow_editor.py`
- `tests/unit/agent/test_workflow_editor.py`

문제:

- 모델이 `TaskStore.add` obligation을 `TaskStore.add_task`처럼 의미적으로 비슷하지만 다른 이름으로
  구현하면 AST completion gate가 계속 실패한다.
- Python class body에서 instance method를 decorator처럼 사용하는 등 import-time 오류를 만드는
  구현이 repair 루프를 낭비한다.

구현:

1. repair/editor prompt에 `Class.method` obligation은 같은 class에 같은 method name으로 정의해야
   한다고 명시한다.
2. 누락 symbol을 wrapper/renamed helper로 대체하지 말고 listed name 그대로 export하라고 안내한다.
3. Python 파일 repair에서는 class definition time에 instance method decorator를 쓰는 패턴을 피하고,
   module-level decorator 또는 인스턴스 생성 후 명시적 registration을 사용하라고 안내한다.
4. 특정 클래스명, 함수명, 프로젝트명을 본체 코드에 하드코딩하지 않는다.

## Phase 10. Contract-Preserving Editor Output and Strong Python CLI Scaffold

대상:

- `src/allCode/agent/workflow_editor.py`
- `src/allCode/generation/strategies/python.py`
- `tests/unit/agent/test_workflow_editor.py`
- `tests/unit/generation/test_strategy_paths.py`

문제:

- model editor가 강한 plan content를 약한 `greet()` 파일로 덮어쓸 수 있다.
- deterministic Python strategy가 featureful CLI 요청에도 generic greeting scaffold만 제공한다.

구현:

1. editor가 Python source file을 생성할 때 planned content가 가진 public API symbol 계약을 새 content가
   크게 잃으면 model output을 폐기하고 planned content를 유지한다.
2. 이 검사는 특정 symbol명을 하드코딩하지 않고 AST 기반 public symbol 추출 결과의 보존 비율을 본다.
3. Python strategy는 prompt가 CLI/command + registry/retry/json/task/test/doc 같은 일반 feature
   signal을 포함하면 one-file이더라도 command registry, JSON-backed store, retry, pytest tests,
   README가 맞물린 강한 기본 scaffold를 생성한다.
4. 이 fallback scaffold는 특정 프로젝트명/테스트 디렉터리에 묶이지 않고 target/package 이름에서
   안전하게 파생한다.
