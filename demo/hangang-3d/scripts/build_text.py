"""docs/content(화면 문구 원본) → web/data/text.json. 화면(app.js · index.html)은 글자를 이 파일에서만 읽는다.

content를 고친 뒤 레포 맨 위에서: python3 -I demo/hangang-3d/scripts/build_text.py
예시 값(「건강관리과」 · 「19:03」 · 전화 · 시행일)이 들어간 문장은 그 자리를 {부서} · {시각} · {전화} · {시행일}로 바꿔 꼴로 쓴다.
content 구조가 바뀌어 찾던 문장이 없으면 멈춘다(조용히 틀린 글자를 쓰지 않게).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content as C  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web', 'data', 'text.json')
EX = {'부서': '건강관리과', '시각': '19:03', '전화': '02-2133-9467', '시행일': '2026-10-01'}   # content 예시 값(첫째 일)


def form(text, *keys):
    """예시 값을 {자리}로 바꾼 꼴. 받침에 따라 붙는 「로 · 가」도 자리로 뺀다."""
    for k in keys:
        for josa in ('로', '가'):
            if EX[k] + josa in text:
                text = text.replace(EX[k] + josa, '{%s}{%s}' % (k, josa))
        if EX[k] not in text and '{%s}' % k not in text:
            raise SystemExit(f'content 문장에 예시 값 「{EX[k]}」가 없다: {text}')
        text = text.replace(EX[k], '{%s}' % k)
    return text


def strip_btn(text):
    return text.removeprefix('버튼: ')


def main():
    a01, a04, u01, u02 = (C.parse(n) for n in ('A-01_상황판', 'A-04_한강지도', 'U-01_현장휴대폰', 'U-02_시민신고'))

    # A-04 한강 3D 지도(낮)
    see, scene = C.section(a04, '지도 보기'), C.section(a04, '예시')
    listing = next(n for n in a04['sections'] if n.startswith('들어온 일'))
    marks = C.section(a04, '지도 위 글자')['items']
    mark = lambda head: C.quoted(next(it['text'] for it in marks if it['text'].startswith(head)))
    pick_bridge = C.items(see, '고르기')[0]['parts']
    t_a04 = {
        'title': a04['title'], 'lead': a04['lead'],
        'all': C.items(see, '버튼')[0]['text'], 'demo': C.items(see, '버튼')[1]['text'], 'fly': C.items(see, '버튼')[2]['text'],
        'bridge': pick_bridge[0], 'bridgePick': pick_bridge[1], 'virtual': see['smalls'][0],
        'scene': C.items(scene, '버튼')[0]['text'],
        'list': re.sub(r'\d+', '{n}', listing, count=1),
        'attrib': mark('지도 출처 표시'), 'ring': mark('「출구'),
        'mapFailed': C.situations(a04)['지도를 불러오지 못함'],
    }

    # A-01 현장 상황판(밤)
    kpi = C.table(C.section(a01, '지금까지 들어온 일'))['rows']
    flt, lst = C.section(a01, '부서별 보기'), C.section(a01, '들어온 일')
    card = next(b for n, b in a01['sections'].items() if n.startswith('판정 카드'))
    rows = C.table(card)['rows']
    approved = C.table(C.section(a01, '승인한 안내'))['rows'][0]
    sit = C.situations(a01)
    views = [it['parts'] for it in C.items(lst, '보기')]
    btn = [it['text'] for it in C.items(card, '버튼')]
    t_a01 = {
        'title': a01['title'], 'lead': a01['lead'], 'exit': C.items(a01, '버튼')[0]['text'],
        'basis': [it['text'] for it in C.section(a01, '기준')['items']],
        'kpi': [r[1].split(' · ', 1) for r in kpi], 'unit': re.sub(r'\d+', '', kpi[0][0]),
        'filter': flt['name'], 'filterLead': flt['lead'], 'all': C.items(flt, '칩')[0]['parts'][0],
        'play': C.items(flt, '버튼')[0]['text'], 'pause': strip_btn(sit['재생 중']), 'playNote': flt['smalls'][0],
        'list': lst['name'], 'listLead': lst['lead'], 'views': views, 'open': views[1][1], 'done': views[1][2],
        'openBtn': strip_btn(C.table(lst)['rows'][0][-1]),
        'labels': {'draft': rows[0][0], 'verdict': rows[1][0], 'basis': rows[2][0], 'effective': rows[3][0],
                   'dept': rows[5][0], 'citizen': rows[6][0]},
        'approve': btn[0], 'law': btn[1], 'close': btn[2],
        'approvedTitle': C.section(a01, '승인한 안내')['name'], 'approved1': approved[2], 'staff': form(approved[1], '부서'),
        'footNote': C.section(a01, '한눈에')['smalls'][0],
    }
    say = {'loading': sit['불러오는 중'], 'empty': sit['들어온 일 없음'], 'deptEmpty': sit['「부서별 보기」에서 그 부서 일이 없음'],
           'sent': form(sit['맡은 부서로 보냄'], '부서'), 'failed': sit['불러오지 못함'], 'approved': sit['안내를 승인함'],
           'doneEmpty': sit['「해결」로 거른 결과 없음'], 'openEmpty': sit['「미해결」로 거른 결과 없음'],
           'sending': C.situations(u02)['보내는 중']}

    # U-02 시민 신고 → U-01 현장 휴대폰(왼쪽 휴대폰 틀)
    ask, after = C.section(u02, '무엇을 봤나요'), C.section(u02, '보낸 뒤')
    inputs = [it['parts'] for it in C.items(ask, '입력')]
    sent = dict(C.table(after)['rows'])
    got = C.section(u01, '받은 안내')
    recv = dict(C.table(got)['rows'])
    t_u02 = {
        'title': u02['title'], 'lead': u02['lead'], 'section': ask['name'], 'fields': [p[0] for p in inputs],
        'send': C.items(ask, '버튼')[0]['text'], 'hint': ask['smalls'][0],
        'after': after['name'], 'afterLead': after['lead'], 'labels': [r[0] for r in C.table(after)['rows']],
        'foot': after['smalls'][0],
        # 발표 때 칸에 미리 들어 있는 값(고정 입력): 보낸 것 · 받은 안내의 장소 · 연락처 칸 예시
        'fixed': {'what': C.quoted(sent['보낸 것']), 'where': recv['장소'], 'phone': inputs[2][1].removeprefix('예: ')},
    }
    t_u01 = {
        'title': u01['title'], 'lead': u01['lead'], 'new': C.situations(u01)['새 안내가 옴'], 'section': got['name'],
        'boxHead': form(got['lead'], '부서'),
        'labels': dict(zip(('draft', 'place', 'basis', 'approval', 'citizen'), [r[0] for r in C.table(got)['rows']])),
        'basisFmt': form(recv['근거'].rsplit(' · ', 1)[1], '시행일'),
        'approvalFmt': form(recv['승인'], '부서', '시각', '전화'),
    }
    data = {'a04': t_a04, 'a01': t_a01, 'say': say, 'u02': t_u02, 'u01': t_u01}
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write('\n')
    os.replace(tmp, OUT)
    print(f'화면 글자 → {OUT}')


if __name__ == '__main__':
    main()
