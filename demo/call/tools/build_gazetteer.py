"""받은 오픈스트리트맵 서울 발췌본에서 「줄인 지명 표」를 만든다. 받은 파일은 읽기만 한다(실행하지 않는다).

    python3 -I demo/call/tools/build_gazetteer.py <받은 폴더> [만들 폴더, 기본 demo/call/data/seoul]

만드는 것 (이름 · 종류 · 좌표만 남긴다):
  places.tsv   이름 \t 종류 \t 경도 \t 위도 \t 브랜드 \t 번호      역 · 역 출구 · 정류장 · 다리 · 교차로 · 건물 · 가게(간판) · 시설 · 동네 이름 …
  roads.json   이름이 있는 길: 이름 · 등급 · 선(같은 이름이라도 떨어져 있으면 다른 길로 가른다)
  areas.json   공원 · 자치구 · 동의 경계(점을 줄인 다각형)
  meta.json    만든 때 · 받은 자료의 날짜 · 종류별 개수
자료: © OpenStreetMap contributors, ODbL 1.0. 서울특별시 경계 안의 것만 남긴다.
"""
import json
import lzma
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

BBOX = (126.76, 37.41, 127.19, 37.71)          # 서울 둘레 상자(먼저 거르는 데만 쓴다)
ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "unclassified", "living_street", "pedestrian",
                "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link", "cycleway", "footway", "path", "service", "road"}
AMENITY = {"school": "학교", "kindergarten": "학교", "university": "학교", "college": "학교", "hospital": "병원", "clinic": "병원", "doctors": "병원",
           "dentist": "병원", "pharmacy": "약국", "bank": "은행", "fuel": "주유소", "parking": "주차장", "toilets": "화장실", "place_of_worship": "종교시설",
           "police": "경찰", "fire_station": "소방서", "townhall": "관공서", "public_building": "관공서", "community_centre": "관공서", "post_office": "관공서",
           "library": "관공서", "cafe": "카페", "restaurant": "음식점", "fast_food": "음식점", "bar": "음식점", "pub": "음식점", "food_court": "음식점",
           "cinema": "문화시설", "theatre": "문화시설", "arts_centre": "문화시설", "marketplace": "시장", "bus_station": "터미널", "ferry_terminal": "선착장"}
SHOP = {"convenience": "편의점", "supermarket": "마트", "mall": "마트", "department_store": "마트", "bakery": "빵집"}


def kind_of(p, geom):
    """표시 → 화면과 계산에 쓰는 종류 한 낱말. 쓰지 않을 것은 None."""
    name = p.get("name", "")
    if p.get("railway") == "subway_entrance":
        return "역 출구"
    if p.get("railway") in ("station", "halt") or (p.get("public_transport") == "station" and (p.get("subway") == "yes" or p.get("train") == "yes" or p.get("railway"))):
        return "역"
    if p.get("railway") in ("stop", "platform", "tram_stop") or p.get("public_transport") == "stop_position":
        return None                                 # 승강장 · 정차 위치는 역과 겹친다
    if p.get("highway") == "bus_stop" or (p.get("public_transport") == "platform" and p.get("bus") == "yes"):
        return "정류장"
    if p.get("highway") == "motorway_junction":
        return "나들목"
    if geom == "Point" and (p.get("highway") in ("traffic_signals", "crossing") or p.get("junction") == "yes"):
        return "교차로"
    if p.get("man_made") == "bridge" or (p.get("bridge") and p.get("bridge") != "no" and name.endswith("교")):
        return "다리"
    if p.get("tunnel") == "yes" and name.endswith(("터널", "지하차도")):
        return "터널"
    if p.get("leisure") == "park":
        return "공원"
    if p.get("leisure") == "playground":
        return "놀이터"
    if p.get("leisure") in ("sports_centre", "pitch", "stadium", "fitness_centre", "swimming_pool"):
        return "체육시설"
    if p.get("amenity") in AMENITY:
        return AMENITY[p["amenity"]]
    if "shop" in p:
        return SHOP.get(p["shop"], "가게")
    if p.get("tourism") in ("hotel", "motel", "guest_house", "hostel"):
        return "숙박"
    if p.get("tourism") in ("museum", "attraction", "artwork", "viewpoint", "zoo", "gallery", "theme_park"):
        return "볼거리"
    if "office" in p:
        return "사무실"
    if p.get("building") in ("apartments", "residential"):
        return "아파트"
    if p.get("place") in ("neighbourhood", "quarter", "suburb", "village"):
        return "동네"
    if p.get("natural") == "peak":
        return "산"
    if "building" in p:
        return "건물"
    if any(k in p for k in ("amenity", "tourism", "leisure", "man_made", "historic", "craft", "healthcare")):
        return "시설"
    return None


def rings_of(geom):
    c = geom["coordinates"]
    return [poly[0] for poly in c] if geom["type"] == "MultiPolygon" else [c[0]] if geom["type"] == "Polygon" else []


