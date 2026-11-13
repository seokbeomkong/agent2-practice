"""FastAPI 서버: API와 프론트엔드 화면(frontend/)을 함께 제공한다.

실행: .venv\\Scripts\\python.exe -m uvicorn app:app --port 8000
접속: http://localhost:8000

API 키는 브라우저가 요청마다 X-Claude-Key 헤더로 보내고, 서버는 저장하지 않는다.
"""
import json
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import claude_api
from agents import a2a
from agents.audit import experts as audit_ex
from agents.audit import orchestrator as audit_orch
from agents.audit import store as audit_store
from agents.common import current_key, friendly_error, stream_run
from agents.orchestra import feedback_agent  # noqa: F401 - Feedback Agent를 A2A 서버로 등록
from agents.orchestra import orchestrator as orche
from agents.orchestra.cat_agent import mcp, mcp_app
from labs import dashboard, persona

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "sample_reports"
MAX_PDF = 30 * 1024 * 1024  # Claude 요청 한도(32MB) 아래로

@asynccontextmanager
async def lifespan(_app):
    # A2A 서버(FastA2A)의 작업자와 MCP 세션 관리자를 앱과 함께 켜고 끈다.
    # 보험심사팀 전문가는 화면에서 추가/삭제할 수 있어 Agent마다 따로 켜고 끈다.
    audit_ex.register_all()
    await a2a.start_all()
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield
    await a2a.stop_all()


app = FastAPI(title="에이전트 실습실", lifespan=lifespan)


@app.exception_handler(claude_api.ClaudeError)
async def claude_error(_, e: claude_api.ClaudeError):
    # Claude 쪽 오류는 화면에 그대로 보여 줄 수 있는 문장과 상세 내용으로 돌려준다.
    return JSONResponse({"error": e.message, "detail": e.detail}, status_code=e.status)


def need_key(key: str | None) -> str:
    if not key or not key.startswith("sk-ant-"):
        raise HTTPException(401, "API 키가 없습니다. 첫 화면에서 키를 다시 입력해 주세요.")
    return key


# ── 공통: API 키 연결 테스트
@app.post("/api/key-test")
async def key_test(x_claude_key: str | None = Header(None)):
    # 키 확인용 짧은 호출: 생각에 쓰는 토큰까지 고려해 max_tokens를 넉넉히 두고 effort는 낮춘다.
    await claude_api.create(need_key(x_claude_key), max_tokens=2048, effort="low",
                            messages=[{"role": "user", "content": "연결 테스트입니다. '확인'이라고만 답해 주세요."}])
    return {"ok": True, "model": claude_api.MODEL}


# ── CH3 불량 리포트 분석
@app.get("/api/dashboard/samples")
def list_samples():
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(SAMPLES.glob("*.pdf"))]


def sample_path(name: str) -> Path:
    # 목록에 있는 파일 이름만 허용한다 (경로 조작 방지)
    names = {p.name: p for p in SAMPLES.glob("*.pdf")}
    if name not in names:
        raise HTTPException(404, "샘플 리포트를 찾을 수 없습니다.")
    return names[name]


@app.get("/api/dashboard/samples/{name}")
def get_sample(name: str):
    return FileResponse(sample_path(name), media_type="application/pdf")


@app.post("/api/dashboard/analyze")
async def analyze(file: UploadFile | None = File(None), sample: str | None = Form(None),
                  x_claude_key: str | None = Header(None)):
    """리포트 PDF 한 건을 분석한다. 업로드 파일(file) 또는 샘플 이름(sample) 중 하나를 받는다."""
    key = need_key(x_claude_key)
    if file is not None:
        pdf, name = await file.read(MAX_PDF + 1), file.filename or "report.pdf"
    elif sample:
        p = sample_path(sample)
        pdf, name = p.read_bytes(), p.name
    else:
        raise HTTPException(400, "분석할 PDF가 없습니다.")
    if len(pdf) > MAX_PDF:
        raise HTTPException(413, "PDF가 너무 큽니다. 30MB 이하로 올려 주세요.")
    if not pdf.startswith(b"%PDF"):
        raise HTTPException(400, f"{name}은(는) PDF 파일이 아닙니다.")
    return await dashboard.analyze_report(key, pdf, name)


class SummaryIn(BaseModel):
    reports: list[dict]


@app.post("/api/dashboard/summary")
async def summary(body: SummaryIn, x_claude_key: str | None = Header(None)):
    if not body.reports:
        raise HTTPException(400, "요약할 리포트가 없습니다.")
    return await dashboard.summarize(need_key(x_claude_key), body.reports)


class ChatIn(BaseModel):
    reports: list[dict]
    summary: dict | None = None
    messages: list[dict]  # [{"role": "user"|"assistant", "content": "..."}]


