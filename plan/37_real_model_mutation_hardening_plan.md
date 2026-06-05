# 37. Real-Model Mutation And Generation Hardening Plan

## 목적

이 문서는 `plan/36_agy_parity_agent_hardening_plan.md` 이후의 보강 계획이다.
목표는 실제 모델이 임시 프로젝트에서 코드 수정, 신규 구현, 검증, 수리 작업을 수행할 때
agy 수준에 더 가깝게 수렴하도록 만드는 것이다.

범위는 기존 MVP agent loop, validation/repair, generation workflow 강화로 한정한다.
git auto-commit, plugin marketplace, MCP server manager, multi-agent swarm, cloud sandbox,
full interactive diff editor는 도입하지 않는다.

## 기준 문서

구현 전 아래 문서를 다시 확인한다.

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/09_generation_workflow_plan.md`
6. `plan/27_validation_repair_convergence_plan.md`
7. `plan/36_agy_parity_agent_hardening_plan.md`
8. 이 문서

충돌 시 `plan/00`~`12`와 `plan/01`을 우선한다.

## agy 검토 반영 요약

agy에는 코드 수정, 파일 생성, 파일 삭제, 포맷팅, 커밋, 푸쉬를 금지하고 계획 검토만
요청했다. 피드백의 핵심은 다음과 같다.

1. related test 후보는 단순 패턴 생성이 아니라 실제 디스크에 존재하는 파일만 후보로
   기록해야 한다.
2. phase gate는 너무 강하면 교착될 수 있다. discovery가 1회 이상 수행되었거나 실존
   후보가 없으면 validation으로 진행할 fallback이 필요하다.
3. prompt에 넣는 public symbol은 많을수록 품질이 떨어진다. public API와 새로 추가된
   심볼 위주로 3~5개만 전달하고 private symbol은 제외한다.
4. Python `__all__`은 정적 문자열 리터럴 list/tuple만 신뢰한다. 동적 export는
   단정하지 않는다.
5. 비-Python regex fallback은 주석 제거 후 매칭해야 하며, 오탐 가능성을 인정해야 한다.
6. completion checker가 누락 API를 발견했을 때, 실패 근거가 self-repair 루프에
   재주입되어야 한다.

## 오픈소스 패턴과 allCode 적용

### Aider

- Aider의 repo map/test-fix 흐름처럼 변경 source와 관련 테스트를 연결한다.
- allCode 적용은 git workflow가 아니라 `CompletionEvidence`와 validation evidence 중심으로
  제한한다.

### OpenHands

- Action -> Observation 이벤트를 기준으로 phase block을 명확히 만든다.
- allCode 적용은 external hook system이 아니라 기존 `PhaseToolGate`와 event stream을
  강화하는 방식이다.

### Gemini CLI

- hierarchical context처럼 compact하고 inspectable한 repair context만 전달한다.
- raw validation log나 full-file dump를 반복 주입하지 않는다.

### Qwen Code

- provider-neutral terminal agent 방식을 유지한다.
- 특정 모델명, 공급자, 테스트 prompt에 대한 분기를 만들지 않는다.

## 금지 사항

- 특정 prompt, scenario ID, benchmark path, 프로젝트명, 모델명 하드코딩 금지.
- 실존하지 않는 테스트 파일을 validation 후보로 단정하지 않는다.
- read-only route에서 mutation, shell, validation tool을 노출하지 않는다.
- API obligation checker가 동적 언어 기능을 과도하게 단정하지 않는다.
- 새 파일 또는 수정 파일은 500줄을 넘기지 않는다.

## 구현 Phase

### Phase 1. API Obligation Checker 강화

수정 파일:

- `src/allCode/agent/api_obligation_checker.py`
- `src/allCode/agent/completion_checker.py`
- 관련 tests

작업:

- Python AST에서 top-level public function/class/assignment 외에 public class method를
  `ClassName.method` 형태로 추출한다.
- `__all__ = ["Name", ...]` 또는 `__all__ = ("Name", ...)` 같은 정적 리터럴만
  export obligation으로 인정한다.
- planned content의 public API와 실제 파일의 public API를 비교한다.
- validation failure에서 추출된 `public_api_expectations`도 실제 public API와 비교한다.
- 비-Python은 이번 구현에서 full parser를 도입하지 않고, 주석 제거 regex fallback은
  계획만 남긴다.

완료 기준:

- 계획 파일에 있던 class method가 실제 생성 파일에서 빠지면 completion이 실패한다.
- 실제 파일에 method가 있으면 completion이 통과한다.
- 동적 `__all__`은 실패 근거로 단정하지 않는다.

### Phase 2. Related Test Candidate Inference 강화

수정 파일:

- `src/allCode/agent/related_tests.py`
- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/tool_evidence.py`
- 관련 tests

