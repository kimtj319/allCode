# 02. Config and Entrypoint 구현 계획

## 목적

`config/` 디렉터리가 구조도에만 존재하는 상태를 방지한다. 모델, API 키, base URL, workspace, approval mode 같은 실행 설정을 한 곳에서 관리하고, CLI 진입점과 패키징 계약을 명확하게 만든다.

## 우선순위

1. `src/allCode/config/schema.py`
2. `src/allCode/config/manager.py`
3. `src/allCode/config/defaults.py`
4. `src/allCode/main.py`
5. `src/allCode/__main__.py`
6. `tests/unit/config/test_config_manager.py`
7. `tests/unit/test_entrypoint.py`

## 설정 스키마

```python
class ModelConfig(BaseModel):
    model_name: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 120
    max_output_tokens: int = 8192

class WorkspaceConfig(BaseModel):
    root: str = "."
    extra_roots: list[str] = Field(default_factory=list)
    sandbox_enabled: bool = True

class ApprovalConfig(BaseModel):
    mode: Literal["ask", "auto", "rules"] = "ask"
    session_allow: list[str] = Field(default_factory=list)

class AppConfig(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
```

## ConfigManager 계약

- 기본 설정 파일은 `~/.config/allCode/config.yaml`이다.
- `ALLCODE_CONFIG` 환경변수가 있으면 해당 파일을 우선한다.
- 환경변수는 설정 파일보다 우선한다.
- API 키 값은 직접 저장하지 않고 환경변수명만 저장한다.
- 설정 파싱 실패는 명확한 오류와 복구 안내를 반환한다.
- config 계층은 LLM adapter와 TUI를 import하지 않는다.

## CLI 진입점

`allCode.main:main`은 다음 책임만 가진다.

1. argv 파싱
2. config 로드
3. workspace root 초기화
4. TUI app 또는 headless runner 시작
5. 최상위 예외를 사용자 친화적인 오류로 출력

## 명령 옵션 MVP

```text
ac
ac --headless "질문"
ac --workspace /path/to/project
ac --config /path/to/config.yaml
ac --model gpt-4o
ac --base-url http://localhost:11434/v1
ac --approval ask|auto|rules
```

## 대규모 프로젝트 생성 절차 반영

프로젝트 구현 요청을 받을 때 config 계층은 다음을 제공한다.

- 현재 workspace root
- write 가능 여부
- shell 실행 정책
- 모델 timeout과 max output token
- approval mode

## 파일 길이 및 모듈화 원칙

- `manager.py`는 파일 I/O와 환경변수 merge만 담당한다.
- schema 정의는 `schema.py`에 둔다.
- CLI argparse는 `main.py`에 두되 250줄을 넘기면 `app/args.py`로 분리한다.

## 공개 오픈소스 참조 기반 보강 계약

Config 계층은 model provider와 TUI 구현체를 느슨하게 연결하는 경계다.

설정 우선순위:

```text
CLI flag > environment variable > project config > user config > defaults
```

민감정보 처리:

- API key 값은 config file에 저장하지 않는다.
- config에는 env var name만 저장한다.
- debug log에는 secret redacted value만 기록한다.
- provider별 설정은 `ModelConfig` 확장 필드가 아니라 adapter-specific config로 분리한다.
- config loading 실패는 agent loop 시작 전에 중단하고, TUI worker 안에서 뒤늦게 터지지 않게 한다.
