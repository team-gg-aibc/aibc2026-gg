"""070 다리: 전화 회선이 「소리 쪽」 자리에 들어온다. 스위치(CALL_VOICE_LINE), 기본 끔. 끄면 이 파일은 읽히지도 않는다.

휴대폰 전화 앱으로 070 번호에 걸면, 번호를 주는 곳(한국AI통신)이 통화 소리를 우리에게 보낸다.
이 다리는 그 소리를 hub.py의 방에 넣고(join · feed), 읽어 줄 말(says)을 전화 소리 꼴로 만들어 회선에 돌려보낸다.
상담 화면 · 위치 좁히기 · 조례 답은 그대로다. 상담 화면은 직접 통화 판(CALL_DIRECT=1 CALL_VOICE=1)이어야 기다리는 통화를 스스로 받는다.

회선을 잇는 길 둘(가운데 Line은 같다)
  CALL_VOICE_LINE=sdk  한국AI통신 SDK(꾸러미 koreaaitel, `import clawops`)가 우리 쪽에서 밖으로 연결한다. 밖에서 닿는 주소 · 포트가 필요 없다(맥북에서도 된다).
                       문서 https://platform.koreaaitel.com/docs/voice-agent (11/21 읽음). 통화마다 세션 하나: start(call) · feed_audio(μ-law) · stop(), 보낼 때 call.send_audio(μ-law)
  CALL_VOICE_LINE=1    VoiceML <Connect><Stream url="wss://…">가 우리 WebSocket으로 걸어 온다. 밖에서 닿는 wss 주소가 있어야 한다.
                       문서 https://platform.koreaaitel.com/docs/build/stream (11/21 읽음). 받는 것 start · media(base64) · mark · stop, 보내는 것 media · mark · clear
둘 다 소리는 G.711 μ-law 8000Hz 한 줄기다.

| 환경 변수 | 뜻 | 기본 |
| CALL_VOICE_LINE | sdk 또는 1(CALL_VOICE=1과 함께) | 끔 |
| CLAWOPS_API_KEY · CLAWOPS_ACCOUNT_ID · CALL_VOICE_LINE_FROM | (sdk) 한국AI통신 열쇠 · 계정 · 받을 070 번호. 환경 변수 또는 ~/.config/gg-team/koreaaitel.env(다른 파일이면 KOREAAITEL_ENV_FILE)에 한 줄씩. 레포에 넣지 않는다 | 없음 |
| CALL_VOICE_LINE_ALLOW | (sdk · 1 둘 다) 꼭 준다. 이 번호들(쉼표)에서 건 전화만 받고 나머지는 받기 전에 거절한다(밖의 사람은 전화로 들어오지 못하게, docs/decisions.md 11-21). 비어 있으면 다리가 뜨지 않는다. Stream 길은 회선이 거는 번호를 따로 주지 않으니 VoiceML이 `<Parameter name="from" value="거는 번호"/>`로 넘겨야 하고, 없거나 정해 둔 번호가 아니면 받지 않는다 | 없음(다리가 뜨지 않음) |
| CALL_VOICE_LINE_PORT · CALL_VOICE_LINE_HOST | (1) 다리가 듣는 포트 · 주소. 밖에서는 앞단이 wss(443)를 받아 이 포트로 넘긴다 | 8790 · 127.0.0.1 |
| CALL_VOICE_LINE_TOKEN | (1) 꼭 준다. start의 customParameters.token이 같아야 받는다(<Parameter name="token" value="…"/>). 회선 연결에는 서명이 없다. 토큰은 「회선이 보낸 연결인가」만 가리고 「누가 걸었나」는 못 가리니 ALLOW와 함께 본다. 비어 있으면 다리가 뜨지 않는다 | 없음(다리가 뜨지 않음) |

읽는 동안과 받기 전에는 회선 소리 대신 조용한 소리를 받아쓰기에 넣는다(브라우저 길의 「마이크 막기」와 같다). 다 읽은 뒤 더 막는 시간은 CALL_VOICE_TAIL_MS(hub.py).
"""
import asyncio
import base64
import hmac
import json
import os
import re
import threading
import time
from pathlib import Path

from . import hub

MODE = os.environ.get("CALL_VOICE_LINE", "")
PORT = int(os.environ.get("CALL_VOICE_LINE_PORT") or 8790)
HOST = os.environ.get("CALL_VOICE_LINE_HOST") or "127.0.0.1"
TOKEN = os.environ.get("CALL_VOICE_LINE_TOKEN", "")
ENV_FILE = Path(os.environ.get("KOREAAITEL_ENV_FILE") or Path.home() / ".config" / "gg-team" / "koreaaitel.env")
QUIET = b"\xff"          # μ-law의 0
BATCH = 1600             # 받아쓰기에는 0.2초씩 모아 넣는다(회선은 20ms씩 준다)
SEND = 3200              # 회선에는 0.4초씩 끊어 보낸다(회선이 20ms씩 맞춰 튼다)
sounds = {}              # 글 → 전화 소리 꼴(μ-law 8000Hz). 같은 말은 다시 만들지 않는다
digits = lambda s: re.sub(r"\D", "", str(s or ""))      # noqa: E731


