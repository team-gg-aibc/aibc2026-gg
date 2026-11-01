#!/usr/bin/env python3
"""한강 3D 웹 지도 데이터 만들기 (표준 라이브러리만).

실행: python3 -I scripts/prep_web.py
입력: data/full_rel_152336.osm (OSM relation 152336 한강), data/overpass/*.json
출력: web/data/*.geojson (좌표 소수 6자리)
"""
import glob, json, math, os, re
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, OUT = os.path.join(ROOT, 'data'), os.path.join(ROOT, 'web', 'data')
KY = 110574.0
DECK = 2.5            # 다리 판 두께 (m)
W_END, E_END = '행주대교', '강동대교'   # 서울 구간 양 끝


def assemble(segs):
    """way 조각들을 끝점끼리 이어 닫힌 고리 목록으로."""
    segs = [list(s) for s in segs if len(s) > 1]
    rings = []
    while segs:
        cur = segs.pop()
        while cur[0] != cur[-1]:
            for i, s in enumerate(segs):
                if s[0] == cur[-1]: cur = cur + s[1:]
                elif s[-1] == cur[-1]: cur = cur + s[-2::-1]
                elif s[-1] == cur[0]: cur = s[:-1] + cur
                elif s[0] == cur[0]: cur = s[:0:-1] + cur
                else: continue
                del segs[i]
                break
            else:
                print('  ! 끝이 안 만나는 고리를 억지로 닫음:', len(cur), '점')
                cur.append(cur[0])
        if len(cur) >= 4:
            rings.append(cur)
    return rings


def inside(pt, rings):
    """홀짝 규칙: 고리 경계를 홀수 번 지나면 안."""
    x, y = pt[0], pt[1]
    c = False
    for r in rings:
        for (x1, y1), (x2, y2) in zip(r, r[1:]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                c = not c
    return c


class Frame:
    """중심 위도 기준 국지 미터 평면."""
    def __init__(self, pts):
        self.lon0 = sum(p[0] for p in pts) / len(pts)
        self.lat0 = sum(p[1] for p in pts) / len(pts)
        self.kx = math.cos(math.radians(self.lat0)) * 111320

    def xy(self, p): return ((p[0] - self.lon0) * self.kx, (p[1] - self.lat0) * KY)

    def ll(self, q): return [round(self.lon0 + q[0] / self.kx, 6), round(self.lat0 + q[1] / KY, 6)]


def selfcheck():
    sq = [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]
    hole = [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)]
    assert inside((0.5, 0.5), [sq, hole]) and not inside((2, 2), [sq, hole]) and not inside((5, 2), [sq])
    r = assemble([[(0, 0), (4, 0)], [(4, 4), (4, 0)], [(4, 4), (0, 4), (0, 0)]])
    assert len(r) == 1 and r[0][0] == r[0][-1] and len(r[0]) == 5


def load_river():
    root = ET.parse(os.path.join(DATA, 'full_rel_152336.osm')).getroot()
    nodes = {n.get('id'): (float(n.get('lon')), float(n.get('lat'))) for n in root.iter('node')}
    ways = {w.get('id'): [nodes[nd.get('ref')] for nd in w.iter('nd')] for w in root.iter('way')}
    segs = {'outer': [], 'inner': []}
    for m in root.find('relation').iter('member'):
        if m.get('type') == 'way' and m.get('ref') in ways:
            segs[m.get('role') or 'outer'].append(ways[m.get('ref')])
    outer, inner = assemble(segs['outer']), assemble(segs['inner'])
    print(f'강 152336: outer 고리 {len(outer)}, inner 고리(섬) {len(inner)}')
    sets = [outer + inner]
    # 152336은 동쪽 끝이 경도 127.092. 그 동쪽(잠실~강동)은 relation 3769500 「한강」
    for e in load_elements('river_east.json'):
        if e['type'] == 'relation' and e.get('tags', {}).get('name') == '한강' and e['id'] != 152336:
            rings = [r for o, ins in polys_of(e) for r in [o] + ins]
            print(f"강 {e['id']}: 고리 {len(rings)}")
            sets.append(rings)
    return sets


def wet_at(p, water):
    return any(inside(p, rs) for rs in water)


def load_elements(pattern):
    seen = {}
    for fn in sorted(glob.glob(os.path.join(DATA, 'overpass', pattern))):
        for e in json.load(open(fn, encoding='utf-8')).get('elements', []):
            seen[(e['type'], e['id'])] = e
    return list(seen.values())


