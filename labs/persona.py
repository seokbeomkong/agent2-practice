"""CH4 페르소나 챗봇 (Deep Agents).

- 캐릭터(페르소나)마다 시스템 프롬프트가 다르다. 추가/편집/삭제 가능.
- 데이터는 모두 방문자별 저장소(kv.py)에 둔다: 캐릭터, 채팅 기록, 캐릭터별 기억(AGENTS.md), 설치한 Skill, 만든 HTML
- Tool: 현재 시각, HTML 문서 만들기, GitHub에서 Skill 설치, Skill 켜기/끄기
- Skill: Deep Agents skills로 불러온다 (꺼 둔 Skill은 skills_off/)
- Memory: 캐릭터마다 /memory/{캐릭터}/AGENTS.md (Deep Agents memory). 새 대화를 해도 같은 캐릭터는 기억을 이어 간다.

Deep Agents는 파일 공간이 필요하므로, 대화 한 번을 실행하는 동안만 임시 폴더에 저장소 내용을 펼쳐 두고
끝나면 바뀐 내용(기억, Skill)을 저장소로 되돌린 뒤 임시 폴더를 지운다. (서버리스에서도 같은 방식으로 동작)
"""
import base64
import contextvars
import copy
import json
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.tools import tool

import kv
from kv import LimitError
from agents.common import current_key, make_model, short, text_of

DEFAULTS = [
    {"id": "gyaru", "name": "갸루상", "color": "#FFD400",
     "prompt": "너는 밝고 텐션 높은 갸루 캐릭터야. 반말로 친근하게 말하고, 이모지를 최대한 많이 써. 모든 문장을 신나게 끝내."},
    {"id": "pirate", "name": "해적", "color": "#FF5A2E",
     "prompt": "너는 성격이 포악한 해적 선장이다. 거칠고 호통치듯 말하지만 질문에는 끝까지 제대로 답한다. '이 풋내기야!' 같은 표현을 즐겨 쓴다."},
]
COLORS = ["#FFD400", "#FF5A2E", "#00A86B", "#2B9BFF", "#E0218A", "#7A6FA8"]
MAX_PERSONAS = 12
MAX_SKILL_BYTES = 1_500_000   # 설치한 Skill 전체 크기 한도 (저장소 용량 보호)
MAX_HTML = 300_000


# ── 저장소 키 (방문자별로 자동 분리된다)
K_LIST = "persona:list"
K_SKILLS = "persona:skills"      # 해시: "skills/이름/SKILL.md" → base64 내용
K_HTML = "persona:html"          # 해시: 파일 이름 → HTML


def k_chat(pid, cid): return kv.vk(f"persona:chat:{pid}:{cid}")
def k_chats(pid): return kv.vk(f"persona:chats:{pid}")   # 해시: 대화 id → {"title","updated"}
def k_mem(pid): return kv.vk(f"persona:mem:{pid}")


# ── 캐릭터 관리
def load_personas() -> list[dict]:
    items = kv.get_json(kv.vk(K_LIST))
    if items is None:
        items = copy.deepcopy(DEFAULTS)  # 복사해서 쓴다 (원본을 고치면 다른 방문자에게도 보인다)
        save_personas(items)
    return items


def save_personas(items: list[dict]):
    kv.set_json(kv.vk(K_LIST), items)


def get_persona(pid: str) -> dict:
    p = next((p for p in load_personas() if p["id"] == pid), None)
    if not p:
        raise KeyError("캐릭터를 찾을 수 없습니다.")
    return p


def upsert_persona(pid: str | None, name: str, prompt: str) -> dict:
    items = load_personas()
    if pid:
        p = next(p for p in items if p["id"] == pid)
        p.update(name=name, prompt=prompt)
    else:
        if len(items) >= MAX_PERSONAS:
            raise LimitError(f"캐릭터는 {MAX_PERSONAS}명까지 만들 수 있어요. 안 쓰는 캐릭터를 삭제해 주세요.")
        p = {"id": "p" + uuid.uuid4().hex[:8], "name": name, "prompt": prompt, "color": COLORS[len(items) % len(COLORS)]}
        items.append(p)
    save_personas(items)
    return p


