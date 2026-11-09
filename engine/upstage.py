"""업스테이지 호출 한 곳 (Chat · Embedding · Document Parse). AGENTS.md 5절: 바깥 서비스 호출은 여기서만.

Solar는 OpenAI SDK와 호환된다(base_url만 바꿈). 부를 때마다 `calls` 목록에 모델 · 토큰 · 걸린 시간 · 보낸 메시지 · 모델 출력을
남긴다. 점수 틀(eval/run.py)이 이 기록으로 비용을 내고, 궤적 화면(eval/trajectory.py)이 단계마다 보여 준다. 키 값은 기록하지 않는다.
"""
import contextvars
import json
import threading
import time
from contextlib import contextmanager

import requests

from . import config

BASE_URL = "https://api.upstage.ai/v1"

# 100만 토큰당 달러 (입력, 캐시된 입력, 출력). upstage.ai/pricing 2026-11-06 확인. 값이 바뀌면 여기만 고친다.
PRICES = {
    "solar-pro4": (0.30, 0.06, 1.20),
    "solar-mini4": (0.10, 0.01, 0.40),
    "solar-embedding-2-query": (0.02, 0.02, 0.0),
    "solar-embedding-2-passage": (0.02, 0.02, 0.0),
}

_client = None
_lock = threading.Lock()


def has_key():
    return bool(config.api_key())


def client():
    global _client
    with _lock:
        if _client is None:
            key = config.api_key()
            if not key:
                # SystemExit이 아니라 일반 예외로: 서버가 잡아서 「확인 불가」로 답할 수 있게
                raise RuntimeError("UPSTAGE_API_KEY가 없습니다. .env.example을 .env로 복사하고 키를 넣어 주세요.")
            from openai import OpenAI
            _client = OpenAI(api_key=key, base_url=BASE_URL)
    return _client


