"""한강 민원 예시 데이터 → web/data/complaints.json (표준 라이브러리만, 같은 입력이면 같은 결과)

- 화면 문구 원본은 docs/content/다. 판정 카드 문장 · 부서 이름 · 전화 · 핵심 7건(들어온 일 1~7)은 거기서 읽는다:
  A-01_상황판.md(핵심 7건 카드 · 「들어온 일」 표 · 「부서별 보기」 칩), C-01_판정카드.md(배경 일 카드 예시 13개).
- 배경 일 95건은 카드마다 장소 · 문장만 바꿔 만든 가상 예시다(background.py). 본격적으로 만들 때는 Nemotron 페르소나로 만든다(decisions.md 11-01).
- 장소는 OSM(© OpenStreetMap contributors)의 지하철 출입구 · 버스정류장 · 자전거 대여소 · 주차장 · 공원에서 고른다.
  OSM 원본(약 13MB)은 레포에 없다. PM에게 받아 HANGANG_DATA=<그 data 폴더>로 알려 준다.
실행: HANGANG_DATA=<data 폴더> python3 -I demo/hangang-3d/scripts/make_complaints.py
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content as C  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'web', 'data', 'complaints.json')
POIS = os.path.join(os.environ.get('HANGANG_DATA', os.path.join(ROOT, 'data')), 'overpass', 'pois.json')

# 조례 원문 링크(국가법령정보 자치법규, 화면 글자가 아니라 「조례 원문 보기」가 여는 주소)
LAW = {
    '금연': 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171803',
    '자전거': 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171767',
    '동물보호': 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171829',
    '주차장': 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171833',
    '도시공원': 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2147709',
    '청년': 'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2054497',
}
# A-01 판정 카드 · 「들어온 일」 표의 순서(핵심 1~7)와 틀 이름. 배경 일 틀 이름은 C-01 카드 메모에 있다
CORE = ['smoke-subway', 'bike-kickboard', 'parking-dadungi', 'animal-leash', 'park-vendor', 'bike-drunk', 'youth-center']


def load():
    """docs/content → (부서 types, 카드 templates, 신고한 시민 줄, 핵심 7건 줄)"""
    a01 = C.parse('A-01_상황판')
    cards = C.cards(a01) + C.cards(C.parse('C-01_판정카드'))
    phone = dict(dict(c['rows'])['맡은 부서'].split(' · ') for c in cards)
    chips = [it['parts'] for it in C.items(C.section(a01, '부서별 보기'), '칩')][1:]   # 첫째는 「전체」
    types = [{'key': p[1], 'dept': p[0], 'phone': phone[p[0]]} for p in chips]
    type_of = {t['dept']: t['key'] for t in types}
    core_cards = [c for c in cards if c['key'] is None]
    assert len(core_cards) == len(CORE), 'A-01 판정 카드 수가 핵심 7건과 다르다'
    templates = {}
    for key, c in [*zip(CORE, core_cards), *[(c['key'], c) for c in cards if c['key']]]:
        r, extra = dict(c['rows']), c['rows'][4]   # 다섯째 줄이 카드마다 다른 「지정」 · 「추가 확인」
        typ = type_of[r['맡은 부서'].split(' · ')[0]]
        templates[key] = {'type': typ, 'title': c['title'], 'draft': r['안내 초안'], 'verdict': r['판정'], 'basis': r['근거'],
                          'effective': r['시행일'], 'extra_label': extra[0], 'extra': extra[1], 'law': LAW[typ]}
    t = C.table(C.section(a01, '들어온 일'))
    col = {h: i for i, h in enumerate(t['head'])}
    rows = [(C.quoted(r[col['들어온 일']]), r[col['시각']], r[col['어디서']]) for r in t['rows']]
    assert len(rows) == len(CORE), 'A-01 「들어온 일」 표가 핵심 7건과 다르다'
    return types, templates, dict(core_cards[0]['rows'])['신고한 시민'], rows


def core_items(rows, citizen):
    pins = json.load(open(os.path.join(ROOT, 'web', 'data', 'pins.geojson')))
    at = {f['properties']['id']: f for f in pins['features'] if f['geometry']['type'] == 'Point'}
    out = []
    for n, (key, (text, hhmm, src)) in enumerate(zip(CORE, rows), 1):
        p = at[n]
        lng, lat = p['geometry']['coordinates']
        h, m = map(int, hhmm.split(':'))
        item = {'id': n, 'n': n, 'tpl': key, 'text': text, 'time': hhmm, 'sec': (h - 19) * 3600 + m * 60,
                'src': src, 'place': p['properties']['name'], 'lng': lng, 'lat': lat,
                'dx': p['properties']['dx'], 'dy': p['properties']['dy']}
        if src == '시민 신고':
            item['citizen'] = citizen
        out.append(item)
    return out


def main():
    types, templates, citizen, rows = load()
    items = core_items(rows, citizen)
    if not os.path.exists(POIS):
        sys.exit(f'OSM 원본이 없어 배경 일을 만들 수 없다: {POIS}\nPM에게 data 폴더를 받아 HANGANG_DATA=<그 폴더>로 알려 준 뒤 다시 돌린다. '
                 '(문구만 바꿨으면 build_text.py만 돌리면 된다.)')
    from background import make_background   # 장소 고르기는 따로(POI 받은 뒤)
    items += make_background(templates, items, json.load(open(POIS)), random.Random(20261101), citizen)
    items.sort(key=lambda it: (it['sec'], it['id']))
    for it in items:
        assert it['tpl'] in templates, it
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
    keys = {t['key'] for t in types}
    assert all(t['type'] in keys for t in templates.values())
    data = {'meta': {'window': ['19:00', '19:30'], 'note': '가상 예시 · 장소는 © OpenStreetMap contributors'},
            'types': types, 'templates': templates, 'items': items}
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)   # 화면이 읽는 중에 반쯤 쓴 파일을 보지 않게
    solved = sum(it['done'] is not None for it in items)
    print(f'{len(items)}건(19:30 해결 {solved} · 미해결 {len(items) - solved}) → {OUT}')


if __name__ == '__main__':
    main()
