"""채점 API 서버 (킷 app.py 그대로 옮김).

실행:  uvicorn engine.server:app --host 0.0.0.0 --port 8000     (레포 맨 위 폴더에서)
설정:  ENGINE_CONFIG=eval/configs/baseline.json 처럼 설정 파일을 고른다(없으면 출발 판)
호출:  POST /ask  {"question": "장애인 주차요금 감면되나요?"}

채점은 운영진이 마감 직후 한 번 실행한다. 문항당 90초를 넘기거나 오류가 나면 0점이다.
그래서 어떤 경우에도 정해진 JSON을 돌려주게 감쌌다. 마지막 출구 검사 · 판단 기록 파일은 #22 출력 규격 강제(동욱) 몫.
"""
import asyncio
import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel

from . import config, contract, pipeline

CFG = config.load(os.environ.get("ENGINE_CONFIG") or None)
app = FastAPI(title="서울시 조례 Q&A")
log = logging.getLogger("uvicorn.error")


class Ask(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"ok": True, "settings": config.digest(CFG), "config": os.environ.get("ENGINE_CONFIG") or "출발 판"}


@app.post("/ask")
async def ask(req: Ask):
    try:
        resp, trace = await asyncio.wait_for(asyncio.to_thread(pipeline.answer, req.question, CFG),
                                             timeout=CFG["timeout_sec"])
        if trace["reason"]:
            log.info("확인 불가: %s %s", trace["reason"], trace["error"] or "")
        return resp
    except Exception as e:  # noqa: BLE001  시간 초과 · 그 밖의 오류 모두 「확인 불가」로 답한다
        log.warning("ask failed: %s", type(e).__name__)
        return contract.unknown()
