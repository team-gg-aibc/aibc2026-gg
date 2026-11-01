"""한강 민원 예시 데이터 → web/data/complaints.json (표준 라이브러리만, 같은 입력이면 같은 결과)

- 들어온 일 1~7(core)은 vault content/A-01_상황판.md의 일곱 건 그대로다.
- 나머지는 템플릿(조례 근거를 eval/source 원문에서 확인한 판정 카드)마다 장소·문장만 바꿔 만든 가상 예시다.
- 장소는 OSM(© OpenStreetMap contributors)의 지하철 출입구·버스정류장·자전거 대여소·주차장·공원에서 고른다.
실행: python3 -I scripts/make_complaints.py
"""
import json
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'web', 'data', 'complaints.json')
POIS = os.path.join(ROOT, 'data', 'overpass', 'pois.json')

SMOKE = 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171803'
BIKE = 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171767'
ANIMAL = 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171829'
PARKING = 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171833'
PARK = 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2147709'
YOUTH = 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2054497'

SMOKE_LAW = '서울특별시 금연환경 조성 및 간접흡연 피해방지조례'
BIKE_LAW = '서울특별시 자전거이용 활성화에 관한 조례'
PARKING_LAW = '서울특별시 주차장 설치 및 관리 조례'
PARK_LAW = '서울특별시 도시공원 조례'
MAY_DESIGNATE = '지정할 수 있는 곳이에요. 실제 지정 여부는 서울특별시보 고시를 확인해 주세요.'
ONE_DISCOUNT = '감면 사유가 둘 이상이면 감면율이 높은 하나만 적용해요(제7조 제3항)'

# 부서 이름·전화: 국가법령정보 자치법규 「담당부서명」·「전화번호」(2026-10-01 시행본, 11-01 조회, content 파일과 같음)
TYPES = [
    {'key': '금연', 'short': '금연', 'dept': '건강관리과', 'phone': '02-2133-9467'},
    {'key': '자전거', 'short': '자전거', 'dept': '자전거PM과', 'phone': '02-2133-2413'},
    {'key': '동물보호', 'short': '동물', 'dept': '동물보호과', 'phone': '02-2133-7649'},
    {'key': '주차장', 'short': '주차', 'dept': '주차계획과', 'phone': '02-2133-2353'},
    {'key': '도시공원', 'short': '공원', 'dept': '정원도시정책과', 'phone': '02-2133-2047'},
    {'key': '청년', 'short': '청년', 'dept': '청년정책담당관', 'phone': '02-2133-6581'},
]


def tpl(type_, title, draft, verdict, basis, effective, law, extra='—', extra_label='추가 확인'):
    return {'type': type_, 'title': title, 'draft': draft, 'verdict': verdict, 'basis': basis,
            'effective': effective, 'extra_label': extra_label, 'extra': extra, 'law': law}


