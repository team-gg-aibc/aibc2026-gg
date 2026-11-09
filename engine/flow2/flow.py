"""flow2: 검색 → 질문 분석 → 조례 확정 → 조례 읽고 답 쓰기 → 구절 관문 → 질문 대조 → 출력 (PM 별도 실험, 동규 11-10).

설계 · 이유: 공유 노트 「PM별도실험-설계-11-10」. 설정 `flow`가 "flow2"면 pipeline.answer가 이 STAGES를 돈다. 마감 · 오류 · 판단 기록 ·
출구 검사(#22)는 pipeline의 고리를 그대로 쓰고, 검색은 pipeline.search 그대로다. 팀원 파일(answer · whole · gate · retrieve ·
build_index · verify · contract · upstage)은 고치지 않고 부르기만 한다.

- ③ 조례 확정은 코드만(lawmap.route): 질문이 이름을 든 조례가 6종이 아니거나, 자치구 · 다른 시도가 스스로 정한 것을 물으면 확인 불가.
- ④ 고른 조례 원문 전체(별표는 annex.py로 펼친 줄)를 읽고, 조항 이름과 그 조항의 구절을 함께 낸다(#27 방식 + 구절).
- ⑤ 구절 관문(코드): 조항 이름이 목록에 있고 구절이 그 조항 글에 글자 그대로 있어야 인용한다. 근거 대조 판정(verify v1)은 쓰지 않는다.
- ⑥ 질문 대조(가설 17 v3-question 바탕): 질문 대상이 인용 조항에 있나. 대상마다 근거 구절을 받아 코드가 글자로 대조한다.

스스로 시험(키 없이, 몇 초): python -m engine.flow2.flow --selftest
"""
import json
import re

from .. import answer as answer_step
from .. import contract, pipeline, retrieve, upstage
from . import annex, lawmap, prompts

QUOTE_FAIL = "구절 불일치"     # ⑤ 고른 조항의 구절이 그 조항 글에 글자 그대로 없다
PROMPT_VERSIONS = {"analyze": prompts.ANALYZE_V, "read": prompts.READ_V, "check": prompts.CHECK_V}


# ---- 조항 이름 맞추기: #27 engine/whole.py(종희, PR #63)에서 옮김. #63 병합 뒤 `from ..whole import label_ids`로 바꾼다 ----
# flow2가 더한 것: 대괄호와 조 제목 괄호를 지운다. 조각 본문 첫 줄이 「[… 제8조(동물보호센터의 설치ㆍ지정 등)]」 꼴이라
# 모델이 그대로 옮겨 적어 「목록에 없는 조항」이 됐다(맛보기 120문항 중 8문항, 11-10).
def _norm(s):
    s = re.sub(r"\([^()]*\)|[\[\]]", "", s)
    return "".join(s.split()).strip("「」『』\"'“”‘’")


def _match(k, keys):
    """k가 keys 가운데 하나와 같거나, 그 키로 시작하고 바로 뒤가 숫자 · 「의」가 아닌 것. 여러 개면 가장 긴 키."""
    if k in keys:
        return k
    ok = [key for key in keys if k.startswith(key) and not (k[len(key)].isdigit() or k[len(key)] == "의")]
    return max(ok, key=len) if ok else None


def label_ids(labels, hits):
    """모델이 적은 조항 이름 → 목록 번호(1부터). 목록에 없는 이름은 버린다(조항을 지어낼 수 없다)."""
    full, short = {}, {}
    for i, h in enumerate(hits, 1):
        full.setdefault(_norm(h["label"]), i)
        short.setdefault(_norm(h["label"].removeprefix(h.get("law", ""))), []).append(i)
    ids = []
    for lab in labels:
        k = _norm(lab)
        if not k:
            continue
        key = _match(k, full)
        i = full[key] if key else None
        if i is None:
            key = _match(k, short)
            i = short[key][0] if key and len(short[key]) == 1 else None
        if i is not None and i not in ids:
            ids.append(i)
    return ids
# ---- 옮긴 것 끝 ----


