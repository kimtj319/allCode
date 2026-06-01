# 00. allCode Master Implementation Guide

## 구현 전 필수 보강 지시

- 모든 모듈은 실행 및 테스트 가능한 완전한 코드로 작성한다. 임의의 `pass`, `TODO`, `...`, `구현 예정` 문구로 핵심 구현을 생략하지 않는다.
- 전체 구현은 `12_mvp_execution_plan.md`의 마일스톤 순서를 따른다. 한 번에 모든 코드를 생성하더라도 내부적으로는 Alignment -> Config -> Core -> Mock Loop -> Real LLM -> Tool/Workspace -> Memory -> TUI 순서로 체크포인트를 통과해야 한다.
- 파일 분리는 줄 수만 기준으로 하지 않는다. 단일 책임, 높은 응집도, 단방향 의존성, 순환 import 방지를 함께 만족해야 한다.
- `00`~`12`는 기본 구현 대상 문서이고, `15`는 Codex 수준 TUI 보강 구현 문서다. `13`~`14`는 검토 이력 부록이다. 구현 중 판단이 충돌하면 부록보다 `00`~`12`, `15`의 최신 계약을 우선한다.

## GPT-5.5 전달 순서

GPT-5.5에게 구현을 맡길 때는 아래 순서대로 문서를 전달한다. 전체를 한 번에 전달하더라도 모델은 이 순서를 내부 실행 순서로 사용해야 한다.

| 순서 | 문서 | 역할 |
|---:|---|---|
| 00 | `00_master_implementation_guide.md` | 전체 목표, 제외 범위, 최상위 구조 |
| 01 | `01_open_source_alignment_contracts.md` | 공개 에이전트 참조 기반 설계 계약 |
| 02 | `02_config_entrypoint_plan.md` | 설정, secret, CLI entrypoint |
| 03 | `03_core_contracts_plan.md` | provider/UI 독립 core 모델과 이벤트 |
| 04 | `04_llm_loop_plan.md` | LLM stream, tool call, recovery loop |
| 05 | `05_routing_policy_plan.md` | intent routing, policy, prompt builder |
| 06 | `06_tool_system_plan.md` | tool registry, executor, approval, transaction |
| 07 | `07_workspace_context_plan.md` | workspace root, path policy, repo index |
| 08 | `08_context_memory_plan.md` | repo map, hierarchical memory, recent targets |
| 09 | `09_generation_workflow_plan.md` | 신규/수정 프로젝트 생성 workflow |
| 10 | `10_tui_app_plan.md` | Textual 기반 TUI와 event rendering |
| 11 | `11_quality_testing_plan.md` | 품질 점수, 회귀, TTY 검증 |
| 12 | `12_mvp_execution_plan.md` | 마일스톤, suspend/resume, 완료 기준 |
| 13 | `13_agy_review_feedback.md` | 참고 부록: 1차 검토 이력 |
| 14 | `14_agy_review_round2_feedback.md` | 참고 부록: 2차 검토 이력 |
| 15 | `15_codex_tui_alignment_plan.md` | Codex 수준 persistent composer, cell transcript, streaming markdown 보강 |

## GPT-5.5 구현 요청 방식

권장 요청은 한 번에 전체 구현을 맡기는 방식이 아니라 `12_mvp_execution_plan.md`의 5회 분할이다.

1. 요청 1: `00`, `01`, `02`, `03`, `04`를 기준으로 Config, Core, Fake LLM Loop까지 구현한다.
2. 요청 2: `05`, `06`을 기준으로 Routing, Policy, Tool System, Approval을 구현한다.
3. 요청 3: `07`, `08`을 기준으로 Workspace Index, Repo Map, Context Memory를 구현한다.
4. 요청 4: `09`를 기준으로 Project Generation Workflow와 validation/repair loop를 구현한다.
5. 요청 5: `10`, `11`, `12`, `15`를 기준으로 TUI, quality test, Codex 수준 persistent composer, end-to-end 검증을 구현한다.

각 요청의 완료 조건:

- 생성/수정 파일 목록을 보고한다.
- 해당 단계의 unit/integration test를 실행한다.
- 실패 시 로그를 읽고 수정한 뒤 재검증한다.
- 실제 파일 변경 또는 검증 근거 없이 “완료”라고 답하지 않는다.


## 목표

`03_allCode`는 기존 OneCLI의 all_rounder 철학을 유지하되, 기존 코드의 과도한 책임 집중과 UI 누적 구조를 반복하지 않는 다음 버전 코딩 에이전트 프로젝트로 설계한다.

핵심 목표는 다음 세 가지다.

