"""Claude API 호출 도우미.

교안 PoC 지침에 따라 Anthropic SDK 없이 HTTP(httpx)로 직접 호출한다.
- 모델: Sonnet 5.5 (claude-sonnet-5-5), effort = medium
- API 키는 요청마다 브라우저가 보내 준 값만 쓰고, 저장하거나 로그로 남기지 않는다.
"""
import json
import os

import httpx

API_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
TIMEOUT = httpx.Timeout(300.0, connect=15.0)


class ClaudeError(Exception):
    """화면에 그대로 보여 줄 수 있는 오류 (status: 화면에 돌려줄 HTTP 상태)."""

    def __init__(self, message: str, detail: str = "", status: int = 502):
        super().__init__(message)
        self.message, self.detail, self.status = message, detail, status


HINTS = {
    400: "요청이 거절되었습니다. 크레딧 잔액이나 입력 파일을 확인해 주세요.",
    401: "API 키가 올바르지 않거나 비활성화되었습니다. 키를 다시 입력해 주세요.",
    403: "이 키로는 해당 모델을 쓸 권한이 없습니다.",
    404: "요청한 모델을 찾을 수 없습니다.",
    413: "파일이 너무 큽니다. 32MB 이하의 PDF를 올려 주세요.",
    429: "요청 한도를 넘었습니다. 잠시 뒤 다시 시도해 주세요.",
    529: "Claude 서버가 혼잡합니다. 잠시 뒤 다시 시도해 주세요.",
}


def _headers(api_key: str) -> dict:
    return {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2026-10-21",
        # 안전 분류기가 응답을 거절하면 서버가 자동으로 대체 모델로 다시 실행한다.
        "anthropic-beta": "server-side-fallback-2026-07-01",
    }


def _body(effort: str = EFFORT, **kw) -> dict:
    body = {"model": MODEL, "output_config": {"effort": effort}, "fallbacks": "default"}
    fmt = kw.pop("json_schema", None)
    if fmt:
        body["output_config"]["format"] = {"type": "json_schema", "schema": fmt}
    body.update(kw)
    return body


def _raise_for(status: int, raw: bytes):
    try:
        err = json.loads(raw).get("error", {})
    except (ValueError, AttributeError):
        err = {}
    detail = f"HTTP {status} / {err.get('type', 'unknown')}: {err.get('message', raw[:200].decode('utf-8', 'replace'))}"
    raise ClaudeError(HINTS.get(status, "Claude API 호출에 실패했습니다."), detail, 400 if status in (400, 401, 403) else 502)


def _check_stop(msg: dict):
    if msg.get("stop_reason") == "refusal":
        cat = (msg.get("stop_details") or {}).get("category")
        raise ClaudeError("Claude가 이 요청에 답하지 않았습니다.", f"stop_reason: refusal ({cat})", 422)
    if msg.get("stop_reason") == "max_tokens":
        raise ClaudeError("응답이 너무 길어 중간에 끊겼습니다.", "stop_reason: max_tokens")


async def create(api_key: str, **kw) -> dict:
    """한 번 호출하고 응답 전체(JSON)를 돌려준다."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(API_URL, headers=_headers(api_key), json=_body(**kw))
    except httpx.HTTPError as e:
        raise ClaudeError("Claude 서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.", type(e).__name__)
    if r.status_code != 200:
        _raise_for(r.status_code, r.content)
    msg = r.json()
    _check_stop(msg)
    return msg


def text_of(msg: dict) -> str:
    return "".join(b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text")


async def create_json(api_key: str, schema: dict, **kw) -> dict:
    """구조화된 출력(JSON 스키마)으로 호출하고 파싱한 dict를 돌려준다."""
    msg = await create(api_key, json_schema=schema, **kw)
    try:
        return json.loads(text_of(msg))
    except ValueError:
        raise ClaudeError("분석 결과를 읽지 못했습니다. 다시 시도해 주세요.", text_of(msg)[:200])


async def stream_text(api_key: str, **kw):
    """스트리밍 호출: 답변 글자 조각(text_delta)을 차례로 내보낸다."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            async with c.stream("POST", API_URL, headers=_headers(api_key), json=_body(stream=True, **kw)) as r:
                if r.status_code != 200:
                    _raise_for(r.status_code, await r.aread())
                stop = {}
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[5:])
                    t = ev.get("type")
                    if t == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                        yield ev["delta"]["text"]
                    elif t == "message_delta":
                        stop = {"stop_reason": ev["delta"].get("stop_reason"), "stop_details": ev["delta"].get("stop_details")}
                    elif t == "error":
                        raise ClaudeError("답변 도중 오류가 발생했습니다.", json.dumps(ev.get("error", {}), ensure_ascii=False))
                _check_stop(stop)
    except httpx.HTTPError as e:
        raise ClaudeError("Claude 서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.", type(e).__name__)
