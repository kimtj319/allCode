# 08. Context Memory 구현 계획

## 목적

allCode가 긴 세션, 대형 코드베이스, 후속 질문, 프로젝트별 규칙을 안정적으로 처리하도록 context memory 계층을 구현한다. 이 계획은 Aider의 repo map 방식과 Gemini CLI의 hierarchical memory / auto-memory 방식을 참고하되, allCode의 core event, workspace, agent loop 구조에 맞게 재설계한다.

## 핵심 목표

- 사용자의 후속 질문에서 직전 분석/수정 대상 파일과 함수를 잃지 않는다.
- 대형 코드베이스를 전체 본문으로 컨텍스트에 넣지 않고 repo map과 skeleton-only context로 압축한다.
- 프로젝트별 규칙과 사용자 선호를 명시적 memory 파일로 관리한다.
- 세션 재시작 후에도 최근 작업 맥락을 복원할 수 있다.
- auto-memory는 사용자 승인 전까지 active memory를 수정하지 않는다.
- secret, token, API key 같은 민감정보는 memory에 저장하지 않는다.

## 참고 설계 원칙

### Aider식 repo map

- 전체 repository의 class/function/symbol 관계를 compact하게 모델에 제공한다.
- 파일 본문 전체 대신 symbol definition, reference, signature, path를 중심으로 압축한다.
- 현재 요청에 언급된 파일명, symbol, 최근 target에 가중치를 부여한다.
- token budget에 맞게 repo map 크기를 자동 조절한다.

### Gemini CLI식 hierarchical memory

- global, project, directory, session memory를 계층적으로 합친다.
- 명시적 memory command로 show/add/refresh를 지원한다.
- auto-memory는 transcript를 스캔해 후보를 만들되, 승인 전에는 적용하지 않는다.

## 우선순위

1. `memory/schema.py`
2. `memory/store.py`
3. `memory/hierarchy.py`
4. `memory/session_store.py`
5. `memory/session_summary.py`
6. `memory/recent_targets.py`
7. `memory/repo_map.py`
8. `memory/repo_ranker.py`
9. `memory/compactor.py`
10. `memory/selector.py`
11. `memory/auto_memory.py`
12. `memory/inbox.py`
13. `memory/commands.py`
14. tests

## 디렉터리 구조

```text
src/allCode/memory/
  __init__.py
  schema.py
  store.py
  hierarchy.py
  session_store.py
  session_summary.py
  recent_targets.py
  repo_map.py
  repo_ranker.py
  compactor.py
  selector.py
  auto_memory.py
  inbox.py
  commands.py
```

저장 위치:

```text
~/.config/allCode/ALLCODE.md
<repo>/.allCode/ALLCODE.md
<repo>/<subdir>/.allCode/ALLCODE.md
<repo>/.allCode/sessions/{session_id}.jsonl
<repo>/.allCode/sessions/{session_id}.summary.md
<repo>/.allCode/memory/inbox/*.json
<repo>/.allCode/cache/repo_map.json
```

## 1. `memory/schema.py`

### 구현할 모델

```python
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

MemoryScope = Literal["global", "project", "directory", "session"]
MemoryKind = Literal[
    "instruction",
    "preference",
    "constraint",
    "workflow",
    "project_fact",
    "verification_command",
    "known_landmine",
    "recent_target",
    "repo_summary",
]

class MemoryItem(BaseModel):
    id: str
    scope: MemoryScope
    kind: MemoryKind
    text: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    source_session_id: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    approved: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class RecentTarget(BaseModel):
    path: str
    symbol: str | None = None
    target_type: Literal["file", "directory", "class", "function", "test", "command"]
    summary: str = ""
    turn_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class RepoMapEntry(BaseModel):
    path: str
    language: str | None = None
    definitions: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    summary: str = ""
    score: float = 0.0
    mtime: float | None = None

class ContextSection(BaseModel):
    name: str
    priority: int
    token_estimate: int
    content: str
    source: str
```

