# 35. Deep File Exploration Hardening Plan

## 목적

이 문서는 `plan/33_source_analysis_depth_hardening_plan.md`와
`plan/34_ast_lsp_source_intelligence_plan.md` 이후에도 남은 심층 파일 탐색 깊이
문제를 해결하기 위한 보강 계획이다.

목표는 `allcode`가 read-only 소스 분석 요청에서 다음 수준까지 안정적으로 도달하게
하는 것이다.

- 전체 파일 본문을 덤프하지 않고도 넓은 repo의 핵심 흐름을 파악한다.
- `source_overview` 1회와 대표 파일 1개 읽기에서 조기 종료하지 않는다.
- AST/Tree-sitter/LSP에서 얻은 symbol, import, reference 정보를 파일 탐색 순서에
  직접 반영한다.
- 모델이 빈 답변이나 얕은 답변을 반환해도 tool observation 기반의 구조화된
  fallback 답변을 만들 수 있다.
- read-only 분석에서는 mutation, shell, validation, approval schema가 열리지
  않는다.

이 계획은 새로운 제품 범위를 추가하지 않는다. 기존 source analysis workflow의
탐색 깊이와 근거 품질만 고도화한다.

## 우선 참조 문서

구현 전 아래 문서를 순서대로 다시 읽는다.

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/07_workspace_context_plan.md`
6. `plan/08_context_memory_plan.md`
7. `plan/30_source_analysis_language_tooling_hardening_plan.md`
8. `plan/31_terminal_paste_tool_visibility_source_analysis_plan.md`
9. `plan/32_readonly_constraint_routing_repair_plan.md`
10. `plan/33_source_analysis_depth_hardening_plan.md`
11. `plan/34_ast_lsp_source_intelligence_plan.md`
12. 이 문서

충돌 시 `plan/00`~`plan/12`와 `plan/01`을 우선한다.

## 오픈소스 참고 결과와 적용 범위

### Aider repo map

참조:

- https://aider.chat/docs/repomap.html
- https://aider.chat/docs/languages.html

Aider는 repo 전체를 짧은 map으로 만들고, 중요한 class/function signature와
dependency graph ranking을 token budget 안에서 선택한다. Tree-sitter tags 기반의
다국어 repo map도 사용한다.

allCode 적용:

- 이미 있는 `RepoMapBuilder`, `source_overview`, `source_ranking.py`를 유지하되,
  file graph와 symbol slice를 새 모듈로 분리해 대표 파일 선정 정확도를 높인다.
- full PageRank 복제는 하지 않는다. import/reference/call edge의 1~2 hop
  lightweight ranking만 적용한다.
- map 결과는 final answer 본문에 그대로 붙이지 않고 `ToolResult.metadata`와
  `CompletionEvidence`에 구조화해서 저장한다.

### Sourcegraph Cody context/code navigation

참조:

- https://sourcegraph.com/docs/cody/core-concepts/context
- https://sourcegraph.com/docs/code-navigation

Cody/Sourcegraph는 files, symbols, search, code graph를 조합해 codebase-aware
context를 만든다. Sourcegraph code navigation도 definition, references,
implementation 같은 관계 탐색을 핵심 기능으로 둔다.

allCode 적용:

- 외부 Sourcegraph backend, vector database, embedding index는 도입하지 않는다.
- 로컬 `WorkspaceIndex`, `RepoMapEntry`, `SourceFileAnalysis`만 사용해 파일 graph와
  symbol mention 후보를 만든다.
- 특정 symbol/path가 사용자 prompt에 있으면 text search 반복보다 symbol index와
  `source_probe`가 먼저 좁은 slice를 반환하게 한다.

### Gemini CLI hierarchical context

참조:

- https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html

Gemini CLI는 user, project, sub-directory 단위 context file을 계층적으로 읽고
`/memory` 명령으로 관리한다.

allCode 적용:

- source 분석 중 얻은 결과를 durable memory에 raw body로 저장하지 않는다.
- session 범위의 `Active Source Exploration` 요약만 유지한다.
- 다음 턴 후속 질문에서 "그 파일", "해당 함수"를 해석할 때 source probe 결과와
  recent target을 연결한다.

### OpenHands action/observation

참조:

- https://docs.openhands.dev/sdk/arch/tool-system
- https://docs.openhands.dev/sdk/arch/agent

OpenHands는 tool을 Action -> Observation 계약으로 구조화하고 agent loop는 이벤트
기반으로 observation을 축적한다.

allCode 적용:

- 새 탐색 tool도 `ToolResult.metadata["observation"]`에 `kind`, `target`,
  `observed_symbols`, `line_ranges`, `edges`, `truncated`를 표준화해 넣는다.
- TUI/terminal에는 내부 score가 아니라 짧은 상태만 보여준다.
- final answer는 raw tool output이 아니라 observation evidence로 합성한다.

### Tree-sitter와 LSP

참조:

- https://tree-sitter.github.io/tree-sitter/using-parsers/2-basic-parsing.html
- https://microsoft.github.io/language-server-protocol/specifications/lsp/3.18/specification/

Tree-sitter는 syntax node와 byte/line range를 안정적으로 제공한다. LSP는 definition,
references, workspace symbols, diagnostics, call hierarchy 등 더 깊은 semantic
정보를 제공한다.

allCode 적용:

- Python은 현재 `python_ast.py`가 이미 있으므로 우선 이를 file graph와 source slice에
  연결한다.
- Tree-sitter는 설치되어 있을 때만 optional parser로 사용한다.
- LSP는 설치 가능성과 timeout 문제가 있으므로 optional enrichment로 제한한다.
  기본 실행 조건이 되면 안 된다.
- LSP의 write 성격 기능(code action, rename, formatting, workspace edit)은
  source analysis 경로에서 사용하지 않는다.

## agy 토론/검토 반영 요약

agy에는 코드 수정, 파일 생성, 파일 삭제, 커밋을 금지하고 현재 코드 기준의 심층 탐색
계획 검토만 요청했다. 검토 결과는 다음 방향을 지지했다.

1. Aider식 repo map과 token-budgeted representative read는 현재 구조에 가장 잘 맞는다.
2. Sourcegraph/Cody식 context retrieval은 외부 backend가 아니라 로컬 symbol index와
   file graph 수준으로만 가져와야 한다.
3. OpenHands식 action/observation은 `ToolResult.metadata`와 `CompletionEvidence`
   강화를 통해 적용한다.
4. 성능 향상이 확실한 항목은 다음 셋이다.
   - `inspect_staging.py`의 다단계 순차 탐색 보장
   - AST parser 결과를 ranking과 fallback summary가 공유하게 만드는 것
   - `inspect_summary.py`가 read/probe observation을 구조화해 답변 깊이를 보장하는 것
5. LSP full integration, embedding/vector search, 전역 PageRank는 비용과 설치 리스크가
   커서 이번 계획에서는 제외하거나 optional로 둔다.

agy가 보고한 현재 통과 범위는 `tests/unit/workspace`, `tests/unit/memory`,
`tests/unit/agent tests/unit/tools`이다. 이 계획의 구현 후에는 같은 범위에 더해
source probe와 read-only integration 테스트를 추가해야 한다.

## 현재 코드 기준 문제 지점

### 1. `source_overview.py`가 이미 비대화 경계에 가까움

파일:

```text
src/allCode/tools/builtin/source_overview.py
```

현재 463줄이다. 여기에 graph ranking, slice planning, package role synthesis를 더
넣으면 500줄 제한을 넘는다.

필요한 변화:

- `source_overview.py`는 tool entry와 response assembly만 유지한다.
- graph plan, group role inference, coverage calculation, render helper는 단계적으로
  새 모듈로 분리한다.
- 신규 기능은 이 파일에 직접 누적하지 않는다.

### 2. 대표 파일 선정이 graph walk가 아니라 list selection에 가깝다

파일:

```text
src/allCode/tools/builtin/source_ranking.py
src/allCode/tools/builtin/source_overview.py
```

현재 ranking은 public definition, imports, approximate fan-in, entrypoint naming
중심이다. `SourceReference(kind="call"|"inheritance"|"import")` 정보가 있어도
파일 간 1~2 hop 탐색 계획으로 전환되지 않는다.

필요한 변화:

- `workspace/source_intelligence/graph.py`를 추가해 파일별 node/edge를 만든다.
- edge 유형은 `import`, `from_import`, `call_hint`, `inheritance`, `test_to_source`로
  제한한다.
- import module -> workspace path resolve는 best-effort로만 수행한다.
- ranking은 다음 순서로 계산한다.
  1. explicit path/symbol target
  2. entrypoint/public API surface
  3. incoming references/fan-in
  4. outgoing imports/fan-out
  5. test/source pairing
  6. generated/private/large-file penalty

### 3. 정밀 파일 읽기 tool이 `read_file` 하나에 의존한다

파일:

```text
src/allCode/tools/builtin/file_ops.py
src/allCode/tools/builtin/source_overview.py
src/allCode/agent/inspect_staging.py
```

`read_file`은 range-first 제약이 있지만, 모델이 어떤 symbol 주변을 읽어야 하는지
판단하기 어렵다. 넓은 분석 요청에서는 전체 파일 대신 symbol/function/class 주변
slice가 필요하다.

필요한 변화:

- 새 read-only tool `source_probe`를 추가한다.
- 입력:
  - `path: string`
  - `symbols: list[string] | []`
  - `max_ranges: int`
  - `context_lines: int`
  - `include_imports: bool`
  - `include_edges: bool`
- 출력:
  - 파일 본문 전체가 아니라 import block, class/function signature, 요청 symbol 주변
    bounded slice만 반환한다.
  - metadata에는 `observed_symbols`, `line_ranges`, `outgoing_edges`,
    `incoming_hints`, `truncated`, `backend`을 넣는다.
- 구현 위치:
  - `src/allCode/tools/builtin/source_probe.py`
  - `src/allCode/tools/builtin/source_probe_render.py`가 300줄을 넘기면 분리
  - registry 등록은 기존 builtin registry 패턴을 따른다.

### 4. inspect stage가 "탐색 계획"을 유지하지 않는다

파일:

```text
src/allCode/agent/inspect_staging.py
src/allCode/agent/tool_evidence.py
src/allCode/core/result.py
```

현재는 `source_representative_candidates`, `representative_read_paths` 중심이다.
어떤 package에서 어떤 이유로 다음 파일을 볼지, 이미 어떤 slice를 봤는지에 대한
ledger가 약하다.

필요한 변화:

- `CompletionEvidence`에 새 tool-specific field를 계속 늘리지 않는다.
- `source_probe` 결과는 표준 `ToolResult.metadata["observation"]`에 compact하게 보존한다.
- `tool_evidence.py`는 기존 `inspected_paths`, `representative_read_paths`,
  `inspect_observation_count`와 source overview field만 최소 갱신한다.
- probe별 상세 ledger는 core가 아니라 agent-local helper가 최근 tool result metadata에서
  계산한다.
- `inspect_staging.py`는 기존 evidence와 agent-local exploration summary를 기준으로
  다음 단계 target을 결정한다.
- `prompt_builder.py`는 targeted read/probe 단계에서 다음 미관찰 candidate와 이유를
  짧게 제시한다.

### 5. final summary가 모델 품질에 너무 의존한다

파일:

```text
src/allCode/agent/inspect_summary.py
src/allCode/agent/final_reporter.py
```

모델이 reasoning-only나 얕은 답변을 반환하면 현재 fallback은 overview metadata와
일부 read_file summary에 기대어 답한다. probe observation을 더 많이 쌓더라도 final
summary가 이를 읽지 않으면 깊이 개선이 체감되지 않는다.

필요한 변화:

- `inspect_summary.py`에 `source_probe` observation renderer를 추가한다.
- 답변 섹션은 사용자 언어를 따르되 identifier는 번역하지 않는다.
- 넓은 분석 요청의 fallback 답변에는 반드시 다음을 포함한다.
  - 확인한 범위
  - package/module 역할
  - 핵심 파일 근거
  - 주요 class/function/signature
  - import/reference 연결
  - 관찰한 사실과 추론한 내용을 분리한 한계

## 적용 확실 항목과 제외 항목

### 확실하게 적용할 항목

1. **source graph builder**
   - 위치: `src/allCode/workspace/source_intelligence/graph.py`
   - 이유: 현재 `SourceFileAnalysis`에 이미 symbols/imports/references가 있으므로 새
     외부 의존 없이 탐색 우선순위를 개선할 수 있다.

2. **bounded source probe tool**
   - 위치: `src/allCode/tools/builtin/source_probe.py`
   - 이유: full-file dump 없이 symbol 주변 증거를 늘릴 수 있다.

3. **adaptive exploration budget**
   - 위치: `src/allCode/agent/source_exploration.py`,
     `src/allCode/agent/inspect_staging.py`
   - 이유: 현재 max 4 representative read는 넓은 repo에서 얕고, 무제한 증가도 위험하다.
     package_count, truncation, candidate_count, observed_count로 4~10 사이의 bounded
     budget을 계산한다.

4. **source observation ledger**
   - 위치: `src/allCode/core/result.py`, `src/allCode/agent/tool_evidence.py`
   - 이유: 다음 라운드와 다음 턴에서 이미 관찰한 파일/symbol을 재사용해야 한다.

5. **grounded fallback summary 강화**
   - 위치: `src/allCode/agent/inspect_summary.py`
   - 이유: 모델 답변 품질이 낮아도 관찰 근거 기반 최종 답변 품질을 하한선 이상으로
     유지한다.

### 제한적으로만 적용할 항목

1. **Tree-sitter**
   - optional parser로만 둔다.
   - 설치 실패가 전체 CLI 실패가 되면 안 된다.

2. **LSP**
   - `documentSymbol`, `definition`, `references`, diagnostics 정도만 mock-first로 설계한다.
   - 실제 language server process 실행은 timeout, cache, disable switch가 준비된 뒤에만
     추가한다.

### 제외할 항목

1. embedding/vector database
   - 현재 프로젝트의 경량 CLI 목표와 설치 제약에 맞지 않는다.

2. full PageRank/SCIP backend
   - 효과는 있지만 구현/운영 비용이 크다. MVP 후속 과제로 둔다.

3. shell 기반 deep grep 강제
   - read-only source analysis route에서 shell 노출을 금지한 plan 32와 충돌한다.
   - 필요한 검색은 builtin `search_files`, `glob_files`, `source_overview`,
     `source_probe`로 제한한다.

## 상세 구현 계획

### Phase 0. Baseline 고정과 500줄 위험 정리

작업:

- 현재 450줄 이상 파일을 점검한다.
  - `src/allCode/agent/round_runner.py`
  - `src/allCode/agent/model_router.py`
  - `src/allCode/agent/phase_gate.py`
  - `src/allCode/tools/builtin/source_overview.py`
  - `src/allCode/tools/executor.py`
- source analysis 변경 범위에서는 `source_overview.py`에 새 책임을 추가하지 않는다.
- 기존 테스트에 다음 실패 방지 assertion을 추가한다.
  - broad source request에서 `source_overview` 후 곧바로 finalize하지 않는다.
  - read-only route에서 `write_file`, `patch_file`, `run_command`, validation tool이 노출되지 않는다.
  - representative read/probe가 이미 관찰한 경로를 반복하지 않는다.

검증:

```bash
python -m pytest tests/unit/agent/test_inspect_tool_staging.py
python -m pytest tests/unit/tools/test_source_overview_tool.py
```

### Phase 1. Source graph 계층 추가

작업:

- `src/allCode/workspace/source_intelligence/graph.py` 추가.
- 데이터 구조:
  - `SourceGraphNode(path, language, symbols, public_symbol_count, entrypoint_score, large_file_penalty)`
  - `SourceGraphEdge(source_path, target_path, kind, symbol, confidence)`
  - `SourceExplorationCandidate(path, score, reasons, symbols, edge_count)`
- 입력은 `RepoMapEntry` 또는 `SourceFileAnalysis` list로 제한한다.
- import module path resolution은 workspace root 기준 best-effort로 구현한다.
- ranking 함수:
  - `build_source_graph(entries, workspace_root)`
  - `rank_exploration_candidates(graph, prompt_terms, observed_paths, limit)`

주의:

- raw AST node, Tree-sitter node, LSP raw response를 반환하지 않는다.
- 특정 repo명, 테스트 prompt, 경로를 하드코딩하지 않는다.
- file graph 계산은 source file cap 내에서만 수행한다.

테스트:

```bash
python -m pytest tests/unit/workspace/test_source_intelligence_graph.py
```

### Phase 2. Bounded `source_probe` tool 추가

작업:

- `src/allCode/tools/builtin/source_probe.py` 추가.
- `SourceIntelligenceService.analyze_file()` 결과의 line/end_line을 사용한다.
- symbol이 지정되면 해당 symbol 주변 line range를 우선 반환한다.
- symbol이 없으면 import block, top-level class/function signature, entrypoint 후보만
  반환한다.
- 긴 파일은 `max_ranges`와 `context_lines`로 제한한다.
- `ToolResult.metadata["observation"]` 표준:

```python
{
    "kind": "source_probe",
    "target": "src/...",
    "observed_symbols": ["Class.method", "function"],
    "line_ranges": [{"start": 10, "end": 32, "reason": "symbol"}],
    "outgoing_edges": [{"kind": "import", "target": "..."}],
    "incoming_hints": [],
    "truncated": True,
    "backend": "python_ast",
}
```

주의:

- `source_probe`는 read-only tool이다.
- `ToolDefinition(read_only=True, group="search")`를 명시한다.
- 파일 전체를 반환하지 않는다.
- content와 metadata summary는 렌더링 전에 `allCode/memory/redaction.py`의
  redaction helper를 통과시킨다.
- `max_ranges`, `context_lines`, file-size cap이 깨지면 실패하는 테스트를 먼저 둔다.

테스트:

```bash
python -m pytest tests/unit/tools/test_source_probe_tool.py
python -m pytest tests/unit/tools/test_builtin_registry.py
python -m pytest tests/unit/agent/test_tool_schema_filter.py
```

### Phase 3. Exploration planner와 inspect staging 결합

작업:

- `src/allCode/agent/source_exploration.py` 추가.
- 역할:
  - overview metadata와 graph candidates를 읽어 다음 probe/read target을 계산한다.
  - budget은 구조 신호로 계산한다.
    - 단일 파일: 1~2
    - 단일 package: 2~4
    - 다중 package 또는 truncated: 4~8
    - 대형 repo에서 max 10
  - 한 round에 tool target은 최대 3개로 제한한다.
- `inspect_staging.py`는 직접 scoring하지 않고 planner 결과만 사용한다.
- `TARGETED_READ_TOOLS`에 `source_probe`를 추가한다.
- explicit file target이 있으면 `source_probe` -> 필요 시 `read_file` 순서로 좁힌다.

주의:

- `source_exploration.py`가 300줄을 넘으면 budget 계산과 candidate selection을 분리한다.
- model이 임의로 `list_tree` 반복을 선택하지 않도록 broad source inventory 후에는
  `source_probe`, `read_file`, `source_overview`만 허용한다.

테스트:

```bash
python -m pytest tests/unit/agent/test_source_exploration.py
python -m pytest tests/unit/agent/test_inspect_tool_staging.py
```

### Phase 4. Observation ledger와 tool evidence 갱신

작업:

- `src/allCode/core/result.py`에는 가능하면 새 field를 추가하지 않는다.
- 이미 존재하는 `inspected_paths`, `representative_read_paths`,
  `inspect_observation_count`, `source_representative_candidates`,
  `source_representative_reasons`, `source_analysis_coverage`를 우선 재사용한다.
- `source_probe`의 상세 observation은 `ToolResult.metadata`와 message history에 남긴다.
- `src/allCode/agent/source_observation_ledger.py`를 추가해 최근 tool result metadata에서
  compact ledger를 계산한다.
- `src/allCode/agent/tool_evidence.py`는 `source_probe` 결과에서 path 관찰 여부와
  observation count만 표준 evidence에 반영한다.
- session memory에는 raw file body를 넣지 않고 compact observation만 저장한다.
- 후속 질문 context에는 최근 probe path/symbol, package role, 미관찰 target만 넣는다.

주의:

- secret/API key/token 문자열은 memory에 저장하지 않는다.
- `source_probe` content와 metadata summary는 `allCode/memory/redaction.py`의
  redaction helper를 통과한 뒤 저장/렌더링한다.
- `CompletionEvidence`가 provider, TUI, 특정 tool implementation을 import하지 않는다.
- core field 추가가 반드시 필요해지면 먼저 `ToolResult.metadata`로 해결 가능한지
  검토하고, generic field 외에는 추가하지 않는다.

테스트:

```bash
python -m pytest tests/unit/core
python -m pytest tests/unit/agent/test_tool_evidence.py
python -m pytest tests/unit/agent/test_source_observation_ledger.py
python -m pytest tests/unit/memory tests/integration/test_followup_context_memory.py
```

### Phase 5. Grounded summary 강화

작업:

- `src/allCode/agent/inspect_summary.py`가 `source_probe_observations`를 읽는다.
- summary renderer를 새 helper로 분리한다.
  - `src/allCode/agent/source_answer_synthesis.py`
- fallback answer는 관찰과 추론을 분리한다.
- 사용자가 한국어로 물으면 한국어로 답하되 path/symbol/code identifier는 원문 유지한다.

출력 형태:

```text
확인한 범위
- ...

