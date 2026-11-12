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
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from concurrent.futures import TimeoutError as FutureTimeout

from .. import answer as answer_step
from .. import config, contract, pipeline, retrieve, upstage
from . import annex, lawmap, prompts

QUOTE_FAIL = "구절 불일치"     # ⑤ 고른 조항의 구절이 그 조항 글에 글자 그대로 없다


def prompt_versions(cfg):
    """판단 기록에 남길 단계별 프롬프트 판 이름(설정 flow2_version이 고른 판)."""
    return {k: v[0] for k, v in prompts.SETS[cfg["flow2_version"]].items()}


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
_POOL = ThreadPoolExecutor(max_workers=64, thread_name_prefix="flow2")   # 16 → 64(11-11): 다수결(flow2_votes)을 켜면 호출이 세 배다
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
    _, system, schema = prompts.SETS[cfg["flow2_version"]][step]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return guarded(st, cfg, lambda calls: json.loads(upstage.chat(messages, cfg, calls, response_format=schema)), step)


# ---- 스위치 flow2_votes · flow2_memo의 들머리 (11-11) ----
# 위 _ask는 한 글자도 고치지 않았다(#81이 고치는 함수라서). 같은 이름으로 한 겹 싸서, 두 스위치가 다 꺼져 있으면(기본) 위 _ask를 그대로 부른다.
_ask_one = _ask


def _ask(st, cfg, step, user):      # noqa: F811
    """스위치가 켜져 있으면 같은 호출을 여러 번 불러 다수결(flow2_votes) · 같은 글에는 적어 둔 출력(flow2_memo). 꺼져 있으면 _ask_one 그대로."""
    n = (cfg["flow2_votes"] or {}).get(step, 1)

    def run():
        return _ask_one(st, cfg, step, user) if n <= 1 else _voted(st, cfg, step, lambda s: _ask_one(s, cfg, step, user), n)
    if not cfg["flow2_memo"]:
        return run()
    return _memoed(st, cfg, [step, prompts.SETS[cfg["flow2_version"]][step][1], user], run)   # 열쇠: 단계 · 그 판의 프롬프트 글 · 보낸 글


# ---- 같은 글에는 같은 출력 (스위치 flow2_memo, 11-11) ----
# 모델은 같은 글을 보내도 다른 출력을 낸다(아래 「흔들림 줄이기」). 그래서 모델 호출의 출력을 「설정 전체 · 단계 · 프롬프트 글 · 보낸 글」의 지문별로
# 적어 두고, 같은 글을 다시 보내야 할 때는 부르지 않고 적어 둔 출력을 쓴다. 검색 결과도 질문별로 적어 둔다: 임베딩 호출도 같은 질문에 조금씩
# 다른 벡터를 돌려줘서(7판 dev 두 실행: 같은 조각의 의미 점수가 657문항 중 333문항에서 다르고 후보 묶음이 18문항에서 다름) ③이 다른 조례를 고를 수 있다.
# 같은 문의가 다시 오면 ① → ④ → ⑥이 차례로 같은 글을 받으므로
# 답 · 근거가 글자까지 같다. 조례 원문 · 프롬프트 · 설정이 하나라도 바뀌면 지문이 달라져 저절로 새로 부른다. 오류 · 시간 초과로 끝난 호출은 적지 않는다.
# 값은 파일 경로(레포 맨 위 기준)다. 서버를 다시 띄워도 남는다. ":memory:"면 파일 없이 프로세스 안에만 둔다.
# 같은 열쇠를 다른 스레드가 부르는 중이면 끝나기를 기다렸다가 그 값을 쓴다(같은 문의가 동시에 와도 한 번만 부른다. 문의 세트 확인 11-11에서
# 되풀이가 첫 실행이 끝나기 전에 시작돼 한 문항의 답이 갈렸다).
# ponytail: 파일은 줄만 덧붙인다(지우기 · 크기 상한 없음, 검색 결과는 문의 하나에 조각 20개의 글) — 문의가 수만 건이 되면 손본다.
_MEMO, _BUSY, _MEMO_LOCK = {}, {}, threading.Lock()


def _memoed(st, cfg, parts, run):
    """열쇠(설정 전체 + parts)에 적어 둔 값이 있으면 그것을, 없으면 run()을 부르고 적는다."""
    key = config.digest([config.digest(cfg, 32)] + parts, 32)
    with _MEMO_LOCK:
        mine = key not in _BUSY
        busy = _BUSY.setdefault(key, threading.Event())
    if not mine:
        busy.wait(timeout=_left())               # 먼저 부른 쪽을 문항 마감 전까지 기다린다
    try:
        out = _memo_get(cfg, key)
        if out is None:
            out = run()
            _memo_put(cfg, key, out)
            return out
    finally:
        if mine:
            with _MEMO_LOCK:
                _BUSY.pop(key, None)
            busy.set()
    st["calls"].append({"kind": "memo", "model": cfg["chat_model"], "in": 0, "cached": 0, "out": 0, "sec": 0.0,     # 안 불렀다는 기록(토큰 0)
                        "sent": key, "output": json.dumps(out, ensure_ascii=False, default=float)[:2000]})
    return out


def _memo_table(cfg):
    path = cfg["flow2_memo"]
    with _MEMO_LOCK:
        if path not in _MEMO:
            _MEMO[path] = {}
            f = config.ROOT / path
            if path != ":memory:" and f.is_file():
                for line in f.read_text(encoding="utf-8").splitlines():
                    try:
                        k, v = json.loads(line)
                        _MEMO[path][k] = v
                    except ValueError:          # 쓰다 끊긴 줄은 건너뛴다
                        pass
    return _MEMO[path]


def _memo_get(cfg, key):
    out = _memo_table(cfg).get(key)
    return None if out is None else json.loads(json.dumps(out))      # 사본(단계들이 받은 출력에 칸을 더한다)


def _memo_put(cfg, key, out):
    table, path = _memo_table(cfg), cfg["flow2_memo"]
    with _MEMO_LOCK:
        table[key] = json.loads(json.dumps(out, default=float))      # default=float: 검색 점수가 numpy 수일 수 있다
        if path != ":memory:":
            try:
                with open(config.ROOT / path, "a", encoding="utf-8") as f:
                    f.write(json.dumps([key, table[key]], ensure_ascii=False) + "\n")
            except OSError:                     # 적지 못해도 답은 낸다
                pass