### 규칙

- `MemoryItem.text`에 secret/API key/token을 저장하지 않는다.
- `approved=False`인 item은 active context에 들어가지 않는다.
- `RecentTarget`은 후속 질문 해결에 우선 사용한다.
- `RepoMapEntry`는 파일 본문이 아니라 symbol/signature/summary 중심이다.

## 2. `memory/store.py`

### 책임

- memory item 저장/조회/삭제
- markdown memory 파일과 JSON candidate 파일 읽기
- session transcript 저장소와 분리

### API

```python
class MemoryStore:
    def __init__(self, project_root: Path, global_config_dir: Path): ...
    async def load_active_items(self, *, cwd: Path) -> list[MemoryItem]: ...
    async def add_item(self, item: MemoryItem) -> None: ...
    async def update_item(self, item: MemoryItem) -> None: ...
    async def delete_item(self, item_id: str) -> None: ...
```

### 규칙

- global memory는 사용자 홈 설정 디렉터리에 저장한다.
- project/directory memory는 workspace root 하위 `.allCode/ALLCODE.md`에 저장한다.
- markdown memory를 파싱할 때 heading을 kind/tag 추론에 사용한다.
- 파일 쓰기 전 parent directory를 생성한다.

## 3. `memory/hierarchy.py`

### 책임

memory 계층을 올바른 순서로 합친다.

### 로딩 순서

1. global memory
2. project memory
3. directory memory
4. session summary
5. recent targets

### 충돌 처리

- 더 가까운 scope가 더 높은 우선순위를 갖는다.
- 같은 kind와 같은 text hash가 있으면 중복 제거한다.
- 사용자 명시 금지사항은 항상 최상위 우선순위다.

## 4. `memory/session_store.py`

### 책임

turn transcript를 append-only JSONL로 저장하고 복원한다.

### API

```python
class SessionStore:
    async def append_turn(self, session_id: str, turn: TurnState) -> None: ...
    async def load_turns(self, session_id: str, *, limit: int | None = None) -> list[TurnState]: ...
    async def list_sessions(self) -> list[str]: ...
```

### 저장 규칙

- 각 turn 종료 후 `TurnState`, user prompt, final answer, tool summary를 저장한다.
- 전체 tool stdout/stderr는 transcript에 무제한 저장하지 않는다.
- 민감정보는 redaction 후 저장한다.

## 5. `memory/session_summary.py`

### 책임

긴 세션을 짧은 summary로 압축한다.

### summary에 포함할 것

- 사용자가 요청한 목표
- 이미 분석한 파일/함수
- 생성/수정한 파일
- 실패했던 검증 명령과 해결 여부
- 사용자가 명시한 금지사항
- 다음 단계 todo

### summary에 넣지 말 것

- 전체 파일 본문
- 긴 로그 전문
- API key, token, password
- 모델 내부 reasoning

## 6. `memory/recent_targets.py`

### 책임

후속 질문의 “그 파일”, “해당 함수”, “방금 본 코드”를 해결한다.

### API

```python
class RecentTargetMemory:
    def remember(self, target: RecentTarget) -> None: ...
    def resolve(self, prompt: str, *, workspace_candidates: list[str]) -> list[RecentTarget]: ...
```

### 해결 우선순위

1. 프롬프트에 명시된 정확한 path
2. 직전 turn의 target
3. 최근 5개 target 중 파일명/symbol 매칭
4. workspace 전체 후보 검색
5. 후보가 여러 개면 clarification 요청

## 7. `memory/repo_map.py`

### 책임

Aider식 compact repo map을 생성한다.

### 단계

1. workspace index에서 source file 목록을 받는다.
2. 파일별 language를 추론한다.
3. lightweight parser로 definitions, references, imports를 추출한다.
4. `RepoMapEntry`를 생성한다.
5. mtime 기반 cache를 저장한다.
6. repo ranker로 중요도를 계산한다.
7. token budget에 맞게 compact text를 생성한다.

