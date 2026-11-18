"""시연 자리 둘레 건물의 실제 높이 자료를 만든다 → web/heights/buildings.geojson · hi.geojson (화면 web/heights.js가 읽음)

자료: 서울특별시 「서울시 건물 태양에너지 등급도(2018년)」(서울 열린데이터광장 OA-15944, 공공누리 제1유형) CSV. 원본(약 410MB)은 레포에 넣지 않는다.
    python3 -I demo/call/tools/make_heights.py <원본 csv>      (서버: CALL_MODE=saved CALL_PORT=8775 python3 demo/call/server.py)

- 지도 타일(OpenFreeMap)의 건물 층은 같은 높이의 건물을 타일마다 한 덩어리로 묶어 두어 건물마다 높이를 바꿀 수 없다. 그래서 타일 건물은 그대로 두고,
  자리 둘레에서 실제 높이가 타일 높이보다 높은 건물만 바닥 모양을 0.4m 넓혀 실제 높이로 덧그린다(타일 건물이 그 안에 들어가 가려진다).
  실제가 더 낮은 건물은 줄일 수 없어 타일 높이 그대로 둔다(개수를 찍는다). 둘레 밖은 손대지 않는다.
- 높이 잇기: 서울시 자료는 건물마다 점 하나(UTM-K)와 층수 · 높이 · 면적. 타일 바닥 모양 안(1.5m 여유)의 점 가운데 면적이 가장 큰 것을 쓰고,
  면적이 0.25~4배 밖이거나, 타일에 높이가 있는데 서울시 값이 그 절반도 안 되면(단지 안 작은 시설과 잘못 이은 것) 버린다.
- 강조(hi.geojson): 각 장면을 끝까지 돌려 질문이 물어본 표지(이름 · 자리) 가운데 건물 바닥 모양 안(4m 여유)에 든 것의 지붕 둘레 띠.
"""
import csv, json, math, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "web" / "heights"
URL, W, H = "http://127.0.0.1:8775", 1600, 900
AREAS = {      # 장면이 일어나는 자리: 이름 → (가운데 경도 · 위도, 반지름 m)
    "sangdo": ((126.953066, 37.498051), 1000),        # cat_street 상도1동 주민센터
    "seoulforest": ((127.0386, 37.5412), 1000),       # cat_park · stray · vendor 서울숲, roadkill 강변북로
    "anam": ((127.029656, 37.586361), 800),           # pothole 안암역
}
SCENES = ["cat_street", "cat_park", "roadkill", "stray", "vendor", "pothole"]
WIDEN, TALLER = 0.4, 0.5      # 바닥 모양을 넓히는 폭(m), 실제가 타일보다 이만큼 이상 높을 때만 덧그림
SOURCE = "건물 바닥 모양: © OpenStreetMap 기여자(ODbL) · OpenFreeMap. 높이: 서울특별시 「서울시 건물 태양에너지 등급도(2018년)」, 서울 열린데이터광장 OA-15944, 공공누리 제1유형"

# UTM-K(EPSG:5179) → 경도 · 위도 (GRS80, 원점 38°N 127.5°E, 축척 0.9996, 가산 1,000,000 / 2,000,000. Snyder의 횡메르카토르 식)
A_, F_ = 6378137.0, 1 / 298.257222101
E2 = 2 * F_ - F_ * F_; EP2 = E2 / (1 - E2); LAT0, LON0, K0, FE, FN = math.radians(38), math.radians(127.5), 0.9996, 1e6, 2e6
def _m(p): return A_ * ((1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256) * p - (3 * E2 / 8 + 3 * E2 ** 2 / 32 + 45 * E2 ** 3 / 1024) * math.sin(2 * p) + (15 * E2 ** 2 / 256 + 45 * E2 ** 3 / 1024) * math.sin(4 * p) - (35 * E2 ** 3 / 3072) * math.sin(6 * p))
M0 = _m(LAT0)
def utmk_to_ll(x, y):
    mu = (M0 + (y - FN) / K0) / (A_ * (1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256)); e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu) + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    c1, t1 = EP2 * math.cos(p1) ** 2, math.tan(p1) ** 2; n1 = A_ / math.sqrt(1 - E2 * math.sin(p1) ** 2); r1 = A_ * (1 - E2) / (1 - E2 * math.sin(p1) ** 2) ** 1.5; d = (x - FE) / (n1 * K0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d ** 4 / 24 + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = LON0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d ** 5 / 120) / math.cos(p1)
    return math.degrees(lon), math.degrees(lat)


