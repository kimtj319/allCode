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
| 턴 중간 개입 / 큐잉 | **부분** — 큐+라운드 경계 주입 완료, TUI 실시간 캡처 보류 | 강 | 강 | 중 |
| 플랜 모드(승인 후 실행) | **강** — `approval.plan_mode` 승인 게이트 | 강 | 중 | — |
| 세션 재개 | **강** — `--continue` / `--resume` | 강 | 강 | 강 |
| 권한 정밀도(경로/명령) | **강** — allow/deny 글롭 규칙(deny 우선) | 강 | 중 | 중 |
| 셸 스트리밍 / 백그라운드 | **강** — `run_command background` + `get_command_output`/`kill_command` | 강 | 강 | — |
| 병렬 도구 / 서브에이전트 | **부분** — 쓰기 가능 위임 서브에이전트 완료, 병렬 도구 실행 보류 | 강 | 중 | — |
| 체크포인트 / rewind | **강** — 턴별 파일 스냅샷 + `/rewind` | 강 | git | 강 |
| 컨텍스트 압축 / 비용 미터 | **강** — `/compact` + `/cost` | 강 | 중 | 중 |
| MCP | **강** — stdio + HTTP/SSE + resources + prompts | 강 | — | — |
| 모델 티어링 | **강** — 2티어(ultra=라우팅·요약·플래너, max=구현) | 보조모델 | — | architect/editor |
| lint / format / typecheck | **중~강** — 옵트인 ruff/mypy/tsc/eslint | 강 | 중 | 강(자동 lint+커밋) |
| AST / 의미 기반 편집 | **부분** — 편집 후 구문 검증, tree-sitter 미적용 | 부분 | 부분 | 중 |
| 헤드리스 / 스크립트 | **중~강** — text / json / stream-json | 강(이미지 포함) | 강 | 중 |
| @-멘션 | **중** — 경로 단위 첨부, 심볼 단위 미적용 | 강 | 중 | 강 |

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
| 17 | @-멘션 | `tui/mentions.py` |

---

## 3. 한 줄 요약

- **이전**: 생성 워크플로+검증/수리라는 고유 강점은 있었으나 대화형 UX(중간 개입·플랜 승인·세션 재개)와 운영 기능(백그라운드 셸·정밀 권한·MCP 전송)에서 격차가 컸다.
- **현재**: 세션 재개·플랜 승인·권한 정밀도·백그라운드 셸·체크포인트·`/compact`·`/cost`·MCP HTTP/SSE·모델 티어링이 **선두 도구와 동등 수준**에 도달했고, 생성 워크플로는 여전히 **고유 강점**이다.

---

## 4. 남은 격차 (정직한 평가)

1. **턴 중간 개입의 TUI 캡처** — 엔진(큐+라운드 주입)은 완성·테스트됐으나, 실행 중 키 입력을 받는 원시 모드 동시 stdin 캡처가 미완. 동작 중인 터미널 입력 처리를 불안정하게 만들 위험으로 보류. (Claude Code/Codex는 완전 지원)
2. **병렬 도구 실행** — 쓰기 서브에이전트는 완료. 한 라운드 내 다중 도구 동시 실행은 라운드 파이프라인의 게이팅/증거/루프가드 상태가 순서 의존적이라 대형 리팩터 필요로 보류. (Claude Code가 가장 앞섬)
3. **AST 기반 안전 편집** — 현재는 편집 후 구문 검증 수준. tree-sitter 기반 심볼 단위 편집·다중파일 원자적 트랜잭션은 미적용.
4. **헤드리스 이미지 입력 / @심볼 멘션** — JSON·스트리밍은 됐으나 이미지 입력, `@file::symbol` 심볼 단위 멘션은 미적용.

요약: **핵심 에이전트 UX·운영 격차는 대부분 해소**되어 Codex/Claude Code/aider와 동급 또는 (생성 워크플로 면에서) 우위에 있다. 남은 것은 주로 **고급/마감 기능**(실시간 개입 UI, 병렬 실행, AST 편집, 멀티모달)이다.
