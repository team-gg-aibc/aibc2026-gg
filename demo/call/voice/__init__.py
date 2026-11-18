"""통화의 두 스위치. server.py는 둘 가운데 하나라도 켜졌을 때만 이 꾸러미를 불러온다(기본 끔).

  CALL_VOICE=1   음성 통화(받아쓰기 · 읽어 주기)            hub.py · README.md
  CALL_DIRECT=1  직접 통화(배포 판: 방문자가 민원인이 되어 글을 치거나 말하고, 상담사 말은 화면으로만)   direct.py
"""
import os
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def add_script(Handler, name):
    """첫 화면(index.html)에 스크립트를 끼운다. 파일(index.html · call.js)은 그대로 두고 내보낼 때만 끼운다."""
    if not hasattr(Handler, "_scripts"):
        Handler._scripts, get = [], Handler.do_GET

        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html"):
                return get(self)
            tags = "".join(f'<script src="{s}"></script>\n' for s in Handler._scripts)
            body = (WEB / "index.html").read_text(encoding="utf-8").replace("</body>", tags + "</body>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        Handler.do_GET = do_GET
    Handler._scripts.append(name)


def attach(Handler):
    if os.environ.get("CALL_VOICE") == "1":
        from . import hub
        hub.attach(Handler)
    if os.environ.get("CALL_DIRECT") == "1":
        from . import direct
        direct.attach(Handler)
