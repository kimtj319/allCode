# 48. 95% Parity: Deep Source Evidence and Validation Truth Plan

## 목적

`plan/45`의 평균 추정 진척도는 90-91%다. 2026-06-09 동일 프롬프트 비교에서
95%를 막는 다음 두 결함이 재현되었다.

1. source-flow 분석에서 allCode는 `source_probe`의 header/signature 근거에
   과하게 머물러, 사용자가 "핵심 함수 본문 근거"를 요구해도 실제 본문 흐름
   근거가 부족하다.
2. 복잡 프로젝트 생성에서 allCode는 생성된 테스트 파일에 SyntaxError가 있음에도
   validation passed를 보고했다. agy는 같은 요청에서 패키징, 설치, CLI 실행,
   pytest까지 확인했다.
3. SyntaxError false-positive를 막은 뒤 같은 계열 생성에서 allCode는 실패를
   정확히 보고했지만, Python package형 요청에서 top-level `cli.py`를 만들고 테스트는
   package import를 기대해 `ModuleNotFoundError`가 발생했다.

이 계획은 오픈소스 CLI coding agent의 현실적 동작 원칙을 allCode MVP 범위 안에서
반영해 두 결함을 닫는 것을 목표로 한다.

## 오픈소스 참고 원칙

- Aider repo map: 전체 파일 dump 대신 symbol/signature 중심으로 시작하지만,
  실제 수정/분석이 필요한 지점은 관련 함수 본문을 더 읽어 모델이 구체 근거를 갖게
  한다.
- OpenHands action/observation: tool observation은 구조화된 이벤트이고, completion은
  실제 실행/검증 observation에 의해 결정되어야 한다. 검증 명령 문자열만 있으면
  성공으로 보지 않는다.
- Gemini CLI memory/context: 사용자가 명시한 출력 의무와 constraints는 매 라운드
  compact context로 유지해야 한다.
- Qwen Code: provider-neutral tool schema를 유지하면서 terminal-first 실행 검증을
  중시한다.

## 비교 근거

### Source-flow 분석

프롬프트:

```text
코드 수정은 엄격히 금지한다. src/allCode/agent의 라우팅, 툴 실행, 최종 답변 생성 흐름을 실제 파일 근거 기준으로 깊게 분석해줘. 단순 디렉터리 요약이 아니라 핵심 함수 본문 근거를 포함하고, 병목과 개선점을 각각 3개씩 제시해줘.
```

- allCode: 대표 파일과 import/header 근거는 제공했지만 "함수 본문 전체가 포함되지
  않아 상세 로직을 완전히 파악하지 못함"이라고 스스로 한계를 보고했다.
- agy: `loop.py`, `model_router.py`, `route_validator.py`, `tool_call_processor.py`,
  `round_tool_handler.py`, `finalization.py`의 실제 진입점과 line 링크를 더 깊게
  연결했다.

### Project generation

프롬프트:

```text
./output/parity95_round3_cli 안에 표준 라이브러리만 사용하는 Python 패키지형 CLI를 실제로 생성해줘. 기능은 JSONL 로그 뷰어다. config 로딩, command registry, tail 명령, filter 명령, retry helper, pytest 테스트, README를 포함해야 한다. 생성 후 검증을 실행하고 최종 보고서에는 생성 파일과 검증 결과를 포함해줘.
```

- allCode: `tests/test_cli.py`에 unterminated string SyntaxError가 있었지만
  최종 보고서에서 `python -m pytest -q` 통과를 주장했다.
- 직접 검증: `python -m pytest -q output/parity95_round3_cli/tests`는 collection
  SyntaxError로 실패했다.
- agy: 별도 target root에서 package layout, pytest, editable install, entrypoint,
  tail/filter command smoke까지 검증했다.

추가 round4 관찰:

- allCode는 실패를 success로 오보고하지 않았지만 `output/parity95_round4_cli/cli.py`
  같은 flat layout을 만들었고 `tests/test_cli.py`는 `from parity95_round4_cli import cli`
  를 사용했다.
