"""보험심사팀 전문가 Agent (공통).

- 전문가 목록은 data/audit/agents.json에서 읽는다. 화면에서 추가/수정/삭제할 수 있다.
- 각 전문가는 Deep Agent이며 A2A 서버(/agents/{id})로도 노출된다.
- 전문가마다 참조 문서를 둘 수 있다. Agent는 read_file 도구로 문서를 읽고 근거로 답한다 (읽기만 허용).
- 사건(case)별로 자기가 한 말을 기억한다. 기억은 사건 파일에 함께 저장된다.

Full-Mesh가 켜져 있으면 Orchestrator가 부른 전문가는
  1) 먼저 의견(초안)을 내고 2) 다른 모든 전문가에게 A2A로 피드백을 요청해 3) 최대 2번 조율한다 (모두 동의하면 종료).
피드백을 주는 전문가도 필요하면 다른 전문가에게 A2A로 직접 물어볼 수 있다.
Full-Mesh가 꺼져 있으면(Supervisor 구조) 전문가는 자기 의견만 내고, 조율은 Orchestrator가 한다.
"""
import asyncio
import contextvars

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.tools import StructuredTool

from agents import a2a
from agents.audit import store
from agents.common import current_key, detail, emit, final_text, make_model, short

RULES = """
[답변 규칙]
- 답변은 10줄을 넘기지 않는다. 한국어로, 보고서 문체로 간결하게 쓴다.
- 이 앱은 의사결정을 돕는 프로토타입이다. 단정 대신 근거와 조건을 함께 제시한다.
- 다른 전문가의 피드백을 받으면 자기 관점을 지키되, 합리적인 의견은 받아들여 조금씩 의견을 수렴한다."""
MAX_ROUNDS = 2

# 실행 중 정보 (Orchestrator 실행마다 새로 넣는다)
current_case: contextvars.ContextVar[dict] = contextvars.ContextVar("case")          # 사건 데이터 (기억 포함)
mesh_on: contextvars.ContextVar[bool] = contextvars.ContextVar("mesh", default=True)
last_positions: contextvars.ContextVar[dict] = contextvars.ContextVar("positions")  # 전문가별 마지막 동의 여부
LIVE_CASES: dict[str, dict] = {}  # 실행 중인 사건 (A2A 작업자는 별도 작업이라 사건 번호로 찾아 쓴다)


def experts() -> dict[str, dict]:
    return {a["id"]: a for a in store.load_agents()}


def _memory(case: dict, agent: str) -> list[str]:
    return case.setdefault("memory", {}).setdefault(agent, [])


def _docs_prompt(aid: str) -> str:
    docs = store.list_docs(aid)
    if not docs:
        return ""
    names = "\n".join(f"- /{d['name']}.txt" for d in docs)
    return ("\n\n[참조 문서]\n당신에게 배정된 참조 문서입니다. 사건과 관련 있으면 read_file 도구로 읽고, "
            f"답변에 근거로 쓴 문서 이름을 밝히세요.\n{names}")


def _ask_peer_tool(me: str, requester: str, case: dict) -> StructuredTool:
    """피드백 중에 다른 전문가에게 A2A로 직접 물어보는 도구 (요청한 쪽과 자기 자신은 제외)."""
    team = experts()
    peers = [p for p in team if p not in (me, requester)]

    async def ask_peer(agent: str, question: str) -> str:
        if agent not in peers:
            return f"물어볼 수 있는 전문가는 {', '.join(peers)}입니다."
        emit("message", **{"from": me, "to": agent, "text": short(question)})
        detail(me, f"{team[agent]['name']}에게 질문 (A2A)", question, "note")
        answer = await a2a.ask(agent, me, question, context_id=case["id"], case_id=case["id"], hop=2)
        detail(me, f"{team[agent]['name']}의 답 (A2A)", answer, "in")
        emit("message", **{"from": agent, "to": me, "text": short(answer)})
        return answer

    names = ", ".join(f"{p}({team[p]['name']})" for p in peers)
    return StructuredTool.from_function(
        coroutine=ask_peer, name="ask_peer",
        description=f"다른 전문가 Agent에게 A2A로 의견을 묻는다. agent에는 {names} 중 하나를 쓴다. 꼭 필요할 때 한 번만 쓴다.")


