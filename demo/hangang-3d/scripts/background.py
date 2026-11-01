"""핵심 7건 말고 한강 둘레에 깔 가상 민원을 만든다 (make_complaints.py가 부름).

장소 원칙
- 서울시 조례 6종 이야기라 서울 쪽만 쓴다: 경도 126.865 서쪽·127.115 동쪽은 강 남쪽(강서·강동)만, 그 밖은 양쪽.
- 한강공원 안(공원녹지)은 금연 보행자길·자전거·반려견·청년 문의에만 쓰고, 도시공원 일은 이름 붙은 도시공원(한강공원 아님)에만 둔다.
- 주차장 문의는 시 공영주차장 이야기라 이름을 지어내지 않고 「…근처 시 공영주차장(예시)」로만 쓴다.
- 축제 날이라 여의도 가까이에 더 몰리게 무게를 준다.
"""
import json
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAT0, LON0 = 37.53, 126.98
KX, KY = math.cos(math.radians(LAT0)) * 111320, 110574
YEOUIDO = (126.9312, 37.5262)
SPACING = 70                  # 핀끼리 최소 간격(m)
CITY_PARKS = {'여의도공원', '앙카라공원', '서울숲', '평화의공원', '하늘공원', '노을공원', '난지천공원', '사육신공원',
              '효사정공원', '용양봉저정공원', '응봉공원', '경의선숲길공원', '양화진공원', '올림픽공원', '보라매공원'}


def xy(lon, lat):
    return ((lon - LON0) * KX, (lat - LAT0) * KY)


def meters(a, b):
    (ax, ay), (bx, by) = xy(*a), xy(*b)
    return math.hypot(ax - bx, ay - by)


class River:
    """다리 이름표 점(서→동)을 이은 강 중심선. 거리와 어느 쪽 강가인지(북 +, 남 -)."""

    def __init__(self, labels):
        pts, last = [], None
        for f in labels:
            p = f['geometry']['coordinates']
            if last is None or meters(last, p) > 400:
                pts.append(xy(*p))
                last = p
        self.seg = list(zip(pts, pts[1:]))

    def where(self, lon, lat):
        px, py = xy(lon, lat)
        best = (1e18, 0)
        for (ax, ay), (bx, by) in self.seg:
            dx, dy = bx - ax, by - ay
            t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
            d = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if d < best[0]:
                best = (d, dx * (py - ay) - dy * (px - ax))
        return best[0], (1 if best[1] > 0 else -1)


def seoul_side(lon, lat, side):
    if not 126.80 < lon < 127.14:
        return False
    if lon < 126.865 or lon > 127.115:
        return side < 0          # 서쪽 북안은 고양, 동쪽 북안은 구리
    return True


def inside(lon, lat, rings):
    hit = False
    for ring in rings:           # 짝홀 규칙: 바깥 고리 안 + 구멍(여의도 섬 안쪽 등) 밖
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                hit = not hit
    return hit


def hangang_parks():
    out = []
    for f in json.load(open(os.path.join(ROOT, 'web', 'data', 'parks.geojson')))['features']:
        g = f['geometry']
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for rings in polys:
            rings = [[tuple(p) for p in r] for r in rings]
            out.append((f['properties']['name'], rings))
    return out


def tags(e):
    return e.get('tags', {})


def pos(e):
    return (e['lon'], e['lat']) if 'lon' in e else (e['center']['lon'], e['center']['lat'])


