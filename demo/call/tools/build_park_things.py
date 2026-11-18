"""받은 오픈스트리트맵 서울 발췌본에서 「공원 안의 이름 없는 시설」(화장실 · 놀이터 · 정자 · 운동기구 · 음수대 · 분수 · 전망대 · 운동장)을 종류만 남긴 표로 만든다.
공원 안은 이름 붙은 표지가 드물어 「근처에 정자가 보이세요?」처럼 종류로 묻는 데 쓴다. 받은 파일은 읽기만 한다.

    python3 -I demo/call/tools/build_park_things.py <받은 폴더>      → data/seoul/park_things.tsv.gz (종류 \t 경도 \t 위도)
자료: © OpenStreetMap contributors, ODbL 1.0 (places.tsv와 같은 발췌본).
"""
import gzip
import json
import lzma
import sys
from pathlib import Path

import numpy as np

WANT = [("amenity", "toilets", "화장실"), ("leisure", "playground", "놀이터"), ("amenity", "shelter", "정자"), ("leisure", "fitness_station", "운동기구"),
        ("amenity", "drinking_water", "음수대"), ("amenity", "fountain", "분수"), ("tourism", "viewpoint", "전망대"), ("leisure", "pitch", "운동장")]
OUT = Path(__file__).resolve().parents[1] / "data" / "seoul"


def in_ring(lon, lat, ring):
    r = np.asarray(ring)
    inside = np.zeros(len(lon), bool)
    for (a, b), (c, d) in zip(r[:-1], r[1:]):
        if b != d:
            inside ^= ((b > lat) != (d > lat)) & (lon < (c - a) * (lat - b) / (d - b) + a)
    return inside


pts = []
with lzma.open(next(Path(sys.argv[1]).glob("*.geojson.xz")), "rt", encoding="utf-8") as r:
    for line in r:
        s = line.strip().rstrip(",")
        if not s.startswith('{"type":"Feature"') or not any(f'"{v}"' in s for _, v, _ in WANT):
            continue
        d = json.loads(s)
        p, g = d.get("properties") or {}, d["geometry"]
        if p.get("name"):
            continue                                   # 이름이 있는 것은 이미 지명 표(places.tsv)에 있다
        kind = next((lab for k, v, lab in WANT if p.get(k) == v), None)
        if not kind:
            continue
        if g["type"] == "Point":
            lon, lat = g["coordinates"]
        elif g["type"] == "Polygon":
            ring = g["coordinates"][0]
            lon, lat = sum(a for a, _ in ring) / len(ring), sum(b for _, b in ring) / len(ring)
        else:
            continue
        pts.append((kind, lon, lat))
areas = json.loads(gzip.open(OUT / "areas.json.gz", "rt", encoding="utf-8").read() if not (OUT / "areas.json").exists() else (OUT / "areas.json").read_text(encoding="utf-8"))
lon, lat = np.array([p[1] for p in pts]), np.array([p[2] for p in pts])
keep = np.zeros(len(pts), bool)
for pk in areas["parks"]:
    ring = np.asarray(pk["ring"], float).reshape(-1, 2) / 1e5 + (126, 37)
    box = (lon >= ring[:, 0].min()) & (lon <= ring[:, 0].max()) & (lat >= ring[:, 1].min()) & (lat <= ring[:, 1].max()) & ~keep
    if box.any():
        keep[np.flatnonzero(box)[in_ring(lon[box], lat[box], ring)]] = True
rows = sorted(f"{k}\t{a:.6f}\t{b:.6f}" for (k, a, b), m in zip(pts, keep) if m)
with gzip.open(OUT / "park_things.tsv.gz", "wt", encoding="utf-8") as f:
    f.write("\n".join(rows) + "\n")
by = {}
for r_ in rows:
    by[r_.split("\t")[0]] = by.get(r_.split("\t")[0], 0) + 1
print(f"공원 안의 이름 없는 시설 {len(rows):,}곳 {by} (전체 후보 {len(pts):,}) → {OUT / 'park_things.tsv.gz'}")
