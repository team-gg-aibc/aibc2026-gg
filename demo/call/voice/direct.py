"""직접 통화(배포 판). 스위치 CALL_DIRECT=1일 때만 붙는다. 기본 끔이고, 끄면 읽히지도 않는다.

방문자가 민원인이 되어 글을 치거나 말하면(마이크는 CALL_VOICE=1을 함께 켤 때), 차례는 화면(web/direct.js)이 다룬다:
상담사 말은 읽어 주지 않고 대화창에만 올리며, 답을 만드는 동안 더 들어온 말은 합쳐 그 차례를 다시 읽는다.
서버 쪽에는 열쇠를 지키는 자리만 둔다(자세한 정책은 배포를 맡은 세션이 정한다):
  접근 코드   CALL_DIRECT_CODE가 있으면 POST /api/direct/enter 로 맞힌 사람에게만 표(쿠키)를 준다. 코드가 없으면 누구에게나 준다.
              표가 없으면 POST /api/… 는 모두 403(통화 읽기 · 엔진 · 별명 · 기록 · 음성 길까지).
  횟수 상한   민원인의 말 한 줄(POST /api/turn 에 민원인 줄)을 표마다 · 서버 전체로 센다. 넘으면 429.
열쇠(UPSTAGE_API_KEY · ELEVENLABS_API_KEY)는 서버 환경에만 있고, 어느 응답에도 실리지 않는다.

| 환경 변수 | 뜻 | 기본 |
| CALL_DIRECT | 1이면 켠다 | 끔 |
| CALL_DIRECT_CODE | 접근 코드 | 없음(누구나 표를 받는다) |
| CALL_DIRECT_MAX_TURNS | 표 하나가 넣을 수 있는 민원인의 말 수 | 40 |
| CALL_DIRECT_MAX_ALL | 서버를 띄운 동안 모두 합친 민원인의 말 수 | 600 |
"""
import hmac
import io
import json
import os
import secrets
import threading
from http.cookies import SimpleCookie

CODE = os.environ.get("CALL_DIRECT_CODE", "")
MAX_TURNS = int(os.environ.get("CALL_DIRECT_MAX_TURNS", "40"))
MAX_ALL = int(os.environ.get("CALL_DIRECT_MAX_ALL", "600"))
COOKIE = "gg_call"
passes, used, lock = {}, {"all": 0}, threading.Lock()      # 표 → 넣은 민원인의 말 수. ponytail: 서버 메모리에만(다시 띄우면 0). 여러 서버로 늘리면 밖의 저장소로


def _pass(h):
    c = SimpleCookie(h.headers.get("Cookie") or "")
    t = c[COOKIE].value if COOKIE in c else ""
    return t if t in passes else None


def _info(t):
    return {"on": True, "code": bool(CODE), "pass": bool(t), "used": passes.get(t, 0) if t else 0, "max": MAX_TURNS, "left_all": max(0, MAX_ALL - used["all"])}


def attach(Handler):
    from . import add_script
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
    print(f"직접 통화 켬: 접근 코드 {'받음' if CODE else '없음'} · 표마다 {MAX_TURNS}마디 · 모두 {MAX_ALL}마디")
