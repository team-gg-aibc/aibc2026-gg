"""평가셋 검수용 엑셀을 사람마다 한 파일씩 만든다 (2차 회의 10/27 검수 분담, 10/28 동규: 사람마다 양이 비슷하게).

사용: python3 eval/review_sheets.py <출력 폴더>

실제 비슷한 세트는 전부 볼 문항(여러 조항 결합 · 함정 · 회색지대 · 「사람 확인」)을 모두 넣고,
나머지는 파일 순서대로 5개 중 1개를 표본으로 넣는다. 극한 세트는 모두 넣는다.
10-30: 「기계 점검」(check.py와 함정 검색기 eval/verify/trap_scan.json) · 「다른 모델 판정」(eval/verify/astra_compare.json) 칸을 더했다.
표본 밖이라도 둘 중 하나에 걸린 문항은 「어긋남」으로 넣고, 시트마다 걸린 문항을 위에 둔다. 표본을 고르는 방식은 그대로다.
"""
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from check import load_sources, problems

HERE = Path(__file__).parent
FIRST_DUE, PAIR_DUE = "11/1(일)", "11/6(금)"  # 동규가 넘길 때 정한다
ORD = {  # 키: (짧은 이름, 정식 이름, 법제처 판 번호)
    "parking": ("주차장", "서울특별시 주차장 설치 및 관리 조례", 2171833),
    "park": ("도시공원", "서울특별시 도시공원 조례", 2147709),
    "smoking": ("금연", "서울특별시 금연환경 조성 및 간접흡연 피해방지조례", 2171803),
    "animal": ("동물보호", "서울특별시 동물보호 조례", 2171829),
    "bicycle": ("자전거", "서울특별시 자전거이용 활성화에 관한 조례", 2171767),
    "youth": ("청년", "서울특별시 청년 기본 조례", 2054497),
    "common": ("공통 함정", "", 0),
    "new": ("새 함정", "", 0),  # 10-30 동규 몫 묶음 = stress_common.json
}
FOCUS = {  # README 「검수 분담」의 특히 볼 것
    "parking": "별표 1 요금표, 제7조 감면과 제3항 「높은 하나만」(10/1 개정), 계산 문항, 별표 2~4(부설주차장)",
    "park": "제20조 면제 · 감면, 금주구역(제22조의3 · 제23조 제4항), 별표 1 입장료는 금액 「범위」",
    "smoking": "금연구역 지정 장소(제5조 제1항 각 호)",
    "animal": "등록수수료 감면(제28조)",
    "bicycle": "자전거주차장 요금(원칙 무료 + 별표는 상한), 따릉이 감면(제12조의3)",
    "youth": "회색지대 12개, 항 없는 조(제3조)",
    "common": "함정 53개가 6종에 정말 없는지 (source/*.md 6개에서 질문의 핵심어를 찾아본다)",
    "new": "섞인 질문은 답할 부분만 답하고 나머지는 확인 불가, 없는 조 번호는 「그런 조 없음」, 틀린 전제는 「아니요」가 맞는지",
}
# 이름: (파일 이름, 짝, [(키, 세트)]). 공통의 극한 세트 = 10-30 새 함정 묶음(stress_common.json)
PLAN = {
    "건영": ("geonyeong", "동규", [("park", "실제"), ("park", "극한"), ("smoking", "실제"), ("smoking", "극한")]),
    "동욱": ("dongwook", "종희", [("parking", "실제"), ("parking", "극한"), ("bicycle", "극한")]),
    "종희": ("jonghee", "동욱", [("animal", "실제"), ("animal", "극한"), ("bicycle", "실제")]),
    "동규": ("donggyu", "건영", [("youth", "실제"), ("youth", "극한"), ("common", "실제"), ("common", "극한")]),
}
COLS = [("번호", 6), ("id", 14), ("왜 보나", 15), ("유형", 11), ("질문", 45), ("고치기 전 질문", 30),
        ("정답 조항", 24), ("정답 조항 원문", 60), ("정답 열쇠", 40), ("기계 점검", 30), ("다른 모델 판정(astra)", 40),
        ("메모", 30), ("개발 · 확인용 / 태그", 13),
        ("검수 결과", 11), ("고친 질문", 30), ("고친 정답 조항", 22), ("고친 정답 열쇠", 30), ("검수 메모", 30)]
