# 64. 프로젝트 최적화 + 시나리오 검증 (2026-06-14)

## Phase 1 — 데드코드/중복 제거 (vulture + ruff, 무회귀)
- 미사용 import 12개 제거(9개 모듈). `phase_gate.py`의 3개는 다른 모듈이 거기서
  import하는 **facade 재노출**이라 보존; `test_artifact_required`는 테스트가 사용 → 보존.
- `inspect_staging.py`의 위임 전용 죽은 래퍼 4개(`_target_observed`/`_paths_overlap`/
  `_explicit_target_paths`/`_looks_path_like`) + 그로 인해 죽은 import 제거.
- `renderers._render_source_overview_collected`의 계산만 하고 버려지던 지역변수 블록 제거.
- 동일 `_looks_test_path` 4중복 → `core.path_patterns.looks_like_test_path`로 통합(사이클
  없음, import 별칭으로 호출부 불변). `.test.`/`.spec.`까지 보는 memory 변형은 의도적 분리.
- 커밋: `f27b70f`, `cb0e9f4`.

## Phase 2 — 전체 흐름 검수/보강
- **import 건전성**: 262개 모듈 전부 클린 import(순환·import-time 오류 0).
- `executor.py`: `"ApprovalDecision"` forward-ref 주석이 import 안 됨(F821) → import 추가.
- `__main__.py`: 가드 없이 모듈 레벨 `raise SystemExit(main())` → `import allCode.__main__`
  시 CLI가 실행됨. `if __name__ == "__main__"` 가드 추가(`python -m allCode`는 그대로).
- 커밋: `7bc84af`.

## Phase 3 — 다양한 프롬프트 실 TTY 검증 + 보강
- **#1 신규 생성/구현**(circuit breaker, 직전 세션): `breaker.py`/`test_breaker.py` 정확
  생성, pytest 5 passed, 색상 diff UI. ✓
- **#4 일반 Q&A**: 무이모지 구조적 답변. ✓
- **#3 멀티턴 프로젝트 관리**(notes CLI, 3턴): T1 add/list 생성 → T2 "방금 만든"에 delete
  추가(컨텍스트 연속) → T3 자기가 만든 파일을 source_probe로 분석 요약. add/list/delete
  스모크 정상, 라인 앵커 분석, 무이모지. ✓
- **관찰→최적화(과도한 부분)**: 멀티턴 캡처에서 출력의 67%가 ANSI 제어(erase-line 40K).
  원인은 `_render_running_composer`가 **스트리밍 매 토큰마다** 컴포저 전체 repaint.
  → ~30fps 쓰로틀 추가(상태 변경 시 즉시 렌더, 동일 상태 스피너는 33ms 간격). 가시
  변화 없이 repaint 폭주 제거, 779 passed. 커밋: (이 커밋).

## 결과
- 전체 779 passed(+신규 테스트), ruff 클린(phase_gate 재노출 제외), 262모듈 클린 import.
- 4개 시나리오(신규생성/구현·대형분석·수정·멀티턴·일반Q&A) 실 TTY 품질·UI 확인 완료.

## Phase 3 추가 — 대형 프로젝트 분석 실 TTY 재검증 (2026-06-14)

대상: allCode 자체 코드베이스(264파일/39k줄), workspace=레포 루트, 읽기 전용 분석
("src/allCode 아키텍처 + 한 요청의 핵심 실행 흐름 설명").

- **읽기 전용**: src/allCode 변경 0 ✓. 39s에 완료, source_overview 7회 + source_probe 24회.
- **커버리지**: 8개 패키지(core/agent/tools/tui/llm/workspace/generation/memory) 전부 역할 서술.
- **실행 흐름 정확**: `__main__ → main(config/argparse/headless vs TUI) → runtime(ContextBuilder+
  AgentLoop, ModelRouter+LLMClient) → round_runner(PromptBuilder/툴게이트) → LLM(ParsedResponse)
  → tools 레지스트리 → (대화형) tui → memory 세션요약`. 실제 아키텍처와 일치.
- **근거**: 라인 앵커 12개(`__main__.py:3`, `main.py:12-22`, `runtime.py:8-11`,
  `round_runner.py:5-15`, `response_parser.py:27-36`, `tui/runtime.py:15-27` 등).
- **무환각**: "남은 한계·미확인 부분"에서 본문 미관찰 영역(AgentLoop.run, ModelRouter.route,
  tools 레지스트리 내부 등)을 명시 — import/시그니처 근거와 본문 근거를 구분. UI 무이모지·
  구조적. ✓
- 남은 상한은 (모델-의존) 본문 수준 심층도이며, 그조차 정직하게 disclosure됨.