# 구절 글자 대조(나의 우주 관문 G1과 같은 방식): 띄어쓰기 · 따옴표 · 표 칸 기호 · 쉼표 · 가운뎃점 모양 차이는 무시한다.
# 개정 꼬리표(<신설 2026.5.18> · [본조신설 …])는 양쪽에서 지운다(모델이 빼고 옮긴다). 「…」로 줄여 옮긴 구절은 조각마다 본다.
_SAME = str.maketrans({"～": "~", "∼": "~", "ㆍ": "·", "∙": "·", "•": "·", "․": "·", "‧": "·", "・": "·"})
_TAGS = re.compile(r"<[^<>]{0,60}>|\[[^\[\]]{0,120}\]")
_DROP = re.compile(r"[\s\"'“”‘’「」『』|,○◦●■□※]")
_ELLIPSIS = re.compile(r"\.{3,}|…|⋯|‥")
_ITEM = re.compile(r"^(?:\d+\.|[가-하]\.|[①-⑳])")


def _nq(s):
    return _DROP.sub("", _TAGS.sub("", (s or "").translate(_SAME)))


# 호 · 목 · 항 머리(「 2. 」 「 다. 」 「 ③」) 앞에서도 조각을 나눈다: 모델이 머리 문장과 떨어진 호를 「…」 없이 이어 옮긴다
# (본 측정 11-10: 「…다음 각 호와 같다. 2. 「국토의 …」」 꼴로 맞는 인용이 버려졌다). 조각마다 그 조항 글에 있어야 하는 것은 같다.
_ITEM_START = re.compile(r"(?:^|\s)(?=(?:\d{1,2}|[가-하])\.\s|[①-⑳])")


def quote_in(quote, text):
    """quote가 text에 글자 그대로 있나(위 차이 무시). 「…」로 줄였거나 호를 건너뛰어 이어 옮겼으면 조각(2글자 이상)마다 있어야 한다."""
    t = _nq(text)
    parts = [_ITEM.sub("", _nq(q)) for p in _ELLIPSIS.split(quote or "") for q in _ITEM_START.split(p)]
    parts = [p for p in parts if len(p) >= 2]
    return bool(parts) and all(p in t for p in parts)


def by_quote(label, quote, chunks, body):
    """조 이름만 적고(「제5조(제목)」) 한 항의 구절을 옮긴 경우: 그 조의 항 가운데 구절이 글자 그대로 있는 첫 항(원문 글자로만 고른다).
    본 측정 11-10에서 두 번째 실행이 이 꼴로 14문항을 「목록에 없는 조항」으로 잃었다."""
    k = _norm(label)
    for i, c in enumerate(chunks, 1):
        for key in (_norm(c["label"]), _norm(c["label"].removeprefix(c.get("law", "")))):
            if k and key.startswith(k) and key[len(k):len(k) + 1] == "제" and quote_in(quote, body[c["label"]]):
                return [i]
    return []


def view(laws, unit):
    """고른 조례의 조각 전체. 조례는 고른 순서, 안은 원문 순서. 킷이 1,800자씩 자른 별표는 flow2 별표 한 덩어리로 바꾼다."""
    out, seen = [], set()
    for c in retrieve.load(unit)[0]:
        if c["law"] not in laws:
            continue
        ax = annex.text_for(c)
        if ax is not None:
            if c["label"] in seen:
                continue
            seen.add(c["label"])
            c = {**c, "text": ax}
        out.append(c)
    return sorted(out, key=lambda c: laws.index(c["law"]))


def context(chunks):
    return "\n\n".join(f"[조항] {c['label']}\n{c['text']}" for c in chunks)


def _f2(st):
    return st.setdefault("flow2", {})


# ---- 단계 (함수 하나 = 단계 하나, pipeline.STAGES와 같은 꼴) ----
def analyze(st, cfg):
    """① 질문 분석: 답하지 않고 닫힌 값 칸만(solar 1번)."""
    raw = upstage.chat([{"role": "system", "content": prompts.ANALYZE},
                        {"role": "user", "content": f"[질문]\n{st['question']}"}],
                       cfg, st["calls"], response_format=prompts.ANALYZE_SCHEMA)
    _f2(st)["slots"] = json.loads(raw)


