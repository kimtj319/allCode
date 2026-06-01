# 01. Open Source Agent Alignment Contracts

## 목적

`00`~`12` 구현 계획서를 GPT-5.5가 실제 구현할 때 모호하게 해석할 수 있는 부분을 닫는다. 이 문서는 공개적으로 많이 쓰이는 CLI/코딩 에이전트의 설계 방향을 참고해 allCode에 맞는 구체 계약으로 변환한다. `13`~`14`는 검토 이력 부록이므로 구현 계약 충돌 시 `00`~`12`를 우선한다.

## 참고한 오픈소스 에이전트

참고 링크:

- Aider repo map: https://aider.chat/docs/repomap.html
- Gemini CLI hierarchical context: https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- Gemini CLI auto-memory: https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/auto-memory.md
- Qwen Code: https://github.com/QwenLM/qwen-code
- OpenHands: https://github.com/All-Hands-AI/OpenHands

### Aider

참고 포인트:

- 터미널 기반 AI pair programming.
- 전체 코드베이스를 repo map으로 요약해 큰 프로젝트에서 모델이 방향을 잃지 않게 함.
- git-native workflow와 자동 lint/test/fix 흐름을 강조.

allCode 반영:

- `memory/repo_map.py`, `workspace/indexer.py`, `agent/context.py`는 파일 본문 전체 대신 symbol/signature 중심의 context를 우선한다.
- 파일 변경 후 검증 명령을 실행하고 실패 시 수리 루프를 돌린다.
- 추후 git integration을 확장하더라도 MVP에서는 edit transaction snapshot으로 대체한다.

### Gemini CLI

참고 포인트:

- `GEMINI.md` 계층형 context.
- `/memory show`, `/memory refresh`, `/memory add`.
- auto-memory는 transcript를 분석해 후보를 만들고, 승인 전에는 적용하지 않음.

allCode 반영:

- `ALLCODE.md` 기반 hierarchical memory.
- `/memory` slash command.
- auto-memory inbox와 승인 기반 적용.
- memory import와 refresh는 후속 확장으로 두되, 문서 구조는 이를 수용한다.

### Qwen Code

참고 포인트:

- terminal-first coding agent.
- open-source CLI agent로 model provider flexibility와 function calling protocol을 중시.

allCode 반영:

- LLM adapter는 OpenAI-compatible을 MVP 기본으로 하되 provider SDK에 core를 결합하지 않는다.
- response parser와 tool call schema를 provider 중립 모델로 표준화한다.

### OpenHands

참고 포인트:

- production-oriented software engineering agent scaffold.
- sandbox, action/event, tool execution, evaluation workflow가 중요.

allCode 반영:

- `core/events.py`를 중심으로 모든 agent action을 event로 표준화한다.
- destructive tool은 approval과 path policy를 통과해야 한다.
- tool execution, validation, recovery를 관찰 가능한 event stream으로 남긴다.

## 공통 구현 원칙

1. 모델에게 자유도를 주되, 위험한 실행은 policy와 approval이 제어한다.
2. 코드베이스 이해는 full-file dump가 아니라 repo map, symbol map, recent target, active file 조합으로 처리한다.
3. memory는 명시적이고 검토 가능해야 한다. 자동 추출 결과는 바로 적용하지 않는다.
4. tool call schema는 provider 독립 구조로 표준화한다.
5. UI는 agent state를 직접 읽지 않고 event stream만 구독한다.
6. 검증 가능한 완료 조건 없이 final answer를 반환하지 않는다.

## 00 계획 보강: 프로젝트 경계와 제외 범위

모호점:

- MVP와 확장 기능의 경계가 커질 수 있다.
- “상용급”이라는 표현이 범위를 무한히 늘릴 수 있다.

보강 계약:

- MVP는 `core`, `llm`, `agent`, `tools`, `workspace`, `memory`, `tui`, `config`, `tests`까지만 포함한다.
- git auto commit, plugin marketplace, MCP server manager, multi-agent swarm, cloud sandbox는 MVP 제외다.
- 확장 후보는 `docs/future_work.md`에만 기록하고 MVP 구현 중에는 만들지 않는다.

## 03 계획 보강: Core 모델 엄격성

모호점:

- Pydantic 모델이 provider raw payload를 담기 시작하면 core가 오염된다.
- metadata를 만능 필드로 쓰면 타입 안정성이 무너진다.

보강 계약:

- 모든 core model은 `model_config = ConfigDict(extra="forbid")`를 기본으로 한다.
- provider raw payload는 `llm/adapters/*` 안에서만 다룬다.
- `metadata`에는 직렬화 가능한 primitive/list/dict만 허용한다.
- `ToolResult`는 core의 단일 모델만 사용하고 tools 계층에서 별도 동명 모델을 만들지 않는다.

## 04 계획 보강: LLM loop와 response parser

모호점:

- `ModelEvent`의 종류가 불명확하면 loop와 TUI가 서로 다르게 해석한다.
- 빈 응답 재시도와 final answer 강제 조건이 구현마다 달라질 수 있다.

보강 계약:

`ModelEvent`는 최소 아래 종류를 가진다.

```text
text_delta
tool_call_delta
tool_call_completed
response_completed
response_failed
usage
```

루프 규칙:

- `empty_response`는 성공이 아니다. 축약 프롬프트로 1회 재요청한다.
- `reasoning_only`는 사용자에게 직접 출력하지 않고 final answer 요청으로 전환한다.
- `tool_call_completed`가 있으면 텍스트가 없어도 tool execution phase로 간다.
- 같은 tool hash 반복 3회는 recovery로 전환한다.