# ---- 흔들림 줄이기 (스위치 flow2_votes, 11-11): 같은 호출을 여러 번 불러 다수결 ----
# 7판 dev 두 실행(11-10)을 견주니 ④는 보낸 글이 글자까지 같은 648문항 중 643문항의 출력이 달랐고 284문항은 근거 조항 묶음까지
# 달랐다(temperature 0, seed · top_p를 보내도 같다 — 11-11 작은 시험 8문항 × 4번). 모델이 같은 입력에 다른 출력을 내는 것은 못 막으니,
# 같은 호출을 n번 나란히 부르고 「결정」만 다수결로 정한다. 글(답 문장 · 구절)은 다수 쪽 출력 하나를 그대로 쓴다(섞어 짓지 않는다).
# - ① analyze: 조례 고르기에 쓰는 칸(이름 든 조례 · 관할 · 관할 낱말 · 가까운 조례)이 가장 많이 겹치는 출력.
# - ④ read: found는 과반. 근거 조항은 과반이 든 조항만(조항 이름은 ⑤와 같은 방법으로 원문 조각에 맞춘다). 구절은 그 조항을 든 출력들의
#   구절 가운데 원문에 글자 그대로 있는 것. 답 글은 근거 묶음이 다수결 결과와 가장 가까운 출력의 것.
#   flow2_votes에 "read_all": true를 더하면 과반 대신 「답한 표가 모두 든 조항만」 남긴다. 같은 ④ 입력을 100문항 × 10번 다시 보내
#   기록으로 견주니(11-11, 흔들림-도구/sim_rules.py) 두 번 넣어 같은 근거가 한 번 76% · 과반(3) 85% · 모두(3) 89%였다. 실행마다 들쭉날쭉한 것은
#   주로 「덧붙는 조항」이라서다. 대신 셋을 다 기다리고, 근거가 여럿 필요한 질문에서 하나를 잃을 수 있다.
# - ⑥ check: 과반이 notGrounded일 때만 거절.
# 온 표만으로 결과가 정해지면(예: 세 번 중 먼저 온 둘이 같다) 나머지는 기다리지 않는다. 결과는 다 기다린 것과 같다.
# 기다리지 않은 호출의 토큰은 기록(calls)에 안 잡힌다. 몇 표를 불렀고 몇 표를 썼는지는 flow2.vote에 남긴다.
_VOTE = ThreadPoolExecutor(max_workers=48, thread_name_prefix="flow2-vote")   # 안에서 guarded가 _POOL을 쓰므로 풀을 나눈다
_ROUTE_KEYS = ("named_rule", "jurisdiction", "jurisdiction_word", "law_guess")


def _dump(o):
    return json.dumps(o, ensure_ascii=False, sort_keys=True)


def _verdict(out):
    """⑥ 출력 하나의 판정(check와 같은 셈): 물음 하나라도 grounded면 grounded, 모두 notGrounded면 notGrounded."""
    if "asks" not in out:                 # 1판(c1)은 verdict 칸 하나
        return out.get("verdict")
    vs = [a.get("verdict") for a in out.get("asks") or []]
    return "grounded" if "grounded" in vs else "notGrounded" if vs and set(vs) == {"notGrounded"} else "notSure"


def _ev_label(ev, v, body, cfg):
    """④ 출력의 근거 하나 → 원문 조각 이름(⑤ gate와 같은 방법). 목록에 없는 조항이면 None."""
    lab = ev.get("label", "").replace("[조항]", "").strip()
    found = label_ids([lab], v) or by_quote(lab, ev.get("quote", "").replace(DELEG_MARK, ""), v, body)
    return v[found[0] - 1]["label"] if found else None


def pick_slots(outs, left, need):
    """① 다수결. 남은 표(left)가 와도 안 바뀌면 고른 출력, 아니면 None."""
    key = lambda o: tuple(_norm(str(o.get(k, ""))) for k in _ROUTE_KEYS)
    count = {}
    for o in outs:
        count[key(o)] = count.get(key(o), 0) + 1
    top = max(count.values())
    if top < need and left:
        return None
    if top >= need or top > 1:
        k = max(count, key=lambda x: (count[x], x))
        return min((o for o in outs if key(o) == k), key=_dump)
    # 모두 다르면: 칸마다 다수 값과 가장 많이 겹치는 출력
    cols = list(zip(*map(key, outs)))
    score = lambda o: sum(cols[i].count(x) for i, x in enumerate(key(o)))
    return max(outs, key=lambda o: (score(o), _dump(o)))


def pick_read(outs, left, need, v, cfg):
    """④ 다수결. 남은 표가 와도 found와 근거 조항 묶음이 안 바뀌면 합친 출력, 아니면 None."""
    yes = [o for o in outs if o.get("found")]
    no = [o for o in outs if not o.get("found")]
    if left and len(yes) < need and len(no) < need:
        return None
    if len(no) >= need or (not left and len(yes) <= len(no)):       # 과반이 「답할 수 없다」(반반이면 답하지 않는 쪽)
        return dict(min(no, key=_dump), _vote={"found": [bool(o.get("found")) for o in outs]})
    body = {}
    for c in v:
        body[c["label"]] = body.get(c["label"], "") + "\n" + c["text"]
    sets = [[lab for lab in dict.fromkeys(_ev_label(ev, v, body, cfg) for ev in o.get("evidence") or []) if lab] for o in yes]
    count = {}
    for labs in sets:
        for lab in labs:
            count[lab] = count.get(lab, 0) + 1
    every = (cfg["flow2_votes"] or {}).get("read_all")     # True면 「답한 표가 모두 든 조항만」(다 올 때까지 기다린다). 없으면 과반
    if left and (every or any(n < need <= n + left for n in count.values())) or left >= need:   # 아직 결과가 바뀔 수 있다
        return None
    need_now = need if left or len(outs) >= 2 * need - 1 else len(outs) // 2 + 1     # 표가 모자라게 끝났으면 온 표의 과반
    need_now = len(yes) if every else need_now
    major = [c["label"] for c in v if count.get(c["label"], 0) >= need_now]
    concl = [o.get("conclusion") for o in yes]
    order = sorted(range(len(yes)), key=lambda i: (-len(set(sets[i]) & set(major)) / (len(set(sets[i]) | set(major)) or 1),
                                                   -concl.count(concl[i]), _dump(yes[i])))
    rep = yes[order[0]]                                              # 근거 묶음이 다수결 결과와 가장 가까운 출력(같으면 결론이 다수인 쪽)
    vote = {"found": [bool(o.get("found")) for o in outs], "sets": sets, "kept": major}
    if not major:                                                    # 과반이 든 조항이 하나도 없으면 그 출력의 근거를 그대로 쓴다
        return dict(rep, _vote=vote)
    paren, evidence = cfg["flow2_version"] >= 3, []
    for lab in major:
        quotes = sorted({ev.get("quote", "").replace(DELEG_MARK, "") for o, labs in zip(yes, sets) if lab in labs
                         for ev in o.get("evidence") or [] if _ev_label(ev, v, body, cfg) == lab})
        ok = [q for q in quotes if quote_in(q, body[lab], paren=paren)]
        evidence.append({"label": lab, "quote": (ok or quotes)[0]})   # 원문에 있는 구절을 먼저. 하나도 없으면 ⑤가 버린다
    return dict(rep, evidence=evidence, _vote=vote)


