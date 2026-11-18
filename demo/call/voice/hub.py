"""음성 통화의 가운데 자리. server.py가 스위치(CALL_VOICE=1)일 때만 붙인다. 기본은 끔이고, 끄면 이 파일은 읽히지도 않는다.

전화 한 통 = 방 하나. 방에는 두 쪽이 붙는다.
  소리 쪽(거는 사람)   소리를 넣고(feed), 읽어 줄 말을 받아 간다(says)    ← 지금: 브라우저 마이크(web/dial.html · voice.js). 나중: 전화 회선이 이 자리에 온다
  화면 쪽(상담 화면)   받아쓴 글을 받아 가고(events), 읽어 줄 말을 넣는다(ask) ← web/voice.js가 받아 적기 칸에 올리고, 확정 글을 지금의 /api/turn에 그대로 넣는다
위치 좁히기 · 질문 고르기 · 조례 답은 건드리지 않는다. 이 파일은 소리와 글을 나르기만 한다.

전화 회선을 붙일 때는 회선이 준 소리로 join() · feed()를 부르고, says()로 읽어 줄 말을 가져가 회선에 틀면 된다(HTTP 길은 그 셋을 부를 뿐이다).

| 환경 변수 | 뜻 | 기본 |
| CALL_VOICE | 1이면 켠다 | 끔 |
| CALL_VOICE_STT | fake(대본 글 · 친 글을 흘림) · elevenlabs(일레븐랩스 실시간 받아쓰기) · whisper(이 컴퓨터 안의 받아쓰기, 가입 없음) · rtzr(리턴제로) | fake |
| CALL_VOICE_TTS | 읽어 주기. none(소리 없이 글 길이만큼 기다림) · elevenlabs(일레븐랩스 음성 합성. 만든 소리는 web/voice/tts/에 남겨 다시 쓴다) · browser(기기에 든 읽어 주기). web/voice/tts/에 이미 파일이 있으면 그것이 먼저 | none |
| ELEVENLABS_TTS_MODEL · ELEVENLABS_VOICE_ID | 음성 합성 모델 · 목소리 | eleven_multilingual_v2 · 「나의 우주」의 기본 목소리 |
| CALL_VOICE_ASK | 질문을 누가 말하나. ai(화면이 띄운 질문을 읽어 준다) · agent(상담사가 직접 말한다. 읽어 주지 않는다). 주소 ?ask= 로도 바꾼다 | ai |
| CALL_VOICE_CODE | 값이 있으면 통화를 열 때 이 접근 코드를 받는다(밖에 내놓을 때) | 없음 |
| CALL_VOICE_GAP_MS | 확정 글 뒤 이만큼 조용하면 한 차례로 끊는다 | 900 (whisper · elevenlabs는 300) |
| ELEVENLABS_CITIZEN_VOICE_ID | 「대본을 음성 길로」에서 시민 역 목소리(tts_lines.py --citizen이 만든다) | 「나의 우주」의 '부드러운' |
| CALL_VOICE_MAX_ROOMS · CALL_VOICE_ROOM_SEC · CALL_VOICE_OPENS_PER_HOUR | 한꺼번에 열리는 통화 수 · 한 통화의 최대 초 · 한 시간에 여는 횟수 | 4 · 600 · 40 |
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import stt

WEB = Path(__file__).resolve().parents[1] / "web"
CODE = os.environ.get("CALL_VOICE_CODE", "")
TTS = os.environ.get("CALL_VOICE_TTS") if os.environ.get("CALL_VOICE_TTS") in ("browser", "elevenlabs") else "none"
ELEVEN_API = os.environ.get("ELEVENLABS_API_BASE", "https://api.elevenlabs.io")
TTS_MODEL = os.environ.get("ELEVENLABS_TTS_MODEL") or "eleven_multilingual_v2"      # LLMOps 과제(「나의 우주」)와 그 시연 영상이 쓴 모델
TTS_VOICE = os.environ.get("ELEVENLABS_VOICE_ID") or "JBFqnCBsd6RMkjVDRZzb"        # 「나의 우주」의 기본 목소리 '따뜻한'(LLMOps 시연 영상도 이 목소리). 어느 목소리로 할지는 동규가 정한다
CITIZEN_VOICE = os.environ.get("ELEVENLABS_CITIZEN_VOICE_ID") or "EXAVITQu4vr4xnSDxMaL"     # 시민 역('부드러운'). 대본 시연용 소리 파일을 만들 때만 쓴다
ASK = "agent" if os.environ.get("CALL_VOICE_ASK") == "agent" else "ai"      # 질문을 누가 말하나: ai = 화면이 띄운 질문을 읽어 준다 · agent = 상담사가 직접 말한다(읽어 주지 않는다)
STT = stt.pick()
GAP_MS = int(os.environ.get("CALL_VOICE_GAP_MS") or (300 if STT.name in ("whisper", "elevenlabs") else 900))      # 이 둘은 확정 글이 이미 조용함을 기다린 뒤에 온다
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


# ---- 읽어 주기: web/voice/tts/<글의 sha1 앞 12자>.mp3 를 튼다(레포에 넣지 않는다). 파일이 없고 CALL_VOICE_TTS=elevenlabs면 그 자리에서 만들어 남긴다
asked, tts_lock = set(), threading.Lock()      # 통화에서 읽어 달라고 한 글만 새로 만든다(아무 글이나 보내 열쇠를 쓰게 하지 못하게)


def tts_name(text):
    return hashlib.sha1(" ".join(text.split()).encode("utf-8")).hexdigest()[:12] + ".mp3"


def synth(text, voice=None, fmt="mp3_44100_128"):
    """일레븐랩스 음성 합성 → 소리 바이트(fmt: mp3_44100_128 · pcm_16000 등). 목소리 설정은 LLMOps 시연 영상의 값 그대로."""
    req = urllib.request.Request(f"{ELEVEN_API}/v1/text-to-speech/{voice or TTS_VOICE}?output_format={fmt}",
                                 json.dumps({"text": text, "model_id": TTS_MODEL, "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.2}}).encode(),
                                 {"xi-api-key": stt.eleven_key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    stt.used["tts_chars"] += len(text)
    stt.used["tts_calls"] += 1
    return body


def tts_file(text, make=False):
    """그 글의 음성 파일. 없으면 make일 때만 만들어 남긴다. → 파일 또는 None"""
    text = " ".join(text.split())
    f = WEB / "voice" / "tts" / tts_name(text)
    if f.is_file() or not (text and make and TTS == "elevenlabs" and stt.eleven_key()):
        return f if f.is_file() else None
    with tts_lock:
        if not f.is_file():
            try:
                body = synth(text)
            except Exception as e:  # noqa: BLE001  못 만들면 화면은 소리 없이 기다린다
                print(f"음성 합성 실패: {type(e).__name__}")
                return None
            f.parent.mkdir(exist_ok=True)
            f.write_bytes(body)
    return f


def citizen_file(text):
    """「대본을 음성 길로」의 시민 역 소리: web/voice/citizen/<글의 sha1 앞 12자>.wav (16kHz 한 줄기). 서버는 만들지 않고 있는 파일만 준다(tts_lines.py --citizen)."""
    return WEB / "voice" / "citizen" / tts_name(text).replace(".mp3", ".wav")


def _line(h, text):
    f = citizen_file(text)
    if not text or not f.is_file():
        return h.send_json({"error": "시민 음성 파일 없음"}, 404)
    body = f.read_bytes()
    h.send_response(200)
    h.send_header("Content-Type", "audio/wav")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def _say(h, text):
    f = tts_file(text, make=tts_name(text) in asked)
    if not f:
        return h.send_json({"error": "음성 파일 없음"}, 404)
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
        return h.send_json({"on": True, "stt": STT.name, "tts": TTS, "ask": ASK, "used": {k: round(v, 1) for k, v in stt.used.items()}, "gap_ms": GAP_MS, "code": bool(CODE), "room_sec": ROOM_SEC})
    if p == "say":
        return _say(h, q.get("text", "")[:500])
    if p == "line":
        return _line(h, q.get("text", "")[:500])
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
    if p == "ask":                              # 화면 쪽: 이 말을 읽어 달라(+ 지금 나올 법한 지명 → 받아쓰기에 미리 알려 준다)
        if text:
            r["says"].append(text)
            asked.add(tts_name(text))
        terms = b.get("terms")
        if isinstance(terms, list) and r["stt"] and hasattr(r["stt"], "hint"):
            try:
                r["stt"].hint(terms[:60])
            except Exception as e:  # noqa: BLE001  지명을 못 알려 줘도 통화는 간다
                print(f"지명을 알려 주지 못함: {type(e).__name__}")
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
