"""문의 답변 창구 시연 화면의 얇은 서버 (표준 라이브러리만). 문의 저장 · 엔진 부르기 · 고친 글과 승인 · 시민 쪽 답 받기 · 재생.

띄우기 (레포 맨 위에서):   python3 demo/desk/server.py                      → http://127.0.0.1:8770
설정 (환경 변수, 한 줄로 바꾼다):
  DESK_ENGINE_URL   엔진 주소. 기본 http://127.0.0.1:8000 (demo/desk/engine_trace.py). 채점 서버 주소(/ask까지 적어도 됨)로 바꿔도 돈다
  DESK_ENGINE       live = 시민 화면에서 보낸 문의는 그때 엔진을 부른다(기본) · saved = 엔진을 부르지 않고 미리 받은 답만 쓴다
  DESK_PORT · DESK_REPLAY_SEC(재생 간격, 기본 2.5초) · DESK_STATE(저장 파일, 기본 demo/desk/runtime/state.json)
미리 받은 답 만들기:       python3 demo/desk/server.py --save   (같은 통로로 엔진을 불러 data/saved.json에 저장)
스스로 시험:               python3 demo/desk/server.py --selftest   (엔진 · 인터넷 없이)

- 시연 문의(재생)는 늘 미리 받은 답으로 뜬다. 시민 화면에서 보낸 문의만 그때 엔진을 부른다(PRD 3판 3절 추천안).
- 화면 문구는 docs/content/에서 읽는다(요청마다 다시 읽어서, 파일을 고치면 화면이 바로 바뀐다). 이 서버는 낱말을 만들지 않는다.
- 시민 쪽 길(/api/citizen/<번호>)은 승인된 답만 준다. 승인 전 초안은 시민 화면이 받을 수 없다.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "demo" / "hangang-3d" / "scripts"))
import content as C  # noqa: E402  앞 판 화면의 content 읽개를 그대로 쓴다

KST = timezone(timedelta(hours=9))
ENGINE_URL = os.environ.get("DESK_ENGINE_URL", "http://127.0.0.1:8000").rstrip("/")
ENGINE_BASE = ENGINE_URL[:-4] if ENGINE_URL.endswith("/ask") else ENGINE_URL
MODE = os.environ.get("DESK_ENGINE", "live")
PORT = int(os.environ.get("DESK_PORT", "8770"))
REPLAY_SEC = float(os.environ.get("DESK_REPLAY_SEC", "2.5"))
TIMEOUT = 90
TEXT_FILES = ("A-01_답변화면", "C-01_답변초안카드", "U-02_시민문의")
STATE_FILE = Path(os.environ.get("DESK_STATE") or HERE / "runtime" / "state.json")   # 둘을 함께 띄울 때만 바꾼다
SAVED_FILE = HERE / "data" / "saved.json"
OUT_REASONS = {"6종 밖 조례", "관할 밖", "질문 범위 밖"}   # 엔진이 「6종이 다루지 않는 조례 · 관할」이라고 가른 것만 6종 밖
FAIL_REASONS = {"시간 초과", "오류"}

lock = threading.Lock()
replay = json.loads((HERE / "data" / "replay.json").read_text(encoding="utf-8"))
places = {p["id"]: p for p in json.loads((HERE / "data" / "places.json").read_text(encoding="utf-8"))["places"]}
saved = json.loads(SAVED_FILE.read_text(encoding="utf-8")) if SAVED_FILE.exists() else {}
engine = {"trace": None, "reachable": None, "checked": 0}   # trace: /ask/trace가 있나(None = 아직 모름)


def now():
    return datetime.now(KST).isoformat(timespec="seconds")


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"inquiries": [], "replay_next": 0}


state = load_state()


def save_state():
    STATE_FILE.parent.mkdir(exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_FILE)


# ---- 조례 원문 자료: 인용 라벨 → 조례 이름 · 조항 원문 · 링크 · 시행일 (코드가 붙이는 정보, 모델이 쓰지 않음)
def _chunks():
    out = {}
    for ch in json.loads((ROOT / "engine" / "data" / "chunks_paragraph.json").read_text(encoding="utf-8")):
        c = out.setdefault(ch["label"], {"law": ch["law"], "url": ch["source_url"], "effective": ch["effective_date"], "text": ""})
        c["text"] = (c["text"] + "\n" + ch["text"]).strip()
    return out


CHUNKS = _chunks()
_squash = lambda s: re.sub(r"\s+", "", (s or "").replace("[조항]", ""))   # noqa: E731


# ---- 엔진 부르기 (같은 통로: 시민 문의도, 미리 받은 답 만들기도 이 함수 하나)
def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def call_engine(text):
    """→ {"response", "trace"(없으면 None), "sec", "error"(없으면 None)}. 예외를 밖으로 내지 않는다."""
    t0 = time.time()
    try:
        if engine["trace"] is not False:
            try:
                d = post(ENGINE_BASE + "/ask/trace", {"question": text})
                engine["trace"] = True
                return {"response": d["response"], "trace": d["trace"], "sec": round(time.time() - t0, 1), "error": None}
            except urllib.error.HTTPError as e:
                if e.code not in (404, 405):
                    raise
                engine["trace"] = False          # 채점 서버처럼 /ask만 있는 엔진
        d = post(ENGINE_BASE + "/ask", {"question": text})
        return {"response": d, "trace": None, "sec": round(time.time() - t0, 1), "error": None}
    except Exception as e:  # noqa: BLE001  연결 실패 · 시간 초과 · 깨진 응답 → 「불러오지 못함」
        return {"response": None, "trace": None, "sec": round(time.time() - t0, 1), "error": type(e).__name__}


def kind_of(res):
    """엔진 결과 → 카드 갈래: draft(초안) · out(6종 밖) · notfound(조항을 찾지 못함) · failed(불러오지 못함)."""
    r, t = res.get("response"), res.get("trace") or {}
    if res.get("error") or not isinstance(r, dict):
        return "failed"
    if r.get("citation") and not str(r.get("answer", "")).startswith("확인 불가"):
        return "draft"
    if t.get("reason") in FAIL_REASONS:
        return "failed"
    if t.get("reason") in OUT_REASONS:
        return "out"
    return "notfound"      # 기록이 없거나 그 밖의 확인 불가: 「6종 밖」이라 부르지 않는다(PRD 3절 화면)


def card_of(res):
    """엔진 결과 → 카드에 쓰는 자료(낱말 없이 값만)."""
    r, t = res.get("response") or {}, res.get("trace") or {}
    ev = [(_squash(re.sub(r"\([^)]*\)", "", e["label"])), e["quote"]) for e in t.get("evidence") or [] if e.get("quote")]
    cites = []
    for label in r.get("citation") or []:
        c = CHUNKS.get(label, {})
        law = c.get("law") or next((n for n in {x["law"] for x in CHUNKS.values()} if label.startswith(n)), "")
        lab, body = _squash(label), _squash(c.get("text"))
        # 구절이 그 조항 원문 안에 있으면 그 조항의 구절(⑤ 구절 관문이 이미 글자를 대 봄). 별표처럼 원문 자료와 꼴이 다르면 라벨로 짝짓는다
        short = _squash(label[len(law):]) if law else lab
        quotes = ([q for _, q in ev if body and _squash(q) in body] or [q for k, q in ev if k.startswith(lab)]
                  or [q for k, q in ev if short and k.startswith(short)])
        cites.append({"label": label, "law": law, "article": label[len(law):].strip() if law else label,
                      "quotes": list(dict.fromkeys(quotes)), "text": c.get("text"),
                      "url": c.get("url") or r.get("source_url"), "effective": c.get("effective") or r.get("effective_date")})
    return {"answer": r.get("answer") if cites else None, "conclusion": t.get("conclusion") if cites else None,
            "citations": cites, "reason": t.get("reason"), "has_trace": bool(t), "error": res.get("error")}


def apply_result(q, res, how):
    q.update(kind=kind_of(res), card=card_of(res), engine={"how": how, "at": res.get("at") or now(), "sec": res.get("sec"),
                                                            "settings": (res.get("trace") or {}).get("settings")})
    q["draft"] = q["card"]["answer"]


def run_engine(qid):
    with lock:
        q = next(x for x in state["inquiries"] if x["id"] == qid)
        text = q["text"]
    hit = saved.get(text)
    if MODE == "saved" or q["source"] != "citizen":
        res, how = (hit, "saved") if hit else ({"response": None, "error": "미리 받은 답 없음"}, "saved")
    else:
        res, how = call_engine(text), "live"
        engine["reachable"] = res["error"] is None
    with lock:
        apply_result(q, res, how)
        save_state()


def add_inquiry(text, source, place, set_id=None):
    with lock:
        no = max([x["no"] for x in state["inquiries"]], default=0) + 1
        q = {"id": f"q{no}-{int(time.time() * 1000) % 100000}", "no": no, "text": text, "source": source, "place": place,
             "set_id": set_id, "received": now(), "kind": "making", "card": None, "draft": None, "approved": None, "engine": None}
        state["inquiries"].append(q)
        save_state()
    threading.Thread(target=run_engine, args=(q["id"],), daemon=True).start()
    return q


def replay_loop():
    while True:
        with lock:
            i = state["replay_next"]
            if i >= len(replay["replay"]) or not state.get("replaying"):
                state["replaying"] = False
                save_state()
                return
            state["replay_next"] = i + 1
        item = replay["replay"][i]
        add_inquiry(item["text"], item["source"], item.get("place"), item["set_id"])
        time.sleep(REPLAY_SEC)


def engine_status():
    if MODE == "saved":
        return "saved"
    if time.time() - engine["checked"] > 10:          # 10초에 한 번만 엔진이 살아 있는지 본다
        engine["checked"] = time.time()
        try:
            urllib.request.urlopen(ENGINE_BASE + "/health", timeout=3).read()
            engine["reachable"] = True
        except Exception:  # noqa: BLE001  채점 서버엔 /health가 없을 수 있다: 그때는 마지막 호출 결과를 따른다
            if engine["reachable"] is None:
                engine["reachable"] = False
    if not engine["reachable"]:
        return "down"
    return "notrace" if engine["trace"] is False else "live"


# ---- 화면 문구 (docs/content/). 고치는 중 깨진 파일이면 마지막으로 정상이던 글자를 주고 오류를 알린다
_text = {"version": None, "data": None, "error": None}


def text_bundle():
    files = [ROOT / "docs" / "content" / f"{n}.md" for n in TEXT_FILES]
    version = max(f.stat().st_mtime for f in files)
    if version != _text["version"]:
        _text["version"] = version
        try:
            data = {n: C.parse(n) for n in TEXT_FILES}
            data["C-01_답변초안카드"]["sections"]["소관 부서와 처리 기관"]["tables"][0]["rows"][0]   # 쓰는 표가 있나
            _text.update(data=data, error=None)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            _text["error"] = f"{type(e).__name__}: {e}"[:200]
    return {"version": version, "text": _text["data"], "error": _text["error"]}


def citizen_view(q):
    a = q.get("approved")
    return {"no": q["no"], "text": q["text"], "received": q["received"],
            "answer": a["text"] if a else None, "approved_at": a["at"] if a else None,
            "citations": [{"label": c["label"], "effective": c["effective"]} for c in (q["card"] or {}).get("citations", [])] if a else []}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE / "web"), **k)

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except ValueError:
            return {}

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/text":
            return self.send_json(text_bundle())
        if p == "/api/state":
            with lock:
                return self.send_json({"inquiries": state["inquiries"], "places": places, "engine": engine_status(),
                                       "engine_url": ENGINE_BASE, "replaying": bool(state.get("replaying")),
                                       "replay_left": len(replay["replay"]) - state["replay_next"], "core": replay["core"],
                                       "text_version": text_bundle()["version"]})
        m = re.fullmatch(r"/api/citizen/([\w-]+)", p)
        if m:
            with lock:
                q = next((x for x in state["inquiries"] if x["id"] == m.group(1)), None)
                return self.send_json(citizen_view(q) if q else {"error": "없음"}, 200 if q else 404)
        return super().do_GET()

    def do_POST(self):
        p, b = self.path.split("?")[0], self.body()
        if p == "/api/inquiries":
            text = str(b.get("text") or "").strip()
            if not text:
                return self.send_json({"error": "빈 문의"}, 400)
            place = b.get("place") if b.get("place") in places else None
            q = add_inquiry(text[:1000], "citizen", place)
            return self.send_json({"id": q["id"], "no": q["no"]})
        if p == "/api/replay":
            with lock:
                start = not state.get("replaying") and state["replay_next"] < len(replay["replay"])
                state["replaying"] = state.get("replaying") or start
            if start:
                threading.Thread(target=replay_loop, daemon=True).start()
            return self.send_json({"ok": True})
        if p == "/api/reset":
            with lock:
                state.clear()
                state.update(inquiries=[], replay_next=0, replaying=False)
                save_state()
            return self.send_json({"ok": True})
        m = re.fullmatch(r"/api/inquiries/([\w-]+)/(draft|approve|retry)", p)
        if not m:
            return self.send_json({"error": "없는 길"}, 404)
        with lock:
            q = next((x for x in state["inquiries"] if x["id"] == m.group(1)), None)
            if q is None:
                return self.send_json({"error": "없음"}, 404)
            act = m.group(2)
            if act == "retry":
                if q["kind"] != "failed":
                    return self.send_json({"error": "불러오지 못한 문의가 아님"}, 409)
                q["kind"] = "making"
                save_state()
            elif q["approved"]:
                return self.send_json({"error": "이미 시민에게 보낸 답"}, 409)     # 되돌릴 수 없다
            elif q["kind"] != "draft":
                return self.send_json({"error": "초안이 없는 문의"}, 409)
            else:
                text = str(b.get("text") or "").strip()
                if act == "approve" and not text:
                    return self.send_json({"error": "빈 답"}, 400)
                q["draft"] = text or q["draft"]
                if act == "approve":
                    q["approved"] = {"text": text, "at": now(), "by": "처리담당자(시연)", "edited": text != q["card"]["answer"]}
                save_state()
        if act == "retry":
            threading.Thread(target=run_engine, args=(q["id"],), daemon=True).start()
        return self.send_json({"ok": True})


def save_answers():
    """시연 문의(재생 + 첫 장면)를 같은 통로(call_engine)로 엔진에 넣어 data/saved.json에 저장한다."""
    out = dict(saved)
    for item in [replay["core"], *replay["replay"]]:
        res = call_engine(item["text"])
        if res["error"]:
            print("못 받음:", item["set_id"], res["error"])
            continue
        res["at"] = now()
        out[item["text"]] = res
        print(item["set_id"], kind_of(res), res["sec"], "초", (res["response"].get("citation") or ["—"])[0])
    SAVED_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("저장:", SAVED_FILE)


def selftest():
    ok = {"response": {"answer": "네.", "citation": ["서울특별시 주차장 설치 및 관리 조례 제13조 제2항"], "source_url": "u", "effective_date": "2026-10-01"},
          "trace": {"conclusion": "네", "evidence": [{"label": "[조항] 서울특별시 주차장 설치 및 관리 조례 제13조 제2항", "quote": "구절"}]}}
    unk = {"answer": "확인 불가", "citation": [], "source_url": "", "effective_date": ""}
    assert kind_of(ok) == "draft"
    assert kind_of({"response": unk, "trace": {"reason": "관할 밖"}}) == "out"
    assert kind_of({"response": unk, "trace": {"reason": "found 거짓"}}) == "notfound"
    assert kind_of({"response": unk, "trace": None}) == "notfound"                 # 네 칸만: 6종 밖이라 부르지 않는다
    assert kind_of({"response": unk, "trace": {"reason": "시간 초과"}}) == "failed"
    assert kind_of({"response": None, "error": "URLError"}) == "failed"
    c = card_of(ok)["citations"][0]
    assert c["law"] == "서울특별시 주차장 설치 및 관리 조례" and c["article"] == "제13조 제2항" and c["quotes"] == ["구절"], c
    assert c["text"] and c["url"].startswith("https://www.law.go.kr"), c                    # 링크 · 시행일 · 원문은 자료에서
    assert card_of({"response": unk, "trace": {}})["answer"] is None
    tb = text_bundle()
    assert tb["error"] is None and set(tb["text"]) == set(TEXT_FILES), tb["error"]
    q = {"no": 1, "text": "t", "received": "x", "card": card_of(ok), "approved": None}
    assert citizen_view(q)["answer"] is None and citizen_view(q)["citations"] == []          # 승인 전 초안은 시민에게 가지 않는다
    print("server 스스로 시험 통과")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--save" in sys.argv:
        save_answers()
    else:
        with lock:
            state["replaying"] = False
        print(f"문의 답변 창구: http://127.0.0.1:{PORT}  · 엔진 {ENGINE_BASE} · 방식 {MODE}")
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
