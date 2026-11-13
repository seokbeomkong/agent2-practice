"""보험심사팀 데이터 저장 (방문자별 저장소 kv.py).

audit:agents          전문가 Agent 목록 (이름, 역할, 성격 프롬프트, 색)
audit:settings        {"mesh": true}  Full-Mesh 켜기/끄기
audit:case:{id}       사건(대화): 제목, 상태(진행 중/완료/보류), 차례별 질문·결론·기록, Agent별 사건 기억
audit:caseidx         사건 목록용 요약 (해시: 사건 id → 제목, 상태, 시간)
audit:docmeta:{agent} Agent별 참조 문서 목록 (해시: 문서 이름 → 크기, 글자 수)
audit:doctext:{agent} Agent별 참조 문서 본문 (해시: 문서 이름 → 글자만 뽑은 텍스트)

참조 문서는 원본 파일이 아니라 읽을 수 있는 글자만 저장한다 (PDF는 글자를 뽑아 둔다).
"""
import copy
import io
import json
import re
import time
import uuid
from pathlib import Path

import kv
from kv import LimitError

DEFAULT_AGENTS = [
    {"id": "legal", "name": "법률", "role": "약관·법적 근거 검토", "color": "#2B9BFF",
     "prompt": "당신은 보험사 보험심사팀의 LegalReview(법률) 전문가입니다.\n"
               "- 약관 조항, 관련 법령과 판례의 일반 원칙, 면책 사유를 근거로 보험금 지급 여부를 검토합니다.\n"
               "- 결론은 '지급 / 조건부 지급 / 부지급' 중 하나로 분명히 하고 근거를 적습니다."},
    {"id": "customer", "name": "고객", "role": "가입자 입장 대변", "color": "#E0218A",
     "prompt": "당신은 보험사 보험심사팀의 CustomerReview 전문가입니다. 보험 가입자(고객)의 입장을 대변합니다.\n"
               "- 고객이 약관과 안내를 통해 기대할 수 있었던 보장, 공정한 처리, 신뢰와 평판을 중요하게 봅니다.\n"
               "- 고객에게 어떻게 설명하고 안내하면 좋을지도 함께 제안합니다."},
    {"id": "ceo", "name": "경영", "role": "손익·회사 리스크", "color": "#00A86B",
     "prompt": "당신은 보험사 보험심사팀의 CEO(경영 전문가)입니다. 보험회사 경영자의 입장을 대변합니다.\n"
               "- 손해율, 비용, 유사 사례로 번질 위험, 회사의 지속 가능성과 평판을 중요하게 봅니다.\n"
               "- 회사가 감당할 수 있는 현실적인 대안(한도, 자기부담금, 상품 설계 등)을 제안합니다."},
]
DEFAULT_IDS = frozenset(a["id"] for a in DEFAULT_AGENTS)
COLORS = ["#2B9BFF", "#E0218A", "#00A86B", "#FF5A2E", "#7A6FA8", "#00B5C8", "#C98A00"]
STATUSES = ["진행 중", "완료", "보류"]

# 사용 한도 (공개 서버에서 저장소가 가득 차지 않게)
MAX_AGENTS = 8
MAX_DOCS_PER_AGENT = 5
MAX_CASES = 30
MAX_UPLOAD = 4 * 1024 * 1024        # Vercel 요청 본문 한도(4.5MB) 아래
MAX_DOC_TEXT = 600_000              # 문서 하나에서 읽을 최대 글자 수


