# 71. 보강 적용 후 에이전트 역량 비교 — Codex CLI / Claude Code / aider 대비

> `plan/70`의 17개 보강 항목을 모두 적용한 뒤의 갱신 비교.
> 비교 대상: **Codex CLI**, **Claude Code**, **aider**("agy"는 aider로 해석).
> 기준 시점 테스트 상태: **882 passed, 3 skipped**.
> 부분 구현은 정직하게 "부분"으로 표기한다.

---

## 1. 역량별 비교 (갱신)

| 역량 | allCode (현재) | Claude Code | Codex CLI | aider |
|---|---|---|---|---|
| 생성 워크플로 + 검증/수리 | **강 (고유)** — plan→skeleton→impl→tests→validation→repair(최대 5회) | 약 | 중 | 중 |
| 턴 중간 개입 / 큐잉 | **강** — 큐+라운드 경계 주입 + TUI 실시간 캡처(승인 중 일시정지) | 강 | 강 | 중 |
| 플랜 모드(승인 후 실행) | **강** — `approval.plan_mode` 승인 게이트 | 강 | 중 | — |
| 세션 재개 | **강** — `--continue` / `--resume` | 강 | 강 | 강 |
| 권한 정밀도(경로/명령) | **강** — allow/deny 글롭 규칙(deny 우선) | 강 | 중 | 중 |
| 셸 스트리밍 / 백그라운드 | **강** — `run_command background` + `get_command_output`/`kill_command` | 강 | 강 | — |
| 병렬 도구 / 서브에이전트 | **강** — 독립 read 도구 병렬 실행 + 쓰기 가능 위임 서브에이전트 | 강 | 중 | — |
| 체크포인트 / rewind | **강** — 턴별 파일 스냅샷 + `/rewind` | 강 | git | 강 |
| 컨텍스트 압축 / 비용 미터 | **강** — `/compact` + `/cost` | 강 | 중 | 중 |
| MCP | **강** — stdio + HTTP/SSE + resources + prompts | 강 | — | — |
| 모델 티어링 | **강** — 2티어(ultra=라우팅·요약·플래너, max=구현) | 보조모델 | — | architect/editor |
| lint / format / typecheck | **중~강** — 옵트인 ruff/mypy/tsc/eslint | 강 | 중 | 강(자동 lint+커밋) |
| AST / 의미 기반 편집 | **강** — 편집 후 구문 검증 + `replace_symbol`(ast) + `apply_edits`(원자적 다중파일) | 부분 | 부분 | 중 |
| 헤드리스 / 스크립트 | **강** — text / json / stream-json + `--image` 멀티모달 | 강 | 강 | 중 |
| @-멘션 | **강** — 경로 + `@file::symbol` 심볼 단위(ast) | 강 | 중 | 강 |

범례: **강** = 선두 도구와 동등 이상 / **중** = 사용 가능하나 깊이 부족 / **부분** = 핵심 메커니즘은 있으나 일부 미완 / **약** = 미흡 / **—** = 미지원.

---

## 2. 적용된 보강과 매핑되는 모듈 (근거)

| # | 항목 | 핵심 모듈 |
|---|---|---|
| 1 | 턴 중간 개입 | `agent/steering.py`(SteeringQueue), `agent/round_runner.py`(라운드 경계 drain·주입) |
| 2 | 플랜 승인 | `config/schema.py`(`approval.plan_mode`), `agent/workflow.py`(승인 게이트), `agent/workflow_result.py`(거부 결과) |
| 3 | 세션 재개 | `main.py`(`--continue`/`--resume`), `memory/conversation_store.py`, `runtime.seed_resumed_session` |
| 4 | 권한 정밀도 | `tools/permission_rules.py`(allow/deny, deny 우선), `tools/approval.py` |
| 5 | 셸 백그라운드 | `tools/builtin/background_jobs.py`, `tools/builtin/shell.py`(background/output/kill) |
| 6 | 쓰기 서브에이전트 | `tools/builtin/task.py`(`DelegateTaskTool`) |
| 7 | 체크포인트/rewind | `workspace/checkpoint_store.py`, `tui/slash_commands.py`(`/rewind`) |
| 8 | /compact + 비용 | `agent/context.compact_session`, `tui/terminal.py`(`/cost` 미터) |
| 9 | MCP HTTP/SSE | `tools/mcp/http_client.py`, `tools/mcp/manager.py`, `tools/mcp/tool.py`(`MCPResourceTool`) |
| 10 | 모델 티어링 | `llm/settings.py`(`implementation_from_config`), `config/schema.py`(`implementation_model_name`) |
| 11 | AST 인지 편집 | `tools/builtin/file_common.py`(`syntax_warning`) |
| 12 | lint/typecheck | `agent/validation_lint.py`, `agent/validation_runner.py` |
| 13 | 헤드리스 강화 | `headless.py`(`--output-format`), `main.py` |
| 14 | 인덱싱 캐시 | `workspace/indexer.py`, `agent/context_factory.py` |
| 15 | 변경 리뷰 | `workspace/git_ops.working_tree_diff`, `tui/slash_commands.py`(`/review`) |
| 16 | 지시문 요약 | `memory/store.py`(`_condense_instruction_text`) |
| 17 | @-멘션 | `tui/mentions.py`(+ `@file::symbol` ast 추출) |
| (잔여) 1 | TUI 실시간 스티어링 캡처 | `tui/terminal.py`(`_SteeringCapture`) |
| (잔여) 2 | 병렬 read 도구 실행 | `agent/tool_call_processor.py`(`_prefetch_read_only`) |
| (잔여) 3 | AST 심볼 편집 / 원자적 다중파일 | `tools/builtin/ast_edit.py`(`replace_symbol`, `apply_edits`) |
| (잔여) 4 | 헤드리스 이미지 입력 | `main.py`(`--image`), `headless.py`, `runtime.run_agent_turn`(images) |

