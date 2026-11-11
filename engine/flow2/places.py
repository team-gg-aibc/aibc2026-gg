"""flow2 곳 표(#82): 6종 밖 서울특별시 조례가 이름을 걸고 다스리는 곳의 목록(places.json).

왜: 새 흐름 ③은 「이 곳이 이 조례가 말하는 곳인가」를 가리지 못한다. 예) 「서울특별시 한강공원 보전 및 이용에 관한 기본 조례」
제3조 제1호는 한강공원을 「도시공원 및 녹지 등에 관한 법률」의 공원녹지로서 한강수계 둔치라고 따로 정의하고, 제17조 제1항이
한강공원 안의 금지행위(무단 상행위 · 야영 · 취사 등)를 직접 정한다. 도시공원 조례의 「공원」은 같은 법의 「도시공원」이라
다른 말이다(도시공원 조례 제2조 제4호). 그래서 한강공원의 노점을 도시공원 조례로 답하면 원문에 없는 전제로 지어낸 답이 된다.

표의 칸(조례 하나에 한 줄)
- law · mst · effective_date · source_url: 그 조례(법령 API로 받은 판)
- places: 그 조례가 이름을 걸고 다스리는 곳 낱말. 모두 그 조례 원문에 글자 그대로 있다
- rivals: 이 곳의 질문을 대신 받으려 드는 6종 열쇠(ontology.LAW_KEYS). ③이 고른 조례가 모두 rivals이고 그 원문에 곳 낱말이 없을 때만 막는다
- evidence: 정의 · 적용범위 · 금지행위 조항의 구절(원문 글자 그대로). why: rivals를 그렇게 둔 까닭
- candidates: 이름에 곳 낱말이 든 서울특별시 조례 전체(고르지 않은 것도 남겨 검토할 수 있게)

출처는 서울특별시 조례 원문뿐이다(평가 문항에서 가져오지 않는다). 채점 중에는 법령 API를 부르지 않는다(이 파일만 읽는다).
만들기: LAW_OC=<열쇠> python -m engine.flow2.places --build   (법령 API, 몇 초)
점검:  python -m engine.flow2.places --check                   (키 없이: 칸 모양 · 곳 낱말이 증거 구절에 있는지)
"""
import json
import re
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parent / "places.json"
SEOUL = "6110000"   # 법령 API 지자체 기관 코드: 서울특별시 본청
# 이름에 곳이 드는 조례를 훑는 낱말(후보만 고른다. 표에 넣을지는 아래 PICK에서 사람이 정하고 까닭을 적는다)
PLACE_NAME = re.compile(r"공원|광장|숲|한강|천(?:\s|변|의|$)|청계천|산(?:\s|의)|섬|호수|둘레길|거리|마을|시장|타워|센터|공연장|"
                        r"미술관|박물관|도서관|체육|경기장|수목원|식물원|동물원|캠핑|야영")
# 표에 넣는 조례: 이름 → (곳 낱말, rivals, 증거로 옮길 조항 · 그 조항에서 찾을 글[ · 구절이 끝나는 글], 까닭)
# 후보(candidates)에서 고르는 기준: 그 조례가 곳을 「따로 정의」하고 그 곳의 이용 · 금지를 직접 정하는데, 그 곳이 6종이 정하는 대상
# (도시공원 조례의 「공원」 = 법 제2조제3호의 도시공원)이 아니다. 고르지 않은 것과 까닭은 SKIP에 적는다.
_SQUARE = ("광장은 도시공원이 아니다(도시공원 조례 제2조 제4호의 공원은 법 제2조제3호의 도시공원). 이 조례가 광장을 따로 정의하고 "
           "사용 · 관리를 직접 정한다. 금연 조례가 광장을 직접 적는 경우는 그 원문에 낱말이 있어 규칙 C가 막지 않는다")
