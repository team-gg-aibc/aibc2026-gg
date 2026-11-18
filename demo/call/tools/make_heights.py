"""서울 전체 건물의 실제 높이 자료를 만든다 → web/heights/index.json · cells/<x>-<y>.json (화면 web/heights.js가 보이는 칸만 읽음)

자료: 서울특별시 「서울시 건물 태양에너지 등급도(2018년)」(서울 열린데이터광장 OA-15944, 공공누리 제1유형) CSV. 원본(약 410MB)은 레포에 넣지 않는다.
      이 자료의 「건물높이」는 잰 높이가 아니라 모든 줄이 층수 × 3.5m다(674,769줄 모두). 그래서 여기서 말하는 실제 높이 = 서울시 자료의 층수로 셈한 높이다.
    python3 -I demo/call/tools/make_heights.py <원본 csv> <지도 타일을 받아 둘 폴더(레포 밖)>
    python3 -I demo/call/tools/make_heights.py <원본 csv> <타일 폴더> --rings   대본 건물 띠(hi.geojson)도 다시 만든다(서버: CALL_MODE=saved CALL_PORT=8775 python3 demo/call/server.py. 다른 주소면 --rings=http://…)
    python3 -I demo/call/tools/make_heights.py --test                          자료 없이 식 · 풀기만 점검

- 지도 타일(OpenFreeMap, 확대 14)의 건물 층은 같은 높이의 건물을 타일마다 한 덩어리로 묶어 두어 건물마다 높이를 바꿀 수 없다. 그래서 타일 건물은 그대로 두고,
  실제 높이가 타일 높이보다 높은 건물만 바닥 모양을 0.4m 넓혀 실제 높이로 덧그린다(타일 건물이 그 안에 들어가 가려진다).
  실제가 더 낮은 건물은 줄일 수 없어 타일 높이 그대로 둔다(개수를 찍는다).
- 지도 타일은 주마다 새 판이 나온다. 받아 둔 판(타일 폴더의 tiles-url.txt)을 계속 쓰므로, 새 판으로 다시 만들려면 타일 폴더를 비우고 돌린다.
- 칸 = 확대 14 타일 한 장(약 1.9km 네모). 타일 경계에 걸친 건물은 두 타일의 조각을 이어 붙여 가운데가 든 칸에 한 번만 넣는다.
- 높이 잇기: 서울시 자료는 건물마다 점 하나(UTM-K)와 층수 · 높이 · 면적. 타일 바닥 모양 안(1.5m 여유)의 점 가운데 면적이 가장 큰 것을 쓰고,
  면적이 0.25~4배 밖이거나, 타일에 높이가 있는데 서울시 값이 그 절반도 안 되면(단지 안 작은 시설과 잘못 이은 것) 버린다.
- 칸 파일: {"o": [칸 왼쪽 아래 경도, 위도], "b": [[실제 높이, 타일 높이, 바닥 높이, 바깥 고리, 구멍…], …]}. 고리는 1e-6도 정수로, 첫 점은 o에서, 다음 점부터는 앞 점에서 잰 차이.
- 강조(hi.geojson): 각 장면을 끝까지 돌려 질문이 물어본 표지(이름 · 자리) 가운데 건물 바닥 모양 안(4m 여유)에 든 것의 지붕 둘레 띠.
"""
import csv, gzip, json, math, struct, sys, time, urllib.error, urllib.request
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "web" / "heights"
URL, W, H = "http://127.0.0.1:8775", 1600, 900
SCENES = ["cat_street", "cat_park", "roadkill", "stray", "vendor", "pothole"]
TILEJSON, Z, EXT = "https://tiles.openfreemap.org/planet", 14, 4096
N = 2 ** Z
WIDEN, TALLER = 0.4, 0.5      # 바닥 모양을 넓히는 폭(m), 실제가 타일보다 이만큼 이상 높을 때만 덧그림
HUGE = (10000, 40)      # 바닥이 이만큼(㎡) 넓은데 이만큼(m) 넘게 높아지는 건물은 덧그리지 않는다. 탑과 낮은 기단을 한 모양으로 그린 건물이라 통째로 올리면 큰 덩어리가 된다(예: 잠실 롯데월드 4만㎡가 115m로)
SOURCE = "건물 바닥 모양: © OpenStreetMap 기여자(ODbL) · OpenFreeMap. 높이: 서울특별시 「서울시 건물 태양에너지 등급도(2018년)」, 서울 열린데이터광장 OA-15944, 공공누리 제1유형"
LON0, LAT0 = 127.0, 37.55      # 서울 전체를 한 평면(m)에 놓는다. 서울 끝에서 가로 0.2% 어긋나는 정도라 면적 비 · 0.4m 넓히기에는 영향이 없다
KX, KY = math.radians(1) * 6371008.8 * math.cos(math.radians(LAT0)), math.radians(1) * 6371008.8

