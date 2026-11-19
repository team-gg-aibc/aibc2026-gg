"""직접 통화(배포 판)의 서버 쪽 점검. 열쇠 · 인터넷 · 브라우저 없이 몇 초. 실패하면 종료 코드 1.

    OPENBLAS_NUM_THREADS=1 python3 demo/call/voice/check_direct.py

  ① 스위치를 끄면 직접 통화 길이 없다.
  ② 켜면 첫 화면에 direct.js가 끼워지고(음성도 켜면 voice.js 다음에), 표(쿠키) 없이는 POST /api/… 가 403, 표를 받으면 된다.
  ③ 접근 코드가 있으면 맞혀야 표를 준다. 음성 길은 GET까지 표가 있어야 열리고(info만 빼고), 한 통화는 연 표 · 받은 표만 읽는다(남의 통화 글을 못 읽는다).
  ④ 민원인의 말 수를 표마다 · 모두 세고, 상한을 넘으면 429. 상담사 줄은 세지 않는다.
  ⑤ 열쇠(UPSTAGE_API_KEY · ELEVENLABS_API_KEY)가 어느 응답에도 실리지 않는다(가짜 값을 넣고 응답 글을 뒤진다).
  ⑥ 민원인 글: 켜면 한 차례 2,000자까지 읽고(끄면 500 그대로), 화면이 보낸 통화 상태 속 말도 2,000자로 자르며, 규정 찾기의 빠른 길이 원래 정규식과 같은 답을 내고 꾸민 2,000자에서도 빠르다.
  ⑦ 실제 호출로 켜면서 접근 코드가 없으면 서버가 뜨지 않고, CALL_DIRECT_OPEN=1이면 코드 없이 뜬다.
  ⑧ 실제 호출 판에서도 장면 재생은 저장된 답(server.py CALL_SAVED_FIRST, 기본 켬): 장면마다 Upstage를 한 번도 부르지 않고(부르면 실패하게 막아 둠)
     차례마다 저장된 답 판(CALL_MODE=saved로 같은 장면)과 같다. CALL_SAVED_FIRST=0이면 부르러 간다(main과 같음).
"""
import http.cookiejar
import json
import os
import random
import re
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
LONG = ("집 앞 골목에 고양이가 다쳐서 웅크리고 있어요. 상도1동 주민센터 근처예요. " * 60)[:2400]
said_len = lambda o: len(json.loads(turn(o, text=LONG)[1])["state"]["lines"][-1]["text"])


SAVED_FIRST_RUN = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import server as S
def boom(*a, **k):
    raise RuntimeError("Upstage를 불렀다")
if S.MODE == "live":
    S.upstage.chat = S.upstage.embed = boom
out = {}
for scene in (S.scripts() if sys.argv[2] == "all" else [sys.argv[2]]):
    st, view, steps = S.play(scene)
    out[scene] = {"reads": sorted({s["read"] for s in steps}), "steps": [(s["said"], s["next"], s["m"]) for s in steps], "where": view["summary"].get("where"),
                  "engine": (view.get("engine") or {}).get("how"), "answer": (view.get("engine") or {}).get("answer")}
