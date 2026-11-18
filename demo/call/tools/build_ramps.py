"""받은 오픈스트리트맵 서울 발췌본에서 자동차전용도로의 「나가는 길이 갈라지는 점」 · 「들어오는 길이 합쳐지는 점」을 줄인 표로 만든다(33번 3-3).
운전자는 나들목 이름을 몰라도 「방금 빠지는 길을 지났다」는 안다. 받은 파일은 읽기만 한다.

    python3 -I demo/call/tools/build_ramps.py <받은 폴더>      → data/seoul/ramps.tsv.gz (이름 \t 종류 \t 경도 \t 위도 \t 길 \t 가는 방향 x \t 가는 방향 y)

- 본선: highway=motorway · trunk 이고 이름이 자동차전용도로 노선인 한 방향 길(oneway). 연결로: highway=motorway_link · trunk_link.
- 연결로의 첫 점이 본선 위(8m 안)면 그 자리가 「나가는 길」, 끝 점이 본선 위면 「들어오는 길」. 가는 방향은 그 자리의 본선 방향.
- 이름: 1.2km 안의 가장 가까운 나들목 · 분기점 이름(지명 표) + 「 나가는 길」 · 「 들어오는 길」. 없으면 넣지 않는다.
- 같은 이름 · 같은 방향의 점이 60m 안에 또 있으면 하나만 둔다.
자료: © OpenStreetMap contributors, ODbL 1.0 (places.tsv와 같은 발췌본).
"""
import gzip
import json
import lzma
import math
import os
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ["CALL_RAMPS"] = "0"
import gaz  # noqa: E402

OUT = HERE / "data" / "seoul" / "ramps.tsv.gz"
MAIN = {"강변북로": "강변북로", "올림픽대로": "올림픽대로", "내부순환로": "내부순환로", "동부간선도로": "동부간선로", "동부간선로": "동부간선로",
        "북부간선도로": "북부간선도로", "서부간선도로": "서부간선로", "서부간선로": "서부간선로"}       # 오픈스트리트맵 이름 → 지명 표의 길 이름
IC = re.compile(r"(IC|JC|나들목|분기점)$")


def main():
    G = gaz.Gazetteer()
    ics = [i for i in range(len(G.name)) if G.kind[i] in ("나들목", "분기점") or IC.search(G.name[i])]
    icx, icy = G.x[ics], G.y[ics]
    mains, links = [], []
    with lzma.open(next(Path(sys.argv[1]).glob("*.geojson.xz")), "rt", encoding="utf-8") as r:
        for line in r:
            s = line.strip().rstrip(",")
            if not s.startswith('{"type":"Feature"') or '"highway"' not in s:
                continue
            d = json.loads(s)
            p, g = d.get("properties") or {}, d.get("geometry") or {}
            if g.get("type") != "LineString":
                continue
            hw = p.get("highway")
            if hw in ("motorway", "trunk") and p.get("name") in MAIN and p.get("oneway") == "yes":
                xs, ys = gaz.xy([q[0] for q in g["coordinates"]], [q[1] for q in g["coordinates"]])
                mains.append((MAIN[p["name"]], np.column_stack((xs, ys))))
            elif hw in ("motorway_link", "trunk_link"):
                xs, ys = gaz.xy([q[0] for q in g["coordinates"]], [q[1] for q in g["coordinates"]])
                links.append(np.column_stack((xs, ys)))
    segs = []                                          # (길, 시작 점, 끝 점)
    for road, pts in mains:
        segs += [(road, pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
    A = np.array([s[1] for s in segs]); B = np.array([s[2] for s in segs])
    D = B - A
    L2 = np.maximum((D ** 2).sum(1), 1e-9)

    def on_main(q):
        t = np.clip(((q - A) * D).sum(1) / L2, 0, 1)
        d = np.hypot(*(A + D * t[:, None] - q).T)
        k = int(d.argmin())
        return (k, d[k]) if d[k] <= 8 else (None, None)

    rows = []
    for ln in links:
        for end, word in ((ln[0], "나가는 길"), (ln[-1], "들어오는 길")):
            k, _ = on_main(end)
            if k is None:
                continue
            dd = np.hypot(icx - end[0], icy - end[1])
            j = int(dd.argmin())
            if dd[j] > 1200:
                continue
            h = D[k] / math.sqrt(L2[k])
            name = f"{G.name[ics[j]]} {word}"
            if any(r[0] == name and math.hypot(r[2] - end[0], r[3] - end[1]) < 60 and r[4] * h[0] + r[5] * h[1] > 0 for r in rows):
                continue
            rows.append((name, segs[k][0], float(end[0]), float(end[1]), float(h[0]), float(h[1])))
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        for name, road, x, y, hx, hy in rows:
            lo, la = gaz.lonlat(x, y)
            f.write(f"{name}\t진출입로\t{lo}\t{la}\t{road}\t{hx:.3f}\t{hy:.3f}\n")
    from collections import Counter
    print(f"점 {len(rows)}개 · 이름 {len({r[0] for r in rows})}개 → {OUT}")
    print(Counter(r[1] for r in rows).most_common())


if __name__ == "__main__":
    main()
