"""flow2 온톨로지에 더하는 표: 조항끼리의 짝(ontology_links.json). 조례 원문에서 코드로만 만든다(PM 실험 「온톨로지로 조항 고르기」, 11-11).

ontology.py 머리말이 「다음 판(o2)」으로 적어 둔 것 가운데 첫째다. 이번 주기에 ontology.py · ontology.json을 고치는 실험(#82)과
부딪치지 않게 파일을 따로 뒀다. 배분일에 ontology.json의 한 칸으로 합치면 된다.

짝의 근거는 원문의 글투뿐이다(평가 문항은 출처로 쓰지 않는다).
- 같은 조례의 다른 조 · 항 · 별표를 번호로 가리키는 말: 「제6조제1항 본문에도 불구하고」(예외) · 「제5조제4항을 위반하여」(위반) ·
  「제16조를 준용한다」(준용) · 「별표 1과 같다」(별표 내용) · 「제1항에 따른」(따름) · 그 밖에 번호만 든 말(언급)
- 별표 제목의 「(제6조제1항 관련)」(별표 관련)
다른 법령의 조항은 뺀다: 번호 바로 앞이 「법 · 영 · 시행령 · 규칙 · 조례 · 」 · (이하 "영"이라 한다)」이면 다른 법령이고,
「및 · 또는 · , · 부터」로 이어진 번호도 앞 번호를 따른다(예: 「「장애인복지법」 제32조, 같은 법 시행규칙 제26조 및 제27조」).
「제10조에 따른」처럼 조 전체를 가리키면 어느 항인지 알 수 없어 whole 표시를 하고, 쓰는 쪽(cite.py)은 그 짝을 따라가지 않는다.
모든 구절은 원문 조각(별표 관련은 별표 제목)에서 잘라 온 글자 그대로다. --check가 다시 만들어 견주고 구절이 원문에 있는지도 본다.

만들기: python -m engine.flow2.links --build   (키 없이 1초)
점검:  python -m engine.flow2.links --check
"""
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from . import ontology

PATH = Path(__file__).resolve().parent / "ontology_links.json"
VERSION = "l1"
KIND_NAMES = ["예외", "위반", "준용", "별표 내용", "별표 관련", "따름", "언급"]
REF = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?(?:\s*제\s*\d+\s*호(?:의\d+)?)?"
                 r"|제\s*(\d+)\s*항(?:\s*제\s*\d+\s*호(?:의\d+)?)?|(별표)\s*(\d*)")
TAGS = re.compile(r"<[^<>]{0,400}>|\[[^\[\]]{0,300}\]")      # 개정 꼬리표 · 조각 첫 줄 「[조례 이름 제N조(제목)]」 · 부칙 메모
OUTER = re.compile(r"(?:법|법률|영|시행령|시행규칙|규칙|조례|」|같은\s*조|한다\))\s*$")   # 바로 앞이 이러면 다른 법령 · 조례의 조항
JOIN = re.compile(r"^\s*(?:,|ㆍ|·|및|또는|부터|내지|와|과|\s)*\s*(?:같은\s*조\s*)?$")     # 앞 번호에 이어 붙는 말
KINDS = [("예외", re.compile(r"^\s*(?:본문|단서|의\s*규정)?에도\s*불구하고")),
         ("위반", re.compile(r"^[^.,\n]{0,16}위반")),
         ("준용", re.compile(r"^\s*(?:의\s*규정)?(?:을|를)\s*준용")),
         ("별표 내용", re.compile(r"^\s*(?:와|과)\s*같다|^\s*에\s*(?:따른다|의한다)")),
         ("따름", re.compile(r"^\s*(?:각\s*호|본문|단서|전단|후단)?\s*(?:의\s*규정)?(?:에\s*(?:따른|따라|따르|의한|의하여|의거|해당하는)|에서\s*정한|의\s)"))]


def short(label, law):
    return label.removeprefix(law).strip()


