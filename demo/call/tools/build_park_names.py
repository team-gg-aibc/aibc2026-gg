"""받은 오픈스트리트맵 서울 발췌본에서 「공원 경계 안의 이름 붙은 것 가운데 지명 표에 없는 것」(호수 · 광장 · 잔디마당 · 숲 · 동물 마을 · 폭포 · 문 · 산책길)을
줄인 표로 만든다(33번 2-5). 「88호수 옆이에요」 · 「평화의광장이요」를 알아듣게 한다. 받은 파일은 읽기만 한다.

    python3 -I demo/call/tools/build_park_names.py <받은 폴더>      → data/seoul/park_names.tsv.gz (이름 \t 종류 \t 경도 \t 위도 \t 공원)

- 면(호수 · 광장 …)은 한 점이 아니라 테두리를 40m마다 점으로 둔다(물가가 아니면 안쪽도 60m 격자로). 「호수 옆」은 호수 한가운데가 아니라 물가 어디든이다.
  선(산책길 · 개울)은 50m마다. 한 이름에 점은 30개까지(넘으면 간격을 넓힌다).
- 빼는 것: 행정 경계 · 섬 · 철도 · 변전소 · 공사장 · 공원 자기 이름 · 찻길(차가 다니는 길 · 「○○로20길」 꼴) · 터널 · 한글이 없는 이름 · 괄호가 든 이름 · 세 글자보다 짧거나 열여섯 글자보다 긴 이름.
- 지명 표(places.tsv · 상가정보 · 나들목)의 같은 이름이 80m 안에 있으면 넣지 않는다.
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
os.environ["CALL_PARKNAMES"] = "0"                     # 견줄 것은 이 표를 넣기 전의 지명 표
import gaz  # noqa: E402

OUT = HERE / "data" / "seoul" / "park_names.tsv.gz"
ROADY = re.compile(r"(로|길)\d*[가-하]?길$|대로$|로$|^.*(지하차도|터널)$")


def kind_of(p, geom):
    """꼬리표 → 종류(넣지 않을 것은 None)."""
    if p.get("boundary") or p.get("place") == "island" or p.get("railway") or p.get("power") or p.get("public_transport") or p.get("leisure") == "park":
        return None
    if p.get("landuse") in ("construction", "railway") or p.get("tunnel") or p.get("proposed") or p.get("construction"):
        return None
    if p.get("natural") == "water" or p.get("water") or p.get("waterway") in ("stream", "river"):
        return "물가"
    if p.get("waterway") == "waterfall":
        return "폭포"
    if p.get("barrier") in ("gate", "entrance") or p.get("entrance"):
        return "문"
    if p.get("place") == "square" or p.get("landuse") == "grass" or p.get("natural") == "grassland":
        return "광장"
    if p.get("natural") == "wood" or p.get("landuse") == "forest":
        return "숲"
    if p.get("attraction") == "animal" or p.get("zoo"):
        return "동물사"
    if p.get("highway") in ("footway", "steps", "path", "cycleway", "pedestrian", "track") or (p.get("bridge") and p.get("highway") in ("footway", "cycleway")):
        return "산책길" if geom != "Point" else None
    if p.get("highway"):
        return None                                    # 차가 다니는 길은 길 선(roads.json)에 있다
    if p.get("attraction") or p.get("amenity") or p.get("tourism") or p.get("leisure") or p.get("historic") or p.get("man_made"):
        return "시설"
    if geom in ("Polygon", "MultiPolygon") and len(p) == 1:
        return "시설"                                  # 이름만 있는 면(「앵무마을」)
    return None


def rings(g):
    t, c = g["type"], g["coordinates"]
    return [c[0]] if t == "Polygon" else [poly[0] for poly in c] if t == "MultiPolygon" else []


def lines(g):
    t, c = g["type"], g["coordinates"]
    return [c] if t == "LineString" else c if t == "MultiLineString" else []


def along(xs, ys, step):
    """선을 따라 step m마다 점."""
    out = [(xs[0], ys[0])]
    left = step
    for (a, b), (c, d) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        seg = math.hypot(c - a, d - b)
        t = left
        while t <= seg:
            out.append((a + (c - a) * t / seg, b + (d - b) * t / seg))
            t += step
        left = t - seg
    return out


def in_poly(x, y, ring):
    c = False
    for (a, b), (cc, d) in zip(ring, ring[1:] + ring[:1]):
        if (b > y) != (d > y) and x < (cc - a) * (y - b) / (d - b) + a:
            c = not c
    return c


def samples(kind, g):
    """한 요소 → 점들(경위도가 아니라 지명 표의 x, y m)."""
    if g["type"] == "Point":
        return [tuple(float(v) for v in gaz.xy(*g["coordinates"]))]
    pts = []
    for r in rings(g):
        xs, ys = gaz.xy([q[0] for q in r], [q[1] for q in r])
        ring = list(zip(xs.tolist(), ys.tolist()))
        pts += along(xs.tolist(), ys.tolist(), 40.0)
        if kind != "물가":                             # 광장 · 잔디마당 · 숲에는 사람이 안에 선다
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            pts += [(x, y) for x in np.arange(x0 + 30, x1, 60.0) for y in np.arange(y0 + 30, y1, 60.0) if in_poly(x, y, ring)]
    if not rings(g):
        for ln in lines(g):
            xs, ys = gaz.xy([q[0] for q in ln], [q[1] for q in ln])
            pts += along(xs.tolist(), ys.tolist(), 50.0)
    return pts


def thin(pts, cap=30):
    """같은 이름의 점들을 30개 안으로(서로 가까운 것부터 덜어 낸다)."""
    step = 20.0
    while True:
        keep = []
        for p in pts:
            if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= step for q in keep):
                keep.append(p)
        if len(keep) <= cap:
            return keep
        step *= 1.3


def main():
    G = gaz.Gazetteer()
    parks = [(p["name"], [tuple(v) for v in p["ring"].tolist()]) for p in G.parks]
    boxes = [(n, r, min(a for a, _ in r), min(b for _, b in r), max(a for a, _ in r), max(b for _, b in r)) for n, r in parks]
    park_names = {gaz.norm(n) for n, _ in parks}
    got = {}                                            # (이름, 공원) → [종류, 점들]
    with lzma.open(next(Path(sys.argv[1]).glob("*.geojson.xz")), "rt", encoding="utf-8") as r:
        for line in r:
            s = line.strip().rstrip(",")
            if not s.startswith('{"type":"Feature"') or '"name"' not in s:
                continue
            d = json.loads(s)
            p, g = d.get("properties") or {}, d.get("geometry") or {}
            name = (p.get("name") or "").strip()
            if not g or not re.search(r"[가-힣]", name) or gaz.norm(name) in park_names or ROADY.search(name) or "(" in name or not 3 <= len(name) <= 16:     # 괄호 든 긴 이름은 사람이 부르는 이름이 아니다
                continue
            kind = kind_of(p, g["type"])
            if not kind:
                continue
            pts = samples(kind, g)
            if not pts:
                continue
            cx, cy = sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts)
            park = next((n for n, ring, x0, y0, x1, y1 in boxes if x0 <= cx <= x1 and y0 <= cy <= y1 and in_poly(cx, cy, ring)), None)
            if not park:
                continue
            k = (name, park)
            if k in got:
                got[k][1] += pts
            else:
                got[k] = [kind, pts]
    rows, skipped = [], 0
    for (name, park), (kind, pts) in sorted(got.items()):
        pts = thin(pts)
        cx, cy = sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts)
        n = gaz.norm(name)
        if any(gaz.norm(G.name[i]) == n for i in G.near(cx, cy, 80 + max(math.hypot(a - cx, b - cy) for a, b in pts))):
            skipped += 1
            continue
        rows += [(name, kind, *gaz.lonlat(a, b), park) for a, b in pts]
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write("\t".join(str(v) for v in row) + "\n")
    names = {(r[0], r[4]) for r in rows}
    print(f"이름 {len(names)}개 · 점 {len(rows)}개 → {OUT} (지명 표에 이미 있어 뺀 것 {skipped})")
    from collections import Counter
    print(Counter(r[1] for r in {(r[0], r[1], r[4]) for r in rows}).most_common())


if __name__ == "__main__":
    main()
