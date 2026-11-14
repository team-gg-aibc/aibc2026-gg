"""출력 꼴: 대회 응답은 4칸 JSON(answer · citation · source_url · effective_date).

citation · source_url · effective_date는 코드가 조각 라벨과 원문 정보에서 채운다(모델이 쓰지 않음).

#22 마지막 출구 검사(동욱):
- guard(resp): 서버가 늘 거는 꼴 검사. 네 칸 · 칸 자료형 · 확인 불가 꼴 · 링크 · 시행일 꼴이 맞지 않으면 확인 불가로 바꾼다.
  흐름이 낸 정상 응답은 그대로 지나간다(점수에 영향 없음).
- finalize(resp, cfg): 스위치 exit_check를 켜면 흐름 끝에서 건다. 어중간한 답을 둘 중 하나로 맞추고, 색인에 있는 라벨(6종 조 · 항 · 별표)만
  남기고, 겹침을 빼고, 상한(max_citations)을 지키고, 링크 · 시행일은 첫 인용 조례의 원문 정보로 다시 채운다.
- 스스로 시험: python -m engine.contract --selftest (키 없이, CI에서 돈다)
"""
import re
from functools import lru_cache
from pathlib import Path

UNKNOWN = {"answer": "확인 불가", "citation": [], "source_url": "", "effective_date": ""}
FIELDS = tuple(UNKNOWN)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 11-14(설정 unknown_guide): 「확인 불가」 뒤에 붙이는 안내 한 줄. 11-11 받은 답: 「확인 불가」로 시작하고 인용이 비면 뒤에 안내를 붙여도
# 정답이고 답변 품질에 도움이 된다. 모델이 쓴 글은 붙지 않는다: 확인 불가 꼴로 인정하는 답 글은 아래 고정 글뿐이다(guard).
# 한 줄로 둔다: 120다산콜은 서울시 · 25개 자치구 · 유관기관 문의를 받는다(docs/PRD.md 출처 표). 까닭별로 나눈 첫 판은 ①이 나라 법령 일(그린벨트)도
# 「다른 시도」로 적어 「자치구나 다른 시·도」 안내가 맞지 않게 붙었다.
# 「조항이 없다」고 단정하지 않는다: 확인 불가는 마감 · 오류 · 마지막 검사의 거절로도 나온다(그때는 6종에 조항이 있을 수 있다, GG비서 리뷰 P1 11-14).
GUIDES = {"default": "서울시 조례 6종에서 이 질문의 답을 찾지 못했습니다. 다른 법령이나 자치구가 정하는 일일 수 있으니 서울시 120다산콜에 문의해 주세요."}
UNKNOWN_ANSWERS = {UNKNOWN["answer"], *(f"{UNKNOWN['answer']}. {g}" for g in GUIDES.values())}


def unknown(guide=None):
    """확인 불가 응답. guide(GUIDES의 열쇠)를 주면 안내 한 줄을 붙인다. 인용 목록은 새로 만든다(고쳐도 UNKNOWN이 바뀌지 않게)."""
    return {**UNKNOWN, "answer": f"{UNKNOWN['answer']}. {GUIDES[guide]}" if guide else UNKNOWN["answer"], "citation": []}


def build(answer, used):
    """used: 답에 쓴 조각들(순서대로). 인용은 순서를 지키며 겹침을 뺀다. 링크 · 시행일은 첫 조각의 조례 것."""
    citation = list(dict.fromkeys(h["label"] for h in used))
    first = used[0]
    return {"answer": answer, "citation": citation,
            "source_url": first["source_url"], "effective_date": first["effective_date"]}


def is_unknown(resp):
    """킷 꼴 확인 불가, 또는 그 뒤에 GUIDES 안내 한 줄을 붙인 꼴(나머지 세 칸은 킷과 같다)."""
    return isinstance(resp, dict) and resp.get("answer") in UNKNOWN_ANSWERS and {**resp, "answer": UNKNOWN["answer"]} == UNKNOWN