- 직접 검증 결과 `ModuleNotFoundError: No module named 'parity95_round4_cli'`.
- 따라서 validation truth gate 다음 단계는 prompt-derived package obligation을
  planning/sanitization 단계에서 importable layout으로 정규화하는 것이다.

## Phase 1. Deep Source Probe Evidence

대상:

- `src/allCode/tools/builtin/source_probe.py`
- `tests/unit/tools/test_source_probe_tool.py`

구현:

1. 넓은 심볼(`wide_symbols`)에 대해 기존 header/child signature만 반환하지 않고,
   제한된 body sample range를 추가한다.
2. body sample은 full-file dump가 아니어야 한다. 한 wide symbol당 작은 range만
   추가하고 `max_ranges` 제한을 지킨다.
3. observation metadata의 wide symbol summary를 "header/body sample/child signature"
   형태로 갱신해 final answer 합성이 실제 본문 근거가 있음을 알 수 있게 한다.
4. 특정 파일명, 함수명, 테스트 프롬프트 문자열을 보지 않는다.

주의:

- 대형 파일 full dump 금지.
- secret redaction 유지.
- 기존 range limit과 workspace path policy 유지.

## Phase 2. Generation Validation Truth Gate

대상:

- `src/allCode/agent/completion_checker.py`
- `src/allCode/agent/workflow_completion.py`
- `tests/integration/test_generation_workflow.py` 또는 신규 unit test

구현:

1. `CompletionChecker`가 plan의 required Python files를 대상으로 AST parse를 수행해
   SyntaxError를 completion error로 잡는다.
2. 이 검사는 validation command가 성공했다고 기록되어도 별도로 수행한다.
3. 오류 메시지는 repair loop가 사용할 수 있게 `python syntax error in <path>:<line>`
   형태로 구체화한다.
4. validation command가 target root 밖에서 실행되어 root repo 테스트만 통과하는
   false-positive를 줄이기 위해, plan target root 하위 required file syntax를
   completion gate의 독립 근거로 둔다.
5. `workflow_completion.completion_check_repairable`은 `python syntax error` completion
   error를 repairable로 취급해 모델/strategy repair loop가 실제로 수리할 기회를 갖게
   한다.

주의:

- pytest 자체를 하드코딩해서 성공/실패를 조작하지 않는다.
- 특정 output 디렉터리명이나 scenario ID를 보지 않는다.
- SyntaxError가 있으면 final report success 금지.
- SyntaxError를 잡은 뒤 즉시 실패만 반환하면 회귀 개선 효과가 작으므로, repair loop
  연결까지 함께 구현한다.

agy 검토 반영:

- `source_probe.py`의 body sample은 `MAX_BODY_SAMPLE_LINES` 같은 엄격한 상수로
  제한한다.
- `CompletionChecker.check` 내부에서 AST parse를 수행하는 위치가 가장 안전하다.
- `completion_check_repairable`이 기존 `public API` 에러만 repairable로 보던 조건을
  `python syntax error`까지 확장해야 한다.
- 비-파이썬 파일, 인코딩 문제, 파일 시스템 오류는 checker가 비정상 종료되지 않도록
  안전하게 error로 수집한다.

## Phase 3. Python Package Layout Obligation

대상:

- `src/allCode/agent/project_planner.py`
- `tests/unit/agent/test_project_planner.py`

구현:

1. prompt가 Python package/패키지형 CLI를 요구하면 model plan의 top-level Python
   implementation files를 safe package directory 아래로 정규화한다.
2. target root basename을 package candidate로 사용하되 Python identifier로 안전하게
   정규화한다.
3. `pyproject.toml`이 없으면 최소 pytest/import 가능한 project metadata seed를
   추가한다.
4. tests, README, pyproject는 이동하지 않는다.

주의:

- 특정 target 이름(`parity95_round4_cli`)을 보지 않는다.
- 단일 파일 스크립트 요청에는 적용하지 않는다.
- 모델이 이미 `src/<pkg>` 또는 `<pkg>/` layout을 만든 경우 중복 이동하지 않는다.

