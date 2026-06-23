"""Generate the 100-scenario multi-turn stress-test matrix (6 genres).

Each scenario: id, genre, workspace policy, an initial prompt, and 1-2 organic
follow-up turns. Saved to allcode_test_matrix.json at the repo root.

Genres:
  1 project_impl        — build a stdlib project + follow-up feature/bugfix
  2 refactor            — improve seeded legacy code + alternatives/edge cases
  3 analysis            — analyze the allCode repo + component deep-dive (read-only)
  4 tech_qa             — concept Q&A + tail question with example code (no web)
  5 web_qa              — web-search trend/release Q&A + follow-up comparison
  6 web_impl            — search latest spec then build + spec-change update
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def projects() -> list[dict]:
    # (slug, what to build, follow-up A, follow-up B) — stdlib only, isolated ws
    pool = [
        ("todo_cli", "JSON 파일에 저장하는 todo CLI(add/list/done)", "due date(마감일) 필드와 'overdue' 필터를 추가해줘.", "done 처리된 항목을 30일 후 자동 정리하는 기능을 추가해줘."),
        ("kv_store", "TTL 만료를 지원하는 인메모리 key-value 저장소 클래스", "LRU 용량 제한(maxsize)을 추가해줘.", "만료/축출 이벤트를 콜백으로 알리는 기능을 추가해줘."),
        ("url_shortener", "인메모리 URL 단축기(encode/decode, base62)", "충돌 없는 커스텀 별칭(alias) 지원을 추가해줘.", "클릭 수 카운팅과 통계 조회를 추가해줘."),
        ("md2html", "간단한 Markdown→HTML 변환기(heading/bold/list)", "코드 블록(```)과 인라인 코드 변환을 추가해줘.", "링크 [text](url) 변환 시 XSS 방지 이스케이프를 추가해줘."),
        ("csv_stats", "CSV 컬럼 통계(평균/최소/최대/표준편차) 계산기", "결측치(빈 셀) 처리 옵션을 추가해줘.", "그룹별(group-by) 집계 기능을 추가해줘."),
        ("rate_limiter", "토큰 버킷 방식 rate limiter", "슬라이딩 윈도우 방식 대안 구현을 추가해줘.", "여러 키별 독립 버킷을 관리하도록 확장해줘."),
        ("state_machine", "선언적 유한상태기계(FSM) 엔진", "전이 가드(guard) 조건과 진입/이탈 콜백을 추가해줘.", "잘못된 전이 시 명확한 예외를 던지도록 보강해줘."),
        ("expr_eval", "사칙연산+괄호 지원 수식 평가기(재귀하강 파서)", "변수 바인딩과 거듭제곱(^) 연산을 추가해줘.", "0으로 나누기 등 오류를 친절한 메시지로 처리해줘."),
        ("ini_parser", "INI 설정 파일 파서(섹션/키-값/주석)", "값 타입 추론(int/bool/float)을 추가해줘.", "환경변수 치환 ${VAR} 지원을 추가해줘."),
        ("retry_deco", "지수 백오프 재시도 데코레이터", "특정 예외만 재시도하고 나머지는 즉시 전파하도록 추가해줘.", "지터(jitter)와 최대 대기시간 상한을 추가해줘."),
        ("graph_search", "그래프 BFS/DFS와 최단경로(BFS) 라이브러리", "다익스트라 가중 최단경로를 추가해줘.", "사이클 탐지 기능을 추가해줘."),
        ("template_engine", "{{var}} 치환과 {% for %} 루프 지원 미니 템플릿 엔진", "{% if %} 조건 블록을 추가해줘.", "정의되지 않은 변수에 대한 strict/lenient 모드를 추가해줘."),
        ("event_bus", "구독/발행(pub-sub) 이벤트 버스", "와일드카드 토픽 매칭을 추가해줘.", "구독자 예외가 다른 구독자에 영향 주지 않도록 격리해줘."),
        ("priority_queue", "이진 힙 기반 우선순위 큐", "decrease-key 연산을 추가해줘.", "동일 우선순위의 FIFO 안정성을 보장하도록 보강해줘."),
        ("json_diff", "두 JSON 객체의 깊은 차이(diff)를 계산하는 도구", "diff를 사람이 읽기 쉬운 텍스트로 렌더링하는 기능을 추가해줘.", "배열 요소 이동 감지를 추가해줘."),
        ("cron_parser", "cron 표현식 파서와 다음 실행시각 계산기", "범위/스텝(*/5, 1-5) 문법을 추가해줘.", "잘못된 표현식에 대한 검증과 오류 메시지를 보강해줘."),
        ("dice_roller", "TRPG 주사위 표기(2d6+3) 파서/계산기", "advantage/disadvantage 굴림을 추가해줘.", "통계(분포/기댓값) 출력 기능을 추가해줘."),
    ]
    out = []
    for slug, what, f1, f2 in pool:
        out.append({
            "genre": "1_project_impl",
            "workspace": f"output/mt/{slug}",
            "prompt": f"stdlib만 사용해 {what}를 구현하고 pytest 테스트도 작성해 통과시켜줘. 산출물은 현재 작업 디렉터리에만 생성해라.",
            "follow_ups": [f1, f2],
        })
    return out


def refactors() -> list[dict]:
    pool = [
        ("중첩 if로 할인율을 계산하는 함수", "def price(u, qty):\n    if u=='vip':\n        if qty>10: return qty*8\n        else: return qty*9\n    else:\n        if qty>10: return qty*9\n        else: return qty*10",
         "딕셔너리 매핑/전략 패턴 등 대안 구조도 제시해줘.", "qty가 음수이거나 등급이 미지정인 엣지 케이스를 처리해줘."),
        ("전역 변수로 상태를 공유하는 카운터 모듈", "count=0\ndef inc():\n    global count; count+=1; return count\ndef reset():\n    global count; count=0",
         "전역 없이 클래스/클로저로 캡슐화한 대안을 제시해줘.", "멀티스레드 환경에서의 동시성 엣지 케이스를 처리해줘."),
        ("반복문으로 리스트를 평탄화하는 함수", "def flat(xs):\n    r=[]\n    for x in xs:\n        if isinstance(x,list):\n            for y in x: r.append(y)\n        else: r.append(x)\n    return r",
         "임의 깊이 중첩을 처리하는 재귀/제너레이터 대안을 제시해줘.", "튜플/문자열 등 비리스트 이터러블 엣지 케이스를 처리해줘."),
        ("예외를 광범위하게 삼키는 파일 로더", "def load(p):\n    try:\n        return open(p).read()\n    except:\n        return None",
         "구체적 예외 처리/컨텍스트 매니저 대안을 제시해줘.", "권한 오류와 인코딩 오류를 구분 처리해줘."),
        ("문자열 연결로 SQL을 만드는 함수", "def q(name):\n    return \"SELECT * FROM users WHERE name='\"+name+\"'\"",
         "파라미터 바인딩 등 안전한 대안을 제시해줘.", "name에 따옴표/세미콜론이 든 인젝션 시도 엣지 케이스를 처리해줘."),
        ("매직 넘버가 흩어진 등급 판정 함수", "def grade(s):\n    if s>=90: return 'A'\n    elif s>=80: return 'B'\n    elif s>=70: return 'C'\n    else: return 'F'",
         "임계값을 데이터로 분리한 대안을 제시해줘.", "점수가 범위를 벗어나거나 None인 엣지 케이스를 처리해줘."),
        ("깊게 중첩된 콜백 스타일 처리 함수", "def run(a):\n    def step1(x):\n        def step2(y):\n            return y*2\n        return step2(x+1)\n    return step1(a)",
         "평탄한 파이프라인/합성 함수 대안을 제시해줘.", "중간 단계 실패 시 오류 전파 엣지 케이스를 처리해줘."),
        ("O(n^2) 중복 제거 함수", "def uniq(xs):\n    r=[]\n    for x in xs:\n        if x not in r: r.append(x)\n    return r",
         "순서 보존 O(n) 대안을 제시해줘.", "해시 불가능 요소(dict 등) 엣지 케이스를 처리해줘."),
        ("긴 파라미터 목록을 받는 생성 함수", "def make(a,b,c,d,e,f,g=0,h=0):\n    return (a,b,c,d,e,f,g,h)",
         "dataclass/설정 객체로 묶는 대안을 제시해줘.", "필수/선택 인자 검증 엣지 케이스를 처리해줘."),
        ("가변 기본 인자 버그가 있는 함수", "def add(item, bucket=[]):\n    bucket.append(item); return bucket",
         "올바른 패턴과 대안을 제시해줘.", "동시 호출 간 상태 공유 엣지 케이스를 설명·처리해줘."),
        ("수동 인덱스로 두 리스트를 합치는 함수", "def merge(a,b):\n    r=[]\n    for i in range(len(a)):\n        r.append((a[i],b[i]))\n    return r",
         "zip/itertools 대안을 제시해줘.", "길이가 다른 두 리스트 엣지 케이스를 처리해줘."),
        ("문자열 포맷을 % 연산으로 하는 로거", "def log(lvl,msg):\n    print('['+lvl+'] '+msg)",
         "구조화 로깅/f-string 대안을 제시해줘.", "msg에 개행/제어문자가 든 엣지 케이스를 처리해줘."),
        ("재귀 피보나치(메모 없음)", "def fib(n):\n    if n<2: return n\n    return fib(n-1)+fib(n-2)",
         "메모이제이션/반복 대안을 제시해줘.", "음수/매우 큰 n 엣지 케이스를 처리해줘."),
        ("if-elif로 도형 면적을 계산하는 함수", "def area(kind,*d):\n    if kind=='rect': return d[0]*d[1]\n    elif kind=='circle': return 3.14*d[0]*d[0]",
         "다형성/클래스 기반 대안을 제시해줘.", "잘못된 인자 개수/음수 치수 엣지 케이스를 처리해줘."),
        ("중복 코드가 많은 두 검증 함수", "def v_email(s): return '@' in s and '.' in s\ndef v_phone(s): return s.isdigit() and len(s)>=9",
         "검증 규칙을 조합 가능한 구조로 리팩터링하는 대안을 제시해줘.", "빈 문자열/None 입력 엣지 케이스를 처리해줘."),
        ("동기 블로킹 방식 다중 URL 길이 합산(의사코드)", "def total(urls):\n    s=0\n    for u in urls:\n        s+=len(fetch(u))  # fetch는 느림\n    return s",
         "asyncio 기반 동시 처리 대안(의사코드)을 제시해줘.", "일부 URL 실패 시 부분 성공 처리 엣지 케이스를 설명해줘."),
    ]
    out = []
    for title, code, f1, f2 in pool:
        out.append({
            "genre": "2_refactor",
            "workspace": "none",
            "prompt": f"다음 {title}를 더 읽기 쉽고 견고하게 리팩터링해줘(설명 포함, 파일 생성은 불필요):\n```python\n{code}\n```",
            "follow_ups": [f1, f2],
        })
    return out


def analyses() -> list[dict]:
    pool = [
        ("src/allCode/agent의 라우팅/정책 구조", "ModelRouter와 RuleBasedRouter의 역할 차이를 더 깊이 설명해줘."),
        ("src/allCode/tools의 도구 실행/승인 흐름", "승인(approval) 모드 ask/auto/rules가 도구 실행에 어떻게 관여하는지 설명해줘."),
        ("src/allCode/agent/round_runner.py의 라운드 루프", "inspection 예산과 phase gate가 어떻게 상호작용하는지 설명해줘."),
        ("src/allCode/memory의 메모리/세션 구조", "세션 간 컨텍스트가 어떻게 유지·복원되는지 설명해줘."),
        ("src/allCode/agent/context_condensation.py의 컨텍스트 압축", "윈도 인지 압축 예산이 어떻게 산정되는지 설명해줘."),
        ("src/allCode/tui의 터미널 UI 렌더링 구조", "resize 시 트랜스크립트가 어떻게 재렌더되는지 설명해줘."),
        ("src/allCode/agent/parallel_orchestrator.py의 병렬 오케스트레이션", "git worktree 격리와 머지 통합 흐름을 설명해줘."),
        ("src/allCode/agent/finalization.py의 완료 게이트", "회귀-안전 워딩 게이트가 언제 발동하는지 설명해줘."),
        ("src/allCode/llm의 모델 클라이언트/어댑터 구조", "OpenAI-compatible 어댑터의 스트리밍 처리 방식을 설명해줘."),
        ("src/allCode/generation의 프로젝트 생성 워크플로우", "스켈레톤-우선 생성과 검증/자가수정 흐름을 설명해줘."),
        ("src/allCode/config의 설정 로딩 우선순위", "CLI/env/project/user/default 병합 순서를 설명해줘."),
        ("src/allCode/agent/prompt_constraints.py의 제약 추출", "mutation/read-only 의도가 어떻게 판정되는지 설명해줘."),
        ("src/allCode/tools/builtin의 내장 도구 구성", "source_overview와 source_probe의 역할 차이를 설명해줘."),
        ("src/allCode/agent/recovery.py의 루프/관측 반복 탐지", "도구 호출 반복(loop)이 어떻게 감지·완화되는지 설명해줘."),
        ("전체 src/allCode 패키지의 계층 의존성", "core가 어떤 계층에 독립적이어야 하는지와 그 이유를 설명해줘."),
        ("src/allCode/tools/mcp의 MCP 통합 구조", "stdio와 http 클라이언트의 차이를 설명해줘."),
        ("src/allCode/agent/model_router.py의 라우팅 병합 로직", "저신뢰(confidence) 결정이 어떻게 보정되는지 설명해줘."),
    ]
    out = []
    for target, f1 in pool:
        out.append({
            "genre": "3_analysis",
            "workspace": ".",
            "prompt": f"이 저장소에서 {target}를 분석해 핵심 동작과 설계 의도를 설명해줘(읽기 전용).",
            "follow_ups": [f1],
        })
    return out


def tech_qa() -> list[dict]:
    pool = [
        ("Python의 GIL이 무엇이고 멀티스레딩에 미치는 영향", "그렇다면 CPU 바운드 작업은 어떻게 병렬화하는 게 좋은지 예시 코드와 함께 알려줘."),
        ("asyncio의 이벤트 루프와 코루틴 동작 원리", "await가 블로킹을 어떻게 양보하는지 간단한 예시 코드로 보여줘."),
        ("파이썬 데코레이터의 작동 방식", "인자를 받는 데코레이터를 만드는 예시 코드를 보여줘."),
        ("제너레이터와 이터레이터의 차이", "메모리 효율적인 파일 읽기 제너레이터 예시를 보여줘."),
        ("컨텍스트 매니저(with)의 원리", "contextlib.contextmanager로 만든 예시를 보여줘."),
        ("dataclass와 일반 클래스의 차이", "frozen=True와 기본값 팩토리를 쓰는 예시를 보여줘."),
        ("덕 타이핑과 타입 힌트의 관계", "Protocol을 이용한 구조적 서브타이핑 예시를 보여줘."),
        ("얕은 복사와 깊은 복사의 차이", "중첩 리스트에서 차이가 드러나는 예시 코드를 보여줘."),
        ("파이썬 가상환경(venv)과 의존성 관리 개념", "프로젝트 초기 설정 명령 흐름을 예시로 보여줘."),
        ("HTTP의 idempotent 메서드 개념", "PUT과 POST의 차이를 예시 요청으로 설명해줘."),
        ("REST와 RPC 스타일 API의 차이", "같은 기능을 두 스타일로 설계한 예시를 보여줘."),
        ("데이터베이스 인덱스가 조회를 빠르게 하는 원리", "복합 인덱스의 컬럼 순서가 중요한 이유를 예시로 설명해줘."),
        ("프로세스와 스레드의 차이", "파이썬에서 각각을 쓰는 간단한 예시를 보여줘."),
        ("캐시 무효화 전략(TTL/LRU)의 개념", "LRU 캐시를 functools로 적용하는 예시를 보여줘."),
        ("Big-O 표기법과 시간복잡도 개념", "리스트 탐색 vs 집합 탐색의 복잡도 차이를 예시로 보여줘."),
        ("git rebase와 merge의 차이", "협업 시 각각을 언제 쓰는지 예시 흐름으로 설명해줘."),
        ("환경변수로 설정을 주입하는 12-factor 개념", "파이썬에서 안전하게 비밀값을 읽는 예시를 보여줘."),
    ]
    out = []
    for q, f1 in pool:
        out.append({
            "genre": "4_tech_qa",
            "workspace": "none",
            "prompt": f"{q}에 대해 설명해줘.",
            "follow_ups": [f1],
        })
    return out


def web_qa() -> list[dict]:
    pool = [
        ("최신 안정 버전 Python의 주요 새 기능", "이전 메이저 버전과 비교했을 때 마이그레이션에서 주의할 점을 정리해줘."),
        ("FastAPI의 최근 릴리스 주요 변경점", "Flask와 비교했을 때의 장단점을 정리해줘."),
        ("최신 LLM 코딩 에이전트 트렌드", "터미널형 에이전트와 IDE 통합형의 차이를 비교해줘."),
        ("Rust 언어의 최근 안정화된 주요 기능", "Go와 비교한 동시성 모델의 차이를 정리해줘."),
        ("React의 최근 메이저 변경점", "Vue와 비교한 상태관리 접근의 차이를 정리해줘."),
        ("PostgreSQL 최신 버전의 주요 개선점", "MySQL과 비교한 트랜잭션/확장성 차이를 정리해줘."),
        ("Kubernetes 최근 릴리스 트렌드", "Docker Compose 대비 언제 과한지/적절한지 비교해줘."),
        ("uv/poetry 등 파이썬 패키징 도구 동향", "pip 대비 장단점을 비교해줘."),
        ("최신 웹 인증 표준(Passkey/WebAuthn) 동향", "기존 비밀번호 방식과 비교한 보안 이점을 정리해줘."),
        ("최신 프런트엔드 빌드 도구(Vite 등) 동향", "Webpack과 비교한 빌드 속도 차이의 원인을 설명해줘."),
        ("WASM(WebAssembly)의 최근 활용 트렌드", "JavaScript와 비교한 성능/사용처 차이를 정리해줘."),
        ("HTTP/3와 QUIC의 채택 동향", "HTTP/2와 비교한 핵심 차이를 정리해줘."),
        ("최신 컨테이너 런타임 동향", "containerd와 다른 런타임을 비교해줘."),
        ("최신 타입스크립트 메이저 변경점", "자바스크립트 대비 도입 비용/이점을 비교해줘."),
        ("오픈소스 벡터 데이터베이스 동향", "전통적 RDB 대비 적합한 사용처를 비교해줘."),
        ("최신 CI/CD 도구 트렌드", "GitHub Actions와 다른 도구를 비교해줘."),
        ("Edge 컴퓨팅/서버리스 최근 동향", "전통적 서버 배포와 비교한 트레이드오프를 정리해줘."),
    ]
    out = []
    for q, f1 in pool:
        out.append({
            "genre": "5_web_qa",
            "workspace": "none",
            "prompt": f"웹 검색을 사용해 {q}을(를) 최신 정보로 알려줘. 출처도 함께.",
            "follow_ups": [f1],
        })
    return out


def web_impl() -> list[dict]:
    pool = [
        ("env_reader", "현재 안정 버전 Python에서 권장되는 방식으로 .env 파일을 읽는 작은 설정 로더", "권장 방식이 바뀌었다고 가정하고 그에 맞춰 수정해줘."),
        ("http_client", "표준 라이브러리만으로 GET/POST를 보내는 간단한 HTTP 클라이언트 래퍼", "타임아웃/재시도 모범 사례를 검색해 반영해줘."),
        ("semver", "최신 SemVer 명세에 맞는 버전 비교/파싱 유틸리티", "사전 릴리스(pre-release) 우선순위 규칙을 명세대로 보강해줘."),
        ("iso8601", "ISO-8601 날짜/시간 파싱·포맷 유틸리티(stdlib)", "타임존 오프셋 처리 규칙을 명세에 맞게 보강해줘."),
        ("jsonlines", "JSON Lines(jsonl) 포맷 읽기/쓰기 유틸리티", "최신 명세의 권장 인코딩/개행 처리를 반영해줘."),
        ("uuid_tool", "표준 라이브러리로 UUID를 생성/검증하는 유틸리티", "최신 UUID 버전(v7 등) 동향을 검색해 지원을 추가해줘."),
        ("toml_reader", "현재 Python 표준에서 권장하는 방식으로 TOML을 읽는 로더", "쓰기(write)는 어떤 도구가 권장되는지 검색해 반영해줘."),
        ("retry_policy", "HTTP 재시도 정책(백오프) 모범 사례를 반영한 유틸리티", "Retry-After 헤더 처리 권장사항을 반영해줘."),
        ("rate_headers", "표준 rate-limit 응답 헤더를 파싱하는 유틸리티", "최신 표준 초안(draft) 헤더 이름 변경을 반영해줘."),
        ("cron_spec", "표준 cron 명세를 따르는 표현식 검증기", "확장 문법(@hourly 등) 지원을 명세에 맞게 추가해줘."),
        ("color_convert", "웹 표준 색상(hex/rgb/hsl) 변환 유틸리티", "최신 CSS Color 명세의 표기법을 반영해줘."),
        ("slugify", "URL 슬러그 생성 유틸리티(유니코드 처리)", "권장 정규화 방식을 검색해 반영해줘."),
        ("password_rules", "최신 권장사항에 맞는 비밀번호 정책 검증기", "권장 길이/금지목록 정책 변경을 반영해줘."),
        ("mime_detect", "확장자 기반 MIME 타입 매핑 유틸리티", "최신 표준 MIME 타입 추가를 반영해줘."),
        ("lang_tags", "BCP-47 언어 태그 검증/정규화 유틸리티", "명세의 태그 형식 규칙을 보강해줘."),
        ("rfc_email", "이메일 주소 형식 검증기(현행 권장 규칙)", "국제화 이메일(IDN) 처리 권장사항을 반영해줘."),
        ("unit_convert", "SI 단위 변환 유틸리티(길이/무게/온도)", "표준 단위 기호 표기를 명세대로 보강해줘."),
    ]
    out = []
    for slug, what, f1 in pool:
        out.append({
            "genre": "6_web_impl",
            "workspace": f"output/mt/{slug}",
            "prompt": f"웹 검색으로 관련 최신 명세/모범 사례를 확인한 뒤, stdlib만 사용해 {what}와 pytest 테스트를 작성해 통과시켜줘. 산출물은 현재 작업 디렉터리에만.",
            "follow_ups": [f1],
        })
    return out


def main() -> int:
    groups = (projects() + refactors() + analyses() + tech_qa() + web_qa() + web_impl())[:100]
    scenarios = []
    for i, s in enumerate(groups, start=1):
        scenarios.append({"id": f"S{i:03d}", **s})
    matrix = {
        "version": 1,
        "total": len(scenarios),
        "genres": {
            "1_project_impl": "프로젝트 구현 + 후속 기능/버그수정",
            "2_refactor": "코드 수정/리팩토링 + 대안/엣지케이스",
            "3_analysis": "코드/아키텍처 분석 + 컴포넌트 심화",
            "4_tech_qa": "일반 기술 질문 + 꼬리질문/예시코드",
            "5_web_qa": "웹서치 일반 질문 + 후속 비교",
            "6_web_impl": "웹서치 활용 구현 + 스펙변경 수정",
        },
        "scenarios": scenarios,
    }
    out_path = ROOT / "allcode_test_matrix.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for s in scenarios:
        counts[s["genre"]] = counts.get(s["genre"], 0) + 1
    print(f"wrote {out_path} with {len(scenarios)} scenarios")
    for g, c in sorted(counts.items()):
        print(f"  {g}: {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
