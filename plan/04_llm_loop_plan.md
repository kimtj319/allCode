# 04. LLM Loop 구현 계획

## 구현 전 필수 보강 지시

- 스트림 파서는 미완성 JSON, 중간에 끊긴 tool call delta, 빈 응답, reasoning-only 응답에서도 예외로 루프를 붕괴시키지 않는다. 내부 버퍼 상태 머신으로 마지막 정상 상태를 유지한다.
- 실제 provider 연동 전 fake LLM으로 `text only`, `tool call`, `empty response`, `malformed tool call`, `length cutoff` 시나리오를 모두 통과해야 한다.
- 동일 도구/동일 인자 반복 호출은 loop guard가 감지하고 recovery로 전환한다.


## 목적

모델에게 프롬프트를 보내고, 응답 텍스트와 도구 호출을 받아 반복 실행하는 최소 ReAct 루프를 구현한다. 기존 OneCLI의 all_rounder 감각은 유지하되, query_engine처럼 모든 책임을 한 파일에 모으지 않는다.

## 우선순위

1. `llm/client.py` 인터페이스 정의
2. `llm/adapters/openai_compatible.py` 구현
3. `llm/response_parser.py` 구현
4. `agent/loop.py` 구현
5. `agent/recovery.py` 구현
6. fake LLM 기반 테스트 작성

## 상세 수정 및 구현 내용

### 1. `llm/client.py`

정의할 Protocol:

- `LLMClient.stream(messages, tools, settings) -> AsyncIterator[ModelEvent]`
- `LLMClient.complete(messages, tools, settings) -> ModelResponse`

핵심 원칙:

- OpenAI-compatible, 로컬 HTTP, 향후 다른 provider가 동일 인터페이스를 사용한다.
- provider별 token, stream chunk, tool call 형식은 adapter 내부에서 표준화한다.

### 2. `llm/response_parser.py`

담당:

- text delta 정규화
- tool call delta 누적
- empty content 감지
- reasoning-only 응답 감지
- stream ended without content 감지
- finish_reason 정규화

반드시 처리할 상태:

- `ok_text`
- `ok_tool_calls`
- `empty_response`
- `reasoning_only`
- `length_cutoff`
- `malformed_tool_call`
- `slow_stream`
- `stream_timeout`

#### Partial JSON parsing 계약

Tool call arguments는 스트리밍 도중 불완전한 JSON 조각으로 들어올 수 있다. 파서는 `json.loads()` 실패를 루프 실패로 전파하지 않고 다음 순서로 처리한다.

1. tool call id별 argument buffer를 누적한다.
2. 중괄호/대괄호 depth와 문자열 escape 상태를 추적한다.
3. JSON이 완결되지 않았으면 `partial=True` 상태로 보류한다.
4. 완결 후에도 파싱 실패하면 `malformed_tool_call`로 분류하고 recovery로 넘긴다.
5. 마지막 정상 파싱값은 metadata에 보관하되, 미완성 값을 도구 실행에 넘기지 않는다.

### 3. `agent/loop.py`

루프 단계:

1. `TurnStarted` 이벤트 발행
2. router 결과와 context를 받아 model messages 구성
3. 모델 스트리밍 시작
4. 텍스트는 UI 이벤트로 흘려보냄
5. tool call이 있으면 policy 검증
6. tool executor 실행
7. tool result를 message로 누적
8. 완료 조건 검사
9. final answer 생성 및 품질 검사

종료 조건:

- 모델이 최종 답변을 냄
- 도구 호출 후 검증이 완료됨
- max rounds 도달
- 복구 불가능 오류 발생

### 4. `agent/recovery.py`

복구 정책:

- 빈 응답이면 동일 컨텍스트를 축약해 1회 재요청한다.
- tool-call-only가 반복되면 “최종 답변만 작성” 프롬프트를 사용한다.
- 같은 도구와 같은 인자가 반복되면 tool loop guard가 차단한다.
- max rounds 도달 시 실제 파일 변경 여부와 검증 여부를 확인하고 부분 완료 여부를 판단한다.

#### 1.5단계 보강 계약: slow model과 final answer gate