PICK = {
    "서울특별시 한강공원 보전 및 이용에 관한 기본 조례": (
        ["한강공원"], ["도시공원"],
        [("제3조", "\"한강공원\"이란"), ("제17조", "누구든지 한강공원")],
        "제3조가 한강공원을 따로 정의하고 제17조가 그 안의 금지행위를 직접 정한다. 도시공원 조례의 「공원」은 법 제2조제3호의 "
        "도시공원이라(도시공원 조례 제2조 제4호) 한강공원 질문을 도시공원 조례가 받으면 원문에 없는 전제가 된다. 금연 조례는 제5조 "
        "제1항 제11호에 한강공원을 직접 적으므로 rivals가 아니다. 동물보호 · 주차장 · 자전거 조례는 곳을 가리지 않고 정하므로 rivals가 아니다"),
    "서울특별시 광화문광장의 사용 및 관리에 관한 조례": (["광화문광장"], ["도시공원"], [("제2조", "1. \"광화문광장\"이란")], _SQUARE),
    "서울특별시 서울광장의 사용 및 관리에 관한 조례": (["서울광장"], ["도시공원"], [("제1조", "이 조례는")], _SQUARE),
    "서울특별시 세운광장의 사용 및 관리에 관한 조례": (["세운광장"], ["도시공원"], [("제2조", "1. \"세운광장\"이란")], _SQUARE),
    "서울특별시 마곡광장의 사용 및 관리에 관한 조례": (["마곡광장"], ["도시공원"], [("제2조", "1. \"마곡광장\"이란")], _SQUARE),
    "서울특별시 문정 스포츠가든 광장의 사용 및 관리에 관한 조례": (
        ["문정 스포츠가든 광장"], ["도시공원"], [("제2조", "1. \"문정 스포츠가든 광장\"이란")], _SQUARE),
    "서울특별시 서울역광장의 건전한 이용 환경 조성을 위한 지원 조례": (["서울역광장"], ["도시공원"], [("제2조", "이 조례에서")], _SQUARE),
    "서울특별시 청계천 이용ㆍ관리에 관한 조례": (
        ["청계천", "청계광장"], ["도시공원"], [("제1조", "이 조례는"), ("제2조", "이 조례에서", "청계광장")],
        "청계천은 하천이고 청계광장은 이 조례 제2조의 이용시설이다. 둘 다 도시공원이 아니고, 이 조례가 이용 · 사용허가를 직접 정한다"),
    "서울특별시 노들섬 복합문화공간 운영 및 관리 조례": (
        ["노들섬"], ["도시공원"], [("제2조", "1.\"노들섬\"이란"), ("제7조", "시장은 다음")],
        "제2조가 노들섬을 따로 정의하고 제7조가 이용 금지를 직접 정한다. 도시공원 조례에 노들섬은 없다"),
}
SKIP = {
    "서울특별시 남산공원 보전 및 이용에 관한 기본 조례": "제3조 제1호의 남산공원에 남산 근린공원이 든다. 근린공원은 도시공원이라 도시공원 조례도 그대로 "
                                         "적용될 수 있고, 제20조 금지행위도 같은 법 제49조로 넘긴다 → 막으면 답할 수 있는 질문을 막을 수 있다",
    "서울특별시 동대문디자인플라자(DDP) 및 동대문역사문화공원 관리ㆍ운영 조례": "공원부는 도시공원으로 볼 수 있고, 이 조례는 대관 · 운영만 정한다",
    "서울특별시 한강 수상레저활동의 안전 및 활성화에 관한 조례": "곳이 아니라 활동(수상레저)을 정한다. 곳 낱말이 「한강」뿐이라 금연 조례의 한강공원 문항까지 걸린다",
    "서울특별시 도시공원 조례": "6종이다",
    "서울특별시 도시공원의 어린이 놀이환경 조성에 관한 조례": "도시공원 안의 일이라 도시공원 조례와 겹친다(곳을 따로 정의하지 않는다)",
    "서울특별시 도시숲 등의 조성 및 관리에 관한 조례": "곳 이름이 아니라 종류(도시숲)다",
    "서울특별시 한강공원 순환관람차 운영 조례": "시설 하나의 운영. 곳은 한강공원 줄이 이미 덮는다",
}