## 05 계획 보강: Routing confidence threshold

모호점:

- static rule과 LLM router 중 무엇이 우선인지 애매하다.
- read-only 금지 조건과 modify 동사가 충돌할 때 처리 기준이 부족하다.

보강 계약:

```text
confidence >= 0.80: static decision 사용
0.45 <= confidence < 0.80: LLM router 보조 사용
confidence < 0.45: clarification 또는 safe inspect
```

충돌 우선순위:

1. 안전/금지 조건: read-only, no shell, no external network
2. 명시 target path
3. 사용자 작업 동사
4. 후속 질문 context
5. 기본 answer

## 06 계획 보강: Tool schema와 transaction

모호점:

- 파일 write/patch가 실패했을 때 rollback 기준이 약하다.
- shell 실행 결과를 어디까지 보존할지 애매하다.

보강 계약:

- 모든 file mutation은 `EditTransaction` 안에서 실행한다.
- transaction은 `before_hash`, `after_hash`, `diff`, `rollback_payload`를 가진다.
- tool stdout/stderr는 화면용 truncate와 artifact용 full log를 분리한다.
- destructive shell은 approval 없이는 실행하지 않는다.
- `run_tests`는 일반 shell command가 아니라 validation event를 발행한다.

## 07 계획 보강: Workspace index limits

모호점:

- 대형 repo에서 파일 수/크기 제한이 없다.
- binary/generated/vendor 파일 처리 기준이 부족하다.

보강 계약:

- 기본 index 최대 파일 수: 20,000
- 기본 파일 본문 읽기 최대 크기: 256KB
- repo map 대상 파일 최대 크기: 512KB
- `node_modules`, `.git`, `.venv`, `dist`, `build`, `target`, `__pycache__`는 기본 제외
- binary 파일은 content read 대상에서 제외하고 metadata만 기록
- index cache는 path, mtime, size hash로 invalidation한다.

## 10 계획 보강: TUI contract

모호점:

- TUI가 모든 event를 다 그리면 노이즈가 많아진다.
- worker 실패 시 입력창 복구가 누락될 수 있다.

보강 계약:

- TUI는 event severity를 기준으로 렌더링한다.
  - `user_visible`: transcript 출력
  - `status_only`: status bar만 갱신
  - `debug_only`: debug log만 기록
- input box는 worker start/finish/fail/cancel 이후 항상 enabled 상태를 복원한다.
- slash command palette는 command registry에서만 후보를 가져온다.
- long output은 foldable panel로 렌더링하고 full content는 artifact로 연결한다.

## 09 계획 보강: Generation workflow

모호점:

- workflow와 loop의 책임 경계가 흐려질 수 있다.
- 언어별 scaffold가 하드코딩될 수 있다.

보강 계약:

- workflow는 `ProjectPlan`과 `GenerationStep`만 관리한다.
- 실제 파일 생성은 tool executor를 통해서만 수행한다.
- 언어별 기본값은 `generation/strategies/*.py`로 분리한다.
- strategy는 Python, Node/TypeScript, Go, Rust, Java MVP만 제공한다.
- 알 수 없는 언어는 generic file plan으로 처리하고 임의 dependency를 설치하지 않는다.

## 11 계획 보강: Quality scoring

모호점:

- 테스트 통과만으로 답변 품질을 충분히 보장하지 못한다.

보강 계약:

품질 점수는 100점 만점으로 계산한다.

```text
functional_success: 35
tool_appropriateness: 20
context_continuity: 15
self_healing: 10
final_answer_grounding: 10
ui_signal_clarity: 5
safety_compliance: 5
```

85점 이상이면 pass, 70~84점은 warning, 70점 미만은 fail이다.

## 12 계획 보강: 실행 요청 구조

모호점:

- Context Memory가 독립 마일스톤으로 추가되면서 이전 분할 요청 방식이 불완전해졌다.

보강 계약:

권장 분할은 5회다.

1. Milestone 1 + 2
2. Milestone 3 + 4
3. Milestone 5 + 6
4. Milestone 7
5. Milestone 8 + 9 + 10

## 02 계획 보강: Config precedence

모호점:

- CLI flag, env, config.yaml 우선순위가 구현자마다 달라질 수 있다.

보강 계약:

설정 우선순위는 아래 순서다.

```text
CLI flag > environment variable > project config > user config > defaults
```

민감정보:

- API key 값은 config file에 저장하지 않는다.
- config에는 env var name만 저장한다.
- debug log에는 secret redacted value만 기록한다.

## 08 계획과의 연결: Context memory

Context memory는 Milestone 7로 실행한다. `07_workspace_context_plan.md`의 workspace index와 `08_context_memory_plan.md`의 memory selector는 다음 경계를 지킨다.

- workspace는 파일과 symbol 후보를 제공한다.
- memory는 이번 turn에 넣을 context를 선택한다.
- compactor는 token budget에 맞게 줄인다.
- prompt_builder는 이미 압축된 context bundle만 받는다.

## GPT-5.5 구현 지시 추가 문구

전체 구현 요청 또는 단계별 요청의 맨 위에 아래 문구를 추가한다.

```text
구현 중 설계가 모호하면 임의로 기능을 확장하지 말고 plan/01_open_source_alignment_contracts.md의 계약을 우선 적용하라. Aider식 repo map, Gemini CLI식 hierarchical memory, OpenHands식 event/action 관찰성, Qwen Code식 provider-neutral terminal agent 원칙을 allCode 구조에 맞게 반영하라.
```
