# 73. 코드 최적화 플랜 — 데드코드·중복·성능·구조

> 전체 코드(285 모듈 / ~44k LOC, `agent/`만 121파일)를 ruff·vulture + 병렬 분석으로 조사한 결과.
> 동작을 바꾸지 않는(behavior-neutral) 최적화만 제안하며, 각 단계는 **전체 테스트 그린 유지**를 전제로 한다.
> 착수 순서는 6절(저위험·고효과 → 구조 리팩터). 모든 변경은 증분 커밋 + `pytest` 검증.

---

## 1. 성능 (가장 큰 효과)

### P0 — 턴마다 전체 소스 재파싱 (치명적, 최우선)
- **현상**: `memory/selector.py:57`가 매 턴 `RepoMapBuilder.build_entries(workspace_index)` 호출 → `memory/repo_map.py:20`가 `index.source_files()`(이 repo ~1800개)를 돌며 `symbol_indexer.extract(path)`로 **매번 파일을 다시 읽고 AST/tree-sitter 파싱**. 한 줄짜리 질문에도 발생.
- **근본 원인**: `agent/context_factory.py:37`이 `RepoMapBuilder()`를 `cache_path=None`으로 생성 → 이미 존재하는 `load_cache()`/`mtime` 경로가 전혀 동작하지 않음. `build_entries`는 캐시·mtime 비교 없이 항상 전량 재구성.
- **수정**:
  1. `RepoMapBuilder(cache_path=root/".allCode"/"repo_map_cache.json")` 주입.
  2. `build_entries`에서 `RepoMapEntry.mtime`(이미 존재) 대비 변경된 파일만 재파싱, 나머지는 캐시 재사용.
  3. 더 나아가 `ContextMemorySelector` 인스턴스에 결과 메모이즈(턴 간 재사용), `WorkspaceIndexer.update_file`로 파일 단위 무효화.
  4. (선택) 경량 `WorkspaceIndex`로 먼저 랭킹 후 `token_budget`(기본 1200) 안에 드는 상위 K개만 파싱.
- **효과**: 턴당 ~1800 read+parse 제거 → 턴 지연 수백 ms~수 초 절감(최대 효과).

### P1 — 시작 시 전체 인덱스 즉시 빌드 + ignore 디렉터리까지 순회
- **현상**: `agent/context_factory.py:30`이 `build_runtime_context_builder`에서 인덱스를 즉시 빌드(`indexer.py:74` 전체 `rglob("*")`). 헤드리스는 `runtime.py:63`에서 매 턴 컨텍스트 빌더(+인덱스) 재생성.
- 해시 캐시는 미변경 파일의 content read만 생략하고, **전체 트리 walk + 파일별 `stat()`은 매 실행 발생**. `_ignored()`(`indexer.py:131`)는 순회 *후* 필터라 `.venv/.git/node_modules` 내부까지 전부 yield.
- **수정**:
  1. 인덱스를 **지연 빌드**(첫 `ContextBuilder.build()` 시) 또는 TUI 렌더와 병행 백그라운드 빌드.
  2. 순회 단계에서 ignore 디렉터리 **가지치기**(`os.walk` + `dirnames[:]` 또는 `os.scandir` 재귀)로 ignored 서브트리 미진입. 동일 패턴: `project_locator.py:81`, `project_init.py:56`, `workflow_routing.py:134`, `source_overview.py:316-324`.
  3. 헤드리스 다중 턴 시 컨텍스트 빌더 재사용(캐시).
- **효과**: 매 실행 시작 지연 감소(특히 큰 `.venv`/`node_modules` 저장소).

### P2 — 턴마다 메모리 파일 재읽기
- `memory/store.py:61,77,111,137`이 매 턴 `AGENTS.md`/`CLAUDE.md`/계층 `ALLCODE.md`/`items.jsonl`을 `read_text()` 재읽기·재파싱·리댁션. → mtime 캐시(세션 중 거의 불변).

