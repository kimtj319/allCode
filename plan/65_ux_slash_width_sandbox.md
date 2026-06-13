# 65. UX 검증: 슬래시 메뉴 / 창 크기 적응 / 샌드박스 (2026-06-14)

## 실 PTY/TTY 검증 결과

### ① 슬래시 명령어 (Codex 대비)
- ✅ 실행 정상: `/help`가 전체 명령 목록 출력, `/model` 실행 등. `/exit`·`/clear`도 동작.
- ✅ Tab 완성: Tab 시 오버레이 메뉴 표시 + 첫 매치 자동삽입, Tab 반복으로 순환.
- ❌ **`/` 입력 즉시 라이브 메뉴가 뜨지 않음** — Codex는 타이핑 즉시 필터형 메뉴를 보여주는데
  allCode는 Tab을 눌러야 함. (`terminal_input`의 overlay는 `_completion_state`가 있을 때만
  렌더되고, 타이핑은 그 상태를 비움.) → **보강 대상**

### ② 창 크기 적응 렌더링
- ✅ narrow(50칸): 초과 라인 0, 2칸 들여쓰기 유지하며 한국어 래핑.
- ✅ wide(110칸): 초과 0, 가로 구분선까지 너비에 맞춰 확장.
- ✅ 세션 중 리사이즈(60→100, COLUMNS 미고정): 새 답변이 새 너비(98)로 재래핑.
  (답변 렌더러가 `console.width`를 렌더 시점에 재검출.) → **변경 불필요**
  주의: 테스트에서 `COLUMNS` 환경변수를 고정하면 rich가 그 값을 써 리사이즈가 안 잡히는 것처럼
  보이나, 실제 터미널은 COLUMNS를 export하지 않아 정상 동작.

### ③ 생성/수정 시 샌드박스
- allCode는 별도 staging 디렉터리/OS 샌드박스가 아니라 **워크스페이스 격리(confinement)** 모델:
  - `resolve_under_root`/`safe_resolve_under_root`로 루트 하위 강제. `../`, 절대경로
    `/etc/passwd`, `sub/../../escape.py` 등 **모든 탈출 시도 차단(PathPolicyDeniedError)** 확인.
  - 승인 게이트(ask/auto/rules), 삭제는 `.allCode/trash` 이동(롤백), `EditTransaction`에
    rollback_payload 보존.
  - `config.workspace.sandbox_enabled`(기본 True)가 workspace.writable을 제어.
- 결론: 생성/수정은 워크스페이스 경계 안에서만 수행되며 탈출 불가. → **설계대로 동작, 변경 불필요**.

## 보강 작업 (①만 해당)
- terminal-native 입력에 **라이브 슬래시 메뉴** 추가: 컴포저 텍스트가 `/`로 시작하고 줄바꿈이
  없으면, 입력 중에도 매칭 명령(이름 prefix 우선, 없으면 substring)을 설명과 함께 오버레이로
  표시(표시 전용 — 텍스트·커서·Tab 순환 동작 불변). 기존 Tab 완성 경로는 그대로 유지.
- 무회귀(전체 테스트), PTY로 `/` 입력 즉시 메뉴 표시 재확인.