@app.post("/api/dashboard/chat")
async def chat(body: ChatIn, x_claude_key: str | None = Header(None)):
    """답변을 Server-Sent Events로 흘려보낸다: {"t": 글자조각} … {"done": true} 또는 {"error": …}"""
    key = need_key(x_claude_key)
    msgs = [{"role": m["role"], "content": str(m["content"])} for m in body.messages
            if m.get("role") in ("user", "assistant") and m.get("content")]
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(400, "질문이 비어 있습니다.")

    async def events():
        try:
            async for t in dashboard.chat_stream(key, body.reports, body.summary, msgs):
                yield f"data: {json.dumps({'t': t}, ensure_ascii=False)}\n\n"
            yield 'data: {"done": true}\n\n'
        except claude_api.ClaudeError as e:
            yield f"data: {json.dumps({'error': e.message, 'detail': e.detail}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def sse(events):
    """이벤트(dict)를 Server-Sent Events 형식으로 바꾼다."""
    async def gen():
        async for ev in events:
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ── CH4 페르소나 챗봇
class PersonaIn(BaseModel):
    name: str
    prompt: str


def _persona_or_404(pid: str):
    try:
        return persona.get_persona(pid)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/persona/personas")
def personas_list():
    return persona.load_personas()


@app.post("/api/persona/personas")
def persona_create(body: PersonaIn):
    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(400, "이름과 성격(시스템 프롬프트)을 모두 적어 주세요.")
    return persona.upsert_persona(None, body.name.strip()[:20], body.prompt.strip()[:2000])


@app.put("/api/persona/personas/{pid}")
def persona_update(pid: str, body: PersonaIn):
    _persona_or_404(pid)
    return persona.upsert_persona(pid, body.name.strip()[:20], body.prompt.strip()[:2000])


@app.delete("/api/persona/personas/{pid}")
def persona_delete(pid: str):
    _persona_or_404(pid)
    persona.delete_persona(pid)
    return {"ok": True}


@app.get("/api/persona/{pid}/chats")
def persona_chats(pid: str):
    _persona_or_404(pid)
    return persona.list_chats(pid)


@app.get("/api/persona/{pid}/chats/{cid}")
def persona_chat_read(pid: str, cid: str):
    _persona_or_404(pid)
    try:
        return persona.read_chat(pid, cid)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/persona/{pid}/memory")
def persona_memory(pid: str):
    _persona_or_404(pid)
    return {"text": persona.memory_path(pid).read_text(encoding="utf-8")}


@app.get("/api/persona/skills")
def persona_skills():
    return persona.list_skills()


@app.get("/api/persona/html/{name}")
def persona_html(name: str):
    f = persona.HTML / name
    if not (name.endswith(".html") and f.resolve().parent == persona.HTML.resolve() and f.exists()):
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    # Agent가 만든 문서는 격리(sandbox)해서 이 사이트의 키 저장소에 접근하지 못하게 한다.
    return FileResponse(f, media_type="text/html", headers={"Content-Security-Policy": "sandbox allow-scripts"})


class PersonaChatIn(BaseModel):
    persona_id: str
    chat_id: str | None = None
    message: str


@app.post("/api/persona/chat")
async def persona_chat(body: PersonaChatIn, x_claude_key: str | None = Header(None)):
    key = need_key(x_claude_key)
    _persona_or_404(body.persona_id)
    if not body.message.strip():
        raise HTTPException(400, "메시지가 비어 있습니다.")

    async def events():
        current_key.set(key)
        try:
            async for ev in persona.chat_stream(body.persona_id, body.chat_id, body.message.strip()[:4000]):
                yield ev
        except Exception as e:  # noqa: BLE001
            msg, detail = friendly_error(e)
            yield {"type": "error", "message": msg, "detail": detail}
        yield {"type": "done"}

    return sse(events())


# ── CH4 Agent Orchestration 학습 앱
class PromptIn(BaseModel):
    prompt: str
    disabled: list[str] = []  # 화면에서 꺼 둔 Agent


@app.get("/api/orchestra/graph")
def orchestra_graph():
    return orche.GRAPH


@app.post("/api/orchestra/run")
async def orchestra_run(body: PromptIn, x_claude_key: str | None = Header(None)):
    key = need_key(x_claude_key)
    text = body.prompt.strip()[:300]
    if not text:
        raise HTTPException(400, "문장을 입력해 주세요.")
    return sse(stream_run(lambda bus: orche.run(text, bus, set(body.disabled)), key))


# ── CH5 보험금 지급 판단 Agent App
def _audit(fn, *a, **kw):
    """저장소 오류를 HTTP 오류로 바꾼다."""
    try:
        return fn(*a, **kw)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/audit/graph")
def audit_graph():
    return audit_orch.graph()