def pools(pois, river, parks, rng):
    """템플릿이 고를 장소 후보. 값: [(lon, lat, 이름 조각)]"""
    in_hangang = lambda lon, lat: any(inside(lon, lat, r) for _, r in parks)

    def near(e, limit):
        lon, lat = pos(e)
        d, side = river.where(lon, lat)
        return d <= limit and seoul_side(lon, lat, side)

    P = {k: [] for k in ('subway', 'busstop', 'bike', 'parking', 'citypark', 'kidspark', 'riverside')}
    stations = []
    for e in pois:
        t = tags(e)
        lon, lat = pos(e)
        if t.get('railway') == 'subway_entrance':
            m = re.match(r'^\s*(\S+역)\s*(\d+)\s*번\s*출구', t.get('description:ko') or t.get('description') or t.get('name', ''))
            if m:
                stations.append((lon, lat, m.group(1)))
                if near(e, 1300):
                    P['subway'].append((lon, lat, {'station': m.group(1), 'exit': m.group(2)}))
        elif t.get('highway') == 'bus_stop' and t.get('name') and near(e, 900):
            P['busstop'].append((lon, lat, {'stop': t['name']}))
        elif t.get('amenity') == 'bicycle_rental' and '따릉이' in (t.get('brand', '') + t.get('network', '')) \
                and t.get('name') and near(e, 1300):
            P['bike'].append((lon, lat, {'name': t['name']}))
        elif t.get('amenity') == 'parking' and '한강' not in t.get('name', '') and near(e, 1700) \
                and not in_hangang(lon, lat):
            P['parking'].append((lon, lat, {}))
        elif t.get('leisure') in ('park', 'playground') and t.get('name'):
            name, flat = t['name'], t['name'].replace(' ', '')
            if re.search(r'한강|샛강|생태|습지|선유도|유원지|서래섬|노들|밤섬|캠핑', name) or in_hangang(lon, lat):
                continue
            # 도시공원으로 볼 수 있는 이름만: 도시공원 종류 이름으로 끝나거나 잘 알려진 큰 공원(아파트 단지 안 공원 등은 뺌)
            if '어린이공원' in flat:
                if near(e, 1600):
                    P['kidspark'].append((lon, lat, {'park': name}))
            elif t.get('leisure') == 'park' and near(e, 1800) and (
                    re.search(r'(근린공원|소공원|문화공원|역사공원|체육공원)$', flat) or flat in CITY_PARKS):
                P['citypark'].append((lon, lat, {'park': name}))

    # 주차장 이름표: 가장 가까운 지하철역 이름만 빌린다(실제 주차장 이름·운영 주체는 쓰지 않음)
    for lon, lat, extra in P['parking']:
        extra['station'] = min(stations, key=lambda s: meters((lon, lat), s[:2]))[2]

    # 한강공원 안: 면적에 비례하게 고르게 뿌린 점
    for name, rings in parks:
        lons = [p[0] for p in rings[0]]
        lats = [p[1] for p in rings[0]]
        area = (max(lons) - min(lons)) * KX * (max(lats) - min(lats)) * KY
        for _ in range(int(area / 25000)):
            lon, lat = rng.uniform(min(lons), max(lons)), rng.uniform(min(lats), max(lats))
            d, side = river.where(lon, lat)
            if inside(lon, lat, rings) and seoul_side(lon, lat, side):
                P['riverside'].append((lon, lat, {'park': name}))
    return P


