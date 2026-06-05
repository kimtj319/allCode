# 34. AST/LSP Source Intelligence Hardening Plan

## 목적

이 문서는 `plan/33_source_analysis_depth_hardening_plan.md` 이후 단계로,
read-only source analysis의 정확도를 regex 중심에서 AST/LSP 기반 source
intelligence 계층으로 끌어올리기 위한 상세 보강 계획이다.

결론부터 말하면, AST와 LSP는 정확도를 올릴 수 있다. 다만 효과와 비용이 다르다.

- AST/Tree-sitter는 class/function/import/export 같은 구문 구조 정확도를 즉시
  높인다. allCode의 현재 구조에서는 가장 현실적인 1순위 보강이다.
- LSP는 definition, references, workspace symbols, diagnostics처럼 AST만으로
  부족한 semantic 관계를 보강한다. 하지만 외부 language server 설치, process
  lifecycle, timeout, workspace 초기화 비용이 있으므로 optional enrichment로 둔다.
- 목표는 full IDE를 만드는 것이 아니라, read-only 분석과 repo map의 대표 파일
  선택 정확도를 높이는 것이다.

## 참조 문서와 우선순위

구현 전 아래 문서를 다시 읽는다.

1. `README.md`
2. `AGENTS.md`
3. `plan/00_master_implementation_guide.md`
4. `plan/01_open_source_alignment_contracts.md`
5. `plan/07_workspace_context_plan.md`
6. `plan/08_context_memory_plan.md`
7. `plan/30_source_analysis_language_tooling_hardening_plan.md`
8. `plan/32_readonly_constraint_routing_repair_plan.md`
9. `plan/33_source_analysis_depth_hardening_plan.md`
10. 이 문서

충돌 시 `plan/00`~`12`와 `plan/01`을 우선한다. Plan 33은 full LSP를 금지했지만,
그 금지는 당시 MVP 범위 확장 방지 목적이었다. 이 문서는 사용자가 명시적으로
요청한 후속 확장 계획이므로, LSP를 “optional, bounded, read-only semantic
enrichment”로만 허용한다.

## 공개 오픈소스 참고 결과

### Aider repo map

참조:

- https://aider.chat/docs/repomap.html
- https://aider.chat/docs/languages.html
- https://github.com/Aider-AI/aider

Aider 계열 repo map은 Tree-sitter 기반 symbol/tag 추출과 token-budgeted map을
사용해 대형 repo에서 전체 파일 본문을 넣지 않고도 모델에게 구조 방향성을 준다.
Aider의 언어 지원 문서도 repo map이 Tree-sitter grammar의 `tags.scm`에 의존함을
명시한다.

allCode 적용:

- regex-only fallback은 유지하되, 가능한 언어는 AST/Tree-sitter symbol extractor를
  먼저 사용한다.
- 전체 파일 body dump가 아니라 symbol, imports, references, lightweight edge만
  `RepoMapEntry`와 `source_overview` metadata에 넣는다.
- PageRank 전체 복제는 하지 않는다. 현재 `source_ranking.py`의 lightweight scoring에
  semantic edge 신호만 추가한다.

### Sourcegraph/Cody codebase context

참조:

- https://sourcegraph.com/docs/cody/core-concepts/context
- https://sourcegraph.com/docs/cody/capabilities/chat
- https://sourcegraph.com/docs/code-search/code-navigation

Cody/Sourcegraph는 files, symbols, search 결과, repository context를 조합해
codebase-aware answer를 만든다. Sourcegraph의 code navigation 문서도 symbol,
type signature, references 같은 code intelligence를 강조한다.

allCode 적용:

- `source_overview`의 대표 파일 후보 선정에 symbol references, import graph,
  public API surface를 반영한다.
- 사용자가 특정 symbol을 물으면 `search_files` 반복보다 symbol index 기반 후보를
  우선 노출한다.
- 외부 Sourcegraph backend 자체는 도입하지 않는다. 로컬 workspace 내부 index만
  사용한다.

### LSP specification

참조:

- https://microsoft.github.io/language-server-protocol/
- https://microsoft.github.io/language-server-protocol/specifications/lsp/3.18/specification/

