"""Feedback Agent: A2A 서버. Emoji Agent의 결과물을 보고 '이모지를 더 써야 한다'고 피드백한다."""
from deepagents import create_deep_agent

from agents import a2a
from agents.common import current_key, detail, emit, final_text, make_model, short

FEEDBACK_PROMPT = (
    "당신은 이모지 품질 검사관입니다. 문장에 이모지가 충분히 많고 곳곳에 잘 어울리게 들어가 있는지 평가합니다.\n"
    "기준: 이모지가 6개 이상이고 문장 중간에도 들어가 있으면 통과입니다. 그렇지 않으면 이모지를 더 많이 쓰라고 요청하세요.\n"
    "답의 첫 줄은 반드시 [승인] 또는 [수정 요청] 중 하나만 쓰고, 둘째 줄에 이유와 구체적인 제안을 한 문장으로 씁니다."
)


async def handle(text: str, metadata: dict, history: list) -> str:
    detail("feedback", "평가 요청 (A2A Message)", text, "in")
    emit("status", agent="feedback", state="working")
    try:
        agent = create_deep_agent(model=make_model(current_key.get(), max_tokens=1024), system_prompt=FEEDBACK_PROMPT)
        reply = final_text(await agent.ainvoke({"messages": [{"role": "user", "content": text}]}))
    finally:
        emit("status", agent="feedback", state="idle")
    detail("feedback", "승인" if reply.strip().startswith("[승인]") else "수정 요청", reply, "note")
    emit("log", agent="feedback", text=short(reply))
    return reply


feedback_a2a = a2a.register_agent("feedback", "이모지가 충분히 들어갔는지 평가하고 피드백하는 Agent입니다.", handle)
