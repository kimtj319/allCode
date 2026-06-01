# 07. Workspace and Context 구현 계획

## 구현 전 필수 보강 지시

- symbol index는 tree-sitter 같은 외부 parser가 없더라도 실패하지 않고 lightweight regex parser로 fallback한다.
- 대형 코드베이스에서는 전체 파일 본문을 컨텍스트에 누적하지 않는다. 현재 타깃 외 파일은 signature/docstring/import 중심의 skeleton-only context로 압축한다.
- 파일 변경 감지 또는 새 파일 생성 시 workspace index는 전체 재색인이 아니라 부분 갱신을 우선한다.


## 목적

대형 코드베이스에서도 모델이 필요한 파일을 잘 찾고, 후속 질문에서 직전 맥락을 잃지 않도록 작업공간 인덱싱과 컨텍스트 압축을 분리 구현한다.

## 우선순위

1. `workspace/roots.py` 작성
2. `workspace/indexer.py` 작성
3. `workspace/path_resolver.py` 작성
4. `workspace/symbol_index.py` 작성
5. `agent/context.py` 작성
6. `memory/*` (Hierarchical Memory, Recent Targets) 연동 및 검증

## 상세 수정 및 구현 내용

### 1. `workspace/roots.py`

담당:

- 기본 workspace root 관리
- `/directory add` 형태의 추가 root 관리
- 쓰기 가능한 root와 읽기 가능한 root 분리

### 2. `workspace/indexer.py`

담당:

- 파일 트리 요약
- ignore rule 적용
- 대형 디렉터리 샘플링
- 언어별 대표 파일 추출

### 3. `workspace/path_resolver.py`

담당:

- 사용자 프롬프트의 상대 경로 해석
- 직전 분석 대상 기반 파일명 검색
- 다중 root에서 충돌 파일 후보 반환
- 정확도 낮을 때 모델 또는 사용자에게 clarification 요청

### 4. `workspace/symbol_index.py`

담당:

- Python class/function 추출
- Java class/method 추출
- TypeScript export/function/class 추출
- 필요 시 tree-sitter 또는 lightweight parser 확장

### 5. `agent/context.py`

담당:

- 현재 turn에 넣을 context 구성
- 파일 내용 길이 제한
- 최근 도구 결과 요약
- 대화 요약 삽입

### 6. `memory/*` (대체 모듈군)

> [!IMPORTANT]
> `agent/memory.py` 파일의 기존 역할(최근 대상 파일, 최근 프로젝트 root, 사용자 금지 사항, 장기 작업 todo 등)은 `08_context_memory_plan.md`의 `memory/*` 패키지(예: `memory/recent_targets.py`, `memory/hierarchy.py` 등)로 **완전하게 단일화 및 이관**한다.
> 중복 데이터 소스로 인한 모델 혼동과 정합성 에러를 완벽히 예방하기 위해, workspace/context 계층은 자체적인 `agent/memory.py`를 구현하지 않고, Milestone 7의 `memory` 모듈에 직접 질의하도록 단방향 결합 인터페이스를 설계한다.

## Workspace 상태 이벤트

workspace 계층은 TUI를 직접 알지 않는다. 아래 이벤트만 agent loop 또는 TUI에 전달한다.

- `WorkspaceRootAdded`
- `WorkspaceRootRejected`
- `WorkspaceIndexed`
- `PathResolved`
- `PathResolutionAmbiguous`
- `WorkspaceIndexUpdated`

## PathPolicy 계약

- 모든 write/patch/delete 대상은 writable `WorkspaceRef.root` 하위여야 한다.
- `..`, symlink, absolute path를 정규화한 뒤에도 root 밖이면 `PathPolicyDeniedError`를 반환한다.
- read-only root에서는 read/search/list만 허용한다.
- 다중 root에서 동일 파일명이 발견되면 자동 선택하지 않고 후보를 반환한다.
- 후속 질문에서 파일명만 주어진 경우 최근 target memory를 먼저 검색하고, 없으면 workspace 전체 후보를 검색한다.

## 대규모 프로젝트 코드 생성 절차 반영

프로젝트 구현 전 workspace 계층은 다음 정보를 agent loop에 제공해야 한다.

1. 대상 디렉터리가 비어 있는지 확인한다.
2. 기존 파일이 있으면 덮어쓰기 위험을 표시한다.
3. 생성할 파일 경로를 normalized path로 변환한다.
4. 프로젝트 언어와 빌드 시스템 후보를 추론한다.
5. 테스트 명령 후보를 제안한다.
6. 구현 후 생성 파일 인벤토리를 제공한다.

## 파일 길이 및 모듈화 원칙

- 경로 해석은 `path_resolver.py`에만 둔다.
- index 생성은 `indexer.py`, symbol 추출은 `symbol_index.py`로 나눈다.
- context 압축은 workspace 계층이 아니라 agent 계층에서 처리한다.
- 대형 코드베이스 분석 규칙은 데이터 파일 또는 strategy 클래스로 분리한다.

## 공개 오픈소스 참조 기반 보강 계약

Workspace context는 Aider식 repo map과 Gemini CLI식 hierarchical memory가 만나는 계층이다.

- 기본 index 최대 파일 수는 20,000개다.
- 기본 파일 본문 읽기 최대 크기는 256KB다.
- repo map 대상 파일 최대 크기는 512KB다.
- `node_modules`, `.git`, `.venv`, `dist`, `build`, `target`, `__pycache__`는 기본 제외한다.
- binary 파일은 content read 대상에서 제외하고 metadata만 기록한다.
- index cache는 path, mtime, size hash로 invalidation한다.
- workspace는 후보 파일과 symbol 정보를 제공하고, 이번 turn에 무엇을 넣을지는 memory/context selector가 결정한다.