LSP는 editor/IDE와 language server 사이의 표준 protocol이며 definition,
references, workspace/symbol, documentSymbol, diagnostics 등을 제공한다.

allCode 적용:

- LSP는 `workspace/source_intelligence/lsp_client.py` 안에서만 optional client로
  사용한다.
- core model이나 agent loop가 language server process를 직접 알지 않는다.
- LSP가 없거나 timeout이면 AST/regex로 graceful downgrade한다.
- LSP 기능은 read-only metadata enrichment에만 사용하고 code action, rename,
  formatting은 금지한다.

### Tree-sitter

참조:

- https://tree-sitter.github.io/tree-sitter/
- https://tree-sitter.github.io/tree-sitter/using-parsers/2-basic-parsing.html

Tree-sitter는 source code를 concrete syntax tree로 parsing하고 incremental update에
강점이 있다.

allCode 적용:

- 기본 설치에서는 Python stdlib `ast`를 먼저 강화한다.
- 다국어 AST는 optional extra로 Tree-sitter 계층을 추가한다.
- Tree-sitter parser 설치 실패가 allCode 실행 실패로 이어지면 안 된다.

## agy 검토 반영 요약

agy에는 코드 수정, 파일 생성, 파일 삭제, 커밋을 금지하고 현재 코드 구조 기준 검토를
요청했다. 피드백 요지는 다음과 같다.

1. AST가 LSP보다 먼저다.
   - AST는 단일 process 안에서 안정적으로 동작하고, 현재 MVP 경량 구조에 맞다.
   - LSP는 language server 설치와 process lifecycle이 있어 optional이어야 한다.
2. `SymbolIndexer`는 언어별 parsing 책임을 직접 갖지 말고
   `workspace/source_intelligence/` 하위 parser로 분리해야 한다.
3. `source_structure.py`, `repo_map.py`, `source_overview.py`,
   `source_ranking.py`가 같은 parser 결과를 공유해야 regex 중복과 불일치가 줄어든다.
4. fallback은 다음 순서가 적절하다.
   - LSP optional enrichment
   - AST/Tree-sitter parser
   - regex fallback
   - generic line/header fallback
5. 테스트는 실제 LSP process 없이 mock client로 deterministic하게 작성해야 한다.

## 현재 코드 기준 문제 지점

### 1. `workspace/symbol_index.py`

현재 상태:

- Python은 stdlib `ast`를 사용한다.
- Java/JS/TS는 regex parser다.
- `SymbolRecord`에는 path, name, kind, signature, line만 있다.
- references는 거의 비어 있다.

문제:

- Python도 method scope, parent class, decorators, import alias, call references,
  end_line 정보가 부족하다.
- 다른 언어는 regex라 nested/anonymous/export/import 관계를 놓친다.
- 이 파일 하나에 parser strategy가 쌓이면 곧 책임이 커진다.

### 2. `memory/repo_map.py`

현재 상태:

- `SymbolIndexer.extract()` 결과를 `RepoMapEntry.definitions/imports/references`로
  단순 mapping한다.

문제:

- references가 약하므로 repo map ranking이 imports와 filename 중심으로 기운다.
- symbol scope, class method, exported surface, call edge가 없다.

### 3. `tools/builtin/source_overview.py`

현재 상태:

- `RepoMapBuilder().build_entries()`를 호출해 groups와 representative reads를 만든다.
- metadata는 `representative_reads`, reasons, scores를 보존한다.

문제:

- scoring 입력이 regex/기초 AST 수준이라 semantic centrality가 약하다.
- LSP diagnostics/definition/reference 신호를 담을 위치가 없다.

### 4. `tools/builtin/source_ranking.py`

현재 상태:

- public definition count, import count, approximate fan-in, entrypoint name으로 ranking한다.

문제:

- 같은 symbol 이름이 여러 파일에 있을 때 definition/reference를 구분하지 못한다.
- 실제 call/reference 관계가 아니라 import string match에 의존한다.

### 5. `agent/source_structure.py`

현재 상태:

- `read_file` fallback summary용 regex parser가 별도로 존재한다.

문제:

- `SymbolIndexer`와 parsing 로직이 중복된다.
- Python AST와 다국어 parser가 개선돼도 fallback summary가 같은 정확도 향상을
  자동으로 받지 못한다.

