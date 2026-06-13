# 44. 95 Percent Gap Closure Plan

## 목적

이 문서는 `plan/45_parity_progress_tracker.md`의 현재 기준선을 바탕으로 allCode를
agy/open-source CLI coding agent 대비 분야별 95%에 가깝게 끌어올리기 위한
반복 계획이다. `plan/00`부터 `plan/12`까지의 구현 계약을 대체하지 않으며,
충돌 시 `plan/01_open_source_alignment_contracts.md`와 기존 MVP 계약을
우선한다.

## 현재 부족 핵심

1. 최종 답변 합성 품질
2. 복잡한 프로젝트 생성/수정/검증 수렴성
3. 멀티턴 기억과 이전 실패 맥락 유지

## 오픈소스 참조

- Aider repo map은 전체 파일 dump 대신 핵심 class/function signature와
  dependency graph ranking을 token budget 안에서 제공한다.
- Aider architect/editor 및 edit format은 문제 해결과 실제 파일 편집을
  분리하고, full-file rewrite보다 search/replace 또는 diff 기반 수정을
  선호한다.
- Gemini CLI는 `GEMINI.md` 계층형 context와 `/memory` 명령으로 장기 지시와
  프로젝트 맥락을 명시적으로 유지한다.
- OpenHands는 event history, action, observation, condenser, security
  validation을 중심으로 루프를 구성한다.
- Qwen Code는 terminal-first, provider-neutral 실행을 기본 원칙으로 둔다.

## agy 검토 반영

각 phase는 `agy --print` read-only 검토를 거쳤으며, 아래 피드백만 반영한다.

### Phase A. 최종 답변 합성

- `source_answer_guard.py`의 grounding parser는 citation 형식 다양성에 민감할
  수 있으므로, 첫 번째 재시도에서는 anchor를 더 명확히 지시하고 fallback은
  두 번째 실패 이후의 안전망으로 유지한다.
- structured answer outline은 JSON schema를 강제하기보다, evidence brief 안에
  관찰 가능한 섹션 계획으로 넣는 편이 provider 호환성이 높다.
- retry/fallback 증가는 latency를 늘릴 수 있으므로 retry budget은 현행 1회
  기준을 유지한다.

### Phase B. 생성/검증/수리

- `ModelWorkflowEditor`가 파일별 생성/수리 시 compact `TaskLoopDigest`를
  받지 않아 context blindness가 생길 수 있다.
- validation repair loop와 completion repair loop는 독립적으로 반복되어,
  completion repair가 다시 validation을 깨뜨리는 경우 수렴성이 약하다.
- failure signature는 raw log hash보다 file + exception + line excerpt 기반의
  normalized signature가 더 안정적이다.

### Phase C. 멀티턴 memory/failure context

- 현재 `AgentSessionState`는 process-local이므로 headless 재실행 사이에는
  obligation/recovery 맥락이 사라진다.
- source exploration ledger는 경로를 무제한 넣지 말고 directory/package 단위로
  압축해야 한다.
- stale repair target은 사용자 외부 수정 이후 반복 수리로 이어질 수 있으므로,
  나중에 file hash 또는 validation freshness와 결합해야 한다.

## Phase A. Final Answer Synthesis 95%

대상:

- `src/allCode/agent/source_analysis_rendering.py`
- `src/allCode/agent/final_answer_context.py`
- `src/allCode/agent/source_answer_guard.py`
- `src/allCode/agent/source_answer_fallback.py`

작업:

1. evidence brief에 관찰 범위, 역할, 대표 파일, 연결, 한계를 최종 답변
   outline으로 재배열한 `Answer synthesis outline`을 추가한다.
2. final synthesis system guard는 outline을 우선 따르되, 사용자가 지정한 형식과
   분량 제약을 더 높은 우선순위로 둔다.
3. fallback은 정확성 안전망으로 유지하되, 직접 모델 답변을 먼저 통과시키기
   위해 evidence-to-answer 지시를 더 구체화한다.
4. 특정 프롬프트, 경로, scenario ID를 검사하지 않는다.

검증:

```bash
python -m pytest tests/unit/agent/test_final_answer_context.py \
  tests/unit/agent/test_source_answer_synthesis.py \
  tests/unit/agent/test_source_answer_guard.py \
  tests/unit/agent/test_source_answer_fallback.py \
  tests/integration/test_readonly_source_analysis.py
```

## Phase B. Generation Convergence 95%

대상:

- `src/allCode/agent/workflow.py`
- `src/allCode/agent/workflow_editor.py`
- `src/allCode/agent/workflow_repair.py`
- `src/allCode/agent/task_loop_digest.py`

작업:

1. implementation/test file generation model calls에 현재 phase의
   `TaskLoopDigest`를 넣는다.
2. repair model call에는 최신 validation/completion failure와 remaining
   obligations가 반영된 digest를 넣는다.
3. repair loop의 반복 차단은 raw hash뿐 아니라 normalized failure signature로
   확장한다.
4. editor는 기존처럼 실제 mutation을 하지 않고 raw content/diff 후보만
   반환한다. 파일 쓰기는 계속 `WorkflowActions`/tool executor가 담당한다.

검증:

```bash
python -m pytest tests/unit/agent/test_workflow_editor.py \
  tests/unit/agent/test_project_planner.py \
  tests/integration/test_generation_workflow.py \
  tests/unit/agent/test_validation_repair.py
```

## Phase C. Multiturn Memory 95%

대상:

- `src/allCode/agent/session_state.py`
- `src/allCode/agent/context.py`
- `src/allCode/memory/project_obligations.py`
- `src/allCode/agent/context_condensation.py`

작업:

1. `CompletionEvidence`의 source overview/probe/read 결과를
   `SourceExplorationLedger`로 압축해 session state에 보존한다.
2. context builder는 repair context, active obligations 다음에 source
   exploration ledger를 낮은 비용 section으로 주입한다.
3. ledger는 대표 파일, 관찰 범위, 미관찰 후보를 각각 제한된 개수만 유지한다.
4. process 재시작 persistence는 다음 반복에서 `SessionStore` schema 확장으로
   처리한다. 이번 반복에서는 in-session follow-up 품질을 먼저 고정한다.

검증:

```bash
python -m pytest tests/unit/agent/test_session_state.py \
  tests/unit/agent/test_context_builder.py \
  tests/unit/memory/test_project_obligations.py \
  tests/integration/test_followup_context_memory.py
```

## 반복 평가와 문서 갱신

각 phase 구현 후 아래를 수행한다.

1. 관련 targeted tests 실행.
2. `python -m pytest` 회귀 실행.
3. 400줄 이상 Python 파일 스캔.
4. 특정 프롬프트/시나리오 하드코딩 스캔.
5. 실모델 smoke 또는 allCode/agy 동일 프롬프트 비교.
6. 결과에 따라 `plan/45_parity_progress_tracker.md`의 percentage와 근거를 갱신한다.

95% 도달 조건은 `plan/45_parity_progress_tracker.md`의 update rules를 따른다.

## 2026-06-08 1차 구현 결과

Phase A:

- `source_analysis_rendering.py`가 evidence brief에 `Answer synthesis outline`
  / `답변 합성 outline`을 포함한다.
- `final_answer_context.py`가 source-analysis final synthesis에서 outline을
  답변 계획으로 사용하도록 지시한다.
- 실제 source-analysis smoke에서 fallback이 아니라 직접 모델 답변이 생성됐고,
  확인 범위, 역할, 흐름, 대표 파일 근거, 남은 한계가 분리됐다.

Phase B:

- `ModelWorkflowEditor.generate_file()`과 `repair_files()`가 optional
  `task_digest`를 받는다.
- `workflow.py`는 implementation/tests 단계 digest를 editor 호출에 전달한다.
- `workflow_repair.py`는 validation/completion repair 호출에 최신
  `TaskLoopDigest`를 전달한다.
- 생성 smoke에서 테스트 파일 생성이 related-test discovery evidence로 인정되지
  않아 validation gate가 막히는 문제가 발견됐다.
- `related_tests.py`와 `tool_evidence.py`를 보강해 성공한 `write_file`/`patch_file`
  이 만든 테스트 파일을 related-test candidate로 기록한다.

Phase C:

- `SourceExplorationLedger`를 추가해 source overview/probe/read 결과를
  session state에 압축 저장한다.
- `ContextBuilder`는 repair context, active obligations 다음에
  `source_exploration_ledger` section을 주입한다.

추가 수정:

- `artifact_detection.py`에 generic document request detector를 추가했다.
- `phase_gate_artifacts.py`가 README/docs/문서/사용법 요청을 `document`
  artifact obligation으로 seed한다.
- 실제 generation smoke에서 `README.md` 누락이 발견됐고, 보강 후
  `./output/parity_digest_demo3` 생성은 `cli.py`, `tests/test_cli.py`,
  `README.md`를 만들고 validation passed로 종료했다.

검증:

```bash
python -m pytest tests/unit/agent/test_final_answer_context.py \
  tests/unit/agent/test_source_answer_synthesis.py \
  tests/unit/agent/test_source_answer_guard.py \
  tests/unit/agent/test_source_answer_fallback.py \
  tests/integration/test_readonly_source_analysis.py \
  tests/unit/agent/test_workflow_editor.py \
  tests/unit/agent/test_project_planner.py \
  tests/integration/test_generation_workflow.py \
  tests/unit/agent/test_validation_repair.py \
  tests/unit/agent/test_session_state.py \
  tests/unit/agent/test_context_builder.py \
  tests/unit/memory/test_project_obligations.py \
  tests/integration/test_followup_context_memory.py
# 80 passed

python -m pytest tests/unit/agent/test_tool_evidence.py \
  tests/unit/agent/test_phase_gate.py \
  tests/integration/test_generation_workflow.py \
  tests/unit/agent/test_workflow_editor.py
# 57 passed

python -m pytest
# 604 passed, 7 skipped
```

현재 남은 95% 미달 항목:

- Final synthesis: 다양한 대형 repo prompt에서 direct answer가 fallback 없이 유지되는지 추가 비교 필요.
- Generation: validation repair와 completion repair를 하나의 convergence state machine으로 합치는 작업이 남음.
- Memory: `AgentSessionState`의 process restart persistence와 stale repair target freshness check가 남음.