def number(s):
    """전화번호를 한 꼴로: 숫자만, 나라 번호 82는 0으로(+82 10-… → 010…)."""
    d = digits(s)
    return "0" + d[2:] if d.startswith("82") else d


def allowed():
    """받을 번호들(CALL_VOICE_LINE_ALLOW)."""
    return {number(x) for x in os.environ.get("CALL_VOICE_LINE_ALLOW", "").split(",") if number(x)}


def permit(caller, allow):
    """이 번호에서 건 전화를 받나. 정해 둔 번호가 아니면(번호를 숨긴 전화 포함) 받지 않는다."""
    return bool(allow) and number(caller) in allow


def guard():
    """다리를 띄워도 되나 → 안 되면 까닭(되면 빈 글). 밖의 사람이 전화로 들어오지 못하게, 막는 값이 없으면 띄우지 않는다."""
    if not allowed():
        return "CALL_VOICE_LINE_ALLOW(받을 번호)가 비어 있다"
    return "" if MODE == "sdk" or TOKEN else "CALL_VOICE_LINE_TOKEN이 비어 있다"


def sound(text):
    if text not in sounds:
        sounds[text] = hub.synth(text, fmt="ulaw_8000")
    return sounds[text]


class Line:
    """전화 한 통의 가운데: 방 하나를 열어 회선 소리를 넣고, 읽어 줄 말을 회선에 튼다. 회선을 잇는 길(sdk · Stream)은 send · clear · hang만 준다.
    marks = 회선이 「거기까지 다 틀었다」를 알려 주나. 알려 주지 않으면 소리 길이만큼 기다린다."""

    def __init__(self, send, clear, hang, mark=None):
        self.send, self.clear, self.hang, self.mark = send, clear, hang, mark
        self.rid, self.r, self.buf, self.mute, self.mouth = None, None, b"", 0.0, None

    async def open(self):
        self.rid = hub.open_room(waiting=True)
        if not self.rid:
            print("070 다리: 방이 꽉 참")
            return False
        self.r = hub.rooms[self.rid]
        try:
            await asyncio.to_thread(hub.join, self.r, 8000, "MULAW")
        except Exception as e:  # noqa: BLE001  받아쓰기에 닿지 못함(열쇠 · 망)
            print(f"070 다리: 받아쓰기를 열지 못함: {type(e).__name__}")
            self.close()
            return False
        self.r["caller"], self.r["caller_at"] = True, time.time()
        self.mouth = asyncio.create_task(self.speak())
        print("070 다리: 전화가 왔다 → 상담 화면이 받기를 기다림")
        return True

    def hear(self, pcm):
        """회선이 준 소리 한 토막(μ-law)."""
        r, now = self.r, time.time()
        if not r:
            return
        r["last"] = r["caller_at"] = now
        self.buf += pcm if r["picked"] and now >= self.mute else QUIET * len(pcm)
        if len(self.buf) >= BATCH:
            hub.feed(r, self.buf)
            self.buf = b""

    def marked(self, n):
        """회선이 n번째 말까지 다 틀었다고 알렸다."""
        if self.r:
            self.r["played"] = max(self.r["played"], n)
            self.mute = time.time() + hub.TAIL_MS / 1000

    async def speak(self):      # 읽어 줄 말을 온 순서대로 회선에 튼다
        r, rid, seen, cut = self.r, self.rid, 0, self.r["cut"]
        while rid in hub.rooms:
            if r["cut"] > cut:                                    # 상담사가 넘겨받음: 틀던 소리를 버린다
                cut = r["cut"]
                await self.clear()
            for s in hub.says(r, seen):
                seen = s["n"]
                try:
                    audio = await asyncio.to_thread(sound, s["text"])
                except Exception as e:  # noqa: BLE001  못 만들면 그 말은 건너뛴다(화면에는 글이 있다)
                    print(f"070 다리: 음성 합성 실패: {type(e).__name__}")
                    r["played"] = max(r["played"], s["n"])
                    continue
                sec = len(audio) / 8000
                self.mute = time.time() + sec + hub.TAIL_MS / 1000
                for i in range(0, len(audio), SEND):
                    await self.send(audio[i:i + SEND])
                if self.mark:
                    await self.mark(s["n"])
                t0, wait = time.time(), sec + (1.5 if self.mark else 0.2)      # 회선이 알려 주지 않아도 소리 길이만큼만 기다린다
                while rid in hub.rooms and r["played"] < s["n"] and r["cut"] == cut and time.time() - t0 < wait:
                    await asyncio.sleep(0.05)
                r["played"] = max(r["played"], s["n"])
            await asyncio.sleep(0.1)
        await self.hang()                                         # 상담 화면이 통화를 마쳤다 → 회선을 놓는다

    def close(self):
        """회선이 끊겼다: HTTP 「end」와 같은 일(상담 화면이 곧 안다)."""
        if self.mouth:
            self.mouth.cancel()
        with hub.lock:
            if self.rid in hub.rooms:
                hub.rooms[self.rid]["last"] = 0
                hub._reap(time.time())
        self.r = None


