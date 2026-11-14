# Agent 개발 Demo

- 목적: 교안의 네 가지 실습 결과물을 Claude API 키로 체험하는 웹 앱.
- 구조: `app.py`(FastAPI), `frontend/`(HTML/JS/CSS), `labs/`, `agents/`.
- 실행: 의존성 설치 후 `python -m uvicorn app:app --port 8000`. 상세 규칙은 `CLAUDE.md` 참고.
- 디자인 변경은 색상만 허용한다. 기존 실습 내용, 기능, 문구(승인된 제목 제외), 배치, 글꼴, 노드·엣지 그래프와 상호작용은 보존한다.
- 색상은 `frontend/assets/console-colors.css`에서 변경한다. 기존 그래프의 색상 구분은 유지한다.
- 검증: 변경 전후 HTML/JS 차이와 그래프 노드·엣지·클릭/토글 동작을 비교한다. 색상 수정에 API 키나 유료 모델 호출은 필요 없다.