## Non-Negotiable Constraints

금지:

- 특정 prompt, scenario ID, repository path, 프로젝트명, 파일명을 예외 처리하지 않는다.
- read-only source analysis에서 mutation, shell, validation, approval schema를 열지 않는다.
- full-file dump를 만들지 않는다.
- LSP code action, rename, formatting, workspace edit은 사용하지 않는다.
- LSP server 설치를 기본 실행 조건으로 만들지 않는다.
- core에 LSP process, Tree-sitter raw node, provider raw payload를 넣지 않는다.
- MCP server manager, plugin marketplace, cloud sandbox, multi-agent swarm은 도입하지 않는다.
- PageRank full clone은 하지 않는다. lightweight graph scoring만 한다.
- 신규/수정 Python 파일은 500줄을 넘기지 않는다. 300줄을 넘기면 분리 후보로 본다.

허용:

- Python stdlib `ast` 강화.
- optional dependency extra로 Tree-sitter parser 계층 추가.
- optional LSP client와 mockable protocol 추가.
- JSON-safe source intelligence metadata를 `ToolResult.metadata`,
  `CompletionEvidence`, `RepoMapEntry`에 보존.
- 실제 LSP가 없을 때 AST/regex로 fallback.

## 목표 아키텍처

```text
workspace/source_intelligence/
  schema.py              # SourceSymbol, SourceImport, SourceReference, SourceFileAnalysis
  service.py             # SourceIntelligenceService: parser + optional LSP orchestration
  parser_protocol.py     # SourceParser Protocol
  python_ast.py          # Python stdlib ast parser
  regex_fallback.py      # current regex fallback, language-neutral fallback
  tree_sitter_parser.py  # optional Tree-sitter parser adapter
  lsp_client.py          # optional read-only JSON-RPC LSP client protocol
  lsp_registry.py        # configured server command discovery and capability map
```

의존 방향:

```text
workspace/source_intelligence
    -> workspace.indexer
    -> memory.repo_map
    -> tools.builtin.source_overview / source_ranking
    -> agent.source_structure
```

금지 방향:

```text
core -> workspace/source_intelligence
tui -> workspace/source_intelligence
agent loop -> raw LSP process
```

## 데이터 계약

### `SourceSymbol`

필드:

- `path: str`
- `name: str`
- `kind: str`
- `signature: str`
- `line: int`
- `end_line: int | None`
- `scope: str`
- `parent: str`
- `visibility: str`
- `decorators: list[str]`
- `exported: bool`

### `SourceImport`

필드:

- `path: str`
- `module: str`
- `names: list[str]`
- `alias: str`
- `line: int`
- `relative: bool`

### `SourceReference`

필드:

- `path: str`
- `symbol: str`
- `line: int`
- `kind: Literal["call", "import", "inheritance", "reference", "definition"]`
- `target_hint: str`
- `confidence: float`

### `SourceFileAnalysis`

필드:

- `path: str`
- `language: str`
- `backend: Literal["python_ast", "tree_sitter", "regex", "generic"]`
- `symbols: list[SourceSymbol]`
- `imports: list[SourceImport]`
- `references: list[SourceReference]`
- `diagnostics: list[dict[str, object]]`
- `quality: dict[str, object]`

모든 필드는 JSON-safe primitive/list/dict로 직렬화 가능해야 한다.

## 구현 Phase

### Phase 0. 기준 테스트 고정

추가/수정 대상:

```text
tests/unit/workspace/test_source_intelligence_python_ast.py
tests/unit/workspace/test_source_intelligence_fallback.py
tests/unit/workspace/test_source_intelligence_lsp.py
tests/unit/memory/test_repo_map.py
tests/unit/tools/test_source_overview_tool.py
tests/unit/agent/test_inspect_summary.py
tests/integration/test_readonly_source_analysis.py
```

테스트 기준:

1. Python AST parser가 class method scope를 `ClassName.method` 형태로 보존한다.
2. decorators, async functions, imports alias, base classes, call references를 추출한다.
3. SyntaxError 파일은 regex fallback으로 degrade하고 전체 분석은 실패하지 않는다.
4. Tree-sitter package가 없어도 `python -m pytest` 기본 회귀가 통과한다.
5. Mock LSP client가 workspaceSymbol/documentSymbol/references를 반환하면 metadata에
   semantic references가 반영된다.