# 판정 카드 템플릿. 근거 문장은 팀 레포 eval/source/*.md(시행본 원문)에서 그대로 옮겼다.
TEMPLATES = {
    # ── 금연 (core 1은 content 파일 그대로)
    'smoke-subway': tpl(
        '금연', '출구에서 10m 안은 금연구역이에요.',
        '「지하철역 출구에서 10m 안은 금연구역이에요. 출구에서 떨어진 곳으로 옮겨 달라고 안내해 주세요.」',
        '예 · 금연구역',
        f'{SMOKE_LAW} 제5조 제1항 제9호 「시 관할 구역의 지하철역 출입구로부터 10m 이내」',
        '2026-10-01', SMOKE,
        extra='2016년 5월부터 서울시 관내 모든 지하철역 출입구 10m가 금연구역이에요(서울시 금연구역 안내)', extra_label='지정'),
    'smoke-riverpath': tpl(
        '금연', '강변 보행자길은 금연구역으로 지정할 수 있는 곳이에요.',
        '「하천 옆 보행자길은 시가 금연구역으로 지정할 수 있는 곳이에요. 지정 여부를 확인한 뒤, 산책로에서는 담배를 피우지 말아 달라고 안내해 주세요.」',
        '확인 필요 · 지정 대상',
        f'{SMOKE_LAW} 제5조 제1항 제2호 「하천(「하천법」에 따른 하천을 말한다) 연변의 보행자길」',
        '2026-10-01', SMOKE, extra=MAY_DESIGNATE),
    'smoke-busstop': tpl(
        '금연', '버스정류소는 금연구역으로 지정할 수 있는 곳이에요.',
        '「버스정류소는 시가 금연구역으로 지정할 수 있는 곳이에요. 지정 여부를 확인한 뒤, 정류소에서 떨어진 곳으로 옮겨 달라고 안내해 주세요.」',
        '확인 필요 · 지정 대상',
        f'{SMOKE_LAW} 제5조 제1항 제7호 「「여객자동차 운수사업법 시행규칙」에 따른 시 관할 구역의 버스정류소 및 택시 승차대」',
        '2026-10-01', SMOKE, extra=MAY_DESIGNATE),
    'smoke-park': tpl(
        '금연', '도시공원은 금연구역으로 지정할 수 있는 곳이에요.',
        '「도시공원은 시가 금연구역으로 지정할 수 있는 곳이에요. 지정 여부를 확인한 뒤, 공원 안에서는 담배를 피우지 말아 달라고 안내해 주세요.」',
        '확인 필요 · 지정 대상',
        f'{SMOKE_LAW} 제5조 제1항 제1호 「도시공원(「도시공원 및 녹지 등에 관한 법률」에 따른 도시 공원을 말한다)」',
        '2026-10-01', SMOKE, extra=MAY_DESIGNATE),
    # ── 자전거 (core 2·6은 content 파일 그대로)
    'bike-kickboard': tpl(
        '자전거', '시가 정리해야 하는 일이에요.',
        '「대여소 앞 공유 킥보드를 옆으로 옮기고, 반납하려는 분께 가까운 대여소를 안내해 주세요.」',
        '예 · 시가 정리할 일',
        f'{BIKE_LAW} 제12조의2 제7항 「시장은 공공자전거 주차구역의 질서 유지를 위하여, 민간 공유자전거, 개인형 이동장치 및 일반자전거 등이 해당 구역에 무단으로 주차되지 않도록 필요한 조치를 마련하여야 한다.」 · 제8항(안내판 설치, 앱 안내, 현장 계도 활동)',
        '2026-10-01', BIKE),
    'bike-drunk': tpl(
        '자전거', '술을 마셨다면 따릉이를 타지 않도록 안내해 주세요.',
        '「술을 드셨다면 따릉이 대신 대중교통을 이용해 주세요.」(안내 방송)',
        '예 · 타지 않도록 안내',
        f'{BIKE_LAW} 제4조 제5항 「자전거를 이용하는 시민은 음주 및 약물의 영향으로 인하여 정상적으로 운전하지 못할 우려가 있는 상태에서 자전거를 운행하지 않도록 하여야 한다.」 · 제3조 제4항(시장의 음주 운행 방지 홍보 · 교육 · 캠페인)',
        '2026-10-01', BIKE),
    'bike-abandoned': tpl(
        '자전거', '자전거는 자전거주차장이나 보관소에 세워야 해요.',
        '「자전거는 자전거주차장이나 보관소에 세워 달라고 안내해 주세요. 주인 없이 오래 놓인 자전거는 구청에 알려 주세요.」',
        '예 · 방치 자전거 확인',
        f'{BIKE_LAW} 제4조 제3항 「자전거를 이용하는 시민은 자전거를 자전거주차장이나 자전거보관소 이외의 장소에 자전거를 무단방치하지 않도록 해야 한다.」 · 제3조 제5항(무단방치자전거의 처분은 자치구청장 업무)',
        '2026-10-01', BIKE),
    'bike-pedestrian': tpl(
        '자전거', '보행자를 먼저 살피며 달려 달라고 안내해 주세요.',
        '「사람이 많은 길에서는 보행자를 먼저 살피며 천천히 달려 주세요.」(안내 방송)',
        '예 · 보행자 주의 안내',
        f'{BIKE_LAW} 제4조 제2항 「자전거를 이용하는 시민은 도로교통에 관한 법령을 준수하여 보행자에게 위해를 주는 일이 없도록 보행자에 주의하면서 운전하여야 하며, 안전사고 예방을 위해 이용시설여건에 따라 자전거 운전시 안전장비를 구비하여야 한다.」',
        '2026-10-01', BIKE),
    # ── 동물보호 (core 4는 content 파일 그대로)
    'animal-leash': tpl(
        '동물보호', '목줄을 해 달라고 안내해 주세요.',
        '「사람이 많은 곳이라 반려견에게 목줄을 해 주세요.」',
        '예 · 목줄 안내',
        '서울특별시 동물보호 조례 제7조 제3항 「소유자등은 등록대상동물을 동반하고 외출할 때에는 다음 각 호의 사항을 준수하여야 한다.」 제1호 「…목줄 착용 등 사람 또는 동물에 대한 위해를 예방하기 위한 안전조치를 할 것」',
        '2026-10-01', ANIMAL),
    'animal-waste': tpl(
        '동물보호', '배설물은 바로 치워 달라고 안내해 주세요.',
        '「반려견 배설물은 바로 수거해 주세요.」',
        '예 · 배설물 수거 안내',
        '서울특별시 동물보호 조례 제7조 제3항 제3호 「배설물(소변의 경우에는 공동주택의 엘리베이터ㆍ계단 등 건물 내부의 공용공간 및 평상ㆍ의자 등 사람이 눕거나 앉을 수 있는 기구 위의 것으로 한정한다)이 생겼을 때에는 즉시 수거할 것」',
        '2026-10-01', ANIMAL),
    # ── 주차장 (core 3은 content 파일 그대로). 한강공원 주차장은 다른 조례(6종 밖)라 시 공영주차장만 쓴다
    'parking-dadungi': tpl(
        '주차장', '다둥이 행복카드가 있으면 시 공영주차장 요금이 50% 할인돼요.',
        '「다둥이 행복카드를 보여 주시면 서울시 공영주차장 요금을 50% 할인받을 수 있어요.」',
        '예 · 할인 대상(50%)',
        f'{PARKING_LAW} 제7조 제1항 제7호 「「다둥이 행복카드」 소지자에 대하여 주차요금의 100분의 50을 할인한다.」',
        '2026-10-01', PARKING, extra=ONE_DISCOUNT),
    'parking-disabled': tpl(
        '주차장', '장애인이 탄 차는 시 공영주차장 요금이 80% 할인돼요.',
        '「장애인자동차표지를 붙이고 장애인이 함께 탄 차는, 장애인등록증을 보여 주시면 서울시 공영주차장 요금을 80% 할인받을 수 있어요.」',
        '예 · 할인 대상(80%)',
        f'{PARKING_LAW} 제7조 제1항 제1호 「다음의 장애인 및 국가유공자 등이 사용하는 자동차에 대하여는 주차요금의 100분의 80을 할인한다.」 가목(장애인자동차표지 부착 · 장애인 탑승 · 장애인등록증 제시)',
        '2026-10-01', PARKING, extra=ONE_DISCOUNT),
    'parking-ev': tpl(
        '주차장', '전기차는 충전하는 동안 1시간까지 주차요금이 면제돼요.',
        '「전기차를 충전하시면 서울시 공영주차장 요금이 1시간까지 면제되고, 그 뒤 요금은 50% 할인돼요.」',
        '예 · 충전 1시간 면제',
        f'{PARKING_LAW} 제7조 제1항 제9호 「「환경친화적 자동차의 개발 및 보급 촉진에 관한 법률」 제2조에 따른 "전기자동차"는 충전 할 경우 1시간 범위 내에서 주차요금을 면제하고 1시간 초과 시부터 부과되는 주차요금의 100분의 50을 할인한다.」',
        '2026-10-01', PARKING, extra=ONE_DISCOUNT),
    'parking-pregnant': tpl(
        '주차장', '임산부가 탄 차는 시 공영주차장 요금이 50% 할인돼요.',
        '「임산부 앱카드처럼 임산부임을 보여 주시면 서울시 공영주차장 요금을 50% 할인받을 수 있어요.」',
        '예 · 할인 대상(50%)',
        f'{PARKING_LAW} 제7조 제1항 제7의3호 「「서울특별시 임산부 예우 및 지원에 관한 조례」에 따른 임산부가 탑승한 차량으로 임산부 앱카드 등 임산부임을 증명할 수 있는 서류를 제시한 경우 주차요금의 100분의 50을 할인한다.」',
        '2026-10-01', PARKING, extra=ONE_DISCOUNT),
    'parking-compact': tpl(
        '주차장', '경차 · 저공해차는 시 공영주차장 요금을 50% 할인할 수 있어요.',
        '「경차 · 저공해차는 서울시 공영주차장 요금을 50% 할인받을 수 있는 대상이에요. 이 주차장에서 할인하는지 확인한 뒤 안내해 주세요.」',
        '확인 필요 · 할인할 수 있음(50%)',
        f'{PARKING_LAW} 제7조 제1항 제2호 「시장은 「자동차관리법」 제3조 및 같은 법 시행규칙 제2조에 따른 경형자동차와 「대기환경보전법」 제2조제16호 및 같은 법 시행령 제1조의2에 따른 저공해자동차에 대하여 주차요금의 100분의 50을 할인할 수 있다.」',
        '2026-10-01', PARKING, extra='조례가 「할인할 수 있다」고 정해요. 이 주차장에서 할인하는지 확인해 주세요'),
    # ── 도시공원 (core 5는 content 파일 그대로). 한강공원은 도시공원이 아니라(6종 밖) 도시공원 안에만 둔다
    'park-vendor': tpl(
        '도시공원', '공원 안 장사는 허용받은 행사 부스만 할 수 있어요.',
        '「여의도공원 안에서는 공원관리청이 허용한 행사 부스만 음식을 팔 수 있어요. 허용받은 부스인지 확인해 주세요.」',
        '예 · 허용 행사만 가능',
        f'{PARK_LAW} 제22조 제1항 「누구든지 법 제2조제3호에 해당하는 도시공원에서 법 제49조제1항 및 제2항 각 호의 행위를 하여서는 아니된다.」 · 제2항(공원관리청이 공익에 부합한다고 판단하여 허용한 행사의 상행위는 허용할 수 있음)',
        '2026-07-13', PARK, extra='그 노점이 허용받은 행사 부스인지는 공원관리청 허가 내역으로 확인해 주세요'),
    'park-signage': tpl(
        '도시공원', '도시공원 입구에는 금지행위 안내표지를 두어야 해요.',
        '「공원 입구의 금지행위 안내표지가 잘 보이는지 확인하고, 없으면 설치를 요청해 주세요.」',
        '예 · 안내표지 설치 대상',
        f'{PARK_LAW} 제22조의2 제1항 「시장은 법 제49조제1항 및 제2항에 따라 금지행위가 적용되는 도시공원 입구에 안내표지를 설치하여야 한다.」',
        '2026-07-13', PARK),
    'park-pet': tpl(
        '도시공원', '공원 화장실 · 매점 앞 반려동물 공간은 시가 마련하도록 노력할 일이에요.',
        '「화장실 · 매점 앞에 반려견 목줄을 걸어 둘 곳이 필요하다는 의견을 공원 관리 쪽에 전해 주세요.」',
        '예 · 시가 노력할 일',
        f'{PARK_LAW} 제22조의2 제2항 「시장은 반려동물 안전사고 예방 및 시민의 이용 편의성을 보장하기위해 공원 내 화장실, 매점 등에 반려동물의 목줄 등을 걸어두거나 반려동물이 따로 머무를 수 있는 공간을 설치하도록 노력하여야 한다.」',
        '2026-07-13', PARK, extra='시민의 이동과 안전에 지장이 없는 곳이어야 해요(같은 항 단서)'),
    'park-drink-kids': tpl(
        '도시공원', '어린이공원은 금주구역으로 지정할 수 있는 곳이에요.',
        '「어린이공원은 시가 금주구역으로 지정할 수 있는 곳이에요. 지정 여부를 확인한 뒤, 술은 공원 밖에서 마셔 달라고 안내해 주세요.」',
        '확인 필요 · 지정 대상',
        f'{PARK_LAW} 제22조의3 「시장은 「국민건강증진법」제8조의4에 따라 법 제15조제1항제2호나목에 따른 어린이공원을 금주구역으로 지정할 수 있다.」',
        '2026-07-13', PARK, extra=MAY_DESIGNATE),
    # ── 청년 (core 7은 content 파일 그대로)
    'youth-center': tpl(
        '청년', '서울시 청년 지원 상담은 서울청년센터에서 받을 수 있어요.',
        '「서울시 청년 지원 정보와 상담은 서울청년센터에서 받을 수 있어요. 가까운 서울청년센터를 안내해 주세요.」',
        '예 · 서울청년센터 안내',
        '서울특별시 청년 기본 조례 제20조 제3항 제1호 「청년지원정보 집적ㆍ제공 및 분야별 종합상담 사업」(자치구별 서울청년센터의 기능) · 제20조 제1항(서울광역청년센터 · 자치구별 서울청년센터)',
        '2025-07-14', YOUTH, extra='가까운 서울청년센터 위치는 서울청년센터 안내에서 확인해 주세요'),
}

