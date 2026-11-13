"""사용자 데이터 저장소 (키-값).

- 배포(Vercel): Upstash Redis REST API. 서버리스 함수는 요청마다 다른 인스턴스에서 실행되고 파일이 남지 않으므로
  데이터는 모두 여기에 둔다. 환경변수 UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
  (Vercel 마켓플레이스 연동 시 KV_REST_API_URL / KV_REST_API_TOKEN 이름으로도 들어온다)
- 로컬 개발: data/store.json 파일 (같은 명령을 흉내 낸다. 외부 서비스 없이 바로 실행된다)

데이터는 방문자(브라우저)마다 따로 둔다: 키는 u:{방문자번호}:... 로 시작하고, 마지막으로 쓴 뒤 30일이 지나면 사라진다.
"""
import contextvars
import json
import os
import re
import threading
from pathlib import Path

import httpx

TTL = 30 * 24 * 3600
LOCAL_FILE = Path(__file__).resolve().parent / "data" / "store.json"

current_visitor: contextvars.ContextVar[str] = contextvars.ContextVar("visitor", default="")
VISITOR_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class StoreError(Exception):
    """화면에 그대로 보여 줄 수 있는 저장소 오류."""

    def __init__(self, message: str, detail: str = "", status: int = 500):
        super().__init__(message)
        self.message, self.detail, self.status = message, detail, status


class LimitError(ValueError):
    """사용 한도를 넘었을 때 (화면에 그대로 보여 준다)."""


def valid_visitor(v: str | None) -> str | None:
    return v if v and VISITOR_RE.match(v) else None


def vk(name: str) -> str:
    """현재 방문자 전용 키: u:{방문자번호}:{이름}"""
    v = current_visitor.get()
    if not v:
        raise StoreError("방문자 정보를 확인하지 못했습니다. 페이지를 새로고침해 주세요.", status=400)
    return f"u:{v}:{name}"


# ── 로컬 백엔드: Redis 명령 일부를 파일 하나로 흉내 낸다
class LocalBackend:
    def __init__(self, path: Path):
        self.path, self.lock = path, threading.RLock()
        self.data: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def pipeline(self, cmds: list[list]) -> list:
        with self.lock:
            out, changed = [], False
            for c in cmds:
                r, ch = self._run(c)
                out.append(r)
                changed |= ch
            if changed:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.path)
            return out

    def _run(self, c: list):
        d, op = self.data, str(c[0]).upper()
        if op == "GET":
            return d.get(c[1]), False
        if op == "SET":
            d[c[1]] = str(c[2])
            return "OK", True
        if op == "DEL":
            n = sum(1 for k in c[1:] if d.pop(k, None) is not None)
            return n, n > 0
        if op == "HSET":
            h = d.setdefault(c[1], {})
            pairs = c[2:]
            for i in range(0, len(pairs), 2):
                h[str(pairs[i])] = str(pairs[i + 1])
            return len(pairs) // 2, True
        if op == "HGET":
            return d.get(c[1], {}).get(str(c[2])), False
        if op == "HDEL":
            h = d.get(c[1], {})
            n = sum(1 for f in c[2:] if h.pop(str(f), None) is not None)
            return n, n > 0
        if op == "HGETALL":
            return [x for kv in d.get(c[1], {}).items() for x in kv], False
        if op == "RPUSH":
            lst = d.setdefault(c[1], [])
            lst.extend(str(x) for x in c[2:])
            return len(lst), True
        if op == "LRANGE":
            lst = d.get(c[1], [])
            end = int(c[3])
            return lst[int(c[2]): None if end == -1 else end + 1], False
        if op == "EXPIRE":
            return 1, False
        raise StoreError(f"지원하지 않는 저장소 명령입니다: {op}")


# ── Upstash Redis REST 백엔드
class RedisBackend:
    def __init__(self, url: str, token: str):
        self.http = httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=15)

    def pipeline(self, cmds: list[list]) -> list:
        try:
            r = self.http.post("/pipeline", json=cmds)
        except httpx.HTTPError as e:
            raise StoreError("저장소에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.", type(e).__name__, 503)
        if r.status_code != 200:
            raise StoreError("저장소 요청이 실패했습니다.", f"HTTP {r.status_code}: {r.text[:200]}", 502)
        out = []
        for item in r.json():
            if isinstance(item, dict) and item.get("error"):
                raise StoreError("저장소 요청이 실패했습니다.", str(item["error"])[:200], 502)
            out.append(item.get("result") if isinstance(item, dict) else item)
        return out


def _make_backend():
    url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    if url and token:
        return RedisBackend(url, token)
    if os.environ.get("VERCEL"):  # 배포 환경에서 저장소가 없으면 파일에 몰래 저장하지 않고 분명히 알린다
        raise StoreError("저장소가 연결되지 않았습니다. 관리자에게 Redis(Upstash) 연결을 요청해 주세요.", "UPSTASH_REDIS_REST_URL 없음", 503)
    return LocalBackend(LOCAL_FILE)


_backend = None
_lock = threading.Lock()


def backend():
    global _backend
    with _lock:
        if _backend is None:
            _backend = _make_backend()
        return _backend


def mode() -> str:
    try:
        return "redis" if isinstance(backend(), RedisBackend) else "local"
    except StoreError:
        return "missing"


def run(*cmds: list) -> list:
    return backend().pipeline([list(c) for c in cmds])


def _touch(key: str) -> list:
    return ["EXPIRE", key, TTL]


# ── 편의 함수 (쓸 때마다 30일 만료를 다시 건다)
def get(key: str) -> str | None:
    return run(["GET", key])[0]


def set(key: str, value: str):
    run(["SET", key, value], _touch(key))


def get_json(key: str, default=None):
    v = get(key)
    return json.loads(v) if v else default


def set_json(key: str, obj):
    set(key, json.dumps(obj, ensure_ascii=False))


def delete(*keys: str):
    if keys:
        run(["DEL", *keys])


def hget(key: str, field: str) -> str | None:
    return run(["HGET", key, field])[0]


def hset(key: str, mapping: dict[str, str]):
    if mapping:
        flat = [x for kv in mapping.items() for x in kv]
        run(["HSET", key, *flat], _touch(key))


def hdel(key: str, *fields: str):
    if fields:
        run(["HDEL", key, *fields])


def hgetall(key: str) -> dict[str, str]:
    r = run(["HGETALL", key])[0] or []
    if isinstance(r, dict):
        return r
    return {r[i]: r[i + 1] for i in range(0, len(r), 2)}


def rpush(key: str, value: str):
    run(["RPUSH", key, value], _touch(key))


def lrange(key: str) -> list[str]:
    return run(["LRANGE", key, 0, -1])[0] or []
