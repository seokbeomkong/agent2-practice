"""CH4 페르소나 챗봇 (Deep Agents).

- 캐릭터(페르소나)마다 시스템 프롬프트가 다르다. 추가/편집/삭제 가능.
- 채팅 기록은 txt 파일로 저장한다 (DB 사용 안 함): data/persona/chats/{캐릭터}/{대화}.txt
- Tool: 현재 시각, HTML 문서 만들기, GitHub에서 Skill 설치, Skill 켜기/끄기
- Skill: data/persona/ws/skills/ 의 Skill을 Deep Agents skills로 불러온다 (꺼 둔 Skill은 skills_off/)
- Memory: 캐릭터마다 data/persona/ws/memory/{캐릭터}/AGENTS.md (Deep Agents memory)
  새 대화를 해도, 서버를 다시 켜도 같은 캐릭터는 기억을 이어 간다.
"""
import json
import re
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.tools import tool

from agents.common import current_key, make_model, short, text_of

ROOT = Path(__file__).resolve().parent.parent / "data" / "persona"
WS = ROOT / "ws"                 # Deep Agents 파일 공간 (memory, skills)
CHATS = ROOT / "chats"
HTML = ROOT / "html"
PERSONAS = ROOT / "personas.json"
for d in (WS / "skills", WS / "skills_off", WS / "memory", CHATS, HTML):
    d.mkdir(parents=True, exist_ok=True)

DEFAULTS = [
    {"id": "gyaru", "name": "갸루상", "color": "#FFD400",
     "prompt": "너는 밝고 텐션 높은 갸루 캐릭터야. 반말로 친근하게 말하고, 이모지를 최대한 많이 써. 모든 문장을 신나게 끝내."},
    {"id": "pirate", "name": "해적", "color": "#FF5A2E",
     "prompt": "너는 성격이 포악한 해적 선장이다. 거칠고 호통치듯 말하지만 질문에는 끝까지 제대로 답한다. '이 풋내기야!' 같은 표현을 즐겨 쓴다."},
]
COLORS = ["#FFD400", "#FF5A2E", "#00A86B", "#2B9BFF", "#E0218A", "#7A6FA8"]


# ── 캐릭터 관리
def load_personas() -> list[dict]:
    if not PERSONAS.exists():
        save_personas(DEFAULTS)
    return json.loads(PERSONAS.read_text(encoding="utf-8"))


def save_personas(items: list[dict]):
    PERSONAS.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


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
        p = {"id": "p" + uuid.uuid4().hex[:8], "name": name, "prompt": prompt, "color": COLORS[len(items) % len(COLORS)]}
        items.append(p)
    save_personas(items)
    return p


def delete_persona(pid: str):
    save_personas([p for p in load_personas() if p["id"] != pid])
    shutil.rmtree(CHATS / pid, ignore_errors=True)
    shutil.rmtree(WS / "memory" / pid, ignore_errors=True)