async def run_expert(agent: str, text: str, case: dict, hop: int, requester: str = "", title: str = "받은 요청") -> str:
    """전문가 Agent를 실행한다. 이 사건에서 자기가 했던 말과 참조 문서를 함께 준다."""
    spec, mem = experts()[agent], _memory(case, agent)
    system = spec["prompt"] + RULES + _docs_prompt(agent)
    if mem:
        system += "\n\n[이 사건에서 지금까지 당신이 한 말]\n" + "\n---\n".join(mem[-6:])
    tools = [_ask_peer_tool(agent, requester, case)] if hop == 1 and len(experts()) > 2 else []
    detail(agent, title, text, "in")
    emit("status", agent=agent, state="working")
    try:
        deep = create_deep_agent(
            model=make_model(current_key.get(), max_tokens=2048), tools=tools, system_prompt=system,
            backend=FilesystemBackend(root_dir=store.doc_root(agent), virtual_mode=True),
            permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")])  # 문서는 읽기만
        reply = final_text(await deep.ainvoke({"messages": [{"role": "user", "content": text}]}))
    finally:
        emit("status", agent=agent, state="idle")
    mem.append(short(reply, 600))
    return reply


async def _a2a_handler(agent: str, text: str, metadata: dict, history: list) -> str:
    case = LIVE_CASES.get(metadata.get("case_id", "")) or {"id": metadata.get("case_id", "default")}
    title = "다른 전문가의 질문 (A2A)" if int(metadata.get("hop", 1)) == 2 else "피드백 요청 (A2A)"
    reply = await run_expert(agent, text, case, int(metadata.get("hop", 1)), metadata.get("from", ""), title)
    detail(agent, "보낸 답 (A2A Artifact)", reply)
    return reply


def register(agent_id: str):
    spec = experts()[agent_id]
    a2a.register_agent(agent_id, f"{spec['name']} 전문가: {spec['role']}",
                       lambda text, meta, hist, _a=agent_id: _a2a_handler(_a, text, meta, hist))


def register_all():
    for aid in experts():
        if aid not in a2a.APPS:
            register(aid)


# ── 전문가 호출 (Orchestrator의 Tool)
async def _feedback(lead: str, peer: str, request: str, case: dict) -> tuple[str, str, bool]:
    team = experts()
    emit("message", **{"from": lead, "to": peer, "text": f"{team[lead]['name']} 의견에 대한 피드백 요청"})
    answer = await a2a.ask(peer, lead, request, context_id=case["id"], case_id=case["id"], hop=1)
    agree = answer.strip().startswith("[동의]")
    detail(lead, f"{team[peer]['name']}의 피드백 ({'동의' if agree else '수정 요청'})", answer, "in")
    emit("message", **{"from": peer, "to": lead, "text": short(answer, 200), "agree": agree})
    return peer, answer, agree


async def consult(lead: str, question: str) -> str:
    """Orchestrator가 전문가(lead)를 부를 때 실행된다."""
    case, team = current_case.get(), experts()
    name = team[lead]["name"]
    emit("call", **{"from": "orch", "to": lead, "text": short(question)})
    draft = await run_expert(lead, f"[사건]\n{question}\n\n{name} 관점에서 의견을 내 주세요.", case, hop=0, title="Orchestrator의 요청")
    detail(lead, "1차 의견", draft)
    emit("log", agent=lead, text=f"의견: {short(draft, 300)}")

    peers = [p for p in team if p != lead]
    if not mesh_on.get() or not peers:  # Supervisor 구조: 조율 없이 의견만 돌려준다
        emit("call", **{"from": lead, "to": "orch", "text": "의견 보고"})
        return f"[{name} 전문가 의견]\n{draft}"

    positions: dict[str, dict] = {}
    for rnd in range(1, MAX_ROUNDS + 1):
        emit("round", n=rnd, max=MAX_ROUNDS, lead=lead)
        request = (f"[{rnd}번째 조율] {name} 전문가의 의견에 대해 당신의 입장에서 검토해 주세요.\n\n[사건]\n{question}\n\n"
                   f"[{name} 의견]\n{draft}\n\n첫 줄에 [동의] 또는 [수정 요청] 중 하나만 쓰고, 이어서 이유와 제안을 적어 주세요.")
        results = await asyncio.gather(*(_feedback(lead, p, request, case) for p in peers))
        positions = {p: {"agree": ok, "text": ans} for p, ans, ok in results}
        if all(v["agree"] for v in positions.values()):
            emit("log", agent=lead, text=f"{rnd}번째 조율에서 모든 전문가가 동의해 조율을 마칩니다.")
            break
        if rnd == MAX_ROUNDS:
            emit("log", agent=lead, text=f"조율 {MAX_ROUNDS}번을 모두 마쳤습니다. 남은 이견은 결론에 함께 적습니다.")
            break
        feedback = "\n\n".join(f"[{team[p]['name']} 전문가]\n{v['text']}" for p, v in positions.items())
        draft = await run_expert(lead, f"[사건]\n{question}\n\n[받은 피드백]\n{feedback}\n\n피드백을 반영해 수정한 의견을 내 주세요.",
                                 case, hop=0, title="받은 피드백 정리")
        detail(lead, f"{rnd}번째 조율 후 수정 의견", draft)
        emit("log", agent=lead, text=f"수정 의견: {short(draft, 300)}")

    last_positions.get().update({p: v["agree"] for p, v in positions.items()})
    emit("call", **{"from": lead, "to": "orch", "text": "조율 결과 보고"})
    others = "\n\n".join(f"[{team[p]['name']} 전문가 {'동의' if v['agree'] else '이견'}]\n{v['text']}" for p, v in positions.items())
    return f"[{name} 전문가 최종 의견]\n{draft}\n\n[다른 전문가 입장]\n{others}"


def expert_tools() -> list[StructuredTool]:
    """전문가마다 Orchestrator용 Tool을 만든다 (call_{id})."""
    tools = []
    for aid, spec in experts().items():
        async def call(case: str, _aid=aid) -> str:
            return await consult(_aid, case)
        how = "그 전문가가 다른 전문가들과 A2A로 조율한 결과를 돌려준다." if mesh_on.get() else "그 전문가의 의견을 돌려준다."
        tools.append(StructuredTool.from_function(
            coroutine=call, name=f"call_{aid}",
            description=f"{spec['name']} 전문가({spec['role']})에게 사건 검토를 맡긴다. {how} case에는 사건 내용 전체를 넣는다."))
    return tools
