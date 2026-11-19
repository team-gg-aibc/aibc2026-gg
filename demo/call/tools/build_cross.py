"""표준노드링크에서 서울 일반 도로의 교차로 이름을 줄인 표(data/seoul/cross_nodes.tsv.gz)로 만든다(60번, 58번 표 2의 3번).
차로 지나간 시민이 댈 수 있는 것은 간판이 아니라 교차로 이름인데, 오픈스트리트맵 지명 표에는 교차로가 729곳뿐이다. 받은 zip은 읽기만 한다(풀지 않는다).

    python3 -I demo/call/tools/build_cross.py <받은 zip> [살펴본 것을 적을 json]     → data/seoul/cross_nodes.tsv.gz (이름 \t 종류 \t 경도 \t 위도 \t 묶은 노드 수 \t 노드가 퍼진 m)

자료: 국가교통정보센터 「표준노드링크」 [2026-11-11]판(MOCT_NODE). build_nodelink.py가 자동차전용도로에 쓰는 그 파일이다(새로 받지 않음).
- 이름: 「사거리 · 삼거리 · 오거리 · 네거리 · 교차로 · 로터리」로 끝나는 노드 이름. 서울 25개 구 경계 안의 노드만.
- 빼는 것(엉뚱한 곳을 가리키지 않게):
  · 지명 표(가게 포함)에 같은 이름이 이미 있는 것 — 넣지 않고, 그 자리와 노드 자리가 얼마나 다른지만 잰다(노드 좌표를 믿어도 되는지 보는 대조).
  · 같은 이름의 노드가 300m 넘게 떨어진 두 곳 이상에 있는 것(「시장사거리」가 여러 구에 있다): 어느 곳인지 몰라 뺀다.
  · 이름 꼴이 아닌 것: 앞말이 한 글자 이하 · 숫자 · 번지 · 「교차로」만 있는 것, 가상 시민 · 화면이 못 쓰는 꼴(괄호, 16자 넘음).
  · 소리가 같은 다른 이름이 지명 표에 있는 것(받아 적은 글로 못 가른다): 넣으면 「어느 구의 ○○인가요」를 한 번 더 묻게 된다 — 빼지 않고 수만 적는다.
  · 「○○앞교차로 · ○○입구교차로」의 ○○가 지명 표에 한두 곳뿐인 이름인데 그 자리에서 400m 넘게 떨어진 것(이름과 자리가 안 맞는다).
- 자리: 같은 이름의 노드(큰 교차로의 네 귀퉁이)를 가운데 한 점으로 묶는다.
- 한계: 노드 이름이 현장의 교차로 표지판 · 내비게이션이 부르는 이름과 같은지는 이 자료로 알 수 없다(「○○앞교차로」는 관리용 이름일 수 있다).
"""
import gzip
import json
import math
import os
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["CALL_CROSS"] = "0"                     # 견줄 것은 교차로 이름을 넣기 전의 지명 표
import gaz                    # noqa: E402
import build_nodelink as N    # noqa: E402

OUT = HERE / "data" / "seoul"
TAIL = re.compile(r"(사거리|삼거리|오거리|네거리|교차로|로터리)$")
SPREAD_M = 300.0
HEAD_M = 400.0       # 「○○앞교차로」가 지명 표의 ○○에서 이보다 멀면 넣지 않는다
LONG = {"다리", "터널", "나들목", "동네", "산", "공원", "역"}      # 길거나 넓어서 한 점과 견줄 수 없는 종류(「마포대교앞교차로」는 다리 가운데 점에서 700m)