def _law_api():
    """법령 API는 eval/fetch_source.py 한 곳에서만 부른다(--build 때만 읽어 온다. 채점 중 엔진은 이 파일을 쓰지 않는다)."""
    sys.path.insert(0, str(PATH.parents[2] / "eval"))
    import fetch_source
    return fetch_source


def seoul_ordinances(api):
    """서울특별시 본청 조례 목록: [{name, mst, effective_date}]."""
    return [{"name": it["자치법규명"], "mst": str(it["자치법규일련번호"]), "effective_date": it["시행일자"]}
            for it in api.search_ordinances(SEOUL, "30001") if it.get("지자체기관명", "서울특별시") == "서울특별시"]


def _articles(api, mst):
    law = api.fetch(mst)
    arts = {}
    for item in api.as_list(law["조문"]["조"]):
        if item.get("조문여부") == "Y":
            a = api.parse_article(item, "")
            arts[a["label"]] = re.sub(r"\s+", " ", item["조내용"]).strip()
    return law["자치법규기본정보"], arts


def _sentence(text, start, end=None):
    """조항 글에서 start로 시작하는 문장 하나(다음 「다.」까지). end를 주면 그 글이 끝나는 곳까지."""
    i = text.index(start)
    if end:
        return text[i:text.index(end, i) + len(end)]
    j = text.find("다.", i)
    return text[i:j + 2 if j >= 0 else len(text)]


def build():
    api = _law_api()
    names = seoul_ordinances(api)
    by_name = {o["name"]: o for o in names}
    rows = []
    for name, (places, rivals, cites, why) in PICK.items():
        o = by_name.get(name)
        if not o:
            sys.exit(f"서울특별시 조례 목록에 없음: {name}")
        info, arts = _articles(api, o["mst"])
        body = " ".join(arts.values())
        missing = [p for p in places if p not in body]
        if missing:
            sys.exit(f"{name}: 원문에 없는 곳 낱말 {missing}")
        rows.append({"law": name, "mst": o["mst"], "effective_date": info["시행일자"],
                     "source_url": f"https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq={o['mst']}",
                     "places": places, "rivals": rivals,
                     "evidence": [{"label": c[0], "quote": _sentence(arts[c[0]], *c[1:])} for c in cites], "why": why})
    cands = sorted({o["name"] for o in names if PLACE_NAME.search(o["name"].removeprefix("서울특별시 "))})
    return {"source": "법제처 국가법령정보 OPEN API(서울특별시 본청 조례)", "ordinances_seen": len(names),
            "places": rows, "skipped": SKIP, "candidates": cands}


def load():
    return json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {"places": []}


def check():
    """키 없이: 칸이 다 있고, rivals가 6종 열쇠이고, 곳 낱말이 증거 구절에 글자 그대로 있는지. 문제 목록을 돌려준다."""
    from .ontology import LAW_KEYS
    bad = []
    for r in load()["places"]:
        for k in ("law", "mst", "places", "rivals", "evidence", "why"):
            if not r.get(k):
                bad.append(f"{r.get('law')}: 빈 칸 {k}")
        bad += [f"{r['law']}: 6종 열쇠가 아님 {k}" for k in r.get("rivals", []) if k not in LAW_KEYS]
        quotes = " ".join(e["quote"] for e in r.get("evidence", []))
        bad += [f"{r['law']}: 증거 구절에 없는 곳 낱말 {p}" for p in r.get("places", []) if p not in quotes]
    return bad


if __name__ == "__main__":
    if sys.argv[1:] == ["--build"]:
        o = build()
        PATH.write_text(json.dumps(o, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"places.json: 서울특별시 조례 {o['ordinances_seen']}개 훑음 · 곳 이름 후보 {len(o['candidates'])}개 · 표 {len(o['places'])}줄")
    elif sys.argv[1:] == ["--check"]:
        bad = check()
        print("✅ 곳 표 칸 · 증거 구절 이상 없음" if not bad else "✗ " + " / ".join(bad))
        sys.exit(1 if bad else 0)
    else:
        print("쓰는 법: LAW_OC=<열쇠> python -m engine.flow2.places --build | python -m engine.flow2.places --check")
