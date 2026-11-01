"""docs/content/*.md(화면 문구 원본)를 읽는다. 읽는 규칙은 docs/content/A-01_상황판.md 맨 위 블록.

parse()는 파일 하나를 {title, lead, items, smalls, tables, notes, sections}로 나눈다. sections는 `##` 구역마다 같은 꼴이다.
cards()는 판정 카드 구역(`## 판정 카드 …`)을 카드 하나씩 돌려준다. 표준 라이브러리만 쓴다.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # 레포 맨 위
CONTENT = os.path.join(ROOT, 'docs', 'content')


def _block(name=None):
    return {'name': name, 'lead': None, 'items': [], 'smalls': [], 'tables': [], 'notes': []}


def _item(text):
    kind, _, rest = text.partition(': ')
    if kind in ('버튼', '칩', '보기', '고르기', '입력'):
        return {'kind': kind, 'text': rest, 'parts': rest.split(' · ')}
    return {'kind': '', 'text': text, 'parts': text.split(' · ')}


def parse(name):
    doc = _block()
    doc['title'], doc['sections'] = None, {}
    cur, in_note, table = doc, False, None
    with open(os.path.join(CONTENT, name + '.md'), encoding='utf-8') as f:
        lines = f.read().split('\n')
    for line in lines:
        s = line.strip()
        if not s:
            in_note, table = False, None
        elif s.startswith('> [!note]'):
            in_note = True
            cur['notes'].append(s[len('> [!note]'):].strip())
        elif in_note and s.startswith('>'):
            cur['notes'][-1] += '\n' + s[1:].strip()
        elif s.startswith('# '):
            doc['title'] = s[2:].strip()
        elif s.startswith('## '):
            cur = doc['sections'][s[3:].strip()] = _block(s[3:].strip())
        elif s.startswith('> '):
            if cur['lead'] is None:
                cur['lead'] = s[2:].strip()
        elif s.startswith('- '):
            cur['items'].append(_item(s[2:].strip()))
        elif re.fullmatch(r'\*[^*].*\*', s):
            cur['smalls'].append(s[1:-1])
        elif s.startswith('|'):
            cells = [c.strip() for c in s.strip('|').split('|')]
            if table is None:
                table = {'head': cells, 'rows': []}
                cur['tables'].append(table)
            elif not re.fullmatch(r'[-:| ]+', s):
                table['rows'].append(cells)
    return doc


def section(doc, name):
    if name not in doc['sections']:
        raise SystemExit(f'content에 「## {name}」 구역이 없다: {doc["title"]}')
    return doc['sections'][name]


def table(block, i=0):
    if len(block['tables']) <= i:
        raise SystemExit(f'content 「{block["name"]}」 구역에 표가 없다')
    return block['tables'][i]


def situations(doc):
    """`## 상황별 안내` 표 → {상황: 보일 말}"""
    return {r[0]: r[1] for r in table(section(doc, '상황별 안내'))['rows']}


def items(block, kind):
    return [it for it in block['items'] if it['kind'] == kind]


def quoted(text):
    """「…」 안의 글자(없으면 그대로)"""
    m = re.search(r'「(.+)」', text)
    return m.group(1) if m else text


def cards(doc):
    """판정 카드 구역마다 {name, key, title, rows: [(항목, 내용)…]}. key는 메모의 「틀 이름: …」(없으면 None)."""
    out = []
    for name, b in doc['sections'].items():
        if not name.startswith('판정 카드'):
            continue
        key = next((m.group(1) for n in b['notes'] for m in [re.search(r'틀 이름: ([a-z0-9-]+)', n)] if m), None)
        out.append({'name': name, 'key': key, 'title': b['lead'], 'rows': [tuple(r[:2]) for r in table(b)['rows']]})
    return out
