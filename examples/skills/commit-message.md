---
description: Conventional Commits 규칙으로 커밋 메시지 작성 (스테이징된 변경 기반)
---
# 커밋 메시지 작성

[Conventional Commits](https://www.conventionalcommits.org) 형식으로 커밋
메시지를 작성한다. 먼저 `git diff --staged`(없으면 `git diff`)로 실제 변경을
읽고, 추측이 아니라 변경 내용에 근거해 작성한다.

## 형식
```
<type>(<scope>): <subject>

<body>

<footer>
```

- **type**: `feat` `fix` `docs` `style` `refactor` `perf` `test` `build`
  `ci` `chore` `revert` 중 하나.
- **scope**(선택): 영향받는 모듈/영역. 예: `auth`, `api`, `tui`.
- **subject**: 명령형 현재시제, 50자 이내, 마침표 없음. 무엇을 했는지.
- **body**(선택): 무엇을·왜 바꿨는지. 어떻게(코드)보다 의도를 설명. 72자 줄바꿈.
- **footer**(선택): `BREAKING CHANGE: ...`, 이슈 참조(`Closes #12`).

## 규칙
- 한 커밋은 한 가지 논리적 변경만. 여러 성격이 섞였으면 분리를 제안한다.
- 호환성을 깨면 `feat!:`처럼 `!`를 붙이거나 footer에 `BREAKING CHANGE`를 쓴다.
- 메시지는 영어 또는 한국어 중 저장소 컨벤션을 따른다(기존 로그 확인).

## 예시
```
fix(auth): refresh 토큰 만료 시 무한 재시도 방지

재발급 실패가 401을 반환하면 즉시 로그아웃 처리한다. 이전에는
같은 요청을 계속 재시도해 CPU를 점유했다.

Closes #142
```