### P3 — 함수/루프 내부 정규식 컴파일 (저위험, 쉬움)
- `agent/validation_failure_parser.py:89-214`(수리 라운드마다 다수 `re.compile`), `memory/project_obligations.py:137-153,254-259`(변경 턴마다 프롬프트 빌드), `llm/tool_argument_repair.py:146-189`, `workspace/source_intelligence/regex_fallback.py:30-82`(라인 루프 내). → 모듈 레벨 컴파일로 승격.

---

## 2. 데드코드 삭제 (검증 완료, 안전)

병렬 트리아지로 **production-dead** 확정(테스트 결합 없음):
- `core/errors.py` — `ModelResponseError`, `ToolExecutionError`, `PolicyDeniedError`(주의: 사용 중인 `PathPolicyDeniedError`와 별개), `ApprovalRequiredError`, `ContextBudgetExceededError` (정의만 존재, 어디서도 raise/import 안 됨).
- `core/events.py` — `WorkspaceRootAdded/WorkspaceRootRejected/WorkspaceIndexed/PathResolved/PathResolutionAmbiguous/WorkspaceIndexUpdated`(미발행), `TurnCancelled`(미발행). 함께: `tui/layout.py:98`의 `"turn_cancelled"` 처리·`tui/renderers.py:312` `_render_turn_cancelled`·`tests/helpers/quality.py:129`의 `"path_resolved"` 체크 정리.
- `tui/input_box.py` — **모듈 전체 미참조**(어디서도 import 안 됨; 실제 입력은 `tui/app.py`의 `query_one("#input")` 사용). 파일 삭제.

**테스트 전용**(프로덕션 미사용 — 테스트와 함께만 삭제 판단): `memory/auto_memory.py`(`AutoMemoryExtractor`), `tui/approval_panel.py`, `is_image_path`, `needs_candidate_read`, `source_answer_retry_used`, `transcript_to_markdown`, `format_transcript_block`, `transcript_block_content`. → 유지 또는 "기능 폐기 시 테스트째 삭제" 정책 결정.

**오탐(유지)**: `_render_*`(동적 `getattr` 디스패치), Pydantic `@field_validator`/`@model_validator`, `StaticTextTool`/`StaticLspClient`(테스트 픽스처), Textual 콜백. **삭제 금지.**

ruff `F401/F811/F841` 6건(미사용 import/변수)은 `ruff check --fix`로 일괄 정리.

---

## 3. 중복 제거 → 공유 헬퍼 (저위험, 기계적)

| 중복 | 위치(≥2) | 제안 헬퍼 |
|---|---|---|
| 마크다운 펜스 제거 + JSON 파싱 | `project_planner.py:334`, `final_answer_format.py:332`, `workflow_editor.py:306` | `core/json_extraction.py` (`strip_code_fence`, `extract_json`) |
| 경로→워크스페이스 상대 (`relative_to`+ValueError 폴백) | ~10곳(`tool_evidence.py:236`, `round_context.py:38`, `repair_target_ranking.py:63`, `phase_gate_artifacts.py:275`, `related_tests.py:130`, …) | `workspace/path_resolver.to_workspace_relative()` |
| 경로 토큰 정리(`strip().strip("\`").replace("\\\\","/")`) | 20곳 | `workspace/path_resolver.normalize_path_token()` |
| N자 절단+말줄임(`_compact`/`_truncate`) | 4+곳(`task_loop_digest.py:182`, `source_answer_guard.py:525`, `project_planner.py:197`, `modify_fallback.py:81`, `shell.py:23`, `custom_commands.py:60`) | `core/text.truncate(text, limit, *, collapse=)` |
| git subprocess 래퍼 | `git_ops.py:28` `_run` vs `git_state.py:27,58` 재구현 | `git_ops.run_git`/`is_git_repo` 공개·재사용 |
| 의도/제약 용어 테이블(10개 동일 상수, `READ_ONLY_TERMS` 바이트 동일) | `intent_terms.py` ↔ `prompt_constraint_terms.py` | `agent/prompt_terms.py`로 호이스트 |

