"""음성 통화의 가운데 자리. server.py가 스위치(CALL_VOICE=1)일 때만 붙인다. 기본은 끔이고, 끄면 이 파일은 읽히지도 않는다.

전화 한 통 = 방 하나. 방에는 두 쪽이 붙는다.
  소리 쪽(거는 사람)   소리를 넣고(feed), 읽어 줄 말을 받아 간다(says)    ← 지금: 브라우저 마이크(web/dial.html · voice.js). 나중: 전화 회선이 이 자리에 온다
  화면 쪽(상담 화면)   받아쓴 글을 받아 가고(events), 읽어 줄 말을 넣는다(ask) ← web/voice.js가 받아 적기 칸에 올리고, 확정 글을 지금의 /api/turn에 그대로 넣는다
위치 좁히기 · 질문 고르기 · 조례 답은 건드리지 않는다. 이 파일은 소리와 글을 나르기만 한다.

전화 회선을 붙일 때는 회선이 준 소리로 join() · feed()를 부르고, says()로 읽어 줄 말을 가져가 회선에 틀면 된다(HTTP 길은 그 셋을 부를 뿐이다).

| 환경 변수 | 뜻 | 기본 |
| CALL_VOICE | 1이면 켠다 | 끔 |
| CALL_VOICE_STT | fake(대본 글 · 친 글을 흘림) · whisper(이 컴퓨터 안의 받아쓰기, 가입 없음) · rtzr(리턴제로) | 리턴제로 열쇠가 있으면 rtzr, 없으면 fake |
| CALL_VOICE_TTS | 읽어 주기. none(소리 없이 글 길이만큼 기다림) · browser(기기에 든 읽어 주기). web/voice/tts/에 미리 만든 파일이 있으면 그것이 먼저 | none |
| CALL_VOICE_ASK | 질문을 누가 말하나. ai(화면이 띄운 질문을 읽어 준다) · agent(상담사가 직접 말한다. 읽어 주지 않는다). 주소 ?ask= 로도 바꾼다 | ai |
| CALL_VOICE_CODE | 값이 있으면 통화를 열 때 이 접근 코드를 받는다(밖에 내놓을 때) | 없음 |
| CALL_VOICE_GAP_MS | 확정 글 뒤 이만큼 조용하면 한 차례로 끊는다 | 900 (whisper는 300) |
| CALL_VOICE_MAX_ROOMS · CALL_VOICE_ROOM_SEC · CALL_VOICE_OPENS_PER_HOUR | 한꺼번에 열리는 통화 수 · 한 통화의 최대 초 · 한 시간에 여는 횟수 | 4 · 600 · 40 |
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import stt

WEB = Path(__file__).resolve().parents[1] / "web"
CODE = os.environ.get("CALL_VOICE_CODE", "")
TTS = "browser" if os.environ.get("CALL_VOICE_TTS") == "browser" else "none"
ASK = "agent" if os.environ.get("CALL_VOICE_ASK") == "agent" else "ai"      # 질문을 누가 말하나: ai = 화면이 띄운 질문을 읽어 준다 · agent = 상담사가 직접 말한다(읽어 주지 않는다)
STT = stt.pick()
GAP_MS = int(os.environ.get("CALL_VOICE_GAP_MS") or (300 if STT.name == "whisper" else 900))      # 로컬 받아쓰기는 확정 글이 이미 0.7초의 조용함을 기다린 뒤에 온다
MAX_ROOMS = int(os.environ.get("CALL_VOICE_MAX_ROOMS", "4"))             # 리턴제로 무료는 스트리밍 5줄까지(문서)
ROOM_SEC = int(os.environ.get("CALL_VOICE_ROOM_SEC", "600"))
OPENS_PER_HOUR = int(os.environ.get("CALL_VOICE_OPENS_PER_HOUR", "40"))
IDLE_SEC = 90                                                            # 양쪽 다 이만큼 소식이 없으면 방을 닫는다
rooms, opens, lock = {}, [], threading.Lock()


# ---- 방 (전화 회선도 이 셋을 부른다)
def open_room():
    """방을 연다 → 방 이름. 꽉 찼으면 None."""
    now = time.time()
    with lock:
        _reap(now)
        opens[:] = [t for t in opens if now - t < 3600]
        if len(rooms) >= MAX_ROOMS or len(opens) >= OPENS_PER_HOUR:
            return None
        rid = secrets.token_hex(3)
        rooms[rid] = {"at": now, "last": now, "stt": None, "events": [], "says": [], "played": 0, "down": False, "picked": False}
        opens.append(now)
        return rid


def join(r, rate=16000, encoding="LINEAR16"):
    """소리 쪽이 붙는다: 그 소리 꼴로 받아쓰기를 연다. 전화 회선이면 rate=8000 · encoding="MULAW"."""
    if r["stt"]:
        r["stt"].close()
    r["stt"] = STT(lambda final, text: r["events"].append({"final": final, "text": text}), rate=rate, encoding=encoding)
    r["down"], r["bps"] = False, rate * (1 if encoding in ("MULAW", "ALAW") else 2)      # 1초의 바이트 수


def feed(r, pcm):
    """소리 한 토막을 받아쓰기에 넣는다."""
    try:
        r["stt"].feed(pcm)
    except Exception as e:  # noqa: BLE001  받아쓰기가 끊겨도 통화 화면은 살아 있게
        if not r["down"]:
            print(f"받아쓰기에 소리를 넣지 못함: {type(e).__name__}")
        r["down"] = True


def says(r, since):
    """읽어 줄 말 가운데 since번 뒤의 것."""
    return [{"n": i + 1, "text": t} for i, t in enumerate(r["says"]) if i >= since]


def _reap(now):
    for rid, r in list(rooms.items()):
        if now - r["last"] > IDLE_SEC or now - r["at"] > ROOM_SEC:
            if r["stt"]:
                r["stt"].close()
            del rooms[rid]


# ---- 읽어 주기: 미리 만든 파일만 튼다(web/voice/tts/<글의 sha1 앞 12자>.mp3. 레포에 넣지 않는다). 실시간 음성 합성은 아직 꽂지 않았다
def tts_name(text):
    return hashlib.sha1(" ".join(text.split()).encode("utf-8")).hexdigest()[:12] + ".mp3"


def _say(h, text):
    f = WEB / "voice" / "tts" / tts_name(text)
    if not text or not f.is_file():
        return h.send_json({"error": "미리 만든 음성 없음"}, 404)
    body = f.read_bytes()
    h.send_response(200)
    h.send_header("Content-Type", "audio/mpeg")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


# ---- HTTP 길 (/api/voice/…)
def _int(q, k, lo, hi, d):
    try:
        return max(lo, min(hi, int(q.get(k, d))))
    except ValueError:
        return d


def _api(h, body):
    u = urlsplit(h.path)
    p, q = u.path[len("/api/voice/"):], {k: v[0] for k, v in parse_qs(u.query).items()}
    if p == "info":
        return h.send_json({"on": True, "stt": STT.name, "tts": TTS, "ask": ASK, "gap_ms": GAP_MS, "code": bool(CODE), "room_sec": ROOM_SEC})
    if p == "say":
        return _say(h, q.get("text", "")[:500])
    try:
        b = json.loads(body.decode("utf-8")) if body and p in ("room", "ask", "fake") else {}
    except ValueError:
        b = {}
    if not isinstance(b, dict):
        b = {}
    if p == "room":                             # 화면 쪽이 통화를 연다
        if CODE and not hmac.compare_digest(str(b.get("code", "")).encode(), CODE.encode()):
            return h.send_json({"error": "접근 코드가 다릅니다."}, 403)
        rid = open_room()
        return h.send_json({"room": rid}) if rid else h.send_json({"error": "지금은 통화가 꽉 찼습니다. 잠시 뒤에 다시 해 주세요."}, 429)
    with lock:
        _reap(time.time())
        r = rooms.get(q.get("room", ""))
        if r:
            r["last"] = time.time()
    if not r:
        return h.send_json({"error": "끝난 통화입니다."}, 404)
    text = " ".join(str(b.get("text", "")).split())[:500]
    if p == "join":                             # 소리 쪽이 붙는다(마이크의 표본화 주파수를 그대로 알린다. 서버에서 바꾸지 않는다)
        try:
            join(r, _int(q, "rate", 8000, 48000, 16000), q.get("enc") if q.get("enc") in ("MULAW", "ALAW") else "LINEAR16")
        except Exception as e:  # noqa: BLE001  받아쓰기에 닿지 못함(열쇠 · 망)
            print(f"받아쓰기를 열지 못함: {type(e).__name__}")
            return h.send_json({"error": "받아쓰기에 닿지 못했습니다."}, 502)
        return h.send_json({"ok": True, "stt": STT.name})
    if p == "audio":                            # 소리 쪽: 소리 한 토막(없어도 됨)을 넣고, 읽어 줄 말을 받아 간다
        if body and r["stt"]:
            feed(r, body)
        r["played"] = max(r["played"], _int(q, "played", 0, 10**6, 0))
        return h.send_json({"says": says(r, _int(q, "says", 0, 10**6, 0)), "down": r["down"], "picked": r["picked"]})
    if p == "fake":                             # 소리 쪽(가짜 받아쓰기일 때만 뜻이 있다): 이 글을 「말한다」
        if r["stt"] and text:
            r["stt"].speak(text)
        return h.send_json({"ok": True})
    if p == "desk":                             # 화면 쪽: 받아쓴 글을 받아 간다
        if r["stt"]:
            r["stt"].pump()
        since = _int(q, "since", 0, 10**6, 0)
        ev = r["events"][since:]
        return h.send_json({"events": ev, "next": since + len(ev), "joined": bool(r["stt"]), "played": r["played"], "heard_sec": round(r["stt"].heard / r["bps"], 2) if r["stt"] else 0, "down": r["down"]})
    if p == "pick":                             # 화면 쪽: 전화를 받았다(거는 쪽의 연결음이 그친다)
        r["picked"] = True
        return h.send_json({"ok": True})
    if p == "ask":                              # 화면 쪽: 이 말을 읽어 달라
        if text:
            r["says"].append(text)
        return h.send_json({"n": len(r["says"])})
    if p == "end":
        with lock:
            r["last"] = 0
            _reap(time.time())
        return h.send_json({"ok": True})
    return h.send_json({"error": "없는 길"}, 404)


def attach(Handler):
    """server.py의 Handler에 /api/voice/… 를 얹고, 첫 화면에 voice.js를 끼운다. 기존 파일(index.html · call.js)은 그대로 둔다."""
    get, post = Handler.do_GET, Handler.do_POST

    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/api/voice/"):
            return _api(self, b"")
        if p in ("/", "/index.html"):
            body = (WEB / "index.html").read_text(encoding="utf-8").replace("</body>", '<script src="voice.js"></script>\n</body>').encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        return get(self)

    def do_POST(self):
        if not self.path.startswith("/api/voice/"):
            return post(self)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > 1_000_000:                       # 0.25초 토막은 수십 KB다
            return self.send_json({"error": "너무 큼"}, 413)
        return _api(self, self.rfile.read(n) if n > 0 else b"")

    Handler.do_GET, Handler.do_POST = do_GET, do_POST
    print(f"음성 통화 켬: 받아쓰기 {STT.name} · 읽어 주기 {TTS}" + (" · 접근 코드 받음" if CODE else ""))
