"""flow2: 검색 → 질문 분석 → 조례 확정 → 조례 읽고 답 쓰기 → 구절 관문 → 질문 대조 → 출력 (PM 별도 실험, 동규 11-10).

설계 · 이유: 공유 노트 「PM별도실험-설계-11-10」. 설정 `flow`가 "flow2"면 pipeline.answer가 이 STAGES를 돈다. 마감 · 오류 · 판단 기록 ·
출구 검사(#22)는 pipeline의 고리를 그대로 쓰고, 검색은 pipeline.search 그대로다. 팀원 파일(answer · whole · gate · retrieve ·
build_index · verify · contract · upstage)은 고치지 않고 부르기만 한다.

- ③ 조례 확정은 코드만(lawmap.route): 질문이 이름을 든 조례가 6종이 아니거나, 자치구 · 다른 시도가 스스로 정한 것을 물으면 확인 불가.
- ④ 고른 조례 원문 전체(별표는 annex.py로 펼친 줄)를 읽고, 조항 이름과 그 조항의 구절을 함께 낸다(#27 방식 + 구절).
- ⑤ 구절 관문(코드): 조항 이름이 목록에 있고 구절이 그 조항 글에 글자 그대로 있어야 인용한다. 근거 대조 판정(verify v1)은 쓰지 않는다.
- ⑥ 질문 대조(가설 17 v3-question 바탕): 질문 대상이 인용 조항에 있나. 대상마다 근거 구절을 받아 코드가 글자로 대조한다.

- 5판: 호출 하나가 오래 안 돌아오면 기다리면서 하나 더 부르고, 깨진 JSON 출력은 다시 부른다(guarded). 시간 초과 · 오류를 없애려는 것이다.
- 6판: 검색이 끝나면 ①을 기다리지 않고 ④를 미리 부른다(검색 점수만으로 고른 조례). ③이 같은 조례로 정하면 그 답을 쓰고, 다르면 버리고 다시 읽는다.
- 7판: 원문이 내용을 상위 법령으로 넘기기만 하는 구절 뒤에 「이 자료에 없다」 표시를 붙여 ④ · ⑥에 보여 준다(DELEG). ⑥ 출력 끝에 닫는 칸(c8).

스스로 시험(키 없이, 몇 초): python -m engine.flow2.flow --selftest
"""
import contextvars
import json
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from concurrent.futures import TimeoutError as FutureTimeout

from .. import answer as answer_step
from .. import contract, pipeline, retrieve, upstage
from . import annex, lawmap, prompts

QUOTE_FAIL = "구절 불일치"     # ⑤ 고른 조항의 구절이 그 조항 글에 글자 그대로 없다


def prompt_versions(cfg):
    """판단 기록에 남길 단계별 프롬프트 판 이름(설정 flow2_version이 고른 판)."""
    return {k: prompts.pick(cfg, k)[0] for k in prompts.SETS[cfg["flow2_version"]]}


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
_ITEM = re.compile(r"^(?:\d+\.|[가-하]\.|[①-⑳]|제\d+항)")   # 「제N항」: 모델이 항 머리 「②」를 「제2항」으로 바꿔 옮긴다(11-10 2판 시험)
# 3판: 짧은 괄호 글(「(이하 "시장"이라 한다)」 · 「(月齡)」)은 양쪽에서 지우고 본다. 모델이 빼고 옮겨 맞는 구절이 버려졌다
# (2판 전체 측정 11-10: dev 한 실행에서 버린 구절 40개 중 14개, 정답 조항을 잃은 문항 5~6개. 옛 규칙으로 통과하던 구절은 그대로 통과 777/777)
_PAREN = re.compile(r"\([^()]{0,40}\)")


def _nq(s):
    return _DROP.sub("", _TAGS.sub("", (s or "").translate(_SAME)))


# 호 · 목 · 항 머리(「 2. 」 「 다. 」 「 ③」) 앞에서도 조각을 나눈다: 모델이 머리 문장과 떨어진 호를 「…」 없이 이어 옮긴다
# (본 측정 11-10: 「…다음 각 호와 같다. 2. 「국토의 …」」 꼴로 맞는 인용이 버려졌다). 조각마다 그 조항 글에 있어야 하는 것은 같다.
_ITEM_START = re.compile(r"(?:^|\s)(?=(?:\d{1,2}|[가-하])\.\s|[①-⑳])")


def quote_in(quote, text, paren=False):
    """quote가 text에 글자 그대로 있나(위 차이 무시). 「…」로 줄였거나 호를 건너뛰어 이어 옮겼으면 조각(2글자 이상)마다 있어야 한다.
    paren=True(3판)면 짧은 괄호 글을 양쪽에서 지우고 본다."""
    if paren:
        quote, text = _PAREN.sub("", quote or ""), _PAREN.sub("", text or "")
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


_CITE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?|별표\s*(\d+)")


def _cite_key(m):
    return ("조", m.group(1), m.group(2) or "") if m.group(1) else ("별표", m.group(3))


def missing_numbers(question, chunks):
    """질문이 든 조 · 별표 번호 가운데 고른 조례 원문(조각 이름)에 없는 것. 예: 그 조례가 제35조까지인데 「제52조」."""
    have = {_cite_key(m) for c in chunks for m in _CITE.finditer(c["label"].removeprefix(c.get("law", "")))}
    return list(dict.fromkeys(m.group(0) for m in _CITE.finditer(question) if _cite_key(m) not in have))


