# 부가기능 사용 예시 — 커스텀 커맨드 / 서브에이전트 정의

allCode가 시작 시 읽는 프로젝트 리소스 파일들의 작성 예시입니다.

## 1. 커스텀 슬래시 커맨드 — `.allCode/commands/<name>.md`

`/<파일명>` 으로 호출됩니다. `$ARGUMENTS`(또는 `{{args}}`)는 입력 인자로,
`@{경로}`는 파일 내용으로, `!{명령}`은 셸 실행 결과로 치환됩니다.

```markdown
# 변경 리뷰
다음 커밋되지 않은 변경을 검토하고 위험을 요약하라.

현재 diff:
!{git --no-pager diff --stat}

코딩 규칙:
@{AGENTS.md}

추가 요청: $ARGUMENTS
```

→ `/review-changes 보안 위주로` 처럼 호출.

## 2. 서브에이전트 정의 — `.allCode/agents/<name>.md`

`/agents` 로 목록을 확인합니다. frontmatter로 설명/모델/도구를 지정합니다.

```markdown
---
description: 디프를 버그/보안 관점으로 검토하는 리뷰어
model: wisenut/wise-lloa-max-v1.2.1
tools: read_file, search_files, source_overview
---
당신은 꼼꼼한 코드 리뷰어입니다. 정확성과 보안에 집중하고,
구체적 파일·라인과 재현 시나리오를 들어 지적하세요.
```

## 3. 온보딩 / 진단 / 세션

- `/init` — 위 `AGENTS.md` 초안을 코드베이스에서 자동 생성(있으면 `/init force`).
- `/doctor` — 설정·API 키·base_url·AGENTS.md·config 점검.
- `/export [경로]` — 현재 대화 트랜스크립트를 마크다운으로 저장.
- `/context` — 컨텍스트 토큰 사용량. `/theme dark|light` — 테마 전환.
- `allcode --name <이름>` 으로 세션 명명 → `allcode --resume <이름>` 으로 재개.
- `allcode --fork [세션]` — 기존 대화를 복제한 새 세션으로 분기.
- `/pr [제목]` — 변경 커밋·푸시 후 gh로 PR 생성.
