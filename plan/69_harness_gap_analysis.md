# 69. 에이전트 하네스 보강 항목 (vs OSS / 상용 코딩 에이전트) — 2026-06-14

비교 대상: 상용(Codex CLI, Claude Code, Cursor), OSS(Aider, Cline/Roo, OpenHands,
Continue, Goose). allCode 코드 근거 기반(추측 아님). **모델 역량이 아닌 하네스(엔지니어링)**
관점.

## 현재 allCode 하네스 (확인된 보유)
- 도구 14종: read/write/patch/delete_file, glob/search/list_tree/list_directory,
  run_command/run_tests, source_overview(repo map)/source_probe(AST), web_search/web_fetch.
- 소스 인텔리전스: repo map + AST probe + LSP 클라이언트(source_intelligence/service 연결).
- 컨텍스트: 압축(ContextCompactor), 멀티소스 섹션, 메모리(세션 노트/recent targets/대화 흐름),
  토큰 사용량 집계.
- 안전: 워크스페이스 경로 격리(탈출 차단) + 승인 모드(ask/auto/rules) + `.allCode/trash`
  롤백 + EditTransaction rollback_payload.
- 흐름: 모델 라우터, phase gate, 생성 워크플로(skeleton→impl→tests→validate→repair→report),
  evidence 기반 완료 검증/자가수리, 슬래시 명령(+라이브 메뉴), 멀티턴 메모리.

## 보강 필요 — 상용 에이전트(Codex/Claude Code/Cursor) 기준

| # | 항목 | 현황 | 격차/근거 | 우선도 |
|---|------|------|-----------|--------|
| 1 | **MCP (Model Context Protocol)** | 없음 | Codex·Claude Code·Cursor·Cline·Goose 모두 MCP로 외부 도구/데이터 연결. allCode는 도구가 14종 빌트인으로 고정 → 확장 불가. | **P0** |
| 2 | **서브에이전트/작업 위임** | 없음(순차 단일 루프) | Claude Code Task 툴, OpenHands 멀티에이전트. 대형 작업 분할·병렬 탐색 불가. | P1 |
| 3 | **이미지/멀티모달 입력** | 없음(텍스트만) | Claude Code·Cursor·Codex는 스크린샷/도식 입력. UI/디자인·에러 스샷 작업 불가. | P1 |
| 4 | **OS 레벨 샌드박스** | 경로격리+승인만 | Codex는 seatbelt/landlock, OpenHands는 Docker 런타임. allCode는 임의 셸(run_command)이 승인만 통과하면 시스템 접근 가능. | **P0(보안)** |
| 5 | **Hooks/확장점** | 없음 | Claude Code pre/post-tool hooks, 커스텀 명령. 정책/감사/자동화 주입 불가. | P2 |
| 6 | **@파일 멘션 + 커스텀 슬래시 명령** | 슬래시는 고정셋, @멘션 없음 | Codex/Claude/Cursor의 `@경로` 컨텍스트 첨부·사용자 정의 명령. | P2 |
| 7 | **병렬 도구 실행** | 순차(gather 없음) | 상용은 독립 read/search를 병렬 호출해 지연 단축. | P2 |
| 8 | **mid-turn steering / 큐잉** | Ctrl-C/`/stop`만 | 실행 중 추가 지시를 큐에 넣어 방향 수정(Claude Code/Codex)이 안 됨. | P2 |

## 보강 필요 — OSS 에이전트 기준

| # | 항목 | 현황 | 격차/근거 | 우선도 |
|---|------|------|-----------|--------|
| 9 | **git 통합(자동 커밋/diff 리뷰/undo)** | git 상태 읽기만, 커밋 도구 없음 | Aider의 핵심: 변경마다 자동 커밋 + `/undo`. allCode는 에이전트가 커밋/브랜치 불가, 사용자 대면 undo·checkpoint 명령 없음(내부 rollback은 있음). | **P1** |
| 10 | **체크포인트/타임라인 되돌리기** | 내부 rollback만, UI 없음 | Cline 체크포인트 타임라인, Cursor checkpoint. 턴 단위 되돌리기 UX 부재. | P1 |
| 11 | **시맨틱 검색/임베딩 인덱스** | AST·휴리스틱 repo map만 | Cursor·Continue는 임베딩 벡터 인덱스로 의미 기반 검색. 대형 레포에서 관련 코드 탐색 정확도. | P2 |
| 12 | **브라우저/런타임 도구** | 없음 | OpenHands·Cline 브라우저 툴(웹앱 확인·스크래핑). | P3 |
| 13 | **견고한 diff 적용 포맷** | patch_file=정확 search/replace | Aider/Codex의 unified-diff/anchored 패치 대비 정확매칭 의존 → 공백·문맥 변화에 취약. fuzzy/anchored 적용 보강 여지. | P1 |
| 14 | **표준 AGENTS.md 로딩** | `.allCode/ALLCODE.md`만 읽음 | Codex는 `AGENTS.md`, Claude는 `CLAUDE.md`를 프로젝트 지침으로 로드. allCode는 자체 파일만 → 표준 지침 파일 미반영(상호운용성). | P2 |
| 15 | **웹 검색 백엔드 기본 구성** | 코드 있음, 백엔드 미구성 | SearXNG/DDG 등 기본 백엔드 설정/문서화 필요(현재 "unavailable"). | P2 |