def guard(resp):
    """꼴만 본다: 맞으면 그대로, 아니면 확인 불가. 확인 불가로 시작하는 답은 킷의 꼴(또는 정해 둔 안내를 붙인 꼴)로 맞춘다."""
    if is_unknown(resp):
        return resp
    if not isinstance(resp, dict) or set(resp) != set(FIELDS):
        return unknown()
    a, c, u, d = (resp[k] for k in FIELDS)
    if not (isinstance(a, str) and isinstance(c, list) and all(isinstance(x, str) for x in c)
            and isinstance(u, str) and isinstance(d, str)):
        return unknown()
    if not a.strip() or a.strip().startswith("확인 불가") or not c:
        return unknown()
    if not u.startswith("http") or not DATE.fullmatch(d):
        return unknown()
    return resp


@lru_cache(maxsize=None)
def sources(unit):
    """색인 라벨 → (원문 링크, 시행일). 이 목록에 있는 라벨만 인용으로 나간다(6종 조 · 항 · 별표)."""
    from . import retrieve
    out = {}
    for ch in retrieve.load(unit)[0]:
        out.setdefault(ch["label"], (ch["source_url"], ch["effective_date"]))
    return out


def finalize(resp, cfg):
    """마지막 출구 검사(exit_check). 돌려주는 것은 늘 guard를 지나는 꼴이다."""
    if is_unknown(resp):
        return resp
    if not isinstance(resp, dict):
        return unknown()
    a, c = resp.get("answer"), resp.get("citation")
    if not isinstance(a, str) or not a.strip() or a.strip().startswith("확인 불가"):
        return unknown()                       # 「확인 불가」로 시작하면 인용이 있어도 확인 불가 꼴로
    allowed = sources(cfg["chunk_unit"])
    cites = [x for x in dict.fromkeys(c if isinstance(c, list) else []) if isinstance(x, str) and x in allowed]
    if cfg.get("max_citations"):
        cites = cites[:cfg["max_citations"]]
    if not cites:
        return unknown()                       # 인용 없이 답한 글은 확인 불가로 (인용 없음은 0점, 함정이면 지어낸 답)
    url, date = allowed[cites[0]]
    return guard({"answer": a.strip(), "citation": cites, "source_url": url, "effective_date": date})