### parser fallback

- Python: `ast` 우선, 실패 시 regex
- Java: regex로 class/interface/enum/method 추출
- TypeScript/JavaScript: regex로 export/class/function/interface 추출
- 기타: filename, heading, import-like line만 추출

## 8. `memory/repo_ranker.py`

### 책임

현재 요청과 관련 높은 파일/symbol을 우선순위화한다.

### scoring 요소

- 프롬프트에 직접 언급된 path/symbol: +10
- recent target과 동일 파일: +8
- recent target과 같은 directory: +4
- definition이 프롬프트 keyword와 매칭: +5
- test file은 구현 요청에서 +2, 분석 요청에서는 +1
- ignore/glob 제외 파일은 0점

### PageRank류 확장

MVP에서는 단순 weighted score로 시작한다. 이후 reference graph 기반 PageRank는 확장 단계에서 구현한다.

## 9. `memory/compactor.py`

### 책임

context budget에 맞게 sections를 압축한다.

### 기본 budget 비율

```text
active files: 35%
repo map: 25%
session summary: 15%
durable memory: 10%
recent tool summaries: 10%
safety margin: 5%
```

### 압축 규칙

- 직접 요청된 파일은 full content 우선.
- 직접 요청되지 않은 파일은 skeleton-only.
- 긴 로그는 마지막 error block과 command summary만 유지.
- durable memory는 중복 제거 후 scope 가까운 순서로 유지.
- budget 초과 시 repo map detail을 먼저 줄이고, active file은 마지막에 줄인다.

## 10. `memory/selector.py`

### 책임

이번 turn에 어떤 memory와 context를 넣을지 결정한다.

### API

```python
class ContextMemorySelector:
    async def select(self, turn_input: TurnInput) -> list[ContextSection]: ...
```

### 선택 순서

1. user prompt의 explicit target
2. read-only / modify / operate routing decision
3. recent target memory
4. hierarchical durable memory
5. repo map
6. session summary
7. recent tool summaries

## 11. `memory/auto_memory.py`

### 책임

세션 transcript에서 장기 기억 후보를 추출한다.

### 실행 조건

- 세션이 idle 상태일 때만 실행
- 최소 10개 user message 이상
- active agent turn 중에는 실행하지 않음
- 사용자가 disable 가능

### 후보 추출 대상

- 반복되는 검증 명령
- 프로젝트 고유 제약
- 사용자가 반복해서 말한 선호
- known failure와 해결 방식
- 자주 쓰는 workspace root

### 금지 대상

- secret/token/password/API key
- 일회성 감정 표현
- 모델 추론 과정
- 검증되지 않은 사실

## 12. `memory/inbox.py`

### 책임

auto-memory 후보를 승인 전까지 보관한다.

### API

```python
class MemoryInbox:
    async def list_candidates(self) -> list[MemoryItem]: ...
    async def approve(self, candidate_id: str) -> MemoryItem: ...
    async def reject(self, candidate_id: str) -> None: ...
```

### 규칙

- 승인 전 후보는 active context에 들어가지 않는다.
- 승인 시 `approved=True`로 store에 저장한다.
- reject된 후보는 audit 목적으로 짧은 tombstone만 남긴다.

## 13. `memory/commands.py`

### Slash command

TUI와 CLI는 다음 명령을 제공한다.

```text
/memory show
/memory add <text>
/memory refresh
/memory inbox
/memory approve <id>
/memory reject <id>
/memory clear-session
```

### 명령 동작

- `/memory show`: 현재 적용 중인 global/project/directory/session memory를 보여준다.
- `/memory add`: 사용자가 직접 memory를 추가한다.
- `/memory refresh`: ALLCODE.md와 session summary를 다시 로드한다.
- `/memory inbox`: auto-memory 후보를 보여준다.
- `/memory approve/reject`: 후보를 반영 또는 폐기한다.