작업:

- 변경된 source path에서 일반적인 테스트 후보 path를 추론한다.
  - Python: `tests/test_<stem>.py`, `tests/<package>/test_<stem>.py`,
    `<source_dir>/test_<stem>.py`
  - Go: `<source_dir>/<stem>_test.go`
  - JS/TS: `<source_dir>/<stem>.test.ts`, `<source_dir>/<stem>.spec.ts`,
    `tests/<package>/<stem>.test.ts`
- 추론 후보 중 실제 존재하는 파일만 `related_test_candidates`에 기록한다.
- private symbol은 discovery prompt 후보에서 제외한다.
- 실존 후보가 없고 discovery가 1회 이상 끝났으면 validation 진행을 허용한다.

완료 기준:

- source 변경 후 workspace에 기존 관련 테스트 파일이 있으면 discovery 없이도 후보로
  기록된다.
- 관련 테스트 후보가 없어도 discovery가 한 번 끝났으면 phase gate가 교착되지 않는다.

### Phase 3. Prompt And Phase Feedback 동기화

수정 파일:

- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/phase_block.py`
- `src/allCode/agent/round_response_handler.py`

작업:

- related-test discovery prompt에는 changed source path와 public symbol을 compact하게 넣는다.
- completion/API obligation 실패 근거는 다음 repair request의 `Blocked phase feedback`으로
  전달 가능해야 한다.
- final answer 전에 validation 또는 API obligation이 부족하면 success로 가지 않는다.

완료 기준:

- prompt builder tests가 related discovery 지침, mutation 금지, validation 보류를 검증한다.

### Phase 4. Completion Repair Feedback

수정 파일:

- `src/allCode/agent/workflow.py`
- `src/allCode/agent/completion_checker.py`
- 관련 generation workflow tests

작업:

- validation 통과 후 completion checker가 API obligation 누락을 발견하면 즉시 실패하지 않고
  bounded completion repair를 1회 시도한다.
- repair는 기존 `strategy.repair_files(plan, failure_log)`를 사용한다.
- 동일 실패가 반복되면 partial/failed 상태로 종료하고 누락 근거를 error message에 남긴다.

완료 기준:

- completion checker 오류가 repair loop에 전달된다.
- repair 후 validation이 다시 통과하고 API obligation이 만족되면 success가 된다.

### Phase 5. Real-Model Smoke Harness

이번 구현에서는 source code 변경 범위가 커지는 것을 막기 위해 자동 harness는 만들지 않는다.
대신 다음 수동 검증 절차를 문서화한다.

```bash
mkdir -p output/real_model_smoke
allcode --workspace output/real_model_smoke --headless "<mutation prompt>"
```

평가 항목:

- 파일 mutation 전 대상 파일을 읽는가.
- 변경 후 related test 후보를 찾는가.
- validation 없이 success를 반환하지 않는가.
- validation 실패 시 실패 파일/line/symbol을 근거로 repair하는가.
- final answer에 생성/수정 파일, 검증 명령, 결과, 남은 리스크가 포함되는가.

## 검증 계획

집중 테스트:

```bash
python -m pytest tests/unit/agent/test_phase_gate.py tests/unit/agent/test_prompt_builder.py tests/unit/agent/test_tool_evidence.py tests/integration/test_generation_workflow.py
```

회귀 테스트:

```bash
python -m pytest tests/unit/agent tests/unit/tools tests/unit/core tests/integration/test_generation_workflow.py tests/integration/test_mock_agent_loop.py tests/integration/test_headless_runner.py
```

실모델 smoke는 저장소 오염을 막기 위해 `output/real_model_smoke` 하위 workspace에서만
진행한다.
