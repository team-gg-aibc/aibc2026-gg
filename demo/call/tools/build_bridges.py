"""다리 면 표(data/seoul/bridges.json.gz)를 만든다. 지명 표는 다리를 가운데 한 점으로 줄여 두어서, 「망원한강공원 자전거길, 양화대교 밑」의 다리가 강 한복판 한 점이 되어
공원과 겹치지 않는다(75번: 공원 말을 버리고 강 건너에 핀, 542m). 다리의 면(오픈스트리트맵 man_made=bridge)을 따로 적어 두고, 「○○대교 밑 · 앞」을 그 면 둘레로 읽는다.
받은 파일은 읽기만 한다(실행하지 않는다). 지명 표(places.tsv)는 고치지 않는다.

    python3 -I demo/call/tools/build_bridges.py <받은 오픈스트리트맵 폴더>      → data/seoul/bridges.json.gz  {"bridges": [{"name", "lon", "lat", "rings": [[경도·위도를 areas.json과 같은 정수 꼴로 …]]}]}

- 지명 표의 「다리」 줄과 이름이 같고, 그 줄의 점이 면에서 1.5km 안인 것만(같은 이름의 다른 다리와 섞이지 않게). lon · lat = 그 지명 표 줄의 값(글자 그대로, 줄을 찾는 열쇠).
- 긴 쪽이 MIN_M보다 짧은 다리는 적지 않는다(한 점으로 봐도 되는 크기). 꼭짓점은 5m보다 촘촘하면 솎는다.
자료: © OpenStreetMap contributors, ODbL 1.0.
"""
import gzip
import json
import lzma
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_gazetteer as B        # noqa: E402

OUT = HERE / "data" / "seoul"
KX, KY = 88200.0, 111000.0
MIN_M = 60.0


def thin(ring, step=5.0):
    keep = [ring[0]]
    for p in ring[1:]:
        if math.hypot((p[0] - keep[-1][0]) * KX, (p[1] - keep[-1][1]) * KY) >= step:
            keep.append(p)
    return keep


def main(src):
    rows = [ln.rstrip("\n").split("\t") for ln in gzip.open(OUT / "places.tsv.gz", "rt", encoding="utf-8")]
    spots = {}
    for r in rows:
        if r[1] == "다리":
            spots.setdefault(r[0], []).append((float(r[2]), float(r[3]), r[2], r[3]))
    got = {}
    with lzma.open(next(Path(src).expanduser().glob("*.geojson.xz")), "rt", encoding="utf-8") as f:
        for line in f:
            if '"man_made":"bridge"' not in line or '"name"' not in line:
                continue
            d = json.loads(line.strip().rstrip(","))
            g, name = d["geometry"], " ".join(((d.get("properties") or {}).get("name") or "").split())
            if g["type"] not in ("Polygon", "MultiPolygon") or name not in spots:
                continue
            for ring in B.rings_of(g):
                if len(ring) < 4:
                    continue
                xs, ys = [p[0] for p in ring], [p[1] for p in ring]
                if math.hypot((max(xs) - min(xs)) * KX, (max(ys) - min(ys)) * KY) < MIN_M:
                    continue
                d0, lo, la = min((min(math.hypot((x - s[0]) * KX, (y - s[1]) * KY) for x, y in ring), s[2], s[3]) for s in spots[name])
                if d0 <= 1500:
                    got.setdefault((name, lo, la), []).append([v for x, y in thin(ring) for v in (round((x - 126) * 1e5), round((y - 37) * 1e5))])
    out = [{"name": k[0], "lon": k[1], "lat": k[2], "rings": v} for k, v in sorted(got.items())]
    with gzip.open(OUT / "bridges.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"bridges": out}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"적은 다리 {len(out):,} · 면 {sum(len(b['rings']) for b in out):,} · 지명 표의 다리 이름 {len(spots):,}")


if __name__ == "__main__":
    main(sys.argv[1])
