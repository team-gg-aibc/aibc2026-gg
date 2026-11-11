"""평가셋의 기준 원문(서울특별시 조례 6종, 2026-10-01 기준)을 법제처 국가법령정보 OPEN API로 받아 조 · 항 · 호 · 별표로 나눈다.

실행: LAW_OC=<인증키> python3 eval/fetch_source.py
결과: eval/source/<조례>.json (점검 스크립트가 읽는 원본) + eval/source/<조례>.md (검수자가 읽는 사본)
판은 자치법규일련번호(MST)로 고정한다. 받은 판의 시행일이 기준과 다르면 멈춘다.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

# 키: (정식 이름, 자치법규일련번호, 기준 시행일). 도시공원 · 청년은 10/1 이전 개정본이 기준 시점의 최신본이다.
ORDINANCES = {
    "parking": ("서울특별시 주차장 설치 및 관리 조례", "2171833", "20261001"),
    "park": ("서울특별시 도시공원 조례", "2147709", "20260713"),
    "smoking": ("서울특별시 금연환경 조성 및 간접흡연 피해방지조례", "2171803", "20261001"),
    "animal": ("서울특별시 동물보호 조례", "2171829", "20261001"),
    "bicycle": ("서울특별시 자전거이용 활성화에 관한 조례", "2171767", "20261001"),
    "youth": ("서울특별시 청년 기본 조례", "2054497", "20250714"),
}
OUT = Path(__file__).parent / "source"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def law_api(path: str, **params) -> dict:
    """법제처 국가법령정보 OPEN API를 부르는 단 한 곳(AGENTS.md 5절). 키 확인 · 요청 · 응답에서 키 지우기를 여기서만 한다."""
    oc = os.environ.get("LAW_OC")
    if not oc:
        sys.exit("LAW_OC 환경 변수가 없습니다 (.env.example 참고)")
    query = urllib.parse.urlencode({"OC": oc, "type": "JSON", **params})
    raw = urllib.request.urlopen(f"https://www.law.go.kr/DRF/{path}?{query}", timeout=60).read()
    # 응답 안의 상세 링크에 인증키가 그대로 들어 있어서, 저장하기 전에 지운다.
    return json.loads(raw.decode("utf-8").replace(oc, ""))


def fetch(mst: str) -> dict:
    return law_api("lawService.do", target="ordin", MST=mst)["LawService"]


def search_ordinances(org: str, knd: str) -> list[dict]:
    """지자체 조례 목록(lawSearch.do)을 끝 쪽까지 넘기며 받는다. org: 지자체 기관 코드, knd: 자치법규 종류(30001 조례)."""
    out, page = [], 1
    while items := as_list(law_api("lawSearch.do", target="ordin", org=org, knd=knd, display=100, page=page)["OrdinSearch"].get("law")):
        out += items
        page += 1
    return out


def as_list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def split_numbered(text: str, nexts, state) -> tuple[list[tuple[str, str]], int]:
    """순서대로 나오는 다음 표시(nexts가 주는 후보)만 경계로 본다. <개정 2005. 1. 13.> · [본조신설 …] 괄호 안의 날짜는 건너뛴다."""
    notes = [m.span() for m in re.finditer(r"<[^<>]*>|\[[^\[\]]*\]", text)]
    cuts, pos = [], 0
    while True:
        best = None
        for label, new_state, rx in nexts(state):
            at = pos
            while (m := rx.search(text, at)) and any(s <= m.start() < e for s, e in notes):
                at = m.end()
            if m and (best is None or m.start() < best[2].start()):
                best = (label, new_state, m)
        if not best:
            break
        label, state, m = best
        cuts.append((label, m.start(), m.end()))
        pos = m.end()
    return [(no, text[end:cuts[i + 1][1] if i + 1 < len(cuts) else len(text)].strip()) for i, (no, _, end) in enumerate(cuts)], (cuts[0][1] if cuts else len(text))


def next_item(state: tuple[int, int]) -> list:
    """다음 호 후보: 「n+1.」 또는 「n의m+1.」(예: 1. → 1의2. → 2.)."""
    main, sub = state
    found = [(str(main + 1), (main + 1, 1), re.compile(rf"(?<!\d)(?<!\d\.)(?<!의){main + 1}\.(?!\d)"))]
    if main:
        found.append((f"{main}의{sub + 1}", (main, sub + 1), re.compile(rf"(?<!\d)(?<!\d\.){main}의{sub + 1}\.(?!\d)")))
    return found


def items_of(text: str) -> tuple[str, list[dict]]:
    found, head = split_numbered(text, next_item, (0, 1))
    if len(found) < 2:  # 「1.」 하나만 있으면 호가 아니라 본문 속 숫자로 본다
        return text.strip(), []
    return text[:head].strip(), [{"no": no, "text": t} for no, t in found]


def parse_article(item: dict, name: str) -> dict:
    num = item["조문번호"][0] if isinstance(item["조문번호"], list) else item["조문번호"]
    main, sub = int(num[:4]), int(num[4:])
    label = f"제{main}조" + (f"의{sub}" if sub else "")
    text = item["조내용"].strip()
    heading = f"{label}({item.get('조제목', '')})"
    body = text[len(heading):].strip() if text.startswith(heading) else re.sub(rf"^{label}\s*", "", text)
    article = {"label": label, "title": item.get("조제목", ""), "text": text, "deleted": bool(re.match(r"^삭제", body))}
    paras, head = split_numbered(body, lambda n: [(n + 1, n + 1, re.compile(CIRCLED[n]))] if n < len(CIRCLED) else [], 0)
    if paras:
        if body[:head].strip():
            article["lead"] = body[:head].strip()
        article["paragraphs"] = []
        for no, ptext in paras:
            lead, items = items_of(ptext)
            article["paragraphs"].append({"label": f"{label} 제{no}항", "text": lead, "items": items, "cite": f"{name} {label} 제{no}항"})
    else:
        article["lead"], article["items"] = items_of(body)
    article["cite"] = f"{name} {label}"
    return article


def annex_label(a: dict) -> str:
    no, branch = int(a["별표번호"]), int(a.get("별표가지번호") or 0)
    return a["별표구분"] + (f" {no}" if no else "") + (f"의{branch}" if branch else "")


def build(key: str) -> dict:
    name, mst, want = ORDINANCES[key]
    law = fetch(mst)
    info = law["자치법규기본정보"]
    if info["자치법규명"] != name or info["시행일자"] != want or info["지자체기관명"] != "서울특별시":
        sys.exit(f"{key}: 받은 판이 기준과 다릅니다 ({info['자치법규명']}, {info['시행일자']}, {info['지자체기관명']})")
    articles, chapter = [], ""
    for item in as_list(law["조문"]["조"]):
        if item["조문여부"] != "Y":
            chapter = item["조내용"].strip()
            continue
        article = parse_article(item, name)
        article["chapter"] = chapter
        articles.append(article)
    annexes = []
    for a in as_list(law.get("별표단위")):
        content = a.get("별표내용") or []
        text = "".join(x for part in content for x in as_list(part))
        label = annex_label(a)
        annexes.append({"label": label, "title": a["별표제목"].strip(), "text": text, "cite": f"{name} {label}"})
    fmt = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return {
        "name": name,
        "mst": mst,
        "effective_date": fmt(info["시행일자"]),
        "promulgated": f"{fmt(info['공포일자'])} 제{info['공포번호']}호 {info['제개정정보']}",
        "source_url": f"https://www.law.go.kr/ordinInfoP.do?ordinSeq={mst}",
        "fetched": date.today().isoformat(),
        "articles": articles,
        "annexes": annexes,
    }


def reflow(text: str) -> str:
    """별표는 줄바꿈 없이 이어 붙어 온다. 표(┌…┘) 안은 행 경계에서만, 표 밖은 긴 공백에서 줄을 바꿔 사람이 읽게 한다(.md 사본에만 쓴다)."""
    parts, pos = [], 0
    for m in re.finditer(r"┌.*?┘", text, flags=re.S):
        parts += [re.sub(r" {4,}", "\n", text[pos:m.start()]), "\n" + re.sub(r"(?<=[┐┤┥│┘┨┫])(?=[│├┝└┠┣])", "\n", m.group(0)) + "\n"]
        pos = m.end()
    parts.append(re.sub(r" {4,}", "\n", text[pos:]))
    return re.sub(r"\n\s*\n", "\n", "".join(parts)).strip()


def markdown(src: dict) -> str:
    lines = [f"# {src['name']}", "", f"- 시행일: {src['effective_date']} · 공포: {src['promulgated']}",
             f"- 원문: {src['source_url']}", f"- 받은 날: {src['fetched']} (`eval/fetch_source.py`, 이 파일은 json에서 만든 읽기용 사본)", ""]
    chapter = None
    for a in src["articles"]:
        if a["chapter"] != chapter and a["chapter"]:
            chapter = a["chapter"]
            lines += [f"## {chapter}", ""]
        lines += [f"### {a['label']}({a['title']})" if a["title"] else f"### {a['label']}", ""]
        if a.get("lead"):
            lines += [f"**{a['label']}** {a['lead']}", ""]
        for item in a.get("items", []):
            lines.append(f"- {item['no']}호: {item['text']}")
        for p in a.get("paragraphs", []):
            lines.append(f"- **{p['label']}** {p['text']}")
            lines += [f"  - {item['no']}호: {item['text']}" for item in p["items"]]
        lines.append("")
    for x in src["annexes"]:
        lines += [f"### {x['label']} {x['title']}", "", "```", reflow(x["text"]), "```", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for key in ORDINANCES:
        src = build(key)
        (OUT / f"{key}.json").write_text(json.dumps(src, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (OUT / f"{key}.md").write_text(markdown(src), encoding="utf-8")
        paras = sum(len(a.get("paragraphs", [])) or 1 for a in src["articles"])
        print(f"{key}: 조 {len(src['articles'])} · 항(항 없는 조는 1) {paras} · 별표 {len(src['annexes'])} · 시행 {src['effective_date']}")