print(json.dumps(out, ensure_ascii=False))
'''


def check_saved_first():
    env = {**os.environ, "CALL_MODE": "", "UPSTAGE_API_KEY": FAKE_KEY, "CALL_REPLAY_SEC": "0", "OPENBLAS_NUM_THREADS": "1"}
    r = subprocess.run([sys.executable, "-c", SAVED_FIRST_RUN, str(HERE.parent), "all"], capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr[-800:]
    got = json.loads(r.stdout.strip().splitlines()[-1])
    r = subprocess.run([sys.executable, "-c", SAVED_FIRST_RUN, str(HERE.parent), "all"], capture_output=True, text=True, timeout=300, env={**env, "CALL_MODE": "saved"})
    want = json.loads(r.stdout.strip().splitlines()[-1])
    bad = {k: v for k, v in got.items() if v["reads"] != ["saved"] or {x: v[x] for x in ("steps", "where", "answer")} != {x: want[k][x] for x in ("steps", "where", "answer")}}
    assert len(got) >= 6 and not bad, ("실제 호출 판의 장면 재생이 저장된 답과 다름", bad)
    scene = next(iter(got))
    r = subprocess.run([sys.executable, "-c", SAVED_FIRST_RUN, str(HERE.parent), scene], capture_output=True, text=True, timeout=300, env={**env, "CALL_SAVED_FIRST": "0"})
    off = json.loads(r.stdout.strip().splitlines()[-1])[scene] if r.returncode == 0 else {"reads": ["(멈춤)"]}
    assert "saved" not in off["reads"], ("CALL_SAVED_FIRST=0인데 저장된 답을 씀", off)
    return got


def check_rule():
    sys.path.insert(0, str(HERE.parent))
    from voice.direct import _Rule
    rx = re.compile(re.search(r'RULE_Q = re.compile\(r"(.*?)"\)', (HERE.parent / "server.py").read_text(encoding="utf-8")).group(1))
    fast, toks, rnd = _Rule(rx), ["벌금", "과태료", "되나요", "되는 거", "해도 돼", "데려가", "신고하면", "조례", "고양이", " ", ", ", ".", "?", "!", "가"], random.Random(7)
    for _ in range(3000):
        t = "".join(rnd.choice(toks) for _ in range(rnd.randint(0, 30)))
        a, b = rx.search(t), fast.search(t)
        assert (a and a.group()) == (b and b.group()), ("규정 찾기 빠른 길이 다른 답", t)
    t0 = time.perf_counter()
    fast.search(("벌금과태료불법조례되나요" * 200)[:2000])
    assert time.perf_counter() - t0 < 0.05, "꾸민 2,000자에서 규정 찾기가 느림"


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
        assert info == {"on": True, "code": False, "pass": False, "used": 0, "max": 2, "left_all": 3, "said_max": 2000, "input_max": 1000, "settle_ms": 3000, "law_wait_ms": 80000}, info
        assert req(o, "/api/direct/enter", {})[0] == 200 and json.loads(req(o, "/api/direct/info")[1])["pass"] is True
        for who in ("시민", "상담사", None):                                              # who가 없는 줄도 민원인으로 센다(server.py가 그렇게 읽으니)
            c, b = turn(o, who)
            assert c == 200, (who, c, b[:200])
            seen.append(b)
        c, b = turn(o)
        assert c == 429 and json.loads(b).get("limit") is True, (c, b[:200])                # 표 하나에 민원인의 말 둘까지(상담사 줄은 안 셈, who 없는 줄은 셈)
        assert turn(o, "x")[0] == 429, "who를 다른 값으로 바꿔 상한을 건너뜀"
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
        info = json.loads(req(o, "/api/direct/info")[1])
        assert (info["said_max"], info["input_max"], info["settle_ms"], info["law_wait_ms"]) == (2000, 1000, 3000, 80000), info
    finally:
        stop(p)
    p = server(CALL_DIRECT="1")                                                              # ⑥
    try:
        o = opener()
        req(o, "/api/direct/enter", {})
        n = said_len(o)
        assert n == 2000, f"켜면 한 차례 2,000자까지 읽어야 함: {n}"
        st = json.loads(req(o, "/api/turn", {"state": {"id": "c", "lines": [{"who": "시민", "text": "가" * 5000}], "turns": [{"said": "나" * 5000}]},
                                              "line": {"who": "상담사", "text": "네"}})[1])["state"]
        assert len(st["lines"][0]["text"]) == 2000 and len(st["turns"][0]["said"]) == 2000, "통화 상태 속 말이 잘리지 않음"
    finally:
        stop(p)
    p = server()
    try:
        assert said_len(opener()) == 500, "끄면 500자 그대로여야 함"
    finally:
        stop(p)
    check_rule()
    print("  ✓ 민원인 글: 켜면 한 차례 2,000자(끄면 500) · 규정 찾기 빠른 길 = 원래 정규식(3,000가지) · 꾸민 2,000자 0.05초 안")
    with socket.socket() as s:                                                              # ⑦
        assert s.connect_ex(("127.0.0.1", PORT)) != 0
    r = subprocess.run([sys.executable, str(HERE.parent / "server.py")], capture_output=True, text=True, timeout=120,
                       env={**os.environ, "CALL_MODE": "", "CALL_PORT": str(PORT), "CALL_DIRECT": "1", "UPSTAGE_API_KEY": FAKE_KEY, "CALL_DIRECT_CODE": "", "CALL_DIRECT_OPEN": ""})
    assert r.returncode != 0 and "CALL_DIRECT_OPEN" in r.stderr, ("실제 호출 + 코드 없음인데 서버가 떴다", r.returncode, r.stderr[-300:])
    p = server(CALL_MODE="", CALL_DIRECT="1", CALL_DIRECT_OPEN="1")
    try:
        o = opener()
        assert req(o, "/api/direct/enter", {})[0] == 200 and json.loads(req(o, "/api/direct/info")[1])["pass"] is True
    finally:
        stop(p)
    print("  ✓ 실제 호출 + 접근 코드 없음 → 서버가 뜨지 않음 · CALL_DIRECT_OPEN=1이면 코드 없이 표를 줌")
    got = check_saved_first()                                                              # ⑧
    print(f"  ✓ 실제 호출 판의 장면 재생 {len(got)}개: Upstage 0번, 차례마다 저장된 답 판과 같음(엔진 답 {sorted({v['engine'] for v in got.values()}, key=str)}) · CALL_SAVED_FIRST=0이면 부르러 감")
    p = server(CALL_DIRECT="1", CALL_DIRECT_CODE="맞는-코드", CALL_VOICE="1")              # ③
    try:
        o = opener()
        html = req(o, "/")[1]
        assert html.index("voice.js") < html.index("direct.js"), "voice.js가 direct.js보다 먼저 끼워져야 함"
        assert req(o, "/api/voice/room", {})[0] == 403, "표 없이 음성 길이 열림"
        assert [req(o, x)[0] for x in ("/api/voice/waiting", "/api/voice/desk?room=abcdef&since=0", "/api/voice/poll?room=abcdef")] == [403] * 3, "표 없이 통화방 GET이 열림"
        assert req(o, "/api/voice/info")[0] == 200
        assert json.loads(req(o, "/api/direct/info")[1])["code"] is True
        assert req(o, "/api/direct/enter", {"code": "틀림"})[0] == 403 and turn(o)[0] == 403
        assert req(o, "/api/direct/enter", {"code": "맞는-코드"})[0] == 200 and turn(o)[0] == 200 and req(o, "/api/voice/room", {})[0] == 200
        b = req(o, "/api/voice/info")[1]
        assert FAKE_KEY not in b and FAKE_EL not in b
        assert json.loads(b)["poll_ms"] == 600, "직접 통화와 함께면 폴링 0.6초"
        room = json.loads(req(o, "/api/voice/room", {"from": "phone"})[1])["room"]          # 휴대폰이 친 글도 한 줄 2,000자까지
        req(o, f"/api/voice/join?room={room}&text=1", {})
        req(o, f"/api/voice/text?room={room}", {"text": LONG})
        assert len(json.loads(req(o, f"/api/voice/desk?room={room}")[1])["events"][0]["text"]) == 2000
        desk, other = opener(), opener()                                                     # 같은 코드를 가진 다른 사람 둘: 상담 화면 · 남
        for x in (desk, other):
            assert req(x, "/api/direct/enter", {"code": "맞는-코드"})[0] == 200
        assert room in json.loads(req(desk, "/api/voice/waiting")[1])["rooms"]
        assert [req(desk, f"/api/voice/{x}?room={room}&since=0")[0] for x in ("desk", "poll")] == [403, 403], "받지 않은 표가 남의 통화를 읽음"
        assert req(desk, f"/api/voice/text?room={room}", {"text": "끼어들기"})[0] == 403
        assert req(desk, f"/api/voice/claim?room={room}", {})[0] == 200 and req(desk, f"/api/voice/desk?room={room}&since=0")[0] == 200, "받은 표가 못 읽음"
        assert req(other, f"/api/voice/claim?room={room}", {})[0] == 409 and req(other, f"/api/voice/desk?room={room}&since=0")[0] == 403, "남이 받은 통화를 읽음"
        assert req(o, f"/api/voice/poll?room={room}")[0] == 200, "건 표가 못 읽음"
        for code, body in (req(other, f"/api/voice/claim?room={room}", {}), req(other, f"/api/voice/desk?room={room}"), req(opener(), "/api/voice/waiting")):
            assert re.fullmatch(r'\{"error": "[a-z_]+"(, "need_code": true)?\}', body), ("서버 오류에 화면 글이 실림", body)
        print("  ✓ 접근 코드: 틀리면 표를 안 줌 · 맞히면 통화 · 음성 길(GET까지)이 표를 거침 · 한 통화는 건 표 · 받은 표만 읽음 · 서버 오류는 종류만")
    finally:
        stop(p)
    print("직접 통화 서버 점검 통과")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"점검 실패: {e}", file=sys.stderr)
        sys.exit(1)
