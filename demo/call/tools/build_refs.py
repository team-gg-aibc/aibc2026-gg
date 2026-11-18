"""접수 카드 맨 아래 「참고 자료」 칸에 보일 값을 원본에서 그대로 뽑아 web/refs.json으로 만든다(11-18 동규 확정: 일의 종류마다 다른 범용 참고 칸).

    python3 -I demo/call/tools/build_refs.py      → demo/call/web/refs.json

- 조례 원문의 값: engine/data/ordinances.json(엔진이 쓰는 조례 원문, 읽기만)에서 조문 · 별표의 글과 표 칸을 고치지 않고 옮긴다.
  주차 = 별표 1 공영주차장 주차요금표와 그 ※ · 비고 3, 제6조 제1항 / 금연 = 제10조 제1항 / 공원 · 노점 = 도시공원 조례 제23조 제1항 / 자전거 = 별표 요금표.
- 자리별 조례 6종 안팎: demo/call/data/routes.json의 갈래(scope · law)를 그대로. 화면의 「같은 일이 다른 자리였다면」 표에 칸 하나로 붙는다.
- 사람이 쓴 글(표 머리 · 단위 · 「없음」 줄 · 갈래 · 처리 기관 줄)은 여기 적지 않는다. 문구 파일 A-05의 「참고 자료」 표에 있고, refs.json에는 그 표의 「항목」 이름만 둔다(화면이 K('참고 자료')로 꺼낸다, PR #114 리뷰).
  표 이름은 원문 별표 제목에서 「(…관련)」만 뗀다. 바뀐 값이 원본과 맞는지 · 가리킨 이름이 문구 파일에 있는지는 check.py가 본다.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
ORD = {o["name"]: o for o in json.loads((ROOT / "engine" / "data" / "ordinances.json").read_text(encoding="utf-8"))}
TYPES = json.loads((HERE / "data" / "routes.json").read_text(encoding="utf-8"))["types"]
PARKING, SMOKE, PARK, BIKE = "서울특별시 주차장 설치 및 관리 조례", "서울특별시 금연환경 조성 및 간접흡연 피해방지조례", "서울특별시 도시공원 조례", "서울특별시 자전거이용 활성화에 관한 조례"
GAL = {"stray": "A3", "parking": "P1", "smoking": "S2", "park_use": "K3", "vendor": "K3", "bike": "C3"}      # 일의 종류 → 조항-갈래 표의 갈래 번호(글은 A-05 「갈래 ○」 · 「처리 기관 ○」)
ABSENT = {"parking": "주차 과태료 없음", "park_use": "공원 과태료 없음", "vendor": "공원 과태료 없음"}      # 일의 종류 → A-05 「참고 자료」의 「없음」 줄 이름
sp = lambda s: re.sub(r"\s+", " ", s).strip()      # noqa: E731


def meta(law):
    return {"law": law, "effective": ORD[law]["effective_date"], "url": ORD[law]["source_url"]}


def article(law, no, para):
    a = next(x for x in ORD[law]["articles"] if x["article"] == no)
    t = re.sub(r"\s*<(개정|신설)[^>]*>", "", sp(a["text"]))
    t = re.search(rf"{para}\s*(.*?)(?=\s[②-⑳]\s|$)", t).group(1).strip()
    return {"kind": "text", "where": f"{no} {a['title']} {para}", "text": t, **meta(law)}


def annex(law, label, keep):
    x = next(a for a in ORD[law]["annexes"] if a["label"] == label)
    rows = [[c.strip() for c in re.split(r"[│┃]", ln)[1:-1]] for ln in x["text"].splitlines() if re.match(r"\s*│\s*(\d급지|주차요금)", ln)]
    return x, [[r[i] for i in keep] for r in rows]


def table(law, x, rows, words, more=None):      # words = A-05 「참고 자료」의 「○ 요금표 머리 · 단위 · 더」 이름 앞부분
    return {"kind": "table", "where": f"{x['label']} {annex_name(x)}", "head": f"{words} 머리", "unit": f"{words} 단위", "rows": rows, **({"more": more} if more else {}), **meta(law)}


def annex_name(x):      # 별표 제목에서 「(제6조제1항 관련)」 같은 꼬리만 뗀다
    return re.sub(r"\s*\([^)]*관련\)\s*$", "", x["title"])


def quote(law, where, pattern, text):
    return {"kind": "quote", "where": where, "text": sp(re.search(pattern, text).group(1)), **meta(law)}


x, rows = annex(PARKING, "별표 1", [0, 1, 2, 3, 4])
REFS = {
    "parking": [table(PARKING, x, rows, "주차 요금표", more="주차 요금표 더"),
                quote(PARKING, "별표 1 ※", r"※ (개별주차장 요금은 해당 급지 주차요금에 공시지가 변수를 곱하여 산정한다\.)", x["text"]),
                dict(article(PARKING, "제6조", "①"), kind="quote"),
                quote(PARKING, "별표 1 비고 3", r"(급지는 다음 각 목과 같이 도시철도역 접근성 및 환승역·비환승역을 기준으로 선정한다\.)", x["text"])],
    "smoking": [article(SMOKE, "제10조", "①")],
    "park_use": [dict(article(PARK, "제23조", "①"), kind="quote")],
    "vendor": [dict(article(PARK, "제23조", "①"), kind="quote")],
}
bx, brows = annex(BIKE, "별표", [0, 1, 2, 3])
REFS["bike"] = [table(BIKE, bx, brows, "자전거 요금표")]
for k, t in ABSENT.items():
    REFS[k].append({"kind": "absent", "key": t})
for k, g in GAL.items():
    REFS.setdefault(k, []).append({"kind": "gal", "code": g})
out = {"note": "접수 카드 「참고 자료」 칸의 값. tools/build_refs.py가 만든다(손으로 고치지 않는다). check.py가 원본과 대조한다. head · unit · more · key · code는 문구 파일 A-05 「참고 자료」 표의 항목 이름",
       "gal_source": "소관 · 처리 기관 조사의 조항-갈래 표(2026-11-11)",
       "types": {k: {"scope": v["scope"], "law": v.get("law"), "routes": [{kk: r[kk] for kk in ("class", "scope", "law") if kk in r} for r in v["routes"]]} for k, v in TYPES.items()},
       "refs": REFS}
dest = HERE / "web" / "refs.json"
dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(dest.relative_to(ROOT), "· 일", len(REFS), "· 값", sum(len(v) for v in REFS.values()))
