"""쉬운 말로 다듬기 (설정 flow2_plain, PM 11-14): ⑥을 지난 답 글을 상담사가 전화로 읽어 줄 짧고 쉬운 말로 한 번 더 쓴다.

왜: 11-14 점검에서 낼 판 답이 평균 165자, 조문을 20자 넘게 옮긴 문장 26%, 답 글에 조 번호 36%였다(특강 예시 답은 24~35자).
어떻게: 「구절 관문」 뒤에 호출 하나(프롬프트 w1)를 ⑥과 나란히 미리 부르고(start), 「근거 정리」 뒤에 받아 답 글만 바꾼다(settle).
- 인용 · 링크 · 시행일과 답함 / 확인 불가는 건드리지 않는다. ⑥이 거절한 문항은 이 단계에 오지 않는다(미리 부른 호출은 버린다).
- 새 답이 아래(accept)를 하나라도 어기면 버리고 원래 답을 낸다: 숫자가 원래 답 · 근거 조문에 없음, 결론 낱말(네 · 아니요)이 바뀜,
  「조례에 정해져 있지 않다」 안내가 사라짐, 원래 답보다 길어짐(150자까지는 봐줌). 늦거나 깨져도 원래 답을 낸다.
- 판단 기록 flow2.plain에 판 이름 · 바꾸기 전 답 · 버린 까닭을 남긴다.

스스로 시험(키 없이): python -m engine.flow2.plain --selftest
"""
import contextvars
import json
import re
from concurrent.futures import TimeoutError as FutureTimeout

from .. import upstage
from . import lawmap, prompts

WAIT = 12            # 미리 부른 호출을 「근거 정리」 뒤에 기다리는 초(넘으면 원래 답)
LONG = 150           # 원래 답보다 길어도 이 글자 수까지는 받는다(짧은 원래 답에 확인하는 곳 안내가 붙는 경우)
EXTRA_NUMS = {"120"}  # 프롬프트가 붙이게 한 안내(「120다산콜」)의 숫자
# 「조례에 정해져 있지 않다」 꼴(eval/answer_stats.py NOT_SET과 같은 낱말 + flow.NOT_SET)
GRAY = re.compile(r"(?:정해져|정하여져|규정되어|규정돼|명시되어|명시돼|적혀|나와) 있지 (?:않|아니)|(?:정하고|규정하고|명시하고) 있지 (?:않|아니)"
                  r"|정하지 (?:않|아니)|(?:조례|조문|자료|6종)에는? 없")
LEAD = re.compile(r"^\s*(네|예|아니요|아니오)(?=[\s,.!]|$)")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(만|천)?")


def nums(text, every=True):
    """글 속 숫자. 쉼표는 지운다. 「10만」 · 「5천」은 곱한 값. every=True(원래 글 쪽)면 곱하기 전 숫자도 넣는다."""
    out = set()
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).replace(",", "")
        n = re.match(r"[\d.]+", raw).group(0)
        if m.group(1):
            v = float(n) * (10000 if m.group(1) == "만" else 1000)
            out.add(str(int(v)) if v == int(v) else str(v))
            if every:
                out.add(n)
        else:
            out.add(n)
    return out


def _word(w):
    return {"예": "네", "아니오": "아니요"}.get(w, w)


def conclusion(st):
    """w1에 줄 결론 낱말. 답 첫머리(flow.lead)가 붙이는 경우와 같은 때만 「네 · 아니요」, 그 밖은 「정보」."""
    from . import flow
    word = (flow._f2(st).get("read") or {}).get("conclusion")
    q = st["question"]
    ask = next((p for p in lawmap._SENT.split(q) if p.rstrip().endswith(("?", "？"))), q)
    return word if word in ("네", "아니요") and not flow.ASK_WORD.search(ask) else "정보"


def accept(new, old, word, texts):
    """새 답을 써도 되면 None, 아니면 버린 까닭."""
    if not isinstance(new, str) or not new.strip():
        return "빈 답"
    new = new.strip()
    if new.startswith("확인 불가"):
        return "확인 불가로 바꿈"
    if len(new) > max(len(old), LONG):
        return "더 길어짐"
    extra = nums(new, every=False) - nums(old) - nums(" ".join(texts)) - EXTRA_NUMS
    if extra:
        return f"없던 숫자 {sorted(extra)}"
    a, b = LEAD.match(new), LEAD.match(old)
    if (b and a and _word(a.group(1)) != _word(b.group(1))) or (word in ("네", "아니요") and a and _word(a.group(1)) != word):
        return "결론 낱말이 바뀜"
    if GRAY.search(old) and not GRAY.search(new):
        return "「정해져 있지 않다」 안내가 빠짐"
    return None