def in_ring(lon, lat, ring):
    """점들이 다각형 안인가(반직선 세기, numpy로 한꺼번에)."""
    r = np.asarray(ring)
    inside = np.zeros(len(lon), bool)
    x1, y1, x2, y2 = r[:-1, 0], r[:-1, 1], r[1:, 0], r[1:, 1]
    for a, b, c, d in zip(x1, y1, x2, y2):
        if b == d:
            continue
        hit = ((b > lat) != (d > lat)) & (lon < (c - a) * (lat - b) / (d - b) + a)
        inside ^= hit
    return inside


def simplify(ring, tol_m):
    """점 줄이기(Douglas–Peucker). 닫힌 고리는 반으로 나눠 줄인다(한 번에 하면 점 둘로 무너진다)."""
    def dp(pts):
        if len(pts) < 3:
            return pts
        (x1, y1), (x2, y2) = pts[0], pts[-1]
        dx, dy = (x2 - x1) * 88200, (y2 - y1) * 111000
        best, at = 0.0, 0
        for i in range(1, len(pts) - 1):
            px, py = (pts[i][0] - x1) * 88200, (pts[i][1] - y1) * 111000
            t = max(0.0, min(1.0, (px * dx + py * dy) / ((dx * dx + dy * dy) or 1)))
            d = math.hypot(px - t * dx, py - t * dy)
            if d > best:
                best, at = d, i
        return dp(pts[:at + 1])[:-1] + dp(pts[at:]) if best > tol_m else [pts[0], pts[-1]]
    if len(ring) < 8:
        return ring
    half = len(ring) // 2
    sys.setrecursionlimit(20000)
    return dp(ring[:half + 1])[:-1] + dp(ring[half:])


flat = lambda pts: [v for x, y in pts for v in (round((x - 126) * 1e5), round((y - 37) * 1e5))]   # noqa: E731  경도 − 126, 위도 − 37을 10만 배한 정수