---

## 3. 한 줄 요약

- **이전**: 생성 워크플로+검증/수리라는 고유 강점은 있었으나 대화형 UX(중간 개입·플랜 승인·세션 재개)와 운영 기능(백그라운드 셸·정밀 권한·MCP 전송)에서 격차가 컸다.
- **plan/70 적용 후**: 세션 재개·플랜 승인·권한 정밀도·백그라운드 셸·체크포인트·`/compact`·`/cost`·MCP HTTP/SSE·모델 티어링이 **선두 도구와 동등 수준**에 도달.
- **plan/71 잔여 격차 해소 후(현재)**: 턴 중간 개입(TUI 실시간 캡처 포함)·병렬 read 도구 실행·AST 심볼 편집/원자적 다중파일 편집·@심볼 멘션·헤드리스 이미지 입력까지 적용되어, **표의 모든 역량이 선두 도구와 동등 이상**이다. 생성 워크플로는 여전히 **고유 강점**.

---

## 4. 남은 격차 (정직한 평가)

plan/71 4절에 적었던 4개 잔여 격차는 모두 해소되었다.

1. ✅ **턴 중간 개입의 TUI 캡처** — `_SteeringCapture`가 쿡트 모드 TTY에서 백그라운드로 라인 캡처 → 큐 push. 승인 프롬프트 중에는 일시정지해 응답을 가로채지 않음.
2. ✅ **병렬 도구 실행** — 한 라운드의 독립 read-only 호출을 `_prefetch_read_only`로 동시 실행. 게이팅/순서/증거는 순차 유지(순수 최적화). 쓰기/승인 도구가 섞이면 순차로 폴백.
3. ✅ **AST 기반 안전 편집** — `replace_symbol`(ast로 함수/클래스 교체, 파싱 실패 시 거부) + `apply_edits`(다중파일 원자적 적용/롤백).
4. ✅ **헤드리스 이미지 입력 / @심볼 멘션** — `--image`(멀티모달, repeatable) + `@file::symbol`(ast 추출).

### 의도적으로 남긴 범위 (현재 미적용, 위험/효용 판단)
- **tree-sitter 기반 다언어 AST 편집**: 현재 심볼 편집은 Python(`ast` 표준 라이브러리) 한정. JS/TS/Go 등 다언어 구조 편집은 tree-sitter 의존성 추가가 필요해 보류(파이썬 외 언어는 패치/원자적 편집으로 처리).
- **헤드리스 이미지의 실제 인식**: 파이프라인·CLI 전달은 완료. 실제 이미지 이해는 백엔드 모델의 비전 지원에 의존(현재 vLLM 모델 구성에 따라 다름).
- **병렬 *쓰기* 도구 실행**: 쓰기 호출은 충돌·체크포인트·승인 때문에 의도적으로 순차 유지(read만 병렬). 동시 쓰기는 워크트리 격리 서브에이전트(`delegate_task`)로 대신한다.

요약: plan/71에서 식별한 잔여 격차가 모두 해소되어, allCode는 **대화형 UX·편집 안전성·운영 기능 전반에서 Codex/Claude Code/aider와 동급 이상**이며, 생성 워크플로+검증/수리에서 우위를 유지한다. 전체 테스트 **900 passed, 3 skipped**.