# ── 채팅 기록 (txt, 한 줄에 메시지 하나를 JSON으로)
def _safe(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", s or ""):
        raise KeyError("잘못된 이름입니다.")
    return s


def chat_file(pid: str, cid: str) -> Path:
    return CHATS / _safe(pid) / f"{_safe(cid)}.txt"


def read_chat(pid: str, cid: str) -> list[dict]:
    f = chat_file(pid, cid)
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []


def append_chat(pid: str, cid: str, role: str, content: str, steps: list | None = None):
    f = chat_file(pid, cid)
    f.parent.mkdir(parents=True, exist_ok=True)
    row = {"role": role, "content": content, "ts": time.time()}
    if steps:
        row["steps"] = steps
    with f.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def list_chats(pid: str) -> list[dict]:
    d = CHATS / _safe(pid)
    out = []
    for f in sorted(d.glob("*.txt"), key=lambda x: x.stat().st_mtime, reverse=True) if d.exists() else []:
        first = next((json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()), {})
        out.append({"id": f.stem, "title": short(first.get("content", "새 대화"), 24), "updated": f.stat().st_mtime})
    return out


def memory_path(pid: str) -> Path:
    p = WS / "memory" / _safe(pid) / "AGENTS.md"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {get_persona(pid)['name']}의 기억\n\n사용자에 대해 알게 된 사실을 여기에 적는다.\n", encoding="utf-8")
    return p


def list_skills() -> list[dict]:
    out = []
    for folder, on in ((WS / "skills", True), (WS / "skills_off", False)):
        for d in sorted(folder.iterdir()):
            md = d / "SKILL.md"
            if md.exists():
                m = re.search(r"^description:\s*(.+)$", md.read_text(encoding="utf-8", errors="replace"), re.M)
                out.append({"name": d.name, "enabled": on, "description": (m.group(1).strip() if m else "")[:200]})
    return out


# ── Tool: Agent가 필요하다고 판단할 때 스스로 쓴다
@tool
def get_current_time() -> str:
    """현재 날짜와 시각(한국 시간)을 정확히 확인한다."""
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y년 %m월 %d일 %H시 %M분 %S초 (KST)")


@tool
def create_html(title: str, html: str) -> str:
    """HTML 문서를 만들어 서버에 저장하고, 열어 볼 수 있는 링크를 돌려준다.
    html에는 <!doctype html>부터 시작하는 완성된 문서 전체를 넣는다. 답할 때 반환된 링크를 꼭 함께 알려 준다."""
    name = f"{uuid.uuid4().hex[:12]}.html"
    (HTML / name).write_text(html, encoding="utf-8")
    return f"저장 완료: '{title}' 문서 링크는 /api/persona/html/{name} 입니다."


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
                elif item["type"] == "file" and item["size"] <= 512_000:
                    files[rel + item["name"]] = (await c.get(item["download_url"])).content
        try:
            await walk(path, "")
        except httpx.HTTPError as e:
            return f"Skill을 내려받지 못했습니다: {e}"
    if "SKILL.md" not in files:
        return "그 폴더에 SKILL.md가 없어 Skill로 설치할 수 없습니다."
    target = WS / "skills" / name
    shutil.rmtree(target, ignore_errors=True)
    shutil.rmtree(WS / "skills_off" / name, ignore_errors=True)
    for rel, data in files.items():
        f = (target / rel).resolve()
        if target.resolve() in f.parents:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
    return f"'{name}' Skill을 설치하고 켰습니다 (파일 {len(files)}개). 다음 메시지부터 사용할 수 있습니다."


@tool
def manage_skills(action: str, name: str = "") -> str:
    """설치된 Skill을 관리한다. action은 list(목록), on(켜기), off(끄기) 중 하나다."""
    if action == "list":
        items = list_skills()
        return "\n".join(f"- {s['name']} ({'켜짐' if s['enabled'] else '꺼짐'}): {s['description']}" for s in items) or "설치된 Skill이 없습니다."
    src, dst = (WS / "skills_off", WS / "skills") if action == "on" else (WS / "skills", WS / "skills_off")
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


async def chat_stream(pid: str, cid: str | None, message: str):
    """대화 한 번을 실행하며 Agent의 사고 과정(생각, 도구 호출, 결과)과 답변을 이벤트로 흘려보낸다."""
    persona = get_persona(pid)
    cid = cid or uuid.uuid4().hex[:12]
    history = [{"role": m["role"], "content": m["content"]} for m in read_chat(pid, cid)]
    memory_path(pid)
    mem_virtual = f"/memory/{pid}/AGENTS.md"
    agent = create_deep_agent(
        model=make_model(current_key.get(), max_tokens=8192, thinking_display="summarized"),
        tools=TOOLS,
        system_prompt=SYSTEM.format(prompt=persona["prompt"], name=persona["name"], memory=mem_virtual),
        backend=FilesystemBackend(root_dir=WS, virtual_mode=True),
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
                        if m.name == "edit_file" or m.name == "write_file":
                            yield {"type": "memory", "text": memory_path(pid).read_text(encoding="utf-8")}
    final = final or buf.strip()
    append_chat(pid, cid, "assistant", final, steps)
    yield {"type": "final", "text": final}
