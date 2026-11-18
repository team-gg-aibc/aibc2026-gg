"""표준노드링크에서 서울 자동차전용도로 위의 나들목 · 분기점 · 다리 · 터널 · 지하차도 이름을 줄인 표(data/seoul/road_nodes.tsv.gz)로 만든다.
다리가 없는 자동차전용도로(내부순환로 · 동부간선로 · 북부간선도로 …)에서도 「○○ 나들목 지나서」 · 「○○터널 안」으로 좁히는 데 쓴다. 받은 zip은 읽기만 한다(풀지 않는다).

    python3 -I demo/call/tools/build_nodelink.py <받은 zip>          → data/seoul/road_nodes.tsv.gz (이름 \t 종류 \t 경도 \t 위도 \t 길)

자료: 국가교통정보센터 「표준노드링크」 [2026-11-11]판(MOCT_NODE · MOCT_LINK, 좌표계 ITRF2000 중부원점 TM — .prj에서 확인).
- 길: 링크의 도로 등급이 고속도로(101) · 도시고속도로(102)이고 이름이 자동차전용도로 노선인 것. 그 링크의 양 끝 노드만 본다.
- 이름: 차에서 표지판으로 보이는 꼴만 남긴다(…IC · JC · 분기점 · 요금소 · 터널 · 지하차도 · 고가 · …교 · 대교 북단).
  노드 이름 가운데 둘레 건물 · 주소 · 교차로(「○○아파트」 · 「상암동 1536-5」 · 「○○앞」)는 뺀다.
- 자리: 지명 표의 그 길 선에서 60m 안의 노드만(본선 위). 같은 이름이 길을 따라 150m 넘게 퍼져 있으면(긴 터널 · 다리의 양 끝)
  두 끝 사이를 길 선을 따라 80m마다 점으로 채운다(「터널 안이에요」가 터널 전체를 가리키게). 나들목은 같은 이름의 노드들 가운데로 하나.
- 오픈스트리트맵 지명 표에 1.5km 안의 같은 이름(나들목 · 분기점 · IC · JC는 같은 말로 봄)이 이미 있으면 넣지 않는다.
"""
import gzip
import json
import math
import os
import re
import struct
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ["CALL_SHOPS"], os.environ["CALL_NODES"] = "0", "0"      # 견줄 것은 오픈스트리트맵 지명 표와 길 선뿐
import gaz          # noqa: E402

OUT = HERE / "data" / "seoul"
ROADS = {"강변북로": "강변북로", "올림픽대로": "올림픽대로", "내부순환도로": "내부순환로", "내부순환로": "내부순환로", "동부간선도로": "동부간선로", "동부간선로": "동부간선로",
         "북부간선도로": "북부간선도로", "서부간선도로": "서부간선로", "서부간선로": "서부간선로", "강남순환도시고속도로": "강남순환로", "강남순환로": "강남순환로",
         "경부고속도로": "경부고속도로", "국회대로": "국회대로", "우면산로": "우면산로"}       # 노드링크의 노선 이름 → 지명 표의 길 이름
SAME = {"서부간선로": ("서부간선로", "서부간선도로"), "동부간선로": ("동부간선로", "동부간선도로")}
DROP = re.compile(r"(앞|입구|교차로|사거리|삼거리|오거리|램프|연결|합류\d*|분기|초교|중교|고교|학교)$|화장실|^\d|\d+-\d+|동\s?\d|^(교량|고가차도|고가교|터널|지하차도|교량[동서남북]측)$")