---

## 4. 과편화 모듈 병합 (단일 소비자, behavior-neutral)

**고신뢰(약 5파일 감소)**:
- `model_router_json.py`+`model_router_schema.py`+`model_router_prompt.py` → `model_router_support.py` (각각 1심볼, `model_router.py`만 소비).
- `source_package_role_guard.py`(162) → `source_answer_guard.py` (유일 소비자).
- `answer_prompt.py`(61) → `prompt_sections.py` (단일 소비 체인).

**구조 중복 제거**: `answer_scope_guard`/`dependency_answer_guard`/`source_answer_guard`가 동일한 `*Violation`(reason/excerpt) 데이터클래스 + `*_retry_used`를 각자 재정의 → `agent/answer_guard_base.py`로 `GuardViolation`+retry 계약 추출.

**병합 금지**(응집도 사유): `tool_schema_*` 3종, `round_*` 단계 모듈군, `validation_repair.py`(7곳 재노출 파사드), `read_only_guard.py`(도구정책 레이어). — 분리 유지.

---

## 5. 갓 모듈 분리 (>450 LOC, 관심사 혼재)

| 파일 | LOC | 분리안 |
|---|---|---|
| `project_planner.py` | 637 | `project_plan_payload.py`(coerce/extract), `_layout.py`(스캐폴드), `_safety.py`(경로/검증), `_prompt.py`(planning context). 스파인은 `ModelProjectPlanner`+`_sanitize_plan` 유지 |
| `finalization.py` | 497 | 14개 문구 게이트를 `final_answer_{safety,validation,lookup,web,feature}.py`로 분류, 오케스트레이터만 유지 |
| `source_answer_guard.py` | 529 | `source_anchor_map.py`, `source_answer_retry_prompts.py`(87줄 이중언어) 분리 |
| `tools/web_provider.py` | 619 | `web_html.py`(파서), `web_evidence.py`, `web_provider_duckduckgo.py`; 프로토콜·팩토리만 유지 |
| `tui/terminal.py` | 634 | `terminal_steering.py`(`_SteeringCapture`·자기완결, 최우선), 이후 `terminal_metrics.py`/`terminal_output.py` |

`loop.py`(502)/`round_runner.py`(495)/`workflow.py`(475)는 응집적 — 분리 보류(선택적 소규모 추출만).

---

## 6. 착수 순서 · 위험 · 검증

1. **Phase 1 (저위험·기계적)**: §2 데드코드 삭제 + ruff --fix, §3 중복 헬퍼 추출. → 표면적 축소, 동작 불변. 각 커밋마다 전체 pytest.
2. **Phase 2 (고효과 성능)**: §1 P0(repo_map 캐시) → P1(지연/가지치기 인덱스) → P2(store mtime) → P3(정규식). P0/P1은 캐시 정확성 회귀 위험 → mtime 무효화 테스트 추가.
3. **Phase 3 (구조)**: §4 병합 → §5 갓 모듈 분리. 공개 API 보존(오케스트레이터 잔류, 내부만 이동), import 갱신, 각 단계 pytest.

**가드레일**:
- 변경 전 기준선: 현재 `~938 passed, 3 skipped`. 매 커밋 그린 유지.
- 데드코드는 "정의-only + 비동적-디스패치 + 비검증자"만 삭제. 의심되면 보류.
- 성능 캐시는 mtime/size 키로 정확성 보장 + 무효화 단위테스트 동반.
- 파일 이동/병합은 한 번에 하나씩, import 경로만 바꾸고 로직 무변경.

> 본 문서는 계획이며 코드 변경은 포함하지 않는다. 착수 시 Phase 단위로 진행한다.
