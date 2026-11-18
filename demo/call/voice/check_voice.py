"""음성 통화 점검. 열쇠 · 인터넷 · 마이크 · 소리 없이 십여 초. 실패하면 종료 코드 1.

    OPENBLAS_NUM_THREADS=1 python3 demo/call/voice/check_voice.py

보는 것
  ① 스위치를 끄면 음성 길이 없다(/api/voice 404, 첫 화면에 voice.js 없음).
  ② 켜면: 방을 열고 → 소리 쪽이 붙고 → 대본 글을 소리 대신 흘리면(가짜 받아쓰기) 도중 글이 먼저 오고 확정 글이 온다
     → 그 글을 지금의 통화 길(/api/turn)에 넣으면 글로 넣었을 때와 같은 자리로 끝난다 → 화면이 띄운 질문이 소리 쪽에 읽어 줄 말로 건너간다.
     읽어 주기는 미리 만든 음성 파일이 있으면 그 파일을 주고, 없으면 404다.
  ③ 접근 코드가 틀리면 열리지 않고, 한꺼번에 여는 통화 수를 넘으면 거절한다.
  ④ 리턴제로 · 일레븐랩스 받아쓰기 코드가 문서의 규격대로 말을 주고받는다(이 컴퓨터 안의 가짜 서버와. 진짜 서비스는 부르지 않는다).
     일레븐랩스: 지명을 알려 주면 줄을 새로 열어 keyterms로 넘긴다.
  ⑤ 일레븐랩스 음성 합성: 통화에서 읽어 달라고 한 글만 만들고, 만든 소리는 남겨 다시 쓴다(가짜 서버와).
  ⑥ 휴대폰이 먼저 거는 통화: 방이 「기다림」으로 열리고 한 화면만 받는다. 휴대폰은 글로만 붙어(받아쓰기 없음) 친 글을 보내고, 상담사 말을 받는다.
"""
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("CALL_CHECK_PORT", "8782"))
BASE = f"http://127.0.0.1:{PORT}"
SCENE = "cat_street"


def call(path, body=None, raw=None):
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(BASE + path, data, {"Content-Type": "application/json"}), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def code_of(path, body=None):
    try:
        call(path, body)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


def server(**env):
    for port in range(PORT, PORT + 5):                    # 그 포트에 다른 서버가 떠 있으면 그 서버를 점검하게 된다 → 비어 있을 때만 시작한다
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", port)) != 0, f"포트 {port}를 다른 프로그램이 쓰고 있다. CALL_CHECK_PORT로 빈 포트를 준다"
    p = subprocess.Popen([sys.executable, str(HERE.parent / "server.py")], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         env={**os.environ, "CALL_MODE": "saved", "CALL_PORT": str(PORT), "CALL_REPLAY_SEC": "0", "CALL_VOICE_STT": "fake", "CALL_VOICE_FAKE_CPS": "200", **env})
    for _ in range(200):
        try:
            return p, call("/api/text")
        except OSError:
            assert p.poll() is None, "서버가 뜨지 않음: " + p.stderr.read().decode()[-600:]
            time.sleep(0.1)
    raise AssertionError("서버가 20초 안에 뜨지 않음")


def stop(p):
    p.terminate()
    p.wait(timeout=5)


def turn(state, **ev):
    d = call("/api/turn", {"state": state, **ev})
    return d["state"], d["view"]


def run_scene(script, greeting, hear):
    """장면 하나를 끝까지. hear(대본 줄, 직전에 뜬 질문) → 통화 길에 넣을 글(그대로 넣거나, 음성 길을 거쳐 받아쓴 글)."""
    st, view = turn({"id": f"voice-check-{time.time()}"}, line={"who": "상담사", "text": greeting})
    said, q = script["처음"], None
    for _ in range(12):
        st, view = turn(st, line={"who": "시민", "text": hear(said, q)})
        st, view = turn(st, phase="model")
        if view["confirmed"]:
            return view
        q = view["question"]
        st, view = turn(st, line={"who": "상담사", "text": q["say"]})
        said = script[q["id"]]
    raise AssertionError("장면이 12차례 안에 끝나지 않음")


