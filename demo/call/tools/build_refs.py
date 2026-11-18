"""접수 카드 맨 아래 「참고 자료」 칸에 보일 값을 원본에서 그대로 뽑아 web/refs.json으로 만든다(11-18 동규 확정: 일의 종류마다 다른 범용 참고 칸).

    python3 -I demo/call/tools/build_refs.py      → demo/call/web/refs.json

- 조례 원문의 값: engine/data/ordinances.json(엔진이 쓰는 조례 원문, 읽기만)에서 조문 · 별표의 글과 표 칸을 고치지 않고 옮긴다.
  주차 = 별표 1 공영주차장 주차요금표와 그 ※ · 비고 3, 제6조 제1항 / 금연 = 제10조 제1항 / 공원 · 노점 = 도시공원 조례 제23조 제1항 / 자전거 = 별표 요금표.
- 자리별 조례 6종 안팎: demo/call/data/routes.json의 갈래(scope · law)를 그대로. 화면의 「같은 일이 다른 자리였다면」 표에 칸 하나로 붙는다.
- 처리 기관 한 줄: 소관 · 처리 기관 조사(PM 쪽 조항-갈래 표, 2026-11-11)의 그 갈래 줄 「처리 기관」 칸을 그대로 옮겨 적었다(아래 GAL).
- 「없음」 줄은 원문을 낱말로 찾아 본 결과다(아래 ABSENT). 바뀐 값이 원본과 맞는지는 check.py가 글자로 대조한다.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
ORD = {o["name"]: o for o in json.loads((ROOT / "engine" / "data" / "ordinances.json").read_text(encoding="utf-8"))}
TYPES = json.loads((HERE / "data" / "routes.json").read_text(encoding="utf-8"))["types"]
PARKING, SMOKE, PARK, BIKE = "서울특별시 주차장 설치 및 관리 조례", "서울특별시 금연환경 조성 및 간접흡연 피해방지조례", "서울특별시 도시공원 조례", "서울특별시 자전거이용 활성화에 관한 조례"
GAL = {      # 일의 종류 → (갈래, 그 갈래의 처리 기관). 소관 · 처리 기관 조사의 조항-갈래 표에서 그대로
    "stray": ("A3 유기 · 피학대 동물 구조 · 보호 · 입양 · 반환", "자치구 · 동물보호센터 (구청장이 구조 · 보호, 센터 지정)"),
    "parking": ("P1 공영주차장 요금 · 감면 · 징수 · 환불", "서울시설공단 주차시설운영처 (시 공영주차장)"),
    "smoking": ("S2 금연구역 흡연 단속 · 과태료 · 금연지도원", "적발한 자치구 보건소 (서울시가 25개 자치구와 함께 단속, 시가 관리하는 도시공원은 그 공원을 관리하는 사업소)"),
    "park_use": ("K3 공원 금지행위 · 금주구역 · 과태료", "그 공원을 관리하는 기관 (과태료 부과도 별표 6의 수임기관, 금주구역 과태료는 구청장에게 맡길 수 있음)"),
    "vendor": ("K3 공원 금지행위 · 금주구역 · 과태료", "그 공원을 관리하는 기관 (과태료 부과도 별표 6의 수임기관, 금주구역 과태료는 구청장에게 맡길 수 있음)"),
    "bike": ("C3 자전거 주차장 · 보관소 · 수리센터 · 방치 자전거", "자치구 (방치 자전거 수거 · 처분은 구청, 주차장 · 보관대 관리도 구청장에게 위임 가능)"),
}
ABSENT = {      # 원문을 찾아 본 결과(찾은 낱말은 괄호 밖 설명 대신 여기 주석으로): 주차 = 「주정차 · 불법주차 · 견인」이 6종 어디에도 과태료 조문으로 없음
    "parking": "불법 주정차 과태료 조문: 조례 6종 원문에 없음",
    "park_use": "과태료 금액: 도시공원 조례에는 없음(위 제23조대로 시행령 별표 4를 따름)",
    "vendor": "과태료 금액: 도시공원 조례에는 없음(위 제23조대로 시행령 별표 4를 따름)",
}
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


def quote(law, where, pattern, text):
    return {"kind": "quote", "where": where, "text": sp(re.search(pattern, text).group(1)), **meta(law)}


x, rows = annex(PARKING, "별표 1", [0, 1, 2, 3, 4])
REFS = {
    "parking": [{"kind": "table", "where": f"{x['label']} 공영주차장 주차요금표", "unit": "원 · 1구획당", "head": ["급지", "노상 5분당", "노상 1일권(야간)", "노외 5분당", "노외 1일"],
                 "rows": rows, "more": "월 정기권(전일 · 야간)은 원문 표에", **meta(PARKING)},
                quote(PARKING, "별표 1 ※", r"※ (개별주차장 요금은 해당 급지 주차요금에 공시지가 변수를 곱하여 산정한다\.)", x["text"]),
                dict(article(PARKING, "제6조", "①"), kind="quote"),
                quote(PARKING, "별표 1 비고 3", r"(급지는 다음 각 목과 같이 도시철도역 접근성 및 환승역·비환승역을 기준으로 선정한다\.)", x["text"])],
    "smoking": [article(SMOKE, "제10조", "①")],
    "park_use": [dict(article(PARK, "제23조", "①"), kind="quote")],
    "vendor": [dict(article(PARK, "제23조", "①"), kind="quote")],
}
bx, brows = annex(BIKE, "별표", [0, 1, 2, 3])
REFS["bike"] = [{"kind": "table", "where": f"{bx['label']} 자전거주차장 요금표", "unit": "원", "head": ["구분", "1회(1시간당)", "1일주차권", "월 정기권"], "rows": brows, **meta(BIKE)}]
for k, t in ABSENT.items():
    REFS[k].append({"kind": "absent", "text": t})
for k, (g, a) in GAL.items():
    REFS.setdefault(k, []).append({"kind": "gal", "gal": g, "agency": a})
out = {"note": "접수 카드 「참고 자료」 칸의 값. tools/build_refs.py가 만든다(손으로 고치지 않는다). check.py가 원본과 대조한다",
       "gal_source": "소관 · 처리 기관 조사의 조항-갈래 표(2026-11-11)",
       "types": {k: {"scope": v["scope"], "law": v.get("law"), "routes": [{kk: r[kk] for kk in ("class", "scope", "law") if kk in r} for r in v["routes"]]} for k, v in TYPES.items()},
       "refs": REFS}
dest = HERE / "web" / "refs.json"
dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(dest.relative_to(ROOT), "· 일", len(REFS), "· 값", sum(len(v) for v in REFS.values()))
