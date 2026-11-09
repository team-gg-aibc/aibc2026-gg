"""flow2 별표: Document Parse enhanced(HTML)로 다시 읽은 별표를 「머리글: 값」 줄로 펼친다 (PM 별도 실험 11-10).

왜: 킷 별표(`engine/data/annex/`, DP standard 마크다운)는 칸 안 줄바꿈이 공백으로 뭉친다. 예: 공원입장료 「어 른 1회 청소년 1회
어린이 1회」와 「3,000～6,000 2,000～4,000 1,000～2,000」이 각각 한 칸이라 어느 금액이 누구 것인지 글자 순서로 짐작해야 했다.
enhanced는 머리글 칸을 <th>로, 칸 안 줄바꿈을 <br/>로 지킨다. 코드가 칸 합치기(rowspan · colspan)를 풀고 줄을 짝지으면
Solar가 표 칸 위치를 짐작하지 않는다. 비교(DP standard · enhanced · Information Extract)와 비용은 annex/README.md.

- 원본 HTML: annex/<일련번호>_<별표>.html (DP 응답의 content.html 그대로). 부르는 코드는 레포에 두지 않는다(바깥 서비스 호출은
  engine/upstage.py 한 곳 — AGENTS.md. upstage.document_parse에 mode 칸이 없어 enhanced를 못 부른다).
- 펼치기: 위쪽의 모두 <th>인 줄 = 열 머리글(위→아래 경로). 값 줄마다 「머리글: 값 · 머리글: 값」 한 줄. 한 줄에 같은 수(2 이상)의
  줄바꿈 칸이 둘 이상이면 줄마다 나눈다. 가로로 다 차는 칸(비고 줄)은 글만 쓴다.
"""
import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

DIR = Path(__file__).resolve().parent / "annex"
_BLOCK = ("p", "h1", "h2", "h3", "h4", "header", "footer")