def polys_of(e):
    """Overpass 요소 → [(바깥 고리, [안쪽 고리…])]."""
    if e['type'] == 'way':
        ring = [(g['lon'], g['lat']) for g in e.get('geometry', []) if g]
        if len(ring) < 3: return []
        if ring[0] != ring[-1]: ring.append(ring[0])
        return [(ring, [])]

    def members(role):
        return [[(g['lon'], g['lat']) for g in m['geometry'] if g] for m in e.get('members', [])
                if m['type'] == 'way' and m.get('geometry') and (m.get('role') or 'outer') == role]
    outers, inners = assemble(members('outer')), assemble(members('inner'))
    return [(o, [i for i in inners if inside(i[0], [o])]) for o in outers]


def geometry(polys):
    rings = lambda o, ins: [[[round(x, 6), round(y, 6)] for x, y in r] for r in [o] + ins]
    if len(polys) == 1: return {'type': 'Polygon', 'coordinates': rings(*polys[0])}
    return {'type': 'MultiPolygon', 'coordinates': [rings(o, ins) for o, ins in polys]}


def top_of(name):
    if '잠수교' in name: return 4.5
    if '반포대교' in name: return 18.0
    if '철교' in name: return 12.0
    return 15.0


def analyze(e, water):
    polys = polys_of(e)
    if not polys: return None
    pts = [p for o, _ in polys for p in o]
    f = Frame(pts)
    xy = [f.xy(p) for p in pts]
    sxx = sum(x * x for x, _ in xy); syy = sum(y * y for _, y in xy); sxy = sum(x * y for x, y in xy)
    a = 0.5 * math.atan2(2 * sxy, sxx - syy)          # 주성분(긴 축) 방향
    u, v = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
    ts = [x * u[0] + y * u[1] for x, y in xy]; ss = [x * v[0] + y * v[1] for x, y in xy]
    tmin, tmax, smid = min(ts), max(ts), (min(ss) + max(ss)) / 2
    n = max(1, round((tmax - tmin) / 20))
    at = lambda t, s: f.ll((t * u[0] + s * v[0], t * u[1] + s * v[1]))
    tvals = [tmin + (tmax - tmin) * i / n for i in range(n + 1)]
    samples = [at(t, smid) for t in tvals]
    wet = [wet_at(p, water) for p in samples]
    # 강을 가로지르는지: 물 위 점에서 다리와 직각으로 ±250m(=강 위·아래쪽)가 둘 다 물이면 그 점은 가로지름.
    # 물 위 점의 절반 이상이 그렇고 길이 500m 이상이어야 한강 횡단 다리. 강가를 따라 놓인 램프·접속교는 빠진다.
    xs = sum(1 for t, w in zip(tvals, wet) if w and wet_at(at(t, smid + 250), water) and wet_at(at(t, smid - 250), water))
    xfrac = xs / max(1, sum(wet))
    cross = xfrac >= 0.5 and tmax - tmin >= 500
    return {'e': e, 'name': e.get('tags', {}).get('name', ''), 'polys': polys, 'f': f, 'u': u, 'v': v, 'at': at,
            'tmin': tmin, 'tmax': tmax, 'samples': samples, 'wet': wet, 'ratio': sum(wet) / len(wet),
            'cross': cross, 'xfrac': xfrac, 'center': at((tmin + tmax) / 2, smid), 'smin': min(ss), 'smax': max(ss)}


def piers(b, top):
    """양 끝 40m를 빼고 65m 간격, 긴 축 4m × 판 폭의 70%."""
    f, u, v = b['f'], b['u'], b['v']
    rings = [[(x * u[0] + y * u[1], x * v[0] + y * v[1]) for x, y in map(f.xy, r)]
             for o, ins in b['polys'] for r in [o] + ins]
    length = b['tmax'] - b['tmin'] - 80
    if length < 0: return []
    out, t = [], b['tmin'] + 40 + (length % 65) / 2
    while t <= b['tmax'] - 40 + 1e-6:
        xs = sorted(s1 + (t - t1) * (s2 - s1) / (t2 - t1)
                    for r in rings for (t1, s1), (t2, s2) in zip(r, r[1:]) if (t1 > t) != (t2 > t))
        for s0, s1 in zip(xs[0::2], xs[1::2]):
            w, c = min((s1 - s0) * 0.7, 30), (s0 + s1) / 2   # 굽은 다리에서 비스듬히 잘린 폭은 30m로 자름
            if w >= 1:
                ring = [b['at'](t + dt, c + ds) for dt, ds in ((-2, -w / 2), (2, -w / 2), (2, w / 2), (-2, w / 2))]
                out.append(ring + [ring[0]])
        t += 65
    return out


