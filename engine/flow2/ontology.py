"""flow2 온톨로지 첫 판(o1): ③ 조례 확정이 쓰는 지도를 조례 원문에서 코드로 만든 JSON 한 파일(ontology.json).

담는 것(6종 모든 조 · 항 · 별표를 같은 기준으로): 조례 이름 · 별칭 규칙, 조마다 제목(= 다루는 대상 · 행위)과 그 조의 항,
별표 제목과 관련 조, 6종이 「」로 드는 법령 · 조례, 자치구 · 구청장이 나오는 문장(역할 갈래), 원문의 서울시 시설 이름, 덮은 비율.
조례 원문에 없는 것은 자치구 25곳 하나뿐이고 출처를 적는다. 평가셋 질문 글은 출처로 쓰지 않는다(동규 11-10).
모든 구절은 원문 조각에서 잘라 온 것이라 글자 그대로다. --check가 다시 만들어 견주고, 구절이 원문에 있는지도 본다.

다음 판(o2, 동규 11-10): 조항끼리의 관계(「다만」 예외 · 준용 · 위임 · 용어 정의, ④ 결합형용), 별표 숫자를 대상 · 조건 · 금액 칸으로,
시민 말 ↔ 조례 말 별칭(② · ⑥용, 원문에 없으면 공개 공식 출처를 적는다). 실패로 고치는 고리는 failures.py와 이 파일의 changes 칸.

만들기: python -m engine.flow2.ontology --build   (키 없이 1초)
점검:  python -m engine.flow2.ontology --check
"""
import hashlib
import json
import re
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parent / "ontology.json"
VERSION = "o1"
LAW_KEYS = {   # 분석 칸 law_guess 값(prompts.LAW_KEYS) → 정식 이름(색인 조각 law 칸과 같은 글자)
    "주차장": "서울특별시 주차장 설치 및 관리 조례",
    "동물보호": "서울특별시 동물보호 조례",
    "자전거": "서울특별시 자전거이용 활성화에 관한 조례",
    "도시공원": "서울특별시 도시공원 조례",
    "청년": "서울특별시 청년 기본 조례",
    "금연": "서울특별시 금연환경 조성 및 간접흡연 피해방지조례",
}
DISTRICTS = {
    "names": ("종로 중 용산 성동 광진 동대문 중랑 성북 강북 도봉 노원 은평 서대문 마포 양천 강서 구로 금천 "
              "영등포 동작 관악 서초 강남 송파 강동").split(),
    "source": "서울특별시 자치구 25곳(공개 행정구역 정보). 조례 원문 밖의 사실이라 출처를 적는다. #25 engine/gate.py와 같은 목록",
}
FAILURE_LOOP = {
    "steps": ["판단 기록에서 실패 모으기(failures.py, trace-hub의 eval/failures.py가 생기면 그 출력)",
              "원인 나누기: 온톨로지 빈칸 · 프롬프트 · 검색 · 정답 애매",
              "온톨로지 빈칸만 고치기: 근거는 조례 원문 글자, 같은 조의 다른 항 · 같은 꼴의 다른 조례까지 함께 보고 규칙으로",
              "다시 재기: dev + 극한 세트 + 원문에서 새로 쓴 바꿔 말한 질문. dev만 오르면 「dev만 오름」 경고",
              "고친 문항은 회귀 목록에 넣어 다음 판에서도 맞는지 본다. holdout은 이정표에서 PM만"],
    "causes": ["온톨로지 빈칸", "프롬프트", "검색", "정답 애매"],
    "change_fields": ["date", "failures", "cause", "evidence_label", "evidence_quote", "neighbors_checked", "change",
                      "checked_on"],
}
_ARTICLE = re.compile(r"(제\d+조(?:의\d+)?)")
_TITLE = re.compile(r"제\d+조(?:의\d+)?\(([^()]{1,60})\)")
_SENT = re.compile(r"(?<=다\.)\s+|\n+")


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def _role(s):
    if "위임" in s or "위탁" in s:
        return "위임 · 위탁"
    if re.search(r"협의|협력|협조", s):
        return "협의 · 협력"
    if re.search(r"(?:자치구청장|구청장)(?:은|이|과|에게|또는)", s) or re.search(r"(?:시장 또는|시장과) 구청장", s):
        return "구청장이 하는 일"
    return "자치구 언급"


def _annex_titles():
    """원문 메타(engine/data/ordinances.json, 킷이 법제처에서 받은 것)의 별표 제목: {(조례 이름, 별표 라벨): 제목}."""
    import ast
    from .. import config
    out = {}
    for law in json.loads((config.DATA / "ordinances.json").read_text(encoding="utf-8")):
        axs = law["annexes"] if isinstance(law["annexes"], list) else ast.literal_eval(law["annexes"])
        for a in axs:
            out[(law["name"], a["label"])] = re.sub(r"\s+", " ", a["title"]).strip()
    return out