## Phase 4. Generation Workflow Handoff Hardening

대상:

- `src/allCode/agent/prompt_constraint_detection.py`
- `src/allCode/agent/workflow_routing.py`
- `tests/unit/agent/test_prompt_constraints.py`
- `tests/unit/agent/test_workflow_handoff.py`

round5 관찰:

- Python package layout 정규화는 planner 경로에 적용되었지만, 실제 headless 실행은
  generation workflow가 아니라 일반 tool loop로 떨어졌다.
- 실패 프롬프트는 `./output/<name> 안에 ... 패키지형 CLI ... 생성해줘` 형태였고,
  기존 directory-output/context root 감지는 `안에` 조사를 처리하지 못했다.
- 그 결과 기존 workspace에 소스가 존재하는 상황에서 `infer_generation_target_root`가
  `None`을 반환했고, `should_use_generation_workflow`가 handoff를 거부했다.

구현:

1. `directory_output_hint`가 한국어 위치 조사 `안에`를 directory output context로
   인식하게 한다.
2. `infer_generation_target_root`도 `경로에/아래에/하위에/내부에`뿐 아니라 `안에`를
   명시 directory target으로 인식하게 한다.
3. `NEW_PROJECT_MARKERS`에는 일반적 프로젝트/패키지 생성 의도를 나타내는
   `패키지형`, `패키지 생성` 수준의 구조 신호만 추가한다.
4. prompt constraint와 workflow handoff 단위 테스트를 추가해 기존 workspace에서도
   명시 output directory 생성 요청이 generation workflow로 넘어가는지 검증한다.

주의:

- `안` 단독은 부정 표현과 충돌하므로 추가하지 않는다.
- 특정 output 디렉터리명, 테스트 프롬프트, scenario ID를 보지 않는다.
- 기존 파일 수정 요청이 generation workflow로 잘못 넘어가지 않게 suffix target guard를
  유지한다.

agy 검토 반영:

- 최소 수정으로 `안에` 조사와 explicit directory-root regex만 확장한다.
- 한국어 조사 다양성은 남은 리스크로 두되, 우선 가장 재현된 `안에`만 안전하게 다룬다.
- 단위 테스트는 prompt constraint 감지와 existing workspace handoff를 둘 다 포함한다.

## Phase 5. Comparison and Progress Update

검증:

```bash
python -m pytest tests/unit/tools/test_source_probe_tool.py \
  tests/unit/agent/test_project_planner.py \
  tests/unit/agent/test_prompt_constraints.py \
  tests/unit/agent/test_workflow_handoff.py \
  tests/integration/test_generation_workflow.py

python -m pytest tests/unit/agent tests/unit/tools tests/integration/test_generation_workflow.py
python -m pytest
```

실제 비교:

1. source-flow deep analysis prompt를 allCode/agy에 동일 실행.
2. `./output/parity95_round6_cli` 생성 prompt를 allCode에 실행하고 실제
   `python -m pytest -q <target>/tests`로 재검증.
3. 결과가 개선되면 `plan/45_parity_progress_tracker.md`를 갱신한다.

## 95% 판단 기준

이번 계획이 완료돼도 평균 95%를 바로 선언하지 않는다. 다음 조건을 모두 만족해야
진척도를 올린다.

- source analysis가 header/signature 근거뿐 아니라 body sample 근거를 사용한다.
- generation workflow가 SyntaxError 산출물을 success로 보고하지 않는다.
- 실제 산출물 pytest가 성공하거나, 실패 시 final answer가 실패를 정확히 보고한다.
- 기존 unit/integration/quality/tty 회귀가 깨지지 않는다.

## Phase 6. Source Analysis Body-Evidence Synthesis

round6 source-flow 관찰:

- `source_probe`가 class-level `symbol_body_sample` range를 반환하기 시작했지만,
  답변 합성은 여전히 넓은 핵심 메서드를 `header/signatures only`로 설명했다.
- 사용자가 "핵심 함수 본문 근거"를 요구한 경우 agy는 실제 주요 함수의 흐름을 설명했지만,
  allCode는 관찰 범위와 import 연결을 나열하는 수준에 머물렀다.

