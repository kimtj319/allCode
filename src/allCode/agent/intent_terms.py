"""Term tables and regexes for prompt intent extraction."""

from __future__ import annotations

import re

READ_ONLY_TERMS = (
    "read-only",
    "read only",
    "do not edit",
    "don't edit",
    "no changes",
    "no file changes",
    "수정 금지",
    "변경 금지",
    "파일 변경 금지",
    "수정하지",
    "수정하지 마",
    "수정하지마",
    "변경하지",
    "파일 수정은 하지",
    "파일은 수정하지",
    "절대 수정",
    "읽기만",
    "분석만",
)
NO_SHELL_TERMS = (
    "no shell",
    "don't run commands",
    "do not run commands",
    "명령 실행 금지",
    "셸 실행 금지",
    "쉘 실행 금지",
)
NO_NETWORK_TERMS = (
    "no network",
    "offline",
    "검색 금지",
    "외부 검색 금지",
    "네트워크 금지",
)
MODIFY_TERMS = (
    "implement",
    "create",
    "modify",
    "edit",
    "write",
    "fix",
    "add",
    "update",
    "delete",
    "generate",
    "scaffold",
    "refactor",
    "change",
    "구현",
    "생성",
    "수정",
    "고쳐",
    "추가",
    "작성",
    "삭제",
    "변경",
    "만들",
    "보강",
)
INSPECT_TERMS = (
    "inspect",
    "explain",
    "analyze",
    "review",
    "read",
    "find",
    "search",
    "describe",
    "분석",
    "설명",
    "검토",
    "찾아",
    "검색",
    "읽어",
)
OPERATE_TERMS = (
    "run",
    "test",
    "build",
    "compile",
    "install",
    "execute",
    "pytest",
    "npm",
    "cargo",
    "gradle",
    "mvn",
    "실행",
    "테스트",
    "빌드",
    "컴파일",
)
EXTERNAL_TERMS = (
    "latest",
    "current",
    "today",
    "search the web",
    "look up",
    "검색해서",
    "최신",
    "현재",
    "오늘",
    "공개 문서",
)
CONCEPTUAL_TERMS = (
    "why",
    "what",
    "how",
    "explain",
    "describe",
    "tell me",
    "reason",
    "benefit",
    "drawback",
    "difference",
    "compare",
    "concept",
    "왜",
    "이유",
    "무엇",
    "뭐",
    "어떤",
    "어떻게",
    "설명",
    "알려줘",
    "중요",
    "개념",
    "차이",
    "장점",
    "단점",
    "필요",
    "역할",
)
ENGLISH_CHANGE_COMMAND = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:implement|create|modify|edit|write|fix|add|update|delete|generate|scaffold|refactor|change)\b"
    r"|(?:can|could|would)\s+you\s+"
    r"(?:implement|create|modify|edit|write|fix|add|update|delete|generate|scaffold|refactor|change)\b",
    re.IGNORECASE,
)
KOREAN_CHANGE_COMMAND = re.compile(
    r"(?:구현|생성|수정|변경|추가|작성|삭제|보강|고쳐|만들)(?:해\s*줘|해줘|해주세요|하라|해라|하시오|하자|해야|어\s*줘|어줘|줘)"
)
KOREAN_CHANGE_CONNECTIVE = re.compile(
    r"(?:구현|생성|수정|변경|추가|작성|삭제|보강|고쳐|만들)(?:하고|해서|하여)"
)
KOREAN_TRAILING_COMMAND = re.compile(
    r"(?:실행|테스트|검증)(?:해\s*줘|해줘|해주세요|하라|해라|하시오)"
)
KOREAN_OPERATE_COMMAND = re.compile(
    r"(?:실행|테스트|검증|빌드|컴파일)(?:해\s*줘|해줘|해주세요|하라|해라|하시오)"
)
ENGLISH_OPERATE_COMMAND = re.compile(
    r"^\s*(?:please\s+)?(?:run|execute|rerun|build|compile|install)\b"
    r"|(?:can|could|would)\s+you\s+(?:run|execute|rerun|build|compile|install)\b"
    r"|\b(?:run|execute|rerun)\s+(?:the\s+)?(?:tests?|pytest|npm|cargo|gradle|mvn|build|compile)\b",
    re.IGNORECASE,
)
GENERATION_MARKERS = (
    "create a project",
    "generate project",
    "new project",
    "scaffold",
    "bootstrap",
    "프로젝트 생성",
    "새 프로젝트",
    "프로젝트를 생성",
    "프로젝트를 만들어",
    "프로젝트를 구축",
    "프로젝트를 완성",
    "플랫폼 프로젝트",
)
MULTI_ARTIFACT_TERMS = (
    "cli",
    "entrypoint",
    "config",
    "registry",
    "runner",
    "retry",
    "backoff",
    "logger",
    "jsonl",
    "audit",
    "plugin",
    "plugins",
    "commands",
    "modules",
    "tests",
    "pytest",
    "readme",
    "진입점",
    "설정",
    "레지스트리",
    "실행기",
    "재시도",
    "백오프",
    "로거",
    "감사",
    "플러그인",
    "명령",
    "모듈",
    "테스트",
    "문서",
)
PROJECT_OUTPUT_TERMS = (
    "project",
    "platform",
    "application",
    "package",
    "service",
    "프로젝트",
    "플랫폼",
    "애플리케이션",
    "패키지",
    "서비스",
)
UNSTABLE_KNOWLEDGE_TERMS = (
    "law",
    "legal",
    "regulation",
    "compliance",
    "price",
    "pricing",
    "cost",
    "market",
    "share",
    "benchmark",
    "kpi",
    "revenue",
    "roadmap",
    "budget",
    "forecast",
    "trend",
    "2025",
    "2026",
    "법률",
    "규정",
    "컴플라이언스",
    "가격",
    "비용",
    "시장",
    "점유율",
    "벤치마크",
    "실적",
    "매출",
    "로드맵",
    "예산",
    "전망",
    "동향",
    "지표",
)