def main(src, note=None):
    t0 = time.time()
    z = zipfile.ZipFile(src)
    files = {(i.filename if i.flag_bits & 0x800 else i.filename.encode("cp437").decode("cp949", "replace")): i for i in z.infolist()}
    prj = z.read(files["MOCT_NODE.prj"]).decode()
    assert "Central_Belt" in prj and "200000" in prj and "600000" in prj and "127.0" in prj and "38.0" in prj, prj      # 좌표계가 바뀌면 멈춘다
    cand = []
    for (x, y), d in zip(N.points(z, files["MOCT_NODE.shp"]), N.dbf(z, files["MOCT_NODE.dbf"])):
        nm = re.sub(r"\s+", "", d["NODE_NAME"])
        if 176000 < x < 222000 and 530000 < y < 572000 and TAIL.search(nm):
            cand.append((nm, x, y))
    G = gaz.Gazetteer()
    lon, lat = N.tm_to_lonlat(np.array([c[1] for c in cand]), np.array([c[2] for c in cand]))
    px, py = gaz.xy(lon, lat)
    inside = np.zeros(len(cand), bool)
    for g in G.gu:
        x0, y0, x1, y1 = g["box"]
        m = (px >= x0) & (px <= x1) & (py >= y0) & (py <= y1) & ~inside
        if m.any():
            r = g["ring"]
            ins = np.zeros(int(m.sum()), bool)
            for (ax, ay), (bx, by) in zip(r[:-1], r[1:]):
                if ay != by:
                    ins ^= ((ay > py[m]) != (by > py[m])) & (px[m] < (bx - ax) * (py[m] - ay) / (by - ay) + ax)
            inside[m] = ins
    groups, raw = defaultdict(list), defaultdict(set)      # 다듬은 이름으로 묶는다(「목동2,3단지교차로」 = 「목동2.3단지교차로」)
    for (nm, _, _), a, b, ok in zip(cand, px, py, inside):
        if ok:
            groups[gaz.norm(nm)].append((float(a), float(b)))
            raw[gaz.norm(nm)].add(nm)
    rows, why, drop, gap, alike, head_gap = [], Counter(), defaultdict(list), [], [], []
    for key, pts in sorted(groups.items()):
        nm = sorted(raw[key], key=lambda n: (len(n), n))[0]
        a = np.array(pts)
        cx, cy = float(a[:, 0].mean()), float(a[:, 1].mean())
        spread = float(max(math.hypot(p[0] - q[0], p[1] - q[1]) for p in pts for q in pts))
        head = TAIL.sub("", nm)
        if len(head) < 2 or re.search(r"^\d|\d+-\d+", head) or "(" in nm or not 3 <= len(nm) <= 16:
            why["이름 꼴이 아님"] += 1
            drop["이름 꼴이 아님"].append(nm)
            continue
        if key in G.ix:
            refs = [r for r in G.ix[key] if r[0] == "p"]
            if refs:
                j = min((i for _, i in refs), key=lambda i: math.hypot(G.x[i] - cx, G.y[i] - cy))
                gap.append((round(math.hypot(G.x[j] - cx, G.y[j] - cy)), nm, G.kind[j]))
            why["지명 표에 이미 있음"] += 1
            continue
        if spread > SPREAD_M:
            why["같은 이름이 멀리 여러 곳"] += 1
            drop["같은 이름이 멀리 여러 곳"].append(f"{nm}({len(pts)}점 · {spread:.0f}m)")
            continue
        base = gaz.norm(re.sub(r"(앞|입구)$", "", head))          # 「○○앞교차로」의 ○○가 지명 표에 한두 곳뿐인 이름이면 그 자리와 견준다(이름과 자리가 맞나)
        refs = [i for k, i in G.ix.get(base, ()) if k == "p"] if len(base) >= 3 else []
        if 1 <= len(refs) <= 3 and not any(k != "p" for k, _ in G.ix[base]) and not any(G.kind[i] in LONG for i in refs):
            d = min(math.hypot(G.x[i] - cx, G.y[i] - cy) for i in refs)
            head_gap.append((round(d), nm))
            if d > HEAD_M:
                why["이름 속 장소와 자리가 안 맞음"] += 1
                drop["이름 속 장소와 자리가 안 맞음"].append(f"{nm}({d:.0f}m)")
                continue
        if G.alike(key):
            alike.append(f"{nm} ↔ {' · '.join(G.display(k) for k in G.alike(key))}")
        lo, la = gaz.lonlat(cx, cy)
        rows.append(f"{nm}\t교차로\t{lo:.6f}\t{la:.6f}\t{len(pts)}\t{spread:.0f}")
    ears = defaultdict(list)
    for r in rows:
        ears[gaz.ear(gaz.norm(r.split("\t")[0]))].append(r.split("\t")[0])
    alike += [" ↔ ".join(v) for v in ears.values() if len(v) > 1]      # 새 이름끼리 소리가 같은 것
    with gzip.open(OUT / "cross_nodes.tsv.gz", "wt", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    gap.sort(), head_gap.sort()
    g, hg, sp = [d for d, _, _ in gap], [d for d, _ in head_gap], sorted(int(r.split("\t")[5]) for r in rows)
    q = lambda p, g=g: g[min(len(g) - 1, int(p * len(g)))] if g else None     # noqa: E731
    names = [r.split("\t")[0] for r in rows]
    inner = sorted({f"{n} ⊃ {G.display(k)}" for n in names for ln in range(len(gaz.norm(n)) - 1, 2, -1) for s in range(len(gaz.norm(n)) - ln + 1)
                    for k in [gaz.norm(n)[s:s + ln]] if k in G.ix and not G.shop_only(G.ix[k]) and G.ref_kind(G.ix[k][0]) in gaz.HIGH})     # 새 이름 속에 든, 이미 있는 눈에 띄는 이름(가장 긴 이름부터 찾으므로 새 이름이 이긴다)
    out = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"), "source": "국가교통정보센터 표준노드링크 [2026-11-11] (MOCT_NODE)", "zip": Path(src).name,
           "seoul_names": len(groups), "rows": len(rows), "dropped": dict(why), "already_gap_m": {"n": len(g), "median": q(.5), "p90": q(.9), "over_150": sum(1 for d in g if d > 150)},
           "head_gap_m": {"n": len(hg), "median": q(.5, hg), "p90": q(.9, hg), "over_400": sum(1 for d in hg if d > HEAD_M)}, "spread_m": {"median": q(.5, sp), "p90": q(.9, sp), "over_150": sum(1 for d in sp if d > 150)},
           "alike": alike, "tails": dict(Counter(TAIL.search(n).group() for n in names))}
    print(json.dumps(out, ensure_ascii=False), f"{time.time() - t0:.0f}초")
    if note:
        Path(note).write_text(json.dumps(dict(out, names=names, drop={k: v for k, v in drop.items()}, already_far=[x for x in gap if x[0] > 150], inside_names=inner),
                                         ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
