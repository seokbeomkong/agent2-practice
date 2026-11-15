# CLAUDE.md

## 프로젝트 목적

`교안/` 폴더의 "하루만에 익히는 Agent 개발 과정" 교안(CHAPTER 1~5) 내용을 바탕으로, **수강생이 본인의 Claude API 키를 직접 입력해 교안의 실습 결과물을 바로 체험·테스트해 볼 수 있는 Web App**을 만든다.

교안은 따라 하며 만드는 방식인데, 이 App은 완성된 결과물을 한곳에 모아 두고 **실행해 보며 동작 원리를 이해**하게 하는 것이 목적이다. 수업 후 자택에서 복습하거나, 자신의 도메인에 적용할 아이디어를 얻는 용도로 쓴다.

## 핵심 요구사항

- 사용자가 화면에서 **Claude API 키를 직접 입력**하고, 연결 테스트(실패 시 상세 에러 표시)에 성공하면 본 화면으로 진입한다.
- API 키는 사용자가 직접 입력한 값만 사용한다. 서버·파일·저장소에 영구 저장하거나 로그로 남기지 않는다. 코드·문서에 키를 하드코딩하지 않는다.
- 교안의 각 실습 결과물을 메뉴(탭)별로 체험할 수 있게 한다.
- 각 결과물에는 "무엇을 하는 앱인지 / 어떤 개념을 배우는지" 설명을 함께 보여 준다.
- 동작 과정(Agent 사고 과정, Agent 간 통신, 로그)이 눈에 보이도록 한다.

## 교안 기반 체험 대상 (교안 챕터별 실습 결과물)

| 교안 | 결과물 | 배우는 개념 |
|---|---|---|
| CH3 | **불량 리포트 분석 Dashboard + 챗봇** — 스마트폰 불량 리포트 PDF를 Claude API로 분석 → 전체 요약 / Dashboard 탭 / 챗봇 대화 | AI Application (Claude API 연동) |
| CH4 | **페르소나 챗봇** — 캐릭터 선택·추가·편집(시스템 프롬프트), Tool(현재 시각, HTML 생성), Skill, 페르소나별 Memory | Deep Agents, Tool / Skill / Memory |
| CH4 | **Agent Orchestration 학습 앱** — Orchestrator → Latte → Cat(MCP) → Emoji ↔ Feedback(A2A) 흐름을 그래프로 시각화 | Subagent / Tool / MCP / A2A |
| CH5 | **보험금 지급 판단 Agent App (보험심사팀)** — Orchestrator + 법률(LegalReview) / 고객(CustomerReview) / 경영(CEO) Agent가 A2A Full-Mesh로 의견을 조율하고 결론 도출 | Supervisor, Full-Mesh, High Stakes 의사결정 |

CH1(환경 설정), CH2(Agent View 병렬 개발)는 도구 사용법 중심이라 App의 직접 체험 대상이 아니며, 필요 시 소개/안내 페이지에서 개념만 설명한다.

## 기술 스택 (교안 기준)

- 백엔드: Python 3.13, FastAPI (`app.py`)
- 프론트엔드: HTML + JavaScript (`frontend/`)
- Agent: Deep Agents 프레임워크 (`agents/{Agent이름}.py`, 공통은 `agents/common.py`)
- A2A: FastA2A, 표준 A2A 4단계(Agent Card → Message → Task 상태 → Artifact)를 따른다. 별도 서버/프로세스 없이 FastAPI의 `/agents/{이름}` 경로로 통신한다.
- LLM: Sonnet 5.5 (`claude-sonnet-5-5`, effort = medium)로 고정한다.

## 개발 규칙

- Subagent는 교안 예시인 Latte Agent에만 쓴다. 다른 Agent는 독립된 Deep Agent로 만들고 Tool로 호출한다.
- 코드는 리뷰하기 쉽도록 최소한으로 작성하고, 핵심 부분에는 초보자도 이해할 수 있는 주석을 단다.
- 프론트는 Agent 이름·개수를 코드에 적지 않고 서버가 보낸 값으로 그린다. (교안의 프론트-백엔드 계약)
- 디자인(UI/UX) 작업은 전역 규칙에 따라 `frontend-design` 스킬을 먼저 호출한다.
- 모든 사용자 대상 텍스트와 설명은 한국어로 작성한다.

## 현재 진행 상황

