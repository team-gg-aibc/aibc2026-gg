"""문의 답변 창구 시연 화면(3판)의 얇은 서버 (표준 라이브러리만). 문의 저장 · 엔진 부르기 · 접수 위치 · 위치 바로잡기 · 고친 글과 승인 · 시민 쪽 답.

띄우기 (레포 맨 위에서):   python3 demo/desk/server.py      → 담당자 화면 http://127.0.0.1:8770 · 시민 화면 /citizen.html
설정 (환경 변수, 한 줄로 바꾼다):
  DESK_ENGINE_URL   엔진 주소. 기본 http://127.0.0.1:8000 (demo/desk/engine_trace.py). 채점 서버 주소(/ask까지 적어도 됨)로 바꿔도 돈다
  DESK_ENGINE       live = 시민 문의 · 위치 바로잡기는 그때 엔진을 부른다(기본) · saved = 엔진을 부르지 않고 미리 받은 답만 쓴다
  DESK_LOC          demo = 시민 화면의 「현재 위치」가 장면마다 미리 정한 자리(기본, 영상용) · real = 휴대폰 위치 기능
  DESK_PORT · DESK_STATE(저장 파일, 기본 demo/desk/runtime/state.json)
미리 받은 답 만들기:       python3 demo/desk/server.py --save   (같은 통로로 엔진을 불러 data/saved.json에 저장. 없는 글만, 모두 다시는 --all)
스스로 시험:               python3 demo/desk/server.py --selftest   (엔진 · 인터넷 없이)

- 처음 띄우면(또는 「처음 상태로」) 문의 47건(data/presets.json)이 미리 받은 답으로 들어와 있다. 시민 화면에서 보낸 문의만 그때 엔진을 부른다.
- 엔진은 글만 받는다. 시민이 지정한 접수 위치가 이름 있는 장소면 글 앞에 「○○에서 」를 붙여 보낸다(「이 공원에서 · 여기서」는 그 자리 이름으로 바꾼다).
- 화면 문구는 docs/content/의 3판 파일 둘에서 읽는다(요청마다 다시 읽어서, 파일을 고치면 화면이 바로 바뀐다). 이 서버는 낱말을 만들지 않는다.
- 시민 쪽 길(/api/citizen/<번호>)은 승인된 답만 준다. 승인 전 초안은 시민 화면이 받을 수 없다.
- 앞 판(2판) 화면 web/index.html · app.js · style.css는 지우지 않고 쓰지 않는다(이 서버의 /api는 3판 꼴).
"""
import json
import math
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
LOC_MODE = "real" if os.environ.get("DESK_LOC") == "real" else "demo"
PORT = int(os.environ.get("DESK_PORT", "8770"))
TIMEOUT = 90
TEXT_FILES = ("A-01_답변창구-3판", "U-02_시민접수-3판")
STATE_FILE = Path(os.environ.get("DESK_STATE") or HERE / "runtime" / "state.json")   # 둘을 함께 띄울 때만 바꾼다
SAVED_FILE = HERE / "data" / "saved.json"
OUT_REASONS = {"6종 밖 조례", "관할 밖", "질문 범위 밖"}   # 엔진이 「6종이 다루지 않는 조례 · 관할」이라고 가른 것만 6종 밖
FAIL_REASONS = {"시간 초과", "오류"}
NEAR_KM = 0.9          # 고른 자리에서 이만큼 안의 가장 가까운 장소 이름을 붙인다(주소 찾기 서비스는 쓰지 않음)
HERE_WORDS = re.compile(r"^(여기서|여기에서|이곳에서|이 공원에서|이 근처에서)\s*")

lock = threading.Lock()
presets = json.loads((HERE / "data" / "presets.json").read_text(encoding="utf-8"))
_pl = json.loads((HERE / "data" / "places.json").read_text(encoding="utf-8"))
places, scenes = {p["id"]: p for p in _pl["places"]}, _pl["scenes"]
RING = json.loads((HERE / "web" / "data" / "seoul.geojson").read_text(encoding="utf-8"))["features"][0]["geometry"]["coordinates"][0]
saved = json.loads(SAVED_FILE.read_text(encoding="utf-8")) if SAVED_FILE.exists() else {}
engine = {"trace": None, "reachable": None, "checked": 0}   # trace: /ask/trace가 있나(None = 아직 모름)