# ---- 길 1: Stream(회선이 우리 WebSocket으로 걸어 온다)
async def stream(ws):
    """전화 한 통 = 연결 하나."""
    line = None
    try:
        async for raw in ws:
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            ev = m.get("event")
            if ev == "start" and not line:
                params = (m.get("start") or {}).get("customParameters") or {}
                got = str(params.get("token", ""))
                if not TOKEN or not hmac.compare_digest(got.encode(), TOKEN.encode()):
                    print("070 다리: 토큰이 달라 받지 않음")
                    return
                if not permit(params.get("from"), allowed()):      # 거는 번호를 모르거나 정해 두지 않은 번호면 방을 열지 않는다
                    print("070 다리: 정해 두지 않은 번호라 받지 않음")
                    return
                line = Line(lambda a: ws.send(json.dumps({"event": "media", "media": {"payload": base64.b64encode(a).decode()}})),
                            lambda: ws.send(json.dumps({"event": "clear"})), ws.close,
                            lambda n: ws.send(json.dumps({"event": "mark", "mark": {"name": f"say-{n}"}})))
                if not await line.open():
                    return
            elif ev == "media" and line:
                line.hear(base64.b64decode((m.get("media") or {}).get("payload", "")))
            elif ev == "mark" and line:
                name = str((m.get("mark") or {}).get("name", ""))
                if name.startswith("say-") and name[4:].isdigit():
                    line.marked(int(name[4:]))
            elif ev == "stop":
                break
    finally:
        if line:
            line.close()


async def serve_stream():
    try:
        from websockets.asyncio.server import serve      # websockets 13 이상
    except ImportError:
        from websockets import serve                     # 11 · 12
    async with serve(stream, HOST, PORT):
        print(f"070 다리: ws://{HOST}:{PORT} 에서 회선을 기다림")
        await asyncio.Future()


# ---- 길 2: 한국AI통신 SDK(우리 쪽에서 밖으로 잇는다)
class Session:
    """SDK가 통화마다 하나씩 만든다(문서의 Session 꼴). 모델은 없다: 소리를 방에 넣고, 방의 말을 회선에 튼다."""

    def __init__(self):
        self.line = None

    async def prewarm(self):
        pass

    async def start(self, call):
        self.line = Line(call.send_audio, call.clear_audio, call.hangup)
        if not await self.line.open():
            self.line = None
            await call.hangup()

    attach = start

    async def feed_audio(self, audio, timestamp=0):
        if self.line:
            self.line.hear(audio)

    async def feed_dtmf(self, digits_):
        pass

    async def stop(self):
        if self.line:
            self.line.close()
            self.line = None

    def get_telemetry(self):
        return None


def env_file():
    """열쇠 파일의 값을 환경 변수로(이미 있는 환경 변수가 먼저다)."""
    if ENV_FILE.exists():
        for ln in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, _, v = ln.strip().removeprefix("export ").partition("=")
            if k in ("CLAWOPS_API_KEY", "CLAWOPS_ACCOUNT_ID", "CALL_VOICE_LINE_FROM", "CALL_VOICE_LINE_ALLOW") and v.strip():
                os.environ.setdefault(k, v.strip().strip("\"'"))


async def serve_sdk():
    from clawops.agent import BuiltinTool, ClawOpsAgent
    allow = allowed()
    agent = ClawOpsAgent(from_=digits(os.environ.get("CALL_VOICE_LINE_FROM")), session_factory=Session, builtin_tools=BuiltinTool.NONE, prewarm_enabled=False)

    @agent.on_incoming
    async def screen(c):      # 우리만 걸게: 정해 둔 번호가 아니면 받기 전에 거절한다
        if not permit(c.from_number, allow):
            print("070 다리: 정해 두지 않은 번호라 받지 않음")
            await c.reject()

    await agent.connect()
    print(f"070 다리: 한국AI통신에 이어짐 · 받는 번호 끝자리 {digits(os.environ.get('CALL_VOICE_LINE_FROM'))[-4:]} · 받을 번호 {len(allow)}개")
    await asyncio.Future()


def run():
    if MODE == "sdk":
        env_file()
    why = guard()
    if why:
        print(f"070 다리를 띄우지 않음: {why}")
        return
    try:
        asyncio.run(serve_sdk() if MODE == "sdk" else serve_stream())
    except Exception as e:  # noqa: BLE001  다리가 못 떠도 화면 서버는 그대로 돈다
        print(f"070 다리가 뜨지 못함: {type(e).__name__}: {str(e)[:200]}")


def start():
    threading.Thread(target=run, daemon=True).start()