def route(st, cfg):
    """③ 조례 확정(코드만, 호출 0). 규칙과 근거 조항은 lawmap.py."""
    r = lawmap.route(st["question"], _f2(st).get("slots") or {}, st["_hits"], use_onto=cfg["flow2_ontology"])
    _f2(st)["route"] = r
    _f2(st)["ontology"] = lawmap.ontology.VERSION if cfg["flow2_ontology"] else "끔"
    if r["block"]:
        st["reason"] = r["block"]


def read(st, cfg):
    """④ 고른 조례를 통째로 읽고 답 · 결론 · 근거(조항 이름 + 구절)를 낸다(solar 1번). 원문이 앞, 질문이 뒤(입력 캐시)."""
    v = view(_f2(st)["route"]["laws"], cfg["chunk_unit"])
    st["_view"] = v
    hit = {c["label"]: c for c in st["candidates"]}          # 검색 후보 점수는 남기고, 나머지 조각은 점수 없음
    st["candidates"] = [hit.get(c["label"], {"label": c["label"], "score": None, "kw": None, "cos": None}) for c in v]
    s = _f2(st).get("slots") or {}
    note = (f"대상: {' · '.join(s.get('targets') or []) or '없음'} / 알고 싶은 것: {s.get('asks') or '없음'}"
            f" / 유형: {s.get('type') or '없음'}")
    raw = upstage.chat([{"role": "system", "content": prompts.READ},
                        {"role": "user", "content": f"[근거]\n{context(v)}\n\n[질문 분석]\n{note}\n\n[질문]\n{st['question']}"}],
                       cfg, st["calls"], response_format=prompts.READ_SCHEMA)
    out = json.loads(raw)
    st["_read"] = out
    _f2(st)["read"] = {k: out.get(k) for k in ("found", "conclusion", "evidence")}
    if not out.get("found"):
        st["reason"] = pipeline.NOT_FOUND


def gate(st, cfg):
    """⑤ 구절 관문(코드만): 목록에 있는 조항 · 자치구 아님 · 구절이 그 조항 글에 글자 그대로 있음 → 인용."""
    v, out = st["_view"], st["_read"]
    body = {}
    for c in v:
        body[c["label"]] = body.get(c["label"], "") + "\n" + c["text"]
    kept, ids, dropped = [], [], []
    for ev in out.get("evidence") or []:
        found = label_ids([ev.get("label", "")], v) or by_quote(ev.get("label", ""), ev.get("quote", ""), v, body)
        if not found:
            dropped.append({"label": ev.get("label", ""), "why": "목록에 없는 조항"})
            continue
        c = v[found[0] - 1]
        if answer_step.DISTRICT.search(c["label"]):
            dropped.append({"label": c["label"], "why": "자치구"})
        elif not quote_in(ev.get("quote", ""), body[c["label"]]):
            dropped.append({"label": c["label"], "why": "구절이 원문에 없음", "quote": ev.get("quote", "")})
        elif c["label"] not in {k["label"] for k in kept}:
            kept.append(c)
            ids.append(found[0])
    _f2(st)["gate"] = {"kept": [c["label"] for c in kept], "dropped": dropped}
    st["evidence_ids"] = ids
    if kept:
        st["draft"] = contract.build(out.get("answer", ""), kept)
    else:
        st["reason"] = QUOTE_FAIL if any(d["why"] == "구절이 원문에 없음" for d in dropped) else pipeline.NO_EVIDENCE