# 템플릿마다: (몇 건, 후보, 장소 이름, 신고 문장들, 출처 무게)
PLAN = {
    'smoke-subway': (9, 'subway', '{station} {exit}번 출구', [
        '{station} {exit}번 출구 앞에서 담배 피우는 사람들이 있어요',
        '{station} 출구 바로 옆에서 담배를 피우는 분이 계세요',
        '{station} {exit}번 출구 계단 앞이 담배 연기로 가득해요',
        '불꽃 보러 가는 길인데 {station} 출구 앞에서 담배를 피워요'], {'시민 신고': 6, '현장 보고': 4}),
    'smoke-riverpath': (6, 'riverside', '{park} 강변 산책로', [
        '강변 산책로를 걸으며 담배 피우는 사람이 있어요',
        '{park} 산책길 의자에서 담배를 피워요',
        '{park} 강변길에서 여럿이 모여 담배를 피워요',
        '강가 계단에 앉아 담배 피우는 사람이 있어요',
        '산책로에서 담배 연기 때문에 아이들이 힘들어해요'], {'시민 신고': 6, '현장 보고': 4}),
    'smoke-busstop': (3, 'busstop', '{stop} 버스정류소', [
        '{stop} 정류소에서 담배 피우는 사람이 있어요',
        '버스 기다리는 줄 바로 옆에서 담배를 피워요'], {'시민 신고': 7, '현장 보고': 3}),
    'smoke-park': (3, 'citypark', '{park}', [
        '{park} 안에서 담배 피우는 사람이 있어요',
        '{park} 놀이터 근처에서 담배를 피워요'], {'시민 신고': 7, '현장 보고': 3}),
    'bike-kickboard': (7, 'bike', '따릉이 대여소({name})', [
        '따릉이 대여소에 공유 킥보드가 쓰러져 있어요',
        '{name} 대여소 거치대를 공유 킥보드가 막고 있어요',
        '대여소 앞에 공유 자전거랑 킥보드가 뒤엉켜 있어요'], {'현장 보고': 6, '시민 신고': 4}),
    'bike-drunk': (5, 'bike', '따릉이 대여소({name})', [
        '술 마신 분이 따릉이를 타려고 해요',
        '맥주 마신 일행이 따릉이를 빌리고 있어요',
        '{name} 대여소에서 취한 분이 자전거를 꺼내요'], {'현장 보고': 8, '시민 신고': 2}),
    'bike-abandoned': (5, 'riverside', '{park} 자전거길 옆', [
        '자전거길 옆에 바퀴 빠진 자전거가 몇 주째 그대로 있어요',
        '{park} 나무에 묶인 자전거가 오래 놓여 있어요',
        '자전거길 옆에 주인 없는 자전거가 쓰러져 있어요',
        '산책로 난간에 녹슨 자전거가 묶인 채 오래 있어요',
        '의자 옆에 버려진 듯한 자전거가 있어요'], {'시민 신고': 8, '현장 보고': 2}),
    'bike-pedestrian': (5, 'riverside', '{park} 산책로', [
        '사람 많은 산책로에서 자전거가 너무 빨리 달려요',
        '{park} 인파 사이로 자전거가 지나가서 위험해요',
        '불꽃 보러 온 사람들 사이로 자전거가 계속 지나가요',
        '자전거가 벨을 울리며 사람들 사이를 빠르게 지나가요',
        '산책로에서 자전거 때문에 아이가 넘어질 뻔했어요'], {'시민 신고': 6, '현장 보고': 4}),
    'animal-leash': (10, 'riverside+citypark', '{park}', [
        '목줄 없이 뛰어다니는 큰 개가 있어요',
        '{park}에서 반려견 목줄을 풀어 놓고 있어요',
        '아이들 사이로 목줄 없는 개가 다녀요',
        '돗자리 사이를 목줄 없는 강아지가 뛰어다녀요',
        '목줄 없는 개가 사람들한테 달려들어요'], {'시민 신고': 6, '현장 보고': 4}),
    'animal-waste': (7, 'riverside+citypark', '{park}', [
        '산책로에 반려견 배변을 안 치우고 갔어요',
        '{park} 풀밭에 반려견 배설물이 그대로 있어요',
        '반려견 배설물을 치우지 않고 그냥 가요',
        '의자 앞에 반려견 배설물이 있어요',
        '강아지 배변을 그냥 두고 가는 걸 봤어요'], {'시민 신고': 8, '현장 보고': 2}),
    'parking-dadungi': (3, 'parking', '{station} 근처 시 공영주차장(예시)', [
        '{station} 근처 시 공영주차장도 다둥이 행복카드로 할인돼요?',
        '다둥이 카드가 있으면 시 공영주차장 요금이 얼마나 빠져요?'], {'120 문의': 1}),
    'parking-disabled': (3, 'parking', '{station} 근처 시 공영주차장(예시)', [
        '장애인 차량은 시 공영주차장 요금이 할인돼요?',
        '장애인 부모님을 모시고 왔는데 시 공영주차장 할인받을 수 있어요?'], {'120 문의': 1}),
    'parking-ev': (3, 'parking', '{station} 근처 시 공영주차장(예시)', [
        '전기차 충전하는 동안에도 시 공영주차장 요금이 나와요?',
        '{station} 근처 시 공영주차장에서 전기차 충전하면 주차비가 어떻게 돼요?'], {'120 문의': 1}),
    'parking-pregnant': (2, 'parking', '{station} 근처 시 공영주차장(예시)', [
        '임산부가 타고 있는데 시 공영주차장 할인돼요?',
        '임산부 앱카드가 있으면 시 공영주차장 요금이 빠져요?'], {'120 문의': 1}),
    'parking-compact': (2, 'parking', '{station} 근처 시 공영주차장(예시)', [
        '경차는 시 공영주차장 요금이 할인돼요?',
        '하이브리드 차도 시 공영주차장 할인이 돼요?'], {'120 문의': 1}),
    'park-vendor': (5, 'citypark', '{park}', [
        '{park} 안에서 돗자리 깔고 음식을 파는 사람이 있어요',
        '{park} 산책로에서 노점이 음료를 팔아요',
        '{park} 입구 안쪽에 간이 매대가 생겼어요'], {'현장 보고': 6, '시민 신고': 4}),
    'park-signage': (2, 'citypark', '{park} 입구', [
        '{park} 입구에 금지행위 안내판이 안 보여요',
        '{park} 입구 안내판이 쓰러져 있어요'], {'시민 신고': 1}),
    'park-pet': (3, 'citypark', '{park}', [
        '{park} 화장실 앞에 반려견을 묶어 둘 곳이 없어요',
        '{park} 매점 앞에 개를 잠깐 둘 곳이 있으면 좋겠어요'], {'시민 신고': 1}),
    'park-drink-kids': (3, 'kidspark', '{park}', [
        '{park}에서 어른들이 술을 마시고 있어요',
        '{park} 놀이터 옆에서 술판이 벌어졌어요'], {'시민 신고': 6, '현장 보고': 4}),
    'youth-center': (9, 'riverside', '{park}', [
        '축제 단기 일을 하러 온 청년이 서울시 청년 일자리 지원은 어디서 묻냐고 해요',
        '청년 월세 지원 상담은 어디서 받아요?',
        '자원봉사 온 대학생이 서울시 청년 정책 정보를 어디서 보냐고 물어요',
        '청년 취업 상담 받을 곳을 찾는 분이 있어요',
        '서울시 청년 지원 사업을 한곳에서 물어볼 수 있는 데가 있어요?',
        '공연 스태프로 온 청년이 청년 지원 정보를 어디서 받냐고 해요'], {'현장 문의': 6, '120 문의': 4}),
}


