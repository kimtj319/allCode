# 59. Project Analysis Quality Parity Plan (Axis ③)

## 목적

대형 프로젝트 분석(③) 품질을 Codex/agy 수준(≥95%)으로 끌어올린다. 동일 프롬프트로
이 레포(allCode)를 분석시켰을 때 allCode의 출력이 Codex/agy 대비 심각하게 떨어지는
원인을 닫는다.

이번 계획은 **read-only 소스 분석 경로(inspect route)의 탐색 타겟팅과 최종 답변
합성**만 다룬다. generation/modify workflow, routing 기본 구조, tool policy, 모델
adapter, TUI 렌더링은 변경하지 않는다.

## 참조 계약 / 주의사항 (최우선 검토)

- `plan/00`: 특정 프롬프트/프로젝트명/파일명 하드코딩 금지. 파일 SRP·500줄·단방향
  의존성. agent loop는 UI 무지. core는 provider SDK 비결합.
- `AGENTS.md`: 변경 전 실제 코드 확인. 변경에는 테스트 추가. route 기반 tool 노출
  유지. read-only 분석을 특정 파일명/패키지명에 과하게 맞추지 말 것.
- `plan/01`: Aider식 repo map(symbol/signature 중심), 관찰 못 한 것 단정 금지.
- 기존 회귀(`python -m pytest` 772 passed) 유지. source-answer 관련 테스트
  (`tests/unit/agent/*source*`, `test_dependency_answer_guard.py` 등) 깨지 않기.

## Test 결과 (1차, 2026-06-13)

동일 프롬프트(`tmp_test_run/bench_analysis/prompt_t3a.txt`, 이 레포 아키텍처 분석,
코드 수정 금지)를 세 에이전트에 투입:

- allCode `--headless`: 결과 `tmp_test_run/bench_analysis/allcode_t3a.txt`
- codex `exec --sandbox read-only`: `codex_t3a.txt`
- agy `-p`: `agy_t3a.txt`

관찰:

- **codex**: main→Config→runtime→ContextBuilder→ModelRouter→route_validator→
  PromptBuilder→ToolSchemaFilter→RoundRunner→OpenAI client→ResponseParser→
  ToolCallProcessor→Executor→turn_completion→TurnResult 15단계 흐름 + 계층별 책임 +
  핵심 파일(라인 앵커) + 깔끔한 footer. 실제 `agent/`·`llm/`·`tools/` 코어를 읽음.
- **agy**: 8계층 아키텍처 표 + mermaid 시퀀스 다이어그램 + 핵심 4파일 설명.
- **allCode**: 노이즈 디렉터리(`.pytest_cache`, `.allCode/sessions/state/*.json`,
  `plan/*.md`, 최상위 `README.md`/`AGENTS.md`)와 `src/` 3개 파일만 봄.
  `coverage ratio 0.0129`(1.3%). `agent/` 코어 전체 누락. 그리고 내부 스캐폴딩
  ("답변 합성 outline:", "함수/모듈 책임 매트릭스:", "confidence=0.60",
  "backend regex", "anchors(...)")을 사용자 답변에 그대로 덤프.

## 근본 원인 (코드 확정)

1. **탐색 타겟팅·깊이 실패 (P0)**
   - 소스 탐색이 `src/` 패키지 루트를 우선하지 않고 노이즈 디렉터리
     (`.pytest_cache`, `.allCode`, session state JSON, build/cache, 문서 위주)를
     포함한다. 광역 아키텍처 분석에서 coverage 1.3%로 조기 종료.
   - 관련: `src/allCode/workspace/indexer.py`, `src/allCode/agent/inspect_targets.py`,
     source overview/probe 대상 선택부.

2. **결정론적 fallback이 내부 스캐폴딩을 답변으로 덤프 (P0, 가독성)**
   - `agent/round_text_response.py:144-182`: 모델 분석 답변이
     `source_answer_violation`(=`source_answer_guard`)에 걸리면 최대 2회 재시도 후
     `safe_source_analysis_answer(...)`(`source_answer_fallback.py`)를 success로 반환.
   - 이 fallback 렌더(`source_analysis_rendering.py`/`source_responsibility_graph.py`)
     는 "답변 합성 outline", "함수/모듈 책임 매트릭스", "confidence", "backend",
     "anchors", "책임 그래프 한계", 중복 "확인한 범위" 등 내부 브리프를 그대로 출력.

3. **모델 답변이 guard에 과도 거부 → fallback 강제 (P1)**
   - 얕은 탐색으로 근거(body-sample anchor 등)가 부족 → guard 통과 실패 → fallback.
   - 즉 ①이 ③을 유발하고 ②가 사용자에게 노출되는 복합 구조.

4. **문서/캐시 파일을 source module로 오분류 (P1)**
   - `plan`, `.pytest_cache`에 "public code surface / source module" 같은 역할 부여.

## 개선 방향 (원칙)