# UTM-K(EPSG:5179) → 경도 · 위도 (GRS80, 원점 38°N 127.5°E, 축척 0.9996, 가산 1,000,000 / 2,000,000. Snyder의 횡메르카토르 식)
A_, F_ = 6378137.0, 1 / 298.257222101
E2 = 2 * F_ - F_ * F_; EP2 = E2 / (1 - E2); PHI0, LAM0, K0, FE, FN = math.radians(38), math.radians(127.5), 0.9996, 1e6, 2e6
def _m(p): return A_ * ((1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256) * p - (3 * E2 / 8 + 3 * E2 ** 2 / 32 + 45 * E2 ** 3 / 1024) * math.sin(2 * p) + (15 * E2 ** 2 / 256 + 45 * E2 ** 3 / 1024) * math.sin(4 * p) - (35 * E2 ** 3 / 3072) * math.sin(6 * p))
M0 = _m(PHI0)
def utmk_to_ll(x, y):
    mu = (M0 + (y - FN) / K0) / (A_ * (1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256)); e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu) + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    c1, t1 = EP2 * math.cos(p1) ** 2, math.tan(p1) ** 2; n1 = A_ / math.sqrt(1 - E2 * math.sin(p1) ** 2); r1 = A_ * (1 - E2) / (1 - E2 * math.sin(p1) ** 2) ** 1.5; d = (x - FE) / (n1 * K0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d ** 4 / 24 + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = LAM0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d ** 5 / 120) / math.cos(p1)
    return math.degrees(lon), math.degrees(lat)


# 타일 번호 ↔ 경도 · 위도 ↔ 평면(m)
def cell_of(lon, lat): return int((lon + 180) / 360 * N), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * N)
def cell_ll(fx, fy): return fx / N * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * fy / N))))      # 타일 좌표(소수) → 경도 · 위도
def to_m(lon, lat): return (lon - LON0) * KX, (lat - LAT0) * KY
def to_ll(x, y): return x / KX + LON0, y / KY + LAT0


# 벡터 타일(.pbf) 풀기: 건물 층의 낱개 바닥 모양과 높이만 꺼낸다
def _varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1; r |= (c & 0x7F) << s; s += 7
        if c < 0x80: return r, i
def _fields(b):      # 메시지 → (칸 번호, 값)
    i = 0
    while i < len(b):
        k, i = _varint(b, i); w = k & 7
        if w == 0: v, i = _varint(b, i)
        elif w == 2: n, i = _varint(b, i); v = b[i:i + n]; i += n
        else: n = 4 if w == 5 else 8; v = b[i:i + n]; i += n
        yield k >> 3, v
def _ints(b):
    i, out = 0, []
    while i < len(b): v, i = _varint(b, i); out.append(v)
    return out
def _value(b):
    (f, v), = _fields(b)
    return v.decode() if f == 1 else struct.unpack("<f", v)[0] if f == 2 else struct.unpack("<d", v)[0] if f == 3 else (v >> 1) ^ -(v & 1) if f == 6 else v
def tile_buildings(pbf):      # → [(고리들(타일 좌표), 높이, 바닥 높이)]. 고리들 = [바깥, 구멍…]
    out = []
    for f, layer in _fields(pbf):
        if f != 3: continue
        L = list(_fields(layer))
        if next(v for k, v in L if k == 1) != b"building": continue
        keys, vals = [v.decode() for k, v in L if k == 3], [_value(v) for k, v in L if k == 4]
        for feat in (v for k, v in L if k == 2):
            F = dict(_fields(feat)); t = _ints(F.get(2, b"")); p = {keys[t[j]]: vals[t[j + 1]] for j in range(0, len(t), 2)}
            g, i, x, y, ring, polys = _ints(F[4]), 0, 0, 0, [], []
            while i < len(g):
                cmd, cnt = g[i] & 7, g[i] >> 3; i += 1
                if cmd == 7:      # 고리 끝: 넓이 부호가 +면 새 건물의 바깥, -면 앞 건물의 구멍
                    a = sum(ring[k][0] * ring[k - 1][1] - ring[k - 1][0] * ring[k][1] for k in range(len(ring)))
                    if len(ring) >= 3 and a < 0: polys.append([ring])
                    elif len(ring) >= 3 and a > 0 and polys: polys[-1].append(ring)
                    ring = []; continue
                for _ in range(cnt):
                    x += (g[i] >> 1) ^ -(g[i] & 1); y += (g[i + 1] >> 1) ^ -(g[i + 1] & 1); i += 2; ring.append((x, y))
            out += [(rings, float(p.get("render_height") or 10), float(p.get("render_min_height") or 0)) for rings in polys]
    return out


