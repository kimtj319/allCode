# 50. 95% Parity: Source Evidence and Generated CLI Documentation Consistency

## 목적

`plan/45` 기준 allCode의 평균 진척도는 92-93%다. 95%에 도달하지 못한 핵심
원인은 다음 두 축이다.

1. 소스 분석 답변은 구조화되어 있지만, agy 수준에 비해 함수 본문 근거와 실행
   책임 연결이 약하다.
2. 생성 workflow는 pytest 통과까지는 도달했지만, README/사용법 문서가 실제
   CLI parser와 어긋나는 경우를 completion gate가 충분히 차단하지 못한다.

이번 계획은 특정 프롬프트, 출력 디렉터리, 테스트 시나리오 ID를 하드코딩하지
않고, 구조화된 근거와 실제 산출물 관계만 사용해 두 축을 보강한다.

## 현재 코드 기준 관찰

- `src/allCode/agent/source_answer_guard.py`는 관찰되지 않은 파일/심볼/앵커와
  raw tool JSON 출력은 차단하지만, 사용자가 "핵심 함수 본문 근거"를 요구했을 때
  모델 답변이 본문 sample anchor를 실제로 사용했는지까지는 검사하지 않는다.
- `src/allCode/agent/source_analysis_rendering.py`는 representative anchor를
  brief에 넣지만, body sample anchor를 별도 우선순위 블록으로 강조하지 않는다.
- `src/allCode/agent/source_answer_fallback.py`는 fallback 답변에서만 본문 근거
  섹션을 구성한다. 정상 모델 답변 경로의 품질을 올리려면 fallback이 아니라
  final-answer request/guard가 강화되어야 한다.
- `src/allCode/agent/completion_checker.py`는 README가 존재하지 않는 파일을
  언급하는 drift는 잡지만, README가 존재하지 않는 CLI subcommand나 option을
  설명하는 drift는 잡지 않는다.

## 오픈소스 참고 원칙

- Aider repo map은 전체 repo에서 중요한 class/function/signature와 핵심 정의
  라인을 token budget에 맞춰 제공하고, 필요하면 모델이 해당 파일을 더 보게
  한다. allCode에는 `source_overview`/`source_probe`가 있으므로, body sample이
  있는 대표 심볼을 최종 합성에서 더 강하게 우선시한다.
- OpenHands tool system은 `Action -> Observation` 구조화 계약을 강조한다.
  allCode completion gate도 "파일이 존재한다" 수준이 아니라 README usage라는
  관찰 가능한 산출물과 parser AST라는 관찰 가능한 산출물을 대조해야 한다.
- Gemini CLI는 `GEMINI.md` 계층 memory와 `/memory show/refresh`처럼 컨텍스트를
  명시적으로 관리한다. allCode는 이번 계획에서 새 memory 기능을 확장하지 않고,
  source brief에 현재 관찰 근거를 더 압축해 주입하는 방식만 사용한다.
- Qwen Code는 provider-neutral 설정과 terminal-first 흐름을 유지한다. 이번
  보강도 core/provider/TUI 결합 없이 agent와 completion checker 경계에서 처리한다.

## Phase 1. Source Body Evidence Quality Gate

대상:

- `src/allCode/agent/source_answer_guard.py`
- `tests/unit/agent/test_source_answer_guard.py`

구현:

1. 사용자 프롬프트가 함수/메서드/본문/body 근거를 요구하는지 구조적으로 감지한다.
2. 관찰된 `source_probe` line range 중 `symbol_body_sample` 또는
   `child_body_sample` anchor가 있으면, 최종 답변에는 최소 하나 이상의 body
   sample anchor가 포함되어야 한다.
3. 답변이 body sample을 전혀 사용하지 않고 import/header/signature anchor만
   사용하는 경우 `source_answer_missing_body_evidence`로 retry한다.
4. body sample이 관찰되지 않은 경우에는 실패시키지 않는다. 대신 brief/답변의
   한계 섹션에서 "본문 샘플 근거 부족"을 드러내도록 한다.

금지:

- 특정 파일명, 클래스명, 함수명, 테스트 프롬프트를 조건문에 넣지 않는다.
- body evidence가 없는데 임의 라인 근거를 만들어내지 않는다.

## Phase 2. Source Brief Body Evidence Priority

대상:

- `src/allCode/agent/source_analysis_rendering.py`
- `tests/unit/agent/test_source_answer_synthesis.py`

구현:

1. representative file evidence에서 body sample anchor를 별도 문장으로 먼저
   노출한다.
2. 사용자가 본문 근거를 요구하면 final-answer instruction에 "본문 sample anchor
   우선 사용, 없으면 한계로 명시"를 추가한다.
3. compact brief에서도 body sample anchor를 대표 근거 label에 포함시켜 짧은
   답변에서도 누락되지 않게 한다.

## Phase 3. README / CLI Parser Consistency Gate

대상:

- `src/allCode/agent/completion_checker.py`
- `src/allCode/agent/workflow_repair.py`
- `tests/integration/test_generation_workflow.py`

구현:

1. Python implementation 파일에서 `argparse` parser를 AST 기반으로 추출한다.
   - `add_subparsers()` 결과 변수에 이어지는 `add_parser("name")`
   - `ArgumentParser.add_argument("--flag")`
   - subparser 변수의 `add_argument("--flag")`
2. README와 문서 파일의 code block/inline usage에서 추출한 subcommand/option을
   실제 parser subcommand/option과 대조한다.
3. README가 실제 parser에 없는 subcommand 또는 option을 설명하면 다음 오류로
   completion을 차단한다.
   - `documentation references unsupported CLI command in README.md: ...`
   - `documentation references unsupported CLI option in README.md: ...`
4. 이 오류는 repair 가능한 completion failure로 취급하고 preferred repair target은
   README와 parser가 있는 source file을 함께 제시한다.

금지:

- `greet`, `taskhub`, `status`, `output` 같은 특정 샘플 명령명을 하드코딩하지 않는다.
- README 전체 자연어에서 모든 `--word`를 무조건 option으로 보지 않는다. code block,
  inline command, usage/options 섹션 등 CLI 문맥의 토큰만 추출한다.

## Phase 4. Validation and Real Comparison

집중 테스트:

```bash
python -m pytest tests/unit/agent/test_source_answer_guard.py tests/unit/agent/test_source_answer_synthesis.py tests/integration/test_generation_workflow.py
```

확장 테스트:

```bash
python -m pytest tests/unit/agent tests/unit/tools tests/unit/generation tests/integration/test_generation_workflow.py
python -m pytest
```

실제 동일 프롬프트 비교:

1. source 분석:
   - "코드 수정은 엄격히 금지한다. src/allCode/agent의 라우팅, 툴 실행, 최종 답변
     생성 흐름을 실제 파일 근거 기준으로 깊게 분석해줘. 핵심 함수 본문 근거를
     포함하고, 병목과 개선점을 각각 3개씩 제시해줘."
2. 복잡한 생성:
   - `./output/parity95_round_next_taskhub` 하위에 표준 라이브러리 Python
     package CLI, command registry, JSON 저장소, retry, tests, README를 요구한다.
3. 일반 지식:
   - 외부 최신성이 필요 없는 복잡한 RAG/long-context 품질 질문을 사용한다.

비교 후 `plan/45_parity_progress_tracker.md`를 갱신한다. 95%는 테스트 통과,
실제 모델 smoke, agy와의 답변 밀도 비교가 모두 만족될 때만 기록한다.

## agy 검토 반영 예정

이 계획은 코드 수정 전 agy에게 "코드 수정 금지" 조건으로 검토를 요청한다.
agy 피드백 중 현재 MVP 계약과 충돌하지 않고, 하드코딩 없이 구현 가능한 내용만
아래에 반영한다.

## agy 검토 반영

agy 검토 결과, 계획은 현재 코드 구조에 적용 가능하다고 판단되었다. 반영할
구체 피드백은 다음과 같다.

- `source_answer_guard.py`: 본문/body 요구를 감지하더라도 관찰된 body sample
  anchor가 없으면 실패시키지 않는다. body sample이 관찰된 경우에만 최종 답변이
  최소 하나의 body sample anchor를 사용했는지 검사한다.
- `source_answer_synthesis.py`: `_representative_files`에서 range label을 `[:6]`
  으로 자르기 전에 `symbol_body_sample`, `child_body_sample`을 우선 정렬한다.
  imports/header가 많은 파일에서도 본문 샘플 근거가 렌더링 단계까지 살아남아야
  한다.