대상:

- `src/allCode/tools/builtin/source_probe.py`
- `src/allCode/agent/source_answer_synthesis.py`
- `tests/unit/tools/test_source_probe_tool.py`
- `tests/unit/agent/test_source_answer_synthesis.py`

구현:

1. 넓은 parent symbol의 child method/function에 대해 signature 3줄만 반환하지 않고,
   `MAX_BODY_SAMPLE_LINES` 이하의 `child_body_sample` range를 반환한다.
2. 기존 class-level `symbol_body_sample`과 child-level `child_body_sample`을 합쳐도
   `max_ranges` 상한을 지킨다.
3. wide symbol label은 하드코딩된 `header/signatures only` 문구 대신 observation의
   `summary`를 사용한다.
4. 최종 답변 합성 brief가 child body sample anchor를 대표 근거로 노출하게 한다.

주의:

- full-file dump 금지.
- 특정 함수명이나 테스트 프롬프트 하드코딩 금지.
- 모델 답변 자체를 템플릿으로 대체하지 않고, 더 나은 근거를 제공하는 데 집중한다.

## Phase 7. Source Final-Answer Recovery Quality

round6 source-flow 로그 관찰:

- 모델 1차 답변은 import anchor를 클래스/메서드 동작 근거처럼 사용해
  `source_answer_mismatched_anchor`에 걸렸다.
- 재요청에서는 모델이 reasoning-only로 돌아왔고, `safe_source_analysis_answer` fallback이
  최종 답변이 되었다.
- 현재 fallback은 안전하지만 사용자가 요구한 `핵심 함수 본문 근거`, `병목 3개`,
  `개선점 3개` 같은 출력 의무를 충분히 만족하지 못한다.

대상:

- `src/allCode/agent/source_answer_guard.py`
- `src/allCode/agent/source_answer_fallback.py`
- `tests/unit/agent/test_source_answer_guard.py`
- `tests/unit/agent/test_source_answer_fallback.py`

구현:

1. source-answer retry prompt에 "최종 답변 본문을 바로 작성하고 reasoning-only로 끝내지
   말라"는 지시를 추가한다.
2. fallback은 prompt에서 병목/개선점 개수 요구를 일반 패턴으로 추출한다.
3. fallback은 관찰된 대표 파일, line anchor, import/reference edge, wide symbol summary만
   사용해 다음을 생성한다.
   - 관찰 근거 기준 핵심 흐름
   - 요청된 개수의 후보 병목
   - 요청된 개수의 개선점
4. 개선점은 특정 테스트 프롬프트가 아니라 관찰된 결핍 신호에서 나온다.
   예: coverage 제한, 미관찰 대표 후보, wide symbol body sampling 한계, edge 부족,
   anchor mismatch 위험.

주의:

- fallback은 모델 답변을 대체하는 정상 경로가 아니라 guard/retry 실패 시의 안전망이다.
- 특정 파일명 기반 예외는 만들지 않고, 파일명 token과 관찰 메타데이터에 기반한 일반적
  역할 추론만 허용한다.
- 관찰되지 않은 호출 관계를 단정하지 않는다.

## Phase 8. Source Answer Retry Context Hygiene

관찰:

- source-answer guard가 모델 답변을 거부한 뒤, 기존 retry 메시지는 잘못된 이전 답변
  전체를 assistant 메시지로 다시 넣었다.
- 이 방식은 잘못된 anchor 사용을 모델 컨텍스트에 다시 강화하고, 일부 모델에서
  reasoning-only 회피 응답을 유발할 수 있다.

구현:

1. retry 시에는 잘못된 이전 답변 전체를 재주입하지 않는다.
2. 대신 violation reason과 compact excerpt만 user feedback으로 제공한다.
3. 이미 관찰된 tool evidence와 final answer instruction은 유지하되, 오염된 산출물은
   제거한다.

주의:

- guard 기준을 낮추지 않는다.
- raw action 답변이나 mismatched anchor 답변을 success로 허용하지 않는다.