def check_fake(text):
    assert code_of("/api/voice/info") == 200 and call("/api/voice/info")["stt"] == "fake"
    assert "voice.js" in urllib.request.urlopen(BASE + "/", timeout=5).read().decode("utf-8"), "켰는데 첫 화면에 voice.js가 없음"
    greeting = next(r[1] for t in text["text"]["sections"]["통화 글"]["tables"] for r in t["rows"] if r[0] == "인사")
    script = text["scripts"][SCENE]
    plain = run_scene(script, greeting, lambda said, q: said)                 # 글로 바로 넣었을 때

    room = call("/api/voice/room", {})["room"]
    assert call(f"/api/voice/desk?room={room}")["joined"] is False
    assert call(f"/api/voice/join?room={room}&rate=48000", {})["stt"] == "fake"
    assert call(f"/api/voice/audio?room={room}", raw=bytes(4800))["picked"] is False      # 소리 0.05초(48kHz 16비트): 마이크 → 서버 길. 아직 받지 않았다(거는 쪽은 연결음)
    call(f"/api/voice/pick?room={room}", {})                                 # 상담 화면이 받는다
    assert call(f"/api/voice/audio?room={room}", raw=b"")["picked"] is True
    call(f"/api/voice/cut?room={room}", {})                                  # 상담사가 넘겨받으면 소리 쪽이 끊을 차례를 안다
    assert call(f"/api/voice/audio?room={room}", raw=b"")["cut"] == 1
    seen = {"since": 0, "says": 0, "partials": 0}

    def hear(said, q):
        if q:                                                                # 화면이 띄운 질문 → 읽어 줄 말로 소리 쪽에 건너간다
            n = call(f"/api/voice/ask?room={room}", {"text": q["say"]})["n"]
            got = call(f"/api/voice/audio?room={room}&says={seen['says']}", raw=b"")["says"]
            assert [s["text"] for s in got] == [q["say"]] and got[0]["n"] == n, f"읽어 줄 말이 건너가지 않음 {got}"
            seen["says"] = n
            call(f"/api/voice/audio?room={room}&says={n}&played={n}", raw=b"")
            assert call(f"/api/voice/desk?room={room}&since={seen['since']}")["played"] == n
        call(f"/api/voice/fake?room={room}", {"text": said})                 # 대본 글을 소리 대신 흘린다
        parts, t0 = [], time.time()
        while time.time() - t0 < 10:
            d = call(f"/api/voice/desk?room={room}&since={seen['since']}")
            seen["since"] = d["next"]
            parts += d["events"]
            if parts and parts[-1]["final"]:
                break
            time.sleep(0.02)
        assert parts and parts[-1]["final"] and parts[-1]["text"] == said, f"확정 글이 다름 {parts[-3:]}"
        assert all(said.startswith(p["text"]) and not p["final"] for p in parts[:-1]), "도중 글이 확정 글의 앞부분이 아님"
        seen["partials"] += len(parts) - 1
        return parts[-1]["text"]

    voice = run_scene(script, greeting, hear)                                # 음성 길을 거쳐 넣었을 때
    d = call(f"/api/voice/desk?room={room}")
    assert d["heard_sec"] == 0.05 and seen["partials"] >= 3, f"소리 · 도중 글이 흐르지 않음 {d['heard_sec']} {seen}"
    same = ("where", "to", "point", "bunji")
    assert voice["confirmed"] and all(voice["summary"].get(k) == plain["summary"].get(k) for k in same), f"음성 길의 끝이 글로 넣었을 때와 다름\n  글: {plain['summary']}\n  음성: {voice['summary']}"
    assert code_of(f"/api/voice/end?room={room}", {}) == 200 and code_of(f"/api/voice/desk?room={room}") == 404
    probe = f"점검용 읽어 주기 파일 {os.getpid()}"                              # 읽어 주기: 미리 만든 파일이 있으면 그 파일을, 없으면 404(화면은 소리 없이 기다린다). 남이 만든 음성 파일에 기대지 않게 점검만의 글로
    name = hashlib.sha1(probe.encode("utf-8")).hexdigest()[:12] + ".mp3"
    f, say = HERE.parent / "web" / "voice" / "tts" / name, "/api/voice/say?text=" + urllib.parse.quote(probe)
    assert not f.exists() and code_of(say) == 404, "음성 파일이 없는데 404가 아님(또는 점검이 지울 파일이 이미 있음)"
    f.parent.mkdir(exist_ok=True)
    f.write_bytes(b"ID3-check")
    try:
        with urllib.request.urlopen(BASE + say, timeout=5) as r:
            assert r.headers["Content-Type"] == "audio/mpeg" and r.read() == b"ID3-check"
    finally:
        f.unlink()
    print(f"  ✓ 가짜 받아쓰기로 {SCENE} 끝까지: 도중 글 {seen['partials']}번 · 읽어 줄 말 {seen['says']}번 → {voice['summary']['where']}")