def delete_persona(pid: str):
    save_personas([p for p in load_personas() if p["id"] != pid])
    chats = kv.hgetall(k_chats(pid))
    kv.delete(*[k_chat(pid, c) for c in chats], k_chats(pid), k_mem(pid))


# ── 채팅 기록 (대화마다 메시지를 한 줄씩 쌓는다)
def _safe(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", s or ""):
        raise KeyError("잘못된 이름입니다.")
    return s


def read_chat(pid: str, cid: str) -> list[dict]:
    return [json.loads(x) for x in kv.lrange(k_chat(_safe(pid), _safe(cid)))]


def append_chat(pid: str, cid: str, role: str, content: str, steps: list | None = None):
    row = {"role": role, "content": content, "ts": time.time()}
    if steps:
        row["steps"] = steps
    kv.rpush(k_chat(pid, cid), json.dumps(row, ensure_ascii=False))
    old = kv.hget(k_chats(pid), cid)
    title = json.loads(old)["title"] if old else short(content, 24)
    kv.hset(k_chats(pid), {cid: json.dumps({"title": title, "updated": time.time()}, ensure_ascii=False)})


def list_chats(pid: str) -> list[dict]:
    rows = [{"id": c, **json.loads(v)} for c, v in kv.hgetall(k_chats(_safe(pid))).items()]
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


# ── 기억 (AGENTS.md)
def read_memory(pid: str) -> str:
    return kv.get(k_mem(_safe(pid))) or f"# {get_persona(pid)['name']}의 기억\n\n사용자에 대해 알게 된 사실을 여기에 적는다.\n"


# ── Skill: 저장소에는 {상대 경로: base64}로 두고, 실행할 때 임시 폴더에 펼친다
def _skill_files() -> dict[str, bytes]:
    return {p: base64.b64decode(v) for p, v in kv.hgetall(kv.vk(K_SKILLS)).items()}


def _describe(files: dict[str, bytes]) -> list[dict]:
    out = []
    for rel, data in sorted(files.items()):
        parts = rel.split("/")
        if len(parts) == 3 and parts[0] in ("skills", "skills_off") and parts[2] == "SKILL.md":
            m = re.search(r"^description:\s*(.+)$", data.decode("utf-8", "replace"), re.M)
            out.append({"name": parts[1], "enabled": parts[0] == "skills", "description": (m.group(1).strip() if m else "")[:200]})
    return out


def list_skills() -> list[dict]:
    return _describe(_skill_files())


def _read_tree(ws: Path) -> dict[str, bytes]:
    out = {}
    for top in ("skills", "skills_off"):
        for f in (ws / top).rglob("*"):
            if f.is_file():
                out[f.relative_to(ws).as_posix()] = f.read_bytes()
    return out


current_ws: contextvars.ContextVar[Path] = contextvars.ContextVar("persona_ws")


# ── Tool: Agent가 필요하다고 판단할 때 스스로 쓴다
@tool
def get_current_time() -> str:
    """현재 날짜와 시각(한국 시간)을 정확히 확인한다."""
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y년 %m월 %d일 %H시 %M분 %S초 (KST)")


@tool
def create_html(title: str, html: str) -> str:
    """HTML 문서를 만들어 서버에 저장하고, 열어 볼 수 있는 링크를 돌려준다.
    html에는 <!doctype html>부터 시작하는 완성된 문서 전체를 넣는다. 답할 때 반환된 링크를 꼭 함께 알려 준다."""
    if len(html.encode("utf-8")) > MAX_HTML:
        return "문서가 너무 커서 저장하지 못했습니다. 더 짧게 만들어 다시 시도해 주세요."
    name = f"{uuid.uuid4().hex[:12]}.html"
    kv.hset(kv.vk(K_HTML), {name: html})
    return f"저장 완료: '{title}' 문서 링크는 /api/persona/html/{name}?v={kv.current_visitor.get()} 입니다."


@tool
async def install_skill(github_url: str) -> str:
    """GitHub 주소의 Skill 폴더(SKILL.md가 들어 있는 폴더)를 내려받아 설치한다.
    예: https://github.com/anthropics/skills/tree/main/skills/brand-guidelines"""
    m = re.match(r"https://github\.com/([\w.-]+)/([\w.-]+)/(?:tree|blob)/([\w.-]+)/(.+?)/?$", github_url.strip())
    if not m:
        return "GitHub 폴더 주소 형식이 아닙니다. 예: https://github.com/<owner>/<repo>/tree/<branch>/<path>"
    owner, repo, ref, path = m.groups()
    path = path.removesuffix("/SKILL.md")
    name = re.sub(r"[^A-Za-z0-9_-]", "-", path.rsplit("/", 1)[-1])[:40]
    files: dict[str, bytes] = {}
    async with httpx.AsyncClient(timeout=30, headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-lab"}) as c:
        async def walk(p: str, rel: str):
            r = await c.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{p}", params={"ref": ref})
            r.raise_for_status()
            for item in r.json():
                if len(files) >= 40:
                    return
                if item["type"] == "dir":
                    await walk(item["path"], f"{rel}{item['name']}/")
                elif item["type"] == "file" and item["size"] <= 200_000:
                    files[rel + item["name"]] = (await c.get(item["download_url"])).content
        try:
            await walk(path, "")
        except httpx.HTTPError as e:
            return f"Skill을 내려받지 못했습니다: {e}"
    if "SKILL.md" not in files:
        return "그 폴더에 SKILL.md가 없어 Skill로 설치할 수 없습니다."
    ws = current_ws.get()
    used = sum(len(b) for rel, b in _read_tree(ws).items() if rel.split("/")[1] != name)
    if used + sum(len(b) for b in files.values()) > MAX_SKILL_BYTES:
        return "설치한 Skill이 너무 많아 더 설치할 수 없습니다. 안 쓰는 Skill을 정리해 주세요."
    target = ws / "skills" / name
    shutil.rmtree(target, ignore_errors=True)
    shutil.rmtree(ws / "skills_off" / name, ignore_errors=True)
    for rel, data in files.items():
        f = (target / rel).resolve()
        if target.resolve() in f.parents:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
    return f"'{name}' Skill을 설치하고 켰습니다 (파일 {len(files)}개). 다음 메시지부터 사용할 수 있습니다."


@tool
def manage_skills(action: str, name: str = "") -> str:
    """설치된 Skill을 관리한다. action은 list(목록), on(켜기), off(끄기) 중 하나다."""
    ws = current_ws.get()
    if action == "list":
        items = _describe(_read_tree(ws))
        return "\n".join(f"- {s['name']} ({'켜짐' if s['enabled'] else '꺼짐'}): {s['description']}" for s in items) or "설치된 Skill이 없습니다."
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name or ""):
        return "Skill 이름을 확인해 주세요."
    src, dst = (ws / "skills_off", ws / "skills") if action == "on" else (ws / "skills", ws / "skills_off")
    if action not in ("on", "off") or not (src / name).is_dir():
        return f"'{name}' Skill을 찾을 수 없거나 이미 {'켜져' if action == 'on' else '꺼져'} 있습니다."
    shutil.move(str(src / name), str(dst / name))
    return f"'{name}' Skill을 {'켰습니다' if action == 'on' else '껐습니다'}. 다음 메시지부터 적용됩니다."


TOOLS = [get_current_time, create_html, install_skill, manage_skills]

SYSTEM = """{prompt}

[너는 '{name}' 캐릭터다. 위 성격과 말투를 대화 내내 지킨다.]
- 현재 날짜나 시각이 필요하면 추측하지 말고 get_current_time 도구를 쓴다.
- HTML 문서나 카드를 만들어 달라고 하면 create_html 도구로 만들고, 돌려받은 링크를 답에 그대로 적는다.
  Skill(예: 디자인 가이드라인)이 있으면 먼저 읽고 그 지침대로 만든다.
- 사용자가 Skill의 GitHub 주소를 주면 install_skill로 설치하고, 켜고 끄기나 목록은 manage_skills로 한다.
- 사용자 이름, 취향, 약속처럼 다음 대화에도 기억할 만한 내용은 {memory} 파일에 edit_file로 바로 적는다.
- 답은 짧고 자연스러운 대화체로 쓴다."""


def _open_workspace(pid: str) -> tuple[Path, dict[str, bytes], str]:
    """저장소 내용을 임시 폴더에 펼친다. (폴더, 처음 Skill 상태, 처음 기억)"""
    ws = Path(tempfile.mkdtemp(prefix="persona-"))
    (ws / "skills").mkdir()
    (ws / "skills_off").mkdir()
    skills = _skill_files()
    for rel, data in skills.items():
        f = (ws / rel).resolve()
        if ws.resolve() in f.parents:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
    mem = read_memory(pid)
    mp = ws / "memory" / pid / "AGENTS.md"
    mp.parent.mkdir(parents=True)
    mp.write_text(mem, encoding="utf-8")
    return ws, skills, mem


def _close_workspace(ws: Path, pid: str, skills_before: dict[str, bytes], mem_before: str):
    """바뀐 기억과 Skill을 저장소에 되돌리고 임시 폴더를 지운다."""
    try:
        mem = (ws / "memory" / pid / "AGENTS.md").read_text(encoding="utf-8")
        if mem != mem_before:
            kv.set(k_mem(pid), mem[:20_000])
        after = _read_tree(ws)
        if after != skills_before:
            key = kv.vk(K_SKILLS)
            kv.delete(key)
            kv.hset(key, {rel: base64.b64encode(data).decode() for rel, data in after.items()})
    finally:
        shutil.rmtree(ws, ignore_errors=True)


async def chat_stream(pid: str, cid: str | None, message: str):
    """대화 한 번을 실행하며 Agent의 사고 과정(생각, 도구 호출, 결과)과 답변을 이벤트로 흘려보낸다."""
    persona = get_persona(pid)
    cid = _safe(cid) if cid else uuid.uuid4().hex[:12]
    history = [{"role": m["role"], "content": m["content"]} for m in read_chat(pid, cid)]
    ws, skills_before, mem_before = _open_workspace(pid)
    current_ws.set(ws)
    mem_virtual = f"/memory/{pid}/AGENTS.md"
    try:
        agent = create_deep_agent(
            model=make_model(current_key.get(), max_tokens=8192, thinking_display="summarized"),
            tools=TOOLS,
            system_prompt=SYSTEM.format(prompt=persona["prompt"], name=persona["name"], memory=mem_virtual),
            backend=FilesystemBackend(root_dir=ws, virtual_mode=True),
            skills=["/skills/"],
            memory=[mem_virtual],
        )
        append_chat(pid, cid, "user", message)
        yield {"type": "chat", "chat_id": cid}
        steps, final, buf = [], "", ""
        async for mode, data in agent.astream({"messages": history + [{"role": "user", "content": message}]},
                                              stream_mode=["messages", "updates"]):
            if mode == "messages":
                chunk, meta = data
                if chunk.type != "AIMessageChunk" or meta.get("langgraph_node") != "model":
                    continue
                blocks = chunk.content if isinstance(chunk.content, list) else [{"type": "text", "text": chunk.content}]
                for b in blocks:
                    if b.get("type") == "thinking" and b.get("thinking"):
                        yield {"type": "thinking", "t": b["thinking"]}
                    elif b.get("type") == "text" and b.get("text"):
                        buf += b["text"]
                        yield {"type": "text", "t": b["text"]}
            else:  # updates: 완성된 도구 호출과 결과
                for out in data.values():
                    msgs = out.get("messages", []) if isinstance(out, dict) else []
                    msgs = getattr(msgs, "value", msgs)
                    for m in msgs if isinstance(msgs, list) else []:
                        if m.type == "ai":
                            for call in getattr(m, "tool_calls", None) or []:
                                args = {k: (short(v, 160) if isinstance(v, str) else v) for k, v in call["args"].items()}
                                steps.append({"kind": "tool", "name": call["name"], "args": args})
                                yield {"type": "tool_call", "name": call["name"], "args": args}
                            if not getattr(m, "tool_calls", None):
                                final = text_of(m.content).strip() or final
                        elif m.type == "tool":
                            res = m.content if isinstance(m.content, str) else text_of(m.content)
                            steps.append({"kind": "result", "name": m.name, "text": short(res, 300)})
                            yield {"type": "tool_result", "name": m.name, "text": short(res, 300)}
                            if m.name in ("edit_file", "write_file"):
                                yield {"type": "memory", "text": (ws / "memory" / pid / "AGENTS.md").read_text(encoding="utf-8")}
        final = final or buf.strip()
        append_chat(pid, cid, "assistant", final, steps)
        yield {"type": "final", "text": final}
    finally:
        _close_workspace(ws, pid, skills_before, mem_before)
