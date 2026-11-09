"""조례 통째로 읽기 (#27): 검색 후보 대신 질문의 조례 원문 전체를 근거 목록으로 보여 준다.

- 조례 고르기: 검색 후보(top_k)의 점수를 조례별로 더해 가장 큰 조례. 2위 조례의 합이 1위의 `whole_second_ratio` 배 이상이면
  두 조례를 함께 넣는다(`whole_max_laws`까지). 1위 조각 하나로 고르면 후보 6개 중 5개가 주차장인데 1위가 도시공원이라
  도시공원을 고른 일이 있었다(킷 예시 「장애인 · 다둥이 할인」, 11-09).
- 조각은 원문 순서(조각 id 순)로 놓는다. 모델은 지금처럼 「[근거 i]」 번호만 고르고, 인용 · 링크 · 시행일은 코드가 라벨에서 붙인다.
- 원문이 프롬프트 앞, 질문이 맨 뒤라 같은 조례를 묻는 질문끼리 입력 앞부분이 같다(입력 캐시가 맞는지 보려고).
- 기본 흐름은 건드리지 않는다. 스위치 `whole_ordinance`가 꺼져 있으면(기본) 이 파일은 쓰이지 않는다.
"""
from . import retrieve


def pick_laws(hits, cfg):
    """검색 후보에서 넣을 조례 이름들(점수 높은 순)."""
    best = {}
    for h in hits:
        best[h["law"]] = best.get(h["law"], 0.0) + h["score"]
    ranked = sorted(best, key=lambda k: -best[k])
    if not ranked:
        return []
    top = best[ranked[0]]
    laws = [ranked[0]]
    for k in ranked[1:cfg["whole_max_laws"]]:
        if top > 0 and best[k] >= cfg["whole_second_ratio"] * top:
            laws.append(k)
    return laws


def expand(hits, cfg):
    """검색 후보 → 고른 조례의 조각 전체(원문 순서). 검색 점수 칸은 후보에 있던 조각만 남기고 나머지는 None."""
    chunks = retrieve.load(cfg["chunk_unit"])[0]
    laws = pick_laws(hits, cfg)
    seen = {h["id"]: h for h in hits}
    out = []
    for law in laws:
        for c in chunks:
            if c["law"] == law:
                h = seen.get(c["id"])
                out.append({**c, "score": h["score"] if h else None, "kw": h["kw"] if h else None,
                            "cos": h["cos"] if h else None})
    return out
