"""받아쓰기를 꽂는 자리. 소리(한 줄기)를 받아 「도중 글 · 확정 글」을 emit(확정인가, 글)으로 낸다.
Fake 말고는 업스테이지가 아닌 모델이다: 개발 실험 · 영상 제작용이고, 운영사무국 답 전까지 배포 · 채점에 쓰지 않는다(docs/decisions.md 11-19). 기본은 Fake.

  Fake  열쇠 없이 흐름을 맞추는 가짜. 소리는 양만 세고, speak(글)로 받은 글을 말하는 빠르기로 흘려보낸다(대본 글 · 손으로 친 글).
  Eleven  일레븐랩스 실시간 받아쓰기(Scribe). 동규 11/18: 먼저 이것으로(LLMOps 과제에서 써 본 것), 안 되면 Whisper로. 지명을 미리 알려 줄 수 있다(keyterms 50개까지).
        열쇠: ~/.config/gg-team/elevenlabs.env 의 ELEVENLABS_API_KEY (ELEVENLABS_ENV_FILE로 다른 파일을 가리킬 수 있다. 값은 찍지 않는다). 업스테이지 모델이 아니다 → 스위치로만.
        규격(2026-11-18에 읽음): https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime
  Whisper  이 컴퓨터 안에서 도는 받아쓰기(mlx_whisper, turbo 모델. 애플 실리콘 맥에서만). 가입 · 돈이 없고 소리가 밖으로 나가지 않는다.
        스트리밍 모델이 아니라서, 말소리가 이어지는 동안 1초쯤마다 그때까지의 소리를 다시 받아써 도중 글을 내고, 0.7초 조용해지면 그 마디를 확정한다.
        말소리가 없는 소리는 받아쓰지 않는다(조용한 소리에서 「감사합니다.」 같은 글을 지어내기 때문. 56번 9-2절). 업스테이지 모델이 아니다 → 스위치로만.
  Rtzr  리턴제로 스트리밍 받아쓰기(한국어 전화용 sommers_ko · CALL). 업스테이지 모델이 아니다 → 스위치(CALL_VOICE=1)와 열쇠가 둘 다 있을 때만 쓴다.
        열쇠: ~/.config/gg-team/rtzr.env 의 RTZR_CLIENT_ID · RTZR_CLIENT_SECRET (또는 같은 이름의 환경 변수). 값은 찍지 않는다.
        규격(2026-11-18에 읽음): https://developers.rtzr.ai/docs/stt-streaming/websocket/ · https://developers.rtzr.ai/docs/authentications/
모두 같은 꼴이다: feed(소리 바이트) · speak(글) · pump() · close() (+ 있으면 hint(지명들)).  고르기는 pick().
"""
import base64
import json
import os
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

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