CITIZEN = '010-0000-0000(가상) · 필요할 때만 연락'

# content/A-01_상황판.md 「들어온 일」 일곱 건과 지도 핀(pins.geojson) 자리·칩 위치
CORE = [
    (1, 'smoke-subway', '여의나루역 출구 앞에서 담배 피우는 사람이 많아요', '19:02', '시민 신고', '여의나루역 출구'),
    (2, 'bike-kickboard', '따릉이 대여소에 공유 킥보드가 잔뜩 세워져 반납을 못 한대요', '19:06', '현장 보고', '따릉이 대여소'),
    (3, 'parking-dadungi', '축제 보고 가는 길에 시 공영주차장도 다둥이 행복카드로 할인돼요?', '19:09', '120 문의', '공영주차장(예시)'),
    (4, 'animal-leash', '목줄 없이 다니는 반려견이 있어요', '19:13', '현장 보고', '강변 산책로'),
    (5, 'park-vendor', '여의도공원 안에서 음식을 파는 노점이 보여요', '19:17', '현장 보고', '여의도공원'),
    (6, 'bike-drunk', '술 마신 분들이 따릉이를 빌리려 해요', '19:24', '현장 보고', '따릉이 대여소'),
    (7, 'youth-center', '자원봉사 온 청년이 서울시 청년 지원은 어디서 물어보냐고 해요', '19:28', '현장 문의', '안내센터'),
]