def now():
    return datetime.now(KST).isoformat(timespec="seconds")


# ---- 장소: 서울 안인가 · 가까운 이름 · 엔진에 보낼 글
def in_seoul(lon, lat):
    inside, j = False, len(RING) - 1
    for i in range(len(RING)):
        (xi, yi), (xj, yj) = RING[i], RING[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def km(a, b):
    return math.hypot((a[0] - b[0]) * 88.2, (a[1] - b[1]) * 111)   # 서울 위도에서 대략 거리


def near_place(lon, lat):
    d, p = min(((km((lon, lat), (p["lon"], p["lat"])), p) for p in places.values()), key=lambda x: x[0])
    return p if d <= NEAR_KM else None


def make_loc(lon, lat, how, place_id=None):
    p = places.get(place_id) if place_id else near_place(lon, lat)
    if p and place_id:
        lon, lat = p["lon"], p["lat"]
    return {"name": p["name"] if p else None, "place": p["id"] if p else None, "gu": p.get("gu", "") if p else "",
            "lon": round(lon, 6), "lat": round(lat, 6), "how": how, "virtual": False}


def engine_text(text, loc):
    """시민 · 담당자가 지정한 위치가 이름 있는 장소면 그 이름을 글에 넣는다(엔진은 글만 받는다). 시연 문의 47건은 기록한 글 그대로."""
    name = loc and loc.get("how") in ("here", "map", "staff") and loc.get("name")
    if not name:
        return text
    if HERE_WORDS.match(text):
        return HERE_WORDS.sub(f"{name}에서 ", text, count=1)
    return text if name in text else f"{name}에서 {text}"


# ---- 처음 상태: 문의 47건(미리 받은 답). 받은 시각은 띄운 때에서 거꾸로 약 11분 간격(시연용으로 정한 값)
def fresh_state():
    t0, n = datetime.now(KST), len(presets["presets"])
    inq = []
    for i, p in enumerate(presets["presets"], 1):
        at = (t0 - timedelta(minutes=11 * (n - i) + 6)).isoformat(timespec="seconds")
        q = {"id": f"p{i}", "no": i, "text": p["text"], "source": p["source"], "set_id": p["set_id"], "form": {}, "received": at,
             "loc": {**p["loc"], "how": "preset", "gu": (places.get(p["loc"].get("place")) or {}).get("gu", "")},
             "loc_from": None, "prev": None, "approved": None}
        q["engine_text"] = q["text"]
        res = saved.get(q["engine_text"]) or {"response": None, "error": "미리 받은 답 없음"}
        apply_result(q, res, "saved")
        if p["approved"] and q["kind"] == "draft":
            q["approved"] = {"text": q["card"]["answer"], "at": (t0 - timedelta(minutes=11 * (n - i))).isoformat(timespec="seconds"),
                             "by": "처리담당자(시연)", "edited": False, "reply": "draft"}
        inq.append(q)
    return {"v": 3, "inquiries": inq}


def load_state():
    try:
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if st.get("v") == 3:
            return st
    except (OSError, ValueError):
        pass
    return None                              # 없거나 앞 판(2판) 꼴이면 처음 상태로


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
LAWS = {x["law"] for x in CHUNKS.values()}
_squash = lambda s: re.sub(r"\s+", "", (s or "").replace("[조항]", ""))   # noqa: E731
DELEG_MARK = "(※ 그 내용은 이 자료에 없다)"   # 엔진(flow2)이 조례가 다른 법령에 넘긴 구절에 붙이는 안쪽 표시. 구절에도 답 글에도 그대로 들어올 수 있다
_inner = lambda s: re.sub(r"\s*" + re.escape(DELEG_MARK), "", s or "").strip()   # noqa: E731  엔진 안쪽 표시는 화면 · 시민 답에 내지 않는다


# ---- 엔진 부르기 (같은 통로: 시민 문의도, 위치 바로잡기도, 미리 받은 답 만들기도 이 함수 하나)
def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def call_engine(text):
    """→ {"response", "trace"(없으면 None), "sec", "error"(없으면 None)}. 예외를 밖으로 내지 않는다."""
    t0 = time.time()
    try:
        try:                                 # 문의마다 기록 길부터 불러 본다(엔진을 바꿔 띄워도 화면 서버를 다시 띄울 필요가 없게)
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
    ev = [(_squash(re.sub(r"\([^)]*\)", "", e["label"])), _inner(e["quote"])) for e in t.get("evidence") or [] if e.get("quote")]
    cites = []
    for label in r.get("citation") or []:
        c = CHUNKS.get(label, {})
        law = c.get("law") or next((n for n in LAWS if label.startswith(n)), "")
        lab, body = _squash(label), _squash(c.get("text"))
        # 구절이 그 조항 원문 안에 있으면 그 조항의 구절(⑤ 구절 관문이 이미 글자를 대 봄). 별표처럼 원문 자료와 꼴이 다르면 라벨로 짝짓는다
        short = _squash(label[len(law):]) if law else lab
        quotes = ([q for _, q in ev if body and _squash(q) in body] or [q for k, q in ev if k.startswith(lab)]
                  or [q for k, q in ev if short and k.startswith(short)])
        cites.append({"label": label, "law": law, "article": label[len(law):].strip() if law else label,
                      "quotes": list(dict.fromkeys(quotes)), "text": c.get("text"),
                      "url": c.get("url") or r.get("source_url"), "effective": c.get("effective") or r.get("effective_date")})
    return {"answer": _inner(r.get("answer")) if cites else None,   # 실제 호출 답 글에도 안쪽 표시가 들어온다(점검 11-11 밤) "conclusion": t.get("conclusion") if cites else None,
            "citations": cites, "reason": t.get("reason"), "has_trace": bool(t), "error": res.get("error")}


def apply_result(q, res, how):
    q.update(kind=kind_of(res), card=card_of(res), engine={"how": how, "at": res.get("at") or now(), "sec": res.get("sec"),
                                                            "made_by": res.get("made_by"), "settings": (res.get("trace") or {}).get("settings")})
    q["draft"] = q["card"]["answer"]


def run_engine(qid):
    with lock:
        q = next(x for x in state["inquiries"] if x["id"] == qid)
        text, use_saved = q["engine_text"], MODE == "saved" or (q["source"] != "citizen" and q["loc"]["how"] != "staff")
    if use_saved:
        hit = saved.get(text)
        res, how = (hit, "saved") if hit else ({"response": None, "error": "미리 받은 답 없음"}, "saved")
    else:
        res, how = call_engine(text), "live"
        engine["reachable"] = res["error"] is None
    with lock:
        apply_result(q, res, how)
        save_state()


def add_inquiry(text, form, loc):
    with lock:
        no = max([x["no"] for x in state["inquiries"]], default=0) + 1
        q = {"id": f"q{no}-{int(time.time() * 1000) % 100000}", "no": no, "text": text, "source": "citizen", "set_id": None,
             "form": form, "received": now(), "loc": loc, "loc_from": None, "prev": None, "engine_text": engine_text(text, loc),
             "kind": "making", "card": None, "draft": None, "approved": None, "engine": None}
        state["inquiries"].append(q)
        save_state()
    threading.Thread(target=run_engine, args=(q["id"],), daemon=True).start()
    return q


def engine_status():
    if MODE == "saved":
        return "saved"
    if time.time() - engine["checked"] > 10:          # 10초에 한 번만 엔진이 살아 있는지 본다
        engine["checked"] = time.time()
        try:
            urllib.request.urlopen(ENGINE_BASE + "/health", timeout=3).read()
            engine["reachable"] = True
        except urllib.error.HTTPError:  # 답은 했다(채점 서버엔 /health가 없을 수 있다): 마지막 호출 결과를 따른다
            if engine["reachable"] is None:
                engine["reachable"] = False
        except Exception:  # noqa: BLE001  연결 자체가 안 된다: 켜져 있던 엔진이 꺼진 때도 「연결되지 않음」으로 바꾼다
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
            data["A-01_답변창구-3판"]["sections"]["상황별 안내"]["tables"][0]["rows"][0]   # 쓰는 표가 있나
            _text.update(data=data, error=None)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            _text["error"] = f"{type(e).__name__}: {e}"[:200]
    return {"version": version, "text": _text["data"], "error": _text["error"]}


def citizen_view(q):
    a = q.get("approved")
    cites = (q.get("card") or {}).get("citations") or []
    return {"no": q["no"], "text": q["text"], "title": (q.get("form") or {}).get("title", ""), "received": q["received"],
            "loc": q.get("loc_from") or q.get("loc"), "answer": a["text"] if a else None, "approved_at": a["at"] if a else None,
            "citations": [{"label": c["label"], "effective": c["effective"]} for c in cites] if a and a.get("reply") == "draft" else []}


def str_or(v, n):
    return str(v).strip()[:n] if isinstance(v, (str, int, float)) else ""


def num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


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
        """요청 본문 → dict. 길이 머리말이 이상하거나 JSON이 깨졌거나 dict가 아니면 빈 dict(서버가 죽지 않고 400 · 409로 답한다)."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(n).decode("utf-8")) if 0 < n < 200_000 else {}
        except ValueError:
            return {}
        return d if isinstance(d, dict) else {}

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":                                  # 3판 담당자 화면(앞 판 index.html은 쓰지 않음)
            self.send_response(302)
            self.send_header("Location", "/desk.html")
            self.end_headers()
            return None
        if p == "/api/text":
            return self.send_json(text_bundle())
        if p == "/api/state":
            status = engine_status()      # 엔진이 살아 있는지 보는 호출(길면 3초)은 잠금 밖에서: 그동안 다른 요청이 멈추지 않게
            with lock:
                return self.send_json({"inquiries": state["inquiries"], "places": places, "scenes": scenes, "pair": presets["pair"],
                                       "engine": status, "loc_mode": LOC_MODE, "text_version": text_bundle()["version"]})
        m = re.fullmatch(r"/api/citizen/([\w-]+)", p)
        if m:
            with lock:
                q = next((x for x in state["inquiries"] if x["id"] == m.group(1)), None)
                return self.send_json(citizen_view(q) if q else {"error": "없음"}, 200 if q else 404)
        return super().do_GET()

    def do_POST(self):
        p, b = self.path.split("?")[0], self.body()
        if p == "/api/inquiries":
            text, title = str_or(b.get("text"), 3000), str_or(b.get("title"), 30)
            if not text or not title:
                return self.send_json({"error": "빈 제목 · 내용"}, 400)
            if b.get("agree") is not True:                    # 실제 신청 화면처럼 개인정보 수집 · 이용 동의가 있어야 받는다
                return self.send_json({"error": "동의 필요"}, 400)
            lo = b.get("loc") if isinstance(b.get("loc"), dict) else {}
            lon, lat = num(lo.get("lon")), num(lo.get("lat"))
            if lon is None or lat is None or not in_seoul(lon, lat):
                return self.send_json({"error": "서울 안의 민원 장소 필요"}, 400)
            loc = make_loc(lon, lat, "map" if lo.get("how") == "map" else "here")
            loc["demo"] = lo.get("demo") is True
            form = {"title": title, "region": str_or(b.get("region"), 20), "public": b.get("public") is True,
                    "notify": [str_or(x, 10) for x in b.get("notify")][:4] if isinstance(b.get("notify"), list) else []}
            q = add_inquiry(text, form, loc)
            return self.send_json({"id": q["id"], "no": q["no"]})
        if p == "/api/reset":
            with lock:
                state.clear()
                state.update(fresh_state())
                save_state()
            return self.send_json({"ok": True})
        m = re.fullmatch(r"/api/inquiries/([\w-]+)/(draft|approve|retry|relocate)", p)
        if not m:
            return self.send_json({"error": "없는 길"}, 404)
        act = m.group(2)
        with lock:
            q = next((x for x in state["inquiries"] if x["id"] == m.group(1)), None)
            if q is None:
                return self.send_json({"error": "없음"}, 404)
            if act == "retry":
                if q["kind"] != "failed":
                    return self.send_json({"error": "불러오지 못한 문의가 아님"}, 409)
                q["kind"] = "making"
            elif q["approved"]:
                return self.send_json({"error": "이미 시민에게 보낸 답"}, 409)     # 되돌릴 수 없다
            elif act == "relocate":
                if q["kind"] == "making":
                    return self.send_json({"error": "초안을 만드는 중"}, 409)
                pid, lon, lat = b.get("place"), num(b.get("lon")), num(b.get("lat"))
                if isinstance(pid, str) and pid in places:
                    loc = make_loc(0, 0, "staff", pid)
                elif lon is not None and lat is not None and in_seoul(lon, lat):
                    loc = make_loc(lon, lat, "staff")
                else:
                    return self.send_json({"error": "서울 안의 장소 필요"}, 400)
                q["prev"] = {"kind": q["kind"], "card": q["card"], "loc": q["loc"]}
                q["loc_from"] = q["loc_from"] or q["loc"]
                q.update(loc=loc, kind="making", engine_text=engine_text(q["text"], loc))
            elif q["kind"] not in ("draft", "out", "notfound"):
                return self.send_json({"error": "답을 쓸 수 없는 상태"}, 409)
            else:
                text = str_or(b.get("text"), 3000)
                if act == "approve" and not text:
                    return self.send_json({"error": "빈 답"}, 400)
                q["draft"] = text or q["draft"]
                if act == "approve":
                    reply = b.get("reply") if b.get("reply") in ("draft", "direct", "guide") else "direct"
                    if q["kind"] != "draft":
                        reply = "guide" if reply == "guide" else "direct"     # 초안이 없는 문의는 근거 조항 없이 나간다
                    q["approved"] = {"text": text, "at": now(), "by": "처리담당자(시연)", "edited": text != (q["card"] or {}).get("answer"),
                                     "reply": reply}   # 시민 답의 담당부서 줄에는 기관 이름을 싣지 않는다(답한 곳처럼 읽혀서, 점검 11-11)
            save_state()
        if act in ("retry", "relocate"):
            threading.Thread(target=run_engine, args=(q["id"],), daemon=True).start()
        return self.send_json({"ok": True})


def save_answers():
    """시연 문의 47건과 장면마다 「접수 위치 + 두 시민 글」을 같은 통로(call_engine)로 엔진에 넣어 data/saved.json에 저장한다."""
    texts = [p["text"] for p in presets["presets"]]
    texts += [engine_text(presets["pair"]["text"], make_loc(0, 0, "here", s["place"])) for s in scenes.values()]
    out = dict(saved)                         # 이미 받은 답은 그대로 둔다(--all이면 다시 받는다)
    for t in texts:
        if t in out and "--all" not in sys.argv:
            continue
        res = call_engine(t)
        if res["error"]:
            print("못 받음:", t[:30], res["error"])
            continue
        res.update(at=now(), made_by=os.environ.get("DESK_MADE_BY", "새 흐름 7판"))
        out[t] = res
        print(kind_of(res), res["sec"], "초", (res["response"].get("citation") or ["—"])[0], "|", t[:30])
    SAVED_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("저장:", SAVED_FILE)


def selftest():
    ok = {"response": {"answer": "네.", "citation": ["서울특별시 주차장 설치 및 관리 조례 제13조 제2항"], "source_url": "u", "effective_date": "2026-10-01"},
          "trace": {"conclusion": "네", "evidence": [{"label": "[조항] 서울특별시 주차장 설치 및 관리 조례 제13조 제2항", "quote": "구절(※ 그 내용은 이 자료에 없다)"}]}}
    unk = {"answer": "확인 불가", "citation": [], "source_url": "", "effective_date": ""}
    assert kind_of(ok) == "draft"
    assert kind_of({"response": unk, "trace": {"reason": "6종 밖 조례"}}) == "out"
    assert kind_of({"response": unk, "trace": {"reason": "found 거짓"}}) == "notfound"
    assert kind_of({"response": unk, "trace": None}) == "notfound"                 # 네 칸만: 6종 밖이라 부르지 않는다
    assert kind_of({"response": unk, "trace": {"reason": "시간 초과"}}) == "failed"
    assert kind_of({"response": None, "error": "URLError"}) == "failed"
    c = card_of(ok)["citations"][0]
    assert c["law"] == "서울특별시 주차장 설치 및 관리 조례" and c["article"] == "제13조 제2항" and c["quotes"] == ["구절"], c
    assert c["text"] and c["url"].startswith("https://www.law.go.kr"), c                    # 링크 · 시행일 · 원문은 자료에서
    assert card_of({"response": unk, "trace": {}})["answer"] is None
    mk = {"response": {**ok["response"], "answer": "각 호의 행위 (※ 그 내용은 이 자료에 없다)를 하면 안 됩니다."}, "trace": ok["trace"]}
    assert card_of(mk)["answer"] == "각 호의 행위를 하면 안 됩니다.", card_of(mk)["answer"]   # 답 글의 안쪽 표시도 지운다
    # 장소: 서울 안 · 밖, 이름 붙이기, 엔진에 보낼 글
    sf, tt = places["seoulforest"], places["ttukseom-hangang"]
    assert in_seoul(sf["lon"], sf["lat"]) and not in_seoul(127.11, 37.40)            # 판교는 서울 밖
    assert make_loc(sf["lon"] + 0.002, sf["lat"], "here")["name"] == "서울숲"
    assert make_loc(127.0, 37.62, "here")["name"] is None                            # 0.9km 안에 아는 장소 없음
    pt = presets["pair"]["text"]
    assert engine_text(pt, make_loc(0, 0, "here", "seoulforest")).startswith("서울숲에서 돗자리를")
    assert engine_text(pt, make_loc(0, 0, "staff", tt["id"])).startswith("뚝섬한강공원에서 돗자리를")
    assert engine_text("요금이 얼마인가요?", make_loc(0, 0, "map", "dongjak")) == "동작대교 공영주차장에서 요금이 얼마인가요?"
    assert engine_text("동작대교 공영주차장 요금은?", make_loc(0, 0, "here", "dongjak")) == "동작대교 공영주차장 요금은?"
    assert engine_text("요금은?", {**make_loc(0, 0, "here", "dongjak"), "how": "preset"}) == "요금은?"   # 47건은 기록한 글 그대로
    # 두 시민 장면 · 47건은 미리 받은 답이 모두 있다
    for s in scenes.values():
        assert engine_text(pt, make_loc(0, 0, "here", s["place"])) in saved, s
    st = fresh_state()
    assert len(st["inquiries"]) == 47 and all(q["kind"] != "failed" for q in st["inquiries"]), [q["set_id"] for q in st["inquiries"] if q["kind"] == "failed"]
    assert sum(q["source"] in ("real", "faq") for q in st["inquiries"]) == 30
    tb = text_bundle()
    assert tb["error"] is None and set(tb["text"]) == set(TEXT_FILES), tb["error"]
    q = {"no": 1, "text": "t", "received": "x", "card": card_of(ok), "approved": None, "loc": None}
    assert citizen_view(q)["answer"] is None and citizen_view(q)["citations"] == []          # 승인 전 초안은 시민에게 가지 않는다
    print("server 스스로 시험 통과")


state = load_state() or fresh_state()

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--save" in sys.argv:
        save_answers()
    else:
        save_state()
        print(f"문의 답변 창구: http://127.0.0.1:{PORT}  · 시민 화면 /citizen.html · 엔진 {ENGINE_BASE} · 방식 {MODE} · 위치 {LOC_MODE}")
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
