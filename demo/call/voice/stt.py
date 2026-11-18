"""받아쓰기를 꽂는 자리. 소리(한 줄기)를 받아 「도중 글 · 확정 글」을 emit(확정인가, 글)으로 낸다.

  Fake  열쇠 없이 흐름을 맞추는 가짜. 소리는 양만 세고, speak(글)로 받은 글을 말하는 빠르기로 흘려보낸다(대본 글 · 손으로 친 글).
  Rtzr  리턴제로 스트리밍 받아쓰기(한국어 전화용 sommers_ko · CALL). 업스테이지 모델이 아니다 → 스위치(CALL_VOICE=1)와 열쇠가 둘 다 있을 때만 쓴다.
        열쇠: ~/.config/gg-team/rtzr.env 의 RTZR_CLIENT_ID · RTZR_CLIENT_SECRET (또는 같은 이름의 환경 변수). 값은 찍지 않는다.
        규격(2026-11-18에 읽음): https://developers.rtzr.ai/docs/stt-streaming/websocket/ · https://developers.rtzr.ai/docs/authentications/
둘 다 같은 꼴이다: feed(소리 바이트) · speak(글) · pump() · close().  고르기는 pick().
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

FAKE_CPS = float(os.environ.get("CALL_VOICE_FAKE_CPS", "9"))            # 가짜 받아쓰기가 글을 흘리는 빠르기(초당 글자). 사람 말은 대략 초당 5~7자, 받아쓰기는 낱말째 뜬다
RTZR_API = os.environ.get("RTZR_API_BASE", "https://openapi.vito.ai")    # 점검(check_voice.py)이 가짜 서버로 바꿔 끼운다
RTZR_ENV = Path(os.environ.get("RTZR_ENV_FILE") or Path.home() / ".config" / "gg-team" / "rtzr.env")


class Fake:
    name = "fake"

    def __init__(self, emit, rate=16000, encoding="LINEAR16"):
        self.emit, self.job, self.heard = emit, None, 0

    def feed(self, pcm):
        self.heard += len(pcm)                # 소리는 양만 센다(마이크 → 서버 길이 살아 있는지 보는 데 쓴다)

    def speak(self, text):
        self.job = [text, time.monotonic(), 0]      # 글 · 말하기 시작한 때 · 이미 낸 글자 수

    def pump(self):                           # 화면이 물어볼 때마다 그때까지 「말한」 만큼 낸다(스레드 없이)
        if not self.job:
            return
        text, t0, sent = self.job
        cut = text.rfind(" ", 0, int((time.monotonic() - t0) * FAKE_CPS) + 1)      # 낱말이 끝난 곳까지만(받아쓰기는 낱말째 뜬다)
        if (time.monotonic() - t0) * FAKE_CPS >= len(text):
            self.job = None
            self.emit(True, text)
        elif cut > sent:
            self.job[2] = cut
            self.emit(False, text[:cut])

    def close(self):
        pass


def _keys():
    got = {k: os.environ.get(k, "") for k in ("RTZR_CLIENT_ID", "RTZR_CLIENT_SECRET")}
    if RTZR_ENV.exists():
        for ln in RTZR_ENV.read_text(encoding="utf-8").splitlines():
            k, _, v = ln.strip().removeprefix("export ").partition("=")
            if k in got and v.strip():
                got[k] = v.strip().strip("\"'")
    return got["RTZR_CLIENT_ID"], got["RTZR_CLIENT_SECRET"]


def has_keys():
    return all(_keys())


_tok = {"v": None, "until": 0}
_tok_lock = threading.Lock()


def _token():      # 토큰은 6시간 간다(문서). 5시간 쓰고 새로 받는다
    with _tok_lock:
        if _tok["v"] and time.time() < _tok["until"]:
            return _tok["v"]
        cid, sec = _keys()
        req = urllib.request.Request(RTZR_API + "/v1/authenticate", urllib.parse.urlencode({"client_id": cid, "client_secret": sec}).encode(), {"accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        _tok.update(v=d["access_token"], until=min(time.time() + 5 * 3600, float(d.get("expire_at") or 9e18) - 600))
        return _tok["v"]


class Rtzr:
    name = "rtzr"

    def __init__(self, emit, rate=16000, encoding="LINEAR16"):      # 전화 회선은 rate=8000 · encoding="MULAW" 그대로 넘기면 된다(문서: 8000~48000Hz, MULAW · ALAW 받음)
        from websockets.sync.client import connect      # 이 길을 켤 때만 필요한 꾸러미(websockets 11 이상)
        self.emit, self.heard = emit, 0
        q = urllib.parse.urlencode({"sample_rate": int(rate), "encoding": encoding, "model_name": "sommers_ko", "domain": "CALL", "use_itn": "true", "use_punctuation": "true"})
        self.ws = connect(RTZR_API.replace("http", "ws", 1) + "/v1/transcribe:streaming?" + q, additional_headers={"Authorization": "bearer " + _token()}, open_timeout=10)
        threading.Thread(target=self._recv, daemon=True).start()

    def _recv(self):
        try:
            for msg in self.ws:               # {"seq", "start_at", "duration", "final", "alternatives": [{"text", "confidence", "words"}]}
                d = json.loads(msg)
                text = ((d.get("alternatives") or [{}])[0].get("text") or "").strip()
                if text:
                    self.emit(bool(d.get("final")), text)
        except Exception as e:  # noqa: BLE001  끊기면 그 통화의 받아쓰기만 멈춘다
            print(f"리턴제로 받아쓰기 끊김: {type(e).__name__}")

    def feed(self, pcm):
        self.heard += len(pcm)
        self.ws.send(pcm)

    def speak(self, text):                    # 진짜 받아쓰기는 글을 받지 않는다(소리만)
        pass

    def pump(self):
        pass

    def close(self):
        try:
            self.ws.send("EOS")
            self.ws.close()
        except Exception:  # noqa: BLE001  이미 끊긴 연결
            pass


def pick():
    """쓸 받아쓰기. CALL_VOICE_STT=fake|rtzr 로 정하고, 비워 두면 열쇠가 있을 때만 rtzr."""
    want = os.environ.get("CALL_VOICE_STT") or ("rtzr" if has_keys() else "fake")
    if want == "rtzr" and not has_keys():
        raise SystemExit(f"CALL_VOICE_STT=rtzr 인데 열쇠가 없다({RTZR_ENV} 에 RTZR_CLIENT_ID · RTZR_CLIENT_SECRET)")
    return Rtzr if want == "rtzr" else Fake