def key_of(s):
    """조각 이름(조례 이름 뺀 것) → ("조", 조, 의, 항) · ("별표", 번호). 그 밖은 None."""
    m = re.fullmatch(r"제(\d+)조(?:의(\d+))?(?: 제(\d+)항)?", s)
    if m:
        return ("조", m.group(1), m.group(2) or "", m.group(3) or "")
    m = re.fullmatch(r"별표 ?(\d*)", s)
    return ("별표", m.group(1)) if m else None


def refs(text, me):
    """글에서 같은 조례 안의 조 · 항 · 별표를 가리키는 말 → [(키, 갈래, 구절)]. me: 이 조각의 키(「제1항」만 적힌 말은 같은 조다)."""
    body = TAGS.sub(lambda m: " " * len(m.group(0)), text)
    ms = list(REF.finditer(body))
    out, run, prev_end, prev_outer, prev_art = [], [], 0, False, None
    for i, m in enumerate(ms):
        if me[0] == "조" and m.start() < 3 and m.group(1):       # 조 단위 조각의 첫머리 「제11조(제목)」은 자기 이름
            prev_end, prev_outer, prev_art = m.end(), False, None
            continue
        between = body[prev_end:m.start()]
        chained = i > 0 and bool(run or prev_outer) and JOIN.match(between) is not None
        outer = prev_outer if chained else OUTER.search(body[max(0, m.start() - 12):m.start()]) is not None
        if not chained:
            run = []
        if m.group(1):
            key, prev_art = ("조", m.group(1), m.group(2) or "", m.group(3) or ""), (m.group(1), m.group(2) or "")
        elif m.group(4):
            a = prev_art if chained and prev_art else ((me[1], me[2]) if me[0] == "조" else None)
            key = ("조", a[0], a[1], m.group(4)) if a else None
        else:
            key = ("별표", m.group(6))
        if not outer and key:
            if run and "부터" in between and key[0] == "조" and run[-1][0][:3] == key[:3] and run[-1][0][3] and key[3]:
                for n in range(int(run[-1][0][3]) + 1, int(key[3])):      # 「제1항부터 제3항까지」의 사이 항
                    run.append(((*key[:3], str(n)), m.start(), m.end()))
            run.append((key, m.start(), m.end()))
        nxt = ms[i + 1] if i + 1 < len(ms) else None
        last = not (nxt and JOIN.match(body[m.end():nxt.start()]))
        if last and run:       # 이어진 번호 묶음(「제2항 및 제3항에 따라」)은 마지막 번호 뒤의 말로 갈래를 정한다
            kind = next((k for k, rx in KINDS if rx.search(body[m.end():m.end() + 24])), "언급")
            out += [(k, kind, text[max(0, a - 12):min(len(text), b + 14)].strip()) for k, a, b in run]
            run = []
        prev_end, prev_outer = m.end(), outer
    return out


