# 70. 에이전트 하네스 격차 분석 — Codex CLI / Claude Code / aider 대비

> 현재 `allCode` 코드(`src/allCode/`)를 직접 조사해 작성한 기능/로직 격차 분석 및 보강 로드맵.
> 비교 대상: **Codex CLI**, **Claude Code**, **aider**("agy"는 aider로 해석).
> 모든 항목을 적용 예정이며, 본 문서는 그 작업 명세 겸 기준점이다.

---

## 0. 이미 강점인 부분 (비교 기준점)

격차를 논하기 전, allCode가 이미 갖춘(그리고 비교 대상보다 우위인) 항목:

- **구조화된 생성 워크플로**: `plan → skeleton → implementation → tests → validation → repair(최대 5회)` + 완료 검사.
  - `agent/workflow.py`, `agent/project_planner.py`, `agent/task_plan.py`, `agent/validation_runner.py`, `agent/completion_checker.py`
- **이중 라우터 + 안전 게이트**: 규칙 라우터 + LLM 라우터 교차검증, read-only / no-shell / no-network 강제.
  - `agent/router.py`, `agent/model_router.py`, `agent/policy.py`, `agent/loop.py:180-205`(교차검증 가드레일)
- **repo map / source_probe / source_overview**: aider식 심볼 기반 요약.
  - `memory/repo_map.py`, `tools/builtin/`(source_overview, source_probe)
- **MCP(stdio)**: `tools/mcp/`(client/manager/tool)
- **seatbelt 샌드박스**: `tools/builtin/shell_sandbox.py`(macOS workspace-write)
- **pre/post 훅**: `tools/hooks.py`
- **자동 메모리(inbox 승인) + 계층 메모리**: `memory/auto_memory.py`, `memory/inbox.py`, `memory/store.py`, `memory/hierarchy.py`
- **git 자동커밋 + /undo**: `workspace/git_ops.py`
- **패치 견고성**: exact + 공백 유연 폴백 `tools/builtin/file_common.py`(`_apply_flexible_patch`)

이 기반은 탄탄하다. 격차는 주로 **대화형 제어(human-in-the-loop)**, **권한 정밀도**, **실시간/병렬성**에 있다.

---

## Tier 1 — 핵심 에이전트 UX 격차 (최우선)

### 1. 턴 중간 개입(mid-turn steering) / 메시지 큐잉 — 미구현 (기능 추가)
- **현재**: `AgentLoop.run_turn()`이 원자적이라 실행 중 사용자가 추가 지시/정정을 넣을 수 없음. 취소만 가능(`loop.py` CancelledError). 이벤트 버스는 publish 전용.
- **비교**: Codex·Claude Code 모두 실행 중 입력을 큐에 넣거나 즉시 방향 전환 가능. 체감 품질 차이가 가장 큼.
- **보강 방향**: 라운드 경계(`agent/round_runner.py` 루프)에서 입력 큐를 폴링해 다음 라운드 프롬프트에 주입. TUI 컴포저에 "실행 중 입력 → 큐" 경로 연결.

### 2. 플랜 모드(승인 후 실행) — 부분만 (로직 보강)
- **현재**: 계획을 `GenerationWorkflowStarted` 이벤트로 보여주기만 하고 즉시 스켈레톤을 씀(`agent/workflow.py:117`). 일시정지·승인·계획 편집 없음.
- **비교**: Claude Code의 plan mode(계획 제시 → 승인 대기 → 실행).
- **보강 방향**: 계획 이벤트 후 승인 핸들러를 `await`하고, 거부 시 재계획 루프. approval 모드와 연동(플랜 승인 on/off).

### 3. 세션 재개(resume / continue) — 저장은 하나 미사용 (기능 추가)
- **현재**: 트랜스크립트(`memory/session_store.py`)와 상태 스냅샷(`memory/session_state_store.py`)을 매 턴 저장하지만 **다시 불러와 대화를 잇는 경로가 없음**. 매 실행이 새 session_id.
- **비교**: Claude Code(`--continue`/`--resume`), Codex, aider 모두 직전 대화 복원 제공.
- **보강 방향**: `--continue`(마지막 세션)/`--resume`(선택) CLI 플래그 추가, 시작 시 최근 세션 로드 → 컨텍스트/메시지 복원. `main.py`, `runtime.py`, `memory/session_store.py` 연계.