def main(src: Path):
    from playwright.sync_api import sync_playwright
    from shapely.geometry import shape, Point, Polygon, MultiPolygon, mapping
    from shapely.ops import transform
    from shapely.strtree import STRtree
    # 1. 서울시 점을 자리마다 잘라 둔다(원본은 읽기만)
    sol = defaultdict(list)
    with open(src, encoding="cp949", newline="") as f:
        rd = csv.reader(f, delimiter=";"); head = next(rd); ix = {k: head.index(k) for k in ("층수", "건물높이", "건물면적", "x좌표", "y좌표")}
        for c in rd:
            try: lon, lat = utmk_to_ll(float(c[ix["x좌표"]]), float(c[ix["y좌표"]]))
            except ValueError: continue      # noqa: E701
            for name, ((alon, alat), r) in AREAS.items():
                if math.hypot((lon - alon) * 88200, (lat - alat) * 111000) <= r + 100:
                    sol[name].append((lon, lat, int(float(c[ix["층수"]] or 0)), float(c[ix["건물높이"]] or 0), float(c[ix["건물면적"]] or 0)))
    # 2. 자리마다 타일 건물(확대 14, 화면이 받는 타일 그대로)과 각 장면이 물어본 표지
    tiles, marks = {}, {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--mute-audio"])
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto(f"{URL}/?heights=off"); pg.wait_for_function("window.CALL && CALL.map && CALL.map.loaded()", timeout=90000)
        for name, (c, r) in AREAS.items():
            pg.evaluate("(c) => CALL.map.jumpTo(c)", {"center": list(c), "zoom": 14, "pitch": 0, "bearing": 0}); pg.wait_for_timeout(1500)
            pg.wait_for_function("CALL.map.areTilesLoaded() && CALL.map.loaded()", timeout=90000, polling=300); pg.wait_for_timeout(800)
            tiles[name] = pg.evaluate("() => CALL.map.querySourceFeatures('openmaptiles', { sourceLayer: 'building' }).map((f) => ({ p: f.properties, g: f.geometry }))")
        pg.close()
        for sc in SCENES:      # 질문이 띄운 표지를 화면과 같은 방법으로 모은다(call.js renderMap의 marks)
            pg = b.new_page(viewport={"width": W, "height": H})
            pg.add_init_script("""window.__mk = {}; setInterval(() => { try { const q = ui.askQ; if (!q) return;
                for (const o of q.options) for (const c of (o.set.clues || [])) { if (c.p && typeof c.p[0] === 'number') window.__mk[c.label || o.label] = ll(c.p);
                  else if (c.p) c.p.forEach((x, i) => { const n = (c.label || '').replace(' 사이', '').split(' ~ ')[i]; if (n) window.__mk[n] = ll(x); }); } } catch (e) {} }, 200);""")
            pg.goto(f"{URL}/?heights=off&auto={sc}&speed=6"); pg.wait_for_function("window.CALL && CALL.ui.ended", timeout=400000)
            marks[sc] = pg.evaluate("window.__mk"); pg.close()
        b.close()
    feats, rings, stat = [], [], {}
    for name, ((alon, alat), r) in AREAS.items():
        kx, ky = math.radians(1) * 6371008.8 * math.cos(math.radians(alat)), math.radians(1) * 6371008.8
        to_m = lambda g: transform(lambda xs, ys, zs=None: ([(x - alon) * kx for x in xs], [(y - alat) * ky for y in ys]), g)
        to_ll = lambda g: transform(lambda xs, ys, zs=None: ([round(x / kx + alon, 6) for x in xs], [round(y / ky + alat, 6) for y in ys]), g)
        polys = []      # 덩어리를 낱개 건물로
        for t in tiles[name]:
            try: g = to_m(shape(t["g"])).buffer(0)
            except Exception: continue      # noqa: BLE001,E701
            for q in (g.geoms if isinstance(g, MultiPolygon) else [g]):
                if isinstance(q, Polygon) and q.area >= 4 and q.centroid.distance(Point(0, 0)) <= r:
                    polys.append((q, float(t["p"].get("render_height") or 10), float(t["p"].get("render_min_height") or 0)))
        kept = []      # 같은 건물이 타일 둘에 겹쳐 들면 하나만
        for q, h, h0 in sorted(polys, key=lambda t: -t[1]):
            if not any(q.intersection(k[0]).area > 0.5 * min(q.area, k[0].area) for k in kept if k[0].intersects(q)):
                kept.append((q, h, h0))
        rows = sol[name]; pts = [Point((x[0] - alon) * kx, (x[1] - alat) * ky) for x in rows]; tree = STRtree(pts)
        st = defaultdict(int); shown = {}
        for n, (q, h, h0) in enumerate(kept):
            gb = q.buffer(1.5); cand = [rows[i] for i in tree.query(gb) if gb.contains(pts[i])]
            if not cand: st["서울시 점 없음"] += 1; continue      # noqa: E702
            best = max(cand, key=lambda x: x[4]); sh = best[3] if best[3] > 0 else best[2] * 3.0
            if sh <= 0: st["서울시 높이 빈칸"] += 1; continue      # noqa: E702
            if not 0.25 <= q.area / max(best[4], 1) <= 4: st["면적이 너무 다름"] += 1; continue      # noqa: E702
            if h != 5.0 and sh < 0.5 * h: st["타일 높이의 절반도 안 됨(잘못 이음)"] += 1; continue      # noqa: E702
            st["실제 높이 붙음"] += 1
            if sh < h - TALLER: st["실제가 더 낮아 못 줄임(타일 높이 그대로)"] += 1; continue      # noqa: E702
            if sh <= h + TALLER: st["타일과 같음"] += 1; continue      # noqa: E702
            st["실제가 더 높아 덧그림"] += 1; st["3m 넘게 높아짐"] += sh - h >= 3; shown[n] = sh
            feats.append({"type": "Feature", "properties": {"render_height": round(sh, 1), "render_min_height": h0, "tile_height": h, "area": name},
                          "geometry": mapping(to_ll(q.buffer(WIDEN, join_style=2).simplify(0.3)))})
        st["건물(둘레 안)"] = len(kept); stat[name] = st
        for sc, mk in marks.items():      # 표지가 든 건물의 지붕 둘레 띠(높이는 화면에 보이는 높이)
            for label, (lon, lat) in mk.items():
                pt = Point((lon - alon) * kx, (lat - alat) * ky)
                if pt.distance(Point(0, 0)) > r:
                    continue
                hit = [(n, k) for n, k in enumerate(kept) if k[0].buffer(4).contains(pt)]
                if not hit:
                    continue
                n, (q, h, _) = min(hit, key=lambda t: t[1][0].distance(pt))
                if any(rg["properties"]["name"] == label for rg in rings):      # 두 장면이 같은 곳을 물으면 띠는 하나(겹치면 깜빡인다)
                    continue
                rings.append({"type": "Feature", "properties": {"name": label, "scene": sc, "at": [round(lon, 6), round(lat, 6)], "h": round(shown.get(n, h), 1)},
                              "geometry": mapping(to_ll(q.buffer(WIDEN + 1.2, join_style=2).difference(q.buffer(WIDEN * 0.5, join_style=2)).simplify(0.2)))})
    OUT.mkdir(exist_ok=True)
    for fn, fc in (("buildings.geojson", feats), ("hi.geojson", rings)):
        (OUT / fn).write_text(json.dumps({"type": "FeatureCollection", "source": SOURCE, "areas": {k: {"center": c, "r": r} for k, (c, r) in AREAS.items()}, "features": fc},
                                         ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"자리별": stat, "덧그린 건물": len(feats), "강조 띠": [(x["properties"]["scene"], x["properties"]["name"]) for x in rings],
                      "파일": {fn: f"{(OUT / fn).stat().st_size // 1024}KB" for fn in ("buildings.geojson", "hi.geojson")}}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