def make_background(templates, core, pois, rng, citizen):
    river = River(json.load(open(os.path.join(ROOT, 'web', 'data', 'bridge_labels.geojson')))['features'])
    parks = hangang_parks()
    P = pools(pois, river, parks, rng)
    P['riverside+citypark'] = P['riverside'] + P['citypark'] * 6   # 도시공원 몫을 조금 키움
    placed = [(it['lng'], it['lat']) for it in core]
    out, nid, said = [], 100, set()
    for key, (count, pool, place, texts, srcs) in PLAN.items():
        assert key in templates, key
        cand = list(P[pool])
        assert len(cand) >= count * 2, (key, pool, len(cand))
        weight = lambda c: 1 + 5 * math.exp(-(meters(c[:2], YEOUIDO) / 1800) ** 2)
        order = list(texts)
        rng.shuffle(order)                                       # 같은 문장이 붙어 나오지 않게 섞어서 돌림
        for k in range(count):
            ok = [c for c in cand if all(meters(c[:2], q) >= SPACING for q in placed)]
            lon, lat, extra = rng.choices(ok, weights=[weight(c) for c in ok])[0]
            cand.remove((lon, lat, extra))
            placed.append((lon, lat))
            # 같은 곳에 같은 문장이 두 번 오지 않게 다음 문장으로 넘김
            text = order[k % len(order)].format(**extra)
            for j in range(len(order)):
                t = order[(k + j) % len(order)].format(**extra)
                if (t, place.format(**extra)) not in said:
                    text = t
                    break
            said.add((text, place.format(**extra)))
            src = rng.choices(list(srcs), weights=list(srcs.values()))[0]
            sec = int(125 + 1670 * rng.random() ** 0.85)       # 축제 시간이 갈수록 조금 더 몰림. 19:02 시민 신고(1번)보다 늦게
            nid += 1
            item = {'id': nid, 'tpl': key, 'text': text,
                    'time': f'19:{sec // 60:02d}', 'sec': sec, 'src': src,
                    'place': place.format(**extra), 'lng': round(lon, 6), 'lat': round(lat, 6)}
            if src == '시민 신고':
                item['citizen'] = citizen   # A-01 판정 카드의 「신고한 시민」 줄
            out.append(item)

    # 스스로 점검: 서울 쪽, 간격, 몫
    for it in out:
        d, side = river.where(it['lng'], it['lat'])
        assert seoul_side(it['lng'], it['lat'], side), it
        assert '{' not in it['text'] + it['place'], it
    pts = [(i['lng'], i['lat']) for i in core + out]
    assert all(meters(pts[j], q) >= SPACING for j in range(len(core), len(pts)) for q in pts[:j]), 'spacing'
    assert len(out) == sum(v[0] for v in PLAN.values())
    return out
