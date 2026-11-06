"""업스테이지 호출 한 곳 (Chat · Embedding · Document Parse). AGENTS.md 5절: 바깥 서비스 호출은 여기서만.

Solar는 OpenAI SDK와 호환된다(base_url만 바꿈). 부를 때마다 `calls` 목록에 모델 · 토큰 · 걸린 시간 · 보낸 메시지 · 모델 출력을
남긴다. 점수 틀(eval/run.py)이 이 기록으로 비용을 내고, 궤적 화면(eval/trajectory.py)이 단계마다 보여 준다. 키 값은 기록하지 않는다.
"""
import json
import threading
import time

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
    """429(too_many_requests)는 잠시 기다렸다 다시 부른다(킷 그대로). 시간 예산 · 5xx는 #22 출력 규격 강제 몫."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) and i < tries - 1:
                time.sleep(2 ** i)
                continue
            raise


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
    resp = _retry(lambda: client().chat.completions.create(**kw))
    content = resp.choices[0].message.content
    _log(calls, "chat", cfg["chat_model"], resp.usage, t0, messages, content)
    return content


def embed(texts, model, calls=None):
    out = []
    for i in range(0, len(texts), 50):        # 한 번에 너무 많이 보내지 않는다
        batch = texts[i:i + 50]
        t0 = time.perf_counter()
        resp = _retry(lambda: client().embeddings.create(model=model, input=batch))
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