6. Mock LSP timeout/error는 `lsp_unavailable` metadata만 남기고 AST 결과를 유지한다.
7. read-only source analysis에서 write/patch/delete/run_command/run_tests가 호출되지 않는다.
8. 특정 path나 prompt 문자열을 하드코딩하지 않았는지 기존 no-hardcoding 테스트를 확장한다.

### Phase 1. Source intelligence contract 추가

수정/추가 대상:

```text
src/allCode/workspace/source_intelligence/schema.py
src/allCode/workspace/source_intelligence/parser_protocol.py
src/allCode/workspace/source_intelligence/regex_fallback.py
src/allCode/workspace/source_intelligence/service.py
```

구현 내용:

1. `SourceParser` Protocol을 정의한다.
2. 기존 `SymbolRecord`/`FileSymbols`와 호환되는 adapter를 제공한다.
3. `SourceIntelligenceService.analyze_file(path)`는 다음 순서로 분석한다.
   - Python stdlib AST parser
   - optional Tree-sitter parser
   - regex fallback
   - generic fallback
4. `SymbolIndexer.extract()`는 public API를 유지하되 내부적으로 service를 호출한다.

주의:

- `SymbolIndexer.extract()`의 기존 테스트는 깨지지 않아야 한다.
- core model은 수정하지 않는다.

### Phase 2. Python AST parser 강화

추가 대상:

```text
src/allCode/workspace/source_intelligence/python_ast.py
```

구현 내용:

1. `ast.NodeVisitor` 기반 parser를 만든다.
2. 추출 대상:
   - module imports/import aliases
   - class definitions, base classes
   - methods with parent class scope
   - functions/async functions
   - decorators
   - top-level constants if exported/public
   - call references: `foo()`, `obj.method()`, `ClassName()`
3. line/end_line을 기록한다.
4. syntax error는 exception을 던지지 않고 fallback reason을 반환한다.

효과:

- 현재 regex fallback보다 Python 구조 정확도가 크게 오른다.
- 대표 파일 ranking에서 class method와 public API surface가 더 정확해진다.

### Phase 3. Optional Tree-sitter parser 계층

수정 대상:

```text
pyproject.toml
requirements.txt
src/allCode/workspace/source_intelligence/tree_sitter_parser.py
```

계획:

1. 기본 dependency에는 추가하지 않는다.
2. optional extra 후보:

```toml
[project.optional-dependencies]
source-intelligence = [
  "tree-sitter>=0.22",
  "tree-sitter-language-pack>=0.7",
]
```

3. 구현 전 실제 package availability와 Python 3.11/macOS 설치 가능성을 확인한다.
4. import 실패 시 `TreeSitterParser.available == False`로 처리한다.
5. Tree-sitter query는 MVP 언어부터 제한한다.
   - Python은 stdlib AST가 우선이므로 Tree-sitter fallback 또는 cross-language support.
   - JavaScript/TypeScript
   - Go
   - Rust
   - Java
6. query가 없거나 parse error가 있으면 regex fallback으로 degrade한다.

주의:

- Aider처럼 100+ 언어를 목표로 하지 않는다.
- `tags.scm` 관리 체계를 직접 대규모로 복제하지 않는다.
- optional extra 미설치 상태에서도 전체 테스트가 통과해야 한다.

### Phase 4. Optional LSP enrichment

추가 대상:

```text
src/allCode/workspace/source_intelligence/lsp_client.py
src/allCode/workspace/source_intelligence/lsp_registry.py
src/allCode/config/schema.py
src/allCode/config/defaults.py
```

설정 후보:

```yaml
source_intelligence:
  mode: auto        # off | ast | ast_lsp | auto
  lsp_enabled: false
  lsp_timeout_ms: 1000
  servers:
    python:
      command: ["pyright-langserver", "--stdio"]
    typescript:
      command: ["typescript-language-server", "--stdio"]
```

환경 변수 후보:

```text
ALLCODE_SOURCE_INTELLIGENCE=auto|off|ast|ast_lsp
ALLCODE_LSP_ENABLED=0|1
ALLCODE_LSP_TIMEOUT_MS=1000
```