### 4. 권한 정밀도(per-path / per-command allow·deny) — 카테고리 단위뿐 (로직 보강)
- **현재**: 승인은 mutation/shell **카테고리 단위**(`tools/approval.py`)와 정규식 위험패턴만. 경로별/명령별 허용·거부 규칙 없음.
- **비교**: Claude Code는 `Bash(npm run test:*)`, `Read(./src/**)`, deny 규칙 등 세밀한 영속 권한(`settings.json`).
- **보강 방향**: `.allCode/config.yaml`에 allow/deny 글롭 규칙 + 세션 학습("이 명령 항상 허용"). `config/schema.py`(권한 규칙 모델), `tools/approval.py`/`agent/policy.py` 평가 로직.

### 5. 셸 출력 스트리밍 / 백그라운드 프로세스 — 버퍼링·차단 (기능 추가)
- **현재**: `run_command`가 완료까지 출력을 버퍼링(`tools/builtin/shell.py`), 실시간 표시 없음. `&`(백그라운드)는 위험패턴으로 차단 → 개발 서버 띄우고 상호작용 불가.
- **비교**: Claude Code의 백그라운드 Bash + 실시간 출력 + Kill.
- **보강 방향**: 라인 스트리밍 콜백 + 백그라운드 잡 핸들 + 출력 폴링/종료 도구(BashOutput/Kill 유사).

---

## Tier 2 — 역량 깊이 격차

### 6. 병렬 도구 실행 / 병렬·쓰기 가능 서브에이전트 — 순차·읽기전용 (로직 보강)
- **현재**: 도구 호출 순차, 서브에이전트(`tools/builtin/task.py`)는 깊이1·읽기전용·직렬.
- **비교**: Claude Code는 병렬 Task + 병렬 tool-call.
- **보강 방향**: 독립 read 도구의 병렬 실행, 쓰기 가능한 위임 서브에이전트(격리 워크스페이스/워크트리).

### 7. 체크포인트 / 되돌리기(rewind) — git 전체커밋 undo만 (기능 추가)
- **현재**: 파일·편집 단위 스냅샷/롤백 없음, `auto_commit` 기본 off(`workspace/git_ops.py`).
- **비교**: Claude Code rewind, aider 변경마다 커밋+`/undo`.
- **보강 방향**: 도구 실행 전 파일 스냅샷(또는 자동 마이크로 커밋) + `/rewind`.

### 8. 컨텍스트 압축 명령 + 토큰/비용 미터 — 자동 1회뿐 (로직 보강)
- **현재**: 압축은 전송 직전 휴리스틱 1회(`agent/context_condensation.py`, 32k 한도). 사용자 `/compact`나 세션 중 자동 재압축·연속 없음. 푸터에 컨텍스트 토큰 표시는 있으나 누적 비용($)·세션 사용량 미터 없음.
- **비교**: Claude Code `/compact`·`/cost`.
- **보강 방향**: `/compact` 명령, 임계치 도달 시 자동 요약+계속, 비용 추정 표시.

### 9. MCP 완성도 — stdio·tools만 (기능 추가)
- **현재**: HTTP/SSE 전송 없음, MCP resources/prompts/sampling 미지원(`tools/mcp/`).
- **비교**: Claude Code는 stdio+SSE+HTTP+resources+prompts.
- **보강 방향**: HTTP/SSE 전송, resources(파일/문서 컨텍스트), prompts(서버 제공 슬래시 명령).

### 10. 모델 티어링(빠른/똑똑한 분리) — 단일 모델 (로직 보강) ★구체 배정 확정
- **현재**: planner / editor / router / 요약이 전부 같은 단일 모델(`config/schema.py`의 단일 `ModelConfig`).
- **확정 배정** (이번 분석 반영):
  - **라우팅 / 요약(컨텍스트 압축) / 플래너용 모델 = `wisenut/wise-lloa-ultra-v1.1.0`** (현재 사용 중인 모델을 그대로 사용)
  - **구현용 고성능 모델 = `wisenut/wise-lloa-max-v1.2.1`** (코드 생성·편집·수리 단계에 사용)
- **적용 지점(예정)**:
  - `config/schema.py`: 역할별 모델을 지정할 수 있도록 모델 설정 확장(예: `model`(기본/경량) + `implementation_model`(고성능) 또는 역할→모델 매핑).
  - 라우터(`agent/router.py`/`agent/model_router.py`), 컨텍스트 요약(`agent/context_condensation.py`), 플래너(`agent/project_planner.py`) → `ultra-v1.1.0`.
  - 구현/편집(`agent/workflow_editor.py`의 `generate_file`/`repair_files`) → `max-v1.2.1`.
  - 미설정 시 기본값은 현재 단일 모델로 폴백(하위 호환).