- 모델 루프 구조를 작고 명확한 코어로 분리한다.
- 사용자 프롬프트 입력 후 라우팅, 정책, 도구 사용 판단이 자연스럽게 이어지도록 한다.
- UI는 Kimi Code CLI처럼 전용 TUI 앱으로 설계하여 입력창, 출력, 승인, diff, 상태 표시가 한 화면 모델에서 안정적으로 동작하게 한다.

## OneCLI에서 가져갈 것

- all_rounder의 기본 동작 원칙: 모델이 스스로 판단하고 필요한 도구를 호출한다.
- ToolRegistry 개념: 도구 schema, 실행, 권한 요청을 명시적 계약으로 관리한다.
- 빈 응답, tool-call-only, length cutoff, 반복 도구 호출에 대한 복구 개념.
- 최근 작업 대상 기억, 컨텍스트 압축, 작업 완료 근거 작성 개념.
- 파일 변경 전 승인, diff 미리보기, 검증 실행 후 최종 요약 흐름.

## OneCLI에서 그대로 가져오지 않을 것

- `query_engine.py` 전체 구조.
- `cli.py` 중심의 입력, 명령, UI, 작업 제어 혼합 구조.
- 특정 테스트 프롬프트 또는 특정 프로젝트를 겨냥한 generation profile 하드코딩.
- read-only 분석을 특정 파일명/패키지명에 과하게 맞춘 규칙 묶음.
- UI와 agent loop가 서로 내부 상태를 직접 참조하는 구조.

## 권장 최상위 구조

```text
03_allCode/
  pyproject.toml
  README.md
  src/allCode/
    core/
    llm/
    agent/
    tools/
    workspace/
    tui/
    config/
    telemetry/
  tests/
    unit/
    integration/
    tty/
  docs/
  plan/
```

## 프로젝트 빌드 및 의존성 사양

GPT-5.5에게 전체 구현을 요청할 때 프로젝트의 패키징과 의존성을 임의로 해석하게 두지 않는다. 최초 스켈레톤 단계에서 아래 계약을 기준으로 `pyproject.toml`을 작성한다.

