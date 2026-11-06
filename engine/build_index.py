"""색인 만들기: 조문을 조각(chunk)으로 나누고 임베딩한다(킷 그대로 옮김).

조각마다 「인용 라벨」을 붙여 두는 것이 핵심이다. 예) 서울특별시 주차장 설치 및 관리 조례 제7조 제3항
모델은 이 라벨을 고르기만 하고, 조항 표기를 직접 쓰지 않는다.

실행:  python3 -m engine.build_index                  (항 단위, 키가 있으면 임베딩까지)
       python3 -m engine.build_index --unit article   (조 단위)
결과:  engine/data/chunks_<단위>.json · vectors_<단위>.npy · index_<단위>.json(조각과 임베딩이 짝인지 보는 지문)
조각 글을 바꿨는데 키가 없으면 임베딩이 옛 조각 것으로 남는다. 그때 검색은 키워드만 돌고, 혼합 검색은 멈춘다.
"""
import argparse
import json

import numpy as np

from . import config, upstage
from .parse_annex import annex_path
from .retrieve import chunks_digest


def make_chunks(laws, unit, use_parsed_annex=True):
    chunks = []
    for law in laws:
        meta = {"law": law["name"], "effective_date": law["effective_date"], "source_url": law["source_url"]}
        for a in law["articles"]:
            head = f"{law['name']} {a['article']}({a['title']})"
            if unit == "article" or len(a["paragraphs"]) <= 1 or a["paragraphs"][0]["no"] is None:
                chunks.append({**meta, "label": f"{law['name']} {a['article']}",
                               "text": a["text"]})
                continue
            for p in a["paragraphs"]:
                chunks.append({**meta, "label": f"{law['name']} {a['article']} 제{p['no']}항",
                               "text": f"[{head}]\n{p['text']}"})
        for ax in law["annexes"]:
            if not ax["label"].startswith("별표"):
                continue
            parsed = annex_path(law["mst"], ax["label"])
            if use_parsed_annex and parsed.exists():
                body, src = parsed.read_text(encoding="utf-8"), "document-parse"
            else:
                body, src = ax["text"], "law.go.kr 원문(괘선 표)"
            # 긴 별표는 잘라서 넣되 라벨은 같게 둔다
            for i in range(0, max(len(body), 1), 1800):
                chunks.append({**meta, "label": f"{law['name']} {ax['label']}",
                               "text": f"[{law['name']} {ax['label']} {ax['title']}]\n{body[i:i + 1800]}",
                               "annex_source": src})
    for i, c in enumerate(chunks):
        c["id"] = i
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default=config.DEFAULTS["chunk_unit"], choices=["paragraph", "article"])
    ap.add_argument("--raw-annex", action="store_true", help="별표를 Document Parse 결과 대신 법제처 괘선 원문으로")
    a = ap.parse_args()

    laws = json.loads((config.DATA / "ordinances.json").read_text(encoding="utf-8"))
    chunks = make_chunks(laws, a.unit, use_parsed_annex=not a.raw_annex)
    (config.DATA / f"chunks_{a.unit}.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"조각 {len(chunks)}개 ({a.unit} 단위)")

    if not upstage.has_key():
        print("⚠ API 키가 없어 임베딩은 건너뜁니다. 조각 글이 바뀌었으면 혼합 검색이 멈추고 키워드 검색만 돕니다.")
        return
    vecs = upstage.embed([c["text"] for c in chunks], config.DEFAULTS["embed_passage"])
    np.save(config.DATA / f"vectors_{a.unit}.npy", np.array(vecs, dtype=np.float32))
    (config.DATA / f"index_{a.unit}.json").write_text(json.dumps(
        {"chunks_sha256": chunks_digest(chunks), "embed_model": config.DEFAULTS["embed_passage"], "chunks": len(chunks)},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("임베딩 저장 완료")


if __name__ == "__main__":
    main()
