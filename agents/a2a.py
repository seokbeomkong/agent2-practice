"""A2A 통신 (FastA2A 사용, 표준 A2A 4단계를 함수 하나씩으로 나눴다).

① 명함 확인 (Agent Card)       : get_agent_card()   - 최초 1회
② 부탁 쪽지 보내기 (Message)    : send_message()     - 답으로 일감(Task)을 받는다
③ 진행 상황 확인하기 (Task 상태): wait_for_task()    - 접수됨 → 작업 중 → 완료/실패
④ 결과 받기 (Artifact)          : get_artifact()

별도 서버/프로세스를 띄우지 않는다. 각 Agent는 FastAPI 앱의 /agents/{이름} 경로에 붙은
FastA2A 앱이며, 같은 프로세스 안에서 HTTP(ASGI)로 통신한다.
"""
import asyncio
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

import anyio
import httpx
from fasta2a import FastA2A, Worker
from fasta2a.broker import InMemoryBroker
from fasta2a.client import A2AClient
from fasta2a.storage import InMemoryStorage

import kv
from agents.common import RUNS, current_bus, current_key, emit, short

STATE_KO = {"submitted": "접수됨", "working": "작업 중", "completed": "완료", "failed": "실패"}

# 이름 → FastA2A 앱 (register_agent로 등록)
APPS: dict[str, FastA2A] = {}
WORKERS: dict[str, Worker] = {}
HOST_APP = None  # app.py가 FastAPI 앱을 넣는다. 통신은 이 앱의 /agents/{이름} 경로로 한다.


# ── 서버 쪽: Agent를 A2A로 노출하기
Handler = Callable[[str, dict, list], Awaitable[str]]  # (받은 글, metadata, 이 대화의 이전 기록) → 답


@dataclass
class AgentWorker(Worker[list]):
    """FastA2A 작업자: 일감을 받아 Agent를 실행하고 결과를 Artifact로 남긴다."""
    handler: Handler = None

    async def _loop(self) -> None:
        # 기본 작업자는 일감을 하나씩 처리한다. Full-Mesh에서는 두 Agent가 서로에게 동시에 물을 수 있어
        # 순서대로 처리하면 서로를 기다리며 멈추므로, 일감마다 따로 실행한다.
        async with anyio.create_task_group() as tg:
            async for op in self.broker.receive_task_operations():
                tg.start_soon(self._handle_task_operation, op)

    async def run_task(self, params):
        task_id, ctx_id = params["id"], params["context_id"]
        meta = params.get("metadata") or {}
        # 요청한 쪽의 실행 정보(화면 버스, API 키)를 이어받는다
        bus = RUNS.get(meta.get("run_id", ""))
        current_bus.set(bus)
        current_key.set(meta.get("api_key", ""))
        kv.current_visitor.set(meta.get("visitor", ""))  # 요청한 방문자의 데이터(전문가 목록 등)를 읽기 위해
        await self.storage.update_task(task_id, state="working")
        text = "".join(p.get("text", "") for p in params["message"]["parts"])
        history = await self.storage.load_context(ctx_id) or []
        try:
            reply = await self.handler(text, meta, history)
        except Exception as e:  # noqa: BLE001 - 실패 이유를 Task 기록에 남겨 요청한 쪽에 알린다
            from agents.common import friendly_error
            msg, det = friendly_error(e)
            err = {"role": "agent", "parts": [{"text": f"{msg} ({det})"}], "message_id": uuid.uuid4().hex}
            await self.storage.update_task(task_id, state="failed", new_messages=[err])
            return
        await self.storage.update_context(ctx_id, history + [{"asked": text, "answered": reply}])
        artifact = {"artifact_id": uuid.uuid4().hex, "name": "answer", "parts": [{"text": reply}]}
        message = {"role": "agent", "parts": [{"text": reply}], "message_id": uuid.uuid4().hex}
        await self.storage.update_task(task_id, state="completed", new_artifacts=[artifact], new_messages=[message])

    async def cancel_task(self, params):
        await self.storage.update_task(params["id"], state="canceled")

    def build_message_history(self, history):
        return history

    def build_artifacts(self, result):
        return []


_STOPS: dict[str, asyncio.Event] = {}
_RUNNERS: dict[str, asyncio.Task] = {}
_started = False


def register_agent(name: str, description: str, handler: Handler) -> FastA2A:
    """Agent를 A2A 서버로 등록한다. 서버가 이미 돌고 있으면 바로 작업자를 켠다 (실행 중 추가 가능)."""
    storage, broker = InMemoryStorage(), InMemoryBroker()
    app = FastA2A(storage=storage, broker=broker, name=name, description=description,
                  url=f"http://localhost:8000/agents/{name}", docs_url=None)
    APPS[name] = app
    WORKERS[name] = AgentWorker(broker=broker, storage=storage, handler=handler)
    if _started:
        _start(name)
    return app


async def unregister_agent(name: str):
    """Agent의 A2A 서버를 내린다 (Agent 삭제)."""
    if name in _STOPS:
        _STOPS[name].set()
        await asyncio.gather(_RUNNERS.pop(name), return_exceptions=True)
    _STOPS.pop(name, None)
    APPS.pop(name, None)
    WORKERS.pop(name, None)


