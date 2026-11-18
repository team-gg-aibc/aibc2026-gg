"""직접 통화(배포 판). 스위치 CALL_DIRECT=1일 때만 붙는다. 기본 끔이고, 끄면 읽히지도 않는다.

방문자가 민원인이 되어 글을 치거나 말하면(마이크는 CALL_VOICE=1을 함께 켤 때), 차례는 화면(web/direct.js)이 다룬다:
상담사 말은 읽어 주지 않고 대화창에만 올리며, 답을 만드는 동안 더 들어온 말은 합쳐 그 차례를 다시 읽는다.
서버 쪽에는 열쇠를 지키는 자리만 둔다(자세한 정책은 배포를 맡은 세션이 정한다):
  접근 코드   CALL_DIRECT_CODE가 있으면 POST /api/direct/enter 로 맞힌 사람에게만 표(쿠키)를 준다. 코드가 없으면 누구에게나 준다.
              표가 없으면 POST /api/… 는 모두 403(통화 읽기 · 엔진 · 별명 · 기록 · 음성 길까지).
  횟수 상한   민원인의 말 한 줄(POST /api/turn 에 민원인 줄)을 표마다 · 서버 전체로 센다. 넘으면 429.
열쇠(UPSTAGE_API_KEY · ELEVENLABS_API_KEY)는 서버 환경에만 있고, 어느 응답에도 실리지 않는다.
실제 호출 방식으로 켜면서 접근 코드가 없으면 서버가 뜨지 않는다(열쇠를 모르는 새 열어 두지 않게). 코드 없이 여는 정식 방식은 CALL_DIRECT_OPEN=1
(앞에 문지기를 둘 때 · 11/22 평가자용 주소. 그때의 보호는 문지기가 맡는다).
민원인의 글은 한 차례 CALL_DIRECT_SAID_MAX자까지 읽는다(server.py의 SAID_MAX를 늘린다. 스위치를 끄면 500 그대로). 넘으면 화면이 앞부분으로 답하고 알린다.
긴 글에서 규정을 묻는 말을 찾는 정규식(server.py RULE_Q)이 꾸민 2,000자에 3초 넘게 걸려, 같은 답을 내는 빠른 길(_Rule)로 바꿔 끼운다(56번 20절).

| 환경 변수 | 뜻 | 기본 |
| CALL_DIRECT | 1이면 켠다 | 끔 |
| CALL_DIRECT_CODE | 접근 코드 | 없음 |
| CALL_DIRECT_OPEN | 1이면 접근 코드 없이 연다(누구나 표를 받는다). 저장된 답 방식은 이것 없이도 열린다 | 끔 |
| CALL_DIRECT_SAID_MAX · CALL_DIRECT_INPUT_MAX | 서버가 한 차례에 읽는 민원인 글 자 수 · 입력 칸 자 수 | 2000 · 1000 |
| CALL_DIRECT_SETTLE_MS | 받아쓴 말이 이만큼 멎어야 읽는다(말로 할 때만. 글은 보내기를 누르면 바로). 동규 11/19: 3초 | 3000 |
| CALL_DIRECT_MAX_TURNS | 표 하나가 넣을 수 있는 민원인의 말 수 | 0 = 제한 없음 |
| CALL_DIRECT_MAX_ALL | 서버를 띄운 동안 모두 합친 민원인의 말 수 | 0 = 제한 없음 |
"""
import hmac
import io
import json
import os
import re
import secrets
import sys
import threading
from http.cookies import SimpleCookie

CODE = os.environ.get("CALL_DIRECT_CODE", "")
OPEN = os.environ.get("CALL_DIRECT_OPEN") == "1"
SAID_MAX = int(os.environ.get("CALL_DIRECT_SAID_MAX") or 2000)
INPUT_MAX = int(os.environ.get("CALL_DIRECT_INPUT_MAX") or 1000)
SETTLE_MS = int(os.environ.get("CALL_DIRECT_SETTLE_MS") or 3000)
MAX_TURNS = int(os.environ.get("CALL_DIRECT_MAX_TURNS", "0")) or 10**9      # 0 = 제한 없음(기본). 현장 테스트는 앞에 둔 문지기가 막는다
MAX_ALL = int(os.environ.get("CALL_DIRECT_MAX_ALL", "0")) or 10**9
COOKIE = "gg_call"
passes, used, lock = {}, {"all": 0}, threading.Lock()      # 표 → 넣은 민원인의 말 수. ponytail: 서버 메모리에만(다시 띄우면 0). 여러 서버로 늘리면 밖의 저장소로