def pick_check(outs, left, need):
    """⑥ 다수결: 과반이 notGrounded일 때만 거절. 남은 표가 와도 안 바뀌면 그쪽 출력, 아니면 None."""
    bad = [o for o in outs if _verdict(o) == "notGrounded"]
    good = [o for o in outs if _verdict(o) != "notGrounded"]
    votes = {"_vote": {"verdicts": [_verdict(o) for o in outs]}}
    if len(bad) >= need or (not left and len(bad) > len(good)):
        return dict(min(bad, key=_dump), **votes)
    if left and len(bad) + left >= need:
        return None
    return dict(min(good, key=lambda o: (_verdict(o) != "grounded", _dump(o))), **votes)


def _voted(st, cfg, step, one, n):
    """one(상태) → 출력을 n번 나란히 부르고 다수결로 하나를 돌려준다. 호출 기록 · 더 부른 기록은 온 표의 것만 st에 붙인다."""
    need = n // 2 + 1
    pick = {"analyze": lambda o, left: pick_slots(o, left, need),
            "read": lambda o, left: pick_read(o, left, need, st["_view"], cfg),
            "check": lambda o, left: pick_check(o, left, need)}[step]
    boxes = [{"calls": []} for _ in range(n)]
    pend = {_VOTE.submit(contextvars.copy_context().run, one, b): b for b in boxes}
    outs, err = [], None
    while pend:
        done, _ = wait(pend, timeout=_left(), return_when=FIRST_COMPLETED)
        if not done:
            raise upstage.DeadlineExceeded("다수결 호출이 마감 전에 안 끝남")
        for f in done:
            box = pend.pop(f)
            if f.exception() is not None:
                err = f.exception()
                continue
            outs.append(f.result())
            st["calls"].extend(box["calls"])
            if box.get("flow2"):
                _f2(st).setdefault("guard", []).extend(box["flow2"]["guard"])
        out = pick(outs, len(pend)) if outs else None
        if out is not None:
            return dict(out, _vote=dict(out.get("_vote") or {}, n=n, used=len(outs)))
    raise err


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

    def run():
        return {k: v for k, v in guarded(st, cfg, fn, "search").items() if k not in ("question", "calls")}
    st.update(_memoed(st, cfg, ["search", st["question"]], run) if cfg["flow2_memo"] else run())    # 꺼져 있으면(기본) 그대로 부른다
    laws = lawmap.pick_laws(st["_hits"]) if cfg["flow2_version"] >= 6 and not st["reason"] else []
    if laws:
        v = view(laws, cfg["chunk_unit"])
        box = {"calls": [], "_view": v}       # _view: 다수결(flow2_votes)이 조항 이름을 원문 조각에 맞출 때 쓴다
        user = _read_user(st["question"], v, cfg)
        st["_spec"] = (laws, box, _SPEC.submit(contextvars.copy_context().run, _ask, box, cfg, "read", user))


def analyze(st, cfg):
    """① 질문 분석: 답하지 않고 닫힌 값 칸만(solar 1번)."""
    _f2(st)["slots"] = _ask(st, cfg, "analyze", f"[질문]\n{st['question']}")


def route(st, cfg):
    """③ 조례 확정(코드만, 호출 0). 규칙과 근거 조항은 lawmap.py."""
    r = lawmap.route(st["question"], _f2(st).get("slots") or {}, st["_hits"], use_onto=cfg["flow2_ontology"],
                     mixed_ok=cfg["flow2_version"] >= 2, sentences=cfg["flow2_version"] >= 3,
                     place=cfg["flow2_place_scope"])
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
    if not out.get("found"):
        st["reason"] = pipeline.NOT_FOUND


def gate(st, cfg):
    """⑤ 구절 관문(코드만): 목록에 있는 조항 · 자치구 아님 · 구절이 그 조항 글에 글자 그대로 있음 → 인용."""
    v, out = st["_view"], st["_read"]
    if "_vote" in out:                       # 다수결(flow2_votes)을 켰을 때만 있다
        _f2(st).setdefault("vote", {})["read"] = out["_vote"]
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
    if "_vote" in out:                       # 다수결(flow2_votes)을 켰을 때만 있다
        _f2(st).setdefault("vote", {})["check"] = out["_vote"]
    if st["verdict"] == "notGrounded":
        st["reason"] = pipeline.REJECTED


