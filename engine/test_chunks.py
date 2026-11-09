"""#23 조각 다듬기 단위 시험. 실행: python -m engine.test_chunks (키 · 크레딧 필요 없음)

1. 스위치를 모두 끄면 커밋된 출발 판 조각(chunks_paragraph.json)과 한 글자도 다르지 않다
2. 꼬리표를 뗀 조각: 꼬리표 0건, 꼬리표 밖 본문 글자 차이 0, 본문이 「삭제」뿐인 조각 0개(주차장 제25조 제4항 등 4개가 빠짐)
3. 호 · 별표 행 조각은 항 · 별표 라벨을 그대로 쓴다
4. chunk_whole_item을 켜면 호 조각이 이겨도 그 항 전체 글이 넘어간다(순서는 그대로)
"""
import json
import re

from . import config
from .build_index import TAG_INLINE, TAG_LINE, is_deleted, make_chunks, strip_tags


def squash(s):
    return re.sub(r"\s+", "", s)


def main():
    laws = json.loads((config.DATA / "ordinances.json").read_text(encoding="utf-8"))
    base = json.loads((config.DATA / "chunks_paragraph.json").read_text(encoding="utf-8"))
    off = make_chunks(laws, "paragraph")
    assert off == base, "스위치를 모두 껐는데 출발 판 조각과 다르다"

    on = make_chunks(laws, "paragraph", strip=True)
    assert not [c for c in on if TAG_INLINE.search(c["text"]) or TAG_LINE.search(c["text"])], "꼬리표가 남았다"
    assert not [c for c in on if is_deleted(c["text"])], "삭제된 항 조각이 남았다"
    kept = [c for c in off if not is_deleted(strip_tags(c["text"])[0])]
    assert len(kept) == len(on) and len(off) - len(on) == 4, (len(off), len(on))
    for o, n in zip(kept, on):
        text = o["text"]
        for t in n["tags"]:
            text = text.replace(t, "", 1)
        assert squash(text) == squash(n["text"]), f"꼬리표 밖 본문이 바뀜: {n['label']}"

    labels = {c["label"] for c in off}
    for kw in ({"item_split": True}, {"annex_rows": True}, {"article_head": True}):
        v = make_chunks(laws, "paragraph", **kw)
        assert {c["label"] for c in v} == labels, f"{kw}: 라벨이 달라졌다"
    assert len(make_chunks(laws, "paragraph", item_split=True)) > len(off)
    assert len(make_chunks(laws, "paragraph", annex_rows=True)) > len(off)

    # 4. chunk_whole_item: 호 조각이 이겨도 항 전체 글이 넘어간다(키워드 검색, 호 조각만 있는 말로 물어서)
    from . import retrieve
    cfg = {**config.DEFAULTS, "use_embedding": False, "chunk_item_split": True, "chunk_whole_item": True, "top_k": 6}
    unit = config.index_unit(cfg)
    chunks = retrieve.load(unit)[0]
    first = {}
    for c in chunks:
        first.setdefault(c["label"], c)
    piece = next(c for c in chunks if c["text"] != first[c["label"]]["text"] and "annex_source" not in c)
    q = piece["text"].splitlines()[-1]
    hit = [r for r in retrieve.retrieve(q, cfg) if r["label"] == piece["label"]]
    assert hit and hit[0]["text"] == first[piece["label"]]["text"], "호 조각이 이겼는데 항 전체 글이 아니다"
    off = retrieve.retrieve(q, {**cfg, "chunk_whole_item": False})
    assert [r["label"] for r in off] == [r["label"] for r in retrieve.retrieve(q, cfg)], "순서가 바뀌었다"
    print("✅ 조각 시험 통과 (끈 판 = 출발 판 · 꼬리표 0 · 본문 차이 0 · 삭제 조각 0 · 라벨 그대로)")


if __name__ == "__main__":
    main()
