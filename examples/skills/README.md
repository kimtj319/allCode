# 예시 스킬 모음

allCode의 [스킬](../../README.md#스킬-allcodeskills) 시스템에 바로 쓸 수 있는
재사용 작업 지침입니다. 이름과 한 줄 설명만 항상 모델에 노출되고, 본문은
모델이 `skill(<name>)`을 호출할 때 로드됩니다(progressive disclosure).

## 포함된 스킬
- **code-review** — 정확성·보안·성능·테스트·가독성 체크리스트 기반 코드 리뷰
- **commit-message** — Conventional Commits 형식 커밋 메시지 작성
- **pr-description** — 리뷰어 친화적 PR 제목·본문 작성
- **debug** — 가설-검증 기반 체계적 디버깅 절차
- **test-author** — 경계·실패 경로를 포함한 결정적 테스트 작성
- **security-review** — OWASP 관점의 보안 점검

## 설치
이 디렉터리의 스킬은 **예시(reference)**입니다. 프로젝트의 활성 스킬 목록
(`/skills`)에는 사용자가 `.allCode/skills/`에 직접 둔 스킬만 표시됩니다. 쓰고
싶은 스킬을 골라 복사하면, 그 순간부터 "내 커스텀 스킬"로 목록에 나옵니다.
```bash
mkdir -p .allCode/skills
cp examples/skills/code-review.md .allCode/skills/   # 원하는 것만 골라 복사
```
복사 후 TUI에서 `/skills`로 확인할 수 있고, 관련 작업 시 모델이 알맞은 스킬을
`skill(<name>)`로 로드합니다. (이 README는 스킬이 아니므로 `.allCode/skills/`에
함께 복사돼도 목록에 잡히지 않습니다.)

## 번들/템플릿 스킬 숨기기
프로젝트에 스킬을 **번들로 동봉하되 활성 목록에는 띄우지 않으려면**, 해당 스킬
frontmatter에 `template: true`(또는 `hidden: true`)를 추가하세요. 이런 스킬은
`/skills`와 모델의 `skill` 도구 어디에도 노출되지 않습니다 — 활성 목록은 항상
사용자가 직접 작성/채택한 커스텀 스킬만 보여줍니다.
```markdown
---
description: 사내 표준 리뷰 템플릿
template: true
---
...
```

## 직접 작성하기
`.allCode/skills/<name>.md`(단일 파일) 또는
`.allCode/skills/<name>/SKILL.md`(보조 파일 동봉 가능) 형식으로,
frontmatter의 `description`과 본문 지침을 작성하면 됩니다.

```markdown
---
description: 한 줄 설명 (모델이 언제 이 스킬을 쓸지 판단하는 기준)
---
여기에 모델이 따라야 할 구체적 지침을 적습니다.
```