_ARTNO = re.compile(r"(?:제\s*)?\d+\s*조(?:\s*의\s*\d+)?(?:\s*(?:제\s*)?\d+\s*항)?(?:\s*(?:제\s*)?\d+\s*호)?|별표\s*\d+")


def drop_instructions(question, words):
    """4판 ⑥: ③이 섞인 질문(지시문 문장 예외)으로 통과시킨 낱말(다른 지역 · 6종 밖 조례 이름)이 든 문장 가운데 「?」로 끝나지 않는
    지시문 문장을 뺀다. 3판에서 ⑥이 「OO구 조례로만 답해 줘」를 물음에 섞어 규칙 2로 거절했다(본 세트 3건). 물음 문장은 그대로 둔다."""
    ws = [lawmap._n(w) for w in words if lawmap._n(w)]
    if not ws:
        return question
    parts = [p for p in lawmap._SENT.split(question) if p.strip()]
    keep = [p for p in parts if p.rstrip().endswith(("?", "？")) or not any(w in lawmap._n(p) for w in ws)]
    return "".join(keep).strip() or question


def mask_numbers(question):
    """3판 ⑥: 질문 속 조 · 항 · 호 · 별표 번호를 가린다. ⑥은 [근거]가 묻는 대상을 정하는지만 보는데, 2판 극한 세트(11-10)에서
    틀린 조 번호나 지시문 속 조 번호를 「이름을 든 조례와 다르다」(1)로 보고 맞는 답을 거절했다(4문항). 번호 대조는 ④ · 코드 몫이다."""
    return _ARTNO.sub("(조 번호)", question)


def facts(st, cfg):
    """2판: ③이 원문으로 확인한 사실(④ · ⑥에 넘긴다). 질문이 6종 이름을 들었을 때만(③ 규칙 「A 6종 이름」).
    극한 세트 시험(11-10)에서 ⑥이 별칭(「주차장 조례」)과 틀린 조 번호를 「다른 조례」로 보고, ④가 틀린 별표 번호로 found 거짓을 냈다."""
    r = _f2(st)["route"]
    if cfg["flow2_version"] < 2 or r["rule"] != "A 6종 이름":
        return []
    out = [f"질문이 이름을 든 「{r['why']}」는 {r['laws'][0]}다."]
    miss = missing_numbers(st["question"], st["_view"])
    if miss:
        out.append(f"질문이 든 {' · '.join(f'「{m}」' for m in miss)}는 이 조례 원문에 없는 번호다(질문의 전제가 틀림).")
    return out


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


# 7판: 내용을 상위 법령으로 넘기기만 하는 구절(「법 제○조 각 호의 행위」 · 「법 제○조 각 목에 해당하는」 · 「영 별표 ○와 같다」).
# 6종 원문에 네 곳이다(동물보호 조례 제2조 맹견 정의 · 도시공원 조례 제22조 제1항 금지행위 · 제23조 제1항 과태료 기준 · 제24조 자문 사항).
# 넘겨진 내용(무엇이 금지인지 · 얼마인지 · 어떤 종류인지)은 6종 원문에 없는데, 1~6판은 이 조문을 근거로 「법 제49조 각 호의 행위가
# 금지됩니다」 같은 답을 만들어 함정이 샜다(1~4판 16개 실행에서 common-T018 5번 · animal-X031 5번 · common-T043 4번 · park-X034 3번).
# 모델에게 규칙 글로 시키는 것(11-10 작은 묶음 r7 bc)은 듣지 않았고, 「없다」는 표시를 자료 안에 붙이면 지어내지 않았다.
# 원문 글자에서만 찾는다. 조문이 내용을 스스로 적은 인용(「영 제23조 별표 1의 제10호 …를 위하여 설치하는 가설건축물」)에는 붙이지 않는다.
DELEG = re.compile(r"(?:법|영|시행령|시행규칙)\s*제\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호)?(?:\s*(?:및|ㆍ|·)\s*제\d+항)?\s*"
                   r"(?:각\s*호의\s*(?:행위|사항)|각\s*목에\s*해당하는|별표\s*\d+\s*와\s*같다)")
DELEG_MARK = "(※ 그 내용은 이 자료에 없다)"


def context(chunks, mark=False):
    """모델에게 보여 줄 근거 글. mark=True(7판)면 위임 구절 뒤에 DELEG_MARK를 붙인다(구절 대조 ⑤는 표시 없는 원문으로 한다)."""
    return "\n\n".join(f"[조항] {c['label']}\n" + (DELEG.sub(lambda m: m.group(0) + DELEG_MARK, c["text"]) if mark else c["text"])
                       for c in chunks)


def _f2(st):
    return st.setdefault("flow2", {})


