"""Orchestrator: 사람의 요청을 받아 켜져 있는 Agent를 Latte → Cat → Emoji 순서로 부른다.

- Latte Agent : Subagent (task Tool)
- Cat Agent   : MCP + Tool
- Emoji Agent : Tool (Emoji Agent는 다시 Feedback Agent와 A2A로 협업)

단계별 실습을 위해 화면에서 Agent를 켜고 끌 수 있다. 꺼진 Agent는 도구 목록과 지시문에서 빠진다.
"""
from deepagents import create_deep_agent

from agents.common import current_key, detail, disabled_agents, emit, make_model, short, text_of
from agents.orchestra.cat_agent import load_cat_tools
from agents.orchestra.emoji_agent import call_emoji_agent
from agents.orchestra.latte_agent import LATTE_SUBAGENT

# (Agent, Orchestrator에게 줄 지시) — 켜져 있는 것만 순서대로 지시문에 넣는다
STEPS = [
    ("latte", "task 도구로 latte Subagent를 불러 문장을 라떼 선배 말투로 바꾼다."),
    ("cat", "cat_translate 도구로 앞 단계 결과를 고양이 말로 번역한다."),
    ("emoji", "call_emoji_agent 도구로 앞 단계 결과에 이모지를 추가한다."),
]

# 화면 계약: 노드와 연결 (프론트는 이 값으로만 그래프를 그린다). toggleable: 화면에서 켜고 끌 수 있는 Agent
GRAPH = {
    "nodes": [
        {"id": "human", "name": "사람", "role": "문장 입력", "kind": "human"},
        {"id": "orch", "name": "Orchestrator", "role": "순서 조율", "kind": "hub"},
        {"id": "latte", "name": "Latte", "role": "라떼 선배 말투", "toggleable": True},
        {"id": "cat", "name": "Cat", "role": "고양이 말 번역", "toggleable": True},
        {"id": "emoji", "name": "Emoji", "role": "이모지 추가", "toggleable": True},
        {"id": "feedback", "name": "Feedback", "role": "이모지 평가", "toggleable": True, "requires": "emoji"},
    ],
    "links": [
        {"from": "human", "to": "orch", "kind": "request", "label": "요청"},
        {"from": "orch", "to": "latte", "kind": "subagent", "label": "Subagent"},
        {"from": "orch", "to": "cat", "kind": "mcp", "label": "MCP + Tool"},
        {"from": "orch", "to": "emoji", "kind": "tool", "label": "Tool"},
        {"from": "emoji", "to": "feedback", "kind": "a2a", "label": "A2A"},
    ],
}
TOGGLEABLE = {n["id"] for n in GRAPH["nodes"] if n.get("toggleable")}


def build_prompt(enabled: list[str]) -> str:
    steps = [text for agent, text in STEPS if agent in enabled]
    if not steps:
        return "당신은 Orchestrator입니다. 지금은 켜진 Agent가 없습니다. 사람이 보낸 문장을 그대로 답하세요."
    lines = "\n".join(f"{i}. {t}" for i, t in enumerate(steps, 1))
    return (f"당신은 Orchestrator입니다. 사람이 보낸 문장을 아래 순서대로 다른 Agent에게 맡겨 변환합니다.\n{lines}\n"
            "첫 단계에는 사람이 보낸 문장을, 다음 단계에는 앞 단계의 결과를 그대로 넘깁니다. "
            "순서를 지키고 한 번에 하나씩 부르세요. 목록에 없는 도구는 쓰지 마세요.\n"
            "마지막에는 마지막 단계의 결과 문장만 그대로 답하세요.")


async def run(prompt: str, bus, disabled: set[str] | None = None) -> None:
    off = frozenset((disabled or set()) & TOGGLEABLE)
    if "emoji" in off:  # Feedback은 Emoji를 통해서만 쓰인다
        off |= {"feedback"}
    disabled_agents.set(off)
    enabled = [a for a, _ in STEPS if a not in off]

    emit("call", **{"from": "human", "to": "orch", "text": prompt})
    detail("orch", "사람의 요청", prompt, "in")
    plan = " → ".join(a.capitalize() for a in enabled) or "없음 (원문 그대로)"
    detail("orch", "실행 계획", f"켜진 Agent 순서: {plan}" + (f"\n꺼진 Agent: {', '.join(sorted(a.capitalize() for a in off))}" if off else ""), "note")
    emit("status", agent="orch", state="working")

    tools = (await load_cat_tools() if "cat" in enabled else []) + ([call_emoji_agent] if "emoji" in enabled else [])
    agent = create_deep_agent(model=make_model(current_key.get(), max_tokens=2048), tools=tools,
                              subagents=[LATTE_SUBAGENT] if "latte" in enabled else [],
                              system_prompt=build_prompt(enabled))
    final = ""
    pending: set[str] = set()  # 진행 중인 Latte 호출 id
    # updates 스트림으로 Orchestrator가 Latte(Subagent)를 부르고 받는 것을 지켜본다.
    # (Subagent는 내부에서 이벤트를 못 보내므로 스트림에서 감지한다. 다른 Agent는 도구 안에서 직접 알린다)
    async for update in agent.astream({"messages": [{"role": "user", "content": prompt}]}, stream_mode="updates"):
        for node_out in update.values():
            msgs = node_out.get("messages", []) if isinstance(node_out, dict) else []
            msgs = getattr(msgs, "value", msgs)  # Overwrite 래퍼 대응
            for m in msgs if isinstance(msgs, list) else []:
                if m.type == "ai":
                    for call in getattr(m, "tool_calls", []) or []:
                        if call["name"] == "task" and call.get("args", {}).get("subagent_type") == "latte":
                            pending.add(call["id"])
                            text = call["args"].get("description", "")
                            emit("call", **{"from": "orch", "to": "latte", "text": short(text)})
                            detail("latte", "받은 요청", text, "in")
                            emit("status", agent="latte", state="working")
                    if not getattr(m, "tool_calls", None) and text_of(m.content).strip():
                        final = text_of(m.content).strip()
                elif m.type == "tool" and m.tool_call_id in pending:
                    pending.discard(m.tool_call_id)
                    result = m.content if isinstance(m.content, str) else text_of(m.content)
                    emit("status", agent="latte", state="idle")
                    detail("latte", "라떼 말투 변환 결과", result)
                    emit("log", agent="latte", text=f"라떼 말투로 변환: {short(result)}")
                    emit("call", **{"from": "latte", "to": "orch", "text": short(result)})
    emit("status", agent="orch", state="idle")
    detail("orch", "최종 결과", final)
    emit("call", **{"from": "orch", "to": "human", "text": short(final)})
    bus.emit("result", text=final)
