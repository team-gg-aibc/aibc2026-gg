"""흐름: 질문 받기 → 검색 → 근거 고르기 · 답 쓰기 → 판정 → 출력.

단계 하나 = 함수 하나이고 경계는 LangGraph 노드와 같다(LangGraph는 쓰지 않음). 단계는 상태 st를 받아 고치고,
확인 불가로 끝낼 때는 st["reason"]에 까닭을 적는다. 새 단계(게이트 · 질문 다듬기 · 묶음 등)는 STAGES에 끼운다.

answer(question, cfg) → (응답 4칸, 판단 기록). 서버는 응답만 내보내고, 점수 틀은 판단 기록으로 틀린 원인을 나눈다.
판단 기록에는 단계마다 걸린 시간(steps)과, 업스테이지 호출마다 단계 이름 · 보낸 메시지 · 모델 출력 · 토큰 · 시간(calls)이 남는다.
궤적 화면: python3 eval/trajectory.py <실행> [문항]. 키 · 개인 정보는 남기지 않는다.
"""
import time
from functools import lru_cache

from . import answer as answer_step
from . import config, contract, retrieve, upstage, verify

# 확인 불가를 낸 까닭 (판단 기록 reason)
LOW_SCORE = "점수 낮음"          # 검증 ①: 1위 후보의 의미 점수가 문턱보다 낮음
NOT_FOUND = "found 거짓"         # 모델이 근거로 답할 수 없다고 함
NO_EVIDENCE = "근거 번호 없음"   # 모델이 고른 번호가 없거나 후보 밖 · 자치구뿐
REJECTED = "판정 거절"           # 검증 ②: 판정이 notGrounded
ERROR = "오류"                   # 호출 실패 · JSON 깨짐 등
TIMEOUT = "시간 초과"            # #22: 마감 시각(받은 때 + timeout_sec)이 지남


def receive(st, cfg):
    """질문 받기. 지금은 그대로 넘긴다(#25 질문 분석 게이트가 여기서 관할 밖 · 지시문을 거른다)."""


def search(st, cfg):
    hits = retrieve.retrieve(st["question"], cfg, st["calls"])
    st["_hits"] = hits
    st["retrieval"] = retrieve.mode(cfg)
    st["candidates"] = [{"label": h["label"], "score": round(h["score"], 4), "kw": round(h["kw"], 4),
                         "cos": None if h["cos"] is None else round(h["cos"], 4)} for h in hits]
    if verify.low_score(hits, cfg):
        st["reason"] = LOW_SCORE


def select_and_write(st, cfg):
    sel = answer_step.select_and_write(st["question"], st["_hits"], cfg, st["calls"])
    st["_sel"] = sel
    st["evidence_ids"] = sel["evidence_ids"]
    if sel["used"]:
        st["draft"] = contract.build(sel["answer"], sel["used"])   # 판정 전 답 (판정이 맞는 답을 버렸는지 보려고)
    if not sel["found"]:
        st["reason"] = NOT_FOUND
    elif not sel["used"]:
        st["reason"] = NO_EVIDENCE


def judge(st, cfg):
    if not cfg["use_verify"]:
        return
    sel = st["_sel"]
    st["verdict"] = verify.judge(answer_step.context(sel["used"]), sel["answer"], cfg, st["calls"], st["question"])
    if st["verdict"] == "notGrounded":
        st["reason"] = REJECTED


def output(st, cfg):
    st["response"] = st["draft"]


STAGES = [("받기", receive), ("검색", search), ("고르기 · 답 쓰기", select_and_write), ("판정", judge), ("출력", output)]


@lru_cache(maxsize=None)
def _index(unit):
    return retrieve.fingerprint(unit)


def _error(e):
    """오류 기록: 바깥 서비스 오류는 종류와 상태 번호만(메시지에 키 일부가 섞일 수 있어서), 우리 오류는 메시지까지."""
    if type(e).__module__.startswith(("openai", "httpx", "requests")):
        return f"{type(e).__name__} {getattr(e, 'status_code', '') or ''}".strip()
    return f"{type(e).__name__}: {str(e)[:200]}"


def answer(question, cfg=None, deadline=None, box=None):
    """deadline: 마감 시각(time.monotonic() 초). 없으면 지금 + timeout_sec. 단계 사이와 업스테이지 호출이 이것을 본다(#22).
    box: 서버가 넘기는 빈 dict. 여기에 진행 중인 상태(box["st"])를 둬서, 서버가 마감에 먼저 답할 때 판정 전 답 · 기록을 쓴다."""
    cfg = cfg or config.load()
    st = {"question": question, "reason": None, "error": None, "retrieval": None, "candidates": [],
          "evidence_ids": [], "draft": None, "verdict": None, "response": None, "steps": {}, "calls": [],
          "settings": config.digest(cfg),
          "switches": {k: v for k, v in cfg.items() if config.DEFAULTS.get(k) != v},
          "models": {"chat": cfg["chat_model"], "embed_query": cfg["embed_query"]},
          "prompts": {"answer": cfg["answer_prompt"], "verify": cfg["verify_prompt"]},
          "index": _index(cfg["chunk_unit"])}
    if box is not None:
        box["st"] = st
    t0 = time.perf_counter()
    deadline = deadline if deadline is not None else time.monotonic() + cfg["timeout_sec"]
    with upstage.budget(cfg, deadline):
        for name, fn in STAGES:
            if time.monotonic() >= deadline:
                st["reason"] = TIMEOUT
                break
            t, n = time.perf_counter(), len(st["calls"])
            try:
                fn(st, cfg)
            except upstage.DeadlineExceeded:
                st["reason"] = TIMEOUT
            except Exception as e:  # noqa: BLE001  어떤 오류든 확인 불가로 끝내고 까닭을 남긴다
                st["reason"], st["error"] = ERROR, _error(e)
            st["steps"][name] = round(time.perf_counter() - t, 3)
            for c in st["calls"][n:]:
                c["stage"] = name
            if st["reason"]:
                break
    st["sec"] = round(time.perf_counter() - t0, 3)
    resp = final(st, cfg)
    trace = {k: v for k, v in st.items() if not k.startswith("_") and k != "response"}
    return resp, trace


def final(st, cfg):
    """나갈 응답. 마감이 지났고 on_deadline이 "draft"면 판정 전 답을 낸다. exit_check면 마지막 출구 검사를 건다(#22)."""
    if st["reason"] == TIMEOUT and cfg["on_deadline"] == "draft" and st["draft"]:
        resp = st["draft"]
    elif st["reason"] or not st["response"]:
        resp = contract.unknown()
    else:
        resp = st["response"]
    return contract.finalize(resp, cfg) if cfg["exit_check"] else resp


if __name__ == "__main__":   # 한 문항 돌려 보기: python3 -m engine.pipeline "질문" [설정 파일]
    import json
    import sys
    r, t = answer(sys.argv[1], config.load(sys.argv[2] if len(sys.argv) > 2 else None))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print("판단 기록:", json.dumps(t, ensure_ascii=False, indent=1))
