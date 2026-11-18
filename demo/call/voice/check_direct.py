"""직접 통화(배포 판)의 서버 쪽 점검. 열쇠 · 인터넷 · 브라우저 없이 몇 초. 실패하면 종료 코드 1.

    OPENBLAS_NUM_THREADS=1 python3 demo/call/voice/check_direct.py

  ① 스위치를 끄면 직접 통화 길이 없다.
  ② 켜면 첫 화면에 direct.js가 끼워지고(음성도 켜면 voice.js 다음에), 표(쿠키) 없이는 POST /api/… 가 403, 표를 받으면 된다.
  ③ 접근 코드가 있으면 맞혀야 표를 준다. 음성 길(/api/voice/room)도 표가 있어야 열린다.
  ④ 민원인의 말 수를 표마다 · 모두 세고, 상한을 넘으면 429. 상담사 줄은 세지 않는다.
  ⑤ 열쇠(UPSTAGE_API_KEY · ELEVENLABS_API_KEY)가 어느 응답에도 실리지 않는다(가짜 값을 넣고 응답 글을 뒤진다).
"""
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("CALL_CHECK_PORT", "8797"))
BASE = f"http://127.0.0.1:{PORT}"
FAKE_KEY, FAKE_EL = "SENTINEL-upstage-0000", "SENTINEL-eleven-0000"


def opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def req(o, path, body=None):
    """→ (상태, 본문 글)"""
    data = json.dumps(body).encode() if body is not None else None
    try:
        with o.open(urllib.request.Request(BASE + path, data, {"Content-Type": "application/json"}), timeout=30) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def server(**env):
    with socket.socket() as s:
        assert s.connect_ex(("127.0.0.1", PORT)) != 0, f"포트 {PORT}를 다른 프로그램이 쓰고 있다. CALL_CHECK_PORT로 빈 포트를 준다"
    p = subprocess.Popen([sys.executable, str(HERE.parent / "server.py")], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         env={**os.environ, "CALL_MODE": "saved", "CALL_PORT": str(PORT), "CALL_REPLAY_SEC": "0", "UPSTAGE_API_KEY": FAKE_KEY, "ELEVENLABS_API_KEY": FAKE_EL,
                              "ELEVENLABS_ENV_FILE": "/nonexistent", "CALL_VOICE_STT": "fake", **env})
    for _ in range(200):
        try:
            urllib.request.urlopen(BASE + "/api/text", timeout=2).read()
            return p
        except OSError:
            assert p.poll() is None, "서버가 뜨지 않음: " + p.stderr.read().decode()[-600:]
            time.sleep(0.1)
    raise AssertionError("서버가 20초 안에 뜨지 않음")


def stop(p):
    p.terminate()
    p.wait(timeout=5)


turn = lambda o, who="시민", text="마포구인데요, 스타벅스 앞 가로등이 꺼져 있어요": req(o, "/api/turn", {"state": {"id": "d"}, "line": {"who": who, "text": text}})


def main():
    p = server()                                                          # ①
    try:
        o = opener()
        assert req(o, "/api/direct/info")[0] == 404 and "direct.js" not in req(o, "/")[1] and turn(o)[0] == 200, "스위치를 껐는데 직접 통화 길이 있음"
        print("  ✓ 스위치 끔: 직접 통화 길 없음, /api/turn은 그대로")
    finally:
        stop(p)
    p = server(CALL_DIRECT="1", CALL_DIRECT_MAX_TURNS="2", CALL_DIRECT_MAX_ALL="3")      # ② ④ ⑤
    try:
        o, seen = opener(), []
        html = req(o, "/")[1]
        assert "direct.js" in html and "voice.js" not in html
        assert turn(o)[0] == 403 and req(o, "/api/view", {"state": {}})[0] == 403 and req(o, "/api/alias", {"name": "점검", "at": [127, 37.5]})[0] == 403, "표 없이 POST가 됨"
        info = json.loads(req(o, "/api/direct/info")[1])
        assert info == {"on": True, "code": False, "pass": False, "used": 0, "max": 2, "left_all": 3}, info
        assert req(o, "/api/direct/enter", {})[0] == 200 and json.loads(req(o, "/api/direct/info")[1])["pass"] is True
        for who in ("시민", "상담사", "시민"):
            c, b = turn(o, who)
            assert c == 200, (who, c, b[:200])
            seen.append(b)
        c, b = turn(o)
        assert c == 429 and json.loads(b).get("limit") is True, (c, b[:200])                # 표 하나에 민원인의 말 둘까지(상담사 줄은 안 셈)
        assert turn(o, "상담사")[0] == 200
        o2 = opener()
        req(o2, "/api/direct/enter", {})
        assert turn(o2)[0] == 200 and turn(o2)[0] == 429, "모두 합친 상한(3)이 듣지 않음"
        info = json.loads(req(o, "/api/direct/info")[1])
        assert info["used"] == 2 and info["left_all"] == 0, info
        for path in ("/", "/api/text", "/api/direct/info", "/direct.js", "/call.js"):
            seen.append(req(o, path)[1])
        assert not any(FAKE_KEY in b or FAKE_EL in b for b in seen), "열쇠가 응답에 실렸다"
        print("  ✓ 직접 통화: 표 없이는 403 · 표를 받으면 됨 · 민원인의 말을 표마다(2) · 모두(3) 세어 429 · 상담사 줄은 안 셈 · 열쇠는 어느 응답에도 없음")
    finally:
        stop(p)
    p = server(CALL_DIRECT="1", CALL_DIRECT_CODE="맞는-코드", CALL_VOICE="1")              # ③
    try:
        o = opener()
        html = req(o, "/")[1]
        assert html.index("voice.js") < html.index("direct.js"), "voice.js가 direct.js보다 먼저 끼워져야 함"
        assert req(o, "/api/voice/room", {})[0] == 403, "표 없이 음성 길이 열림"
        assert json.loads(req(o, "/api/direct/info")[1])["code"] is True
        assert req(o, "/api/direct/enter", {"code": "틀림"})[0] == 403 and turn(o)[0] == 403
        assert req(o, "/api/direct/enter", {"code": "맞는-코드"})[0] == 200 and turn(o)[0] == 200 and req(o, "/api/voice/room", {})[0] == 200
        b = req(o, "/api/voice/info")[1]
        assert FAKE_KEY not in b and FAKE_EL not in b
        print("  ✓ 접근 코드: 틀리면 표를 안 줌 · 맞히면 통화 · 음성 길이 열림")
    finally:
        stop(p)
    print("직접 통화 서버 점검 통과")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"점검 실패: {e}", file=sys.stderr)
        sys.exit(1)
