"""CH3 불량 리포트 분석 Dashboard + 챗봇.

교안 PRD:
- 불량분석 리포트 PDF들을 여러 개 불러와 Claude API로 분석하여 Text를 정리해 둔다.
- 정리된 Text 내용을 하나로 모아 사용자가 확인할 수 있다.
- 분석이 끝나면 전체 요약 Page와 Dashboard 탭이 보여진다.
- 화면 한쪽의 챗봇이 불량 데이터를 이해하고 대화할 수 있다.
"""
import base64
import json

import claude_api

# ── 1) 리포트 한 건 분석: PDF를 Claude에게 그대로 보여 주고 정해진 항목을 뽑는다.
REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["doc_no", "created_date", "product", "product_line", "department", "defect_type", "category",
                 "author", "approval", "found_date", "production_qty", "defect_qty", "defect_rate", "severity",
                 "status", "reproduction_rate", "improved_defect_rate", "cause", "reproduction_steps",
                 "improvement", "result", "summary"],
    "properties": {
        "doc_no": {"type": "string", "description": "문서번호"},
        "created_date": {"type": "string", "description": "작성일 YYYY-MM-DD"},
        "product": {"type": "string", "description": "제품명 전체 (예: 갤러리 S25 Ultra)"},
        "product_line": {"type": "string", "description": "제품군: 갤러리 S / 갤러리 A / 갤러리 N 중 하나"},
        "department": {"type": "string"},
        "defect_type": {"type": "string", "description": "불량유형 (예: 화면 깜빡임)"},
        "category": {"type": "string", "description": "타입 (예: 하드웨어 / 디스플레이)"},
        "author": {"type": "string"},
        "approval": {"type": "string", "description": "결재 흐름 요약 (예: 작성 김하늘 완료 → 검토 박준영 완료 → 승인 이도윤 대기)"},
        "found_date": {"type": "string", "description": "발견일 YYYY-MM-DD"},
        "production_qty": {"type": ["integer", "null"], "description": "생산 수량(대). 없으면 null"},
        "defect_qty": {"type": ["integer", "null"], "description": "불량 수량(대). 없으면 null"},
        "defect_rate": {"type": "number", "description": "불량률(%) 숫자만"},
        "severity": {"type": "integer", "description": "심각 수준 Level 1~5"},
        "status": {"type": "string", "description": "조치 상태"},
        "reproduction_rate": {"type": ["number", "null"], "description": "재현율(%) 숫자만"},
        "improved_defect_rate": {"type": ["number", "null"], "description": "개선 후 불량률(%). 없으면 null"},
        "cause": {"type": "string", "description": "문제 원인을 2~3문장으로"},
        "reproduction_steps": {"type": "array", "items": {"type": "string"}, "description": "재현 절차"},
        "improvement": {"type": "string", "description": "개선 방법"},
        "result": {"type": "string", "description": "개선 결과 (수치 포함)"},
        "summary": {"type": "string", "description": "이 리포트의 핵심을 한두 문장으로"},
    },
}

REPORT_PROMPT = """첨부한 PDF는 스마트폰 불량 분석 리포트입니다.
문서에 적힌 내용만 근거로 각 항목을 채워 주세요. 문서에 없는 값은 추측하지 말고 null로 두세요.
퍼센트 값은 숫자만 적습니다(예: "2.4%" → 2.4). 문장은 한국어로, 보고서 문체로 간결하게 씁니다."""


async def analyze_report(api_key: str, pdf: bytes, filename: str) -> dict:
    data = await claude_api.create_json(
        api_key, REPORT_SCHEMA, max_tokens=16000,
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.b64encode(pdf).decode()}, "title": filename},
            {"type": "text", "text": REPORT_PROMPT},
        ]}],
    )
    data["file"] = filename
    return data


# ── 2) 전체 요약: 분석된 리포트들을 모아 경영진 보고용 요약을 만든다.
SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "key_findings", "priorities", "by_product_line"],
    "properties": {
        "headline": {"type": "string", "description": "전체 상황을 한 문장으로"},
        "key_findings": {"type": "array", "items": {"type": "string"}, "description": "핵심 발견 3~5개"},
        "priorities": {"type": "array", "description": "먼저 대응할 순서", "items": {
            "type": "object", "additionalProperties": False, "required": ["doc_no", "title", "reason"],
            "properties": {"doc_no": {"type": "string"}, "title": {"type": "string"}, "reason": {"type": "string"}}}},
        "by_product_line": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["product_line", "note"],
            "properties": {"product_line": {"type": "string"}, "note": {"type": "string"}}}},
    },
}

SUMMARY_PROMPT = """아래는 스마트폰 불량 리포트 {n}건을 분석한 데이터(JSON)입니다.
품질 담당 임원에게 보고한다고 생각하고 전체 상황을 요약해 주세요.
- 심각 수준, 불량률, 조치 상태를 함께 보고 대응 우선순위를 정합니다.
- 숫자는 데이터에 있는 값만 씁니다.
- 한국어로, 짧고 분명하게 씁니다.

<reports>
{data}
</reports>"""


def _compact(reports: list[dict]) -> str:
    return json.dumps(reports, ensure_ascii=False)


async def summarize(api_key: str, reports: list[dict]) -> dict:
    return await claude_api.create_json(
        api_key, SUMMARY_SCHEMA, max_tokens=16000,
        messages=[{"role": "user", "content": SUMMARY_PROMPT.format(n=len(reports), data=_compact(reports))}],
    )


# ── 3) 챗봇: 분석 데이터를 시스템 프롬프트에 넣어 불량 데이터를 이해한 상태로 대화한다.
CHAT_SYSTEM = """당신은 스마트폰 품질 분석 도우미입니다. 사용자는 품질 담당자입니다.
아래 <reports>의 불량 리포트 분석 데이터와 <summary>만 근거로 답하세요.
데이터에 없는 내용은 모른다고 말하고, 어떤 리포트를 보면 되는지 안내하세요.
답할 때 관련 리포트의 문서번호를 함께 적고, 숫자는 데이터 그대로 인용하세요.
한국어로 간결하게 답하고, 목록이 도움이 될 때만 목록을 씁니다. 마크다운 표는 쓰지 마세요.

<reports>
{reports}
</reports>
<summary>
{summary}
</summary>"""


def chat_stream(api_key: str, reports: list[dict], summary: dict | None, messages: list[dict]):
    return claude_api.stream_text(
        api_key, max_tokens=16000,
        system=CHAT_SYSTEM.format(reports=_compact(reports), summary=json.dumps(summary or {}, ensure_ascii=False)),
        messages=messages,
    )
