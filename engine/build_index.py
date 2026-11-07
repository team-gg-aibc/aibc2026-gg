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
import re

import numpy as np

from . import config, upstage
from .parse_annex import annex_path
from .retrieve import chunks_digest

# ---- #23 조각 다듬기 ----
# 조문 끝 꼬리표: 줄 끝의 <개정 …> · <신설 …>, 그리고 줄 전체가 [본조신설 …] · [전문개정 …] · [종전 제N조는 …] 같은 줄
TAG_INLINE = re.compile(r"[ \t]*<(?:개정|신설)\s[^>\n]*>")
TAG_LINE = re.compile(r"^\[(?:본조신설|전문개정|제목개정|종전|제\d+조[^\n\]]*이동|조례 제\d+호)[^\n]*\]$\n?", re.M)
DELETED = re.compile(r"^\s*[①-⑳]?\s*삭제(?:\s*<[^>\n]*>)?\s*$")  # 본문이 「삭제」뿐인 항
ITEM = re.compile(r"^\s*\d+\.\s")
ITEM_MIN = 5  # ponytail: 호 5개 이상인 항만 호 조각을 더한다. 문턱이 맞는지는 적중률로 보고 조정


def strip_tags(text):
    """(꼬리표를 뗀 글, 뗀 꼬리표 목록). 꼬리표 밖 글자는 그대로다."""
    tags = [m.group().strip() for m in TAG_INLINE.finditer(text)] + [m.group().strip() for m in TAG_LINE.finditer(text)]
    return TAG_LINE.sub("", TAG_INLINE.sub("", text)).rstrip("\n"), tags


def is_deleted(text):
    return bool(DELETED.match(text.split("\n", 1)[-1])) if text.startswith("[") else bool(DELETED.match(text))


def split_items(text):
    """항 글을 (앞 문장, [호 글…])로 나눈다. 호가 ITEM_MIN개 미만이면 호 목록을 비워 돌려준다."""
    lead, items = [], []
    for line in text.split("\n"):
        if ITEM.match(line):
            items.append([line])
        elif items:
            items[-1].append(line)  # 목(가 · 나) 줄은 앞 호에 붙인다
        else:
            lead.append(line)
    return "\n".join(lead), ["\n".join(i) for i in items] if len(items) >= ITEM_MIN else []


def table_rows(body):
    """별표 글을 (표 아닌 글, [(머리글, 행)…])로 나눈다. 머리글은 표 첫 줄과 구분선."""
    other, rows, i, lines = [], [], 0, body.split("\n")
    while i < len(lines):
        if not lines[i].startswith("|"):
            other.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].startswith("|"):
            j += 1
        head = lines[i:i + 2] if i + 1 < j and lines[i + 1].startswith("| ---") else lines[i:i + 1]
        rows += [("\n".join(head), r) for r in lines[i + len(head):j]]
        i = j
    return "\n".join(other), rows


def make_chunks(laws, unit, use_parsed_annex=True, strip=False, article_head=False, item_split=False, annex_rows=False):
    """스위치(strip · article_head · item_split · annex_rows)를 모두 끄면 출발 판과 같은 조각이 나온다."""
    chunks = []

    def add(meta, label, text, **extra):
        tags = []
        if strip:
            text, tags = strip_tags(text)
            if is_deleted(text):
                return
        chunks.append({**meta, "label": label, "text": text, **({"tags": tags} if strip else {}), **extra})

    def add_items(meta, label, head, text):
        lead, items = split_items(text)
        for it in items if item_split else []:
            add(meta, label, f"[{head}]\n{lead}\n{it}" if lead.strip() else f"[{head}]\n{it}")

    for law in laws:
        meta = {"law": law["name"], "effective_date": law["effective_date"], "source_url": law["source_url"]}
        for a in law["articles"]:
            head = f"{law['name']} {a['article']}({a['title']})"
            if unit == "article" or len(a["paragraphs"]) <= 1 or a["paragraphs"][0]["no"] is None:
                label, body = f"{law['name']} {a['article']}", a["text"]
                if article_head and a["paragraphs"]:
                    body = f"[{head}]\n{a['paragraphs'][0]['text']}"
                add(meta, label, body)
                if unit != "article" and a["paragraphs"]:
                    add_items(meta, label, head, a["paragraphs"][0]["text"])
                continue
            for p in a["paragraphs"]:
                label = f"{law['name']} {a['article']} 제{p['no']}항"
                add(meta, label, f"[{head}]\n{p['text']}")
                add_items(meta, label, head, p["text"])
        for ax in law["annexes"]:
            if not ax["label"].startswith("별표"):
                continue
            parsed = annex_path(law["mst"], ax["label"])
            if use_parsed_annex and parsed.exists():
                body, src = parsed.read_text(encoding="utf-8"), "document-parse"
            else:
                body, src = ax["text"], "law.go.kr 원문(괘선 표)"
            label, title = f"{law['name']} {ax['label']}", f"[{law['name']} {ax['label']} {ax['title']}]"
            rows = []
            if annex_rows:
                body, rows = table_rows(body)
            # 긴 별표는 잘라서 넣되 라벨은 같게 둔다
            for i in range(0, max(len(body), 1), 1800):
                add(meta, label, f"{title}\n{body[i:i + 1800]}", annex_source=src)
            for hd, row in rows:  # 표 행마다 머리글을 되풀이한다
                add(meta, label, f"{title}\n{hd}\n{row}", annex_source=src)
    for i, c in enumerate(chunks):
        c["id"] = i
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default=config.DEFAULTS["chunk_unit"], choices=["paragraph", "article"])
    for flag, key in (("--strip-tags", "chunk_strip_tags"), ("--article-head", "chunk_article_head"),
                      ("--item-split", "chunk_item_split"), ("--annex-rows", "chunk_annex_rows")):
        ap.add_argument(flag, dest=key, action="store_true", help=f"설정의 {key} 스위치를 켠 색인")
    ap.add_argument("--no-embed", action="store_true", help="임베딩은 만들지 않고 조각 파일만(키워드 검색만 잴 때, 크레딧 0)")
    ap.add_argument("--raw-annex", action="store_true", help="별표를 Document Parse 결과 대신 법제처 괘선 원문으로")
    a = ap.parse_args()

    laws = json.loads((config.DATA / "ordinances.json").read_text(encoding="utf-8"))
    sw = {k: getattr(a, k) for k in config.SWITCH_UNITS}
    unit = config.index_unit({"chunk_unit": a.unit, **sw})
    chunks = make_chunks(laws, a.unit, use_parsed_annex=not a.raw_annex, strip=sw["chunk_strip_tags"],
                         article_head=sw["chunk_article_head"], item_split=sw["chunk_item_split"],
                         annex_rows=sw["chunk_annex_rows"])
    (config.DATA / f"chunks_{unit}.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"조각 {len(chunks)}개 ({unit})")

    if a.no_embed or not upstage.has_key():
        print("⚠ API 키가 없어 임베딩은 건너뜁니다. 조각 글이 바뀌었으면 혼합 검색이 멈추고 키워드 검색만 돕니다.")
        return
    vecs = upstage.embed([c["text"] for c in chunks], config.DEFAULTS["embed_passage"])
    np.save(config.DATA / f"vectors_{unit}.npy", np.array(vecs, dtype=np.float32))
    (config.DATA / f"index_{unit}.json").write_text(json.dumps(
        {"chunks_sha256": chunks_digest(chunks), "embed_model": config.DEFAULTS["embed_passage"], "chunks": len(chunks)},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("임베딩 저장 완료")


if __name__ == "__main__":
    main()