def user(st, word):
    from . import flow
    kept = set(flow._f2(st)["gate"]["kept"])
    used = [c for c in st["_view"] if c["label"] in kept]
    return (f"[질문]\n{st['question']}\n\n[결론]\n{word}\n\n[초안]\n{st['draft']['answer']}\n\n"
            f"[근거]\n{flow.context(used)}"), [c["text"] for c in used]


def _ask(box, cfg, text):
    from . import flow
    _, system, schema = prompts.pick(cfg, "plain")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]

    def run():
        return flow.guarded(box, cfg, lambda calls: json.loads(upstage.chat(messages, cfg, calls, response_format=schema)), "plain")
    out = flow._memoed(box, cfg, ["plain", system, text], run) if cfg.get("flow2_memo") else run()
    return out.get("answer")


def start(st, cfg):
    """「근거 고르기」 뒤: 다듬기 호출을 ⑥과 나란히 돌게 미리 부른다."""
    if not cfg["flow2_plain"]:
        return
    from . import flow
    word = conclusion(st)
    text, texts = user(st, word)
    box = {"calls": []}
    st["_plain"] = (word, texts, box, flow._SPEC.submit(contextvars.copy_context().run, _ask, box, cfg, text))


def settle(st, cfg):
    """「근거 정리」 뒤: 받은 새 답을 accept로 본 뒤 답 글만 바꾼다. 무엇이 잘못돼도 원래 답이 나간다."""
    if not cfg["flow2_plain"]:
        return
    from . import flow
    word, texts, box, fut = st.pop("_plain")
    old = st["draft"]["answer"]
    rec = flow._f2(st)["plain"] = {"prompt": prompts.PLAIN_V, "word": word, "before": old}
    try:
        left = flow._left()
        new = fut.result(timeout=WAIT if left is None else max(0.0, min(WAIT, left - 2)))
        st["calls"].extend(box["calls"])
        if box.get("flow2"):
            flow._f2(st).setdefault("guard", []).extend(box["flow2"]["guard"])
        rec["drop"] = accept(new, old, word, texts)
    except FutureTimeout:
        rec["drop"] = "늦음"
    except Exception as e:  # noqa: BLE001  이 단계의 오류로 답을 잃지 않는다
        rec["drop"] = type(e).__name__
    if not rec["drop"]:
        st["draft"] = dict(st["draft"], answer=new.strip())


def selftest():
    old = "네, 장애인 주차요금은 감면됩니다. 장애인자동차표지를 붙이고 장애인이 타면 주차요금의 100분의 80을 할인합니다."
    assert accept("네, 장애인이 타면 80% 할인됩니다.", old, "네", []) is None
    assert accept("아니요, 할인되지 않습니다.", old, "네", []) == "결론 낱말이 바뀜"
    assert accept("네, 90% 할인됩니다.", old, "네", []) == "없던 숫자 ['90']"
    assert accept("확인 불가", old, "네", []) == "확인 불가로 바꿈" and accept(" ", old, "네", []) == "빈 답"
    assert accept("네. " + "가" * 200, old, "네", []) == "더 길어짐"
    assert accept("과태료는 10만 원입니다.", "과태료는 100,000원이다.", "정보", []) is None              # 쉼표 · 「만」을 같은 값으로
    assert accept("과태료는 1만 원입니다.", "과태료는 100,000원이다.", "정보", []) == "없던 숫자 ['10000']"
    assert accept("요금은 500원입니다.", "요금은 별표 1과 같다.", "정보", ["5분당 500"]) is None             # 근거 조문의 숫자는 된다
    gray = "청년 월세 지원 금액은 이 조례에 정해져 있지 않습니다. 시장은 월세 보조 방안을 수립·시행하여야 합니다."
    assert accept("금액은 조례에 정해져 있지 않습니다. 서울시 공고나 120다산콜에서 확인할 수 있습니다.", gray, "정보", []) is None
    assert accept("서울시가 월세를 지원합니다.", gray, "정보", []) == "「정해져 있지 않다」 안내가 빠짐"
    assert nums("1만 5천 원, 10,000원 · 100분의 80") == {"10000", "1", "5000", "5", "100", "80"}
    print("plain selftest ok")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        print("쓰는 법: python -m engine.flow2.plain --selftest")
