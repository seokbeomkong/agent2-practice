"""Agent 공통 코드: 모델 만들기, 실행 중 이벤트 전달(화면 로그/그래프), 응답 텍스트 꺼내기."""
import asyncio
import contextvars
import os
import time
import uuid

from langchain_anthropic import ChatAnthropic

MODEL = "claude-sonnet-5-5"  # 교안 기준 모델 (effort = medium)


def make_model(api_key: str, max_tokens: int = 4096, thinking_display: str | None = None) -> ChatAnthropic:
    """사용자가 입력한 API 키로 Claude 모델을 만든다. 키는 이 요청 안에서만 쓰인다."""
    kw = dict(model=MODEL, anthropic_api_key=api_key, max_tokens=max_tokens,
              output_config={"effort": "medium"}, max_retries=2, default_request_timeout=300)
    if os.environ.get("ANTHROPIC_BASE_URL"):  # 테스트용 가짜 서버 주소
        kw["anthropic_api_url"] = os.environ["ANTHROPIC_BASE_URL"]
    if thinking_display:  # "summarized"면 생각 요약이 스트리밍으로 온다
        kw["thinking"] = {"type": "adaptive", "display": thinking_display}
    return ChatAnthropic(**kw)


def text_of(content) -> str:
    """LangChain 메시지 content(문자열 또는 블록 목록)에서 글자만 꺼낸다."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def final_text(result: dict) -> str:
    """agent.ainvoke 결과에서 마지막 답변 글자를 꺼낸다."""
    return text_of(result["messages"][-1].content).strip()


# ── 실행 이벤트: Agent들이 무엇을 하는지 화면(SSE)으로 흘려보내는 통로
class EventBus:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.queue: asyncio.Queue = asyncio.Queue()

    def emit(self, type: str, **data):
        self.queue.put_nowait({"type": type, "ts": time.time(), **data})


RUNS: dict[str, EventBus] = {}                       # run_id → 버스 (A2A 작업자가 찾아 쓸 수 있게)
current_bus: contextvars.ContextVar[EventBus | None] = contextvars.ContextVar("bus", default=None)
current_key: contextvars.ContextVar[str] = contextvars.ContextVar("key", default="")
disabled_agents: contextvars.ContextVar[frozenset] = contextvars.ContextVar("disabled", default=frozenset())


def emit(type: str, **data):
    bus = current_bus.get()
    if bus:
        bus.emit(type, **data)


def detail(agent: str, title: str, text: str, kind: str = "out"):
    """노드 팝업에 보여 줄 전체 내용 (자르지 않는다). kind: in(받은 요청) / out(결과) / note(판단)"""
    emit("detail", agent=agent, title=title, text=str(text), kind=kind)


def friendly_error(e: BaseException) -> tuple[str, str]:
    """예외를 (화면에 보여 줄 문장, 상세 내용)으로 바꾼다."""
    import anthropic
    import kv
    from claude_api import HINTS
    if isinstance(e, kv.StoreError):
        return e.message, e.detail
    while isinstance(e, BaseExceptionGroup) and e.exceptions:  # TaskGroup이 감싼 예외 풀기
        e = e.exceptions[0]
    if isinstance(e, anthropic.APIStatusError):
        err = (e.body or {}).get("error", {}) if isinstance(e.body, dict) else {}
        return HINTS.get(e.status_code, "Claude API 호출에 실패했습니다."), f"HTTP {e.status_code} / {err.get('type', '')}: {err.get('message', str(e))[:300]}"
    if isinstance(e, anthropic.APIConnectionError):
        return "Claude 서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.", type(e).__name__
    return "Agent 실행 중 오류가 발생했습니다.", f"{type(e).__name__}: {str(e)[:300]}"


async def stream_run(job, api_key: str):
    """job(bus)을 백그라운드로 실행하면서 버스의 이벤트를 차례로 내보낸다 (SSE용)."""
    bus = EventBus()
    RUNS[bus.id] = bus

    async def runner():
        current_bus.set(bus)
        current_key.set(api_key)
        try:
            await job(bus)
        except Exception as e:  # noqa: BLE001 - 화면에 오류를 보여 주기 위해 모두 잡는다
            msg, detail = friendly_error(e)
            bus.emit("error", message=msg, detail=detail)
        finally:
            bus.emit("done")

    task = asyncio.create_task(runner())
    try:
        while True:
            ev = await bus.queue.get()
            yield ev
            if ev["type"] == "done":
                break
    finally:
        task.cancel()
        RUNS.pop(bus.id, None)


def short(text: str, n: int = 140) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[: n - 1] + "…"