FILL_FROM = 14  # 14번째 칸(N)부터 검수하는 사람이 채운다
FILL, LAST = get_column_letter(FILL_FROM), get_column_letter(len(COLS))
RESULTS = "맞음,고침,빼기,모르겠음"
FONT, BOLD = Font(name="Arial", size=10), Font(name="Arial", size=10, bold=True)
GRAY, YELLOW_HEAD, YELLOW, RED = (PatternFill("solid", fgColor=c) for c in ("D9D9D9", "FFE699", "FFF2CC", "F8CBAD"))
WRAP = Alignment(wrap_text=True, vertical="top")
UNITS = load_sources()
SCAN = json.loads((HERE / "verify" / "trap_scan.json").read_text(encoding="utf-8"))
ASTRA = json.loads((HERE / "verify" / "astra_compare.json").read_text(encoding="utf-8"))["rows"]


def machine(q):
    """기계 점검 칸: check.py가 사람 확인으로 돌리는 것 + 함정 검색기의 비슷한 말. 계산식은 맞으면 식을 보여 준다."""
    review = problems(q, UNITS)[1]
    review += [f"검색기: {short(label)}에 점검 핵심어 「{w}」에 가까운 말이 있음" for qid, w, label in SCAN["near"] if qid == q["id"]]
    if "calc" in q and not any(r.startswith("계산식") for r in review):
        review.append("계산식을 코드로 다시 계산해 맞음: " + " · ".join(q["calc"]))
    return review


def astra_cell(q):
    """(어긋남 목록, 칸 글). 「참고:」로 시작하는 약한 표시(정답 열쇠에 없는 수)는 어긋남에 넣지 않고 칸에만 적는다."""
    row = ASTRA.get(q["id"])
    if not row or not row["astra"]:
        return [], "다른 모델 답 없음"
    a = row["astra"]
    hard = [f for f in row["flags"] if not f.startswith("참고:")]
    soft = [f for f in row["flags"] if f.startswith("참고:")]
    said = f"다른 모델 답({a['verdict']}): {a['answer']}" + (f"\n근거: {' · '.join(short(c) for c in a['cites'])}" if a["cites"] else "")
    head = ("어긋남: " + " / ".join(hard) if hard else "같음") + ("\n" + " / ".join(soft) if soft else "")
    return hard, head + "\n" + said


def odd(q):
    """기계 점검이나 다른 모델 판정에 걸렸나(계산식이 맞았다는 표시는 걸린 것이 아님)."""
    return bool([r for r in machine(q) if not r.startswith("계산식을 코드로")] or astra_cell(q)[0])


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def flagged(q):
    return "[사람 확인" in q.get("note", "")


def why(q):
    n = q.get("note", "")
    if flagged(q):
        return "전부 · 사람 확인"
    if "[회색지대]" in n:
        return "전부 · 회색지대"
    if q["type"] == "근거 없음 (함정)":
        return "전부 · 함정"
    if q["type"] == "여러 조항 결합":
        return "전부 · 결합"
    return "표본"


def pick(key, kind):
    if kind == "극한":
        qs = load(f"stress_{key}.json")
        rows = [("극한 · 사람 확인" if flagged(q) else "극한", q) for q in qs]
    else:
        qs = load(f"questions_{key}.json")
        must = [q for q in qs if why(q) != "표본"]
        rest = [q for q in qs if why(q) == "표본"]
        sample = rest[::5]  # 틀린 비율을 재는 표본이라 고르는 방식을 바꾸지 않는다
        extra = [q for q in rest if q not in sample and odd(q)]
        rows = [(why(q), q) for q in must] + [("표본", q) for q in sample] + [("어긋남", q) for q in extra]
    return sorted(rows, key=lambda row: not odd(row[1]))  # 걸린 문항을 위로(같은 무리 안의 순서는 그대로)


def short(label):
    for name, full, _ in ORD.values():
        if full and label.startswith(full):
            return name + " 조례" + label[len(full):]
    return label


def gold_cells(q):
    if not q["gold"]:
        return "없음 (함정)", "6종 어디에도 근거가 없어야 정답이다"
    labels = " + ".join(" 또는 ".join(short(x) for x in group) for group in q["gold"])
    texts = []
    for group in q["gold"]:
        for x in group:
            t = UNITS.get(x, "(원문을 찾지 못함)")
            texts.append(f"[{short(x)}] " + (t if len(t) <= 1200 else t[:1200] + " …(뒤는 원문 사본에서)"))
    return labels, "\n".join(texts)