# ---- 이 컴퓨터 안에서 도는 받아쓰기 (mlx_whisper)
WHISPER_MODEL = os.environ.get("CALL_VOICE_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
WHISPER_PROMPT = os.environ.get("CALL_VOICE_WHISPER_PROMPT", "")       # 미리 알려 주는 말(지명 등). 기본은 없음: 말 없는 소리가 새어 들면 이 글의 지명을 지어내기 때문(56번 9-2절)
VAD = float(os.environ.get("CALL_VOICE_VAD", "0.012"))                 # 이보다 큰 소리(0~1, 30ms의 평균 크기)를 말소리로 본다. 실제 마이크로 맞춘 값이 아니다
END_SIL, MIN_SPEECH, PARTIAL_SEC, MAX_SEC = 0.7, 0.2, 1.0, 25.0        # 마디를 끝내는 조용한 초 · 마디로 치는 가장 짧은 말소리 · 도중 글 간격 · 한 마디의 가장 긴 초
_jobs = queue.Queue()
_worker = None
# 받아쓰기는 숫자를 한글로 적을 때가 있다(「상도 일동 주민센터」 · 「삼번 출구」). 지명 표는 숫자로 적혀 있어 그대로는 못 찾는다 → 지명에 쓰이는 세 꼴만 숫자로 고친다.
# ponytail: 1~20, 「○동 + 기관」 · 「○번 출구」 · 「○호선」만. 「이동 중」 같은 말을 건드리지 않으려고 좁게 잡았다. 제자리는 지명 찾기(gaz.py)가 한글 숫자도 읽는 것이다
_N = {w: n for n, w in enumerate("일 이 삼 사 오 육 칠 팔 구 십 십일 십이 십삼 십사 십오 십육 십칠 십팔 십구 이십".split(), 1)}
_NW = "(" + "|".join(sorted(_N, key=len, reverse=True)) + ")"
_NUM_FIX = [(re.compile(_NW + r"동(?= ?(?:주민센터|행정복지센터|주민자치|우체국|파출소|치안센터|지구대|경로당))"), "동"), (re.compile(_NW + r"번 ?출구"), "번 출구"), (re.compile(_NW + r"호선"), "호선")]


def digits(text):
    for rx, tail in _NUM_FIX:
        text = rx.sub(lambda m: f"{_N[m.group(1)]}{tail}", text)
    return text


def _whisper_loop():      # 모델은 한 스레드에서만 올리고 쓴다(한 번에 한 마디). 받아 둔 모델만 쓴다: 없으면 내려받지 않고 멈춘다
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import mlx_whisper
    while True:
        inst, final, audio, rate = _jobs.get()
        try:
            x = audio.astype(np.float32) / 32768
            if rate != 16000:      # ponytail: 고르게 잇는 단순한 길(걸러 내기 없음). 받아쓰기에는 충분했다. 소리 질이 문제면 제대로 된 바꾸기로
                x = np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x).astype(np.float32)
            r = mlx_whisper.transcribe(x, path_or_hf_repo=WHISPER_MODEL, language="ko", initial_prompt=WHISPER_PROMPT or None, condition_on_previous_text=False, temperature=0.0)
            text = digits(" ".join(r["text"].split()))
            if any(s.get("compression_ratio", 0) > 2.4 for s in r.get("segments") or []):
                text = ""              # 같은 말을 되풀이한 글(지어낸 것)은 버린다
            if inst is not None and text and not inst.closed:
                inst.emit(final, text)
        except Exception as e:  # noqa: BLE001  한 마디가 실패해도 다음 마디는 받는다
            print(f"로컬 받아쓰기 실패: {type(e).__name__}: {str(e)[:120]}")
        finally:
            if inst is not None:
                inst.busy = False


def whisper_warm():
    """받아쓰기 스레드를 띄우고 모델을 미리 올린다(첫 마디가 5초쯤 늦지 않게)."""
    global _worker
    if _worker is None:
        _worker = threading.Thread(target=_whisper_loop, daemon=True)
        _worker.start()
        _jobs.put((None, True, np.zeros(8000, np.int16), 16000))


