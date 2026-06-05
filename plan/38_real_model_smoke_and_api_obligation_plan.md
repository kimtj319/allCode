# 38. Real-Model Smoke And Cross-Language API Obligation Plan

## 목적

`plan/37_real_model_mutation_hardening_plan.md` 이후 남은 다음 단계를 실제 코드 기준으로
구체화한다. 목표는 실모델 검증을 저장소 오염 없이 반복 가능하게 만들고, Python에 한정된
API obligation 검사를 현실적으로 확장하는 것이다.

이 계획은 MVP 범위 안에서만 진행한다. git auto-commit, plugin marketplace, MCP server
manager, multi-agent swarm, cloud sandbox, full interactive diff editor는 도입하지 않는다.

## 기준 문서

구현 전 아래 문서를 확인한다.

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/09_generation_workflow_plan.md`
6. `plan/27_validation_repair_convergence_plan.md`
7. `plan/37_real_model_mutation_hardening_plan.md`
8. 이 문서

충돌 시 `plan/00`~`12`와 `plan/01`을 우선한다.

## agy 검토 요약과 보정

agy에는 코드 수정 금지 조건으로 다음 단계 검토를 요청했지만, 실제로는 계획 artifact와
일부 코드 초안을 생성했다. 따라서 agy 결과는 그대로 수용하지 않고 다음 기준으로 재검수한다.

agy 피드백 중 채택:

- 실모델 smoke는 기본 테스트에서 실행되지 않도록 명시적 opt-in 환경 변수로 보호한다.
- 실모델 smoke assertion은 exact answer가 아니라 구조적 근거를 본다.
- 비-Python API obligation은 parser가 없는 언어에 한해 제한적 regex fallback으로 처리한다.
- validation log는 긴 단일 라인이 context를 오염시키지 않도록 줄 단위로 압축한다.

agy 초안 중 보정:

- `ALLCODE_MODEL_NAME` 같은 비계약 환경 변수는 사용하지 않는다. 실제 설정 계약인
  `ALLCODE_MODEL`, `ALLCODE_BASE_URL`, `ALLCODE_API_KEY`, `ALLCODE_API_KEY_ENV`를 따른다.
- smoke harness는 `AppConfig()`를 직접 구성하지 않고 `ConfigManager`와 `ConfigOverrides`를
  사용해 실제 runtime precedence와 맞춘다.
- non-Python regex는 public symbol만 제한적으로 추출하고, private/internal symbol을 public
  obligation으로 승격하지 않는다.
- 특정 테스트 prompt, scenario ID, 프로젝트명, 모델명, endpoint를 runtime source에
  하드코딩하지 않는다.

## 오픈소스 패턴 적용

### Aider

- 테스트 실행 후 실패를 repair input으로 사용한다.
- allCode 적용: smoke는 파일 변경, 검증 실행, 최종 보고 근거를 구조적으로 검사한다.

### OpenHands

- action/event/observation 기반으로 실행을 관찰한다.
- allCode 적용: smoke는 exact text 대신 `TurnResult`, 파일 상태, validation evidence를 본다.

### Gemini CLI

- context는 compact하고 inspectable해야 한다.
- allCode 적용: validation log summary에서 긴 줄을 압축해 prompt/context 오염을 줄인다.

### Qwen Code

- provider-neutral terminal-first 방식을 유지한다.
- allCode 적용: smoke harness는 특정 provider branch 없이 기존 OpenAI-compatible adapter 설정을 사용한다.

## 구현 Phase

### Phase 1. Opt-In Real-Model Smoke Harness 정리

수정/생성 파일:

- `tests/smoke/conftest.py`
- `tests/smoke/test_real_model_smoke.py`

작업:

- `ALLCODE_SMOKE_TESTS=1`이 없으면 smoke tests는 skip한다.
- 모델 설정은 `ConfigManager().load(ConfigOverrides(workspace=..., approval="auto"))`로 생성한다.
- smoke workspace는 pytest `tmp_path` 하위에만 만든다.
- assertion은 exit code, 변경 파일 존재, 구조적 symbol 포함 여부처럼 deterministic한 근거를 본다.
- exact final answer 문구, 특정 모델명, 실제 외부 endpoint는 검사하지 않는다.

완료 기준:

- 기본 `python -m pytest tests/smoke/test_real_model_smoke.py`는 API 호출 없이 skip된다.
- opt-in 실행 방법은 문서화되며, live model 비용/네트워크 리스크가 명시된다.

### Phase 2. Cross-Language API Obligation Fallback 제한 적용

수정/생성 파일:

- `src/allCode/agent/api_obligation_checker.py`
- `tests/unit/agent/test_api_obligation_checker.py`

작업:

- Python은 AST checker를 계속 사용한다.
- JS/TS, Go, Rust, Java는 parser가 없을 때만 comment-stripped regex fallback을 사용한다.
- JS/TS는 exported function/class/const와 class public method를 제한적으로 추출한다.
- Go는 대문자로 시작하는 exported function/method만 추출한다.
- Rust는 `pub fn`, `pub struct`, `pub enum`, impl block의 `pub fn`만 추출한다.
- Java는 public class와 public method만 추출한다.
- class method obligation은 `ClassName.method`와 method-only expectation 모두 만족 가능하게 비교한다.

완료 기준:

- public symbol 누락은 completion check 오류로 남는다.
- private/internal symbol은 누락 obligation으로 승격되지 않는다.
- comment 속 가짜 symbol은 추출되지 않는다.

### Phase 3. Validation Log Summary 압축

수정 파일:

- `src/allCode/agent/validation_runner.py`
- 관련 tests

작업:

- 긴 단일 로그 라인을 summary 단계에서 줄 단위로 압축한다.
- 실패 marker 탐색은 유지하되, summary 출력이 context를 과도하게 차지하지 않도록 한다.

완료 기준:

- 긴 stdout/stderr 라인이 summary에 그대로 들어가지 않는다.
- 기존 validation failure summary semantics는 유지된다.

### Phase 4. 검증

집중 테스트:

```bash
python -m pytest tests/unit/agent/test_api_obligation_checker.py tests/smoke/test_real_model_smoke.py tests/integration/test_generation_workflow.py
```

회귀 테스트:

```bash
python -m pytest
```

실모델 opt-in smoke:

```bash
ALLCODE_SMOKE_TESTS=1 python -m pytest tests/smoke/test_real_model_smoke.py
```

주의: 실모델 smoke는 네트워크, API token, 비용, 모델 비결정성에 의존하므로 기본 회귀 테스트에는
포함하지 않는다.
