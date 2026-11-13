"""보험심사팀 Orchestrator: 사건을 받아 필요한 전문가를 Tool로 부르고, 결과로 결론을 낸다.

그래프 (Full-Mesh): 사람 → Orchestrator → 모든 전문가(Tool), 전문가끼리는 모두 A2A로 연결.
Full-Mesh를 끄면 Supervisor 구조가 된다 (전문가끼리 A2A 조율 없음).
"""
import time

from deepagents import create_deep_agent

from agents.audit import experts as ex
from agents.audit import store
from agents.common import current_key, detail, emit, final_text, make_model, short

PROMPT_MESH = """당신은 DSD 보험사 보험심사팀의 Orchestrator입니다. 사람이 보험 관련 사건이나 질문을 입력하면 전문가 Agent에게 검토를 맡기고 결론을 냅니다.

[전문가]
{team}

[진행 방법 - Full-Mesh]
- 전문가 한 명을 부르면, 그 전문가가 나머지 전문가들과 A2A로 의견을 조율한 결과를 가져옵니다.
- 그래서 보통은 사건의 핵심 쟁점을 맡을 전문가 한 명만 부르면 됩니다. 결과에 빠진 관점이 있을 때만 다른 전문가를 추가로 부르세요.
{tail}"""
PROMPT_SUPERVISOR = """당신은 DSD 보험사 보험심사팀의 Orchestrator입니다. 사람이 보험 관련 사건이나 질문을 입력하면 전문가 Agent에게 검토를 맡기고 결론을 냅니다.

[전문가]
{team}

[진행 방법 - Supervisor]
- 전문가끼리는 서로 소통하지 않습니다. 사건과 관련 있는 전문가를 각각 불러 의견을 듣고, 당신이 의견을 조율하세요.
{tail}"""
TAIL = """
[결론 작성]
- 10줄 이내. 첫 줄은 결론 한 문장 (예: 조건부 지급을 권고합니다.)
- 이어서 근거, 각 전문가의 입장, 남은 이견이나 확인할 점을 짧게 적습니다.
- 최종 판단은 사람 전문가가 합니다. 단정하지 말고 조건을 분명히 씁니다."""


def graph() -> dict:
    """화면 계약: 노드와 연결. 프론트는 이 값으로만 그래프를 그린다."""
    team = list(ex.experts().values())
    nodes = [{"id": "human", "name": "사람", "role": "사건 입력", "kind": "human", "color": "#14101F"},
             {"id": "orch", "name": "Orchestrator", "role": "사건 배분, 결론 정리", "kind": "hub", "color": "#FFD400"}]
    nodes += [{"id": a["id"], "name": a["name"], "role": a["role"], "kind": "expert", "color": a["color"],
               "docs": len(store.list_docs(a["id"]))} for a in team]
    links = [{"from": "human", "to": "orch", "kind": "request", "label": "요청"}]
    links += [{"from": "orch", "to": a["id"], "kind": "tool", "label": "Tool"} for a in team]
    links += [{"from": a["id"], "to": b["id"], "kind": "a2a", "label": "A2A"} for i, a in enumerate(team) for b in team[i + 1:]]
    return {"nodes": nodes, "links": links, "mesh": store.load_settings()["mesh"]}


async def run(case_id: str, question: str, bus) -> None:
    case = store.load_case(case_id)
    mesh = store.load_settings()["mesh"]
    team = ex.experts()
    if not team:
        raise RuntimeError("전문가 Agent가 없습니다. Agent 관리에서 전문가를 추가해 주세요.")
    ex.current_case.set(case)
    ex.LIVE_CASES[case["id"]] = case
    ex.mesh_on.set(mesh)
    ex.last_positions.set({})
    if not case["turns"]:
        case["title"] = short(question, 40)

    # 화면에 보낸 상세 기록을 모아 사건 파일에도 저장한다 (다시 열었을 때 팝업에 보이도록)
    saved: list[dict] = []
    orig_emit = bus.emit

    def tap(type, **data):
        if type == "detail":
            saved.append({k: data[k] for k in ("agent", "title", "text", "kind")} | {"time": time.strftime("%H:%M:%S")})
        orig_emit(type, **data)

    bus.emit = tap
    try:
        emit("call", **{"from": "human", "to": "orch", "text": short(question)})
        detail("orch", "사람의 요청", question, "in")
        detail("orch", "진행 방식", ("Full-Mesh: 부른 전문가가 다른 전문가들과 A2A로 조율합니다." if mesh else
                                   "Supervisor: 전문가끼리 소통하지 않고 Orchestrator가 조율합니다.")
               + f"\n전문가: {', '.join(a['name'] for a in team.values())}", "note")
        emit("status", agent="orch", state="working")
        team_txt = "\n".join(f"- call_{a['id']}: {a['name']} 전문가 ({a['role']})" for a in team.values())
        prompt = (PROMPT_MESH if mesh else PROMPT_SUPERVISOR).format(team=team_txt, tail=TAIL)
        agent = create_deep_agent(model=make_model(current_key.get(), max_tokens=4096), tools=ex.expert_tools(), system_prompt=prompt)
        history = case.setdefault("orch_history", [])
        conclusion = final_text(await agent.ainvoke({"messages": history + [{"role": "user", "content": question}]}))
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": conclusion}]
        emit("status", agent="orch", state="idle")
        detail("orch", "결론", conclusion)
        emit("call", **{"from": "orch", "to": "human", "text": "결론 전달"})
        agreements = dict(ex.last_positions.get())
        case["turns"].append({"question": question, "conclusion": conclusion, "agreements": agreements,
                              "names": {k: v["name"] for k, v in team.items()}, "mesh": mesh,
                              "details": saved, "time": time.time()})
        store.save_case(case)
    finally:
        bus.emit = orig_emit
        ex.LIVE_CASES.pop(case["id"], None)
    bus.emit("result", text=conclusion, agreements=agreements, names={k: v["name"] for k, v in team.items()},
             case={k: case[k] for k in ("id", "title", "status")})