def _retry(fn, tries=4):
    """429(too_many_requests)는 잠시 기다렸다 다시 부른다(킷 그대로). retry_budget을 켜면 아래 _call이 대신한다."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) and i < tries - 1:
                time.sleep(2 ** i)
                continue
            raise


# ---- #22 시간 예산 · 재시도 · 동시 호출 제한 ----
# 흐름(pipeline.answer)이 문항마다 budget(cfg, 마감 시각)을 걸어 두면, 그 안의 호출은 마감을 보고 재시도 · 대기를 멈춘다.
# 마감 시각은 time.monotonic() 기준 초다. budget 밖(색인 만들기 등)에서 부르면 킷 그대로 돈다.
RETRY_TRIES = 6         # retry_budget: 한 호출에 많아야 이만큼 (마감이 먼저 오면 그 전에 멈춘다)
RETRY_CAP_SEC = 8.0     # 재시도 간격 상한 (0.5 · 1 · 2 · 4 · 8 …초)
MIN_TRY_SEC = 1.0       # 마감까지 이보다 적게 남으면 새로 부르지 않는다
_budget = contextvars.ContextVar("upstage_budget", default=None)
_slots, _slots_lock = {}, threading.Lock()


class DeadlineExceeded(Exception):
    """마감 시각이 지나(또는 곧 지나) 더 부르지 않는다. 흐름은 이것을 「시간 초과」로 남긴다."""


@contextmanager
def budget(cfg, deadline):
    """이 안의 업스테이지 호출에 설정(retry_budget · max_concurrent_calls)과 마감 시각(monotonic 초)을 건다."""
    token = _budget.set((deadline, cfg))
    try:
        yield
    finally:
        _budget.reset(token)


def retryable(e):
    """다시 불러 볼 만한 오류: 429 · 5xx · 시간 초과 · 연결 오류. 그 밖의 4xx는 다시 불러도 같다."""
    status = getattr(e, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    names = {c.__name__ for c in type(e).__mro__}
    return bool(names & {"APITimeoutError", "APIConnectionError", "TimeoutError", "ConnectionError"})


def _left(deadline):
    return None if deadline is None else deadline - time.monotonic()


def _in_slot(cfg, deadline, fn):
    """동시 호출 상한(max_concurrent_calls)이 있으면 자리가 날 때까지(마감 전까지만) 기다린다."""
    n = cfg.get("max_concurrent_calls")
    if not n:
        return fn()
    with _slots_lock:
        sem = _slots.setdefault(n, threading.BoundedSemaphore(n))
    left = _left(deadline)
    if not sem.acquire(timeout=None if left is None else max(0.0, left - MIN_TRY_SEC)):
        raise DeadlineExceeded("동시 호출 자리를 마감 전에 얻지 못함")
    try:
        return fn()
    finally:
        sem.release()


def _call(fn):
    """업스테이지 호출 하나. fn(client) → 응답."""
    deadline, cfg = _budget.get() or (None, {})
    if not cfg.get("retry_budget"):
        return _retry(lambda: _in_slot(cfg, deadline, lambda: fn(client())))
    for i in range(RETRY_TRIES):
        left = _left(deadline)
        if left is not None and left < MIN_TRY_SEC:
            raise DeadlineExceeded("마감이 가까워 부르지 않음")
        opts = {"max_retries": 0} if left is None else {"max_retries": 0, "timeout": left}
        c = client()
        c = c.with_options(**opts) if hasattr(c, "with_options") else c
        try:
            return _in_slot(cfg, deadline, lambda: fn(c))
        except DeadlineExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            if not retryable(e) or i == RETRY_TRIES - 1:
                raise
            wait = min(RETRY_CAP_SEC, 0.5 * 2 ** i)
            left = _left(deadline)
            if left is not None and left < wait + MIN_TRY_SEC:
                raise DeadlineExceeded(f"재시도할 시간이 없음 ({type(e).__name__})") from e
            time.sleep(wait)


def _log(calls, kind, model, usage, t0, sent, output):
    if calls is None:
        return
    details = getattr(usage, "prompt_tokens_details", None)
    calls.append({"kind": kind, "model": model,
                  "in": getattr(usage, "prompt_tokens", 0) or 0,
                  "cached": getattr(details, "cached_tokens", 0) or 0,
                  "out": getattr(usage, "completion_tokens", 0) or 0,
                  "sec": round(time.perf_counter() - t0, 3), "sent": sent, "output": output})


def chat(messages, cfg, calls=None, response_format=None):
    kw = dict(model=cfg["chat_model"], messages=messages, temperature=cfg["temperature"])
    if response_format:
        kw["response_format"] = response_format
    if cfg["reasoning_effort"]:
        kw["reasoning_effort"] = cfg["reasoning_effort"]
    t0 = time.perf_counter()
    resp = _call(lambda c: c.chat.completions.create(**kw))
    content = resp.choices[0].message.content
    _log(calls, "chat", cfg["chat_model"], resp.usage, t0, messages, content)
    return content


def embed(texts, model, calls=None):
    out = []
    for i in range(0, len(texts), 50):        # 한 번에 너무 많이 보내지 않는다
        batch = texts[i:i + 50]
        t0 = time.perf_counter()
        resp = _call(lambda c, b=batch: c.embeddings.create(model=model, input=b))
        _log(calls, "embed", model, resp.usage, t0, batch, f"{len(resp.data)}개 × {len(resp.data[0].embedding)}차원")
        out.extend(d.embedding for d in resp.data)
    return out


def cost_usd(calls):
    """calls 기록으로 비용을 낸다. 표에 없는 모델은 None (모르는 값을 0으로 두지 않는다)."""
    total = 0.0
    for c in calls:
        if c["model"] not in PRICES:
            return None
        p_in, p_cached, p_out = PRICES[c["model"]]
        total += ((c["in"] - c["cached"]) * p_in + c["cached"] * p_cached + c["out"] * p_out) / 1e6
    return total


def document_parse(path):
    """Document Parse: 문서를 구조가 살아 있는 Markdown으로 바꾼다. 표가 표로 남는다."""
    url = f"{BASE_URL}/document-digitization"
    headers = {"Authorization": f"Bearer {config.api_key()}"}
    with open(path, "rb") as f:
        resp = requests.post(url, headers=headers, timeout=300,
                             files={"document": f},
                             data={"model": "document-parse",
                                   "output_formats": json.dumps(["html", "markdown"])})
    resp.raise_for_status()
    content = resp.json().get("content", {})
    return content.get("markdown") or content.get("html") or content.get("text") or ""