LSP 허용 request:

- `initialize`
- `initialized`
- `textDocument/didOpen`
- `textDocument/documentSymbol`
- `workspace/symbol`
- `textDocument/definition`
- `textDocument/references`
- diagnostics receive/read
- `shutdown`
- `exit`

LSP 금지 request:

- `textDocument/rename`
- `workspace/applyEdit`
- `textDocument/codeAction` execution
- formatting

Fallback:

1. server command missing -> `lsp_unavailable: command_not_found`
2. initialize timeout -> `lsp_unavailable: timeout`
3. request unsupported -> AST result 유지
4. JSON-RPC error -> AST result 유지

테스트:

- 실제 server process 없이 fake JSON-RPC client로 검증한다.
- 선택적으로 local dev 환경에서만 pyright smoke를 별도 marker로 둔다.

### Phase 5. RepoMapEntry와 source overview 통합

수정 대상:

```text
src/allCode/memory/schema.py
src/allCode/memory/repo_map.py
src/allCode/tools/builtin/source_overview.py
src/allCode/tools/builtin/source_ranking.py
src/allCode/agent/tool_evidence.py
src/allCode/core/result.py
```

구현 내용:

1. `RepoMapEntry`에 optional JSON-safe fields를 추가한다.
   - `symbols: list[dict[str, object]]`
   - `imports_detail: list[dict[str, object]]`
   - `references_detail: list[dict[str, object]]`
   - `analysis_backend: str`
   - `analysis_quality: dict[str, object]`
2. 기존 `definitions/imports/references` 필드는 유지한다.
3. `source_ranking.py` score를 다음 순서로 강화한다.
   - LSP references count
   - AST call/import references
   - public exported symbol count
   - entrypoint signal
   - package diversity
   - existing recent target/prompt target match
4. raw AST node, raw LSP payload는 metadata에 넣지 않는다.
5. `source_overview` output은 summary만 보여주고 상세 graph는 metadata로 전달한다.

### Phase 6. `agent/source_structure.py` 중복 제거

수정 대상:

```text
src/allCode/agent/source_structure.py
src/allCode/agent/inspect_summary.py
```

구현 내용:

1. `read_file` fallback summary도 `SourceIntelligenceService.analyze_text(path, content)`를
   호출한다.
2. 기존 regex 함수는 `regex_fallback.py`로 이동하거나 thin wrapper로 남긴다.
3. summary section은 유지한다.
   - 핵심 파일 근거
   - 주요 클래스/함수
   - 의존성/연결 흐름
   - 아직 단정하지 않은 부분
4. 경로, symbol, command, code identifier는 번역하지 않는다.

### Phase 7. Prompt와 inspect stage 조정

수정 대상:

```text
src/allCode/agent/prompt_builder.py
src/allCode/agent/inspect_staging.py
```

구현 내용:

1. `source_overview` metadata에 `analysis_backend`, `semantic_edge_count`,
   `lsp_available`이 있으면 targeted read 지시에 반영한다.
2. 모델에게 raw graph를 설명하라고 하지 않는다.
3. “관찰된 semantic evidence”와 “추론한 package role”을 분리하라고 지시한다.
4. LSP가 unavailable이면 이를 내부 한계로만 사용하고, 최종 답변에는 필요한 경우
   “정적 분석 근거 기준” 정도로 완화해 표현한다.

### Phase 8. 성능, cache, invalidation

수정 대상:

```text
src/allCode/workspace/indexer.py
src/allCode/workspace/source_intelligence/cache.py
```

구현 내용:

1. cache key:
   - path
   - mtime
   - size
   - content_hash
   - parser backend version
2. 파일 크기 제한:
   - AST parse 기본 최대 512KB
   - Tree-sitter parse 기본 최대 512KB
   - LSP didOpen 기본 최대 512KB
3. cache miss만 parse한다.
4. LSP enrichment는 대표 후보 또는 explicit symbol target에만 수행한다.

주의:

- workspace 전체에 LSP references를 무제한 질의하지 않는다.
- default headless latency가 크게 늘면 안 된다.

## 검증 계획

### 필수 단위 테스트