- 특정 레포 구조를 하드코딩하지 않는다. "노이즈/소스" 구분은 일반 규칙
  (VCS/cache/build/venv/세션상태/문서 vs 코드 확장자·패키지 루트)으로만 한다.
- fallback조차도 내부 스캐폴딩 헤더를 사용자에게 노출하지 않는다. 최종 답변은
  항상 합성된 서사(목적·계층 책임·실행 흐름·핵심 파일·한계)여야 한다.
- 변경을 agent 소스-분석 모듈과 workspace 인덱싱 noise 규칙으로 제한한다.

## Phase 1. 탐색 타겟팅/노이즈 제거 (P0)

수정 대상: `workspace/indexer.py`, `agent/inspect_targets.py`(+ source overview 대상 선택).

1. 디렉터리 워크에서 노이즈 경로를 일반 규칙으로 제외: `.git`, `.hg`, `.svn`,
   `.venv`/`venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`,
   `node_modules`, `dist`, `build`, `.idea`, `.vscode`, 그리고 본 에이전트의 런타임
   상태 디렉터리(세션 state/cache) — 이름 규칙으로만 식별(레포 비종속).
2. 광역 아키텍처 분석 의도에서는 `src/`(또는 최상위 패키지 루트) 코드 파일을
   우선 후보로 올리고, 문서(`.md`)·설정만으로 분석을 종료하지 않는다.
3. coverage가 과도하게 낮으면(예: 코드 파일 다수 미관찰) 대표 코드 파일 후보를
   추가 probe 대상으로 확장한다. 단 breadth는 plan/01 repo-map 원칙(시그니처 중심)
   안에서 제한한다.

## Phase 2. 최종 답변 합성 정리 — 스캐폴딩 누출 제거 (P0)

수정 대상: `agent/source_answer_fallback.py`, `agent/source_analysis_rendering.py`,
필요 시 `agent/source_responsibility_graph.py`.

1. `safe_source_analysis_answer` 및 그 렌더가 내부 브리프 헤더를 사용자 답변에
   출력하지 않도록 한다. 다음 항목만 사람이 읽는 서사로 합성한다:
   - 프로젝트 목적 / 계층(디렉터리·패키지)별 책임 / 요청→응답 실행 흐름 /
     핵심 파일·심볼 / 관찰 한계(마지막에 분리).
2. "confidence=", "backend ", "anchors(", "답변 합성 outline", "함수/모듈 책임
   매트릭스", "책임 그래프 한계", "coverage ratio" 등 진단/스캐폴딩 토큰은 최종
   답변 문자열에서 제거한다(내부 로깅·evidence로만 유지).
3. 중복 섹션("확인한 범위" 2회 등)을 제거한다.

## Phase 3. guard ↔ 합성 정합 (P1)

수정 대상: `agent/source_answer_guard.py`(필요 최소), `round_text_response.py`.

1. 충분한 탐색이 이뤄졌고 모델이 목적·계층·흐름·핵심 파일을 갖춘 서사를 냈다면
   과도하게 fallback으로 강등하지 않는다. guard는 "근거 없는 단정/환각" 차단에
   집중하고, 형식 미세 요건으로 양질의 서사를 버리지 않는다.
2. fallback이 불가피한 경우에도 Phase 2의 정리된 서사 형식을 사용한다.

## Phase 4. 회귀 테스트

수정 대상: `tests/unit/agent/`(소스 분석), 필요 시 신규 테스트 파일.

1. 분석 답변에 스캐폴딩 토큰("답변 합성 outline", "함수/모듈 책임 매트릭스",
   "confidence=", "backend ", "anchors(", "coverage ratio")이 포함되지 않는지.
2. 노이즈 디렉터리(`.pytest_cache`/`__pycache__`/`.git`/`.venv`)가 탐색 후보에서
   제외되는지.
3. 기존 source-answer 관련 테스트 유지.

## Phase 5. 검증 (Codex/agy 교차)

```bash
python -m pytest
.venv/bin/allcode --headless "$(cat tmp_test_run/bench_analysis/prompt_t3a.txt)"
```

관찰 기준: 노이즈 대신 `src/` 코어를 관찰하고, 최종 답변이 스캐폴딩 없이
목적·계층 책임·실행 흐름·핵심 파일·한계로 합성되며, codex/agy와 구조적으로
견줄 만한지. 이후 멀티턴 딥다이브(②축 연계) 후속 검증.

## 구현 결과 (2026-06-13, 1차)

- Phase 1: `workspace/indexer.py`에 보편 노이즈 디렉터리(`.git`/`.venv`/`__pycache__`/
  `.pytest_cache`/`.mypy_cache`/`node_modules`/build + 에이전트 런타임 `.allCode`)
  추가 제외. `CODE_EXTENSIONS` 신설. `tools/builtin/source_overview.py`의 선택
  로직을 코드 파일 우선 + 코드 밀집 상위 그룹 round-robin으로 변경(생성/문서 트리가
  핵심 소스를 희석하지 못하게). 152개 관련 테스트 통과.