def check_limits():
    assert code_of("/api/voice/room", {"code": "틀림"}) == 403 and code_of("/api/voice/room", {}) == 403, "틀린 접근 코드로 열림"
    rooms = [call("/api/voice/room", {"code": "맞음"})["room"] for _ in range(2)]
    assert code_of("/api/voice/room", {"code": "맞음"}) == 429, "통화 수 상한을 넘겨 열림"
    assert code_of("/api/voice/desk?room=ffffff") == 404 and len(set(rooms)) == 2
    print("  ✓ 접근 코드 · 통화 수 상한")


def check_rtzr():
    """리턴제로 쪽 코드가 문서의 꼴대로 말하는가. 가짜 서버 둘(인증 HTTP · 받아쓰기 WebSocket)을 이 컴퓨터 안에 띄워 본다."""
    from websockets.sync.server import serve
    sys.path.insert(0, str(HERE.parent))
    got = {"frames": 0, "eos": False}

    class Auth(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            got["auth"] = (self.path, self.rfile.read(int(self.headers["Content-Length"])).decode())
            body = json.dumps({"access_token": "tok-123", "expire_at": int(time.time()) + 21600}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def ws(conn):
        got["path"], got["bearer"] = conn.request.path, conn.request.headers.get("Authorization")
        for msg in conn:
            if msg == "EOS":
                got["eos"] = True
                return
            got["frames"] += 1
            if got["frames"] == 1:
                conn.send(json.dumps({"seq": 0, "start_at": 0, "duration": 0, "final": False, "alternatives": [{"text": "상도1동", "confidence": 0}]}))
            if got["frames"] == 2:
                conn.send(json.dumps({"seq": 0, "start_at": 0, "duration": 900, "final": True, "alternatives": [{"text": "상도1동 주민센터 앞이에요", "confidence": 0.9, "words": []}]}))

    auth = HTTPServer(("127.0.0.1", PORT + 1), Auth)
    threading.Thread(target=auth.serve_forever, daemon=True).start()
    wss = serve(ws, "127.0.0.1", PORT + 2)
    threading.Thread(target=wss.serve_forever, daemon=True).start()
    from voice import stt
    for said, want in [("상도 일동 주민센터 근처 골목이에요", "상도 1동 주민센터 근처 골목이에요"), ("숭실대입구역 삼번 출구에서 오 분쯤", "숭실대입구역 3번 출구에서 오 분쯤"), ("이호선 타고 이동 중이에요", "2호선 타고 이동 중이에요"),
                       ("십이번 출구 앞, 일동이 다 모였어요", "12번 출구 앞, 일동이 다 모였어요")]:      # 받아쓴 글의 한글 숫자: 지명에 쓰이는 꼴만 숫자로, 다른 말은 그대로
        assert stt.digits(said) == want, (said, stt.digits(said))
    stt.RTZR_API, stt.RTZR_ENV = f"http://127.0.0.1:{PORT + 1}", Path("/nonexistent")      # 진짜 주소 · 진짜 열쇠 파일은 건드리지 않는다(환경 변수가 아니라 불러온 모듈의 값을 직접 바꾼다)
    stt._tok.update(v=None, until=0)
    os.environ.update(RTZR_CLIENT_ID="점검용-아이디", RTZR_CLIENT_SECRET="점검용-비밀")
    assert "127.0.0.1" in stt.RTZR_API and not stt.RTZR_ENV.exists()
    try:
        os.environ["CALL_VOICE_STT"] = "rtzr"
        assert stt.has_keys() and stt.pick() is stt.Rtzr and stt._token() == "tok-123"
        del os.environ["CALL_VOICE_STT"]
        assert stt.pick() is stt.Fake, "받아쓰기를 고르지 않았는데 가짜가 아님"
        assert got["auth"][0] == "/v1/authenticate" and urllib.parse.parse_qs(got["auth"][1]) == {"client_id": ["점검용-아이디"], "client_secret": ["점검용-비밀"]}, got["auth"]
        stt.RTZR_API = f"http://127.0.0.1:{PORT + 2}"
        out = []
        r = stt.Rtzr(lambda final, text: out.append((final, text)), rate=8000, encoding="MULAW")       # 전화 회선의 소리 꼴
        r.feed(bytes(160))
        r.feed(bytes(160))
        t0 = time.time()
        while len(out) < 2 and time.time() - t0 < 5:
            time.sleep(0.02)
        r.close()
        t0 = time.time()
        while not got["eos"] and time.time() - t0 < 5:
            time.sleep(0.02)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(got["path"]).query)
        assert got["bearer"] == "bearer tok-123" and q["sample_rate"] == ["8000"] and q["encoding"] == ["MULAW"] and q["model_name"] == ["sommers_ko"] and q["domain"] == ["CALL"], (got["bearer"], q)
        assert out == [(False, "상도1동"), (True, "상도1동 주민센터 앞이에요")] and got["frames"] == 2 and got["eos"] and r.heard == 320, (out, got)
    finally:
        wss.shutdown()
        auth.shutdown()
    print("  ✓ 리턴제로 받아쓰기 코드: 인증 → 연결(bearer · 8000Hz MULAW · sommers_ko · CALL) → 도중 글 · 확정 글 → EOS (가짜 서버와)")


def check_eleven():
    """일레븐랩스 쪽 코드가 문서의 꼴대로 말하는가. 가짜 서버를 이 컴퓨터 안에 띄워 본다(진짜 주소 · 진짜 열쇠 파일은 쓰지 않는다)."""
    from websockets.sync.server import serve
    sys.path.insert(0, str(HERE.parent))
    from voice import stt
    conns, chunks = [], []

    def ws(conn):
        conns.append((conn.request.path, conn.request.headers.get("xi-api-key")))
        conn.send(json.dumps({"message_type": "session_started", "session_id": "s1", "config": {"model_id": "scribe_v2_realtime", "commit_strategy": "vad"}}))
        for n, msg in enumerate(conn, 1):
            d = json.loads(msg)
            chunks.append((len(conns), d["message_type"], d["commit"], d["sample_rate"], len(base64.b64decode(d["audio_base_64"]))))
            if n == 1 and len(conns) == 1:
                conn.send(json.dumps({"message_type": "partial_transcript", "text": "상도 일동"}))
            if n == 2 and len(conns) == 1:
                conn.send(json.dumps({"message_type": "committed_transcript", "text": "상도 일동 주민센터 앞이에요"}))

    wss = serve(ws, "127.0.0.1", PORT + 3)
    threading.Thread(target=wss.serve_forever, daemon=True).start()
    stt.ELEVEN_WS, stt.ELEVEN_ENV = f"ws://127.0.0.1:{PORT + 3}", Path("/nonexistent")      # 불러온 모듈의 값을 직접 바꾼다(진짜 주소 · 진짜 열쇠 파일을 건드리지 않게)
    os.environ["ELEVENLABS_API_KEY"] = "check-key"
    assert stt.ELEVEN_WS.startswith("ws://127.0.0.1") and not stt.ELEVEN_ENV.exists() and stt.eleven_key() == "check-key"
    try:
        out = []
        e = stt.Eleven(lambda final, text: out.append((final, text)), rate=32000)      # 일레븐랩스가 받지 않는 주파수 → 16000으로 바꿔 보낸다
        e.feed(bytes(6400))
        e.feed(bytes(6400))
        t0 = time.time()
        while len(out) < 2 and time.time() - t0 < 5:
            time.sleep(0.02)
        assert out == [(False, "상도 일동"), (True, "상도 1동 주민센터 앞이에요")], out      # 확정 글의 한글 숫자는 지명에 쓰이는 꼴만 숫자로
        e.hint(["상도1동주민센터", "상도역", "상도역", "가"])                                  # 지명을 알려 주면 줄을 새로 연다(겹친 것 · 한 글자는 뺀다)
        e.feed(bytes(6400))
        t0 = time.time()
        while len(chunks) < 3 and time.time() - t0 < 5:
            time.sleep(0.02)
        e.close()
        q0, q1 = (urllib.parse.parse_qs(urllib.parse.urlsplit(p).query) for p, _ in conns)
        assert [k for _, k in conns] == ["check-key"] * 2 and q0["model_id"] == ["scribe_v2_realtime"] and q0["language_code"] == ["ko"] and q0["audio_format"] == ["pcm_16000"] and q0["commit_strategy"] == ["vad"] and "keyterms" not in q0, (conns, q0)
        assert q1["keyterms"] == ["상도1동주민센터", "상도역"], q1
        assert chunks == [(1, "input_audio_chunk", False, 16000, 3200), (1, "input_audio_chunk", False, 16000, 3200), (2, "input_audio_chunk", False, 16000, 3200)], chunks
        assert round(stt.used["stt_sec"], 2) == 0.3 and stt.used["stt_conn"] == 2, stt.used
    finally:
        wss.shutdown()
    print("  ✓ 일레븐랩스 받아쓰기 코드: 연결(xi-api-key · pcm_16000 · vad · ko) → 도중 글 · 확정 글 → 지명을 알려 주면 새 줄에 keyterms (가짜 서버와)")


def check_tts():
    """일레븐랩스 음성 합성: 통화에서 읽어 달라고 한 글만 만들고, 만든 소리는 남겨 다시 쓴다(가짜 서버와)."""
    calls = []

    class Tts(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            calls.append((self.path, self.headers.get("xi-api-key"), json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode())))
            self.send_response(200)
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"ID3-synth")

    p, _ = server(CALL_VOICE="1", CALL_VOICE_TTS="elevenlabs", ELEVENLABS_API_BASE=f"http://127.0.0.1:{PORT + 4}", ELEVENLABS_API_KEY="check-key", ELEVENLABS_ENV_FILE="/nonexistent", ELEVENLABS_VOICE_ID="voice-x")
    mock = HTTPServer(("127.0.0.1", PORT + 4), Tts)      # 서버를 띄운 뒤에(서버는 포트 다섯이 비었을 때만 시작한다)
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    text = f"점검용 읽어 주기 문장입니다 {os.getpid()}"
    f = HERE.parent / "web" / "voice" / "tts" / (hashlib.sha1(text.encode("utf-8")).hexdigest()[:12] + ".mp3")
    say = "/api/voice/say?text=" + urllib.parse.quote(text)
    try:
        assert call("/api/voice/info")["tts"] == "elevenlabs"
        assert code_of(say) == 404 and not calls, "통화에서 요청하지 않은 글을 만들었다"
        room = call("/api/voice/room", {})["room"]
        call(f"/api/voice/ask?room={room}", {"text": text, "terms": ["상도역"]})      # 가짜 받아쓰기는 지명을 받지 않는다(그래도 통화는 간다)
        for _ in range(2):                                                             # 두 번째는 남겨 둔 파일
            with urllib.request.urlopen(BASE + say, timeout=10) as r:
                assert r.headers["Content-Type"] == "audio/mpeg" and r.read() == b"ID3-synth"
        assert len(calls) == 1 and calls[0][0].startswith("/v1/text-to-speech/voice-x?") and calls[0][1] == "check-key" and calls[0][2]["text"] == text and calls[0][2]["model_id"] == "eleven_multilingual_v2", calls
        assert call("/api/voice/info")["used"]["tts_calls"] == 1
    finally:
        stop(p)
        mock.shutdown()
        f.unlink(missing_ok=True)
    print("  ✓ 일레븐랩스 음성 합성: 통화에서 요청한 글만 만들고, 만든 소리를 남겨 다시 쓴다 (가짜 서버와)")


