"""넓은 장소의 크기 표(data/seoul/extents.tsv.gz)를 만든다. 지명 표는 면으로 그려진 장소(학교 · 시장 · 큰 건물)를 꼭짓점 평균 한 점으로 줄여 두어서,
「○○초등학교 바로 앞」의 범위(반지름 약 40m)에 담장 밖에 선 시민이 들지 않는다(58번 d-01). 그 한 점에서 가장 먼 가장자리까지의 거리를 따로 적어 둔다.
받은 파일은 읽기만 한다(실행하지 않는다). 지명 표(places.tsv)는 고치지 않는다.

    python3 -I demo/call/tools/build_extent.py <받은 오픈스트리트맵 폴더>      → data/seoul/extents.tsv.gz (이름 \t 종류 \t 경도 \t 위도 \t 먼 가장자리 m \t 가까운 가장자리 m)

- 면: 지명 표를 만든 그 파일(Seoul.osm.geojson.xz)의 이름 있는 면. 가운데 점은 build_gazetteer.py와 같은 셈(가장 긴 고리의 꼭짓점 평균)이라 지명 표의 줄과 글자까지 맞는다. 맞는 줄이 없는 면은 버린다.
- 역: 면이 아니라 점이지만 출구들이 100~200m에 퍼져 있다. 같은 지명 표의 「○○역 N번 출구」 가운데 가장 먼 것까지를 크기로 적는다(새 자료 없음).
- 종류는 KEEP(학교 · 시장 · 병원 · 마트 · 체육시설 · 터미널 · 관공서 · 문화시설 · 볼거리 · 경찰 · 소방서)와 역만. 공원은 경계가 areas.json에 따로 있고, 다리 · 터널은 길 위의 표지로 쓴다.
- 먼 가장자리가 MIN_M보다 가까운 것은 적지 않는다(한 점으로 봐도 되는 크기).
자료: © OpenStreetMap contributors, ODbL 1.0.
"""
import gzip
import json
import lzma
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_gazetteer as B        # noqa: E402

OUT = HERE / "data" / "seoul"
KX, KY = 88200.0, 111000.0
MIN_M = 30.0
KEEP = {"학교", "시장", "병원", "마트", "체육시설", "터미널", "관공서", "문화시설", "볼거리", "경찰", "소방서"}     # 사람들이 「○○ 앞」으로 대는 공공 표지 꼴의 넓은 곳(+ 역은 출구로 따로).
# 이름 있는 건물 · 아파트 동 · 주차장 · 사무실 · 종교시설 · 숙박은 뺀다: 크기가 커도(코엑스 222m) 주차장 · 아파트 동과 가를 표시가 자료에 없고,
# 600통에서 넓은 주차장(「올림픽공원 남2문주차장」 85m)을 넓게 읽자 틀리게 답한 시민의 말에 끌려 틀린 확정이 하나 났다(60번 4절)


def seg_d(ax, ay, bx, by):
    """원점에서 선분 a-b까지의 거리."""
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, (-ax * dx - ay * dy) / ((dx * dx + dy * dy) or 1)))
    return math.hypot(ax + t * dx, ay + t * dy)


def main(src):
    rows = [ln.rstrip("\n").split("\t") for ln in gzip.open(OUT / "places.tsv.gz", "rt", encoding="utf-8")]
    have = {(r[0], r[1], r[2], r[3]) for r in rows}
    out, miss = {}, Counter()
    with lzma.open(next(Path(src).expanduser().glob("*.geojson.xz")), "rt", encoding="utf-8") as f:
        for line in f:
            if '"name"' not in line or "Polygon" not in line:
                continue
            s = line.strip().rstrip(",")
            if not s.startswith('{"type":"Feature"'):
                continue
            d = json.loads(s)
            g, p = d["geometry"], d.get("properties") or {}
            if g["type"] not in ("Polygon", "MultiPolygon") or p.get("boundary") == "administrative":
                continue
            ring = max(B.rings_of(g), key=len)
            if len(ring) < 4:
                continue
            lon, lat = sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring)
            name, kind = " ".join((p.get("name") or "").split()), B.kind_of(p, g["type"])
            if kind not in KEEP or not name:
                continue
            pts = [((x - lon) * KX, (y - lat) * KY) for x, y in ring]
            far = max(math.hypot(x, y) for x, y in pts)
            if far < MIN_M:
                continue
            key = (name, kind, f"{lon:.6f}", f"{lat:.6f}")
            if key not in have:
                miss[kind] += 1                           # 서울 밖 · 같은 이름이 가까이 있어 지명 표에서 합쳐진 것
                continue
            near = min(seg_d(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))
            out[key] = (far, near)
    stations, far_exit = [r for r in rows if r[1] == "역"], {}
    for n, _, lo, la, *_ in (r for r in rows if r[1] == "역 출구"):      # 출구는 같은 이름의 역 가운데 가장 가까운 역의 것(「신촌역」은 700m 떨어진 두 역이다)
        same = [(math.hypot((float(s[2]) - float(lo)) * KX, (float(s[3]) - float(la)) * KY), i) for i, s in enumerate(stations) if n.startswith(s[0] + " ")]
        if same:
            d, i = min(same)
            far_exit.setdefault(i, []).append(d)
    for i, d in far_exit.items():
        if max(d) >= MIN_M:
            out[tuple(stations[i][:4])] = (max(d), min(d))
    with gzip.open(OUT / "extents.tsv.gz", "wt", encoding="utf-8") as f:
        f.write("".join("\t".join(k) + f"\t{far:.0f}\t{near:.0f}\n" for k, (far, near) in sorted(out.items())))
    kinds = Counter(k[1] for k in out)
    print(f"적은 줄 {len(out):,} · 종류별 {dict(kinds.most_common())}")
    print(f"지명 표에 맞는 줄이 없어 버린 면 {sum(miss.values()):,} · {dict(miss.most_common(8))}")
    for cut in (40, 60, 100):
        print(f"  먼 가장자리 {cut}m 넘음: {sum(1 for far, _ in out.values() if far > cut):,}")


if __name__ == "__main__":
    main(sys.argv[1])