class MeshIn(BaseModel):
    mesh: bool


@app.put("/api/audit/settings")
def audit_settings(body: MeshIn):
    return audit_store.save_settings(mesh=body.mesh)


class AgentIn(BaseModel):
    name: str
    role: str
    prompt: str


def _clean_agent(body: AgentIn) -> tuple[str, str, str]:
    name, role, prompt = body.name.strip()[:12], body.role.strip()[:30], body.prompt.strip()[:4000]
    if not name or not prompt:
        raise HTTPException(400, "이름과 역할 지시문(시스템 프롬프트)을 모두 적어 주세요.")
    return name, role, prompt


@app.get("/api/audit/agents")
def audit_agents():
    return [a | {"docs": audit_store.list_docs(a["id"])} for a in audit_store.load_agents()]


@app.post("/api/audit/agents")
async def audit_agent_add(body: AgentIn):  # async: 이벤트 루프에서 A2A 작업자를 바로 켜야 한다
    a = audit_store.upsert_agent(None, *_clean_agent(body))
    audit_ex.register(a["id"])  # 새 Agent를 A2A 서버로 바로 붙인다
    return a


@app.put("/api/audit/agents/{aid}")
def audit_agent_edit(aid: str, body: AgentIn):
    _audit(audit_store.get_agent, aid)
    return audit_store.upsert_agent(aid, *_clean_agent(body))


@app.delete("/api/audit/agents/{aid}")
async def audit_agent_delete(aid: str):
    _audit(audit_store.get_agent, aid)
    if len(audit_store.load_agents()) <= 1:
        raise HTTPException(400, "전문가는 최소 1명이 있어야 해요.")
    audit_store.delete_agent(aid)
    await a2a.unregister_agent(aid)
    return {"ok": True}


@app.get("/api/audit/agents/{aid}/docs")
def audit_docs(aid: str):
    _audit(audit_store.get_agent, aid)
    return _audit(audit_store.list_docs, aid)


@app.post("/api/audit/agents/{aid}/docs")
async def audit_doc_upload(aid: str, file: UploadFile = File(...)):
    _audit(audit_store.get_agent, aid)
    data = await file.read(audit_store.MAX_DOC + 1)
    return _audit(audit_store.add_doc, aid, file.filename or "문서", data)


@app.get("/api/audit/agents/{aid}/docs/{name}")
def audit_doc_get(aid: str, name: str):
    p = _audit(audit_store.doc_path, aid, name)
    return FileResponse(p, filename=p.name, headers={"Content-Security-Policy": "sandbox"})


@app.delete("/api/audit/agents/{aid}/docs/{name}")
def audit_doc_delete(aid: str, name: str):
    _audit(audit_store.get_agent, aid)
    _audit(audit_store.delete_doc, aid, name)
    return {"ok": True}


@app.get("/api/audit/cases")
def audit_cases():
    return audit_store.list_cases()


@app.post("/api/audit/cases")
def audit_case_new():
    return audit_store.new_case()


@app.get("/api/audit/cases/{cid}")
def audit_case_get(cid: str):
    c = _audit(audit_store.load_case, cid)
    return {k: v for k, v in c.items() if k not in ("memory", "orch_history")}


class CasePatch(BaseModel):
    status: str | None = None
    title: str | None = None


@app.patch("/api/audit/cases/{cid}")
def audit_case_patch(cid: str, body: CasePatch):
    kw = {k: v for k, v in body.model_dump().items() if v is not None}
    if "title" in kw:
        kw["title"] = kw["title"].strip()[:40] or "새 사건"
    c = _audit(audit_store.update_case, cid, **kw)
    return {k: c[k] for k in ("id", "title", "status")}


@app.delete("/api/audit/cases/{cid}")
def audit_case_delete(cid: str):
    _audit(audit_store.delete_case, cid)
    return {"ok": True}


class CaseRunIn(BaseModel):
    case_id: str
    case: str


@app.post("/api/audit/run")
async def audit_run(body: CaseRunIn, x_claude_key: str | None = Header(None)):
    key = need_key(x_claude_key)
    text = body.case.strip()[:2000]
    if not text:
        raise HTTPException(400, "사건 내용을 입력해 주세요.")
    _audit(audit_store.load_case, body.case_id)
    return sse(stream_run(lambda bus: audit_orch.run(body.case_id, text, bus), key))


# ── A2A 서버(/agents/{이름})와 MCP 서버(/mcp-server/mcp)
app.mount("/agents", a2a.AgentRouter())  # 실행 중 추가/삭제되는 Agent도 이름으로 찾아 넘긴다
a2a.HOST_APP = app
app.mount("/mcp-server", mcp_app)


# ── 프론트엔드 화면 (맨 마지막에 둬야 /api 경로를 가리지 않는다)
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