패키지/모듈 역할
- ...

핵심 파일 근거
- path: observed symbols, import/reference edge

연결 흐름
- A -> B -> C

한계
- 직접 읽은 범위와 추론한 범위를 구분
```

테스트:

```bash
python -m pytest tests/unit/agent/test_inspect_summary.py
python -m pytest tests/integration/test_readonly_source_analysis.py
```

### Phase 6. Optional Tree-sitter/LSP enrichment

작업:

- 기본 구현 완료 후에만 진행한다.
- Tree-sitter는 optional extra 설치와 availability check를 둔다.
- LSP는 mock client부터 구현한다.
- 실제 language server 실행은 별도 config flag로 켠다.

주의:

- 설치 실패, timeout, protocol error가 source analysis 실패가 되면 안 된다.
- LSP write feature는 expose하지 않는다.

테스트:

```bash
python -m pytest tests/unit/workspace/test_lsp_client.py
python -m pytest tests/unit/workspace/test_source_intelligence_service.py
```

### Phase 7. 품질 게이트와 라인 제한 회귀 방지

작업:

- 신규 모듈을 quality line-limit 검사 대상에 포함한다.
- `source_overview.py`는 구현 후 420줄 이하를 목표로 분리한다.
- `model_router.py`, `phase_gate.py`, `round_runner.py`, `tools/executor.py`처럼 450줄
  이상 파일은 이번 source analysis 변경에서 더 비대해지지 않게 한다.
- source analysis 구현 중 300줄을 넘는 helper가 생기면 책임을 다시 분리한다.

테스트:

```bash
python -m pytest tests/quality
python -m pytest tests/unit/test_no_scenario_hardcoding.py
```

## 실제 프롬프트 검증 계획

코드 구현 후 동일 prompt를 `agy`, `codex`, `allcode`에 read-only로 요청해 답변 깊이를
비교한다. `allcode`에는 소스 수정 금지 조건을 명시하고, mutation tool 노출 여부도
로그에서 확인한다.

검증 prompt:

1. `현재 디렉터리의 src 내의 코드들이 어떤 역할을 하는지 정리해서 알려줘. 코드 수정은 엄격히 금지한다`
2. `src/allCode/agent 패키지에서 사용자 요청이 tool 호출과 final answer까지 이어지는 흐름을 파일 근거와 함께 설명해줘.`
3. `source_overview, source_probe, inspect_staging이 서로 어떤 역할을 나눠 갖는지 설명해줘.`
4. `CompletionEvidence가 read-only 분석에서 어떤 근거를 저장하는지 관련 파일과 함께 정리해줘.`
5. 후속 질문: `방금 말한 probe 단계가 왜 필요한지 한계와 함께 다시 설명해줘.`

평가 기준:

- tool 사용이 `source_overview` -> `source_probe/read_file` -> final answer로 수렴하는가.
- 같은 파일만 반복하지 않는가.
- 답변에 package 역할, 핵심 파일, symbol, import/reference 연결이 포함되는가.
- 관찰한 사실과 추론한 내용을 분리하는가.
- 코드 수정, shell, validation, approval이 발생하지 않는가.
- 사용자 언어가 한국어이면 최종 답변도 한국어인가.

## 예상 개선 효과

- 넓은 repo 분석에서 대표 파일 1개만 읽고 끝나는 문제를 줄인다.
- symbol과 import/reference edge 중심으로 다음 파일을 고르므로 탐색 깊이가 올라간다.
- 모델 답변이 약해도 fallback summary가 구조화된 observation을 사용해 답변 품질 하한을
  높인다.
- full-file dump 없이 package-level, file-level, symbol-level 근거를 함께 제공한다.

## 남은 리스크와 완화책

| 리스크 | 완화책 |
| --- | --- |
| tool 호출 수 증가로 latency 상승 | adaptive budget, per-round max 3, max total 10으로 제한 |
| graph resolve가 틀린 파일을 연결 | confidence와 reason을 metadata에 기록하고 final answer에서 관찰/추론 분리 |
| LSP 설치/기동 실패 | optional, timeout, disabled fallback 유지 |
| `source_overview.py` 500줄 초과 | helper 분리 후 새 기능은 `graph.py`, `source_probe.py`, `source_exploration.py`에 배치 |
| 모델이 probe plan을 무시 | inspect stage에서 allowed tool set과 target_paths를 좁힘 |
| memory에 raw code 저장 위험 | compact observation만 저장하고 secret redaction 적용 |
| 특정 prompt 대응 하드코딩 유혹 | 구조 신호만 사용하고 prompt/scenario/project/path literal 금지 테스트 추가 |

## 구현 완료 기준

1. 새 source analysis 관련 Python 파일은 모두 500줄 미만이다.
2. `source_overview.py`는 500줄을 넘지 않으며 가능하면 420줄 이하로 줄인다.
3. read-only source 분석 route에서 mutation/shell/validation/approval tool이 노출되지 않는다.
4. broad source request에서 최소 2개 이상의 대표 source observation을 확보한 뒤 final answer로 간다.
5. `source_probe`는 full-file dump 없이 symbol/range 중심 결과를 반환한다.
6. `source_probe` content와 metadata summary에는 secret redaction이 적용된다.
7. `CompletionEvidence`에 새 tool-specific field를 무분별하게 추가하지 않고,
   probe 상세는 `ToolResult.metadata["observation"]`과 agent-local ledger로 처리한다.
8. fallback final answer가 `source_probe` observation을 근거로 구조화된 답변을 만든다.
9. 실제 `allcode` prompt 검증에서 코드 수정 없이 한국어 final answer가 생성된다.
