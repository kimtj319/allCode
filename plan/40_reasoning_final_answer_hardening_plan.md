# 40. Reasoning Final Answer Hardening Plan

## 목적

실제 모델 실행에서 read-only source analysis가 도구 수집은 수행했지만 최종 답변 턴에서
`reasoning_only`가 두 번 발생하고 local fallback summary로 내려갔다. 이 계획은 모델이
사용자-visible `content`를 직접 생성하도록 final-answer 재요청 경로를 보강한다.

## 분석 대상

- `src/allCode/llm/adapters/openai_compatible.py`
- `src/allCode/llm/response_parser.py`
- `src/allCode/agent/round_runner.py`
- `src/allCode/agent/round_response_handler.py`
- `src/allCode/agent/prompt_builder.py`
- `src/allCode/agent/language.py`
- `src/allCode/agent/inspect_summary.py`
- 최근 실제 실행 로그: `~/.allcode/session/2026/06/05/20260605_072614-03_newcli-afc2df63.jsonl`

## 재현 결과

실제 endpoint probe 결과:

- 단순 단발 streaming/non-streaming 요청은 `content`를 정상 반환한다.
- OpenAI native `assistant.tool_calls` + `tool` role history 뒤에 final answer를 요청하면
  streaming/non-streaming 모두 `content_len == 0`, `reasoning_len > 0`으로 끝난다.
- 같은 관찰 내용을 일반 assistant 텍스트 요약으로 압축해 보내면 streaming/non-streaming 모두
  `content`가 정상 생성된다.

따라서 원인은 모델의 답변 능력 부족이 아니라, 현재 endpoint와 native tool-role history의
final synthesis 호환성 문제다.

## agy 검토 요약

agy는 코드 수정 금지 조건으로 아래 원인을 지적했다.

- `reasoning_only` recovery에서 assistant 응답을 추가하지 않고 final answer user prompt만 추가해
  user-message 연속 구조가 생길 수 있다.
- final answer prompt가 “최종 답변만”을 강하게 요구하지만, reasoning 모델에서 user-visible
  content 생성을 충분히 분리해서 요구하지 못한다.
- `response_parser.py`는 reasoning metrics만 기록하고 raw reasoning text는 보존하지 않는다.
  다만 raw chain-of-thought를 사용자에게 노출하면 안 되므로, allCode는 reasoning 원문을 최종 답변
  재료로 쓰지 않는다.
- `openai_compatible.py`에는 provider별 reasoning/thinking payload 확장과 non-stream fallback 확장
  여지가 필요하다.

2차 계획 검토에서 agy가 보정한 구현 주의사항:

- `PromptBuilder.final_answer_request()`가 `runtime.messages` 자체를 compact하면 안 된다.
  `grounded_inspect_summary()`와 `blocked_summary()`는 원래 tool role history를 사용해 fallback
  근거를 구성한다.
- 따라서 compaction은 모델 호출 직전 outgoing message에만 적용하고, 내부 transcript와 evidence용
  `runtime.messages`는 원본을 유지한다.
- strict config schema 때문에 `extra_body`는 `ModelConfig`와 `ModelSettings` 양쪽에 명시해야 한다.

## 오픈소스 참조

- Aider는 reasoning 모델을 모델 capability로 다루며 `thinking_tokens`, `reasoning_effort`,
  `reasoning_tag`, `streaming`, `use_temperature`, `use_system_prompt` 같은 설정을 모델별로 적용한다.
- Qwen-Agent는 `generate_cfg`를 통해 `thought_in_content`, `use_raw_api`, `extra_body`,
  `enable_thinking` 같은 생성/파싱 제어를 노출한다.
- Qwen 문서는 thinking 모드의 Chat Completions가 `reasoning_content` 뒤에 `content`를 생성하며,
  function calling 중 thinking을 쓰는 경우 reasoning과 tool 결과 history 취급이 중요하다고 설명한다.
- Gemini CLI의 non-interactive loop는 tool call이 없고 content가 나오면 종료하는 구조를 유지한다.

allCode에 바로 적용 가능한 결론은 native tool-role transcript를 그대로 final synthesis에 재사용하지
않고, final answer 턴에서는 action/observation log를 compact text context로 변환하는 것이다.

## 구현 계획

### Phase 1. Final Answer Context Compactor

생성 파일:

- `src/allCode/agent/final_answer_context.py`

작업:

- tool role message가 있는 final-answer 요청에서는 native tool transcript를 제거한다.
- system instruction, 원 사용자 요청, bounded tool observation summary, final answer request만 남긴
  provider-neutral 메시지 목록을 만든다.
- assistant bridge message를 삽입해 user-user 연속 메시지를 피한다.
- tool 결과는 tool name, ok/error, target, observation summary, 핵심 content 일부만 보존한다.
- raw reasoning content는 저장하거나 노출하지 않는다.

### Phase 2. RoundRunner Outgoing Final Context 연결

수정 파일:

- `src/allCode/agent/round_runner.py`

작업:

- final-answer gate가 열려 `allowed_tools=[]`인 모델 호출에만 새 compactor를 적용한다.
- `runtime.messages`는 원본 tool-role transcript를 유지한다.
- `ModelStreamCollector.collect()`에 전달하는 outgoing messages만 compact한다.
- tool history가 없더라도 마지막 메시지가 user이면 assistant bridge를 넣어 재요청 형태를 안정화한다.
- 기존 read-only, mutation, validation gate 책임은 유지한다.

### Phase 3. Final Answer Prompt 완화

수정 파일:

- `src/allCode/agent/language.py`

작업:

- “최종 답변만” 요구는 유지하되, “visible assistant content”에 사용자-facing 답변을 작성하라고 명시한다.
- “reasoning/thinking 채널이 아니라 답변 본문”이라는 조건을 추가한다.
- 한국어/영어 모두 같은 의미를 유지한다.

### Phase 4. Provider Payload 확장 여지

수정 파일:

- `src/allCode/config/schema.py`
- `src/allCode/llm/settings.py`
- `src/allCode/llm/adapters/openai_compatible.py`

작업:

- `model.extra_body`를 config에 추가하고 adapter payload root에 병합한다.
- 기본값은 빈 dict로 유지해 endpoint 호환성을 깨지 않는다.
- 모델명 하드코딩 없이 사용자가 Qwen/vLLM/DashScope류 endpoint에 `enable_thinking`,
  `chat_template_kwargs`, `top_p` 등을 전달할 수 있게 한다.

### Phase 5. 검증

집중 테스트:

```bash
python -m pytest tests/unit/agent/test_prompt_builder.py tests/unit/config tests/unit/llm/test_openai_compatible_adapter.py tests/integration/test_readonly_source_analysis.py
```

회귀 테스트:

```bash
python -m pytest tests/unit/agent tests/unit/llm tests/unit/config tests/integration/test_readonly_source_analysis.py
```

실제 모델 테스트:

```bash
allcode --headless "현재 디렉터리의 src/allCode/agent와 src/allCode/tools가 각각 어떤 책임을 갖고 어떻게 상호작용하는지 코드 근거를 들어 정리해줘. 코드 수정은 엄격히 금지한다. 최종 답변은 한국어로 작성하라."
```

## 금지 사항

- raw chain-of-thought/reasoning_content를 사용자 최종 답변에 노출하지 않는다.
- 특정 모델명, 특정 테스트 프롬프트, 특정 path를 source code에 하드코딩하지 않는다.
- read-only route에 mutation/shell/validation tool을 노출하지 않는다.
- fallback summary만 품질을 높이는 것으로 문제를 덮지 않는다. 우선 목표는 모델-authored final answer다.