# ---- 스스로 시험 ----
def selftest():
    import asyncio
    import json
    import tempfile
    import threading
    import time

    from . import config, server, upstage

    # 가짜 업스테이지는 답 쓰기 한 번(근거 번호 고르기)만 흉내 낸다. DEFAULTS에 채택 실험이 켜져도 그 길로 시험한다(#24 먼저 추리기는 끔).
    cfg = dict(config.load(), exit_check=True, max_citations=4, select_mode="direct")
    labels = list(sources(cfg["chunk_unit"]))
    a, b, c, d, e = labels[:5]
    url, date = sources(cfg["chunk_unit"])[a]
    ok = {"answer": "네, 됩니다.", "citation": [a], "source_url": url, "effective_date": date}

    # 1) 꼴 검사: 정상은 그대로, 깨진 답은 확인 불가
    assert guard(ok) is ok and guard(unknown()) == UNKNOWN
    for bad in (None, [], "확인 불가", {"answer": "네"}, dict(ok, extra=1), dict(ok, citation=a), dict(ok, citation=[1]),
                dict(ok, source_url="law.go.kr"), dict(ok, effective_date="2026.10.01"), dict(ok, citation=[]),
                dict(ok, answer=""), dict(ok, answer="확인 불가: 조례에 없음"), dict(unknown(), citation=[a]),
                dict(unknown(), answer="확인 불가. 이 내용은 모델이 지어낸 법에서 정합니다."), dict(unknown("default"), citation=[a]),
                dict(unknown("default"), source_url=url)):
        assert guard(bad) == UNKNOWN, bad
    # 11-14: 정해 둔 안내를 붙인 확인 불가는 그대로 나간다(킷 채점: 「확인 불가」로 시작 + 빈 인용)
    for key in GUIDES:
        g = unknown(key)
        assert guard(g) is g and is_unknown(g) and g["answer"].startswith("확인 불가. ") and g["citation"] == [] and g != UNKNOWN
    assert is_unknown(UNKNOWN) and not is_unknown(ok) and not is_unknown("확인 불가")
    u = unknown()
    u["citation"].append("x")
    assert UNKNOWN["citation"] == []

    # 2) 마지막 출구: 어중간한 답 맞추기 · 목록 밖 라벨 빼기 · 겹침 · 상한 · 링크 · 시행일 다시 채우기
    assert finalize(ok, cfg) == ok
    assert finalize(dict(ok, citation=[a]), dict(cfg, exit_check=True)) == ok
    assert finalize(dict(ok, answer="확인 불가입니다", citation=[a]), cfg) == UNKNOWN
    assert finalize(dict(ok, citation=[]), cfg) == UNKNOWN
    assert finalize(dict(ok, citation=["서울특별시 강남구 주차장 조례 제3조", "없는 조례 제1조"]), cfg) == UNKNOWN
    r = finalize(dict(ok, citation=["없는 조례 제1조", b, b, a, c, d, e], source_url="", effective_date="?"), cfg)
    assert r["citation"] == [b, a, c, d] and (r["source_url"], r["effective_date"]) == sources(cfg["chunk_unit"])[b]
    assert len(finalize(dict(ok, citation=[a, b, c, d, e]), dict(cfg, max_citations=None))["citation"]) == 5
    assert finalize({"answer": "네", "citation": [a]}, cfg)["citation"] == [a]       # 칸이 빠져도 코드가 채운다
    assert finalize("깨진 JSON", cfg) == UNKNOWN and finalize(dict(ok, answer=7), cfg) == UNKNOWN

    # 3) 가짜 업스테이지
    class Err(Exception):
        def __init__(self, status):
            super().__init__(f"Error code: {status}")
            self.status_code = status

    class Fake:
        """mode: ok(근거 1번 · grounded) · slow(sec초 걸림) · 429 · 400. 부른 수와 동시 호출 최대를 센다."""

        def __init__(self, mode="ok", sec=0.0):
            self.mode, self.sec, self.n, self.now, self.peak, self.lock = mode, sec, 0, 0, 0, threading.Lock()
            ns = lambda **k: type("NS", (), k)  # noqa: E731
            self._ns = ns
            self.chat = ns(completions=ns(create=self._chat))
            self.embeddings = ns(create=lambda model, input: ns(data=[ns(embedding=[0.0])], usage=ns(prompt_tokens=1)))

        def with_options(self, **kw):
            return self

        def _chat(self, **kw):
            with self.lock:
                self.n += 1
                self.now += 1
                self.peak = max(self.peak, self.now)
            try:
                time.sleep(self.sec)
                if self.mode in ("429", "400"):
                    raise Err(int(self.mode))
                if "검증자" in kw["messages"][0]["content"]:
                    content = json.dumps({"verdict": "grounded"})
                else:
                    content = json.dumps({"found": True, "answer": "가짜 답", "evidence_ids": [1, 1, 99]})
                ns = self._ns
                return ns(choices=[ns(message=ns(content=content))], usage=ns(prompt_tokens=1, completion_tokens=1))
            finally:
                with self.lock:
                    self.now -= 1

    old = upstage._client, upstage.has_key, server.CFG, server.LOG_DIR
    server.LOG_DIR = tempfile.mkdtemp()
    upstage.has_key = lambda: False           # 검색은 키워드만(키 없이)
    try:
        # 3-1) 가짜 429: 마감(3초) 안에서 여러 번 다시 부르다 포기한다
        upstage._client = fake = Fake("429")
        bud = dict(cfg, retry_budget=True)
        t0 = time.monotonic()
        with upstage.budget(bud, t0 + 3):
            try:
                upstage.chat([{"role": "user", "content": "?"}], bud)
                raise AssertionError("429인데 답이 나옴")
            except upstage.DeadlineExceeded:
                pass
        assert time.monotonic() - t0 < 3 and fake.n >= 2, (time.monotonic() - t0, fake.n)
        # 3-2) 400은 다시 부르지 않는다
        upstage._client = fake = Fake("400")
        with upstage.budget(bud, time.monotonic() + 30):
            try:
                upstage.chat([{"role": "user", "content": "?"}], bud)
                raise AssertionError("400인데 답이 나옴")
            except Err:
                pass
        assert fake.n == 1
        # 3-3) 동시 호출 제한: 8개를 한꺼번에 불러도 동시에 2개까지
        upstage._client = fake = Fake("ok", sec=0.2)
        lim = dict(cfg, max_concurrent_calls=2)

        def one():
            with upstage.budget(lim, time.monotonic() + 30):
                upstage.chat([{"role": "system", "content": "?"}, {"role": "user", "content": "?"}], lim)
        ts = [threading.Thread(target=one) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert fake.n == 8 and fake.peak == 2, fake.peak

        # 4) 서버: 어떤 요청에도 규격 답
        server.CFG = dict(cfg, retry_budget=True, max_concurrent_calls=4)
        upstage._client = Fake("ok")
        run = lambda body: asyncio.run(server.respond(body))  # noqa: E731
        for body in (b"", b"{", b"[]", b'{"q": 1}', b'{"question": ""}', b'{"question": 7}', "깨짐".encode("cp949")):
            assert run(body) == UNKNOWN, body
        r = run(json.dumps({"question": "경차 주차요금 할인돼요?"}).encode())
        assert guard(r) is r and r != UNKNOWN and len(r["citation"]) == 1, r       # 겹친 번호 · 후보 밖 번호는 빠진다

        # 4-1) 동시에 10문항: 모두 네 칸
        async def many():
            qs = [json.dumps({"question": f"공원에서 {i}번 질문"}).encode() for i in range(10)]
            return await asyncio.gather(*(server.respond(q) for q in qs))
        rs = asyncio.run(many())
        assert len(rs) == 10 and all(guard(x) is x for x in rs)

        # 4-2) 가짜 지연: 모델이 5초 걸려도 마감(2초) 지나면 곧 확인 불가 (실제 서버는 75초, 대회 제한 90초)
        server.CFG = dict(server.CFG, timeout_sec=2)
        upstage._client = Fake("ok", sec=5)
        async def timed(body):   # asyncio.run은 끝날 때 뒤에 남은 스레드를 기다리므로, 답이 나온 때까지만 잰다
            t = time.monotonic()
            return await server.respond(body), time.monotonic() - t
        r, sec = asyncio.run(timed(json.dumps({"question": "경차 주차요금 할인돼요?"}).encode()))
        assert r == UNKNOWN and sec < 2.5, (r, sec)
        # 4-3) 판정 단계에서 마감이 지나면 on_deadline="draft"는 판정 전 답을 낸다
        upstage._client = Fake("ok", sec=1.2)       # 답 쓰기 1.2초 → 판정 1.2초 중에 2초 마감
        server.CFG = dict(server.CFG, on_deadline="draft", retry_budget=False)
        r = run(json.dumps({"question": "경차 주차요금 할인돼요?"}).encode())
        assert r != UNKNOWN and guard(r) is r, r

        # 5) 판단 기록: 문항마다 한 줄, 보낸 글 · 모델 출력은 남기지 않는다
        lines = [json.loads(x) for f in Path(server.LOG_DIR).glob("server-*.jsonl")
                 for x in f.read_text(encoding="utf-8").splitlines()]
        assert len(lines) == 7 + 1 + 10 + 2, len(lines)
        assert not any("sent" in c or "output" in c for x in lines for c in x["calls"])
        assert {x["note"] for x in lines} >= {"요청 본문 이상", "마감에 서버가 먼저 답함"}
    finally:
        upstage._client, upstage.has_key, server.CFG, server.LOG_DIR = old
        time.sleep(1.5)                       # 뒤에 남은 가짜 호출이 끝나게
    print("selftest ok")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        print("쓰는 법: python -m engine.contract --selftest")