def check_phone_text():
    room = call("/api/voice/room", {"from": "phone"})["room"]                     # 휴대폰이 먼저 건다
    assert room in call("/api/voice/waiting")["rooms"], "기다리는 통화에 없음"
    assert call(f"/api/voice/desk?room={room}")["joined"] is False
    assert call(f"/api/voice/join?room={room}&text=1", {})["stt"] is None            # 글로만 붙는다
    d = call(f"/api/voice/desk?room={room}")
    assert d["joined"] is True and d["heard_sec"] == 0, d
    assert code_of(f"/api/voice/claim?room={room}", {}) == 200 and code_of(f"/api/voice/claim?room={room}", {}) == 409, "한 통화를 두 화면이 받음"
    assert room not in call("/api/voice/waiting")["rooms"]
    call(f"/api/voice/text?room={room}", {"text": "  상도1동 주민센터   근처예요 "})
    call(f"/api/voice/text?room={room}", {"text": ""})                               # 빈 글은 넣지 않는다
    ev = call(f"/api/voice/desk?room={room}")["events"]
    assert ev == [{"final": True, "text": "상도1동 주민센터 근처예요", "typed": True}], ev
    n = call(f"/api/voice/ask?room={room}", {"text": "바로 앞에 뭐가 보이세요?"})["n"]  # 상담사 말 → 휴대폰
    assert [x["text"] for x in call(f"/api/voice/audio?room={room}&says=0", raw=b"")["says"]] == ["바로 앞에 뭐가 보이세요?"] and n == 1
    assert call("/api/voice/info")["direct"] is False
    call(f"/api/voice/end?room={room}", {})
    print("  ✓ 휴대폰이 먼저 거는 통화: 기다림 → 한 화면만 받음 · 글로만 붙음 · 친 글이 확정 글로 · 상담사 말이 휴대폰으로")