# ---- 맡긴 내용을 묻는 질문의 답 살리기 (스위치 flow2_handed, 11-11) ----
# 업스테이지 답(11-11): 조문은 있는데 금액 · 세부를 정하지 않은 질문은 「확인 불가」가 아니다. 근거(위임) 조항을 인용하고 「조례에는 정해져 있지
# 않다」와 어디서 정하는지를 안내해야 하고, 「확인 불가」로 답하면 0점일 수 있다. 7판 ④는 그런 답을 쓰는데 ⑥이 「답이 확인할 수 없다고 적었다」
# (검사 프롬프트 규칙 5)로 거절한다. 그래서 ⑥이 거절했어도 아래 넷을 다 채우면 판정 전 답을 그대로 낸다(코드만, 모델 호출 수 그대로).
#  (가) 판정 전 답이 「조례에 정해져 있지 않다」 꼴이다(④ 프롬프트가 시킨 말: 「~는 이 조례에 정해져 있지 않아 …」).
#  (나) ⑤를 지난 근거 조항의 글에 조례가 스스로 맡기는 구절이 있다.
#  (다) 답 글도 누가 · 무엇으로 정하는지 말한다(「시장이 따로 정하도록 되어 있습니다」 꼴). 업스테이지 답이 말한 「어디서 확인하는지 안내」다.
#      (다)가 없던 첫 판은 dev 실측(11-11 11:43)에서 「~는 정해져 있지 않아 확인할 수 없습니다. 다만 제○조는 …」처럼 묻는 것과 다른 일을
#      맡기는 조항을 끌어온 답 둘을 살렸다(함정 하나 · 0점 답 하나). (다)를 넣으면 dev 12개 · 극한 2개 실행 기록에서 샌 함정 0 · 0점 답 0이다.
#  (라) 답 글이 6종 밖의 법령 · 조례 · 고시 이름을 「」로 들지 않는다. 들었다면 묻는 내용을 다른 법령으로 넘기는 꼴이고(예: 조례가 대상을
#      「다른 조례」에 따른 것으로만 적은 경우), 그 꼴의 정답은 업스테이지에 다시 묻는 중이라 7판 동작 그대로 둔다. 극한 실측(11-11 12:31)에서
#      (라)가 없으면 그 꼴 한 문항이 두 판에서 한 번씩 살아났다. 이름이 6종인지는 lawmap.name_kind로 가린다(별칭 포함).
# 맡기는 구절은 6종 조례 원문의 글투에서만 뽑았다: 「시장이 따로 정한다」 · 「시장이 별도로 정한다」 · 「시장이 정한다」 · 「구청장이 따로 정할 수 있다」 ·
# 「위원장이 정한다」 · 「협의하여 별도로 정한다」 · 「규칙으로 정한다」 · 「규칙이 정하는 바에」(528조각 가운데 38조각에 있다).
# 넣지 않은 것: 상위 법령으로 넘기는 구절(위 DELEG) · 다른 조례로 넘기는 구절(「…조례」로 따로 정한다) · 국가 고시(「…고시를 따른다」) —
# 이 꼴의 정답은 업스테이지에 다시 묻는 중이라 7판 동작 그대로 둔다. 「예산의 범위에서」도 넣지 않았다(7판 dev 기록 6개에 대어 보니 함정 하나가 샜다).
# (가)를 빼면 극한 세트 함정 3문항이 샌다(11-10 기록에 대어 봄, 흔들림-도구/replay_handed.py). 평가 문항의 글은 옮기지 않았다.
NOT_SET = re.compile(r"(?:정해져|정하여져|규정되어|명시되어)\s*있지\s*(?:않|아니)|(?:정하고|규정하고|명시하고)\s*있지\s*(?:않|아니)|정하지\s*(?:않|아니)")
HANDED = re.compile(r"(?:시장|구청장|위원장)\s*이\s*(?:따로|별도로)?\s*정(?:한다|하는|할\s*수|하여)|(?:따로|별도로)\s*정(?:한다|하는|할\s*수|하여)"
                    r"|규칙(?:으로|이)\s*정(?:한다|하는|하여)")
_NAMED = re.compile(r"「([^」]{2,60})」")
SAYS = re.compile(r"(?:시장|구청장|위원장)\s*이\s*(?:따로|별도로)?\s*정[하한할해합함했]|(?:따로|별도로)\s*정[하한할해합함했]|규칙(?:으로|이|에서)\s*정[하한할해합함했]")


# ---- 다른 법령으로 넘기는 꼴 (flow2_handed = "law", 11-11 저녁 업스테이지 2차 답) ----
# 2차 답: 6종 안에 질문을 다루는 조항이 있고 그 조항이 구체적인 내용을 다른 법령으로 넘기는 경우에도, 그 조항을 인용하고 「세부 내용은 해당
# 법령에서 정한다」고 안내하는 것이 정답이다(「확인 불가」는 정답이 아님). 그래서 "law"는 위 넷 가운데 (나)(다)(라)를 이렇게 넓힌다.
#  (나′)(다′) 답 글의 한 문장이 「그 법령 + 정한다 · 따른다 · 규정 · 확인」 꼴이고, 그 법령이 ⑤를 지난 근거 조항의 글에 글자 그대로 있다.
#        법령은 둘 중 하나로 든 것만 본다: 「」로 든 이름(「○○법」 · 6종이 스스로 드는 다른 서울시 조례) / 조문이 쓰는 줄임말과 조 번호(「법 제○조」 · 「영 제○조」).
#        6종 원문의 글투다: 「법 제○조」 74조각 · 「영 제○조」 17조각 · 「…법」「…법률」 77조각 · 「…조례」 20조각(521조각 중).
#        이름도 조 번호도 없이 「관련 법령에서 정합니다」라고만 쓴 답은 살리지 않는다(dev · 극한 기록에 대어 보니 함정 둘이 샜다).
#        그 문장은 「정해져 있지 않다」고 한 문장이거나 그 뒤 문장이어야 한다(받은 답의 순서: 조례에는 없다 → 그 법령에서 정한다). 앞 문장에서
#        든 법령은 묻는 것과 다른 일일 수 있다: 순서를 안 보면 dev · 극한 기록 26개에서 함정이 4번 더 샜다(국립공원을 도시공원으로 본 답 등).
#  (라′)  답이 든 6종 밖 법령은 모두 근거 조항 글에 있어야 한다(없으면 조례가 넘긴 것이 아니라 조례가 안 다루는 일이다).
#        6종이 들지도 않는 조례(자치구 · 다른 시 · 도의 조례 등, lawmap.name_kind가 「밖」)를 든 답은 살리지 않는다.
# (가)는 그대로다. 「스스로 맡기는 꼴」(True)의 조건은 바꾸지 않았고, "law"는 그것에 이 길을 더한 것이다.
_PTR = re.compile(r"(?<![가-힣])(?:법|영)\s*제\d+조(?:의\d+)?")
_STEM = re.compile(r"정하|정한|정합|정해|정했|따르|따릅|따라|따른|규정|확인|위임")
_SENT = re.compile(r"[^.?!]+[.?!]?")
HANDED_MODES = (False, True, "law")


def _squash(s):
    return "".join(s.split())


def handed_over(answer, chunks, law=False):
    """(가)(나)(다)(라)를 다 채우면 (조항 이름, 맡기는 구절), 아니면 None. law=True면 다른 법령으로 넘기는 꼴(위 설명)도 본다."""
    if not NOT_SET.search(answer or ""):
        return None
    kinds = [(n, lawmap.name_kind(n)[0]) for n in _NAMED.findall(answer)]
    outside = [n for n, k in kinds if k in ("인용", "법령") or n.endswith("고시")]
    if SAYS.search(answer) and not outside and not any(k == "밖" for _, k in kinds):
        for c in chunks:
            for m in HANDED.finditer(c["text"]):
                if "조례」로" not in c["text"][max(0, m.start() - 8):m.start()]:     # 다른 조례로 넘기는 구절은 뺀다
                    return c["label"], m.group(0)
    if not law or any(k == "밖" for _, k in kinds):
        return None
    body = [(c["label"], _squash(c["text"])) for c in chunks]
    if any(not any(_squash(n) in t for _, t in body) for n in outside):
        return None
    sents = _SENT.findall(answer)
    first = next(i for i, x in enumerate(sents) if NOT_SET.search(x)) if any(NOT_SET.search(x) for x in sents) else 0
    for sent in sents[first:]:               # 「정해져 있지 않다」고 한 문장이거나 그 뒤 문장만(앞 문장의 법령은 다른 일을 말한 것일 수 있다)
        if not _STEM.search(sent):
            continue
        for ref in [n for n in outside if n in sent] + [m.group(0) for m in _PTR.finditer(sent)]:
            for label, t in body:
                if _squash(ref) in t:
                    return label, ref
    return None


