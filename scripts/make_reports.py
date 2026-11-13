"""교안 CH3 UNIT 2: 2페이지짜리 스마트폰 불량 리포트 PDF(가짜 데이터)를 만든다.

- 1페이지: 문서번호, 작성일, 제품명, 부서, 불량유형, 타입, 작성자, 결재(작성-검토-승인)
- 2페이지: 불량률, 조치상태, 심각수준(Level 1~5), 발견일 등 수치 데이터와
          문제 원인, 불량 재현 방법, 재현율, 개선 방법, 결과
교안 PLAN의 10개 시나리오(갤러리 S 3 / A 4 / N 3) 중 5개만 만든다.

실행: .venv\\Scripts\\python.exe scripts\\make_reports.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent.parent / "sample_reports"
pdfmetrics.registerFont(TTFont("Malgun", r"C:\Windows\Fonts\malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBd", r"C:\Windows\Fonts\malgunbd.ttf"))

H1 = ParagraphStyle("h1", fontName="MalgunBd", fontSize=20, leading=26, spaceAfter=4)
H2 = ParagraphStyle("h2", fontName="MalgunBd", fontSize=13, leading=18, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("b", fontName="Malgun", fontSize=10, leading=15)
SMALL = ParagraphStyle("s", fontName="Malgun", fontSize=8.5, leading=12, textColor=colors.HexColor("#555555"))
INK = colors.HexColor("#1F2937")
GRID = colors.HexColor("#9CA3AF")
HEAD_BG = colors.HexColor("#E5E7EB")

REPORTS = [
    dict(no="QA-2611-001", date="2026-11-02", product="갤러리 S25 Ultra", line="갤러리 S", dept="디스플레이 품질팀",
         defect="화면 깜빡임", kind="하드웨어 / 디스플레이", writer="김하늘", reviewer="박준영", approver="이도윤",
         found="2026-10-27", produced=48000, defects=1152, level=4, status="조치 중", repro_rate=82,
         cause="저온(영하 5도 이하) 환경에서 디스플레이 드라이버 IC의 공급 전압이 3.1V까지 떨어지며 패널 리프레시 동기가 어긋난다. 전압 레귤레이터의 온도 보정 테이블이 최신 패널 사양을 반영하지 않았다.",
         steps=["단말을 영하 5도 챔버에 30분 보관", "화면 밝기를 70% 이상으로 설정", "120Hz 스크롤 화면을 2분간 유지", "화면 상단 1/3 영역에서 깜빡임 관찰"],
         fix="디스플레이 드라이버 펌웨어 v2.3 배포(온도 보정 테이블 갱신), 신규 생산분 전압 레귤레이터 부품 교체",
         result="펌웨어 적용 시험군 2,000대에서 재현율 82% → 6%로 감소. 부품 교체는 12월 1주 생산분부터 적용 예정",
         after=0.3),
    dict(no="QA-2611-002", date="2026-11-04", product="갤러리 S25", line="갤러리 S", dept="배터리 안전팀",
         defect="배터리 과열", kind="하드웨어 / 전원", writer="정유진", reviewer="최민석", approver="이도윤",
         found="2026-10-30", produced=52000, defects=936, level=5, status="긴급 대응", repro_rate=64,
         cause="45W 고속 충전 중 배터리 온도 센서(NTC)의 응답이 약 4초 지연되어 충전 전류 제한이 늦게 걸린다. 해당 로트 센서의 접착 두께 편차가 원인이다.",
         steps=["배터리 20% 상태에서 45W 충전기 연결", "충전 중 고사양 게임을 30분 실행", "후면 온도를 열화상 카메라로 측정", "후면 온도 48도 이상 도달 여부 확인"],
         fix="충전 전류 제한 로직을 센서 지연과 무관하게 동작하도록 소프트웨어 개선, 해당 로트(L2410-07) 센서 리콜 및 교체",
         result="소프트웨어 개선 후 최고 온도 48.6도 → 41.2도. 리콜 대상 3,200대 중 1,450대 교체 완료",
         after=0.6),
    dict(no="QA-2611-003", date="2026-11-05", product="갤러리 A56", line="갤러리 A", dept="카메라 모듈팀",
         defect="카메라 초점 불량", kind="하드웨어 / 카메라", writer="한지민", reviewer="오세훈", approver="윤서연",
         found="2026-10-21", produced=86000, defects=2666, level=3, status="원인 분석 완료", repro_rate=71,
         cause="렌즈 모듈 접착 공정의 경화 온도가 높아 렌즈 홀더가 미세하게 휘고, 접사 모드 전환 시 AF 액추에이터가 끝단에 걸린다.",
         steps=["카메라 앱 실행 후 일반 모드에서 촬영", "피사체 10cm 거리에서 접사 모드로 전환", "초점 고정 여부와 AF 소요 시간 측정", "3회 반복하여 초점이 맞지 않는 횟수 기록"],
         fix="접착제를 저온 경화형으로 변경하고 공정 온도를 8도 낮춤, AF 캘리브레이션 범위 확장 펌웨어 적용",
         result="파일럿 라인 5,000대 기준 불량률 3.1% → 0.9%",
         after=0.9),
    dict(no="QA-2611-004", date="2026-11-06", product="갤러리 A36", line="갤러리 A", dept="기구 품질팀",
         defect="충전 단자 접촉 불량", kind="하드웨어 / 커넥터", writer="서지호", reviewer="오세훈", approver="윤서연",
         found="2026-10-18", produced=64000, defects=1280, level=2, status="조치 완료", repro_rate=55,
         cause="USB-C 포트 납땜 공정에서 리플로우 온도 프로파일이 일부 구간 낮아 냉납이 발생했다.",
         steps=["충전 케이블을 정방향으로 연결", "케이블을 위아래로 15도 기울임", "충전 표시 끊김 여부 확인", "10회 반복하여 끊김 횟수 기록"],
         fix="리플로우 온도 프로파일 재설정, 납땜 후 X-ray 검사 비율 5% → 20% 상향, 불량 포트 교체",
         result="조치 후 4주간 신규 불량률 2.0% → 0.2%, 재발 없음",
         after=0.2),
    dict(no="QA-2611-005", date="2026-11-07", product="갤러리 N Fold", line="갤러리 N", dept="오디오 품질팀",
         defect="스피커 잡음", kind="하드웨어 / 오디오", writer="문가은", reviewer="강태호", approver="임수빈",
         found="2026-10-25", produced=21000, defects=252, level=2, status="조치 완료", repro_rate=40,
         cause="스피커 조립 라인의 클린룸 등급이 낮아 진동판 내부에 미세 이물이 들어갔다.",
         steps=["볼륨을 80% 이상으로 설정", "저음이 강한 테스트 음원 재생", "하단 스피커에서 지글거리는 잡음 확인", "5분간 반복 재생"],
         fix="스피커 조립 라인 클린룸 등급을 Class 10,000 → Class 1,000으로 상향, 조립 전 에어 블로우 공정 추가",
         result="조치 후 생산분 8,000대에서 불량률 1.2% → 0.1%",
         after=0.1),
]


def table(rows, widths, head_col=True):
    t = Table(rows, colWidths=widths)
    style = [("FONT", (0, 0), (-1, -1), "Malgun", 10), ("GRID", (0, 0), (-1, -1), 0.6, GRID),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
             ("TEXTCOLOR", (0, 0), (-1, -1), INK)]
    if head_col:
        style += [("BACKGROUND", (0, 0), (0, -1), HEAD_BG), ("FONT", (0, 0), (0, -1), "MalgunBd", 10)]
    t.setStyle(TableStyle(style))
    return t


def build(r):
    rate = round(r["defects"] / r["produced"] * 100, 1)
    story = [Paragraph("스마트폰 불량 분석 리포트", H1), Paragraph("가상 데이터로 만든 실습용 문서입니다.", SMALL), Spacer(1, 8 * mm)]
    # 1페이지: 문서 기본 정보와 결재
    story += [Paragraph("1. 문서 정보", H2), table([
        ["문서번호", r["no"]], ["작성일", r["date"]], ["제품명", r["product"]], ["제품군", r["line"]],
        ["부서", r["dept"]], ["불량유형", r["defect"]], ["타입", r["kind"]], ["작성자", r["writer"]],
    ], [40 * mm, 120 * mm])]
    story += [Paragraph("2. 결재", H2)]
    appr = Table([["작성", "검토", "승인"], [r["writer"], r["reviewer"], r["approver"]], ["완료", "완료", "완료" if r["status"] == "조치 완료" else "대기"]],
                 colWidths=[40 * mm] * 3, rowHeights=[8 * mm, 16 * mm, 8 * mm])
    appr.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Malgun", 10), ("FONT", (0, 0), (-1, 0), "MalgunBd", 10),
                              ("GRID", (0, 0), (-1, -1), 0.6, GRID), ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                              ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [appr, Spacer(1, 6 * mm), Paragraph("3. 개요", H2),
              Paragraph(f"{r['product']}에서 '{r['defect']}' 불량이 보고되었다. 상세 수치와 원인, 재현 방법, 개선 결과는 2페이지에 정리한다.", BODY),
              PageBreak()]
    # 2페이지: 상세 수치와 분석
    story += [Paragraph("4. 상세 수치", H2), table([
        ["발견일", r["found"]], ["생산 수량", f"{r['produced']:,}대"], ["불량 수량", f"{r['defects']:,}대"],
        ["불량률", f"{rate}%"], ["심각 수준", f"Level {r['level']} (1~5)"], ["재현율", f"{r['repro_rate']}%"],
        ["조치 상태", r["status"]], ["개선 후 불량률", f"{r['after']}%"],
    ], [40 * mm, 120 * mm])]
    story += [Paragraph("5. 문제 원인", H2), Paragraph(r["cause"], BODY),
              Paragraph("6. 불량 재현 방법", H2)]
    story += [Paragraph(f"{i}) {s}", BODY) for i, s in enumerate(r["steps"], 1)]
    story += [Paragraph("7. 개선 방법", H2), Paragraph(r["fix"], BODY),
              Paragraph("8. 결과", H2), Paragraph(r["result"], BODY)]
    path = OUT / f"{r['no']}.pdf"
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
                      title=f"{r['no']} {r['defect']}").build(story)
    return path


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for r in REPORTS:
        print("생성:", build(r).name)
