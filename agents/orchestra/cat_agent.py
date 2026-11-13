"""Cat Agent: MCP + Tool 방식.

Cat Agent는 MCP 서버(FastMCP)의 Tool로 노출된다. 다른 App도 이 MCP 서버에 붙으면
같은 Agent를 쓸 수 있어서 확장성이 좋다. 이 수업에서는 별도 프로세스 없이
FastAPI 앱 안에 MCP 서버를 붙이고(/mcp-server), 같은 프로세스 안에서 호출한다.
"""
import httpx
from deepagents import create_deep_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from agents.common import RUNS, current_bus, current_key, detail, emit, final_text, make_model, short

CAT_PROMPT = (
    "당신은 고양이 번역가입니다. 전달받은 문장을 고양이 말투로 번역하세요.\n"
    "문장 끝마다 '냥'을 붙이고, 필요하면 '야옹', '골골' 같은 표현을 섞습니다. 번역한 문장만 답하세요."
)

# 같은 프로세스 안의 호출(mcp.local)과 로컬 접속만 허용한다 (DNS 리바인딩 보호)
mcp = FastMCP("cat-agent", stateless_http=True, json_response=True,
              transport_security=TransportSecuritySettings(
                  enable_dns_rebinding_protection=True,
                  allowed_hosts=["mcp.local", "localhost:*", "127.0.0.1:*"],
                  allowed_origins=["http://localhost:*", "http://127.0.0.1:*"]))


@mcp.tool(description="문장을 고양이 말로 번역해 주는 Cat Agent를 실행한다.")
async def cat_translate(sentence: str, ctx: Context) -> str:
    # MCP 요청 헤더로 실행 정보(API 키, 화면 버스)를 받는다
    headers = ctx.request_context.request.headers
    current_key.set(headers.get("x-claude-key", ""))
    current_bus.set(RUNS.get(headers.get("x-run-id", "")))
    emit("call", **{"from": "orch", "to": "cat", "text": short(sentence)})
    detail("cat", "받은 문장", sentence, "in")
    emit("status", agent="cat", state="working")
    try:
        agent = create_deep_agent(model=make_model(current_key.get(), max_tokens=2048), system_prompt=CAT_PROMPT)
        result = final_text(await agent.ainvoke({"messages": [{"role": "user", "content": sentence}]}))
    finally:
        emit("status", agent="cat", state="idle")
    detail("cat", "고양이 말 번역 결과", result)
    emit("log", agent="cat", text=f"고양이 말로 번역: {short(result)}")
    emit("call", **{"from": "cat", "to": "orch", "text": short(result)})
    return result


mcp_app = mcp.streamable_http_app()  # FastAPI에 /mcp-server로 붙인다 (경로: /mcp-server/mcp)


async def load_cat_tools() -> list:
    """MCP 클라이언트로 Cat Agent의 Tool 목록을 불러온다 (같은 프로세스 안에서 HTTP로 통신)."""
    def client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp_app), headers=headers,
                                 timeout=timeout or httpx.Timeout(300), auth=auth)

    bus = current_bus.get()
    client = MultiServerMCPClient({"cat": {
        "transport": "streamable_http",
        "url": "http://mcp.local/mcp",
        "headers": {"x-claude-key": current_key.get(), "x-run-id": bus.id if bus else ""},
        "httpx_client_factory": client_factory,
    }})
    return await client.get_tools()