def build():
    from .. import retrieve
    titles = ontology._annex_titles()
    laws, cov = [], {"chunks": 0, "links": 0, "unresolved": []}
    chunks = list({c["label"]: c for c in retrieve.load("paragraph")[0]}.values())     # 별표는 이름 하나로 모은다
    for key, name in ontology.LAW_KEYS.items():
        mine = [c for c in chunks if c["law"] == name]
        idx = {key_of(short(c["label"], name)): short(c["label"], name) for c in mine}
        idx.pop(None, None)

        def resolve(k):
            if k in idx:
                return [idx[k]], False
            if k[0] == "별표" or (k[0] == "조" and k[3] and ("조", k[1], k[2], "") in idx):
                hit = idx.get(("조", k[1], k[2], "")) if k[0] == "조" else None    # 항 없이 한 덩어리인 조를 「제○조제1항」으로 가리킴
                return ([hit] if hit else []), False
            return [s for kk, s in idx.items() if kk[0] == "조" and kk[1:3] == k[1:3]], True   # 조 전체 → 그 조의 모든 항

        links = []
        for c in mine:
            me, s = key_of(short(c["label"], name)), short(c["label"], name)
            if me is None:
                continue
            cov["chunks"] += 1
            if me[0] == "별표":       # 별표 본문 안의 번호는 표 내용이라 짝으로 보지 않는다. 제목의 「(…관련)」만 본다
                title = titles.get((name, s), "")
                tail = title[title.rfind("("):] if "관련" in title and "(" in title else ""
                for m in re.finditer(r"제(\d+)(?:조)?(?:의(\d+))?\s*(?:제(\d+)항)?", tail):
                    to, whole = resolve(("조", m.group(1), m.group(2) or "", m.group(3) or ""))
                    if to:
                        links.append({"from": s, "to": to, "kind": "별표 관련", "quote": title, "whole": whole and len(to) > 1})
                continue
            for k, kind, quote in refs(c["text"], me):
                to, whole = resolve(k)
                to = [t for t in to if t != s]
                if k[0] == "별표" and kind in ("언급", "따름"):
                    kind = "별표 내용"
                if to:
                    links.append({"from": s, "to": to, "kind": kind, "quote": quote, "whole": whole and len(to) > 1})
                elif not resolve(k)[0]:
                    cov["unresolved"].append({"law": key, "from": s, "quote": quote})
        cov["links"] += len(links)
        laws.append({"key": key, "name": name, "links": links})
    cov["by_kind"] = {k: sum(e["kind"] == k for law in laws for e in law["links"]) for k in KIND_NAMES}
    return {"version": VERSION, "built_from": {"chunks": retrieve.fingerprint("paragraph")},
            "rule": "같은 조례 안의 조 · 항 · 별표를 번호로 가리키는 말만 짝으로 본다. 번호 바로 앞이 법 · 영 · 규칙 · 조례 · 」 · 한다)이면 "
                    "다른 법령의 조항으로 보고 뺀다. whole이 참이면 조 전체를 가리킨 것이다. 평가 문항은 출처로 쓰지 않는다.",
            "laws": laws, "coverage": cov}