class _Doc(HTMLParser):
    """블록을 차례로 모은다: ("text", 글) 또는 ("table", 줄 목록). 칸 = {"th", "rs", "cs", "lines"}."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.table, self.row, self.cell, self.text = [], None, None, None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"th": tag == "th", "rs": int(a.get("rowspan") or 1), "cs": int(a.get("colspan") or 1), "t": []}
        elif tag == "br":
            (self.cell["t"] if self.cell is not None else self.text).append("\n")
        elif tag in _BLOCK and self.table is None:
            self.flush()

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            lines = (re.sub(r"\s+", " ", x).strip() for x in "".join(self.cell.pop("t")).split("\n"))
            self.cell["lines"] = [x for x in lines if x]
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.blocks.append(("table", self.table))
            self.table = None
        elif tag in _BLOCK and self.table is None:
            self.flush()

    def handle_data(self, data):
        (self.cell["t"] if self.cell is not None else self.text).append(data)

    def flush(self):
        t = re.sub(r"\s+", " ", "".join(self.text)).strip()
        if t:
            self.blocks.append(("text", t))
        self.text = []


def _grid(rows):
    """칸 합치기를 풀어 격자[줄][칸]. 합쳐진 칸은 같은 칸(dict)을 여러 자리에서 가리킨다."""
    grid, spill = [], {}
    for r, row in enumerate(rows):
        out, c, cells = [], 0, iter(row)
        while True:
            if (r, c) in spill:
                out.append(spill.pop((r, c)))
                c += 1
                continue
            cell = next(cells, None)
            if cell is None:
                break
            for dc in range(cell["cs"]):
                out.append(cell)
                for dr in range(1, cell["rs"]):
                    spill[(r + dr, c + dc)] = cell
            c += cell["cs"]
        grid.append(out)
    return grid


def _text(cell):
    return " ".join(cell["lines"])


def table_lines(rows):
    """표 하나 → 줄 목록. 머리글 줄은 열 머리글 경로가 되고, 값 줄은 「머리글: 값 · …」이 된다."""
    g = [r for r in _grid(rows) if r]
    if not g:
        return []
    head = 0
    while head < len(g) - 1 and all(x["th"] for x in g[head]):
        head += 1
    if head == 0 and len(g) > 1:          # 머리글 표시가 없으면 첫 줄을 머리글로 본다
        head = 1
    width = max(len(r) for r in g)
    cols = []
    for c in range(width):
        names = []
        for r in range(head):
            if c < len(g[r]) and _text(g[r][c]) and (not names or names[-1] != _text(g[r][c])):
                names.append(_text(g[r][c]))
        cols.append(" > ".join(names))
    out = []
    for row in g[head:]:
        uniq = list(dict.fromkeys(id(x) for x in row))
        if len(uniq) == 1:                # 가로로 다 차는 칸(비고 · ※ 줄)
            out.append(_text(row[0]))
            continue
        counts = [len(x["lines"]) for x in row]
        n = max((k for k in set(counts) if k > 1 and counts.count(k) >= 2), default=1)
        for i in range(n):
            pairs, prev = [], None
            for c, x in enumerate(row):
                if x is prev:             # 가로 합침: 한 번만
                    continue
                prev = x
                v = x["lines"][i] if n > 1 and len(x["lines"]) == n else _text(x)
                if not v:
                    continue
                h = cols[c] if c < len(cols) else ""
                if pairs and pairs[-1][0] == h and h:
                    pairs[-1] = (h, f"{pairs[-1][1]} > {v}")
                else:
                    pairs.append((h, v))
            out.append(" · ".join(f"{h}: {v}" if h and h != v else v for h, v in pairs))
    return out


def render(html):
    """DP HTML → 글. 표는 펼친 줄(앞에 「- 」), 그 밖의 머리 · 문단은 그대로."""
    d = _Doc()
    d.feed(html)
    d.close()
    d.flush()
    out = []
    for kind, x in d.blocks:
        out += [f"- {line}" for line in table_lines(x)] if kind == "table" else [x]
    return "\n".join(out)


@lru_cache(maxsize=None)
def _rendered(name):
    p = DIR / f"{name}.html"
    return render(p.read_text(encoding="utf-8")) if p.exists() else None


def text_for(chunk):
    """색인 조각이 별표면 펼친 글, 아니면 None. 파일 이름은 원문 주소의 일련번호 + 라벨 끝의 「별표 N」."""
    m = re.search(r"(별표\s*\d*)$", chunk["label"])
    seq = re.search(r"ordinSeq=(\d+)", chunk.get("source_url", ""))
    if not (m and seq):
        return None
    return _rendered(f"{seq.group(1)}_{m.group(1).replace(' ', '')}")


def selftest():
    html = ("<p>공원입장료</p><table><tr><th colspan='2'>공 원 별</th><th>사용기준</th><th>금 액(원)</th></tr>"
            "<tr><td rowspan='2'>서울대공원</td><td>동물원 <br/>(식물원 포함)</td><td>어 른 1회 <br/>청소년 1회 <br/>어린이 1회</td>"
            "<td>3,000~6,000 <br/>2,000~4,000 <br/>1,000~2,000</td></tr>"
            "<tr><td>테마가든</td><td>어 른 1회당 <br/>어린이 1회당</td><td>2,000~4,000 <br/>1,000~2,000</td></tr>"
            "<tr><td colspan='4'>※(주) 어린이 : 6세 이상 12세 이하</td></tr></table><p>1. 비고 &lt;끝&gt;</p>")
    lines = render(html).split("\n")
    assert lines[0] == "공원입장료", lines
    assert lines[1] == "- 공 원 별: 서울대공원 > 동물원 (식물원 포함) · 사용기준: 어 른 1회 · 금 액(원): 3,000~6,000", lines[1]
    assert lines[3] == "- 공 원 별: 서울대공원 > 동물원 (식물원 포함) · 사용기준: 어린이 1회 · 금 액(원): 1,000~2,000", lines[3]
    assert lines[4] == "- 공 원 별: 서울대공원 > 테마가든 · 사용기준: 어 른 1회당 · 금 액(원): 2,000~4,000", lines[4]
    assert lines[6] == "- ※(주) 어린이 : 6세 이상 12세 이하" and lines[7] == "1. 비고 <끝>", lines
    multi = ("<table><tr><th rowspan='2'>구 분</th><th colspan='2'>노 외</th></tr><tr><th>전 일</th><th>야 간</th></tr>"
             "<tr><th>1급지</th><td>250,000</td><td>100,000</td></tr></table>")
    assert render(multi) == "- 구 분: 1급지 · 노 외 > 전 일: 250,000 · 노 외 > 야 간: 100,000", render(multi)
    chunk = {"label": "서울특별시 주차장 설치 및 관리 조례 별표 1",
             "source_url": "https://www.law.go.kr/ordinInfoP.do?ordinSeq=2171833"}
    assert "1급지" in text_for(chunk) and text_for({"label": "… 제7조", "source_url": ""}) is None
    print("annex 스스로 시험: 통과")