def check(st, cfg):
    """⑥ 질문 대조(solar 1번): 판정(가설 17 v3-question)이 notGrounded면 거절. 대상마다 받은 근거 구절은 코드가 글자로 대조해
    기록만 한다(거절에 쓰지 않음). 맛보기 120문항(11-10)에서 「대상마다 구절이 있어야 통과」는 가중 61.0, 「판정만」은 82.8이었다
    (같은 실행 기록으로 다시 매김). 구절을 못 댄 대상은 실패 고리에서 「시민 말 ↔ 조례 말」 빈칸 후보로 쓴다(failures.py)."""
    kept = set(_f2(st)["gate"]["kept"])
    used = [c for c in st["_view"] if c["label"] in kept]
    s = _f2(st).get("slots") or {}
    targets = [t.strip() for t in s.get("targets") or [] if t and t.strip()][:3]
    cited = lawmap.cited_laws(dict.fromkeys(c["law"] for c in used)) if cfg["flow2_ontology"] else []
    user = (f"[질문]\n{st['question']}\n\n[질문 분석]\n대상: {' · '.join(targets) or '없음'}\n\n"
            f"[근거 조례가 드는 법령]\n{' · '.join(cited) or '없음'}\n\n[근거]\n{context(used)}\n\n[답변]\n{st['draft']['answer']}")
    out = json.loads(upstage.chat([{"role": "system", "content": prompts.CHECK}, {"role": "user", "content": user}],
                                  cfg, st["calls"], response_format=prompts.CHECK_SCHEMA))
    got = out.get("targets") or []
    texts = "\n".join(c["text"] for c in used)
    marks = []
    for i, t in enumerate(targets):
        q = (got[i].get("quote") if i < len(got) else "") or ""
        marks.append({"asked": t, "quote": q, "ok": quote_in(q, texts)})
    st["verdict"] = out.get("verdict")
    _f2(st)["check"] = {"verdict": st["verdict"], "reason": out.get("reason", ""), "targets": marks}
    if st["verdict"] == "notGrounded":
        st["reason"] = pipeline.REJECTED


STAGES = [("검색", pipeline.search), ("질문 분석", analyze), ("조례 확정", route), ("조례 읽기 · 답 쓰기", read),
          ("구절 관문", gate), ("질문 대조", check), ("출력", pipeline.output)]