def main():
    p, _ = server()                                       # ① 끔
    try:
        assert code_of("/api/voice/info") == 404 and code_of("/api/voice/room", {}) == 404, "스위치를 껐는데 음성 길이 있음"
        html = urllib.request.urlopen(BASE + "/", timeout=5).read()
        assert b"voice.js" not in html and html == (HERE.parent / "web" / "index.html").read_bytes(), "스위치를 껐는데 첫 화면이 다름"
        print("  ✓ 스위치 끔: 음성 길 없음, 첫 화면은 index.html 그대로")
    finally:
        stop(p)
    p, text = server(CALL_VOICE="1")                      # ② 켬(가짜 받아쓰기)
    try:
        check_fake(text)
    finally:
        stop(p)
    p, _ = server(CALL_VOICE="1")                         # ⑥
    try:
        check_phone_text()
    finally:
        stop(p)
    p, _ = server(CALL_VOICE="1", CALL_VOICE_CODE="맞음", CALL_VOICE_MAX_ROOMS="2")      # ③
    try:
        check_limits()
    finally:
        stop(p)
    check_rtzr()                                          # ④
    check_eleven()
    check_tts()                                           # ⑤
    print("음성 통화 점검 통과")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"점검 실패: {e}", file=sys.stderr)
        sys.exit(1)