def read_points(src):      # 서울시 점을 칸마다
    pts = defaultdict(list)
    with open(src, encoding="cp949", newline="") as f:
        rd = csv.reader(f, delimiter=";"); head = next(rd); ix = {k: head.index(k) for k in ("층수", "건물높이", "건물면적", "x좌표", "y좌표")}
        for c in rd:
            try: lon, lat = utmk_to_ll(float(c[ix["x좌표"]]), float(c[ix["y좌표"]]))
            except ValueError: continue      # noqa: E701
            pts[cell_of(lon, lat)].append((*to_m(lon, lat), int(float(c[ix["층수"]] or 0)), float(c[ix["건물높이"]] or 0), float(c[ix["건물면적"]] or 0)))
    return pts


class Maker:
    def __init__(self, pts, cache):
        from shapely import prepare
        from shapely.geometry import Polygon
        self.pts, self.cache, self.stat = pts, Path(cache), defaultdict(int)
        flat = json.loads((HERE.parent / "data" / "seoul" / "areas.json").read_text(encoding="utf-8"))["seoul"]      # 서울 경계(집계는 서울 안 건물만)
        self.seoul = Polygon([to_m(flat[i] / 1e5 + 126, flat[i + 1] / 1e5 + 37) for i in range(0, len(flat), 2)]).buffer(0); prepare(self.seoul)
        self.cache.mkdir(parents=True, exist_ok=True); v = self.cache / "tiles-url.txt"      # 받아 둔 타일과 같은 판을 계속 쓴다
        if not v.exists(): v.write_text(json.loads(self._get(TILEJSON))["tiles"][0], encoding="utf-8")
        self.url = v.read_text(encoding="utf-8").strip()

    @staticmethod
    def _get(url, tries=4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "make_heights", "Accept-Encoding": "gzip"}), timeout=60) as r:
                b = r.read(); return gzip.decompress(b) if r.headers.get("Content-Encoding") == "gzip" else b
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:      # 받다 끊기면 잠깐 쉬고 다시(없는 타일 404는 그대로 올린다)
            if isinstance(e, urllib.error.HTTPError) or tries <= 1: raise
            time.sleep(3); return Maker._get(url, tries - 1)

    @lru_cache(maxsize=120)
    def pieces(self, tx, ty):      # 타일 한 장의 건물 조각 → [(바닥 모양(m), 높이, 바닥 높이, 'in' 칸 안 · 'cross' 경계에 걸침 · 'out' 이웃 칸 것)]
        from shapely.geometry import Polygon, box
        f = self.cache / f"{tx}_{ty}.pbf"
        if not f.exists():
            try: f.write_bytes(self._get(self.url.format(z=Z, x=tx, y=ty)))
            except urllib.error.HTTPError as e:      # 바다 · 빈 곳은 타일이 없다
                if e.code != 404: raise
                f.write_bytes(b"")
            time.sleep(0.05)
        (x0, y1), (x1, y0) = (to_m(*cell_ll(tx, ty + 1)), to_m(*cell_ll(tx + 1, ty))); core, out = box(x0, y0, x1, y1), []
        for rings, h, h0 in tile_buildings(f.read_bytes()):
            m = [[to_m(*cell_ll(tx + x / EXT, ty + y / EXT)) for x, y in r] for r in rings]; q = Polygon(m[0], m[1:]).buffer(0)
            for p in (q.geoms if q.geom_type == "MultiPolygon" else [q]):
                if p.geom_type == "Polygon" and p.area >= 4:
                    out.append((p, h, h0, "in" if core.contains(p) else "cross" if core.intersection(p).area > 0 else "out"))
        return out

    @lru_cache(maxsize=12)
    def buildings(self, tx, ty):      # 이 칸의 건물 → [(바닥 모양(m), 타일 높이, 바닥 높이, 덧그릴 실제 높이 또는 None, 이은 서울시 높이 또는 None)]
        from shapely import STRtree, points
        from shapely.ops import unary_union
        near = [p for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy for p in self.pieces(tx + dx, ty + dy) if p[3] == "cross"]
        ntree, whole = STRtree([p[0] for p in near]) if near else None, []
        for q, h, h0, where in self.pieces(tx, ty):
            if where == "out": continue
            if where == "cross":      # 경계에 걸친 건물: 이웃 타일의 조각과 이어 붙이고, 가운데가 든 칸이 맡는다
                more = [near[i][0] for i in (ntree.query(q) if ntree else []) if near[i][1:3] == (h, h0) and q.intersection(near[i][0]).area > max(1.0, 0.05 * min(q.area, near[i][0].area))]
                u = unary_union([q, *more]) if more else q
                q = u if u.geom_type == "Polygon" else max(u.geoms, key=lambda g: g.area) if hasattr(u, "geoms") else q
                if cell_of(*to_ll(q.centroid.x, q.centroid.y)) != (tx, ty): continue
            whole.append((q, h, h0))
        whole.sort(key=lambda t: -t[1]); polys = [w[0] for w in whole]; tree, drop = STRtree(polys) if polys else None, set()
        for i, q in enumerate(polys):      # 같은 자리에 겹쳐 그려진 것(건물과 그 부분)은 높은 것 하나만
            if i not in drop:
                drop |= {j for j in tree.query(q) if j > i and j not in drop and q.intersection(polys[j]).area > 0.5 * min(q.area, polys[j].area)}
        kept = [w for i, w in enumerate(whole) if i not in drop]
        inside = [self.seoul.contains(k[0].centroid) for k in kept]; self.stat["서울 밖(칸에 같이 든 건물, 아래 집계에서 뺌)"] += inside.count(False)
        rows = [r for dx in (-1, 0, 1) for dy in (-1, 0, 1) for r in self.pts.get((tx + dx, ty + dy), [])]
        if not rows or not kept: return [(q, h, h0, None, None) for q, h, h0 in kept]
        ptree = STRtree(points([r[:2] for r in rows]))
        def judge(geoms, hs):      # 바닥 모양마다 → (집계 이름, 실제 높이 또는 None)
            cand = defaultdict(list)
            for g, i in zip(*ptree.query([g.buffer(1.5) for g in geoms], predicate="contains")): cand[g].append(rows[i])
            for n, (g, h) in enumerate(zip(geoms, hs)):
                best = max(cand[n], key=lambda r: r[4], default=None); real = best and (best[3] if best[3] > 0 else best[2] * 3.0)
                yield (("서울시 점 없음", None) if not best else ("서울시 높이 빈칸", None) if real <= 0 else ("면적이 너무 다름", None) if not 0.25 <= g.area / max(best[4], 1) <= 4
                       else ("타일 높이의 절반도 안 됨(잘못 이음)", None) if h != 5.0 and real < 0.5 * h else ("실제 높이 붙음", real))
        res = list(judge(polys := [k[0] for k in kept], [k[1] for k in kept]))
        # 지도가 한 건물을 여러 조각으로 그린 곳: 못 이은 조각 가운데 높이가 같고 맞닿은 것끼리 합쳐 한 번 더 이어 본다
        fail = defaultdict(list)
        for n, (why, _) in enumerate(res):
            if why in ("서울시 점 없음", "면적이 너무 다름"): fail[kept[n][1:3]].append(n)
        for (h, _), ns in fail.items():
            u = unary_union([polys[n] for n in ns]); blocks = list(u.geoms) if hasattr(u, "geoms") else [u]; members = defaultdict(list)
            for i, b in zip(*STRtree(blocks).query([polys[n].representative_point() for n in ns], predicate="within")): members[b].append(ns[i])
            for b, (why, real) in enumerate(judge(blocks, [h] * len(blocks))):
                if real and len(members[b]) > 1:
                    for n in members[b]: res[n] = (why, real); self.stat["조각을 합쳐서 이음"] += inside[n]      # noqa: E702
        out = []
        for n, (q, h, h0) in enumerate(kept):
            (why, real), sh = res[n], None; st = self.stat if inside[n] else defaultdict(int); st["건물(서울 안)"] += 1; st[why] += 1
            if real is None: pass
            elif real < h - TALLER: st["실제가 더 낮아 못 줄임(타일 높이 그대로)"] += 1; st["3m 넘게 낮은데 못 줄임"] += h - real >= 3      # noqa: E702
            elif real <= h + TALLER: st["타일과 같음"] += 1
            elif q.area >= HUGE[0] and real - h > HUGE[1]: st["바닥이 아주 넓어 덧그리지 않음(탑 + 낮은 기단)"] += 1
            else: st["실제가 더 높아 덧그림"] += 1; st["3m 넘게 높아짐"] += real - h >= 3; sh = round(real, 1)      # noqa: E702
            out.append((q, h, h0, sh, real))
        return out