1단계 구현이 끝난 뒤 2단계로 넘어가기 전에 아래 동작을 fake LLM 시나리오와 함께 고정한다.

- `empty_response`: 사용자에게 빈 답변을 반환하지 않고 축약 프롬프트로 1회 재요청한다.
- `reasoning_only`: reasoning content를 사용자에게 직접 출력하지 않고 “최종 답변만 작성” 요청으로 전환한다.
- `length_cutoff`: 부분 응답만으로 완료 처리하지 않고 continuation 또는 partial 상태를 반환한다.
- `slow_stream`: 일정 시간 text/tool delta가 없어도 즉시 실패하지 않고 heartbeat/status event를 발행한다.
- `stream_timeout`: timeout 이후에도 partial text/tool call이 있으면 recovery로 넘기고, 아무 근거도 없으면 retry한다.
- final answer gate: 구현/수정 요청에서 `CompletionEvidence`가 없으면 최종 완료 답변을 반환하지 않는다.

추가 fake LLM 시나리오:

- `slow_then_text`: 긴 침묵 뒤 정상 텍스트 반환
- `slow_then_tool`: 긴 침묵 뒤 tool call 반환
- `reasoning_only_then_final`: 첫 응답은 reasoning-only, 재요청 후 final answer 반환
- `empty_twice`: 두 번 모두 빈 응답이면 failed/partial로 종료
- `same_tool_three_times`: 같은 tool signature 3회 반복 시 recovery 발동

#### 반복 도구 호출 감지 pseudocode

```text
for each tool_call:
  key = sha256(tool_name + canonical_json(arguments))
  append key to recent_tool_call_window(max=10)
  if same key appears 3 times in the last 5 calls:
      block current call
      inject recovery message:
        "같은 도구 호출이 반복되었습니다. 다른 파일을 읽거나 다른 접근으로 전환하세요."
      emit ToolLoopDetected event
```

이 guard는 모델 자유도를 과하게 제한하지 않는다. 동일 도구라도 인자가 다르거나 새로운 evidence를 얻는 경우는 허용한다.

## 대규모 프로젝트 코드 생성 절차 반영

대규모 코드 생성 요청에서는 루프가 다음 절차를 강제해야 한다.

1. 요구사항을 구조화한다.
2. 대상 경로와 생성 파일 목록을 확정한다.
3. 스켈레톤을 먼저 생성한다.
4. 핵심 함수와 public API를 설계한다.
5. 파일별 구현을 나눠 진행한다.
6. 파일 간 import와 실행 경로를 연결한다.
7. 테스트 또는 문법 검사를 실행한다.
8. 실패 시 로그를 읽고 재수정한다.
9. 생성/수정된 파일, 검증 결과, 남은 리스크를 최종 답변에 포함한다.

## 파일 길이 및 모듈화 원칙

- `agent/loop.py`는 400줄을 넘기지 않는다.
- 복구 로직은 `agent/recovery.py`로 분리한다.
- model response parsing은 반드시 `llm/response_parser.py`에 둔다.
- prompt 조립은 `agent/prompt_builder.py`로 분리하고 loop에 문자열을 직접 길게 넣지 않는다.

## 공개 오픈소스 참조 기반 보강 계약

LLM loop는 모델별 특성이 아니라 provider-neutral event stream을 기준으로 동작한다.

- `ModelEvent`는 최소 `text_delta`, `tool_call_delta`, `tool_call_completed`, `response_completed`, `response_failed`, `usage`를 가진다.
- `empty_response`는 성공으로 보지 않고 축약 프롬프트로 1회 재요청한다.
- `reasoning_only`는 사용자에게 직접 출력하지 않고 final answer 요청으로 전환한다.
- `tool_call_completed`가 있으면 텍스트가 없어도 tool execution phase로 넘어간다.
- 같은 tool hash가 3회 반복되면 recovery로 전환하고, 동일 도구라도 인자가 다르면 허용한다.
- loop는 TUI나 config file을 직접 import하지 않고 context bundle, router decision, tool registry만 받는다.
- 느린 로컬 모델을 특정 모델명으로 분기하지 않는다. heartbeat, timeout, retry, partial progress event로 일반화해 처리한다.