## Agent loop 연동

`agent/context.py`는 memory selector를 호출한다.

```python
class ContextBuilder:
    async def build(self, turn_input: TurnInput) -> ContextBundle:
        memory_sections = await self.memory_selector.select(turn_input)
        workspace_sections = await self.workspace_context.build(turn_input)
        return self.compactor.fit([*memory_sections, *workspace_sections])
```

loop 단계:

1. Router가 요청 종류를 결정한다.
2. RecentTargetMemory가 후속 질문 target을 보정한다.
3. ContextMemorySelector가 durable/session/repo map context를 선택한다.
4. Compactor가 token budget에 맞게 압축한다.
5. PromptBuilder가 최종 prompt에 context bundle을 삽입한다.
6. Turn 종료 후 SessionStore와 RecentTargetMemory가 갱신된다.
7. idle 상태에서 AutoMemory가 candidate를 생성한다.

## 테스트 계획

### 생성 파일

```text
tests/unit/memory/test_hierarchy.py
tests/unit/memory/test_session_store.py
tests/unit/memory/test_session_summary.py
tests/unit/memory/test_recent_targets.py
tests/unit/memory/test_repo_map.py
tests/unit/memory/test_repo_ranker.py
tests/unit/memory/test_compactor.py
tests/unit/memory/test_selector.py
tests/unit/memory/test_auto_memory.py
tests/unit/memory/test_inbox.py
tests/integration/test_followup_context_memory.py
```

### 필수 검증 케이스

- “그 파일 다시 설명해줘”가 직전 target을 찾는다.
- 특정 파일명만 입력해도 최근 workspace root 안에서 먼저 찾는다.
- 대형 repo에서 전체 파일 본문 대신 repo map과 skeleton-only context가 들어간다.
- global/project/directory memory가 올바른 우선순위로 병합된다.
- auto-memory는 승인 없이 active context에 들어가지 않는다.
- secret/token/API key는 memory 후보에서 제거된다.
- context budget 초과 시 active file이 durable memory보다 우선 유지된다.
- session restart 후 summary와 recent targets가 복원된다.

## 구현 순서

1. schema와 store를 먼저 구현한다.
2. hierarchy와 session_store를 구현한다.
3. recent_targets와 session_summary를 구현한다.
4. repo_map과 repo_ranker를 구현한다.
5. compactor와 selector를 구현한다.
6. auto_memory와 inbox를 구현한다.
7. slash command를 연결한다.
8. agent/context.py와 loop 종료 후 갱신 흐름을 연결한다.
9. unit/integration test를 실행한다.

## 파일 길이 및 모듈화 원칙

- `repo_map.py`가 350줄을 넘으면 `parsers.py`, `cache.py`로 분리한다.
- `compactor.py`는 token budget 계산만 담당하고 memory load를 하지 않는다.
- `selector.py`는 선택 정책만 담당하고 파일 시스템을 직접 스캔하지 않는다.
- slash command 렌더링은 TUI 계층에 두고 memory command는 application service만 제공한다.

## 대규모 프로젝트 코드 생성 절차 반영

대규모 프로젝트 구현 중 context memory는 다음을 보장해야 한다.

1. 생성한 파일 목록을 recent target으로 기록한다.
2. 검증 명령과 실패 로그 요약을 session summary에 저장한다.
3. 다음 턴에서 “방금 만든 테스트”, “그 API 파일” 같은 표현을 해석한다.
4. 프로젝트 고유 제약은 auto-memory candidate로 제안하되 자동 반영하지 않는다.
5. 전체 생성 파일 본문을 무제한 context에 넣지 않고 skeleton-only summary로 압축한다.

## 완료 기준

- 모든 memory unit test가 통과한다.
- follow-up context integration test가 통과한다.
- secret redaction test가 통과한다.
- repo map 생성이 외부 parser 없이도 동작한다.
- session restart 후 최근 target과 summary가 복원된다.