# check 본문은 그대로 두고 같은 이름으로 한 겹 싼다(STAGES 줄도 main 그대로). 스위치가 꺼져 있으면(기본) 위 check 그대로다.
_check_one = check


def check(st, cfg):      # noqa: F811
    """「질문 대조」 단계. ⑥(_check_one)을 그대로 부르고, 스위치 flow2_handed가 켜져 있으면 맡긴 내용을 묻는 질문의 답은 거절을 되돌린다."""
    _check_one(st, cfg)
    mode = cfg["flow2_handed"]
    if mode not in HANDED_MODES:
        raise ValueError(f"flow2_handed 값 {mode!r}: {HANDED_MODES} 가운데 하나여야 합니다")
    if mode and st["reason"] == pipeline.REJECTED:
        kept = set(_f2(st)["gate"]["kept"])
        hit = handed_over(st["draft"]["answer"], [c for c in st["_view"] if c["label"] in kept], law=mode == "law")
        if hit:
            st["reason"] = None
            _f2(st)["handed"] = {"label": hit[0], "phrase": hit[1]}      # 판정(verdict)은 notGrounded 그대로 남긴다
# ---- #83 답 첫머리에 결론 붙이기 (출력 직전, 코드만. 스위치 flow2_lead, 기본값 "off" = 7판과 같은 동작) ----
# 7판 dev 두 실행(11-10)에서 정답 열쇠가 「네 · 아니요」로 시작하는 문항의 답 가운데 그렇게 시작한 것은 66.7 · 68.3%였다(프롬프트로는
# 이미 시키고 있다). ④가 답과 함께 낸 결론 칸(read.conclusion)을 코드가 답 앞에 붙인다. 붙이지 않는 답은 셋이다.
# - 이미 「네 · 예 · 아니요 · 아니오」로 시작하는 답, 결론 칸이 「정보」이거나 빈 답.
# - 첫 물음(「?」로 끝나는 첫 문장, 없으면 질문 전체)에 묻는 말(몇 · 얼마 · 누가 …)이 있는 질문의 답. ④는 「몇 세부터 몇 세까지인가요?」 꼴
#   질문에도 결론 칸에 「네 · 아니요」를 적는다(같은 두 실행에서 결론 칸은 있는데 정답 열쇠가 「네 · 아니요」가 아닌 답이 58 · 51개).
#   그대로 붙이면 「네, 19세부터 39세까지입니다」 · 「아니요, 19세부터 …」 같은 답이 나간다. 묻는 말이 든 다른 낱말(「며칠씩」)의 질문도
#   안 붙이는 쪽으로 간다(7판과 같은 답). 재는 법: python3 eval/answer_stats.py <실행> --config <켠 판 설정>
# - 「확인 불가」로 시작하는 답. 글자 하나도 건드리지 않는다(앞에 낱말이 붙으면 출구 검사가 확인 불가 꼴로 맞추지 못한다).
LEAD = re.compile(r"(?:네|예|아니요|아니오)(?=[\s,.!]|$)")          # 답이 이미 결론 낱말로 시작한다(「예약」 · 「네트워크」는 아니다)
LEAD_JOIN = {"comma": ", ", "period": ". "}                          # 「네, …」로 잇기 · 「네. …」로 끊기
ASK_WORD = re.compile(r"몇|며칠|얼마|누가|누구|언제|어디|어떻게|어떤|어느|무엇|뭐|뭘|무슨|왜")
# 답 글에 샌 안쪽 말 「이 자료」(④에 보여 준 원문을 가리킨다)를 시민에게 보일 말로 바꾼다. 낱말만 바꾸고 뜻은 그대로 둔다.
# 조사가 그대로 이어지는 꼴만 바꾼다: 「이 자료에 · 에서 · 만으로」와 「이 자료로」(→ 「6종으로」). 그 밖의 꼴은 그대로 두고 재는 틀이 센다.
INNER = re.compile(r"(?<![가-힣])이 자료(?:(?=에|만)|(로))")     # 앞이 한글이면 「시장이 자료로」 같은 다른 말이다
INNER_TO = "서울시 조례 6종"


def lead(st, cfg):
    """출력 직전(#83): 마지막 검사를 지난 답의 안쪽 말을 바꾸고, 「네 · 아니요」로 답할 물음이면 ④의 결론 낱말을 앞에 붙인다.
    답 글만 바꾼다(인용 · 링크 · 시행일은 그대로). 판단 기록 flow2.lead에 붙인 낱말 · 안 붙인 까닭 · 바꾸기 전 답을 남긴다."""
    old = st["draft"]["answer"]
    if cfg["flow2_lead"] == "off" or old.lstrip().startswith("확인 불가"):
        return
    new = INNER.sub(lambda m: INNER_TO + ("으로" if m.group(1) else ""), old)
    word = (_f2(st).get("read") or {}).get("conclusion")
    ask = next((p for p in lawmap._SENT.split(st["question"]) if p.rstrip().endswith(("?", "？"))), st["question"])
    skip = ("이미 결론 낱말로 시작" if LEAD.match(new.lstrip()) else "결론 칸이 네 · 아니요가 아님" if word not in ("네", "아니요")
            else "첫 물음에 묻는 말이 있음" if ASK_WORD.search(ask) else None)
    if not skip:
        new = word + LEAD_JOIN[cfg["flow2_lead"]] + new.lstrip()
    _f2(st)["lead"] = {"word": None if skip else word, "skip": skip, "before": old if new != old else None}
    st["draft"] = dict(st["draft"], answer=new)


STAGES = [("검색", search), ("질문 분석", analyze), ("조례 확정", route), ("조례 읽기 · 답 쓰기", read),
          ("구절 관문", gate), ("질문 대조", check), ("답 첫머리", lead), ("출력", pipeline.output)]

