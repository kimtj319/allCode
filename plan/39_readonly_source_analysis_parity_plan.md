# 39. Read-Only Source Analysis Parity Plan

## 목적

동일 프롬프트 비교에서 allCode는 `src/allCode/agent` 일부만 얕게 요약했고,
`src/allCode/tools` 책임과 `ToolCallProcessor -> ToolExecutor -> Approval ->
CompletionEvidence` 상호작용 흐름을 충분히 설명하지 못했다. agy는 두 패키지를 모두
탐색하고 파일/클래스/라인 근거와 실행 순서를 더 깊게 정리했다.

이 계획의 목표는 read-only source analysis에서 여러 명시 target이 있을 때 한쪽 패키지가
대표 읽기 예산을 독점하지 못하게 하고, 최종 답변이 관찰 범위와 미관찰 범위를 명확히
구분하도록 만드는 것이다.

## 기준 문서

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/07_workspace_context_plan.md`
6. `plan/08_context_memory_plan.md`
7. `plan/18_open_source_agent_hardening_plan.md`
8. 이 문서

충돌 시 `plan/00`~`12`와 `plan/01`을 우선한다.

## agy 검토 반영

agy에는 코드 수정 금지 조건으로 검토를 요청했다. agy의 진단은 다음과 같았다.

- `inspect_staging._representative_targets`가 `source_representative_candidates` 앞쪽 후보를
  그대로 선택해 한 패키지가 예산을 독점할 수 있다.
- `decide_inspect_stage`가 prompt에서 추출한 explicit target을 `_representative_targets`로
  전달하지 않아 사용자가 요청한 비교 대상이 후보 선택에 반영되지 않는다.
- targeted read prompt가 상호작용, delegation, caller-callee 흐름을 명시하지 않아 모델이
  파일 역할 나열에 머무를 수 있다.
- grounded fallback summary가 요청했지만 읽지 못한 target을 표시하지 않아 답변의 관찰 범위가
  불명확하다.

agy 초안 중 보정할 점:

- path segment 교집합만으로 candidate와 target을 매칭하면 `src/allCode/agent`와
  `src/allCode/tools`가 모두 `src`, `allCode`를 공유하므로 오분류된다.
- `inspect_summary.py`가 `inspect_staging.py`의 private helper를 import하면 모듈 경계가
  약해진다.

추가 재현 로그 검수 결과:

- 모델이 `source_overview(path=src/allCode/agent)`만 호출한 뒤, `src/allCode/tools`에 대한
  inventory가 없는 상태에서도 agent 후보만 probe하고 finalize하는 경로가 있었다.
- 따라서 representative candidate 균형만으로는 충분하지 않다. `source_overview` 호출의 실제
  target을 `CompletionEvidence`에 별도로 기록하고, 여러 명시 directory target 중 coverage가
  빠진 target은 대표 파일 probe보다 먼저 `source_overview`를 강제 노출해야 한다.

## 오픈소스 패턴 적용

- Aider repo map: full-file dump 대신 대표 파일과 symbol/signature 근거를 균형 있게 읽는다.
- OpenHands action/observation: 관찰한 파일과 관찰하지 못한 target을 final answer에 분리한다.
- Gemini compact context: 여러 target을 읽더라도 bounded source_probe 중심으로 context를 제한한다.
- Qwen provider-neutral loop: 모델/공급자 분기 없이 staging과 prompt만 provider-neutral하게 강화한다.

## 구현 계획

### Phase 1. Target Matching Helper 분리

생성 파일:

- `src/allCode/agent/inspect_targets.py`

작업:

- explicit target 추출, path normalization, target observed/match 판단을 공용 helper로 분리한다.
- target matching은 path containment 기준을 우선한다.
  - `path == target`
  - `path.startswith(target + "/")`
  - `target.startswith(path + "/")`
  - 단일 segment target일 때만 path segment exact match 허용
- segment 교집합만으로는 match하지 않는다.

### Phase 2. Balanced Representative Selection

수정 파일:

- `src/allCode/agent/inspect_staging.py`
- `src/allCode/core/result.py`
- `src/allCode/agent/tool_evidence.py`

작업:

- `source_overview`의 실제 target path를 `CompletionEvidence.source_overview_targets`에 기록한다.
- 명시 target 중 아직 overview/probe/read로 관찰되지 않은 target이 있으면 representative probe보다
  해당 target에 대한 `source_overview`를 우선 노출한다.
- `source_overview_paths`가 상위 package group으로 뭉쳐져도, 명시 target coverage 판단은 우선
  `source_overview_targets`를 기준으로 한다.
- `_representative_targets(evidence, explicit_targets)`가 explicit target별 bucket을 만들고
  round-robin으로 후보를 선택한다.
- explicit target에 매칭되지 않는 후보는 fallback bucket으로 두되, explicit target bucket을
  우선한다.
- explicit target이 없으면 parent package별 bucket으로 round-robin한다.
- finalization은 여러 directory target 중 일부만 관찰된 상태에서 조기 성공하지 않는다.

### Phase 3. Interaction-Focused Prompt

수정 파일:

- `src/allCode/agent/prompt_builder.py`

작업:

- targeted read 지시에 cross-module interaction, delegation sequence, instantiation flow,
  caller-callee 관계를 보라고 명시한다.
- read-only와 bounded source_probe 우선 원칙은 유지한다.

### Phase 4. Grounded Summary Scope Disclosure

수정 파일:

- `src/allCode/agent/inspect_summary.py`

작업:

- user prompt에서 추출한 explicit target 중 관찰되지 않은 target을 별도 섹션으로 표시한다.
- 한국어/영어 label을 모두 제공한다.
- 이 섹션은 실패 문구가 아니라 관찰 범위 disclosure로 취급한다.

### Phase 5. 검증과 동일 프롬프트 비교

집중 테스트:

```bash
python -m pytest tests/unit/agent/test_inspect_tool_staging.py tests/unit/agent/test_inspect_summary.py tests/integration/test_readonly_source_analysis.py
```

회귀 테스트:

```bash
python -m pytest tests/unit/agent tests/unit/tools tests/integration/test_readonly_source_analysis.py
```

동일 프롬프트 비교:

```bash
allcode --headless "현재 디렉터리의 src/allCode/agent와 src/allCode/tools가 각각 어떤 책임을 갖고 어떻게 상호작용하는지 코드 근거를 들어 정리해줘. 코드 수정은 엄격히 금지한다. 최종 답변은 한국어로 작성하라."
agy --print "현재 디렉터리의 src/allCode/agent와 src/allCode/tools가 각각 어떤 책임을 갖고 어떻게 상호작용하는지 코드 근거를 들어 정리해줘. 코드 수정은 엄격히 금지한다. 최종 답변은 한국어로 작성하라."
```

## 금지 사항

- 특정 프롬프트 문자열, 특정 benchmark path, 특정 모델명, 특정 scenario ID 하드코딩 금지.
- read-only route에서 mutation/shell/validation tool 노출 금지.
- full-file dump 강제 금지. 대표 파일은 bounded `source_probe` 우선.
- 500줄 초과 파일 생성 금지.
