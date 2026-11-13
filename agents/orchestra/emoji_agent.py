"""Emoji Agent: Tool 방식 + A2A.

Orchestrator와 별개인 독립 Deep Agent이며, Orchestrator는 Tool(call_emoji_agent)로 부른다.
Emoji Agent는 결과물을 Feedback Agent에게 A2A로 보내 피드백을 받고, 의견을 적극 반영해 고친다.
(피드백 재시도 최대 3번)
"""
from deepagents import create_deep_agent
from langchain_core.tools import tool

from agents import a2a
from agents.common import current_bus, current_key, detail, disabled_agents, emit, final_text, make_model, short

EMOJI_PROMPT = (
    "당신은 문장에 어울리는 이모지를 넣어 주는 Agent입니다. 문장의 뜻과 말투는 그대로 두고 이모지만 추가하세요.\n"
    "피드백을 받으면 적극적으로 반영해 다시 고칩니다. 완성된 문장만 답하세요."
)
MAX_RETRY = 3


@tool
async def call_emoji_agent(sentence: str) -> str:
    """완성된 문장에 이모지를 추가하는 Emoji Agent를 호출한다. Feedback Agent와 A2A로 피드백을 주고받아 결과를 다듬는다."""
    emit("call", **{"from": "orch", "to": "emoji", "text": short(sentence)})
    detail("emoji", "받은 문장", sentence, "in")
    agent = create_deep_agent(model=make_model(current_key.get(), max_tokens=1024), system_prompt=EMOJI_PROMPT)
    messages = [{"role": "user", "content": f"이 문장에 이모지를 추가해 줘:\n{sentence}"}]
    emit("status", agent="emoji", state="working")
    draft = final_text(await agent.ainvoke({"messages": messages}))
    detail("emoji", "이모지 초안", draft)
    emit("log", agent="emoji", text=f"이모지 초안: {short(draft)}")

    bus = current_bus.get()
    if "feedback" in disabled_agents.get():
        emit("log", agent="emoji", text="Feedback Agent가 꺼져 있어 피드백 없이 초안으로 마칩니다.")
    for attempt in range(1, MAX_RETRY + 1):
        if "feedback" in disabled_agents.get():
            break
        # Feedback Agent와 A2A 표준 4단계로 통신한다 (같은 대화 번호 = 같은 실행)
        feedback = await a2a.ask("feedback", "emoji", f"다음 문장을 평가해 줘:\n{draft}", context_id=bus.id if bus else "ctx")
        detail("emoji", f"받은 피드백 {attempt}번째 (A2A Artifact)", feedback, "in")
        if feedback.strip().startswith("[승인]"):
            emit("log", agent="emoji", text=f"Feedback Agent가 승인했습니다 ({attempt}번째 확인).")
            break
        messages += [{"role": "assistant", "content": draft},
                     {"role": "user", "content": f"Feedback Agent의 피드백을 반영해서 다시 고쳐 줘:\n{feedback}"}]
        draft = final_text(await agent.ainvoke({"messages": messages}))
        detail("emoji", f"피드백 반영 {attempt}번째 수정", draft)
        emit("log", agent="emoji", text=f"피드백 반영 ({attempt}/{MAX_RETRY}번째 재시도): {short(draft)}")
    detail("emoji", "최종 결과", draft)
    emit("status", agent="emoji", state="idle")
    emit("call", **{"from": "emoji", "to": "orch", "text": short(draft)})
    return draft