# ---- 5판: 호출 지키기 ----
# 11-10 측정(1~4판 30개 실행)에서 시간 초과 9문항은 모두 호출 하나가 70초 넘게 돌아오지 않은 것이었고(④ 6 · ⑥ 2 · ① 1),
# 오류 4문항(끊긴 네트워크 제외)은 모두 모델이 낸 JSON이 깨진 것이었다(같은 물음을 되풀이하다 끊기거나 빈칸만 이어짐).
# 같은 문항이 다른 실행에서는 몇 초 만에 정상으로 돌아왔다. 그래서 늦으면 하나 더 부르고, 깨지면 다시 부른다.
# 연결 오류: 4판 dev 두 번째 실행(15:50쯤 네트워크가 끊김)에서 102문항이 검색 단계의 APIConnectionError로 끝났다. upstage.py는
# 15.5초 동안 여섯 번 부르고 그만둔다(마감 75초까지 59초가 남는데도). 그래서 마감까지 20초 넘게 남았으면 한 바퀴 더 부른다.
# 팀원 파일 upstage.py는 고치지 않는다. 문항 마감(timeout_sec)은 그대로 upstage 예산이 시도마다 본다.
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="flow2")
TRIES = 3   # 한 단계에 많아야 세 번(늦어서 하나 더 · JSON이 깨져서 다시, 합쳐서)
RETRY_LEFT_SEC = 20   # 연결 오류 · 5xx · 429로 끝난 호출은 문항 마감까지 이보다 많이 남았을 때만 다시 부른다


def _left():
    """문항 마감까지 남은 초(pipeline.answer가 건 upstage 예산). 마감이 없으면 None."""
    b = upstage._budget.get()
    return None if not b or b[0] is None else b[0] - time.monotonic()


def guarded(st, cfg, fn, name):
    """fn(calls) → 값. calls는 그 시도만의 호출 기록이고, 쓴 시도의 것만 st["calls"]에 붙인다(버린 시도의 토큰은 기록에 안 잡힌다).
    flow2_hedge_sec이 없으면(1~4판) 그냥 부른다. 어느 호출을 왜 더 불렀는지는 flow2.guard에 남긴다."""
    limit = cfg["flow2_hedge_sec"]
    if not limit:
        return fn(st["calls"])
    pend, err, tries = {}, None, 0

    def start(why=None):
        nonlocal tries
        tries += 1
        if why:
            _f2(st).setdefault("guard", []).append(f"{name}: {why}")
        box = []
        pend[_POOL.submit(contextvars.copy_context().run, fn, box)] = box

    start()
    while pend:
        done, _ = wait(pend, timeout=limit if tries < TRIES else None, return_when=FIRST_COMPLETED)
        if not done:
            start("늦음")
            continue
        for f in done:
            box, err = pend.pop(f), f.exception()
            if err is None:
                st["calls"].extend(box)
                return f.result()
            if isinstance(err, json.JSONDecodeError) and tries < TRIES:
                start("깨진 JSON")
            elif upstage.retryable(err) and not pend and (_left() or 0) > RETRY_LEFT_SEC:
                start("연결 오류")
    raise err


def _ask(st, cfg, step, user):
    """모델 호출 하나(시스템 프롬프트 · JSON 칸은 판이 고른다) → 읽어 들인 JSON."""
    _, system, schema = prompts.pick(cfg, step)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return guarded(st, cfg, lambda calls: json.loads(upstage.chat(messages, cfg, calls, response_format=schema)), step)


# ---- 6판: ④ 미리 읽기 ----
# 3판 dev · 극한 네 실행에서 ③이 검색 점수만으로 조례를 정한 문항(규칙 「고르기」)이 dev 92% · 극한 75%였다. 이때 ④는 ①의 결과가
# 없어도 같은 조례를 읽는다. 그래서 ①과 ④를 함께 부르고, ③이 다른 조례를 정했거나(분석이 조례를 더함 · 질문이 6종 이름을 듦) 막으면
# 미리 읽은 답은 버린다. 미리 읽기와 다시 읽기가 같은 글을 받도록 6판 ④에는 질문 분석 줄(대상 · 알고 싶은 것 · 유형)을 넣지 않는다(r6).
_SPEC = ThreadPoolExecutor(max_workers=8, thread_name_prefix="flow2-spec")   # 안에서 guarded가 _POOL을 쓰므로 풀을 나눈다


def _read_user(question, v, cfg, fx=()):
    """6판 ④에 보내는 글: 원문 · (③이 확인한 사실) · 질문."""
    return (f"[근거]\n{context(v, cfg['flow2_version'] >= 7)}\n\n" + ("[조례 확정]\n" + "\n".join(fx) + "\n\n" if fx else "")
            + f"[질문]\n{question}")


def _wait(fut):
    """미리 부른 호출을 문항 마감 전까지만 기다린다."""
    try:
        return fut.result(timeout=_left())
    except FutureTimeout:
        raise upstage.DeadlineExceeded("미리 읽기가 마감 전에 안 끝남") from None


# ---- 단계 (함수 하나 = 단계 하나, pipeline.STAGES와 같은 꼴) ----
def search(st, cfg):
    """검색(pipeline.search 그대로). 임베딩 호출도 guarded로 지킨다. 6판은 끝나자마자 ④를 미리 부른다."""
    def fn(calls):
        tmp = {"question": st["question"], "calls": calls, "reason": None}
        pipeline.search(tmp, cfg)
        return tmp
    st.update({k: v for k, v in guarded(st, cfg, fn, "search").items() if k not in ("question", "calls")})
    laws = lawmap.pick_laws(st["_hits"]) if cfg["flow2_version"] >= 6 and not st["reason"] else []
    if laws:
        box = {"calls": []}
        user = _read_user(st["question"], view(laws, cfg["chunk_unit"]), cfg)
        st["_spec"] = (laws, box, _SPEC.submit(contextvars.copy_context().run, _ask, box, cfg, "read", user))


