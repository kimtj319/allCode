# 61. Project Implementation Route Findings (Axis ①)

## Test (2026-06-13)

빈 디렉터리에 동일 프롬프트("표준 라이브러리만으로 add/list/done + JSON 저장,
argparse 엔트리포인트를 갖춘 CLI 할 일 앱")를 allCode와 codex에 투입.

- **codex** (`exec --sandbox workspace-write`): 저장소 탐색 후 `todo.py`(151줄)
  + `test_todo.py`(테스트 작성). EXIT 0.
- **allCode** (`--headless --approval auto`): `todo.py`(86줄) 작성. EXIT 0.

## Audit

- **기능 동등**: 양쪽 `todo.py` 모두 add/list/done + JSON 저장이 정상 동작
  (수동 스모크 통과). 핵심 기능 격차 없음.
- **격차 ①-A (스타일)**: allCode 완료 보고가 이모지 머리글(📦/🎉/🚀)과 홍보성
  산문("자유롭게 확장해 보세요! 🚀")을 사용 → Codex의 간결·plain 완료 요약과
  스타일 괴리. **harness/프롬프트로 교정 가능**.
- **격차 ①-B (자가검증/테스트)**: allCode는 `write_file` 1회 후 종료(자가검증·테스트
  없음). Codex는 `test_todo.py`를 작성. from-scratch라 기존 테스트가 없어 auto-validate
  (run_tests)는 "no tests"로 trivial 통과 → 가치 없음. Codex의 가치는 테스트를
  **작성**하고 실행하는 것. 테스트 작성 여부는 상당 부분 모델 행동 의존이나, 프롬프트로
  유도 가능한 여지 있음(후속).

## 적용 (격차 ①-A)

- `language.py` `final_answer_request_text`(ko/en)에 Codex식 간결·plain 지침 추가:
  이모지·장식 머리글·홍보성 표현 금지, "한 일과 결과만 담백하게". 모든 라우트의 최종
  답변에 적용되는 중앙 chokepoint라 구현/수정/분석 보고 전반의 스타일이 Codex에
  근접.
- **검증**: 동일 구현 프롬프트 재실행 → 보고서 이모지 0개(이전 다수), 산문체 제거,
  기능 정상(EXIT 0). 전체 775 passed(무회귀; 기존 테스트는 substring만 확인).

## 남은 방향 (후속)

- 격차 ①-B(구현 시 테스트 동반 작성)는 모델 행동 의존도가 높음. modify 라우트의
  "테스트 추가 시 테스트 파일 수정" 지침은 이미 존재하나, **신규 구현 시 최소 스모크
  테스트 동반**을 유도하는 프롬프트는 과설계 위험과 trade-off가 있어 별도 평가 필요.