def dist_m(p, q):
    return math.hypot((p[0] - q[0]) * math.cos(math.radians(p[1])) * 111320, (p[1] - q[1]) * KY)


def circle(lon, lat, r, n=64):
    kx = math.cos(math.radians(lat)) * 111320
    ring = [[round(lon + r * math.cos(2 * math.pi * i / n) / kx, 6), round(lat + r * math.sin(2 * math.pi * i / n) / KY, 6)]
            for i in range(n)]
    return ring + [ring[0]]


def interior_point(outer, inners):
    """무게중심, 밖이면 그 위도를 지나는 가로선에서 가장 넓은 안쪽 구간의 가운데."""
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(outer, outer[1:]):
        k = x1 * y2 - x2 * y1
        a += k; cx += (x1 + x2) * k; cy += (y1 + y2) * k
    c = (cx / (3 * a), cy / (3 * a)) if a else outer[0]
    rings = [outer] + inners
    if inside(c, rings): return c
    y = c[1]
    xs = sorted(x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                for r in rings for (x1, y1), (x2, y2) in zip(r, r[1:]) if (y1 > y) != (y2 > y))
    pairs = list(zip(xs[0::2], xs[1::2]))
    if not pairs: return outer[0]
    s0, s1 = max(pairs, key=lambda p: p[1] - p[0])
    return ((s0 + s1) / 2, y)


def area_m2(ring):
    f = Frame(ring)
    xy = [f.xy(p) for p in ring]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:]))) / 2


def feat(geom, **props): return {'type': 'Feature', 'properties': props, 'geometry': geom}


def write(name, feats):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as fp:
        json.dump({'type': 'FeatureCollection', 'features': feats}, fp, ensure_ascii=False, separators=(',', ':'))
    print(f'  → web/data/{name}: {len(feats)}개')


# 핀 7개 (시연용 가상 예시). dx·dy = 칩 위치(화면 px, 땅 점 기준)
PINS = [
    (1, '여의나루역 출구', '건강관리과', 37.5269648, 126.9322458, 70, -125),
    (2, '따릉이 대여소', '자전거PM과', 37.5271568, 126.9319, 112, -58),
    # 카카오맵 장소 20519172 「여의도공원 공영주차장」(여의도동 2-11) 표시 좌표
    (3, '공영주차장(예시)', '주차계획과', 37.527195, 126.922534, 60, -90),
    (4, '강변 산책로', '동물보호과', 37.531485, 126.929177, 0, -70),
    (5, '여의도공원', '정원도시정책과', 37.528005, 126.925394, 0, -70),
    (6, '따릉이 대여소', '자전거PM과', 37.526455, 126.933365, -95, -122),
    (7, '안내센터', '청년정책담당관', 37.527353, 126.932934, -112, -56),
]