@lru_cache(maxsize=None)
def load():
    return json.loads(PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def targets():
    """조각 이름(정식, 조례 이름 포함) → [(가리키는 조각 이름, 갈래, 구절)]. 조 전체를 가리키는 짝(whole)은 뺀다."""
    out = {}
    for law in load()["laws"]:
        for e in law["links"]:
            if not e["whole"]:
                out.setdefault(f"{law['name']} {e['from']}", []).extend(
                    (f"{law['name']} {t}", e["kind"], e["quote"]) for t in e["to"])
    return out


def check():
    """파일이 원문에서 다시 만든 것과 같은지, 모든 구절이 원문 조각(별표 관련은 별표 제목)에 글자 그대로 있는지."""
    from .. import retrieve
    now, built = json.loads(PATH.read_text(encoding="utf-8")), build()
    text = {}
    for c in retrieve.load("paragraph")[0]:
        text[c["label"]] = text.get(c["label"], "") + "\n" + c["text"]
    titles = ontology._annex_titles()
    bad = [(law["key"], e["from"]) for law in now["laws"] for e in law["links"]
           if e["quote"] not in (titles.get((law["name"], e["from"]), "") if e["kind"] == "별표 관련"
                                 else text.get(f"{law['name']} {e['from']}", ""))]
    return now == built, bad


def selftest():
    """원문에서 뽑혀야 하는 짝과 뽑히면 안 되는 짝(다른 법령의 조항). 문장은 조례 원문 글투로 새로 썼다."""
    me = ("조", "7", "", "1")
    got = refs("① 시장은 제6조제1항 본문에도 불구하고 다음 각 호에 해당할 경우에는 주차요금을 감면할 수 있다.", me)
    assert [(k, kind) for k, kind, _ in got] == [(("조", "6", "", "1"), "예외")], got
    got = refs("① 시장은 제5조제4항을 위반하여 금연구역에서 흡연을 한 사람은 10만원의 과태료를 부과ㆍ징수한다.", ("조", "10", "", "1"))
    assert [(k, kind) for k, kind, _ in got] == [(("조", "5", "", "4"), "위반")], got
    got = refs("② 제1항에 따른 감면 대상자는 다음 각 호의 기준에 따른다. 6. 제13조제6항에 따른 인증을 받은 사람", ("조", "12", "3", "2"))
    assert [k for k, _, _ in got] == [("조", "12", "3", "1"), ("조", "13", "", "6")] and {kind for _, kind, _ in got} == {"따름"}, got
    got = refs("① 공영주차장의 주차요금은 별표 1과 같다. 다만, 시장이 따로 정하는 경우에는 그러하지 아니하다.", ("조", "6", "", "1"))
    assert [(k, kind) for k, kind, _ in got] == [(("별표", "1"), "별표 내용")], got
    got = refs("④ 시장은 제1항부터 제3항까지를 시행할 때 특별히 청년 1인가구를 위한 대책을 마련하여야 한다.", ("조", "13", "", "4"))
    assert [k[3] for k, _, _ in got] == ["1", "2", "3"], got
    # 다른 법령의 조항은 짝이 아니다: 법 · 영 · 「」 · (이하 "영"이라 한다) 뒤, 그리고 거기에 이어진 번호
    for s in ("② 법 제9조제3항에 따른 노상주차장의 가산금은 다음 각 호의 경우에 부과한다.",
              "가. 「장애인복지법」 제32조, 같은 법 시행규칙 제26조 및 제27조에 따른 장애인자동차표지를 부착한 경우",
              '① 「자전거 이용 활성화에 관한 법률 시행령」(이하 "영"이라 한다) 제7조의 규정에 의한 자전거주차장',
              "2. 법 제10조제1항부터 제4항까지의 규정을 위반한 경우",
              "[조례 제7634호(2020. 7. 16) 부칙 제2조의 규정에 의하여 이 조 제1항제12호는 2021년 6월 30일까지 유효함]"):
        assert refs(s, me) == [], (s, refs(s, me))
    same, bad = check()
    assert same and not bad, (same, bad[:3])
    t = targets()
    park, smoke, pet = (ontology.LAW_KEYS[k] for k in ("주차장", "금연", "동물보호"))
    assert (f"{park} 제6조 제1항", "예외") in [(a, k) for a, k, _ in t[f"{park} 제7조 제1항"]]
    assert (f"{park} 별표 1", "별표 내용") in [(a, k) for a, k, _ in t[f"{park} 제6조 제1항"]]
    assert (f"{smoke} 제5조 제4항", "위반") in [(a, k) for a, k, _ in t[f"{smoke} 제10조 제1항"]]
    assert f"{pet} 제2조" not in t          # 맹견 정의의 「영 제3조」 · 「시행규칙 제3조」는 다른 법령이다
    assert all(not a.endswith(" 제10조 제1항") for a, _, _ in t.get(f"{pet} 제16조 제1항", []))   # 「제10조에 따라」는 조 전체(whole)라 뺀다
    print("flow2 조항 짝 스스로 시험: 통과")


if __name__ == "__main__":
    if sys.argv[1:] == ["--build"]:
        o = build()
        PATH.write_text(json.dumps(o, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"ontology_links.json {VERSION}: 짝 {o['coverage']['links']}개 {o['coverage']['by_kind']} · 못 푼 번호 {len(o['coverage']['unresolved'])}개")
    elif sys.argv[1:] == ["--check"]:
        same, bad = check()
        print(("✅ 원문에서 다시 만든 것과 같다" if same else "✗ 원문과 다르다: --build로 다시 만든다") +
              (f" · 원문에 없는 구절 {len(bad)}개 {bad[:3]}" if bad else " · 구절 모두 원문에 있음"))
        sys.exit(0 if same and not bad else 1)
    elif sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        print("쓰는 법: python -m engine.flow2.links --build | --check | --selftest")