def analyze(st, cfg):
    """① 질문 분석: 답하지 않고 닫힌 값 칸만(solar 1번)."""
    _f2(st)["slots"] = _ask(st, cfg, "analyze", f"[질문]\n{st['question']}")


def route(st, cfg):
    """③ 조례 확정(코드만, 호출 0). 규칙과 근거 조항은 lawmap.py."""
    r = lawmap.route(st["question"], _f2(st).get("slots") or {}, st["_hits"], use_onto=cfg["flow2_ontology"],
                     mixed_ok=cfg["flow2_version"] >= 2, sentences=cfg["flow2_version"] >= 3)
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
    fx = _f2(st)["facts"] = facts(st, cfg)
    if fx:
        note += "\n\n[조례 확정]\n" + "\n".join(fx)
    laws, box, fut = st.pop("_spec", None) or (None, None, None)
    if fut and laws == _f2(st)["route"]["laws"] and not fx:      # 6판: 미리 읽은 것이 ③이 정한 조례와 같다 → 그 답을 쓴다
        out = _wait(fut)
        st["calls"].extend(box["calls"])
        if box.get("flow2"):
            _f2(st).setdefault("guard", []).extend(box["flow2"]["guard"])
        _f2(st)["spec"] = "씀"
    elif cfg["flow2_version"] >= 6:
        _f2(st)["spec"] = "버림"
        out = _ask(st, cfg, "read", _read_user(st["question"], v, cfg, fx))
    else:
        out = _ask(st, cfg, "read", f"[근거]\n{context(v)}\n\n[질문 분석]\n{note}\n\n[질문]\n{st['question']}")
    st["_read"] = out
    _f2(st)["read"] = {k: out.get(k) for k in ("found", "conclusion", "evidence")}
    if "check" in out:                       # 3판(r4): 결론 앞에 쓴 조건 대조
        _f2(st)["read"]["check"] = out["check"]
    if "asks" in out:                        # #81(r8-81): 물음마다 든 조항 이름
        _f2(st)["read"]["asks"] = out["asks"]
    if not out.get("found"):
        st["reason"] = pipeline.NOT_FOUND


def gate(st, cfg):
    """⑤ 구절 관문(코드만): 목록에 있는 조항 · 자치구 아님 · 구절이 그 조항 글에 글자 그대로 있음 → 인용."""
    v, out = st["_view"], st["_read"]
    body = {}
    for c in v:
        body[c["label"]] = body.get(c["label"], "") + "\n" + c["text"]
    kept, ids, dropped = [], [], []
    v3 = cfg["flow2_version"] >= 3
    for ev in out.get("evidence") or []:
        if cfg["flow2_version"] >= 7:   # 7판: 모델이 위임 표시까지 옮겨 적었으면 떼고 대조한다
            ev = dict(ev, quote=ev.get("quote", "").replace(DELEG_MARK, ""))
        lab = ev.get("label", "")
        if v3:   # 3판: 모델이 근거 줄 머리 「[조항]」까지 옮겨 적는다(2판 dev 두 번째 실행에서 13문항이 「목록에 없는 조항」, 11-10)
            lab = lab.replace("[조항]", "").strip()
        found = label_ids([lab], v) or by_quote(lab, ev.get("quote", ""), v, body)
        if not found:
            dropped.append({"label": ev.get("label", ""), "why": "목록에 없는 조항"})
            continue
        c = v[found[0] - 1]
        if answer_step.DISTRICT.search(c["label"]):
            dropped.append({"label": c["label"], "why": "자치구"})
        elif not quote_in(ev.get("quote", ""), body[c["label"]], paren=v3):
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
    who = (f"\n묻는 일을 하는 사람: {s.get('actor') or '없음'}\n알고 싶은 것: {s.get('asks') or '없음'}"   # 2판: c4의 4(행위 주체)
           if cfg["flow2_version"] >= 2 else "")
    fx = _f2(st).get("facts") or []
    question = st["question"]
    if cfg["flow2_version"] >= 4:            # 4판: ③이 지시문 문장 예외로 통과시킨 낱말이 든 지시문 문장을 뺀다
        question = drop_instructions(question, _f2(st)["route"].get("mixed") or [])
    if cfg["flow2_version"] >= 3:            # 3판: 조 번호를 가리고(mask_numbers), 「없는 번호」 사실은 ⑥에 넘기지 않는다(④에는 넘김)
        question, fx = mask_numbers(question), fx[:1]
    if cfg["flow2_version"] >= 4:            # 4판: 별칭 사실 줄에 분석이 옮긴 조 번호도 가린다(3판에서 「…5조 1항 8호」가 남음)
        fx = [mask_numbers(x) for x in fx]
    who += ("\n\n[조례 확정]\n" + "\n".join(fx)) if fx else ""
    user = (f"[질문]\n{question}\n\n[질문 분석]\n대상: {' · '.join(targets) or '없음'}{who}\n\n"
            f"[근거 조례가 드는 법령]\n{' · '.join(cited) or '없음'}\n\n[근거]\n{context(used, cfg['flow2_version'] >= 7)}\n\n"
            f"[답변]\n{st['draft']['answer']}")
    out = _ask(st, cfg, "check", user)
    got = out.get("targets") or []
    texts = "\n".join(c["text"] for c in used)
    marks = []
    for i, t in enumerate(targets if "targets" in out else []):   # 5판(c7)은 targets 칸이 없다(기록만 하던 칸)
        q = (got[i].get("quote") if i < len(got) else "") or ""
        marks.append({"asked": t, "quote": q, "ok": quote_in(q, texts)})
    if cfg["flow2_version"] >= 2:      # c3 · c4: 물음마다 판정 → 하나라도 grounded면 통과(답할 물음은 답하고 나머지는 범위 밖이라고 적었다)
        vs = [a.get("verdict") for a in out.get("asks") or []]
        st["verdict"] = "grounded" if "grounded" in vs else "notGrounded" if vs and set(vs) == {"notGrounded"} else "notSure"
    else:
        st["verdict"] = out.get("verdict")
    _f2(st)["check"] = {"verdict": st["verdict"], "reason": out.get("reason", ""), "targets": marks, "asks": out.get("asks")}
    if st["verdict"] == "notGrounded":
        st["reason"] = pipeline.REJECTED


