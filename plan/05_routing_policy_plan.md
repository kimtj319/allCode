# 05. Routing and Policy 구현 계획

## 구현 전 필수 보강 지시

- 라우팅은 static rule 기반 1차 판단과 LLM 보조 판단을 조합하되, 특정 테스트 프롬프트나 프로젝트명을 하드코딩하지 않는다.
- 라우팅 결과는 `kind`, `confidence`, `flags`, `target_hint`, `reason`을 포함해야 하며, 정책 계층은 이 구조만 참조한다.
- read-only 금지 조건이 감지되면 mutation 도구는 모델 프롬프트와 ToolPolicy 양쪽에서 차단한다.


## 목적

사용자 프롬프트를 처리 경로로 분류하고, 각 경로에서 허용되는 도구와 검증 의무를 결정한다. 목표는 하드코딩된 특정 문장 대응이 아니라, 의미 기반의 작은 정책 계층을 만드는 것이다.

## 우선순위

1. `agent/router.py` 작성
2. `agent/intent.py` 작성
3. `agent/policy.py` 작성
4. `agent/prompt_builder.py` 작성
5. 라우팅 회귀 테스트 작성

## 라우팅 종류

초기 버전은 다음 4종으로 제한한다.

- `answer`: 일반 질문, 설명, 조언
- `inspect`: 코드 분석, 파일 설명, 구조 파악
- `modify`: 파일 생성, 코드 수정, 프로젝트 구현
- `operate`: 셸 실행, 테스트, 빌드, 환경 작업

보조 플래그:

- `requires_tools`
- `requires_mutation`
- `requires_shell`
- `requires_validation`
- `requires_external_knowledge`
- `read_only_requested`

## RoutingDecision 계약

라우터는 문자열 하나만 반환하지 않는다. 모든 후속 정책은 아래 구조만 참조한다.

```python
class RoutingDecision(BaseModel):
    kind: Literal["answer", "inspect", "modify", "operate"]
    confidence: float
    reason: str
    target_hint: str | None = None
    flags: set[str] = Field(default_factory=set)
    read_only_requested: bool = False
    requires_tools: bool = False
    requires_mutation: bool = False
    requires_shell: bool = False
    requires_validation: bool = False
    requires_external_knowledge: bool = False
```

예상 동작:

- “코드 수정 금지”가 포함되면 `read_only_requested=True`, `requires_mutation=False`가 우선한다.
- “구현/작성/수정/고쳐줘”가 포함되어도 read-only 금지가 명시되면 mutation 정책이 이긴다.
- “검색해서”, “최신”, “현재 버전”은 `requires_external_knowledge=True` 신호다.
- 후속 질문은 최근 target memory를 사용해 `target_hint`를 채운다.

## 상세 수정 및 구현 내용

### 1. `agent/intent.py`

담당:

- 프롬프트에서 명시적 금지 사항 추출
- 대상 경로 추출
- 작업 동사 추출
- 후속 질문 여부 판단
- 외부 지식 필요 여부 판단

주의:

- 특정 프로젝트명이나 테스트 프롬프트를 직접 박지 않는다.
- 단어 기반 신호는 사용하되, 결정은 여러 신호의 조합으로 한다.

### 2. `agent/router.py`

구현:

- rule-based 1차 분류
- ambiguity가 있으면 LLM router를 선택적으로 사용
- 직전 turn context를 참조해 후속 질문을 보정

### 3. `agent/policy.py`

도구 정책:

- `answer`: web/search는 필요 시 허용, 파일 mutation 금지
- `inspect`: list/read/search/code-intel 허용, mutation 금지
- `modify`: read/search/write/patch/test 허용
- `operate`: shell/test/process 허용, destructive 작업은 approval 필요

### 4. `agent/prompt_builder.py`

역할:

- all_rounder 시스템 지시문 생성
- 라우팅 결과에 따른 도구 사용 지시 생성
- read-only 금지 조건 반영
- 대규모 프로젝트 생성 절차 반영

## 대규모 프로젝트 코드 생성 절차 반영

`modify` 요청에서 새 프로젝트 또는 다중 파일 생성이 감지되면 prompt builder는 다음 절차를 모델에게 전달한다.

1. 요구사항 목록을 짧게 구조화한다.
2. 파일 트리 초안을 만든다.
3. 스켈레톤 파일부터 생성한다.
4. 핵심 타입과 함수 시그니처를 먼저 작성한다.
5. 구현 파일을 역할별로 나눠 채운다.
6. 테스트 파일을 작성한다.
7. 의존성 파일을 작성한다.
8. 검증 명령을 실행한다.
9. 실패하면 실패 로그를 읽고 수정한다.
10. 완료 보고에는 파일 목록과 검증 결과를 포함한다.

## 파일 길이 및 모듈화 원칙

- `router.py`는 분류 흐름만 담당한다.
- 분류 신호 추출은 `intent.py`로 분리한다.
- 정책 판단은 `policy.py`로 분리한다.
- prompt 문자열은 `prompt_builder.py` 또는 `prompts/` 하위 템플릿으로 이동한다.

## 공개 오픈소스 참조 기반 보강 계약

라우터는 모델의 자유도를 막는 하드코딩 규칙이 아니라 안전한 실행 전략을 정하는 얇은 계층이어야 한다.

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

라우터는 실행하지 않는다. 실행 여부는 `agent/policy.py`와 tool approval이 최종 판단한다.