- Phase 2: `agent/inspect_summary.py`의 `grounded_inspect_summary`가
  `render_source_analysis_brief`(모델 컨텍스트용 outline/책임 매트릭스/confidence
  스캐폴딩)를 사용자 답변에 덤프하던 것을 제거하고, 신설
  `render_source_flow_section`(핵심 실행 흐름 + 모듈 간 연결만)으로 교체.
- Phase 4: `test_grounded_inspect_summary_does_not_leak_model_scaffolding` 추가.
  전체 `python -m pytest` → 773 passed, 3 skipped.

검증(Phase 5, 실모델 재실행):

- **성공**: 최종 답변이 스캐폴딩 없는 깔끔한 서사(확인 범위 / 디렉터리·패키지 역할
  표 / 핵심 실행 흐름 / 모듈 간 연결 / 대표 파일 근거 / 한계 / 요약)로 합성됨.
  "답변 합성 outline", "함수/모듈 책임 매트릭스", "confidence=" 완전 제거.
- **남은 문제**: 이번 실행에서 모델이 `source_overview`(2회)를 호출했음에도
  `search_files`(11회)·`read_file`(8회)가 **설계 문서 `plan/30_*.md`** 와 `output/`
  테스트 파일에 latch해, `src/` 실제 코드를 분석하지 못함. 즉 도구 선택 개선은
  됐으나 모델 탐색이 코드가 아닌 설계 문서를 소스로 오인.

## Phase 6 (다음 이터레이션). 탐색이 설계 문서가 아닌 코드 우선

- inspect 라우트 discovery/preflight가 분석 대상을 실제 코드(`src/` 등 코드
  확장자)로 우선 고정하고, `plan/`·`docs/` 같은 설계/문서 디렉터리는 보조 근거로만
  취급하도록 유도(레포 비종속: 코드 확장자/문서 확장자 일반 규칙).
- search/read가 문서에서 함수 "정의"를 찾았을 때 그것을 실제 소스 정의로 오인하지
  않도록(문서 내 코드 블록 vs 실제 소스 파일 구분).
- 가능하면 inspect 첫 단계에서 코드 루트 source_overview를 자동 seed.

## 구현 결과 (2026-06-13, 2차 — Phase 6)

근본 원인 추가 확정: `agent/preflight.py`의 inspect 프리플라이트가 아키텍처/모듈/
책임 프롬프트에서 검색어 `"def "`로 `search_files`를 seed → `plan/*.md` 코드펜스와
`output/*.py`에 매칭되어 모델을 문서로 유도.

수정:

- `preflight.py`: `_is_architecture_overview()` 추가. 광역 아키텍처/구조/모듈/책임
  분석(명시 타겟 없음)에서는 `search_files` 대신 코드 우선 `source_overview`(path=".")를
  seed. (policy상 `search_workspace` 능력이면 source_overview 허용)
- `tools/builtin/source_overview.py`: `_gitignore_dirs()` 추가. overview 스캔이
  `.gitignore`의 단순 디렉터리(이 레포: `output/`,`review/`,`docs/`,`tests/`,`cache/`)를
  제외 — 전역 인덱서/컨텍스트/테스트 탐색에는 영향 없음. 아키텍처 분석이 tracked
  소스(`src/`)에 집중.
- 테스트: `test_preflight_seeds_source_overview_for_architecture_analysis`,
  `test_preflight_keeps_keyword_search_for_non_architecture_inspect` 추가;
  기존 `test_preflight_searches_before_workspace_inventory_answer`를 source_overview
  기대로 갱신. 전체 `python -m pytest` → 775 passed, 3 skipped.

검증(실모델 재실행, v4):

- ✅ 확인 범위가 `src/allCode/{agent,memory,tools,tui,core,generation,llm,workspace,
  config,telemetry}` 핵심 패키지 전체로 정확화(노이즈/문서/생성물 제거).
- ✅ 역할 표가 agy 수준으로 정확(각 패키지 책임 1줄, 8개 계층).
- ✅ 대표 파일이 실제 코어 소스(`agent/round_runner.py`, `llm/response_parser.py`,
  `core/events.py` 등) + 실제 import edge 표시.
- ✅ 스캐폴딩 누출 없음(Phase 2 유지).
- 남은 점: 여전히 결정론적 fallback(모델 답변이 source_answer_guard에 거부)이나,
  fallback 내용이 정확·구조적이라 실사용 품질은 codex/agy에 근접. Phase 3(guard가
  양질의 모델 prose를 과도 거부하지 않도록 정합)는 후속 선택 과제.

## 남은 리스크

- source-analysis 서브시스템(다수 파일)이 크다. 합성 정리 시 기존 evidence/guard
  계약을 깨지 않도록 내부 데이터는 유지하고 "표시 문자열"만 정리한다.
- 실제 모델 품질 의존: 탐색·근거가 좋아져도 최종 서사 품질은 모델에 좌우된다.
  deterministic fallback은 최저선 가독성을 보장하는 역할로 한정한다.