- **기대 효과**: 라우팅/요약/계획은 가볍고 빠른 모델로 비용·지연 절감, 실제 코드 구현은 고성능 모델로 품질 확보.

---

## Tier 3 — 견고성·완성도

| # | 격차 | 현재 | 보강 방향 |
|---|---|---|---|
| 11 | AST/의미 기반 편집 | exact+공백유연 패치(`tools/builtin/file_common.py`) | tree-sitter 기반 안전 편집, 다중파일 원자적 트랜잭션+충돌감지 |
| 12 | lint/format/typecheck 검증 | `run_tests`만 1급 | ruff/eslint/mypy/tsc를 검증·자동수정 단계로 편입 |
| 13 | 헤드리스 강화 | 최종 결과만 출력(`headless.py`), 이미지/스트리밍/JSON 없음 | `--output-format json`, 스트리밍, 이미지 입력 |
| 14 | 시작 인덱싱 비용 | 매 실행 ~1800파일 읽기+해시(`workspace/indexer.py`) | 지연/백그라운드 인덱싱, 해시 캐시 영속화, 스크래치 디렉터리 ignore |
| 15 | 변경 리뷰 뷰 | 승인 시 diff만(`tools/executor.py`) | 턴 종료 후 누적 git diff 리뷰, 파일별 수락/되돌리기 |
| 16 | 지시문 처리 | AGENTS.md 6000자 절단(`memory/store.py`) | 절단 대신 요약, 계층 캐싱 |
| 17 | @-멘션 정밀도 | 경로 문자열 완성만(`tui/terminal_completion.py`) | 심볼 단위(`@file::symbol`), AST 인지 |

---

## 한 줄 요약 비교

| 역량 | allCode | Claude Code | Codex CLI | aider |
|---|---|---|---|---|
| 생성 워크플로+검증/수리 | 강(고유) | 약 | 중 | 중 |
| 턴 중간 개입/큐잉 | ✗ | 강 | 강 | 중 |
| 플랜 모드(승인) | 부분 | 강 | 중 | — |
| 세션 재개 | 저장만 | 강 | 강 | 강 |
| 권한 정밀도(경로/명령) | 카테고리 | 강 | 중 | 중 |
| 셸 스트리밍/백그라운드 | ✗ | 강 | 강 | — |
| 병렬 도구/서브에이전트 | ✗ | 강 | 중 | — |
| 체크포인트/rewind | git만 | 강 | git | 강 |
| MCP | stdio/tools | stdio+SSE+HTTP+res/prompts | — | — |
| 모델 티어링 | 단일→2티어(예정) | 보조모델 | — | architect/editor |

---

## 권고 우선순위 (적은 노력 대비 큰 체감 개선)

