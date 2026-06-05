# 36. agy Parity Agent Hardening Plan

## 목적

이 문서는 `allcode`가 agy와 비슷한 수준의 코드 탐색, 코드 수정, 신규 구현 작업을
수행하도록 보강하기 위한 실행 계획이다. 범위는 기존 MVP agent loop를 강화하는 것으로
한정한다. git auto-commit, plugin marketplace, MCP server manager, multi-agent swarm,
cloud sandbox, full PageRank, full LSP lifecycle은 도입하지 않는다.

## 기준 문서

구현 전 아래 문서를 다시 확인한다.

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/05_routing_policy_plan.md`
6. `plan/06_tool_system_plan.md`
7. `plan/07_workspace_context_plan.md`
8. `plan/08_context_memory_plan.md`
9. `plan/09_generation_workflow_plan.md`
10. `plan/21_open_source_parity_95_hardening_plan.md`
11. `plan/27_validation_repair_convergence_plan.md`
12. `plan/35_deep_file_exploration_hardening_plan.md`
13. 이 문서

충돌 시 `plan/00`~`12`와 `plan/01`을 우선한다.

## 오픈소스 참조와 allCode 적용 방식

### Aider

참조:

- https://aider.chat/docs/repomap.html

Aider는 전체 repo map을 graph ranking으로 압축하고, edit 후 test/fix 흐름을 반복해
작업을 수렴시킨다.

allCode 적용:

- `source_overview`는 패키지별 대표 파일을 최소 1개씩 확보한다.
- broad source 분석에서는 단순 상위 점수 4개가 아니라 package coverage를 기준으로
  adaptive probe budget을 사용한다.
- 수정/구현 요청에서는 변경 파일과 validation evidence가 없으면 success를 금지하는
  기존 CompletionEvidence gate를 유지한다.

### Sourcegraph/Cody

참조:

- https://sourcegraph.com/docs/cody/core-concepts/context

Cody는 files, symbols, keyword search, code graph를 조합해 context를 만든다.

allCode 적용:

- `workspace/source_intelligence/graph.py`의 1~2 hop graph 후보를 유지한다.
- `source_probe` observation에 line range, symbol, import/reference edge를 남긴다.
- answer synthesis는 package role과 probe evidence를 함께 렌더링한다.

### Gemini CLI

참조:

- https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md

Gemini CLI는 계층 context를 매 prompt에 병합한다.

allCode 적용:

- raw code를 memory에 저장하지 않는다.
- source 분석 결과는 session-local compact observation만 후속 질문에 사용한다.
- 수정/구현 시에도 기존 `ALLCODE.md`, session summary, recent targets 흐름을 유지한다.

### OpenHands

참조:

- https://docs.openhands.dev/sdk/arch/agent
- https://docs.openhands.dev/sdk/arch/tool-system

OpenHands는 event-driven reasoning-action loop와 Action -> Observation tool contract를
중심으로 한다.

allCode 적용:

- `ToolResult.metadata["observation"]`를 source_probe, source_overview, mutation,
  validation 모두의 표준 관찰 계층으로 유지한다.
- TUI/telemetry는 raw tool output이 아니라 normalized observation을 표시한다.
- read-only route에서는 mutation/shell/validation/approval tool 노출을 금지한다.

## agy 토론 반영 요약

agy에는 코드 수정, 파일 생성/삭제, 커밋을 금지하고 계획 검토만 요청했다. 피드백의
핵심은 다음과 같다.

1. 가장 높은 ROI는 multi-round staging budget, AST/graph centrality,
   grounded fallback summary, bounded `source_probe`다.
2. 수정 작업 parity는 `EditTransaction` evidence와 validation/self-repair gate가
   중심이어야 한다.
3. 신규 구현 parity는 Skeleton -> Contract -> Implementation -> Validation 흐름과
   AST signature 기반 완료 확인을 강화해야 한다.
4. LSP full integration, embedding/vector DB, read-only shell grep은 현재 allCode에는
   과하거나 위험하므로 제외 또는 optional로 둔다.

## 현재 격차

### 1. 코드 탐색

현재 최신 실모델 로그에서 `allcode`는 `source_overview` 후 `source_probe`만 사용하도록
수렴했다. 하지만 agy와 비교하면 다음 격차가 남아 있다.

- 전체 파일별 상세 보고서 수준이 아니라 대표 파일 중심 요약이다.
- `source_representative_candidates`가 최대 8개 수준이라 패키지 수가 많으면 일부
  패키지가 누락된다.
- `inspect_staging`의 required representative observation이 broad/truncated에서도
  최대 4개에 가까워 package coverage가 낮다.
- `source_overview`가 모델이 요청한 `max_files=20`을 그대로 받아, 큰 repo에서 overview
  입력 표본이 지나치게 작아질 수 있다.

### 2. 코드 수정

현재 강점:

- mutation은 tool executor와 EditTransaction을 통과한다.
- validation required 요청은 validation evidence 없이 success가 되지 않는다.
- validation repair target과 patch ambiguity guard가 있다.

남은 격차:

- 변경한 symbol을 사용하는 관련 테스트 파일을 더 적극적으로 찾는 흐름이 약하다.
- patch 후 "변경된 symbol이 실제로 요구사항을 만족하는지"에 대한 AST-level evidence가
  부족하다.

### 3. 신규 구현

현재 강점:

- generation workflow와 language strategy가 있다.
- skeleton-first 흐름과 validation/self-repair가 있다.

남은 격차:

- 구현 계약의 symbol/API obligations가 AST signature로 검증되는 정도가 약하다.
- 여러 파일/모듈이 필요한 구현에서 artifact checklist와 context handoff가 모델 품질에
  일부 의존한다.

## 구현 Phase

### Phase 0. 테스트 고정

- broad source overview가 패키지별 representative candidate를 충분히 반환하는 테스트.
- broad/truncated source 분석에서 required representative count가 package coverage를
  반영하는 테스트.
- source_probe가 package role summary에 들어가는 테스트.
- read-only route에 mutation/shell/validation/approval tool이 노출되지 않는 테스트 유지.

### Phase 1. Package Coverage Source Exploration

수정 파일:

- `src/allCode/tools/builtin/source_ranking.py`
- `src/allCode/tools/builtin/source_overview.py`
- `src/allCode/agent/inspect_staging.py`

작업:

- `representative_reads_with_metadata(..., limit=...)` 호출 시 group count 기반 limit을
  넘겨 최소한 package group별 대표 파일 후보가 생성되게 한다.
- `source_overview` metadata에 `package_representative_reads`를 추가한다.
- `inspect_staging._required_representative_read_count()`를 broad/truncated에서 최대 6개,
  큰 package_count에서는 최대 8개까지 늘리되, candidate count와 inspect budget을 넘지
  않도록 한다.
- 한 round target은 최대 3개로 유지한다.

완료 기준:

- 실제 `allcode` source 분석 prompt에서 5개 이상 package의 `source_probe`가 실행된다.
- final answer가 최소 8개 이상의 주요 package role을 설명한다.

### Phase 2. Source Answer Coverage Synthesis

수정 파일:

- `src/allCode/agent/source_answer_synthesis.py`
- `src/allCode/agent/inspect_summary.py`

작업:

- `source_probe` observation과 `package_roles`를 합쳐 "관찰 근거"와 "추론한 패키지 역할"을
  분리한다.
- probe되지 않은 package는 "overview 기반 추론"으로 표시한다.
- 모델 답변이 얕을 경우 fallback이 package coverage table을 만든다.

### Phase 3. Modification Related-Test Discovery

수정 파일:

- `src/allCode/agent/phase_gate.py`
- `src/allCode/agent/validation_controller.py`
- `src/allCode/agent/prompt_builder.py`

작업:

- 변경된 source path와 public symbol을 evidence에서 읽어 관련 test candidate를
  `search_files`/`source_overview(focus=tests)`로 찾도록 phase hint를 강화한다.
- validation이 필요한 수정 요청은 related test discovery 또는 explicit validation command
  없이 final success로 가지 않게 한다.

이번 반복에서는 Phase 1~2까지만 구현한다. Phase 3은 수정/구현 실모델 회귀에서 격차가
반복될 때 이어서 처리한다.

### Phase 4. Generation API Obligation Check

수정 파일:

- `src/allCode/agent/completion_checker.py`
- `src/allCode/agent/workflow.py`
- `src/allCode/generation/*`

작업:

- requested artifacts와 public API expectation을 AST signature로 확인한다.
- 신규 구현은 skeleton -> contract -> implementation -> tests -> validation 순서를
  event로 관찰 가능하게 유지한다.

이번 반복에서는 계획만 남긴다.

## 금지 사항

- 특정 prompt, scenario ID, 프로젝트명, 절대 경로를 source에 하드코딩하지 않는다.
- full-file dump를 만들지 않는다.
- read-only route에서 mutation, shell, validation, approval schema를 열지 않는다.
- 새 core field를 tool-specific하게 계속 늘리지 않는다.
- 신규/수정 파일은 500줄을 넘기지 않는다.

## 검증 계획

Unit/integration:

```bash
python -m pytest tests/unit/agent tests/unit/tools tests/unit/workspace tests/integration/test_readonly_source_analysis.py
```

실모델 비교:

```bash
allcode --headless "현재 디렉터리의 src 내의 코드들이 각각 어떤 역할을 하는지 분석해서 요약해줘. 코드 수정, 파일 생성/삭제/포맷팅, 커밋은 금지한다."
agy --print "현재 디렉터리의 src 내의 코드들이 각각 어떤 역할을 하는지 분석해서 요약해줘. 코드 수정, 파일 생성/삭제/포맷팅, 커밋은 금지한다."
```

평가 기준:

- allcode가 `source_overview` 후 `source_probe` 중심으로 수렴하는가.
- 최소 5개 이상의 package 대표 파일을 관찰하는가.
- 최종 답변이 한국어를 유지하는가.
- `agent`, `tools`, `workspace`, `llm`, `memory`, `config`, `core`, `tui` 등 핵심 package
  역할이 빠지지 않는가.
- mutation/shell/validation/approval tool이 read-only route에서 사용되지 않는가.

## 반복 종료 기준

동일 read-only source 분석 prompt에서 다음 조건을 만족하면 이번 반복은 종료한다.

- allcode의 답변이 agy처럼 전체 패키지 역할을 포괄적으로 설명한다.
- 실제 tool log에서 `source_probe`가 여러 package에 대해 실행된다.
- 답변이 한국어이고, 관찰 근거와 추론한 역할이 분리된다.
- unit/integration 회귀 테스트가 통과한다.