def encode(q, ox, oy):      # 바닥 모양 → 고리마다 1e-6도 정수(첫 점은 칸 왼쪽 아래에서, 다음부터는 앞 점에서 잰 차이)
    out = []
    for ring in (q.exterior, *q.interiors):
        px = py = 0; flat = []
        for x, y in ring.coords[:-1]:
            lon, lat = to_ll(x, y); ix, iy = round((lon - ox) * 1e6), round((lat - oy) * 1e6); flat += [ix - px, iy - py]; px, py = ix, iy
        out.append(flat)
    return out
def decode(flat, ox, oy):      # heights.js의 ring()과 같은 식(점검용)
    x = y = 0; out = []
    for i in range(0, len(flat), 2): x += flat[i]; y += flat[i + 1]; out.append((ox + x / 1e6, oy + y / 1e6))
    return out
def num(v): return int(v) if float(v).is_integer() else v


def marks(url):      # 질문이 띄운 표지를 화면과 같은 방법으로 모은다(call.js renderMap의 marks)
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--mute-audio"])
        for sc in SCENES:
            pg = b.new_page(viewport={"width": W, "height": H})
            pg.add_init_script("""window.__mk = {}; setInterval(() => { try { const q = ui.askQ; if (!q) return;
                for (const o of q.options) for (const c of (o.set.clues || [])) { if (c.p && typeof c.p[0] === 'number') window.__mk[c.label || o.label] = ll(c.p);
                  else if (c.p) c.p.forEach((x, i) => { const n = (c.label || '').replace(' 사이', '').split(' ~ ')[i]; if (n) window.__mk[n] = ll(x); }); } } catch (e) {} }, 200);""")
            pg.goto(f"{url}/?heights=off&auto={sc}&speed=6"); pg.wait_for_function("window.CALL && CALL.ui.ended", timeout=400000)
            out[sc] = pg.evaluate("window.__mk"); pg.close()
        b.close()
    return out


