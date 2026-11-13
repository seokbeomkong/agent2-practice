"""보험심사팀 데이터 저장 (DB 없이 파일로).

data/audit/
  agents.json            전문가 Agent 목록 (이름, 역할, 성격 프롬프트, 색)
  settings.json          {"mesh": true}  Full-Mesh 켜기/끄기
  cases/{id}.json        사건(대화): 제목, 상태(진행 중/완료/보류), 차례별 질문·결론·기록, Agent별 사건 기억
  docs/{agent}/orig/     Agent별 참조 문서 원본
  docs/{agent}/text/     Agent가 읽는 텍스트 (PDF는 글자만 뽑아 둔다)
"""
import io
import json
import re
import shutil
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "audit"
CASES = ROOT / "cases"
DOCS = ROOT / "docs"
for d in (CASES, DOCS):
    d.mkdir(parents=True, exist_ok=True)

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
COLORS = ["#2B9BFF", "#E0218A", "#00A86B", "#FF5A2E", "#7A6FA8", "#00B5C8", "#C98A00"]
STATUSES = ["진행 중", "완료", "보류"]


def _read(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _write(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_id(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", s or ""):
        raise KeyError("잘못된 이름입니다.")
    return s


# ── 전문가 Agent
def load_agents() -> list[dict]:
    p = ROOT / "agents.json"
    if not p.exists():
        _write(p, DEFAULT_AGENTS)
    return _read(p, [])


def save_agents(items: list[dict]):
    _write(ROOT / "agents.json", items)


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
        a = {"id": "a" + uuid.uuid4().hex[:8], "name": name, "role": role, "prompt": prompt,
             "color": COLORS[len(items) % len(COLORS)]}
        items.append(a)
    save_agents(items)
    return a


def delete_agent(aid: str):
    save_agents([a for a in load_agents() if a["id"] != aid])
    shutil.rmtree(DOCS / _safe_id(aid), ignore_errors=True)


# ── 설정
def load_settings() -> dict:
    return {"mesh": True, **_read(ROOT / "settings.json", {})}


def save_settings(**kw) -> dict:
    s = {**load_settings(), **kw}
    _write(ROOT / "settings.json", s)
    return s


# ── 참조 문서
MAX_DOC = 15 * 1024 * 1024
ALLOWED = {".pdf", ".txt", ".md"}


def _doc_dirs(aid: str) -> tuple[Path, Path]:
    base = DOCS / _safe_id(aid)
    return base / "orig", base / "text"


def doc_root(aid: str) -> Path:
    t = _doc_dirs(aid)[1]
    t.mkdir(parents=True, exist_ok=True)
    return t


def list_docs(aid: str) -> list[dict]:
    orig, text = _doc_dirs(aid)
    out = []
    for f in sorted(orig.glob("*")) if orig.exists() else []:
        t = text / (f.name + ".txt")
        out.append({"name": f.name, "size": f.stat().st_size, "chars": len(t.read_text(encoding="utf-8")) if t.exists() else 0})
    return out


def safe_filename(name: str) -> str:
    name = Path(name or "문서").name
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .")[:80]
    return name or "문서"


def add_doc(aid: str, filename: str, data: bytes) -> dict:
    name = safe_filename(filename)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise ValueError("PDF, txt, md 파일만 올릴 수 있어요.")
    if len(data) > MAX_DOC:
        raise ValueError("파일이 너무 커요. 15MB 이하로 올려 주세요.")
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
    orig, tdir = _doc_dirs(aid)
    orig.mkdir(parents=True, exist_ok=True)
    tdir.mkdir(parents=True, exist_ok=True)
    (orig / name).write_bytes(data)
    (tdir / (name + ".txt")).write_text(text, encoding="utf-8")
    return {"name": name, "size": len(data), "chars": len(text)}


def delete_doc(aid: str, name: str):
    orig, text = _doc_dirs(aid)
    name = safe_filename(name)
    (orig / name).unlink(missing_ok=True)
    (text / (name + ".txt")).unlink(missing_ok=True)


def doc_path(aid: str, name: str) -> Path:
    p = _doc_dirs(aid)[0] / safe_filename(name)
    if not p.exists():
        raise KeyError("문서를 찾을 수 없습니다.")
    return p


# ── 사건(대화)
def list_cases() -> list[dict]:
    out = []
    for f in CASES.glob("*.json"):
        c = _read(f, {})
        out.append({k: c.get(k) for k in ("id", "title", "status", "created", "updated")} | {"turns": len(c.get("turns", []))})
    return sorted(out, key=lambda c: c["updated"] or 0, reverse=True)


def new_case() -> dict:
    now = time.time()
    c = {"id": uuid.uuid4().hex[:12], "title": "새 사건", "status": "진행 중", "created": now, "updated": now,
         "turns": [], "memory": {}, "orch_history": []}
    _write(CASES / f"{c['id']}.json", c)
    return c


def load_case(cid: str) -> dict:
    p = CASES / f"{_safe_id(cid)}.json"
    if not p.exists():
        raise KeyError("사건을 찾을 수 없습니다.")
    return _read(p, {})


def save_case(c: dict):
    c["updated"] = time.time()
    _write(CASES / f"{_safe_id(c['id'])}.json", c)


def update_case(cid: str, **kw) -> dict:
    c = load_case(cid)
    if "status" in kw and kw["status"] not in STATUSES:
        raise ValueError("상태는 진행 중, 완료, 보류 중 하나예요.")
    c.update({k: v for k, v in kw.items() if k in ("title", "status")})
    save_case(c)
    return c


def delete_case(cid: str):
    (CASES / f"{_safe_id(cid)}.json").unlink(missing_ok=True)