def _safe_id(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", s or ""):
        raise KeyError("잘못된 이름입니다.")
    return s


# ── 전문가 Agent
def load_agents() -> list[dict]:
    items = kv.get_json(kv.vk("audit:agents"))
    if items is None:
        items = copy.deepcopy(DEFAULT_AGENTS)  # 복사해서 쓴다 (원본을 고치면 다른 방문자에게도 보인다)
        save_agents(items)
    return items


def save_agents(items: list[dict]):
    kv.set_json(kv.vk("audit:agents"), items)


def get_agent(aid: str) -> dict:
    a = next((a for a in load_agents() if a["id"] == aid), None)
    if not a:
        raise KeyError("Agent를 찾을 수 없습니다.")
    return a


def upsert_agent(aid: str | None, name: str, role: str, prompt: str) -> dict:
    items = load_agents()
    if aid:
        a = next(a for a in items if a["id"] == aid)
        a.update(name=name, role=role, prompt=prompt)
    else:
        if len(items) >= MAX_AGENTS:
            raise LimitError(f"전문가는 {MAX_AGENTS}명까지 둘 수 있어요. 안 쓰는 전문가를 삭제해 주세요.")
        a = {"id": "a" + uuid.uuid4().hex[:8], "name": name, "role": role, "prompt": prompt,
             "color": COLORS[len(items) % len(COLORS)]}
        items.append(a)
    save_agents(items)
    return a


def delete_agent(aid: str):
    save_agents([a for a in load_agents() if a["id"] != aid])
    kv.delete(kv.vk(f"audit:docmeta:{_safe_id(aid)}"), kv.vk(f"audit:doctext:{aid}"))


# ── 설정
def load_settings() -> dict:
    return {"mesh": True, **(kv.get_json(kv.vk("audit:settings")) or {})}


def save_settings(**kw) -> dict:
    s = {**load_settings(), **kw}
    kv.set_json(kv.vk("audit:settings"), s)
    return s


# ── 참조 문서
def safe_filename(name: str) -> str:
    name = Path(name or "문서").name
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .")[:80]
    return name or "문서"


def list_docs(aid: str) -> list[dict]:
    meta = kv.hgetall(kv.vk(f"audit:docmeta:{_safe_id(aid)}"))
    return [{"name": n, **json.loads(m)} for n, m in sorted(meta.items())]


def docs_text(aid: str) -> dict[str, str]:
    """문서 이름 → 본문 (Agent가 read_file로 읽을 내용)"""
    return kv.hgetall(kv.vk(f"audit:doctext:{_safe_id(aid)}"))


def add_doc(aid: str, filename: str, data: bytes) -> dict:
    name = safe_filename(filename)
    ext = Path(name).suffix.lower()
    if ext not in {".pdf", ".txt", ".md"}:
        raise ValueError("PDF, txt, md 파일만 올릴 수 있어요.")
    if len(data) > MAX_UPLOAD:
        raise ValueError("파일이 너무 커요. 4MB 이하로 올려 주세요.")
    existing = {d["name"] for d in list_docs(aid)}
    if name not in existing and len(existing) >= MAX_DOCS_PER_AGENT:
        raise LimitError(f"전문가 한 명에게 문서는 {MAX_DOCS_PER_AGENT}개까지 올릴 수 있어요. 안 쓰는 문서를 삭제해 주세요.")
    if ext == ".pdf":
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join(f"[{i} 페이지]\n{(p.extract_text() or '').strip()}" for i, p in enumerate(reader.pages, 1))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"PDF를 읽지 못했어요: {e}")
    else:
        text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise ValueError("문서에서 글자를 찾지 못했어요. 스캔한 이미지 PDF는 읽을 수 없어요.")
    cut = len(text) > MAX_DOC_TEXT
    text = text[:MAX_DOC_TEXT]
    kv.hset(kv.vk(f"audit:doctext:{aid}"), {name: text})
    meta = {"size": len(data), "chars": len(text), "truncated": cut}
    kv.hset(kv.vk(f"audit:docmeta:{aid}"), {name: json.dumps(meta)})
    return {"name": name, **meta}


def delete_doc(aid: str, name: str):
    name = safe_filename(name)
    kv.hdel(kv.vk(f"audit:docmeta:{_safe_id(aid)}"), name)
    kv.hdel(kv.vk(f"audit:doctext:{aid}"), name)


def doc_text(aid: str, name: str) -> str:
    t = kv.hget(kv.vk(f"audit:doctext:{_safe_id(aid)}"), safe_filename(name))
    if t is None:
        raise KeyError("문서를 찾을 수 없습니다.")
    return t


# ── 사건(대화)
def _meta(c: dict) -> dict:
    return {"title": c["title"], "status": c["status"], "created": c["created"], "updated": c["updated"], "turns": len(c.get("turns", []))}


def list_cases() -> list[dict]:
    rows = [{"id": cid, **json.loads(m)} for cid, m in kv.hgetall(kv.vk("audit:caseidx")).items()]
    return sorted(rows, key=lambda c: c["updated"] or 0, reverse=True)


def new_case() -> dict:
    if len(kv.hgetall(kv.vk("audit:caseidx"))) >= MAX_CASES:
        raise LimitError(f"사건은 {MAX_CASES}개까지 둘 수 있어요. 끝난 사건을 삭제해 주세요.")
    now = time.time()
    c = {"id": uuid.uuid4().hex[:12], "title": "새 사건", "status": "진행 중", "created": now, "updated": now,
         "turns": [], "memory": {}, "orch_history": []}
    save_case(c)
    return c


def load_case(cid: str) -> dict:
    c = kv.get_json(kv.vk(f"audit:case:{_safe_id(cid)}"))
    if c is None:
        raise KeyError("사건을 찾을 수 없습니다.")
    return c


def save_case(c: dict):
    c["updated"] = time.time()
    kv.set_json(kv.vk(f"audit:case:{_safe_id(c['id'])}"), c)
    kv.hset(kv.vk("audit:caseidx"), {c["id"]: json.dumps(_meta(c), ensure_ascii=False)})


def update_case(cid: str, **kw) -> dict:
    c = load_case(cid)
    if "status" in kw and kw["status"] not in STATUSES:
        raise ValueError("상태는 진행 중, 완료, 보류 중 하나예요.")
    c.update({k: v for k, v in kw.items() if k in ("title", "status")})
    save_case(c)
    return c


def delete_case(cid: str):
    kv.delete(kv.vk(f"audit:case:{_safe_id(cid)}"))
    kv.hdel(kv.vk("audit:caseidx"), cid)
