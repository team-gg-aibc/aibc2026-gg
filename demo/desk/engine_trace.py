"""채점 API 서버(engine.server)에 화면용 길 하나(POST /ask/trace)를 더해 띄운다. 엔진 코드는 고치지 않고 불러다 쓴다.

실행 (레포 맨 위에서, 엔진 가상 환경의 파이썬):
    ENGINE_CONFIG=eval/configs/pm-flow2-v7.json python3 demo/desk/engine_trace.py          # 127.0.0.1:8000
    python3 demo/desk/engine_trace.py --selftest                                             # 키 없이 몇 초

- /ask · /health는 engine.server 그대로다(채점 응답 네 칸, 판단 기록 한 줄도 그대로 남는다).
- /ask/trace는 같은 질문에 {"response": 네 칸, "trace": 화면에 쓰는 기록}을 돌려준다. 기록에는 판정 낱말 · 근거로 옮긴 구절 ·
  구절 관문이 남긴 조항 · 확인 불가 사유만 담는다(업스테이지에 보낸 글 · 키 · 프롬프트는 담지 않는다).
- ponytail: 이 길은 엔진 쪽 일(만들 것 목록 E1)이 끝나기 전의 임시 다리다. 엔진이 같은 기록을 내주게 되면 이 파일은 필요 없다.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import Request                      # noqa: E402
from fastapi.responses import JSONResponse       # noqa: E402

from engine import contract, pipeline, server    # noqa: E402

app = server.app


def screen_trace(st):
    """판단 기록에서 화면에 쓰는 것만."""
    st = st or {}
    f2 = st.get("flow2") or {}
    read, gate = f2.get("read") or {}, f2.get("gate") or {}
    route = f2.get("route") or {}
    return {"reason": st.get("reason"), "error": st.get("error"), "sec": st.get("sec"),
            "flow": "flow2" if f2 else "kit", "settings": st.get("settings"),
            "conclusion": read.get("conclusion"),
            "evidence": [{"label": e.get("label", ""), "quote": e.get("quote", "")}
                         for e in (read.get("evidence") or []) if isinstance(e, dict)],
            "kept": gate.get("kept"), "dropped": [{"label": d.get("label"), "why": d.get("why")} for d in gate.get("dropped") or []],
            "laws": route.get("laws"), "block": route.get("block"),
            "verdict": st.get("verdict")}


@app.post("/ask/trace")
async def ask_trace(request: Request):
    """server.respond와 같은 고리(마감 · 오류면 확인 불가 · 출구 검사)에 기록을 함께 돌려준다."""
    t0 = time.monotonic()
    cfg, box = server.CFG, {}
    try:
        question = server.question_of(await request.body())
        if question is None:
            return JSONResponse({"response": contract.unknown(), "trace": {"reason": "요청 본문 이상"}})
        try:
            resp, _ = await asyncio.wait_for(
                asyncio.to_thread(pipeline.answer, question, cfg, t0 + cfg["timeout_sec"], box), timeout=cfg["timeout_sec"])
        except asyncio.TimeoutError:
            st = box.get("st") or {"reason": None, "draft": None, "response": None}
            st["reason"] = pipeline.TIMEOUT
            resp = pipeline.final(st, cfg)
        resp = contract.guard(resp)
        st = box.get("st")
        server.write_log(question, resp, st, time.monotonic() - t0, "화면 길(/ask/trace)")
        return JSONResponse({"response": resp, "trace": screen_trace(st)})
    except Exception as e:  # noqa: BLE001  무엇이 깨져도 확인 불가 꼴로 답한다
        return JSONResponse({"response": contract.unknown(), "trace": {"reason": pipeline.ERROR, "error": type(e).__name__}})


def selftest():
    """키 없이: 기록 고르기와 길이 붙었는지만 본다."""
    st = {"reason": None, "sec": 1.2, "flow2": {"read": {"conclusion": "네", "evidence": [{"label": "가 제1조", "quote": "구절"}]},
                                                 "gate": {"kept": ["가 제1조"], "dropped": [{"label": "나", "why": "자치구", "quote": "x"}]},
                                                 "route": {"laws": ["가"], "block": None}}}
    t = screen_trace(st)
    assert t["conclusion"] == "네" and t["evidence"][0]["quote"] == "구절" and t["kept"] == ["가 제1조"], t
    assert t["dropped"] == [{"label": "나", "why": "자치구"}] and t["flow"] == "flow2", t   # 버린 구절 글은 싣지 않는다
    assert screen_trace(None)["reason"] is None
    assert {r.path for r in app.routes} >= {"/ask", "/ask/trace", "/health"}
    print("engine_trace 스스로 시험 통과")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        import uvicorn
        uvicorn.run(app, host=os.environ.get("ENGINE_HOST", "127.0.0.1"), port=int(os.environ.get("ENGINE_PORT", "8000")))
