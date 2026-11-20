"""위키데이터 서울 항목의 한국어 별칭 + 한국어 위키백과 넘겨주기 이름 → 지명 표의 그 장소(68번 B-4).
    python3 demo/call/tools/build_wiki_alias.py <wd_seoul.json> <kowiki_redirects.json>  → data/seoul/wiki_alias.tsv.gz (별칭 · 지명 표 이름 · 경도 · 위도)
- 받는 법: wd_seoul.json = query.wikidata.org SPARQL(P131+ 서울 · 좌표 · ko 이름 · ko 별칭 · ko 위키백과 문서), kowiki_redirects.json = ko.wikipedia.org API prop=redirects. 둘 다 열쇠 없음.
- 잇는 법: 위키데이터 좌표에서 300m 안에 이름(ko 이름 또는 위키백과 문서 제목)이 다듬은 꼴로 같은 지명 표 장소가 있으면 그곳에 별칭을 단다. 없으면 버린다(지명 표에 없는 곳은 찾아도 쓸 데가 없다).
- 조건: 위키데이터 CC0, 위키백과 넘겨주기 이름은 문서 제목(CC BY-SA 4.0, 출처 표시)."""
import gzip
import json
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import numpy as np   # noqa: E402
import gaz           # noqa: E402

G = gaz.load()
wd = json.loads(Path(sys.argv[1]).read_text())["results"]["bindings"]
rd = json.loads(Path(sys.argv[2]).read_text())
rows, seen = [], set()
for x in wd:
    lon, lat = (float(v) for v in x["coord"]["value"][6:-1].split())
    px, py = (float(v) for v in gaz.xy(lon, lat))
    title = urllib.parse.unquote(x["article"]["value"].rsplit("/wiki/", 1)[1]).replace("_", " ") if "article" in x else None
    names = {gaz.norm(x["label"]["value"])} | ({gaz.norm(title)} if title else set())
    idx = [int(i) for i in G.near(px, py, 300) if not G.shop0 <= int(i) < G.shop1 and gaz.norm(G.name[int(i)]) in names]
    if not idx:
        continue
    i = min(idx, key=lambda i: (G.kind[i] in ("정류장", "시설"), np.hypot(G.x[i] - px, G.y[i] - py)))
    alts = [a for a in (x.get("aliases", {}).get("value") or "").split("|") if a] + (rd.get(title) or [] if title else []) + ([x["label"]["value"]] if gaz.norm(x["label"]["value"]) != gaz.norm(G.name[i]) else [])
    for a in alts:
        k = gaz.norm(a)
        if len(k) >= 2 and k != gaz.norm(G.name[i]) and (k, i) not in seen:
            seen.add((k, i))
            lo, la = gaz.lonlat(G.x[i], G.y[i])
            rows.append(f"{a}\t{G.name[i]}\t{lo}\t{la}")
out = HERE / "data" / "seoul" / "wiki_alias.tsv.gz"
with gzip.open(out, "wt", encoding="utf-8") as f:
    f.write("\n".join(rows) + "\n")
print("별칭", len(rows), "· 이은 장소", len({r.split("\t")[1] + r.split("\t")[2] for r in rows}), "→", out.relative_to(HERE.parents[1]))
for q in ("육삼빌딩", "롯데타워", "서울대병원", "고터", "숭대", "디디피", "동대문운동장"):
    print(q, "→", [r.split("\t")[1] for r in rows if gaz.norm(r.split("\t")[0]) == gaz.norm(q)][:3])