def core_items():
    pins = json.load(open(os.path.join(ROOT, 'web', 'data', 'pins.geojson')))
    at = {f['properties']['id']: f for f in pins['features'] if f['geometry']['type'] == 'Point'}
    out = []
    for n, key, text, hhmm, src, place in CORE:
        p = at[n]
        lng, lat = p['geometry']['coordinates']
        h, m = map(int, hhmm.split(':'))
        item = {'id': n, 'n': n, 'tpl': key, 'text': text, 'time': hhmm, 'sec': (h - 19) * 3600 + m * 60,
                'src': src, 'place': place, 'lng': lng, 'lat': lat,
                'dx': p['properties']['dx'], 'dy': p['properties']['dy']}
        if src == '시민 신고':
            item['citizen'] = CITIZEN
        out.append(item)
    return out


def main():
    items = core_items()
    if os.path.exists(POIS):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from background import make_background   # 장소 고르기는 따로(POI 받은 뒤)
        items += make_background(TEMPLATES, items, json.load(open(POIS)), random.Random(20261101))
    items.sort(key=lambda it: (it['sec'], it['id']))
    for it in items:
        assert it['tpl'] in TEMPLATES, it
        assert 0 <= it['sec'] < 1800, it
    # 번호 = 들어온 순서(동규 11-01). 해결 = 맡은 부서가 안내를 승인한 시각(초), 19:30 안에 없으면 미해결.
    # 배경 일의 70%를 4~15분 뒤에 해결로 둔다. 핵심 7건은 발표자가 직접 승인하므로 비운다.
    done_rng = random.Random(20261102)   # 장소·문장 난수와 따로 두어 앞의 데이터가 바뀌지 않게
    for no, it in enumerate(items, 1):
        it['no'] = no
        it['done'] = None
        if not it.get('n') and done_rng.random() < 0.7:
            done = it['sec'] + 240 + int(660 * done_rng.random())
            it['done'] = done if done < 1800 else None
    assert items[0].get('n') == 1, '1번은 19:02 시민 신고여야 한다'
    keys = {t['key'] for t in TYPES}
    assert all(t['type'] in keys for t in TEMPLATES.values())
    data = {'meta': {'window': ['19:00', '19:30'], 'note': '가상 예시 · 장소는 © OpenStreetMap contributors'},
            'types': TYPES, 'templates': TEMPLATES, 'items': items}
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)   # 화면이 읽는 중에 반쯤 쓴 파일을 보지 않게
    solved = sum(it['done'] is not None for it in items)
    print(f'{len(items)}건(19:30 해결 {solved} · 미해결 {len(items) - solved}) → {OUT}')


if __name__ == '__main__':
    main()