def build():
    from .. import retrieve
    from . import annex
    chunks = retrieve.load("paragraph")[0]
    titles = _annex_titles()
    laws, cov = [], {"articles": 0, "articles_titled": 0, "paragraph_chunks": 0, "paragraph_mapped": 0,
                     "annexes": 0, "annexes_titled": 0}
    for key, name in LAW_KEYS.items():
        mine = [c for c in chunks if c["law"] == name]
        arts, annexes, cites, roles, places = {}, {}, {}, [], {}
        for c in mine:
            label = c["label"].removeprefix(name).strip()
            if label.startswith("별표"):
                title = titles.get((name, label), "")
                annexes.setdefault(label, {"label": label, "title": title,
                                           "related": sorted(set(re.findall(r"제\d+(?:조(?:의\d+)?)?(?:\s*제\d+항)?", title)))})
            else:
                cov["paragraph_chunks"] += 1
                art = _ARTICLE.match(label)
                if art:
                    cov["paragraph_mapped"] += 1
                    a = arts.setdefault(art.group(1), {"label": art.group(1), "title": "", "paragraphs": []})
                    t = _TITLE.search(c["text"])
                    if t and not a["title"]:
                        a["title"] = t.group(1)
                    a["paragraphs"].append(label)
            for m in re.findall(r"「([^」]{2,60})」", c["text"]):
                m = re.sub(r"\s+", " ", m).strip()
                if not m.startswith("별표"):
                    cites.setdefault(m, [])
                    if label not in cites[m]:
                        cites[m].append(label)
            for s in _SENT.split(c["text"]):
                if re.search(r"구청장|자치구", s):
                    roles.append({"label": label, "role": _role(s), "quote": s.strip()[:300]})
            for p in re.findall(r"서울[가-힣]{0,6}?(?:대공원|식물원|청년센터)", re.sub(r"\s+", "", c["text"])):
                places.setdefault(p, [])
                if label not in places[p]:
                    places[p].append(label)
        cov["articles"] += len(arts)
        cov["articles_titled"] += sum(bool(a["title"]) for a in arts.values())
        cov["annexes"] += len(annexes)
        cov["annexes_titled"] += sum(bool(a["title"]) for a in annexes.values())
        seq = re.search(r"ordinSeq=(\d+)", mine[0]["source_url"]).group(1)
        laws.append({
            "key": key, "name": name, "mst": seq, "effective_date": mine[0]["effective_date"],
            "source_url": mine[0]["source_url"],
            "aliases": [name.removeprefix("서울특별시 ")],
            "articles": list(arts.values()), "annexes": list(annexes.values()),
            "cites": [{"name": n, "labels": ls} for n, ls in cites.items()],
            "district_roles": roles, "places": [{"name": p, "labels": ls} for p, ls in sorted(places.items())],
        })
    pct = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
    return {
        "version": VERSION,
        "built_from": {"chunks": retrieve.fingerprint("paragraph"),
                       "annex": _sha(sorted(p.name for p in annex.DIR.glob("*.html")))},
        "alias_rule": "질문이 든 조례 이름에서 앞의 서울특별시 · 서울시 · 서울과 뒤의 「조례」(와 그 뒤)를 뗀 글자가 정식 이름의 한 부분이면 "
                      "같은 조례다(예: 「공원 조례」 → 도시공원 조례). 6종 이름에 없는 글자가 끼면 다른 조례다(lawmap.name_kind).",
        "laws": laws,
        "districts": DISTRICTS,
        "coverage": {**cov, "articles_titled_pct": pct(cov["articles_titled"], cov["articles"]),
                     "paragraph_mapped_pct": pct(cov["paragraph_mapped"], cov["paragraph_chunks"]),
                     "annexes_titled_pct": pct(cov["annexes_titled"], cov["annexes"])},
        "failure_loop": FAILURE_LOOP,
        "changes": [],
    }


def load():
    return json.loads(PATH.read_text(encoding="utf-8"))


def check():
    """파일이 원문에서 다시 만든 것과 같은지(changes 칸 빼고), 모든 구절이 원문 조각에 글자 그대로 있는지."""
    from .. import retrieve
    now, built = load(), build()
    same = {k: v for k, v in now.items() if k != "changes"} == {k: v for k, v in built.items() if k != "changes"}
    text = {c["label"]: c["text"] for c in retrieve.load("paragraph")[0]}
    bad = [(law["name"], r["label"]) for law in now["laws"] for r in law["district_roles"]
           if r["quote"] not in text.get(f"{law['name']} {r['label']}", "")]
    return same, bad


if __name__ == "__main__":
    if sys.argv[1:] == ["--build"]:
        o = build()
        PATH.write_text(json.dumps(o, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"ontology.json {VERSION}: 조례 {len(o['laws'])} · 덮은 비율 {o['coverage']}")
    elif sys.argv[1:] == ["--check"]:
        same, bad = check()
        print(("✅ 원문에서 다시 만든 것과 같다" if same else "✗ 원문과 다르다: --build로 다시 만든다") +
              (f" · 원문에 없는 구절 {len(bad)}개 {bad[:3]}" if bad else " · 구절 모두 원문에 있음"))
        sys.exit(0 if same and not bad else 1)
    else:
        print("쓰는 법: python -m engine.flow2.ontology --build | --check")