# ---- 스스로 시험 (키 없이) ----
def selftest():
    from .. import config
    from . import failures
    annex.selftest()
    lawmap.selftest()
    failures.selftest()
    assert quote_in("1회 주차시 5분당", "구 분: 1급지 · 1회주차시5분당: 500") and not quote_in("5분당 600", "5분당: 500")
    assert quote_in("「도시공원」 안에서", "도시공원 안에서") and not quote_in("가", "가나다")
    src = "④ 시장은 보상을 제공할 수 있다. <신설 2026.5.18>\n1. 차체 결함으로 이용이 불가능한 경우\n2. 그 밖의 경우"
    assert quote_in("시장은 보상을 제공할 수 있다. 1. 차체 결함으로 이용이 불가능한 경우", src)      # 개정 꼬리표를 빼고 옮김
    assert quote_in("시장은 보상을 ... 그 밖의 경우", src) and not quote_in("시장은 보상을 ... 지어낸 말", src)   # 「…」 조각마다
    assert quote_in("시장은 보상을 제공할 수 있다. 2. 그 밖의 경우", src)          # 1호를 건너뛰고 이어 옮김
    assert not quote_in("시장은 보상을 제공할 수 있다. 2. 지어낸 경우", src)
    assert quote_in("감면한다. <개정 2025.9.29> 3. 셋째", "감면한다. <개정 2025.9.29>\n1. 첫째\n3. 셋째")   # 날짜 점에서는 안 나눔
    body = {"서울특별시 동물보호 조례 제5조 제1항": "① 위원회를 둔다.", "서울특별시 동물보호 조례 제5조 제2항": "② 위원은 15명으로 한다.",
            "서울특별시 동물보호 조례 제5조의2": "위원은 15명으로 한다."}
    v5 = [{"label": k, "law": "서울특별시 동물보호 조례", "text": t} for k, t in body.items()]
    assert by_quote("서울특별시 동물보호 조례 제5조(동물복지위원회의 설치ㆍ운영)", "② 위원은 15명으로", v5, body) == [2]
    assert by_quote("[제5조(위원회)]", "위원은 15명으로", v5, body) == [2]               # 「제5조의2」로 새지 않음
    assert by_quote("서울특별시 동물보호 조례 제5조", "지어낸 말", v5, body) == []
    v = [{"label": "서울특별시 도시공원 조례 제7조 제3항", "law": "서울특별시 도시공원 조례"},
         {"label": "서울특별시 도시공원 조례 제7조의2", "law": "서울특별시 도시공원 조례"}]
    assert label_ids(["제7조 제3항", "서울특별시 도시공원 조례 제7조의2", "제9조"], v) == [1, 2]
    assert label_ids(["[서울특별시 도시공원 조례 제7조(공원의 관리) 제3항]"], v) == [1]   # 대괄호 · 조 제목 괄호

    law = "서울특별시 주차장 설치 및 관리 조례"
    chunks = [c for c in retrieve.load("paragraph")[0] if c["law"] == law]
    target = next(c for c in chunks if "경형자동차" in c["text"])
    quote = target["text"][target["text"].index("경형자동차"):][:12]
    plan = {}

    def fake_chat(messages, cfg, calls=None, response_format=None):
        name = response_format["json_schema"]["name"]
        if calls is not None:
            calls.append({"model": "fake", "in": 1, "cached": 0, "out": 1, "sec": 0.0})
        return json.dumps(plan[name], ensure_ascii=False)

    old = upstage.chat, upstage.has_key
    upstage.chat, upstage.has_key = fake_chat, (lambda: False)
    try:
        cfg = dict(config.load(), flow="flow2")
        slots = {"named_rule": "", "jurisdiction": "서울시", "jurisdiction_word": "", "targets": ["경차"], "asks": "가능 여부",
                 "type": "조건", "law_guess": "주차장"}
        plan.update(question_slots=slots,
                    law_answer_quotes={"found": True, "conclusion": "네", "answer": "네, 감면됩니다.",
                                       "evidence": [{"label": target["label"], "quote": quote}]},
                    target_check={"reason": "같은 대상", "targets": [{"asked": "경차", "quote": quote}], "verdict": "grounded"})
        r, t = pipeline.answer("경차를 공영주차장에 세우면 할인돼요?", cfg)
        assert r["citation"] == [target["label"]] and contract.guard(r) is r, (r, t["reason"], t.get("flow2"))
        assert t["flow2"]["gate"]["kept"] == [target["label"]] and t["prompts"] == PROMPT_VERSIONS
        # ⑤ 구절이 원문에 없으면 인용하지 않고 확인 불가
        plan["law_answer_quotes"] = dict(plan["law_answer_quotes"], evidence=[{"label": target["label"], "quote": "원문에 없는 말"}])
        r, t = pipeline.answer("경차를 공영주차장에 세우면 할인돼요?", cfg)
        assert r == contract.UNKNOWN and t["reason"] == QUOTE_FAIL, t["reason"]
        # ⑥ 대상 구절을 못 대도 판정이 grounded면 통과하고 기록만 한다 / 판정이 notGrounded면 거절(판정 전 답은 남김)
        plan["law_answer_quotes"] = dict(plan["law_answer_quotes"], evidence=[{"label": target["label"], "quote": quote}])
        plan["target_check"] = {"reason": "", "targets": [{"asked": "경차", "quote": ""}], "verdict": "grounded"}
        r, t = pipeline.answer("경차를 공영주차장에 세우면 할인돼요?", cfg)
        assert r["citation"] == [target["label"]] and t["flow2"]["check"]["targets"][0]["ok"] is False, t["reason"]
        plan["target_check"] = dict(plan["target_check"], verdict="notGrounded")
        r, t = pipeline.answer("경차를 공영주차장에 세우면 할인돼요?", cfg)
        assert r == contract.UNKNOWN and t["reason"] == pipeline.REJECTED and t["draft"]["citation"] == [target["label"]]
        # ③ 6종 밖 조례 이름 → 읽기 전에 확인 불가(호출은 분석까지)
        plan["question_slots"] = dict(slots, named_rule="청년주거 기본 조례", law_guess="청년")
        r, t = pipeline.answer("서울시 청년주거 기본 조례는 누구를 지원해요?", cfg)
        assert r == contract.UNKNOWN and t["reason"] == lawmap.REJECT_NAME and "조례 읽기 · 답 쓰기" not in t["steps"], t["reason"]
        # 출발 판(flow 기본값)은 그대로 kit 흐름
        assert config.DEFAULTS["flow"] == "kit"
    finally:
        upstage.chat, upstage.has_key = old
    print("flow2 스스로 시험: 통과")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        print("쓰는 법: python -m engine.flow2.flow --selftest")