- `completion_checker.py`: README CLI 검사는 전체 자연어에서 임의 `--flag`를
  잡는 방식이 아니라, `pyproject.toml [project.scripts]`, package/module 실행
  패턴, code block/inline command context를 기준으로 좁힌다.
- `completion_checker.py`: `argparse` parser는 `main()` 고정 위치가 아니라 AST
  전체를 재귀적으로 훑어 `ArgumentParser`, `add_subparsers`, `add_parser`,
  `add_argument` 호출을 찾는다.
- `workflow_repair.py`: unsupported CLI command/option 오류에는 문서 파일과
  관련 parser source 파일을 함께 포함해 기존 `_split_target_list` 기반 preferred
  repair target 추출을 재사용한다.

agy가 별도로 실행한 기존 집중 테스트는 다음과 같았다.

```bash
python -m pytest tests/unit/agent/test_source_answer_guard.py tests/unit/agent/test_source_answer_synthesis.py tests/integration/test_generation_workflow.py
# 40 passed
```

## 구현 결과

적용 파일:

- `src/allCode/agent/source_answer_guard.py`
- `src/allCode/agent/source_answer_synthesis.py`
- `src/allCode/agent/source_analysis_rendering.py`
- `src/allCode/agent/documentation_cli_consistency.py`
- `src/allCode/agent/completion_checker.py`
- `src/allCode/agent/workflow.py`
- `src/allCode/agent/workflow_editor.py`
- `src/allCode/agent/workflow_repair.py`
- 관련 unit/integration tests

핵심 변경:

1. 사용자가 함수/메서드 본문 근거를 요구했고 `source_probe`가 body sample anchor를
   관찰한 경우, 최종 답변이 body sample anchor를 하나도 사용하지 않으면 retry/fallback
   경로로 보낸다.
2. 대표 range trimming 전에 body sample anchor를 우선 정렬해 imports/header가 본문
   근거를 밀어내지 못하게 했다.
3. source flow edge는 repo 내부 resolved target을 표준 라이브러리/외부 import보다
   먼저 정렬한다.
4. README/문서의 CLI usage는 실제 Python `argparse` AST에서 관찰한 command/option,
   `ArgumentParser(prog=...)`, `pyproject.toml [project.scripts]`와 대조한다.
5. `<command>`, `[options]`, `COMMAND` 같은 문서 placeholder는 실제 subcommand로 보지
   않는다.
6. 모델 editor가 literal `api_obligations`를 drop하거나 이름을 바꾸면 해당 모델 출력을
   폐기하고 planned content를 유지한다.
7. featureful Python CLI 모델 plan은 plan 내부 구현 파일에 api obligation이 선언되어
   있지 않으면 수용하지 않는다.

검증:

```bash
python -m py_compile src/allCode/agent/workflow_editor.py src/allCode/agent/documentation_cli_consistency.py src/allCode/agent/workflow.py src/allCode/agent/api_obligation_checker.py
# success

python -m pytest tests/unit/agent/test_workflow_editor.py tests/integration/test_generation_workflow.py tests/unit/agent/test_source_answer_guard.py tests/unit/agent/test_source_answer_synthesis.py
# 59 passed

python -m pytest
# 640 passed, 7 skipped

python -m pytest -q output/parity95_round52_taskhub/tests
# 7 passed
```

실제 비교 결과:

- allCode source-flow smoke: body sample anchor와 repo-internal edge가 포함되지만,
  agy보다 fallback 문체가 강하고 함수 책임 연결 설명이 덜 자연스럽다.
- agy source-flow smoke: 별도 report artifact와 함수별 링크 중심 요약을 제공했다.
- allCode generation smoke: `./output/parity95_round52_taskhub` 생성 성공, direct pytest
  7 passed.
- agy generation smoke: `./output/parity95_round52_agy_taskhub` 생성 성공, reported pytest
  10 passed, 별도 report artifact 포함.

현재 판단:

- project generation/modification/validation은 94-95% 수준까지 상승했다.
- source exploration/project analysis는 91-92% 수준이다. 95% 도달을 위해서는 fallback
  의존도를 줄이고, 모델 최종 합성이 body anchor와 내부 edge를 자연어 함수 책임 흐름으로
  직접 엮도록 추가 보강이 필요하다.
