"""검색: 임베딩(의미) + 키워드(글자 2개 단위 BM25) 혼합. 임베딩을 못 쓰면 키워드만 쓴다(킷 그대로).

색인은 engine/data/chunks_<단위>.json(조각) · vectors_<단위>.npy(조각 임베딩) · index_<단위>.json(둘이 짝인지 보는 지문)이다.
조각 글을 바꾸면 임베딩도 다시 만들어야 한다(python3 -m engine.build_index). 짝이 안 맞으면 의미 검색을 하지 않고 멈춘다.
"""
import hashlib
import json
import math
import re
import threading
from collections import Counter

import numpy as np

from . import config, upstage

_cache = {}
_lock = threading.Lock()


def bigrams(text):
    t = re.sub(r"\s+", "", text)
    return [t[i:i + 2] for i in range(len(t) - 1)]


def chunks_digest(chunks):
    return hashlib.sha256("\n".join(c["text"] for c in chunks).encode("utf-8")).hexdigest()


def load(unit):
    with _lock:
        if unit not in _cache:
            chunks = json.loads((config.DATA / f"chunks_{unit}.json").read_text(encoding="utf-8"))
            vec_path, meta_path = config.DATA / f"vectors_{unit}.npy", config.DATA / f"index_{unit}.json"
            vecs = np.load(vec_path) if vec_path.exists() else None
            stale = vecs is not None and (
                not meta_path.exists()
                or json.loads(meta_path.read_text(encoding="utf-8"))["chunks_sha256"] != chunks_digest(chunks)
                or len(vecs) != len(chunks))
            if vecs is not None:
                vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
            docs = [Counter(bigrams(c["label"] + " " + c["text"])) for c in chunks]
            df = Counter(g for d in docs for g in d)
            avg = sum(sum(d.values()) for d in docs) / len(docs)
            _cache[unit] = (chunks, vecs, stale, docs, df, avg)
        return _cache[unit]


def fingerprint(unit):
    """결과 파일에 찍는 색인 지문: 조각 파일 · 임베딩 파일의 sha256 앞 12자리."""
    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.exists() else "없음"
    return f"chunks:{sha(config.DATA / f'chunks_{unit}.json')} vectors:{sha(config.DATA / f'vectors_{unit}.npy')}"


def bm25(query, docs, df, avg, k1=1.2, b=0.75):
    n = len(docs)
    q = set(bigrams(query))
    scores = np.zeros(n)
    for i, d in enumerate(docs):
        ln = sum(d.values())
        s = 0.0
        for g in q:
            if g in d:
                idf = math.log(1 + (n - df[g] + 0.5) / (df[g] + 0.5))
                s += idf * d[g] * (k1 + 1) / (d[g] + k1 * (1 - b + b * ln / avg))
        scores[i] = s
    return scores


def mode(cfg):
    """이번 실행에서 실제로 쓰는 검색: hybrid(의미 + 키워드) 또는 keyword."""
    vecs = load(config.index_unit(cfg))[1]
    return "hybrid" if cfg["use_embedding"] and vecs is not None and upstage.has_key() else "keyword"


def retrieve(question, cfg, calls=None, k=None):
    """상위 k개 조각(점수 높은 순). 점수가 같으면 조각 번호가 작은 쪽이 앞(어느 컴퓨터에서나 같은 순서)."""
    chunks, vecs, stale, docs, df, avg = load(config.index_unit(cfg))
    kw = bm25(question, docs, df, avg)
    kw_norm = kw / kw.max() if kw.max() > 0 else kw
    if mode(cfg) == "hybrid":
        if stale:
            raise RuntimeError("조각과 임베딩이 짝이 아닙니다. 키를 넣고 python3 -m engine.build_index로 다시 만드세요.")
        q = np.array(upstage.embed([question], cfg["embed_query"], calls)[0], dtype=np.float32)
        cos = vecs @ (q / np.linalg.norm(q))
        w = cfg["hybrid_cos_weight"]
        score = w * cos + (1 - w) * kw_norm
    else:
        cos, score = None, kw_norm
    idx = np.argsort(-score, kind="stable")
    if cfg["chunk_item_split"] or cfg["chunk_annex_rows"]:  # 호 · 행 조각은 라벨이 같아서 가장 높은 하나만 남긴다
        seen = set()
        idx = [i for i in idx if not (chunks[i]["label"] in seen or seen.add(chunks[i]["label"]))]
    idx = idx[:k or cfg["top_k"]]
    return [{**chunks[i], "score": float(score[i]), "kw": float(kw_norm[i]),
             "cos": float(cos[i]) if cos is not None else None} for i in idx]