# ---- PM 실험(11-11): 온톨로지로 근거 묶음 정리(cite.py). 스위치 flow2_cite가 None(기본값)이면 두 단계는 아무 일도 하지 않는다 ----
# STAGES 줄을 고치지 않고 이름으로 찾아 끼운다(같은 주기의 다른 실험이 그 줄에 단계를 더한다).
from . import cite  # noqa: E402  (cite는 flow를 함수 안에서만 부른다)
for _after, _stage in (("구절 관문", ("근거 고르기", cite.start)), ("질문 대조", ("근거 정리", cite.settle))):
    STAGES.insert([n for n, _ in STAGES].index(_after) + 1, _stage)


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
        # 흔들림 줄이기(flow2_votes): 같은 호출 세 번 → 결정만 다수결. 스위치가 꺼져 있으면(기본) 한 번만 부르고 기록도 그대로다
        other = next(c for c in chunks if c["label"] != target["label"] and len(c["text"]) > 30)
        oq = other["text"][:15]
        ok_ev, bad_ev, other_ev = ({"label": target["label"], "quote": quote}, {"label": target["label"], "quote": "원문에 없는 말"},
                                   {"label": other["label"], "quote": oq})
        rd = lambda found, ev, ans="네, 감면됩니다.": {"found": found, "check": "", "conclusion": "네", "answer": ans, "evidence": ev}
        ck = lambda v: {"reason": "", "asks": [{"ask": "경차 할인", "verdict": v}], "done": True}
        need = 2
        assert pick_check([ck("notGrounded"), ck("grounded")], 1, need) is None                       # 아직 모름 → 셋째를 기다림
        assert _verdict(pick_check([ck("grounded"), ck("notSure")], 1, need)) == "grounded"            # 둘이 통과면 셋째를 안 기다림
        assert _verdict(pick_check([ck("notGrounded"), ck("grounded"), ck("notGrounded")], 0, need)) == "notGrounded"
        assert _verdict(pick_check([ck("notGrounded"), ck("grounded"), ck("grounded")], 0, need)) == "grounded"   # 한 번의 거절로는 안 버림
        assert _verdict(pick_check([ck("notGrounded"), ck("grounded")], 0, 2)) == "grounded"           # 두 번 부르면: 둘 다 거절일 때만 거절
        v7 = [target, other]
        assert pick_read([rd(True, [ok_ev]), rd(True, [ok_ev, other_ev])], 1, need, v7, cfg7) is None  # 한쪽만 든 조항이 있다 → 기다림
        got = pick_read([rd(True, [ok_ev]), rd(True, [ok_ev])], 1, need, v7, cfg7)                      # 둘이 같으면 안 기다림
        assert [e["label"] for e in got["evidence"]] == [target["label"]]
        got = pick_read([rd(True, [ok_ev], "답 1"), rd(True, [bad_ev, other_ev], "답 2"), rd(True, [other_ev, ok_ev], "답 3")], 0, need, v7, cfg7)
        assert got["evidence"] == [ok_ev, other_ev] and got["answer"] == "답 2", got                   # 과반이 든 조항(원문 순서) · 원문에 있는 구절 · 근거가 같은 출력의 답
        assert pick_read([rd(True, [ok_ev]), rd(False, []), rd(False, [])], 0, need, v7, cfg7)["found"] is False
        assert pick_read([rd(True, [ok_ev]), rd(False, [])], 1, need, v7, cfg7) is None
        every = dict(cfg7, flow2_votes={"read": 3, "read_all": True})                                   # 「모두 든 조항만」
        three = [rd(True, [ok_ev, other_ev]), rd(True, [ok_ev, other_ev]), rd(True, [ok_ev])]
        assert [e["label"] for e in pick_read(three, 0, need, v7, cfg7)["evidence"]] == [target["label"], other["label"]]
        assert [e["label"] for e in pick_read(three, 0, need, v7, every)["evidence"]] == [target["label"]]
        assert pick_read(three[:2], 1, need, v7, every) is None and pick_read(three[:2], 1, need, v7, cfg7) is not None   # 모두: 셋째를 기다림
        got = pick_read([rd(True, [ok_ev]), rd(True, [other_ev]), rd(False, [])], 0, need, v7, cfg7)    # 과반이 든 조항이 없으면 한 출력의 근거 그대로
        assert got["found"] and len(got["evidence"]) == 1 and got["_vote"]["kept"] == []
        sl = lambda **kw: dict(slots, actor="시민", **kw)
        assert pick_slots([sl(), sl(law_guess="금연")], 1, need) is None
        assert pick_slots([sl(law_guess="금연"), sl(), sl(targets=["경형자동차"])], 0, need)["law_guess"] == "주차장"
        import threading
        seq, lock = {}, threading.Lock()

        def seq_chat(messages, cfg, calls=None, response_format=None):
            name = response_format["json_schema"]["name"]
            with lock:
                out = seq[name].pop(0) if seq.get(name) else plan[name]
            if calls is not None:
                calls.append({"model": "fake", "in": 1, "cached": 0, "out": 1, "sec": 0.0})
            return json.dumps(out, ensure_ascii=False)

        upstage.chat = seq_chat
        plan.update(question_slots=sl(), law_answer_quotes=rd(True, [ok_ev]), target_check=ck("grounded"))
        on = dict(cfg7, flow2_votes={"analyze": 3, "read": 3, "check": 3})
        qv = "경차를 공영주차장에 세우면 할인돼요?"
        seq.update(law_answer_quotes=[rd(True, [bad_ev, other_ev]), rd(True, [ok_ev]), rd(True, [ok_ev])],
                   target_check=[ck("notGrounded"), ck("grounded"), ck("grounded")])
        r, t = pipeline.answer(qv, on)
        assert r["citation"] == [target["label"]] and t["verdict"] == "grounded", (t["reason"], t["flow2"].get("vote"))
        assert t["flow2"]["vote"]["read"]["kept"] == [target["label"]] and t["flow2"]["vote"]["check"]["n"] == 3
        assert t["flow2"]["slots"]["_vote"]["n"] == 3 and len(t["calls"]) >= 6
        seq.update(law_answer_quotes=[rd(True, [bad_ev, other_ev])], target_check=[ck("notGrounded")])
        r, t = pipeline.answer(qv, cfg7)                 # 꺼 두면: 첫 출력 하나로 정한다(다른 조항 · 한 번의 거절로 확인 불가)
        assert r == contract.UNKNOWN and t["reason"] == pipeline.REJECTED and t["draft"]["citation"] == [other["label"]]
        assert "vote" not in t["flow2"] and [c["stage"] for c in t["calls"]] == ["질문 분석", "조례 읽기 · 답 쓰기", "질문 대조"]
        seq.clear()
        seq.update(target_check=[ck("notGrounded"), ck("notGrounded"), ck("grounded")])
        assert pipeline.answer(qv, on)[1]["reason"] == pipeline.REJECTED          # 과반이 거절이면 거절
        seq.clear()
        assert config.DEFAULTS["flow2_votes"] is None
        # 같은 글에는 같은 출력(flow2_memo): 모델이 두 번째에 다른 출력을 내도 같은 문의에는 같은 답. 꺼 두면(기본) 매번 부른다
        import os
        import tempfile
        memo = os.path.join(tempfile.mkdtemp(), "memo.jsonl")
        keep = dict(cfg7, flow2_memo=memo)
        two = lambda: seq.update(law_answer_quotes=[rd(True, [ok_ev], "첫 답"), rd(True, [other_ev], "둘째 답")])
        two()
        r1, t1 = pipeline.answer(qv, keep)
        r2, t2 = pipeline.answer(qv, keep)
        assert r1 == r2 and r1["answer"] == "첫 답" and [c.get("kind") for c in t2["calls"]] == ["memo"] * 4, (r1, r2)
        assert [c["stage"] for c in t2["calls"]] == ["검색", "질문 분석", "조례 읽기 · 답 쓰기", "질문 대조"] and upstage.cost_usd(t2["calls"]) == 0
        _MEMO.clear()                                    # 프로세스를 다시 띄운 것처럼: 파일에서 읽어 같은 답
        assert pipeline.answer(qv, keep)[0] == r1 and pipeline.answer(qv + " ", keep)[0] != r1   # 글자가 다르면 다른 문의다
        seq.clear()
        two()
        assert pipeline.answer(qv, cfg7)[0]["answer"] == "첫 답" and pipeline.answer(qv, cfg7)[0]["answer"] == "둘째 답"   # 꺼 두면 바뀐다
        seq.clear()
        # 같은 문의 둘이 동시에 와도 모델은 한 번씩만 부르고 답이 같다(먼저 부른 쪽을 기다린다)
        n_call = []

        def slow_chat(messages, cfg, calls=None, response_format=None):
            n_call.append(response_format["json_schema"]["name"])
            time.sleep(0.05)
            return seq_chat(messages, cfg, calls, response_format)

        upstage.chat = slow_chat
        seq.update(law_answer_quotes=[rd(True, [ok_ev], "한 답"), rd(True, [other_ev], "다른 답")])
        qc = qv + " 동시에"
        got = list(ThreadPoolExecutor(2).map(lambda _: pipeline.answer(qc, dict(keep, flow2_memo=":memory:"))[0], range(2)))
        assert got[0] == got[1] and sorted(n_call) == ["law_answer_quotes", "question_slots", "target_check"], (got, n_call)
        upstage.chat = seq_chat
        seq.clear()
        assert config.DEFAULTS["flow2_memo"] is None
        # 맡긴 내용을 묻는 질문(flow2_handed): ⑥이 거절해도 답이 「정해져 있지 않다」 꼴이고 근거 조항에 맡기는 구절이 있으면 답을 낸다
        allc = retrieve.load("paragraph")[0]
        hand = next(c for c in allc if "시장이 따로 정한다" in c["text"])
        assert sum(bool(handed_over("정해져 있지 않고 시장이 따로 정합니다", [c])) for c in allc) == 38           # 6종 원문 528조각 가운데 이 꼴이 든 조각(원문이 바뀌면 다시 본다)
        say = "그 금액은 조례에 정해져 있지 않습니다. 시장이 따로 정하도록 되어 있습니다."
        assert handed_over(say, [hand]) == (hand["label"], "시장이 따로 정한다")
        assert handed_over("네, 감면됩니다.", [hand]) is None                                  # (가) 답이 그 꼴이 아니면 안 살린다
        assert handed_over("그 금액은 조례에 정해져 있지 않아 확인할 수 없습니다. 다만 제3조는 다른 일을 정합니다.", [hand]) is None   # (다) 누가 정하는지 말하지 않는 답
        assert handed_over(say, [target]) is None and handed_over(say, [ban]) is None          # (나) 맡기는 구절이 없는 조항 · 상위 법령으로 넘기는 조항
        assert handed_over(say + " 대상은 「서울특별시 출산 및 양육지원에 관한 조례」에 따릅니다.", [hand]) is None       # (라) 답이 6종 밖 조례를 든다
        assert handed_over(say + " 기준은 「동물보호법」에 있습니다.", [hand]) is None and handed_over(say + " 「주차장 조례」와 「거주자우선주차」 얘기입니다.", [hand])
        assert handed_over(say, [{"label": "x", "text": "…은 「서울특별시교육청 학교 주차장 관리에 관한 조례」로 따로 정한다."}]) is None   # 다른 조례로
        assert handed_over(say, [{"label": "x", "text": "세부 기준은 농림축산식품부 고시를 따른다."}]) is None
        assert handed_over(say, [{"label": "x", "text": "시장은 금연구역으로 지정할 수 있다. 수탁자를 선정한다. 예산의 범위에서 지원할 수 있다."}]) is None
        hq = hand["text"][hand["text"].index("시장이 따로 정한다") - 12:][:22]
        plan.update(question_slots=sl(), law_answer_quotes=dict(rd(True, [{"label": hand["label"], "quote": hq}], say), conclusion="정보"),
                    target_check=ck("notGrounded"))
        qh = "그 금액은 얼마예요?"
        plan["question_slots"] = dict(sl(), law_guess=next(k for k in prompts.LAW_KEYS if k in hand["law"]))
        r, t = pipeline.answer(qh, cfg7)
        assert r == contract.UNKNOWN and t["reason"] == pipeline.REJECTED and "handed" not in t["flow2"], (t["reason"], t["flow2"].get("gate"))
        r, t = pipeline.answer(qh, dict(cfg7, flow2_handed=True))
        assert r["citation"] == [hand["label"]] and r["answer"] == say and t["verdict"] == "notGrounded" and t["flow2"]["handed"]["label"] == hand["label"]
        plan["law_answer_quotes"] = dict(plan["law_answer_quotes"], answer="네, 됩니다.")       # 답이 그 꼴이 아니면 거절 그대로
        assert pipeline.answer(qh, dict(cfg7, flow2_handed=True))[1]["reason"] == pipeline.REJECTED
        assert config.DEFAULTS["flow2_handed"] is False
        # flow2_handed = "law": 다른 법령으로 넘기는 꼴도 살린다(2차 답). True의 동작은 그대로다
        fine = next(c for c in allc if c["label"].endswith("도시공원 조례 제23조 제1항"))
        kids = next(c for c in allc if "「서울특별시 출산 및 양육지원에 관한 조례」" in c["text"])
        up = "과태료 금액은 이 조례에 정해져 있지 않습니다. 제23조제1항은 과태료를 부과하는 기준이 영 제51조제1항 별표 4와 같다고 정합니다."
        assert handed_over(up, [fine]) is None and handed_over(up, [fine], law=True) == (fine["label"], "영 제51조")
        other_law = "다자녀의 기준은 이 조례에 정해져 있지 않습니다. 감면 대상은 「서울특별시 출산 및 양육지원에 관한 조례」에 따른 다자녀 가족으로 규정합니다."
        assert handed_over(other_law, [kids]) is None and handed_over(other_law, [kids], law=True)[0] == kids["label"]
        assert handed_over(other_law, [fine], law=True) is None                                  # (라′) 답이 든 법령이 근거 조항 글에 없다
        assert handed_over("그 요금은 이 조례에 정해져 있지 않습니다. 「서울특별시 강남구 주차장 설치 및 관리 조례」에서 정합니다.", [kids, fine], law=True) is None   # 자치구 조례
        assert handed_over("그 금액은 이 조례에 정해져 있지 않습니다. 관련 법령에서 정합니다.", [fine], law=True) is None       # 이름도 조 번호도 없다
        assert handed_over("네, 영 제51조제1항 별표 4와 같다고 정합니다.", [fine], law=True) is None                          # (가) 답 꼴이 아니다
        assert handed_over("기준은 영 제51조제1항 별표 4와 같다고 정합니다. 그런데 주차 요금은 이 조례에 정해져 있지 않습니다.", [fine], law=True) is None   # 법령 문장이 앞에만 있다
        assert handed_over(say, [hand], law=True) == handed_over(say, [hand])                    # 스스로 맡기는 꼴은 두 값이 같다
        fq = fine["text"][fine["text"].index("과태료를 부과하는 기준"):][:22]
        plan.update(question_slots=dict(sl(), law_guess="도시공원"), target_check=ck("notGrounded"),
                    law_answer_quotes=dict(rd(True, [{"label": fine["label"], "quote": fq}], up), conclusion="정보"))
        ql = "공원에서 그 일을 하면 과태료가 얼마예요?"
        assert pipeline.answer(ql, dict(cfg7, flow2_handed=True))[1]["reason"] == pipeline.REJECTED
        r, t = pipeline.answer(ql, dict(cfg7, flow2_handed="law"))
        assert r["citation"] == [fine["label"]] and t["flow2"]["handed"] == {"label": fine["label"], "phrase": "영 제51조"}, (t["reason"], t["flow2"].get("gate"))
        assert pipeline.answer(ql, dict(cfg7, flow2_handed="yes"))[1]["reason"] == pipeline.ERROR      # 모르는 값은 멈춘다
        # #83 답 첫머리(flow2_lead): 끄면 7판 그대로, 켜면 답 글만 바뀐다(인용 · 링크 · 시행일은 같다). 문장은 원문을 보고 새로 썼다
        # (주차장 조례 제7조 경형자동차 100분의 50 · 도시공원 조례 이용료 반환 「사용일 7일 전까지 취소」 · 청년 기본 조례 제3조 19세 이상 39세 이하)
        q, ans = "경차를 공영주차장에 세우면 할인돼요?", "경형자동차는 주차요금의 100분의 50을 할인받을 수 있습니다."
        plan.update(question_slots=dict(slots, actor="시민"),
                    law_answer_quotes={"found": True, "check": "", "conclusion": "네", "answer": ans,
                                       "evidence": [{"label": target["label"], "quote": quote}]},
                    target_check={"reason": "", "asks": [{"ask": "경차 할인", "verdict": "grounded"}], "done": True})
        cfg83 = dict(cfg7, flow2_lead="comma")
        (r0, t0), (r, t) = pipeline.answer(q, cfg7), pipeline.answer(q, cfg83)
        assert r0["answer"] == ans and "lead" not in t0["flow2"], r0
        assert r == dict(r0, answer="네, " + ans) and t["flow2"]["lead"] == {"word": "네", "skip": None, "before": ans}, (r, t["flow2"])
        assert pipeline.answer(q, dict(cfg83, flow2_lead="period"))[0]["answer"] == "네. " + ans
        plan["law_answer_quotes"] = dict(plan["law_answer_quotes"], found=False)       # 확인 불가로 끝난 문항은 이 단계에 오지 않는다
        r, t = pipeline.answer(q, cfg83)
        assert r == contract.UNKNOWN and "lead" not in t["flow2"] and "답 첫머리" not in t["steps"], t["reason"]

        def led(answer, word, question=q, how="comma"):
            st = {"question": question, "draft": {"answer": answer, "citation": [target["label"]]}, "flow2": {"read": {"conclusion": word}}}
            lead(st, dict(cfg83, flow2_lead=how))
            return st["draft"]
        for same, word in (("확인 불가", "네"), ("확인 불가: 그 내용은 이 자료에 없습니다.", "아니요"),      # 확인 불가 답은 글자 하나도
                           ("네, 할인받을 수 있습니다.", "네"), ("아니요. 할인 대상이 아닙니다.", "네"), ("예, 할인됩니다.", "아니요"),   # 이미 시작
                           (ans, "정보"), (ans, None), (ans, "")):                                # 결론 칸이 「정보」 · 빈칸
            assert led(same, word) == {"answer": same, "citation": [target["label"]]}, (same, word)
        assert led(ans, "아니요", how="off")["answer"] == ans
        assert led(ans, "네", "경형자동차는 공영주차장 요금을 얼마나 할인받아요?")["answer"] == ans          # 묻는 말이 있는 물음
        assert led(ans, "네", "경형자동차도 할인 대상이에요? 할인율은 얼마예요?")["answer"] == "네, " + ans   # 첫 물음만 본다
        assert led(ans, "네", "제 차는 경형자동차예요. 공영주차장 요금 할인 대상인지 알려 주세요.")["answer"] == "네, " + ans
        assert led("예약한 날에 취소하면 이용료를 모두 돌려받습니다.", "네", "공원 시설을 예약한 날 바로 취소해도 이용료를 다 돌려받나요?")["answer"] \
            == "네, 예약한 날에 취소하면 이용료를 모두 돌려받습니다."                                  # 「예약」은 결론 낱말 「예」가 아니다
        assert led("마흔 살은 39세 이하가 아니라 청년에 들지 않습니다.", "아니요", "마흔 살도 청년 정책 대상인가요?")["answer"].startswith("아니요, 마흔")
        assert led("할인율은 이 자료에 없습니다. 이 자료만으로는 알 수 없고 이 자료로는 확인할 수 없습니다.", "정보")["answer"] == \
            "할인율은 서울시 조례 6종에 없습니다. 서울시 조례 6종만으로는 알 수 없고 서울시 조례 6종으로는 확인할 수 없습니다."
        assert led("시장이 자료로 확인합니다. 예전 자료에 나온 조 번호와 다릅니다.", "정보")["answer"].count("자료") == 2       # 다른 「자료」는 그대로
        assert contract.finalize(dict(led("확인 불가", "네"), source_url="", effective_date=""), cfg83) == contract.UNKNOWN
        assert [n for n, _ in STAGES][-2:] == ["답 첫머리", "출력"] and config.DEFAULTS["flow2_lead"] == "off"
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
