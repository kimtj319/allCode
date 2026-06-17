# src 폴더 코드 역할 및 루프 구조 분석

## 1. 패키지별 역할 요약 (`src/allCode`)

`src/allCode` 디렉터리는 에이전트의 기능을 모듈화하여 유지보수성과 확장성을 높인 구조로 설계되어 있습니다.

| 패키지 | 주요 역할 | 핵심 구성 요소 |
| :--- | :--- | :--- |
| **`core`** | 시스템 전반의 표준 데이터 모델 및 이벤트 정의 | `model.py`, `event.py`, `result.py` |
| **`llm`** | LLM 통신 추상화 및 어댑터 (OpenAI 호환 및 Fake LLM) | `client.py`, `adapters/`, `fake.py` |
| **`agent`** | **에이전트의 두뇌**. 라우팅, 정책, 루프 제어, 컨텍스트 생성 | `loop.py`, `router.py`, `policy.py`, `context_builder.py` |
| **`tools`** | 도구 정의, 레지스트리, 실행 및 승인 로직 | `base.py`, `registry.py`, `executor.py`, `approval.py` |
| **`workspace`** | 파일 시스템 관리, 경로 해석, 코드 인덱싱 및 심볼 추출 | `workspace.py`, `indexer.py` |
| **`memory`** | 세션 요약, 최근 타깃 관리, 계층적 메모리 저장소 | `store.py`, `session.py`, `selector.py` |
| **`generation`** | 프로젝트 생성 전략 및 코드 생성 워크플로우 조정 | `strategies/`, `workflow.py` |
| **`tui`** | 터미널 네이티브 UI 및 Textual 기반 인터페이스 구현 | `ui.py`, `textual_app.py` |
| **`config`** | 설정 스키마 정의 및 환경/파일 기반 설정 로드 | `schema.py`, `loader.py` |

---

## 2. 루프 구조 상세 분석 (`src/allCode/agent/loop.py`)

`AgentLoop`는 사용자의 요청을 처리하기 위해 **[생각 $\rightarrow$ 도구 실행 $\rightarrow$ 관찰 $\rightarrow$ 판단]** 과정을 반복하는 ReAct(Reasoning and Acting) 패턴의 핵심 엔진입니다.

### 핵심 함수 및 역할

#### `run()`
- **역할**: 에이전트 루프의 최상위 진입점입니다.
- **상세**:
    - 전체 세션의 생명주기를 관리하며, 사용자의 입력이 들어오면 `_execute_turn`을 호출하여 응답을 생성합니다.
    - 루프 도중 발생하는 예외를 포착하여 `RecoveryTracker`를 통해 복구 시도를 수행합니다.

#### `_execute_turn()`
- **역할**: 단일 턴(Turn)의 실행 흐름을 제어합니다.
- **상세**:
    - **컨텍스트 빌드**: `ContextBuilder`를 통해 현재 상태, 메모리, 파일 내용 등을 조합하여 LLM에 전달할 프롬프트를 구성합니다.
    - **모델 호출**: `ModelRouter`를 통해 적절한 LLM 모델에 요청을 보냅니다.
    - **결과 판단**: 모델의 응답이 '최종 답변'인지 '도구 호출'인지 판단합니다.
    - **루프 반복**: 도구 호출이 포함되어 있다면 `_handle_tool_calls`를 통해 실행하고, 다시 `_execute_turn`으로 돌아가 모델이 도구 실행 결과를 관찰하고 다음 행동을 결정하게 합니다.

#### `_handle_tool_calls()`
- **역할**: LLM이 요청한 도구들을 실제로 실행하고 그 결과를 수집합니다.
- **상세**:
    - `ToolCallProcessor`를 사용하여 각 도구 호출의 유효성을 검사하고 실행합니다.
    - 실행 결과(Observation)를 다시 모델이 읽을 수 있는 형태로 변환하여 컨텍스트에 추가합니다.
    - 무한 루프 방지를 위해 `ToolLoopGuard`를 통해 동일한 도구 호출이 반복되는지 감시합니다.