class Whisper:
    name = "whisper"

    def __init__(self, emit, rate=16000, encoding="LINEAR16"):
        if encoding == "ALAW":
            raise ValueError("로컬 받아쓰기는 LINEAR16 · MULAW만 받는다")
        whisper_warm()
        self.emit, self.rate, self.mulaw, self.heard, self.closed, self.busy = emit, int(rate), encoding == "MULAW", 0, False, False
        self.n = int(self.rate * 0.03)                       # 30ms 한 토막
        self.rest = np.zeros(0, np.int16)                    # 토막이 안 된 나머지
        self.pre = np.zeros(0, np.int16)                     # 말소리 직전 0.3초(말머리가 잘리지 않게)
        self.buf, self.speech, self.quiet, self.sent = [], 0.0, 0.0, 0      # 지금 마디의 소리 · 말소리였던 초 · 마지막 말소리 뒤 조용한 초 · 도중 글을 낸 때의 길이
        self.lock = threading.Lock()

    def feed(self, pcm):
        self.heard += len(pcm)
        if self.mulaw:
            import audioop      # ponytail: 파이썬 3.13에서 빠진 꾸러미. 전화 회선(μ-law)을 붙일 때 3.13이면 표로 푼다
            pcm = audioop.ulaw2lin(pcm, 2)
        with self.lock:
            x = np.concatenate([self.rest, np.frombuffer(pcm[:len(pcm) // 2 * 2], np.int16)])
            cut = len(x) // self.n * self.n
            self.rest = x[cut:]
            for i in range(0, cut, self.n):
                f = x[i:i + self.n]
                loud = float(np.sqrt(np.mean((f.astype(np.float32) / 32768) ** 2))) >= VAD
                if loud:
                    if not self.buf:
                        self.buf.append(self.pre)
                    self.speech, self.quiet = self.speech + 0.03, 0.0
                if self.buf:
                    self.buf.append(f)
                    self.quiet += 0 if loud else 0.03
                else:
                    self.pre = np.concatenate([self.pre, f])[-int(self.rate * 0.3):]
            size = sum(len(b) for b in self.buf)
            if self.buf and (self.quiet >= END_SIL or size >= self.rate * MAX_SEC):       # 마디 끝
                if self.speech >= MIN_SPEECH:
                    self.busy = True
                    _jobs.put((self, True, np.concatenate(self.buf), self.rate))
                self.buf, self.speech, self.quiet, self.sent, self.pre = [], 0.0, 0.0, 0, np.zeros(0, np.int16)
            elif self.buf and not self.busy and self.speech >= 0.5 and size - self.sent >= self.rate * PARTIAL_SEC:      # 도중 글(앞의 것이 아직 도는 중이면 건너뛴다)
                self.busy, self.sent = True, size
                _jobs.put((self, False, np.concatenate(self.buf), self.rate))

    def speak(self, text):
        pass

    def pump(self):
        pass

    def close(self):
        self.closed = True


# ---- 일레븐랩스 실시간 받아쓰기 (Scribe)
ELEVEN_WS = os.environ.get("ELEVENLABS_WS_BASE", "wss://api.elevenlabs.io")
ELEVEN_ENV = Path(os.environ.get("ELEVENLABS_ENV_FILE") or Path.home() / ".config" / "gg-team" / "elevenlabs.env")
ELEVEN_STT_MODEL = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2_realtime")      # 또는 scribe_v3_live
ELEVEN_VAD_SEC = os.environ.get("ELEVENLABS_VAD_SILENCE_SECS", "0.8")                # 마디를 끊는 조용한 초. 일레븐랩스 기본은 1.5초라 길다. 0.8은 합성 목소리로 잰 값(56번 12절) — 사람 말은 중간 쉼이 길어 마디가 갈릴 수 있다. 비우면 일레븐랩스 기본값
used = {"stt_sec": 0.0, "stt_conn": 0, "tts_chars": 0, "tts_calls": 0}               # 일레븐랩스에 쓴 양(보고용): 보낸 소리의 초 · 연 줄 · 읽힌 글자 · 부른 횟수


def eleven_key():
    v = os.environ.get("ELEVENLABS_API_KEY", "")
    if ELEVEN_ENV.exists():
        for ln in ELEVEN_ENV.read_text(encoding="utf-8").splitlines():
            k, _, x = ln.strip().removeprefix("export ").partition("=")
            if k == "ELEVENLABS_API_KEY" and x.strip():
                v = x.strip().strip("\"'")
    return v


class Eleven:
    name = "elevenlabs"

    def __init__(self, emit, rate=16000, encoding="LINEAR16"):
        if encoding == "ALAW":
            raise ValueError("일레븐랩스 받아쓰기는 LINEAR16 · MULAW만 넘긴다")
        self.emit, self.heard, self.terms, self.closed, self.mulaw, self.rate = emit, 0, [], False, encoding == "MULAW", int(rate)
        self.out = 8000 if self.mulaw else self.rate if self.rate in (8000, 16000, 22050, 24000, 44100, 48000) else 16000      # 일레븐랩스가 받는 주파수가 아니면 16000으로 바꿔 보낸다
        self.lock = threading.Lock()
        self.ws = self._open()

    def _open(self):
        from websockets.sync.client import connect      # 이 길을 켤 때만 필요한 꾸러미(websockets 11 이상)
        q = [("model_id", ELEVEN_STT_MODEL), ("language_code", "ko"), ("audio_format", "ulaw_8000" if self.mulaw else f"pcm_{self.out}"), ("commit_strategy", "vad")]
        q += [("vad_silence_threshold_secs", ELEVEN_VAD_SEC)] if ELEVEN_VAD_SEC else []
        q += [("keyterms", t) for t in self.terms]
        ws = connect(ELEVEN_WS + "/v1/speech-to-text/realtime?" + urllib.parse.urlencode(q), additional_headers={"xi-api-key": eleven_key()}, open_timeout=10)
        first = json.loads(ws.recv(timeout=10))          # 첫 말이 session_started가 아니면(열쇠 · 받지 않는 설정) 이 줄은 못 쓴다
        if first.get("message_type") != "session_started":
            ws.close()
            raise ValueError(str(first.get("message_type")))
        self.config = first.get("config") or {}
        used["stt_conn"] += 1
        threading.Thread(target=self._recv, args=(ws,), daemon=True).start()
        return ws

    def _recv(self, ws):
        try:
            for msg in ws:               # {"message_type": "partial_transcript" | "committed_transcript" | "session_started" | …_error, "text"}
                d = json.loads(msg)
                kind, text = d.get("message_type") or "", digits(" ".join(str(d.get("text") or "").split()))
                if kind in ("partial_transcript", "committed_transcript") and text:
                    self.emit(kind == "committed_transcript", text)
                elif "error" in kind or kind in ("quota_exceeded", "rate_limited", "queue_overflow", "resource_exhausted", "unaccepted_terms", "commit_throttled", "session_time_limit_exceeded", "chunk_size_exceeded"):
                    print(f"일레븐랩스 받아쓰기: {kind}")      # 종류만 찍는다(받은 글 전체는 찍지 않는다)
        except Exception as e:  # noqa: BLE001  끊기면 그 통화의 받아쓰기만 멈춘다
            if ws is self.ws and not self.closed:
                print(f"일레븐랩스 받아쓰기 끊김: {type(e).__name__}")

    def feed(self, pcm):
        if not pcm:
            return
        self.heard += len(pcm)
        if not self.mulaw and self.out != self.rate:
            x = np.frombuffer(pcm[:len(pcm) // 2 * 2], np.int16).astype(np.float32)
            pcm = np.interp(np.arange(0, len(x), self.rate / self.out), np.arange(len(x)), x).astype(np.int16).tobytes()
        used["stt_sec"] += len(pcm) / (self.out * (1 if self.mulaw else 2))
        with self.lock:
            self.ws.send(json.dumps({"message_type": "input_audio_chunk", "audio_base_64": base64.b64encode(pcm).decode(), "commit": False, "sample_rate": self.out}))

    def hint(self, terms):
        """지금 나올 법한 지명을 미리 알려 준다(50개 · 20자까지). 연결할 때만 줄 수 있어, 목록이 바뀌면 줄을 새로 연다(읽어 주는 동안이라 말이 끊기지 않는다)."""
        terms = list(dict.fromkeys(t for t in (" ".join(str(x).split()) for x in terms) if 2 <= len(t) <= 20))[:50]      # 20자를 넘는 이름은 자르지 않고 뺀다(일레븐랩스가 줄 전체를 거절한다)
        if terms == self.terms or self.closed:
            return
        with self.lock:
            old, was, self.terms = self.ws, self.terms, terms
            try:
                self.ws = self._open()
            except Exception as e:  # noqa: BLE001  새 줄을 못 열면 쓰던 줄로 계속 간다
                self.terms = was
                print(f"일레븐랩스에 지명을 알려 주지 못함: {type(e).__name__}: {str(e)[:40]}")
                return
        try:
            old.close()
        except Exception:  # noqa: BLE001  이미 끊긴 연결
            pass

    def speak(self, text):
        pass

    def pump(self):
        pass

    def close(self):
        self.closed = True
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001  이미 끊긴 연결
            pass


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
    """쓸 받아쓰기. CALL_VOICE_STT=fake|elevenlabs|whisper|rtzr 로 정한다. 비워 두면 fake(밖의 서비스를 부르거나 무거운 모델을 올리는 일은 이름을 대야만 한다)."""
    want = os.environ.get("CALL_VOICE_STT") or "fake"
    if want == "elevenlabs" and not eleven_key():
        raise SystemExit(f"CALL_VOICE_STT=elevenlabs 인데 열쇠가 없다({ELEVEN_ENV} 에 ELEVENLABS_API_KEY, 또는 ELEVENLABS_ENV_FILE로 파일을 가리킨다)")
    if want == "rtzr" and not has_keys():
        raise SystemExit(f"CALL_VOICE_STT=rtzr 인데 열쇠가 없다({RTZR_ENV} 에 RTZR_CLIENT_ID · RTZR_CLIENT_SECRET)")
    if want == "whisper":
        whisper_warm()
    return {"elevenlabs": Eleven, "rtzr": Rtzr, "whisper": Whisper}.get(want, Fake)
