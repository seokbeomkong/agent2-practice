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

- 배포 플랫폼(Vercel, Hostinger 등)은 미정이다. 우선 로컬에서 테스트하는 것을 목표로 한다.
- 디자인은 **팝 스티커**(라벤더 배경, 굵은 검정 테두리, 평평한 그림자, Black Han Sans + Noto Sans KR)로 확정했다. 색과 모양은 `frontend/assets/common.css` 상단의 토큰으로 관리한다.
- 흐름: 접속 → API 키 입력·연결 테스트(`/api/key-test`) → 통과해야만 실습 목록 → 실습 화면. 키는 브라우저 `sessionStorage`에만 두고 요청마다 `X-Claude-Key` 헤더로 보낸다. 서버는 저장·로그하지 않는다.
- 실습 4개 모두 실제 Claude로 동작한다 (모델 `claude-sonnet-5-5`, effort `medium`)
  - CH3 불량 리포트 분석: HTTP 직접 호출(교안 지침: Anthropic SDK 미사용), PDF → 구조화 추출 → 요약 → Dashboard → 스트리밍 챗봇
  - CH4 페르소나 챗봇: Deep Agents. Tool(시각, HTML 생성, Skill 설치/관리), Skill(`data/persona/ws/skills`), 캐릭터별 Memory(AGENTS.md), 채팅 기록 txt, 사고 과정 실시간 표시
  - CH4 Orchestration: Orchestrator → Latte(Subagent) → Cat(MCP + Tool) → Emoji(Tool) ↔ Feedback(A2A, 재시도 최대 3번)
  - CH5 보험심사팀: 완전한 Full-Mesh(사람 → Orchestrator → 모든 전문가 Tool, 전문가끼리 모두 A2A). 부른 전문가가 다른 모든 전문가와 A2A로 최대 2번 조율(모두 동의 시 종료), 피드백 중 ask_peer로 직접 질의. Full-Mesh 끄기 시 Supervisor 구조. 사건별 대화(새 사건/목록/상태: 진행 중·완료·보류, 사건별 Agent 기억 저장), 전문가 추가/수정/삭제(실행 중 A2A 서버 동적 등록), 전문가별 참조 문서(PDF/txt/md) 업로드/삭제 후 read_file로 읽고 답변, 답변 10줄 이내
- 그래프 화면은 서버가 보낸 nodes/links(`/api/orchestra/graph`, `/api/audit/graph`)로만 그리고, 실행 이벤트(SSE)를 순서대로 재생한다.
- 노드를 클릭하면 그 Agent가 받은 요청·결과 전체가 팝업으로 열리고, 다시 클릭하면 닫힌다(`detail` 이벤트). 자동 말풍선은 쓰지 않는다.
- Orchestration 앱은 Latte/Cat/Emoji/Feedback을 켜고 끌 수 있다(꺼진 Agent는 서버에서도 빠짐, Emoji를 끄면 Feedback도 꺼짐).

## Deep Agents / A2A 규칙

- Subagent는 Latte Agent에만 쓴다(교안 예시). 새 Agent는 독립된 Deep Agent로 만들고 Tool로 호출한다.
- A2A는 FastA2A로 구현하고 표준 4단계(명함 확인 → 부탁 쪽지 → 진행 상황 → 결과 받기)를 `agents/a2a.py`의 함수 하나씩으로 둔다.
- 별도 서버/프로세스를 띄우지 않는다. A2A는 FastAPI 앱의 `/agents/{이름}`(이름으로 찾아 넘기는 `AgentRouter`, 실행 중 추가/삭제 가능), MCP는 `/mcp-server/mcp`에 붙이고 같은 프로세스 안에서 호출한다.
- A2A 작업자는 일감을 동시에 처리한다(Full-Mesh에서 서로 동시에 물어도 멈추지 않게).

## 파일 구조

- `app.py`: FastAPI. `/api/*`, A2A 서버(`/agents/{이름}`), MCP 서버(`/mcp-server`), `frontend/` 화면을 함께 제공
- `claude_api.py`: CH3용 Claude API HTTP 호출 도우미 (refusal fallback `fallbacks: "default"` 사용)
- `labs/dashboard.py`: CH3 프롬프트·JSON 스키마·분석/요약/챗봇
- `labs/persona.py`: CH4 페르소나 챗봇 (Tool, Skill, Memory, txt 채팅 기록)
- `agents/common.py`: 모델 생성, 실행 이벤트 버스(SSE), 오류 문구
- `agents/a2a.py`: FastA2A 서버 등록과 A2A 4단계 함수
- `agents/orchestra/`: `orchestrator.py`, `latte_agent.py`, `cat_agent.py`(MCP), `emoji_agent.py`, `feedback_agent.py`
- `agents/audit/`: `orchestrator.py`(그래프·실행), `experts.py`(전문가 실행·Full-Mesh 조율·참조 문서·A2A 등록), `store.py`(Agent·설정·사건·문서 파일 저장)
- `data/persona/`, `data/audit/`: 실행 데이터 (자동 생성, 지우면 기본 캐릭터·기본 전문가 3명으로 다시 만들어짐)
- `sample_reports/`: 교안 UNIT 2 형식의 2페이지 불량 리포트 PDF 5건 (`scripts/make_reports.py`로 생성)
- `frontend/`: `index.html`(키 입력), `gallery.html`(실습 목록), `lab-*.html`(실습), `assets/common.css`, `assets/common.js`, `assets/graph.js`(Agent 그래프)

## 실행

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app:app --port 8000
```
접속: http://localhost:8000 (Python 3.13이 없어 3.12 가상환경을 사용 중)

- 이 PC는 Windows 스마트 앱 컨트롤이 일부 최신 네이티브 DLL(uuid_utils, xxhash, jiter, ormsgpack)을 차단해 `requirements.txt`에서 차단되지 않는 버전으로 고정했다.
- 테스트 시 `ANTHROPIC_BASE_URL` 환경변수로 가짜 Anthropic 서버를 지정할 수 있다.

## 참고

- 교안 원본: `교안/CHAPTER_1.html` ~ `CHAPTER_5.html`
- 세부 요구사항(PRD)과 구현 계획은 별도로 `docs/PRD.md`, `PLAN.md`에 작성한다. (아직 없음)
