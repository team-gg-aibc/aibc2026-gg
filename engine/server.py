"""채점 API 서버 (킷 app.py를 옮기고 #22 출력 규격 강제를 더함).

실행:  uvicorn engine.server:app --host 0.0.0.0 --port 8000     (레포 맨 위 폴더에서, 워커는 하나: --workers를 주지 않는다)
설정:  ENGINE_CONFIG=eval/configs/baseline.json 처럼 설정 파일을 고른다(없으면 출발 판)
호출:  POST /ask  {"question": "장애인 주차요금 감면되나요?"}

채점은 운영진이 마감 직후 한 번 실행한다. 문항당 90초를 넘기거나 오류가 나면 0점이다. 그래서(#22):
- 요청을 받은 때 + timeout_sec(75초)를 마감 시각으로 정해 흐름에 넘기고, 마감이 오면 흐름을 기다리지 않고 답한다
  (on_deadline이 "draft"면 판정 전 답, 아니면 확인 불가).
- 어떤 요청 · 오류에도 HTTP 200 + 네 칸 JSON이다. 요청 본문이 이상하면(질문 칸 없음 · 빈 문자열 · JSON 깨짐) 확인 불가.
- 나가기 직전에 꼴을 한 번 더 본다(contract.guard, exit_check면 흐름 끝에서 contract.finalize도).
- 문항마다 판단 기록 한 줄을 logs/server-YYYYMMDD.jsonl에 남긴다(ENGINE_LOG_DIR로 바꿈, 빈 값이면 남기지 않음).
  키는 없고, 업스테이지에 보낸 글 · 모델 출력은 빼고 모델 · 토큰 · 시간만 남긴다.
"""
import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config, contract, pipeline

CFG = config.load(os.environ.get("ENGINE_CONFIG") or None)
LOG_DIR = os.environ.get("ENGINE_LOG_DIR", str(config.ROOT / "logs"))
KST = timezone(timedelta(hours=9))
app = FastAPI(title="서울시 조례 Q&A")
log = logging.getLogger("uvicorn.error")
_log_lock = threading.Lock()


@app.get("/health")
def health():
    return {"ok": True, "settings": config.digest(CFG), "config": os.environ.get("ENGINE_CONFIG") or "출발 판"}


def question_of(body):
    """요청 본문에서 질문을 꺼낸다. 없거나 이상하면 None."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    q = data.get("question") if isinstance(data, dict) else None
    return q.strip() if isinstance(q, str) and q.strip() else None


def write_log(question, resp, st, sec, note):
    """판단 기록 한 줄. 못 남겨도 답은 나간다."""
    if not LOG_DIR:
        return
    st = st or {}
    line = {"at": datetime.now(KST).isoformat(timespec="seconds"), "question": question, "sec": round(sec, 3),
            "note": note, "unknown": contract.is_unknown(resp), "citation": resp["citation"],
            "reason": st.get("reason"), "error": st.get("error"), "settings": st.get("settings"),
            "candidates": [c["label"] for c in st.get("candidates", [])], "evidence_ids": st.get("evidence_ids"),
            "verdict": st.get("verdict"), "steps": st.get("steps"),
            "calls": [{k: c.get(k) for k in ("stage", "kind", "model", "in", "out", "sec")} for c in st.get("calls", [])]}
    try:
        path = Path(LOG_DIR) / f"server-{datetime.now(KST):%Y%m%d}.jsonl"
        with _log_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log.warning("판단 기록 실패: %s", type(e).__name__)


async def respond(body):
    """요청 본문(bytes) → 네 칸 응답. 어떤 경우에도 예외를 밖으로 내지 않는다."""
    t0 = time.monotonic()
    cfg, box, note, question = CFG, {}, "", None
    try:
        question = question_of(body)
        if question is None:
            resp, note = contract.unknown(), "요청 본문 이상"
        else:
            try:
                resp, _ = await asyncio.wait_for(
                    asyncio.to_thread(pipeline.answer, question, cfg, t0 + cfg["timeout_sec"], box),
                    timeout=cfg["timeout_sec"])
            except asyncio.TimeoutError:     # 흐름이 마감까지 안 끝남: 기다리지 않고 지금 상태로 답한다
                st = box.get("st") or {"reason": None, "draft": None, "response": None}
                st["reason"] = pipeline.TIMEOUT          # 뒤에서 도는 흐름도 다음 단계에서 멈춘다
                resp, note = pipeline.final(st, cfg), "마감에 서버가 먼저 답함"
            reason = (box.get("st") or {}).get("reason")
            if reason:
                log.info("확인 불가: %s %s", reason, box["st"].get("error") or "")
        resp = contract.guard(resp)
    except Exception as e:  # noqa: BLE001  무엇이 깨져도 확인 불가로 답한다
        log.warning("ask failed: %s", type(e).__name__)
        resp, note = contract.unknown(), f"서버 오류 {type(e).__name__}"
    write_log(question, resp, box.get("st"), time.monotonic() - t0, note)
    return resp


@app.post("/ask")
async def ask(request: Request):
    try:
        body = await request.body()
    except Exception:  # noqa: BLE001
        body = b""
    return JSONResponse(await respond(body))