def _pass(h):
    c = SimpleCookie(h.headers.get("Cookie") or "")
    t = c[COOKIE].value if COOKIE in c else ""
    return t if t in passes else None


def _info(t):
    return {"on": True, "code": bool(CODE), "pass": bool(t), "used": passes.get(t, 0) if t else 0, "max": MAX_TURNS, "left_all": max(0, MAX_ALL - used["all"]),
            "said_max": SAID_MAX, "input_max": INPUT_MAX, "settle_ms": SETTLE_MS}


class _Rule:
    """RULE_Q(「[^.?!]*(낱말…)[^.?!]*\\?」)와 같은 답: 그 꼴의 맞는 글은 「?」로 끝나는 한 문장 토막 전체이고, 가장 앞의 것이다.
    그래서 「?」로 끝나고 낱말이 든 첫 토막에만 원래 정규식을 건다 → 글 길이에 비례한다(원래는 꾸민 글에서 세제곱)."""
    SEG = re.compile(r"[^.?!]*[.?!]?")
    HEAD, TAIL = "[^.?!]*(", ")[^.?!]*\\?"

    def __init__(self, rx):
        assert rx.pattern.startswith(self.HEAD) and rx.pattern.endswith(self.TAIL), "RULE_Q의 꼴이 바뀌었다"
        self.rx, self.kw = rx, re.compile(rx.pattern[len(self.HEAD) - 1:-len(self.TAIL) + 1])

    def search(self, s):
        for m in self.SEG.finditer(s):
            seg = m.group()
            if seg.endswith("?") and self.kw.search(seg):
                return self.rx.search(seg)
        return None


def attach(Handler):
    from . import add_script
    mod = sys.modules[Handler.__module__]
    if mod.MODE == "live" and not CODE and not OPEN:
        raise SystemExit("직접 통화를 실제 호출로 켜려면 접근 코드(CALL_DIRECT_CODE)를 주거나, 앞에 문지기를 두고 코드 없이 열 때는 CALL_DIRECT_OPEN=1을 준다")
    mod.SAID_MAX = SAID_MAX                            # 한 차례 글(스위치를 끄면 server.py의 500 그대로)
    mod.RULE_Q = _Rule(mod.RULE_Q)                     # ponytail: server.py의 이름(MODE · SAID_MAX · RULE_Q)에 기대어 바꾼다. 이름이 바뀌면 check_direct가 깨져 알린다
    add_script(Handler, "direct.js")
    get, post = Handler.do_GET, Handler.do_POST

    def do_GET(self):
        if self.path.split("?")[0] == "/api/direct/info":
            return self.send_json(_info(_pass(self)))
        return get(self)

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if p == "/api/direct/enter":                       # 접근 코드 → 표(쿠키, 화면 스크립트는 읽지 못한다)
            try:
                b = json.loads(self.rfile.read(n).decode("utf-8")) if 0 < n < 10_000 else {}
            except ValueError:
                b = {}
            if CODE and not hmac.compare_digest(str(b.get("code", "") if isinstance(b, dict) else "").encode(), CODE.encode()):
                return self.send_json({"error": "접근 코드가 다릅니다."}, 403)
            t = _pass(self) or secrets.token_urlsafe(18)
            with lock:
                passes.setdefault(t, 0)
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", f"{COOKIE}={t}; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if not p.startswith("/api/"):
            return post(self)
        t = _pass(self)
        if not t:
            return self.send_json({"error": "접근 코드가 필요합니다.", "need_code": True}, 403)
        if p == "/api/turn" and 0 < n < 600_000:            # 민원인의 말 한 줄을 센다. 본문은 server.py가 다시 읽으니 읽은 뒤 되돌려 둔다
            raw = self.rfile.read(n)
            self.rfile = io.BytesIO(raw)
            try:
                line = json.loads(raw.decode("utf-8")).get("line") or {}
            except (ValueError, AttributeError):
                line = {}
            if isinstance(line, dict) and line.get("who") == "시민" and str(line.get("text", "")).strip():
                with lock:
                    if passes[t] >= MAX_TURNS or used["all"] >= MAX_ALL:
                        return self.send_json({"error": "쓸 수 있는 횟수를 다 썼습니다.", "limit": True}, 429)
                    passes[t] += 1
                    used["all"] += 1
        return post(self)

    Handler.do_GET, Handler.do_POST = do_GET, do_POST
    print(f"직접 통화 켬: 접근 코드 {'받음' if CODE else '없음(열어 둠)' if OPEN else '없음'} · 상한 {MAX_TURNS if MAX_TURNS < 10**9 else '없음'} · {MAX_ALL if MAX_ALL < 10**9 else '없음'} · 한 차례 {SAID_MAX}자")