## 우선순위 로드맵
- **P0 (기반·보안, 먼저)**: ①MCP 클라이언트(외부 도구 확장의 표준 통로), ④run_command의
  OS 레벨 샌드박싱(또는 컨테이너 실행 옵션).
- **P1 (실사용 임팩트)**: ⑨git 자동 커밋+`/undo`, ⑩체크포인트 되돌리기 UX, ⑬diff 적용
  견고화, ②서브에이전트, ③이미지 입력.
- **P2 (편의·상호운용)**: ⑤hooks, ⑥@멘션/커스텀 명령, ⑦병렬 도구, ⑧mid-turn 큐잉,
  ⑪임베딩 검색, ⑭AGENTS.md 로딩, ⑮웹 백엔드 구성.
- **P3**: ⑫브라우저 도구.

## 비고
- allCode가 OSS 평균 대비 **앞서는 하네스**: 근거기반 소스분석(overview→probe→anti-hallucination
  guard), phase-gated 생성+자가수리, evidence 기반 완료 검증, 경로격리+trash 롤백.
- 위 격차는 대부분 **하네스로 메울 수 있는 것**(모델 무관). 특히 P0의 MCP·샌드박스는 표준화된
  확장/안전 토대라 우선 권장.

## 구현 진행 상황 (2026-06-14)

| 항목 | 우선도 | 상태 | 커밋 |
|------|--------|------|------|
| MCP stdio 클라이언트 (외부 도구 확장) | P0 | ✅ 완료 | `8bd2f7b` |
| run_command/run_tests OS 샌드박스(workspace-write) | P0 | ✅ 완료 | `374d821` |
| patch_file 공백/들여쓰기 허용 적용 | P1 | ✅ 완료 | `a7f2fbd` |
| 표준 AGENTS.md / CLAUDE.md 로딩 | P2 | ✅ 완료 | `043929c` |
| git 자동 커밋 + `/undo` | P1 | ✅ 완료 | `c1cc440` |
| 체크포인트/턴 되돌리기 UX | P1 | ✅ git `/undo`로 충족 | `c1cc440` |
| 서브에이전트/작업 위임 | P1 | ✅ 완료 | `1e3a1fb` |
| 이미지/멀티모달 입력 | P1 | ✅ 완료(배관; 비전모델 필요) | `4346ed5` |
| Hooks/확장점 | P2 | ⏸ 보류(소비자 없는 추측 인프라) | |
| @파일 멘션(해석) | P2 | ✅ 이미 동작(경로추출) / 컴포저 자동완성·커스텀명령은 보류 | — |
| 병렬 도구 실행 | P2 | ⏸ 보류(도구 루프가 상태공유 순차 → 회귀위험>가치) | |
| mid-turn steering/큐잉 | P2 | ⏸ 보류(루프·UI 변경, 중간 위험) | |
| 임베딩 시맨틱 검색 | P2 | ⏸ 보류(임베딩 백엔드 외부 의존) | |
| 웹 검색 백엔드 기본 구성 | P2 | ✅ 이미 기본값(duckduckgo_html) | — |
| 브라우저/런타임 도구 | P3 | ⏸ 보류(브라우저 자동화 외부 의존) | |

- 모든 완료 항목: 실제 동작 검증(MCP echo 서버 왕복, sandbox-exec 차단, flexible patch
  케이스, AGENTS.md 로딩) + 무회귀(현재 788 passed, 3 skipped). 기본값은 비파괴적
  (sandbox·MCP는 opt-in, flexible patch는 정확매치 우선·모호성 시 안전 raise).

## 최종 정리 (2026-06-14)
- **구현 완료(8)**: MCP, OS 샌드박스, flexible patch, AGENTS.md/CLAUDE.md, git 자동커밋+`/undo`,
  체크포인트(=git `/undo`), 서브에이전트(`task`), 이미지 입력 배관. 각 항목 실동작/실모델 검증
  + 로컬 테스트 + 무회귀.
- **이미 충족(2)**: 웹 검색 백엔드 기본값(duckduckgo_html), @mention 경로 해석(extract_prompt_paths).
- **보류(근거 명시)**: 병렬 도구(상태공유 순차 루프 회귀위험), hooks(소비자 부재), mid-turn 큐잉
  (위험), 임베딩 검색·브라우저(외부 의존). 컴포저 @-자동완성/커스텀 슬래시 명령은 UI 후속.
- 전체 테스트 796 passed, 3 skipped. 모든 완료 항목 기본값 비파괴(opt-in/하위호환).