STAGES = [("검색", search), ("질문 분석", analyze), ("조례 확정", route), ("조례 읽기 · 답 쓰기", read),
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
    two = "② 제1항에 따른 대상자는 다음과 같다. <개정 2019.3.28>\n1. 청소년 중 13세 이상인 사람"
    assert quote_in("제2항에 따른 대상자는 다음과 같다. 1. 청소년 중 13세 이상인 사람", two)    # 항 머리 「②」를 「제2항」으로 옮김
    assert not quote_in("제2항에 따른 대상자는 지어낸 말", two)
    body = {"서울특별시 동물보호 조례 제5조 제1항": "① 위원회를 둔다.", "서울특별시 동물보호 조례 제5조 제2항": "② 위원은 15명으로 한다.",
            "서울특별시 동물보호 조례 제5조의2": "위원은 15명으로 한다."}
    v5 = [{"label": k, "law": "서울특별시 동물보호 조례", "text": t} for k, t in body.items()]
    assert by_quote("서울특별시 동물보호 조례 제5조(동물복지위원회의 설치ㆍ운영)", "② 위원은 15명으로", v5, body) == [2]
    assert by_quote("[제5조(위원회)]", "위원은 15명으로", v5, body) == [2]               # 「제5조의2」로 새지 않음
    assert by_quote("서울특별시 동물보호 조례 제5조", "지어낸 말", v5, body) == []
    park = [c for c in retrieve.load("paragraph")[0] if c["law"] == "서울특별시 도시공원 조례"]
    assert missing_numbers("공원 조례 제99조 · 별표 3 · 별표 9 · 제22조의2에 나와요?", park) == ["제99조", "별표 9"]
    v = [{"label": "서울특별시 도시공원 조례 제7조 제3항", "law": "서울특별시 도시공원 조례"},
         {"label": "서울특별시 도시공원 조례 제7조의2", "law": "서울특별시 도시공원 조례"}]
    assert label_ids(["제7조 제3항", "서울특별시 도시공원 조례 제7조의2", "제9조"], v) == [1, 2]
    assert label_ids(["[서울특별시 도시공원 조례 제7조(공원의 관리) 제3항]"], v) == [1]   # 대괄호 · 조 제목 괄호
    # 3판: 괄호 글을 빼고 옮긴 구절(옛 규칙은 버림) · 지어낸 말은 그대로 버림 · 조 번호 가리기
    par = '① 서울특별시장(이하 "시장"이라 한다)은 월령(月齡) 3개월 이상인 개의 명단을 매년 정리하여야 한다.'
    assert quote_in("서울특별시장은 월령 3개월 이상인 개의 명단을", par, paren=True) and not quote_in("서울특별시장은 월령 3개월", par)
    assert quote_in('서울특별시장(이하 "시장"이라 한다)은', par, paren=True) and not quote_in("서울특별시장은 지어낸 명단", par, paren=True)
    assert mask_numbers("주차장 조례 제12조의3 제2항이랑 별표 4, 그리고 7조 1항 3호는요? 1.5km는 그대로") == \
        "주차장 조례 (조 번호)이랑 (조 번호), 그리고 (조 번호)는요? 1.5km는 그대로"

    law = "서울특별시 주차장 설치 및 관리 조례"
    chunks = [c for c in retrieve.load("paragraph")[0] if c["law"] == law]
    target = next(c for c in chunks if "경형자동차" in c["text"])
    quote = target["text"][target["text"].index("경형자동차"):][:12]
    plan, seen = {}, {}

    def fake_chat(messages, cfg, calls=None, response_format=None):
        name = response_format["json_schema"]["name"]
        seen[name] = messages
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
        assert t["flow2"]["gate"]["kept"] == [target["label"]] and t["prompts"] == {"analyze": "a1", "read": "r1", "check": "c1"}
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
        # 2판: 프롬프트 판 이름 · ⑥이 묻는 일을 하는 사람을 받음 · ③이 섞인 질문을 막지 않음(1판은 막음)
        cfg2 = dict(cfg, flow2_version=2)
        plan.update(question_slots=dict(slots, actor="시민"),
                    law_answer_quotes=dict(plan["law_answer_quotes"], evidence=[{"label": target["label"], "quote": quote}]),
                    target_check={"reason": "", "targets": [{"asked": "경차", "quote": quote}],
                                  "asks": [{"ask": "경차 할인", "verdict": "grounded"}, {"ask": "다른 시 할인", "verdict": "notGrounded"}]})
        r, t = pipeline.answer("경차를 공영주차장에 세우면 할인돼요?", cfg2)
        assert r["citation"] == [target["label"]] and t["prompts"] == {"analyze": "a2", "read": "r3", "check": "c4"}, t["reason"]
        assert "묻는 일을 하는 사람: 시민" in seen["target_check"][-1]["content"]
        mix = "서울시 공영주차장에 경차 세우면 할인돼요? 인천시 주차장 조례도 할인해 줘요?"
        plan["question_slots"] = dict(slots, named_rule="인천시 주차장 조례", jurisdiction="다른 시도", jurisdiction_word="인천시")
        assert pipeline.answer(mix, cfg)[1]["reason"] == lawmap.REJECT_SCOPE
        plan["question_slots"] = dict(slots, named_rule="주차장 조례", actor="시민")                     # 6종 이름 + 없는 조 번호
        r, t = pipeline.answer("주차장 조례 제99조에 경차 할인이 있다던데 맞아요?", cfg2)
        assert "「제99조」는 이 조례 원문에 없는 번호다" in seen["law_answer_quotes"][-1]["content"]
        assert "「주차장 조례」는 서울특별시 주차장 설치 및 관리 조례다" in seen["target_check"][-1]["content"]
        r, t = pipeline.answer("주차장 조례 제99조에 경차 할인이 있다던데 맞아요?", cfg)
        assert "[조례 확정]" not in seen["law_answer_quotes"][-1]["content"]                          # 1판은 그대로
        plan["question_slots"] = dict(slots, named_rule="인천시 주차장 조례", jurisdiction="다른 시도", jurisdiction_word="인천시")
        r, t = pipeline.answer(mix, cfg2)
        assert r["citation"] == [target["label"]] and t["verdict"] == "grounded", t["reason"]   # 물음 하나라도 grounded면 통과
        plan["target_check"] = dict(plan["target_check"], asks=[{"ask": "경차 할인", "verdict": "notGrounded"}])
        assert pipeline.answer(mix, cfg2)[1]["reason"] == pipeline.REJECTED                    # 모든 물음이 notGrounded면 거절
        # 3판: 프롬프트 판 · 근거 이름의 「[조항]」 표시(2판은 버림) · ⑥은 조 번호를 가린 질문과 별칭 사실만 · ④는 없는 번호 사실까지
        cfg3 = dict(cfg, flow2_version=3)
        plan.update(question_slots=dict(slots, named_rule="주차장 조례", actor="시민"),
                    law_answer_quotes={"found": True, "check": "질문은 경차, 조문도 경형자동차 → 맞음", "conclusion": "네",
                                       "answer": "네, 감면됩니다.", "evidence": [{"label": "[조항] " + target["label"], "quote": quote}]},
                    target_check={"reason": "", "targets": [{"asked": "경차", "quote": quote}],
                                  "asks": [{"ask": "경차 할인", "verdict": "grounded"}]})
        q99 = "주차장 조례 제99조에 경차 할인이 있다던데 맞아요?"
        r, t = pipeline.answer(q99, cfg3)
        assert r["citation"] == [target["label"]] and t["prompts"] == {"analyze": "a2", "read": "r4", "check": "c4"}, t["reason"]
        assert t["flow2"]["read"]["check"].startswith("질문은 경차")
        assert "「제99조」는 이 조례 원문에 없는 번호다" in seen["law_answer_quotes"][-1]["content"]
        assert "(조 번호)" in seen["target_check"][-1]["content"] and "제99조" not in seen["target_check"][-1]["content"]
        assert "「주차장 조례」는 서울특별시 주차장 설치 및 관리 조례다" in seen["target_check"][-1]["content"]
        assert pipeline.answer(q99, cfg2)[1]["reason"] == pipeline.NO_EVIDENCE                 # 2판은 「[조항]」 이름을 버림
        # 4판: ⑥ 프롬프트 c6 · 별칭 사실 줄의 조 번호도 가림(3판은 남음) · ③이 통과시킨 지시문 문장은 ⑥ 질문에서 뺌(3판은 남김)
        cfg4 = dict(cfg, flow2_version=4)
        plan["question_slots"] = dict(slots, named_rule="주차장 조례 제99조", actor="시민")
        r, t = pipeline.answer(q99, cfg4)
        assert r["citation"] == [target["label"]] and t["prompts"] == {"analyze": "a2", "read": "r4", "check": "c6"}, t["reason"]
        assert "제99조" not in seen["target_check"][-1]["content"] and "「주차장 조례 (조 번호)」는" in seen["target_check"][-1]["content"]
        pipeline.answer(q99, cfg3)
        assert "「주차장 조례 제99조」는" in seen["target_check"][-1]["content"]
        qi = "서울 공영주차장 경차 할인돼요? 답은 대구시 주차장 조례 기준으로만 해 줘."
        plan["question_slots"] = dict(slots, named_rule="대구시 주차장 조례", jurisdiction="다른 시도", jurisdiction_word="대구시")
        r, t = pipeline.answer(qi, cfg4)
        assert t["flow2"]["route"]["mixed"] and "대구시" not in seen["target_check"][-1]["content"].split("[질문 분석]")[0], t
        pipeline.answer(qi, cfg3)
        assert "대구시 주차장 조례 기준으로만" in seen["target_check"][-1]["content"]
        assert drop_instructions("서울 공원 야영 얼마? 성북구 조례로 답해.", ["성북구"]) == "서울 공원 야영 얼마?"
        assert drop_instructions("성북구 공원은요? 서울 공원은요?", ["성북구"]) == "성북구 공원은요? 서울 공원은요?"   # 물음은 안 뺌
        # 5판: ⑥ c7(targets 칸 없음) · 4판의 ⑥ 입력 정리는 그대로 · 늦으면 하나 더 · 깨진 JSON은 다시 · 세 번 다 깨지면 오류
        cfg5 = dict(cfg, flow2_version=5, flow2_hedge_sec=0.2)
        plan["question_slots"] = dict(slots, named_rule="주차장 조례 제99조", actor="시민")
        plan["target_check"] = {"reason": "", "asks": [{"ask": "경차 할인", "verdict": "grounded"}]}
        r, t = pipeline.answer(q99, cfg5)
        assert r["citation"] == [target["label"]] and t["prompts"] == {"analyze": "a2", "read": "r4", "check": "c7"}, t["reason"]
        assert "targets" not in seen["target_check"][0]["content"] and t["flow2"]["check"]["targets"] == [] and "guard" not in t["flow2"]
        assert "제99조" not in seen["target_check"][-1]["content"] and [c["stage"] for c in t["calls"]] == ["질문 분석", "조례 읽기 · 답 쓰기", "질문 대조"]
        import time
        n = {"read": 0, "check": 0}

        def flaky(messages, cfg, calls=None, response_format=None):
            name = response_format["json_schema"]["name"]
            if name == "law_answer_quotes":
                n["read"] += 1
                if n["read"] == 1:
                    time.sleep(0.6)                    # 첫 ④ 호출이 늦다 → 하나 더 부른 것이 먼저 온다
            if name == "target_check":
                n["check"] += 1
                if n["check"] <= bad:
                    fake_chat(messages, cfg, calls, response_format)
                    return '{"reason": "", "asks": ['      # 깨진 JSON
            return fake_chat(messages, cfg, calls, response_format)

        upstage.chat, bad = flaky, 1
        r, t = pipeline.answer(q99, cfg5)
        assert r["citation"] == [target["label"]] and t["flow2"]["guard"] == ["read: 늦음", "check: 깨진 JSON"], (t["reason"], t["flow2"].get("guard"))
        assert [c["stage"] for c in t["calls"]] == ["질문 분석", "조례 읽기 · 답 쓰기", "질문 대조"] and t["sec"] < 0.6
        n.update(read=1, check=0)
        bad = 9
        r, t = pipeline.answer(q99, cfg5)
        assert r == contract.UNKNOWN and t["reason"] == pipeline.ERROR and n["check"] == TRIES, (t["reason"], n)
        n.update(read=1, check=0)
        r, t = pipeline.answer(q99, dict(cfg5, flow2_hedge_sec=None))            # 꺼 두면(1~4판) 한 번 깨지면 바로 오류
        assert t["reason"] == pipeline.ERROR and n["check"] == 1
        APIConnectionError = type("APIConnectionError", (Exception,), {})      # upstage.retryable은 오류 이름으로 가린다

        def down(messages, cfg, calls=None, response_format=None):
            n["down"] += 1
            if n["down"] <= fails:
                raise APIConnectionError("끊김")
            return fake_chat(messages, cfg, calls, response_format)

        upstage.chat, fails = down, 2                # 연결 오류 두 번 뒤 살아남: 마감까지 20초 넘게 남았으니 다시 불러 답한다
        n["down"] = 0
        r, t = pipeline.answer(q99, cfg5)
        assert r["citation"] == [target["label"]] and t["flow2"]["guard"] == ["analyze: 연결 오류", "analyze: 연결 오류"], t["flow2"].get("guard")
        n["down"], fails = 0, 99                     # 마감까지 20초가 안 남았으면 다시 부르지 않고 확인 불가(오류)로 끝낸다
        r, t = pipeline.answer(q99, dict(cfg5, timeout_sec=15))
        assert r == contract.UNKNOWN and t["reason"] == pipeline.ERROR and n["down"] == 1 and t["error"].startswith("APIConnectionError"), (t["reason"], n)
        upstage.chat = fake_chat
        # 6판: ④를 미리 부른다. ③이 검색만으로 정하면 그 답을 쓰고(질문 분석 줄 없음, r6), 질문이 6종 이름을 들면 버리고 사실과 함께 다시 읽는다
        cfg6 = dict(cfg, flow2_version=6, flow2_hedge_sec=0.2)
        plan["question_slots"] = dict(slots, actor="시민")
        r, t = pipeline.answer("경차를 공영주차장에 세우면 할인돼요?", cfg6)
        assert r["citation"] == [target["label"]] and t["prompts"] == {"analyze": "a2", "read": "r6", "check": "c7"}, t["reason"]
        assert t["flow2"]["spec"] == "씀" and t["flow2"]["route"]["rule"] == "고르기", t["flow2"]["route"]
        assert "[질문 분석]" not in seen["law_answer_quotes"][-1]["content"] and "[질문 분석]" not in seen["law_answer_quotes"][0]["content"]
        assert [c["stage"] for c in t["calls"]] == ["질문 분석", "조례 읽기 · 답 쓰기", "질문 대조"]
        plan["question_slots"] = dict(slots, named_rule="주차장 조례 제99조", actor="시민")
        r, t = pipeline.answer(q99, cfg6)
        assert r["citation"] == [target["label"]] and t["flow2"]["spec"] == "버림" and t["flow2"]["route"]["rule"] == "A 6종 이름"
        assert "[조례 확정]" in seen["law_answer_quotes"][-1]["content"] and "「제99조」는 이 조례 원문에 없는 번호다" in seen["law_answer_quotes"][-1]["content"]
        plan["question_slots"] = dict(slots, named_rule="청년주거 기본 조례", law_guess="청년")            # ③이 막으면 미리 읽은 답은 안 쓴다
        r, t = pipeline.answer("서울시 청년주거 기본 조례는 누구를 지원해요?", cfg6)
        assert r == contract.UNKNOWN and t["reason"] == lawmap.REJECT_NAME and "spec" not in t["flow2"]
        # 7판: 위임 구절 표시. 6종 원문에 네 곳뿐이고, ④ · ⑥에 보내는 글에만 붙는다(6판에는 없음). 표시까지 옮긴 구절도 ⑤를 지난다
        marked = [c["label"].removeprefix("서울특별시 ") for c in retrieve.load("paragraph")[0] if DELEG.search(c["text"])]
        assert marked == ["동물보호 조례 제2조", "도시공원 조례 제22조 제1항", "도시공원 조례 제23조 제1항", "도시공원 조례 제24조"], marked
        ban = next(c for c in retrieve.load("paragraph")[0] if c["label"].endswith("도시공원 조례 제22조 제1항"))
        assert "각 호의 행위" + DELEG_MARK in context([ban], True) and DELEG_MARK not in context([ban])
        cfg7 = dict(cfg, flow2_version=7, flow2_hedge_sec=0.2)
        plan.update(question_slots=dict(slots, law_guess="도시공원", actor="시민"),
                    law_answer_quotes={"found": True, "check": "", "conclusion": "정보", "answer": "법이 정한 행위가 금지됩니다.",
                                       "evidence": [{"label": ban["label"], "quote": "법 제49조제1항 및 제2항 각 호의 행위" + DELEG_MARK + "를 하여서는"}]},
                    target_check={"reason": "", "asks": [{"ask": "금지 행위", "verdict": "grounded"}], "done": True})
        r, t = pipeline.answer("서울 도시공원에서 금지되는 행위는 어느 법을 따르나요?", cfg7)
        assert r["citation"] == [ban["label"]] and t["prompts"] == {"analyze": "a2", "read": "r7", "check": "c8"}, (t["reason"], t["flow2"].get("gate"))
        assert DELEG_MARK in seen["law_answer_quotes"][-1]["content"] and DELEG_MARK in seen["target_check"][-1]["content"]
        pipeline.answer("서울 도시공원에서 금지되는 행위는 어느 법을 따르나요?", cfg6)
        assert DELEG_MARK not in seen["law_answer_quotes"][-1]["content"]
        # #81: flow2_read_asks를 켜면 ④가 r8-81(물음마다 조항 이름 칸 asks)을 쓰고 asks를 기록한다. 끄면(기본) 7판 그대로 r7
        assert config.DEFAULTS["flow2_read_asks"] is False
        qb = "서울 도시공원에서 금지되는 행위는 어느 법을 따르나요?"
        plan["law_answer_asks"] = dict(plan["law_answer_quotes"], asks=[{"ask": "금지 행위를 정한 법", "labels": [ban["label"]]}])
        r, t = pipeline.answer(qb, dict(cfg7, flow2_read_asks=True))
        assert r["citation"] == [ban["label"]] and t["prompts"] == {"analyze": "a2", "read": "r8-81", "check": "c8"}, t["reason"]
        assert t["flow2"]["read"]["asks"][0]["labels"] == [ban["label"]] and seen["law_answer_asks"][0]["content"] == prompts.READ81
        r, t = pipeline.answer(qb, cfg7)
        assert r["citation"] == [ban["label"]] and t["prompts"]["read"] == "r7" and "asks" not in t["flow2"]["read"]
        assert seen["law_answer_quotes"][0]["content"] == prompts.READ7
        # 출발 판(flow 기본값)은 그대로 kit 흐름
        assert config.DEFAULTS["flow"] == "kit" and config.DEFAULTS["flow2_hedge_sec"] is None
    finally:
        upstage.chat, upstage.has_key = old
    print("flow2 스스로 시험: 통과")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        print("쓰는 법: python -m engine.flow2.flow --selftest")