def main(src, out):
    src, out = Path(src).expanduser(), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    f = next(src.glob("*.geojson.xz"))
    t0 = time.time()
    pts, roads, parks, admin = [], [], [], {"4": [], "6": [], "8": []}
    with lzma.open(f, "rt", encoding="utf-8") as r:
        for line in r:
            if '"name"' not in line and "subway_entrance" not in line and '"toilets"' not in line:
                continue
            s = line.strip().rstrip(",")
            if not s.startswith('{"type":"Feature"'):
                continue
            d = json.loads(s)
            g, p = d["geometry"], d.get("properties") or {}
            gt = g["type"]
            if p.get("boundary") == "administrative" and p.get("admin_level") in admin and gt in ("Polygon", "MultiPolygon"):
                admin[p["admin_level"]].append((p.get("name", ""), max(rings_of(g), key=len)))
                continue
            if gt == "Point":
                lon, lat = g["coordinates"]
                ring = None
            elif gt == "LineString":
                c = g["coordinates"]
                lon, lat = c[len(c) // 2]
                ring = None
            else:
                ring = max(rings_of(g), key=len)
                lon, lat = sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring)
            if not (BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]):
                continue
            name = " ".join((p.get("name") or "").split())      # 이름 속 줄바꿈 · 탭을 지운다(표가 깨진다)
            if gt == "LineString" and p.get("highway") in ROAD_CLASSES and name:
                roads.append((name, p["highway"], g["coordinates"], lon, lat))
                if not (p.get("bridge") and name.endswith("교")) and not (p.get("tunnel") == "yes" and name.endswith(("터널", "지하차도"))):
                    continue                        # 길은 roads로. 다리 · 터널인 길은 장소로도 남긴다
            elif gt == "LineString":
                continue
            kind = kind_of(p, gt)
            if not kind or (not name and kind not in ("역 출구", "화장실")) or name.isdigit():
                continue
            if kind == "공원" and ring is not None and len(ring) >= 4:
                parks.append((name, ring, lon, lat))
            pts.append((name, kind, lon, lat, " ".join((p.get("brand") or "").split()), " ".join((p.get("ref") or "").split())))
    print(f"읽음: 장소 후보 {len(pts):,} · 길 조각 {len(roads):,} · 공원 면 {len(parks):,} · 경계 {[(k, len(v)) for k, v in admin.items()]} ({time.time() - t0:.0f}초)", flush=True)

    seoul = next(ring for name, ring in admin["4"] if name.startswith("서울"))
    sring = simplify(seoul, 30)
    keep = lambda rows, ix, iy: in_ring(np.array([r[ix] for r in rows]), np.array([r[iy] for r in rows]), sring)   # noqa: E731
    pts = [r for r, k in zip(pts, keep(pts, 2, 3)) if k]
    roads = [r for r, k in zip(roads, keep(roads, 3, 4)) if k]
    parks = [r for r, k in zip(parks, keep(parks, 2, 3)) if k]

    def inside(rows):
        m = keep([(sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring)) for _, ring in rows], 0, 1)
        return [r for r, k in zip(rows, m) if k]
    gu = [(n, simplify(ring, 25)) for n, ring in inside(admin["6"]) if n.endswith("구")]
    dong = [(n, simplify(ring, 20)) for n, ring in inside(admin["8"])]

    # 역 출구에 가장 가까운 역 이름을 붙인다. 역 · 다리 · 정류장은 같은 이름이 가까이 여러 번 나오니 하나로
    stations = [(n, lon, lat) for n, k, lon, lat, _, _ in pts if k == "역"]
    sx, sy = np.array([s[1] for s in stations]), np.array([s[2] for s in stations])
    rows, seen = [], {}
    merge_m = {"역": 500, "다리": 600, "터널": 600, "정류장": 40, "공원": 300, "교차로": 60}
    for name, kind, lon, lat, brand, ref in pts:
        if kind == "역":
            name = name if name.endswith("역") else name + "역"
        if kind == "역 출구":
            if not ref or not len(sx):
                continue
            i = int(np.argmin((sx - lon) ** 2 + (sy - lat) ** 2))
            if math.hypot((sx[i] - lon) * 88200, (sy[i] - lat) * 111000) > 350:
                continue
            st = stations[i][0]
            name = f"{st if st.endswith('역') else st + '역'} {ref}번 출구"
        if not name:
            continue                                # 이름 없는 화장실 등은 뺀다
        near = seen.setdefault((name, kind), [])
        if any(math.hypot((lon - a) * 88200, (lat - b) * 111000) < merge_m.get(kind, 25) for a, b in near):
            continue
        near.append((lon, lat))
        rows.append((name, kind, f"{lon:.6f}", f"{lat:.6f}", brand, ref if kind in ("역 출구", "정류장", "나들목") else ""))
    rows.sort()
    (out / "places.tsv").write_text("\n".join("\t".join(r) for r in rows) + "\n", encoding="utf-8")

    # 같은 이름의 길 조각을 이어진 것끼리 묶는다(끝점이 200m 안이면 같은 길)
    by_name = defaultdict(list)
    for name, cls, coords, _, _ in roads:
        by_name[name].append((cls, coords))
    rank = ["motorway", "trunk", "primary", "secondary", "tertiary"]
    out_roads = []
    for name, ways in sorted(by_name.items()):
        group = list(range(len(ways)))

        def find(i):
            while group[i] != i:
                group[i] = group[group[i]]
                i = group[i]
            return i
        ends = [(w[1][0], w[1][-1]) for w in ways]
        for i in range(len(ways)):
            for j in range(i):
                if find(i) != find(j) and any(math.hypot((a[0] - b[0]) * 88200, (a[1] - b[1]) * 111000) < 200 for a in ends[i] for b in ends[j]):
                    group[find(i)] = find(j)
        parts = defaultdict(list)
        for i, w in enumerate(ways):
            parts[find(i)].append(w)
        for ws in parts.values():
            classes = [c.replace("_link", "") for c, _ in ws]
            cls = min(classes, key=lambda c: rank.index(c) if c in rank else 9)
            out_roads.append({"name": name, "cls": cls, "lines": [flat(simplify(c, 3) if len(c) > 8 else c) for _, c in ws]})
    (out / "roads.json").write_text(json.dumps({"roads": out_roads}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    area = lambda ring: abs(sum((x1 - 127) * 88200 * (y2 - 37.5) * 111000 - (x2 - 127) * 88200 * (y1 - 37.5) * 111000 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2   # noqa: E731
    areas = {"parks": [{"name": n, "ring": flat(simplify(ring, 6))} for n, ring, _, _ in parks if area(ring) > 2500],
             "gu": [{"name": n, "ring": flat(ring)} for n, ring in sorted(gu)], "dong": [{"name": n, "ring": flat(ring)} for n, ring in sorted(dong)],
             "seoul": flat(sring)}
    (out / "areas.json").write_text(json.dumps(areas, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    fetched = json.loads((src / "fetched.json").read_text()) if (src / "fetched.json").exists() else {}
    kinds = Counter(r[1] for r in rows)
    meta = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"), "source": "© OpenStreetMap contributors (ODbL 1.0), BBBike Seoul extract", "fetched": fetched,
            "places": len(rows), "kinds": dict(kinds.most_common()), "with_brand": sum(1 for r in rows if r[4]), "roads": len(out_roads),
            "road_names": len(by_name), "parks": len(areas["parks"]), "gu": len(gu), "dong": len(dong)}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False)[:900])
    print({p.name: p.stat().st_size for p in sorted(out.iterdir())}, f"{time.time() - t0:.0f}초")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).resolve().parents[1] / "data" / "seoul"))