def tm_to_lonlat(x, y):
    """ITRF2000 중부원점 TM(원점 127°E 38°N, 가산 200000 · 600000, 축척 1) → 경위도. GRS80 횡메르카토르 역변환(Snyder)."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = 2 * f - f * f
    ep2 = e2 / (1 - e2)
    lat0, lon0 = math.radians(38.0), math.radians(127.0)
    m_ = lambda p: a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * p - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * np.sin(2 * p)   # noqa: E731
                        + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * np.sin(4 * p) - (35 * e2 ** 3 / 3072) * np.sin(6 * p))
    mu = (m_(lat0) + (np.asarray(y, float) - 600000.0)) / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * np.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * np.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * np.sin(6 * mu) + (1097 * e1 ** 4 / 512) * np.sin(8 * mu))
    c1, t1 = ep2 * np.cos(p1) ** 2, np.tan(p1) ** 2
    n1 = a / np.sqrt(1 - e2 * np.sin(p1) ** 2)
    r1 = a * (1 - e2) / (1 - e2 * np.sin(p1) ** 2) ** 1.5
    d = (np.asarray(x, float) - 200000.0) / n1
    lat = p1 - (n1 * np.tan(p1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                          + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / np.cos(p1)
    return np.degrees(lon), np.degrees(lat)


def dbf(z, info):
    r = z.open(info)
    n, hl, rl = struct.unpack("<IHH", r.read(12)[4:12])
    fl, fields = r.read(hl - 12), []
    for i in range(20, len(fl) - 1, 32):          # 머리 32바이트 가운데 12바이트는 이미 읽었다 → 필드 설명은 20바이트 뒤부터
        d = fl[i:i + 32]
        if d[0] == 0x0D:
            break
        fields.append((d[:11].split(b"\0")[0].decode(), d[16]))
    for _ in range(n):
        rec, p, out = r.read(rl), 1, {}
        for name, w in fields:
            out[name] = rec[p:p + w].decode("cp949", "replace").strip()
            p += w
        yield out


def points(z, info):
    r = z.open(info)
    r.read(100)
    while len(h := r.read(8)) == 8:
        rec = r.read(struct.unpack(">ii", h)[1] * 2)
        yield struct.unpack("<dd", rec[4:20])


def clean(nm):
    """노드 이름 → (보일 이름, 종류) 또는 None."""
    nm = re.sub(r"\s+", "", nm)
    side = re.search(r"\(([동서남북])측\)$", nm)
    base = re.sub(r"\([동서남북]측\)$", "", nm)
    if any(r in base for r in ROADS) or DROP.search(base):
        return None
    m = re.match(r"^(.+대교)(북측|남측|북단|남단)$", base)
    if m:
        return f"{m.group(1)} {m.group(2)[0]}단", "나들목"           # 「가양대교북측」 · 「가양대교북단」 → 「가양대교 북단」(다리가 강변 도로와 만나는 곳)
    if base.endswith("대교") and side:
        return f"{base} {side.group(1)}단", "나들목"                   # 「동작대교(북측)」도 같은 곳
    if re.search(r"(IC|JC|TG|분기점|나들목|요금소)$", base):
        return base, "나들목"
    if re.search(r"(터널|지하차도|지하도로)$", base):
        return base, "터널"
    if base.endswith("육교"):
        return base, "육교"
    if re.search(r"(고가차도|고가교|고가|교)$", base) and len(base) >= 3:
        return base, "다리"
    return None


def variants(name):
    """나들목 이름의 다른 꼴(「신내IC」 = 「신내 나들목」, 「성수JC」 = 「성수 분기점」)."""
    b = re.sub(r"(ic|jc|나들목|분기점|아이씨|제이씨)$", "", gaz.norm(name))
    return {gaz.norm(name), b + "ic", b + "나들목", b + "jc", b + "분기점"} if b and b != gaz.norm(name) else {gaz.norm(name)}


def main(src):
    t0 = time.time()
    z = zipfile.ZipFile(src)
    files = {(i.filename if i.flag_bits & 0x800 else i.filename.encode("cp437").decode("cp949", "replace")): i for i in z.infolist()}
    prj = z.read(files["MOCT_NODE.prj"]).decode()
    assert "Central_Belt" in prj and "200000" in prj and "600000" in prj and "127.0" in prj and "38.0" in prj, prj      # 좌표계가 바뀌면 멈춘다
    nodes = {}
    for (x, y), d in zip(points(z, files["MOCT_NODE.shp"]), dbf(z, files["MOCT_NODE.dbf"])):
        if 176000 < x < 222000 and 530000 < y < 572000:          # 서울을 덮는 네모(TM m)
            nodes[d["NODE_ID"]] = (x, y, d["NODE_TYPE"], d["NODE_NAME"])
    on = defaultdict(set)                                          # 노드 → 지나는 자동차전용도로
    for d in dbf(z, files["MOCT_LINK.dbf"]):
        if d["ROAD_RANK"] in ("101", "102") and d["ROAD_NAME"] in ROADS:
            for k in ("F_NODE", "T_NODE"):
                if d[k] in nodes:
                    on[d[k]].add(ROADS[d["ROAD_NAME"]])
    G = gaz.Gazetteer()
    line = {}
    for road in set(ROADS.values()):
        idx = [i for i, r in enumerate(G.roads) if r["name"] in SAME.get(road, (road,))]
        if idx:
            line[road] = np.vstack([G.road_xy(i) for i in idx])
    groups, why = defaultdict(list), Counter()
    for nid, roads in on.items():
        x, y, _, nm = nodes[nid]
        c = clean(nm)
        if not c:
            why["표지 이름 아님"] += 1
            continue
        lon, lat = tm_to_lonlat(x, y)
        px, py = gaz.xy(lon, lat)
        for road in roads:
            if road not in line:
                continue
            d = np.hypot(line[road][:, 0] - px, line[road][:, 1] - py)
            if d.min() > 60:
                why["본선에서 60m 넘게 떨어짐"] += 1
                continue
            groups[(c[0], c[1], road)].append((float(px), float(py), int(d.argmin())))
    osm = defaultdict(list)
    for i in range(G.shop0):
        for v in (variants(G.name[i]) if G.kind[i] == "나들목" else {gaz.norm(G.name[i])}):
            osm[v].append((G.x[i], G.y[i]))
    rows, seen = [], set()
    for (name, kind, road), pts in sorted(groups.items()):
        a = np.array(pts)
        if any(math.hypot(ox - a[:, 0].mean(), oy - a[:, 1].mean()) < 1500 for v in variants(name) for ox, oy in osm.get(v, ())):
            why["오픈스트리트맵에 이미 있음"] += 1
            continue
        spread = max(math.hypot(p[0] - q[0], p[1] - q[1]) for p in pts for q in pts)
        if kind == "나들목" or spread <= 150:
            if spread > 2500:                                    # 같은 이름이 한 길에서 멀리 둘: 어느 쪽인지 몰라 뺀다
                why["같은 이름이 멀리 둘"] += 1
                continue
            j = int(np.argmin(np.hypot(line[road][:, 0] - a[:, 0].mean(), line[road][:, 1] - a[:, 1].mean())))
            out = [line[road][j]]
        else:                                                      # 긴 터널 · 다리: 두 끝 사이의 길 선을 80m마다
            if spread > 4000:
                why["같은 이름이 멀리 둘"] += 1
                continue
            p, q = max(((p, q) for p in a for q in a), key=lambda pq: math.hypot(pq[0][0] - pq[1][0], pq[0][1] - pq[1][1]))
            u = np.array([q[0] - p[0], q[1] - p[1]]) / spread
            rel = line[road] - p[:2]
            along, off = rel @ u, np.abs(rel @ np.array([-u[1], u[0]]))
            seg = line[road][(along >= -10) & (along <= spread + 10) & (off <= 60)]
            seg = seg[np.argsort((seg - p[:2]) @ u)]
            out = [p[:2]]
            for s in seg:
                if math.hypot(*(s - out[-1])) >= 80:
                    out.append(s)
            if math.hypot(*(q[:2] - out[-1])) >= 40:
                out.append(q[:2])
        for s in out:
            lo, la = gaz.lonlat(*s)
            key = (name, round(lo, 4), round(la, 4))
            if key not in seen:
                seen.add(key)
                rows.append(f"{name}\t{kind}\t{lo:.6f}\t{la:.6f}\t{road}")
    with gzip.open(OUT / "road_nodes.tsv.gz", "wt", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    names = Counter((r.split("\t")[0], r.split("\t")[1], r.split("\t")[4]) for r in rows)
    meta = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
    meta["road_nodes"] = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"), "source": "국가교통정보센터 표준노드링크 [2026-11-11] (MOCT_NODE · MOCT_LINK)",
                          "zip": Path(src).name, "zip_bytes": Path(src).stat().st_size, "names": len(names), "rows": len(rows),
                          "kinds": dict(Counter(k for _, k, _ in names)), "roads": dict(Counter(r for _, _, r in names)), "dropped": dict(why)}
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta["road_nodes"], ensure_ascii=False), f"{time.time() - t0:.0f}초")
    for (n, k, r), c in sorted(names.items(), key=lambda t: (t[0][2], t[0][0])):
        print(f"  {r} | {n} | {k} | 점 {c}")


if __name__ == "__main__":
    main(sys.argv[1])
