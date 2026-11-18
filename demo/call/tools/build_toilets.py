"""받은 「서울시 공중화장실 위치정보」 CSV에서 공원 경계 안의 화장실만 골라, 공원 안 시설 표와 같은 꼴(종류 \t 경도 \t 위도)로 만든다.
「근처에 화장실이 보이세요?」를 오픈스트리트맵에 화장실이 적은 공원(보라매공원 · 올림픽공원 · 하늘공원 …)에서도 쓰게 한다. 받은 파일은 읽기만 한다.

    python3 -I demo/call/tools/build_toilets.py <받은 CSV>      → data/seoul/park_toilets.tsv.gz (화장실 \t 경도 \t 위도)

- 자료: 서울 열린데이터광장 「서울시 공중화장실 위치정보」(OA-22586), 공공누리 제1유형(출처 표시). EUC-KR(cp949), 좌표 칸 「x 좌표」(경도) · 「y 좌표」(위도).
- 넣는 것: 지명 표의 공원 경계(615곳) 안에 드는 것. 이미 있는 화장실(오픈스트리트맵)에서 30m 안이면 같은 것으로 보고 넣지 않는다.
- 좌표와 종류만 남긴다(건물명 · 주소 · 전화번호는 넣지 않는다).
"""
import csv
import gzip
import io
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ["CALL_TOILETS"] = "0"
import gaz  # noqa: E402

OUT = HERE / "data" / "seoul" / "park_toilets.tsv.gz"


def in_ring(x, y, ring):
    inside = np.zeros(len(x), bool)
    for (a, b), (c, d) in zip(ring[:-1], ring[1:]):
        if b != d:
            inside ^= ((b > y) != (d > y)) & (x < (c - a) * (y - b) / (d - b) + a)
    return inside


def main():
    G = gaz.Gazetteer()
    raw = Path(sys.argv[1]).read_bytes()
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("cp949")
    rows = [r for r in csv.DictReader(io.StringIO(text)) if (r.get("x 좌표") or "").strip() and (r.get("y 좌표") or "").strip()]
    lon = np.array([float(r["x 좌표"]) for r in rows]); lat = np.array([float(r["y 좌표"]) for r in rows])
    x, y = gaz.xy(lon, lat)
    inpark = np.zeros(len(rows), bool)
    for p in G.parks:
        ring = np.vstack([p["ring"], p["ring"][:1]])
        inpark |= in_ring(x, y, ring)
    have = np.array([i for i in range(len(G.name)) if G.kind[i] == "화장실"])
    dup = np.array([bool(len(have)) and float(np.hypot(G.x[have] - a, G.y[have] - b).min()) <= 30 for a, b in zip(x, y)])
    keep = inpark & ~dup
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        for lo, la in zip(lon[keep], lat[keep]):
            f.write(f"화장실\t{lo:.6f}\t{la:.6f}\n")
    print(f"전체 {len(rows)} · 공원 안 {int(inpark.sum())} · 이미 있는 것과 겹침 {int((inpark & dup).sum())} → 넣음 {int(keep.sum())} → {OUT}")


if __name__ == "__main__":
    main()
