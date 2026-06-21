# 인기 MCP 서버 카탈로그

자주 쓰이는 [Model Context Protocol](https://modelcontextprotocol.io) 서버를
allCode에 바로 추가할 수 있는 명령과 함께 정리했습니다. 각 서버는 `/mcp add`
(TUI) 또는 `allcode mcp add`(CLI)로 등록하며, 변경은 `.allCode/config.yaml`의
`mcp.servers`에 저장되어 **다음 실행부터** 적용됩니다.

> 사전 준비: `npx` 기반 서버는 Node.js, `uvx` 기반 서버는
> [uv](https://github.com/astral-sh/uv)가 필요합니다. 토큰이 필요한 서버는
> 해당 환경 변수를 셸이나 `.env`에 먼저 설정하세요 (config에는 값이 아니라
> 환경 변수명만 저장하는 것이 안전합니다).

---

## 토큰 없이 바로 쓰는 서버

### filesystem — 파일 읽기/쓰기/검색
지정한 디렉터리 안에서 안전하게 파일을 다룹니다.
```bash
allcode mcp add filesystem npx -y @modelcontextprotocol/server-filesystem /path/to/project
```

### git — 로컬 git 저장소 조작
diff·로그·블레임·커밋 등 git 작업을 노출합니다.
```bash
allcode mcp add git uvx mcp-server-git --repository /path/to/repo
```

### fetch — URL 가져와 마크다운으로 변환
웹 페이지를 읽어 LLM이 쓰기 좋은 텍스트로 변환합니다.
```bash
allcode mcp add fetch uvx mcp-server-fetch
```

### sequential-thinking — 단계적 추론 보조
복잡한 문제를 구조화된 사고 단계로 분해하도록 돕습니다.
```bash
allcode mcp add sequential-thinking npx -y @modelcontextprotocol/server-sequential-thinking
```

### memory — 지식 그래프 기반 영속 메모리
세션을 넘어 사실·관계를 저장/조회합니다.
```bash
allcode mcp add memory npx -y @modelcontextprotocol/server-memory
```

### context7 — 최신 라이브러리 문서 주입 (인기 1위)
버전별 최신 API 문서를 가져와 환각/구버전 예제를 줄입니다.
```bash
allcode mcp add context7 npx -y @upstash/context7-mcp
```
무료 사용은 토큰이 필요 없습니다. 한도를 늘리려면 `--api-key`를 추가하세요.

### playwright — 브라우저 자동화 (인기 2위)
실제 브라우저로 페이지를 탐색/조작/스냅샷합니다. Microsoft 공식.
```bash
allcode mcp add playwright npx @playwright/mcp@latest
```

### sqlite — 로컬 SQLite DB 질의
```bash
allcode mcp add sqlite uvx mcp-server-sqlite --db-path /path/to/app.db
```

### time — 시간/타임존 변환
```bash
allcode mcp add time uvx mcp-server-time
```

---

## 토큰이 필요한 서버

설정 후 해당 토큰 환경 변수를 셸/`.env`에 export 해야 합니다.

### github — 저장소·PR·이슈·워크플로 통합
`GITHUB_PERSONAL_ACCESS_TOKEN` 필요 ([토큰 발급](https://github.com/settings/tokens)).
```bash
allcode mcp add github npx -y @modelcontextprotocol/server-github
```

### brave-search — 웹 검색
`BRAVE_API_KEY` 필요 ([발급](https://brave.com/search/api/)).
```bash
allcode mcp add brave-search npx -y @modelcontextprotocol/server-brave-search
```

### postgres — PostgreSQL 읽기 전용 질의
```bash
allcode mcp add postgres npx -y @modelcontextprotocol/server-postgres postgresql://USER:PASS@HOST:5432/DB
```

### slack — Slack 워크스페이스 연동
`SLACK_BOT_TOKEN`, `SLACK_TEAM_ID` 필요.
```bash
allcode mcp add slack npx -y @modelcontextprotocol/server-slack
```

---

## 원격(HTTP/SSE) 서버 추가

URL로 연결하는 원격 서버는 `--http`(또는 `--sse`) 플래그를 씁니다.
```bash
allcode mcp add my-remote --http https://mcp.example.com/mcp
```

## 관리 명령

```bash
allcode mcp list            # 등록된 서버 목록
allcode mcp remove <name>   # 서버 삭제
```
TUI 안에서는 `/mcp`, `/mcp add ...`, `/mcp remove <name>`로 동일하게 관리합니다.

## config.yaml에 저장되는 형태 (예: filesystem)

```yaml
mcp:
  servers:
    - name: filesystem
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/project"]
      enabled: true
```

특정 서버를 잠시 끄려면 해당 항목의 `enabled: false`로 바꾸면 됩니다(다음
실행부터 로드되지 않습니다).

---

출처:
- [Awesome MCP Servers](https://mcpservers.org/)
- [50 Most Popular MCP Servers in 2026 — mcpmanager.ai](https://mcpmanager.ai/blog/most-popular-mcp-servers/)
- [Top 10 Most Popular MCP Servers in 2026 — mcp.directory](https://mcp.directory/blog/top-10-most-popular-mcp-servers)
- [@upstash/context7-mcp — npm](https://www.npmjs.com/package/@upstash/context7-mcp)