def _start(name: str):
    # 작업 관리자와 작업자는 같은 작업(task) 안에서 켜고 꺼야 하므로 Agent마다 전용 작업을 둔다
    stop = _STOPS[name] = asyncio.Event()

    async def runner():
        async with APPS[name].task_manager, WORKERS[name].run():
            await stop.wait()

    _RUNNERS[name] = asyncio.create_task(runner())


async def start_all():
    global _started
    _started = True
    for name in list(APPS):
        _start(name)
    await asyncio.sleep(0)


async def stop_all():
    for name in list(_STOPS):
        await unregister_agent(name)


class AgentRouter:
    """/agents/{이름}/... 요청을 그 이름의 FastA2A 앱으로 넘긴다 (실행 중 추가·삭제된 Agent도 바로 반영)."""

    async def __call__(self, scope, receive, send):
        from starlette.responses import JSONResponse
        root = scope.get("root_path", "")
        rest = scope["path"][len(root):] if scope["path"].startswith(root) else scope["path"]
        name, _, _ = rest.lstrip("/").partition("/")
        if scope["type"] != "http" or name not in APPS:
            return await JSONResponse({"error": f"'{name}' Agent가 없습니다."}, status_code=404)(scope, receive, send)
        sub = dict(scope, root_path=f"{root}/{name}")
        await APPS[name](sub, receive, send)


# ── 클라이언트 쪽: 표준 4단계
def _http() -> httpx.AsyncClient:
    # 같은 프로세스 안의 FastAPI 앱으로 HTTP 요청을 보낸다 (별도 서버/포트 없음)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=HOST_APP), timeout=600)


def _client(name: str) -> A2AClient:
    return A2AClient(f"http://agents.local/agents/{name}", http_client=_http())


async def get_agent_card(name: str, sender: str) -> dict:
    """① 명함 확인: 상대 Agent가 누구이고 무엇을 할 수 있는지 확인한다."""
    async with _http() as c:
        r = await c.get(f"http://agents.local/agents/{name}/.well-known/agent-card.json")
        r.raise_for_status()
        card = r.json()
    emit("a2a_stage", **{"from": sender, "to": name, "stage": 1, "label": "명함 확인 (Agent Card)", "text": card.get("description", "")})
    return card


async def send_message(name: str, sender: str, text: str, context_id: str, metadata: dict) -> str:
    """② 부탁 쪽지 보내기: 메시지를 보내면 일감(Task) 번호를 받는다."""
    client = _client(name)
    msg = {"role": "user", "parts": [{"text": text}], "message_id": uuid.uuid4().hex, "context_id": context_id}
    res = await client.send_message(msg, metadata=metadata)
    if "error" in res:
        raise RuntimeError(f"A2A 오류: {res['error'].get('message')}")
    result = res["result"]
    task = result.get("task", result)
    emit("a2a_stage", **{"from": sender, "to": name, "stage": 2, "label": "부탁 쪽지 (Message)", "text": short(text)})
    return task["id"]


async def wait_for_task(name: str, sender: str, task_id: str, timeout: float = 600) -> dict:
    """③ 진행 상황 확인하기: 완료 또는 실패가 될 때까지 Task 상태를 주기적으로 확인한다."""
    client, last, waited = _client(name), None, 0.0
    while True:
        res = await client.get_task(task_id)
        task = res["result"]
        state = task["status"]["state"]
        if state != last:
            emit("a2a_stage", **{"from": name, "to": sender, "stage": 3, "label": "진행 상황 (Task 상태)", "text": STATE_KO.get(state, state)})
            last = state
        if state in ("completed", "failed", "canceled", "rejected"):
            return task
        await asyncio.sleep(0.4)
        waited += 0.4
        if waited > timeout:
            raise TimeoutError(f"{name} Agent가 응답하지 않습니다.")


def get_artifact(name: str, sender: str, task: dict) -> str:
    """④ 결과 받기: 완료된 Task의 Artifact에서 답을 꺼낸다."""
    if task["status"]["state"] != "completed":
        why = next((p.get("text", "") for m in reversed(task.get("history", [])) if m.get("role") == "agent" for p in m["parts"]), "")
        raise RuntimeError(f"{name} Agent의 작업이 실패했습니다. {why}".strip())
    text = "".join(p.get("text", "") for a in task.get("artifacts", []) for p in a["parts"])
    emit("a2a_stage", **{"from": name, "to": sender, "stage": 4, "label": "결과 받기 (Artifact)", "text": short(text)})
    return text


_cards: dict[tuple, dict] = {}


async def ask(name: str, sender: str, text: str, context_id: str, **meta) -> str:
    """4단계를 위에서 아래로 순서대로 부른다. 명함은 (실행, 상대)마다 최초 1회만 확인한다."""
    bus = current_bus.get()
    run_id = bus.id if bus else ""
    if (run_id, sender, name) not in _cards:
        _cards[(run_id, sender, name)] = await get_agent_card(name, sender)   # ①
    metadata = {"run_id": run_id, "api_key": current_key.get(), "visitor": kv.current_visitor.get(), "from": sender, **meta}
    task_id = await send_message(name, sender, text, context_id, metadata)   # ②
    task = await wait_for_task(name, sender, task_id)                        # ③
    return get_artifact(name, sender, task)                                  # ④
