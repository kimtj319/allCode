# 06. Tool System 구현 계획

## 구현 전 필수 보강 지시

- `patch_file` 포맷을 명확히 정의한다. MVP에서는 LLM 친화적인 search/replace 블록을 기본으로 하고, 매칭 0개 또는 2개 이상이면 실패로 처리한다.
- 모든 도구는 예외를 상위로 터뜨리지 않고 `ToolResult(ok=False, error=...)`로 반환한다.
- shell 도구는 timeout, cwd, environment allowlist, destructive command approval을 기본 계약으로 가진다.
- 파일 도구는 workspace root 밖 쓰기를 금지하고, 쓰기 전 parent directory를 생성하며, diff preview를 생성한다.


## 목적

모델이 사용할 도구를 명확한 schema와 실행 계약으로 제공한다. 도구 등록, 권한 검사, 실행, 결과 정규화, diff 표시가 분리되어야 한다.

## 우선순위

1. `tools/registry.py` 작성
2. `tools/base.py` 작성
3. `tools/executor.py` 작성
4. `tools/approval.py` 작성
5. builtin 도구 작성
6. 도구 실행 테스트 작성

## 기본 도구 목록

초기 builtin 도구:

- `list_directory`
- `read_file`
- `search_files`
- `write_file`
- `patch_file`
- `run_command`
- `run_tests`
- `web_search`
- `web_fetch`

## 상세 수정 및 구현 내용

### 1. `tools/base.py`

정의 및 계약:

- `ToolDefinition`
- `ToolContext`
- `BaseTool`

> [!IMPORTANT]
> `ToolCall` 및 `ToolResult` 타입은 `core/models.py`에서 정의된 타입을 그대로 Import하여 사용한다. 도구 시스템 패키지(`allCode/tools/`) 내부에서 동명의 타입을 절대로 재정의하지 않고 이를 통해 타입의 일관성과 단방향 의존성을 유지한다.

### 2. `tools/registry.py`

담당:

- 도구 등록
- provider용 tool schema 생성
- 이름 alias 정규화
- 도구 그룹 관리

### 3. `tools/executor.py`

담당:

- policy 검사 후 실행
- approval 필요 시 이벤트 발행
- 예외를 `ToolResult`로 변환
- stdout/stderr 길이 제한
- 실행 시간 기록

### 4. `tools/approval.py`

담당:

- 파일 생성/수정 diff 미리보기
- shell command risk 분류
- session allow rule 관리
- destructive command 차단

### 5. builtin 도구

파일 도구:

- workspace root 밖 쓰기 금지
- path traversal 방지
- write 전 parent directory 생성
- patch 실패 시 명확한 오류 반환

셸 도구:

- timeout 필수
- working directory 명시
- interactive command 기본 금지
- validation command와 destructive command 구분

#### `patch_file` search/replace schema

MVP의 `patch_file`은 unified diff를 직접 생성하지 않는다. LLM이 안정적으로 작성할 수 있는 search/replace 블록을 사용한다.

```json
{
  "file_path": "src/allCode/core/models.py",
  "patches": [
    {
      "search": "class Message(BaseModel):\n    pass\n",
      "replace": "class Message(BaseModel):\n    role: Role\n    content: str = \"\"\n"
    }
  ]
}
```

규칙:

- `search`는 파일 안에서 정확히 1회만 매칭되어야 한다.
- 0회 매칭 또는 2회 이상 매칭이면 도구는 실패한다.
- whitespace normalization을 임의로 하지 않는다.
- trailing newline은 입력 그대로 존중한다.
- 여러 patch는 위에서 아래 순서로 적용한다.
- 적용 전후 unified diff preview를 생성한다.
- 실패 시 파일을 변경하지 않는다.

#### shell 실행 계약

- 기본 timeout은 60초, validation 명령은 180초다.
- cwd는 workspace root 또는 그 하위만 허용한다.
- `rm -rf`, `sudo`, 디스크 전체 접근, background daemon 실행은 approval 없이는 차단한다.
- stdout/stderr는 각각 최대 20,000자까지만 ToolResult에 담고, 전체 로그는 debug artifact로 분리한다.

웹 도구:

- 외부 지식이 필요한 경우만 노출
- 검색 결과를 그대로 나열하지 않고 모델 요약에 쓸 evidence로 반환

## 대규모 프로젝트 코드 생성 절차 반영

대규모 생성에서는 도구 실행 순서가 중요하다.

1. `list_directory`로 기존 상태 확인
2. `write_file`로 스켈레톤 생성
3. `read_file`로 생성 결과 확인
4. `write_file` 또는 `patch_file`로 구현 추가
5. `run_tests` 또는 `run_command`로 검증
6. 실패 시 `read_file`과 `patch_file`로 수리
7. 최종 파일 목록과 diff summary 작성

## 파일 길이 및 모듈화 원칙

- builtin 도구는 파일별로 분리한다.
- `executor.py`는 실행 오케스트레이션만 담당하고 개별 도구 로직을 담지 않는다.
- approval preview 생성은 `approval.py` 또는 `diff.py`로 분리한다.
- 도구 하나가 250줄을 넘으면 helper 모듈로 분리한다.

## 공개 오픈소스 참조 기반 보강 계약

도구 시스템은 OpenHands식 action/event 관찰성과 Aider식 변경 검증 흐름을 함께 만족해야 한다.

- 모든 file mutation은 `EditTransaction` 안에서 실행한다.
- transaction은 `before_hash`, `after_hash`, `diff`, `rollback_payload`를 가진다.
- write/patch 실패 시 파일을 변경하지 않고 실패 event만 발행한다.
- tool stdout/stderr는 화면용 truncate와 artifact용 full log를 분리한다.
- destructive shell은 approval 없이는 실행하지 않는다.
- `run_tests`는 일반 shell command가 아니라 validation event를 발행한다.
- 웹 도구는 raw 검색 결과를 최종 답변으로 바로 쓰지 않고 evidence bundle로만 반환한다.