- 배포: **Vercel**(무료 Hobby)에 올린다. 서버리스라 요청마다 다른 인스턴스에서 실행되고 파일이 남지 않으므로, 사용자 데이터는 모두 `kv.py`의 저장소(배포: Upstash Redis, 로컬: `data/store.json`)에 둔다.
  - 방문자 구분: 브라우저 탭이 만든 랜덤 번호(`visitorId`, sessionStorage — API 키와 같은 수명)를 `X-Visitor-Id` 헤더(문서/HTML 링크는 `?v=`)로 보내고, 저장소 키는 `u:{방문자}:...`로 분리한다. 새 탭·새 접속은 빈 상태로 시작하고 새로고침은 이어진다. **연결 해제**를 누르면 `POST /api/session/clear`(`kv.purge_visitor`)가 그 방문자의 데이터를 모두 지우고 키·방문자 번호도 버린다. 탭을 그냥 닫은 경우에 대비해 마지막으로 쓴 뒤 24시간이 지나면 사라진다.
  - Vercel 한도에 맞춘 규칙: 함수 최대 300초(`vercel.json`), 요청 본문 4.5MB → 업로드 4MB 이하, 쓰기 가능한 곳은 임시 폴더뿐(Deep Agents 파일 공간은 실행 중에만 임시 폴더에 펼치고 끝나면 저장소로 되돌림), SSE는 15초마다 ping.
  - 사용 한도(공개 서버 보호): 캐릭터 12, 전문가 8, 전문가당 문서 5개·문서당 글자 60만자, 사건 30, 설치 Skill 1.5MB.
  - 환경변수: `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` (마켓플레이스 연동 시 `KV_REST_API_URL/TOKEN` 이름도 인식). Vercel에서 저장소가 없으면 파일에 몰래 저장하지 않고 안내 오류를 낸다. 확인: `/api/health`