```toml
[project]
name = "allCode"
version = "0.1.0"
description = "A lightweight all-rounder coding agent with a dedicated TUI."
requires-python = ">=3.11"
dependencies = [
  "pydantic>=2.5.0,<3.0.0",
  "textual>=0.50.0",
  "rich>=13.7.0",
  "openai>=1.10.0",
  "httpx>=0.26.0",
  "pyyaml>=6.0.1",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0.0",
  "pytest-asyncio>=0.23.0",
  "pytest-mock>=3.12.0",
]

[project.scripts]
ac = "allCode.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

## 전역 설정 계약

설정 계층은 MVP 초기에 구현한다. LLM adapter와 TUI가 각자 설정 파일을 직접 읽지 않도록 `config/manager.py`에서 단일 진입점을 제공한다.

- 기본 설정 파일: `~/.config/allCode/config.yaml`
- 환경변수 override: `ALLCODE_MODEL`, `ALLCODE_BASE_URL`, `ALLCODE_API_KEY`, `ALLCODE_WORKSPACE`
- 필수 필드: `model_name`, `base_url`, `api_key_env`, `workspace_root`, `sandbox_enabled`, `approval_mode`
- 비밀값은 설정 파일에 평문 저장하지 않고 환경변수명을 저장한다.

## OneCLI 참조 패턴 매핑

기존 OneCLI 코드를 그대로 복사하지 않는다. 다음 개념만 재설계해 가져온다.

| 가져올 개념 | OneCLI 기준 위치 | allCode 반영 방식 |
|---|---|---|
| ToolRegistry | `src/onecli/tool_registry.py` | `tools/registry.py`에서 schema 생성과 tool lookup만 담당 |
| ToolResult/Error 구조 | `src/onecli/tools/base.py` | `core/models.py`의 Pydantic 모델로 단일화 |
| 반복 도구 호출 감지 | `src/onecli/loop_detection.py` | `agent/recovery.py`의 sliding-window hash guard로 재작성 |
| workspace path policy | `src/onecli/runtime/path_policy.py` | `workspace/path_resolver.py`와 `tools/approval.py`에서 root 하위 쓰기만 허용 |
| context 압축 | `src/onecli/orchestrator/context_budget.py` | `agent/context.py`의 skeleton-only context로 재작성 |
| phase 기반 진행 | `src/onecli/orchestrator/*phase*` | `core/events.py`의 단계 이벤트로 치환 |

## Context Memory 설계 방향

allCode의 context memory는 `plan/08_context_memory_plan.md`를 따른다.

- Aider식 repo map으로 대형 코드베이스의 symbol/signature를 compact하게 제공한다.
- Gemini CLI식 hierarchical memory로 global/project/directory/session 규칙을 병합한다.
- 최근 target memory로 후속 질문의 “그 파일”, “해당 함수”를 해석한다.
- 세션 transcript와 summary를 저장해 재시작 후에도 맥락을 복원한다.
- auto-memory는 후보를 inbox에만 저장하고, 사용자 승인 전에는 active memory에 반영하지 않는다.
- secret/API key/token은 memory 저장 대상에서 제외한다.

## 설계 원칙

1. Agent loop는 UI를 모른다.
2. TUI는 agent 내부 구현을 모르고 이벤트만 렌더링한다.
3. Router는 실행하지 않고 요청 종류와 처리 전략만 결정한다.
4. ToolPolicy는 도구 허용 여부만 판단한다.
5. ToolExecutor는 정책 통과 후 도구를 실행하고 결과를 표준 이벤트로 반환한다.
6. ContextManager는 메모리와 압축을 담당하되 모델 호출을 직접 수행하지 않는다.
7. 각 파일은 하나의 책임만 가진다.
8. 하나의 파일이 300줄을 넘기기 시작하면 분리 후보로 등록하고, 500줄을 넘기기 전에 반드시 분리한다.

## 대규모 프로젝트 코드 생성 절차

신규 프로젝트 구현은 항상 다음 순서를 따른다.

1. 스켈레톤 작성: 디렉터리, 패키지, 빈 인터페이스, 기본 테스트를 먼저 만든다.
2. 계약 정의: dataclass, Protocol, 이벤트 타입, 오류 타입을 먼저 확정한다.
3. 핵심 함수 설계: 각 모듈의 public API를 1차로 설계하고 테스트에서 호출한다.
4. 모듈별 구현: core -> llm -> tools -> agent -> workspace -> tui 순서로 구현한다.
5. 연동 테스트: 모델 호출 없이 fake LLM과 fake tool로 루프를 검증한다.
6. 실제 모델 테스트: OpenAI-compatible 또는 로컬 HTTP 모델로 작은 요청을 실행한다.
7. TUI 테스트: non-headless TTY 환경에서 입력, slash command, tool output, final answer를 확인한다.
8. 회귀 정리: 실패 케이스를 테스트로 고정하고 수정한다.

## 문서 목록

- `01_open_source_alignment_contracts.md`: 공개 CLI 에이전트 참조 기반 모호성 제거 계약.
- `02_config_entrypoint_plan.md`: 설정, 의존성, 진입점.
- `03_core_contracts_plan.md`: 핵심 데이터 계약과 이벤트 모델.
- `04_llm_loop_plan.md`: 모델 호출, 스트림 처리, 루프 복구.
- `05_routing_policy_plan.md`: 사용자 요청 라우팅과 도구 정책.
- `06_tool_system_plan.md`: 도구 레지스트리, 실행기, 승인 시스템.
- `07_workspace_context_plan.md`: 작업공간 인덱싱, 경로 해석, 컨텍스트 압축.
- `08_context_memory_plan.md`: context memory, repo map, session summary, recent target, auto-memory.
- `09_generation_workflow_plan.md`: 대규모 프로젝트 생성/수정 워크플로우.
- `10_tui_app_plan.md`: Kimi Code CLI 스타일 TUI 설계.
- `11_quality_testing_plan.md`: 품질 검증, TTY 테스트, 회귀 체계.
- `12_mvp_execution_plan.md`: MVP 범위, 마일스톤, 중단/재개 규칙.
- `13_agy_review_feedback.md`: agy 검토 피드백 반영 기록.
- `14_agy_review_round2_feedback.md`: agy 2차 토론 및 review 반영 기록.
- `15_codex_tui_alignment_plan.md`: 실제 Codex CLI 소스와 TTY 관찰 결과를 반영한 persistent composer, cell transcript, streaming markdown 보강 계획.

## 공개 오픈소스 참조 기반 보강 계약

GPT-5.5가 구현 중 판단이 애매한 경우 `01_open_source_alignment_contracts.md`의 계약을 우선 적용한다.

- Aider식 repo map 원칙을 적용해 대형 코드베이스는 symbol/signature 중심으로 이해한다.
- Gemini CLI식 hierarchical memory를 적용해 global/project/directory/session 맥락을 명확히 병합한다.
- OpenHands식 event/action 관찰성을 적용해 모델 판단, 도구 실행, 검증, 복구를 event로 남긴다.
- Qwen Code식 provider-neutral terminal agent 원칙을 적용해 core가 특정 model SDK에 묶이지 않게 한다.
- MVP 범위는 `core`, `llm`, `agent`, `tools`, `workspace`, `memory`, `tui`, `config`, `tests`로 제한한다.