```bash
python -m pytest tests/unit/workspace/test_source_intelligence_python_ast.py
python -m pytest tests/unit/workspace/test_source_intelligence_fallback.py
python -m pytest tests/unit/workspace/test_source_intelligence_lsp.py
python -m pytest tests/unit/workspace/test_indexer.py tests/unit/memory/test_repo_map.py
python -m pytest tests/unit/tools/test_source_overview_tool.py
python -m pytest tests/unit/agent/test_inspect_summary.py tests/unit/agent/test_inspect_tool_staging.py
```

### 필수 통합 테스트

```bash
python -m pytest tests/integration/test_readonly_source_analysis.py
python -m pytest tests/tty/test_terminal_readonly_source_analysis.py tests/tty/test_terminal_readonly_tool_visibility.py
python -m pytest tests/unit/agent tests/unit/tools tests/unit/workspace tests/unit/memory
python -m pytest
```

### 선택 LSP smoke

실제 language server가 설치된 개발 환경에서만 실행한다.

```bash
ALLCODE_LSP_ENABLED=1 ALLCODE_SOURCE_INTELLIGENCE=ast_lsp allcode --headless "읽기 전용 분석이다. src의 주요 public API와 reference 흐름을 요약해줘."
```

성공 기준:

- LSP가 없으면 실패하지 않고 AST 기반 답변이 나온다.
- LSP가 있으면 metadata에 `lsp_available: true`, reference/definition evidence가 남는다.
- 최종 답변은 사용자의 언어를 따른다.
- 파일 변경은 0개다.

## 품질 기준

정량 기준:

- Python test fixture에서 symbol extraction precision 90% 이상.
- method scope, decorator, import alias, async function 추출 회귀 0건.
- LSP unavailable scenario에서 전체 turn success 또는 grounded partial summary.
- broad source overview에서 representative read 후보가 semantic centrality에 따라 바뀌는 테스트 통과.
- full regression `python -m pytest` 통과.

정성 기준:

- source 분석 답변이 “디렉터리 역할 나열”에서 끝나지 않고 public API, 주요 class/function,
  import/reference 흐름을 포함한다.
- 관찰된 근거와 추론이 분리된다.
- 내부 backend 이름이나 raw score가 사용자 답변을 오염시키지 않는다.

## 남은 리스크

1. Tree-sitter package 설치 안정성.
   - mitigation: optional extra로 격리하고 기본 테스트는 미설치 상태에서 통과.
2. LSP server별 behavior 차이.
   - mitigation: mock protocol 테스트를 기준으로 하고 실제 server smoke는 optional.
3. 성능 비용.
   - mitigation: AST cache, file size cap, 대표 후보/explicit symbol target에만 LSP 적용.
4. semantic graph 과신.
   - mitigation: confidence를 metadata에 남기고 final answer에서 단정하지 않음.
5. 범위 확장.
   - mitigation: rename/codeAction/formatting/MCP/PageRank/plugin/cloud 기능 금지.
6. 파일 비대화.
   - mitigation: source_intelligence 패키지로 분리하고 300줄 이상부터 분리 후보 검토.

## 구현 순서 요약

1. 테스트부터 추가한다.
2. `SourceFileAnalysis` 계약과 parser protocol을 만든다.
3. Python AST parser를 강화한다.
4. `SymbolIndexer`가 새 service를 호출하도록 바꾼다.
5. `RepoMapBuilder`, `source_overview`, `source_ranking`에 semantic metadata를 연결한다.
6. `source_structure` fallback summary를 새 parser 결과로 통합한다.
7. optional Tree-sitter extra를 추가한다.
8. optional LSP mock client와 config를 추가한다.
9. read-only source analysis smoke와 전체 회귀를 실행한다.

## 최종 판단

AST는 지금 코드에 바로 적용할 가치가 크다. 특히 Python은 stdlib `ast`를 이미 쓰고
있으므로 parent scope, references, imports detail을 보강하면 비용 대비 효과가 크다.

LSP는 정확도 상한을 올리는 수단이지만 기본 실행 경로에 넣으면 설치/속도/환경 리스크가
커진다. 따라서 allCode에서는 “AST 기본, Tree-sitter optional, LSP optional enrichment”
가 현실적인 최종 설계다.