- 기존 실습 내용·기능·노드/엣지 그래프를 유지하고 **개발 콘솔형 색상만** 적용한다. 기본 스타일은 `frontend/assets/common.css`, 색상 전용 덮어쓰기는 `frontend/assets/console-colors.css`에서 관리한다. 그래프·차트는 "다크 3색"(B안)으로 맞춘다. 색은 Subagent(주황 #c98500), MCP(청록 #199e70), A2A(파랑 #3987e5) 세 가지에만 쓴다. Tool, 요청, 노드는 무채색이고, 일하는 곳은 밝은 회백색(#e5eaf0)으로 켜진다. 이 세 색은 색약 검증을 통과했으며, 선 모양과 라벨로도 함께 구분한다. Dashboard 제품군 색도 같은 3색부터 쓴다. 제목은 "하루만에 익히는 Agent 개발 Demo"다.
- 흐름: 접속(홈 한 화면) → 오른쪽 위에서 API 키 입력·연결 테스트(`/api/key-test`) → 통과하면 같은 화면의 실습 네 가지(2×2 썸네일)가 켜짐 → 실습 화면. 연결 전에는 실습이 잠겨 있고, 실습 화면에서 돌아오면 이 탭에 남은 키로 연결된 상태로 보인다(연결 해제 가능). 키는 브라우저 `sessionStorage`에만 두고 요청마다 `X-Claude-Key` 헤더로 보낸다. 서버는 저장·로그하지 않는다.
- 실습 4개 모두 실제 Claude로 동작한다 (모델 `claude-sonnet-5-5`, effort `medium`)
  - CH3 불량 리포트 분석: HTTP 직접 호출(교안 지침: Anthropic SDK 미사용), PDF → 구조화 추출 → 요약 → Dashboard → 스트리밍 챗봇
  - CH4 페르소나 챗봇: Deep Agents. Tool(시각, HTML 생성, Skill 설치/관리), Skill, 캐릭터별 Memory(AGENTS.md), 채팅 기록, 사고 과정 실시간 표시 (모두 방문자별 저장소에 저장)
  - CH4 Orchestration: Orchestrator → Latte(Subagent) → Cat(MCP + Tool) → Emoji(Tool) ↔ Feedback(A2A, 재시도 최대 3번)
  - CH5 보험심사팀: 완전한 Full-Mesh(사람 → Orchestrator → 모든 전문가 Tool, 전문가끼리 모두 A2A). 부른 전문가가 다른 모든 전문가와 A2A로 최대 2번 조율(모두 동의 시 종료), 피드백 중 ask_peer로 직접 질의. Full-Mesh 끄기 시 Supervisor 구조. 사건별 대화(새 사건/목록/상태: 진행 중·완료·보류, 사건별 Agent 기억 저장), 전문가 추가/수정/삭제(실행 중 A2A 서버 동적 등록), 전문가별 참조 문서(PDF/txt/md, 글자만 뽑아 저장) 업로드/삭제 후 read_file로 읽고 답변, 답변 10줄 이내
- 모든 화면은 넓은 화면(901px 이상)에서 페이지 스크롤 없이 한 화면에 들어가는 구성이다. 실습 화면은 `common.js`의 `mountBar`가 `body.lab`을 붙이고, `common.css`가 창 높이에 맞춘다. 긴 내용은 각 패널 안에서만 스크롤한다. 좁은 화면(모바일)은 기존처럼 세로로 쌓고 스크롤한다.
- 보험심사팀 화면은 오른쪽 위에 그래프, 오른쪽 아래에 사건 대화(왼쪽)와 협의 로그(오른쪽)를 항상 보이는 패널로 나눠 둔다. 팝업·귀퉁이 버튼은 쓰지 않는다(노드 상세 팝업만 그래프 안에 뜬다).
- 글꼴은 전체 맑은 고딕(`--font`, `--display`)이다. 외부 웹폰트는 불러오지 않는다.
- 그래프 화면은 서버가 보낸 nodes/links(`/api/orchestra/graph`, `/api/audit/graph`)로만 그리고, 실행 이벤트(SSE)를 순서대로 재생한다.
- 노드를 클릭하면 그 Agent가 받은 요청·결과 전체가 팝업으로 열리고, 다시 클릭하면 닫힌다(`detail` 이벤트). 자동 말풍선은 쓰지 않는다.
- Orchestration 앱은 Latte/Cat/Emoji/Feedback을 켜고 끌 수 있다(꺼진 Agent는 서버에서도 빠짐, Emoji를 끄면 Feedback도 꺼짐).

## Deep Agents / A2A 규칙

- Subagent는 Latte Agent에만 쓴다(교안 예시). 새 Agent는 독립된 Deep Agent로 만들고 Tool로 호출한다.
- A2A는 FastA2A로 구현하고 표준 4단계(명함 확인 → 부탁 쪽지 → 진행 상황 → 결과 받기)를 `agents/a2a.py`의 함수 하나씩으로 둔다.
- 별도 서버/프로세스를 띄우지 않는다. A2A는 FastAPI 앱의 `/agents/{이름}`(이름으로 찾아 넘기는 `AgentRouter`, 실행 중 추가/삭제 가능), MCP는 `/mcp-server/mcp`에 붙이고 같은 프로세스 안에서 호출한다.
- A2A 작업자는 일감을 동시에 처리한다(Full-Mesh에서 서로 동시에 물어도 멈추지 않게).

## 파일 구조

- `app.py`: FastAPI. `/api/*`, A2A 서버(`/agents/{이름}`), MCP 서버(`/mcp-server`), `frontend/` 화면을 함께 제공 (Vercel도 이 파일의 `app`을 실행)
- `kv.py`: 방문자별 키-값 저장소 (Upstash Redis REST / 로컬 파일), 한도·저장소 오류 정의
- `vercel.json`, `.python-version`: Vercel 설정 (함수 300초, Python 3.12)
- `claude_api.py`: CH3용 Claude API HTTP 호출 도우미 (refusal fallback `fallbacks: "default"` 사용)
- `labs/dashboard.py`: CH3 프롬프트·JSON 스키마·분석/요약/챗봇
- `labs/persona.py`: CH4 페르소나 챗봇 (Tool, Skill, Memory, 채팅 기록)
- `agents/common.py`: 모델 생성, 실행 이벤트 버스(SSE), 오류 문구
- `agents/a2a.py`: FastA2A 서버 등록과 A2A 4단계 함수
- `agents/orchestra/`: `orchestrator.py`, `latte_agent.py`, `cat_agent.py`(MCP), `emoji_agent.py`, `feedback_agent.py`
- `agents/audit/`: `orchestrator.py`(그래프·실행), `experts.py`(전문가 실행·Full-Mesh 조율·참조 문서·A2A 등록), `store.py`(Agent·설정·사건·문서 저장)
- `data/store.json`: 로컬 실행 때만 생기는 저장 파일 (지우면 기본 캐릭터·기본 전문가 3명으로 다시 시작)
- `sample_reports/`: 교안 UNIT 2 형식의 2페이지 불량 리포트 PDF 5건 (`scripts/make_reports.py`로 생성)
- `frontend/`: `index.html`(홈: 키 입력 + 실습 목록), `gallery.html`(예전 주소를 index로 보내는 안내), `lab-*.html`(실습), `assets/common.css`, `assets/common.js`, `assets/graph.js`(Agent 그래프)

## 실행

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt   (샘플 PDF를 다시 만들 때만 requirements-dev.txt)
.venv\Scripts\python.exe -m uvicorn app:app --port 8000
```
접속: http://localhost:8000 (Python 3.13이 없어 3.12 가상환경을 사용 중)

- 이 PC는 Windows 스마트 앱 컨트롤이 일부 최신 네이티브 DLL(uuid_utils, xxhash, jiter, ormsgpack)을 차단해 `requirements.txt`에서 차단되지 않는 버전으로 고정했다.
- 테스트 시 `ANTHROPIC_BASE_URL` 환경변수로 가짜 Anthropic 서버를 지정할 수 있다.

## 참고

- 교안 원본: `교안/CHAPTER_1.html` ~ `CHAPTER_5.html`
- 세부 요구사항(PRD)과 구현 계획은 별도로 `docs/PRD.md`, `PLAN.md`에 작성한다. (아직 없음)