def main():
    selfcheck()
    os.makedirs(OUT, exist_ok=True)
    water = load_river()

    # ---- 다리
    els = [e for e in load_elements('bridges_*.json') if e['type'] in ('way', 'relation')]
    print('다리 요소', len(els))
    bs = [b for b in (analyze(e, water) for e in els) if b]
    han = [b for b in bs if b['ratio'] >= 0.3]
    names = {b['name'] for b in han if b['name']}
    for b in han:
        if not b['name']: print(f"  (이름 없음, 물 {b['ratio']:.0%}) {b['e']['type']}/{b['e']['id']} @ {b['center']} → 뺌")
    keep = [b for b in han if b['name']]
    # 같은 이름 조각은 땅 위 접속 구간도 함께 (물 위 조각에서 2km 안)
    for b in bs:
        if b not in keep and b['name'] in names and any(
                dist_m(b['center'], k['center']) < 2000 for k in keep if k['name'] == b['name']):
            keep.append(b)

    groups = {}
    for b in keep:
        groups.setdefault(re.sub(r'\s*[A-Z]선$', '', b['name']), []).append(b)
    labels = []
    for g, ps in groups.items():
        sp = [s for p in ps for s in p['samples']]
        mid = (sum(s[0] for s in sp) / len(sp), sum(s[1] for s in sp) / len(sp))
        wet = [s for p in ps for s, w in zip(p['samples'], p['wet']) if w] or sp
        best = min(wet, key=lambda s: dist_m(s, mid))
        labels.append(feat({'type': 'Point', 'coordinates': best}, name=g, lon=best[0],
                           top=max(top_of(p['name']) for p in ps), cross=any(p['cross'] for p in ps)))
    labels.sort(key=lambda f: f['properties']['lon'])
    lon_of = {f['properties']['name']: f['properties']['lon'] for f in labels}
    west, east = lon_of.get(W_END, 126.80) - 0.004, lon_of.get(E_END, 127.18) + 0.004
    for f in labels:
        if not west <= f['properties']['lon'] <= east: print('  서울 구간 밖이라 뺌:', f['properties']['name'])
    labels = [f for f in labels if west <= f['properties']['lon'] <= east]
    inrange = {f['properties']['name'] for f in labels}

    decks, pier_feats, mask = [], [], []
    for g, ps in groups.items():
        if g not in inrange: continue
        for p in ps:
            top = top_of(p['name'])
            decks.append(feat(geometry(p['polys']), name=p['name'], base=top - DECK, top=top))
            # 원래 지도의 다리 위 도로선을 이 상자 안에서만 숨긴다 (긴 축 ±150m, 폭 ±30m)
            box = [p['at'](t, s) for t, s in ((p['tmin'] - 150, p['smin'] - 30), (p['tmax'] + 150, p['smin'] - 30),
                                              (p['tmax'] + 150, p['smax'] + 30), (p['tmin'] - 150, p['smax'] + 30))]
            mask.append(feat({'type': 'Polygon', 'coordinates': [box + [box[0]]]}, name=p['name']))
            for ring in piers(p, top):
                pier_feats.append(feat({'type': 'Polygon', 'coordinates': [ring]}, base=0, top=top - DECK))
    print('한강 다리 (서→동):')
    for f in labels:
        ps = groups[f['properties']['name']]
        print(f"  {f['properties']['lon']:.4f} {f['properties']['name']} 조각 {len(ps)} "
              f"물비율 {max(p['ratio'] for p in ps):.0%} 가로지름 {max(p['xfrac'] for p in ps):.0%} "
              f"길이 {max(p['tmax'] - p['tmin'] for p in ps):.0f}m 높이 {f['properties']['top']}"
              + ('' if f['properties']['cross'] else '  ← 강가 구조물(판만, 이름표 없음)'))
    write('bridges.geojson', decks)
    write('bridge_mask.geojson', mask)
    write('piers.geojson', pier_feats)
    write('bridge_labels.geojson', [f for f in labels if f['properties']['cross']])

    # ---- 한강공원
    parks = [e for e in load_elements('parks*.json') if e.get('tags', {}).get('name', '').endswith('한강공원')]
    park_feats, best = [], {}
    for e in parks:
        polys = polys_of(e)
        if not polys: continue
        name = e['tags']['name']
        park_feats.append(feat(geometry(polys), name=name))
        for o, ins in polys:
            a = area_m2(o)
            if a > best.get(name, (0,))[0]: best[name] = (a, o, ins)
    write('parks.geojson', park_feats)
    write('park_labels.geojson', [feat({'type': 'Point', 'coordinates': [round(c, 6) for c in interior_point(o, ins)]}, name=n)
                                  for n, (a, o, ins) in sorted(best.items())])
    print('  공원:', ', '.join(sorted(best)))

    # ---- 핀
    pins = []
    for i, name, dept, lat, lon, dx, dy in PINS:
        pins.append(feat({'type': 'Point', 'coordinates': [round(lon, 6), round(lat, 6)]},
                         id=i, name=name, dept=dept, dx=dx, dy=dy))
        pins.append(feat({'type': 'Polygon', 'coordinates': [circle(lon, lat, 14)]}, id=i, kind='ring14'))
    write('pins.geojson', pins)
    _, _, _, lat1, lon1, _, _ = PINS[0]
    kx = math.cos(math.radians(lat1)) * 111320
    write('ring10.geojson', [
        feat({'type': 'Polygon', 'coordinates': [circle(lon1, lat1, 10)]}, kind='ring'),
        feat({'type': 'Point', 'coordinates': [round(lon1 + 7.1 / kx, 6), round(lat1 - 7.1 / KY, 6)]}, label='출구 10m'),
    ])


if __name__ == '__main__':
    main()