1. **세션 재개(`--continue`/`--resume`)** — 저장 인프라가 이미 있어 로드 경로만 추가하면 됨. 노력 대비 효과 최고.
2. **턴 중간 개입 + 플랜 승인** — 대화형 에이전트 체감의 핵심.
3. **권한 정밀도(allow/deny 규칙)** — auto 모드 안전성과 신뢰 향상.
4. **셸 출력 스트리밍 + 백그라운드 잡** — 실제 개발 워크플로(서버/빌드) 지원.
5. **모델 티어링(#10)** — 위 확정 배정대로 적용(라우팅/요약/플래너=ultra-v1.1.0, 구현=max-v1.2.1).

---

## 적용 시 영향 파일 요약 (착수용 인덱스)

- 대화형 제어: `agent/loop.py`, `agent/round_runner.py`, `core/event_bus.py`, `tui/terminal.py`, `tui/terminal_input.py`
- 플랜 승인: `agent/workflow.py`, `tui/terminal.py`(승인 핸들러)
- 세션 재개: `main.py`, `runtime.py`, `memory/session_store.py`, `memory/session_state_store.py`
- 권한 정밀도: `config/schema.py`, `tools/approval.py`, `agent/policy.py`, `tools/executor.py`
- 셸 스트리밍/백그라운드: `tools/builtin/shell.py`, `tools/builtin/`(신규 출력/종료 도구), `tui` 렌더
- 모델 티어링: `config/schema.py`, `llm/factory.py`, `agent/project_planner.py`, `agent/workflow_editor.py`, `agent/context_condensation.py`, `agent/model_router.py`
- 체크포인트: `workspace/git_ops.py`, `tools/executor.py`, `tui/slash_commands.py`
- 컨텍스트/`/compact`/비용: `agent/context_condensation.py`, `tui/slash_commands.py`, `tui/terminal.py`(미터)
- MCP 확장: `tools/mcp/`
- Tier3: `tools/builtin/file_common.py`, `agent/validation_runner.py`, `headless.py`, `workspace/indexer.py`, `memory/store.py`, `tui/terminal_completion.py`

---

## 구현 진척 (이 플랜 기준)

| # | 항목 | 상태 | 핵심 변경 |
|---|---|---|---|
| 3 | 세션 재개 | ✅ 완료 | `--continue`/`--resume`, `memory/conversation_store.py`, `runtime.seed_resumed_session` |
| 4 | 권한 정밀도 | ✅ 완료 | `tools/permission_rules.py`(allow/deny, deny 우선), `approval`·`config.approval` 연동 |
| 7 | 체크포인트/rewind | ✅ 완료 | `workspace/checkpoint_store.py`, 턴별 스냅샷, `/rewind` |
| 8 | /compact + 비용 미터 | ✅ 완료 | `context.compact_session`, `/compact`·`/cost`, 세션 토큰 누적 |
| 10 | 모델 티어링 | ✅ 완료 | `implementation_model_name`(=max-v1.2.1), 라우팅/요약/플래너=ultra-v1.1.0 |
| 11 | AST 인지 편집 | ✅ 완료(경량) | `file_common.syntax_warning`: write/patch 후 `.py`/`.json` 파싱→오류 즉시 피드백 |
| 12 | lint/typecheck 검증 | ✅ 완료 | `agent/validation_lint.py`: 프로젝트가 옵트인한 ruff/mypy/tsc/eslint를 테스트 전에 실행 |
| 13 | 헤드리스 강화 | ✅ 완료(JSON/스트림) | `--output-format text\|json\|stream-json`. 이미지 입력은 향후 |
| 14 | 시작 인덱싱 비용 | ✅ 완료 | `indexer` 디스크 해시 캐시(`.allCode/index_cache.json`), 미변경 파일 재해시 생략 |
| 15 | 변경 리뷰 뷰 | ✅ 완료(diff) | `/review`(=`/diff`) → `git_ops.working_tree_diff` |
| 16 | 지시문 처리 | ✅ 완료 | `store._condense_instruction_text`: 절단 대신 head+tail 요약 |
| 17 | @-멘션 | ✅ 완료 | `tui/mentions.py`: `@경로` 파일/디렉터리 내용을 턴 컨텍스트로 첨부 |
| 1 | 턴 중간 개입 | ✅ 핵심 완료 | `agent/steering.py` SteeringQueue, RoundRunner가 라운드 경계마다 drain→사용자 메시지 주입. 런타임까지 배선·테스트 완료. TUI 실시간 키 입력 캡처(원시 모드 동시 stdin)는 잔여 통합으로 보류 |
| 2 | 플랜 승인 | ✅ 완료 | `approval.plan_mode`, GenerationWorkflow가 계획 제시 후 승인 게이트 대기(거부 시 cancelled, 파일 미작성) |
| 5 | 셸 스트리밍/백그라운드 | ✅ 완료 | `run_command background=true` + `get_command_output`/`kill_command`, `background_jobs.py`(Popen+스레드) |
| 6 | 병렬 도구/서브에이전트 | ✅ 부분 | 쓰기 가능 위임 서브에이전트 `delegate_task` 완료. 병렬 도구 실행은 라운드 파이프라인의 게이팅/증거 상태가 순서 의존적이라 대형 리팩터 필요로 보류 |
| 9 | MCP HTTP/SSE + resources/prompts | ✅ 완료 | `http_client.MCPHttpClient`(Streamable HTTP/SSE), resources/read 도구, prompts 노출, transport 설정 |

**최종 상태**: 17개 보강 항목 전부 적용. #1(TUI 실시간 캡처)과 #6(병렬 도구 실행)은 핵심 메커니즘을 구현·테스트했고, 안전상 잔여 통합/리팩터를 명시적으로 보류함. 전체 테스트 882 passed, 3 skipped.