def data_sheet(wb, title, rows):
    ws = wb.create_sheet(title)
    for c, (head, width) in enumerate(COLS, 1):
        cell = ws.cell(1, c, head)
        cell.font, cell.alignment = BOLD, WRAP
        cell.fill = YELLOW_HEAD if c >= FILL_FROM else GRAY
        ws.column_dimensions[cell.column_letter].width = width
    for r, (reason, q) in enumerate(rows, 2):
        labels, text = gold_cells(q)
        extra = q.get("split") or " · ".join(q.get("tags", []))
        found = machine(q)
        flags, said = astra_cell(q)
        values = [r - 1, q["id"], reason, q["type"], q["question"], q.get("question_orig", ""), labels, text,
                  q.get("answer_key", ""), "\n".join(found), said, q.get("note", ""), extra] + [None] * (len(COLS) - FILL_FROM + 1)
        for c, v in enumerate(values, 1):
            cell = ws.cell(r, c, v)
            cell.font, cell.alignment = FONT, WRAP
            if c >= FILL_FROM:
                cell.fill = YELLOW
        if [x for x in found if not x.startswith("계산식을 코드로")]:
            ws.cell(r, 10).fill = RED
        if flags:
            ws.cell(r, 11).fill = RED
    last = len(rows) + 1
    dv = DataValidation(type="list", formula1=f'"{RESULTS}"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{FILL}2:{FILL}{last}")
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = f"A1:{LAST}{last}"
    return len(rows)


def guide_sheet(ws, name, partner, sheets, keys):
    total = sum(n for _, n in sheets)
    lines = [
        (f"GG 평가셋 검수 · {name}", True),
        ("", False),
        (f"맡은 것: {' + '.join(ORD[k][0] for k in keys)} · 모두 {total}문항", True),
        (f"마감: {FIRST_DUE}까지 1차 검수 → {PAIR_DUE}까지 짝 검수 (짝: {partner})", True),
        ("", False),
        ("하는 순서", True),
        ("1. 시트를 왼쪽부터 차례로 연다. 실제 비슷한 세트를 먼저, 극한 세트는 그다음에 본다.", False),
        ("2. 문항마다 질문 · 정답 조항 원문 · 정답 열쇠를 읽고, 노란 칸을 채운다. 회색 칸은 고치지 않는다.", False),
        ("3. 다 끝나면 이 파일을 디스코드로 동규에게 보낸다. 평가셋 파일에는 동규가 옮긴다.", False),
        (f"4. 짝 검수: {partner}의 파일에서 검수 결과가 「고침 · 빼기 · 모르겠음」인 문항만 다시 보고, 의견을 검수 메모에 더한다.", False),
        ("", False),
        ("문항마다 볼 것", True),
        ("- 정답 조항에 정말 답이 있나? 더 맞는 항이 따로 있지는 않나?", False),
        ("- 질문이 실제로 들을 법한 시민 말투인가? 고치면 정답 조항이 그대로인가?", False),
        ("- 정답 열쇠에 원문에 없는 사실이 들어가지 않았나? 조건 판단의 「네 / 아니요」가 맞나?", False),
        ("- 함정은 6종 어디에도 정말 근거가 없나?", False),
        ("- 애매해서 정답을 정하기 어려운 문항은 「모르겠음」을 고르고 이유를 적는다. 모아서 운영진에 묻는다.", False),
        ("", False),
        ("노란 칸 쓰는 법", True),
        (f"- 검수 결과: {RESULTS.replace(',', ' · ')} 중 하나를 고른다 (칸을 누르면 고르는 목록이 나온다)", False),
        ("- 고친 질문 · 고친 정답 조항 · 고친 정답 열쇠: 고칠 때만 쓴다. 조항은 「주차장 조례 제7조 제1항」처럼 쓴다", False),
        ("- 검수 메모: 왜 고쳤는지, 왜 빼는지, 무엇이 애매한지", False),
        ("", False),
        ("회색 칸 뜻", True),
        ("- 왜 보나: 「전부 · ○○」는 꼭 봐야 하는 문항, 「표본」은 나머지 5개 중 1개, 「극한」은 약점 찾기용 문항, 「어긋남」은 표본 밖이지만 아래 두 칸에 걸려서 넣은 문항", False),
        ("- 기계 점검: 코드가 찾은 것(정답 열쇠의 숫자 · 「」 낱말이 원문에 없음, 계산식을 다시 계산한 결과, 함정 낱말과 비슷한 말이 원문에 있음)", False),
        ("- 다른 모델 판정(astra): 다른 회사 모델이 정답을 보지 않고 조례 원문만 읽고 푼 답. 「어긋남」이면 원문을 보고 우리 정답과 다른 모델 중 누가 맞는지 정한다. 다른 모델이 틀릴 때도 많다", False),
        ("- 두 칸 가운데 하나라도 걸린 문항은 빨간 칸이고 시트 위쪽에 모아 두었다. 걸린 문항부터 본다", False),
        ("- 개발 · 확인용: holdout은 마지막 확인용이다. 검수는 똑같이 하지만, 엔진을 고칠 때 holdout 문항을 보고 고치지 않는다", False),
        ("- 정답 조항 원문이 길면 앞부분만 넣었다. 전체는 팀 레포 eval/source/ 의 원문 사본이나 아래 법제처 링크에서 본다", False),
        ("", False),
        ("특히 볼 것", True),
    ]
    lines += [(f"- {ORD[k][0]}: {FOCUS[k]}", False) for k in keys]
    lines += [("", False), ("원문 (법제처)", True)]
    lines += [(f"- {ORD[k][1]}: https://www.law.go.kr/ordinInfoP.do?ordinSeq={ORD[k][2]}", False) for k in keys if ORD[k][2]]
    for r, (text, bold) in enumerate(lines, 1):
        ws.cell(r, 1, text).font = Font(name="Arial", size=14 if r == 1 else 10, bold=bold)
    r = len(lines) + 2
    ws.cell(r, 1, "진행 상황 (검수 결과를 채우면 저절로 바뀐다)").font = BOLD
    r += 1
    for c, head in enumerate(["시트", "문항", "검수 끝", "남음"], 1):
        cell = ws.cell(r, c, head)
        cell.font, cell.fill = BOLD, GRAY
    first = r + 1
    for title, n in sheets:
        r += 1
        ref = f"'{title}'"
        ws.cell(r, 1, title)
        ws.cell(r, 2, f"=COUNTA({ref}!B2:B{n + 1})")
        ws.cell(r, 3, f"=COUNTA({ref}!{FILL}2:{FILL}{n + 1})")
        ws.cell(r, 4, f"=B{r}-C{r}")
    r += 1
    ws.cell(r, 1, "합계").font = BOLD
    for c in "BCD":
        ws[f"{c}{r}"] = f"=SUM({c}{first}:{c}{r - 1})"
    for row in ws.iter_rows(min_row=first - 1, max_row=r):
        for cell in row:
            cell.font = BOLD if cell.row in (first - 1, r) else FONT
    r += 2
    ws.cell(r, 1, "쓰는 예시 (실제 문항이 아니라 쓰는 법만 보여 줌)").font = BOLD
    example = [("검수 결과", "고친 질문", "고친 정답 조항", "고친 정답 열쇠", "검수 메모"),
               ("맞음", "", "", "", ""),
               ("고침", "서울 공영주차장에 경차 끌고 가면 주차비 얼마나 깎아 줘요?", "", "",
                "조문 낱말을 그대로 써서 시민 말투로 바꿈. 정답 조항은 그대로"),
               ("모르겠음", "", "", "", "조문은 있는데 금액이 없어서 정답이 「확인 불가」인지 모르겠음 → 운영진 질문")]
    for i, vals in enumerate(example):
        r += 1
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v)
            cell.font = BOLD if i == 0 else FONT
            cell.fill = YELLOW_HEAD if i == 0 else YELLOW
            cell.alignment = WRAP
    ws.column_dimensions["A"].width = 30
    for c in "BCDE":
        ws.column_dimensions[c].width = 22


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    for name, (file_name, partner, parts) in PLAN.items():
        wb = Workbook()
        guide = wb.active
        guide.title = "안내"
        titles = [{"실제": ORD[k][0], "극한": "새 함정"}[kind] if k == "common" else f"{ORD[k][0]} {kind}" for k, kind in parts]
        sheets = [(t, data_sheet(wb, t, pick(k, kind))) for t, (k, kind) in zip(titles, parts)]
        keys = list(dict.fromkeys("new" if (k, kind) == ("common", "극한") else k for k, kind in parts))
        guide_sheet(guide, name, partner, sheets, keys)
        path = out / f"GG-eval-review-{file_name}.xlsx"
        wb.save(path)
        print(f"{name}: {sum(n for _, n in sheets)}문항 " + ", ".join(f"{t} {n}" for t, n in sheets) + f" → {path.name}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