def make_rings(mk, url):      # 표지가 든 건물의 지붕 둘레 띠(높이는 화면에 보이는 높이)
    from shapely.geometry import Point, mapping
    from shapely.ops import transform
    ll6 = lambda g: transform(lambda xs, ys, zs=None: ([round(x / KX + LON0, 6) for x in xs], [round(y / KY + LAT0, 6) for y in ys]), g)
    rings = []
    for sc, found in marks(url).items():
        for label, (lon, lat) in found.items():
            pt = Point(*to_m(lon, lat)); tx, ty = cell_of(lon, lat)
            hit = [b for dx in (-1, 0, 1) for dy in (-1, 0, 1) for b in mk.buildings(tx + dx, ty + dy) if b[0].buffer(4).contains(pt)]
            if not hit or any(r["properties"]["name"] == label for r in rings):      # 두 장면이 같은 곳을 물으면 띠는 하나(겹치면 깜빡인다)
                continue
            q, h, _, sh, _ = min(hit, key=lambda b: b[0].distance(pt))
            rings.append({"type": "Feature", "properties": {"name": label, "scene": sc, "at": [round(lon, 6), round(lat, 6)], "h": sh or h},
                          "geometry": mapping(ll6(q.buffer(WIDEN + 1.2, join_style=2).difference(q.buffer(WIDEN * 0.5, join_style=2)).simplify(0.2)))})
    (OUT / "hi.geojson").write_text(json.dumps({"type": "FeatureCollection", "source": SOURCE, "features": rings}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return [(r["properties"]["scene"], r["properties"]["name"], r["properties"]["h"]) for r in rings]


def main(src, cache, rings=None):
    pts = read_points(src); mk = Maker(pts, cache); cells = {}; (OUT / "cells").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "cells").glob("*.json"): old.unlink()
    for n, (tx, ty) in enumerate(sorted(pts, key=lambda c: (c[1], c[0]))):      # 서울시 점이 있는 칸만, 줄(위도) 차례로 — 이웃 타일을 다시 풀지 않게
        (ox, oy) = (round(v, 6) for v in cell_ll(tx, ty + 1)); rows = []
        for q, h, h0, sh, _ in mk.buildings(tx, ty):
            if sh is None: continue
            g = q.buffer(WIDEN, join_style=2).simplify(0.3)
            rows += [[num(sh), num(h), num(h0), *encode(p, ox, oy)] for p in (g.geoms if g.geom_type == "MultiPolygon" else [g]) if not p.is_empty]
        if rows:
            cells[f"{tx}-{ty}"] = len(rows)
            (OUT / "cells" / f"{tx}-{ty}.json").write_text(json.dumps({"o": [ox, oy], "b": rows}, separators=(",", ":")), encoding="utf-8")
        if n % 20 == 0: print(f"  칸 {n}/{len(pts)}", file=sys.stderr, flush=True)
    (OUT / "index.json").write_text(json.dumps({"source": SOURCE, "tiles": mk.url, "z": Z, "cells": cells}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size = sum(f.stat().st_size for f in (OUT / "cells").glob("*.json"))
    print(json.dumps({"서울시 자료 줄": sum(map(len, pts.values())), "칸": len(cells), "건물 집계": dict(mk.stat), "칸 파일 합계": f"{size / 1e6:.1f}MB", "가장 큰 칸": f"{max(f.stat().st_size for f in (OUT / 'cells').glob('*.json')) // 1024}KB",
                      "강조 띠": make_rings(mk, rings) if rings else "그대로 둠"}, ensure_ascii=False, indent=1))


def test():      # 자료 없이: 좌표 식 · 타일 풀기 · 고리 줄여 적기
    from shapely.geometry import Polygon
    lon, lat = utmk_to_ll(1e6, 2e6); assert abs(lon - 127.5) < 1e-9 and abs(lat - 38) < 1e-9
    lon, lat = utmk_to_ll(1e6, 2e6 + 1000); assert abs(lon - 127.5) < 1e-9 and abs(lat - 38.009013) < 1e-5, (lon, lat)      # 북으로 1km = 위도 0.009013도(자오선 곡률 반지름 6,359,630m · 축척 0.9996)
    assert cell_of(126.953066, 37.498051) == (13969, 6348) and cell_of(*cell_ll(13969.5, 6348.5)) == (13969, 6348)
    zz = lambda v: (v << 1) ^ (v >> 63)
    vb = lambda v: bytes([v]) if v < 128 else bytes([v & 127 | 128]) + vb(v >> 7)
    msg = lambda *kv: b"".join(vb(k << 3 | (2 if isinstance(v, bytes) else 0)) + (vb(len(v)) + v if isinstance(v, bytes) else vb(v)) for k, v in kv)
    geom = b"".join(vb(v) for v in [9, zz(10), zz(10), 26, zz(20), zz(0), zz(0), zz(20), zz(-20), zz(0), 15,          # 바깥 네모(화면에서 시계 방향)
                                    9, zz(5), zz(-15), 26, zz(0), zz(10), zz(10), zz(0), zz(0), zz(-10), 15])      # 구멍(반시계)
    pbf = msg((3, msg((1, b"building"), (2, msg((2, bytes([0, 0])), (3, 3), (4, geom))), (3, b"render_height"), (4, msg((4, 31))))))
    (rings, h, h0), = tile_buildings(pbf); assert (h, h0, len(rings)) == (31.0, 0.0, 2) and rings[0] == [(10, 10), (30, 10), (30, 30), (10, 30)] and rings[1][0] == (15, 15), (rings, h, h0)
    q = Polygon([(100, 200), (130, 200), (130, 240), (100, 240)], [[(110, 210), (120, 210), (120, 220), (110, 220)]]); ox, oy = to_ll(0, 0)
    m = [[to_m(*p) for p in decode(r, ox, oy)] for r in encode(q, ox, oy)]; back = Polygon(m[0], m[1:])
    assert back.symmetric_difference(q).area < 0.02 * q.area and abs(back.area - q.area) < 20, back.area
    print("ok")


if __name__ == "__main__":
    test() if sys.argv[1:] == ["--test"] else main(sys.argv[1], sys.argv[2], next((a.partition("=")[2] or URL for a in sys.argv if a.startswith("--rings")), None))
