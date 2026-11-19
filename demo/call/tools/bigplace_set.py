"""넓은 장소 앞에 선 시민 묶음(60번): 가상 통화 600통에는 없는 경우를 따로 만든다. 가상 시민(sim_calls.py)의 기본 동작은 바꾸지 않는다.

    OPENBLAS_NUM_THREADS=1 python3 demo/call/tools/bigplace_set.py <받은 오픈스트리트맵 폴더> [--n 90] [--seed 60] [--json 파일]
    견줄 때: CALL_ON=<기본값> 과 CALL_ON=<기본값>,bigplace 로 두 번 돌린다(같은 씨앗이면 같은 통화).

- 넓은 곳(학교 · 시장 · 병원 · 마트 · 체육시설 …, 지명 표의 한 점에서 가장 먼 가장자리가 40m 넘는 면): 참 위치 = 실제 테두리의 아무 점에서 바깥으로 6m(담장 앞). 첫 말 「○○ 바로 앞인데요」.
- 역: 참 위치 = 그 역의 아무 출구에서 5~15m. 첫 말 「○○역 앞인데요」(출구 번호는 말하지 않는다).
- 작은 곳(대조군, 크기 표에 없는 관공서 · 병원 · 은행 …): 참 위치 = 그 점에서 5~12m. 첫 말은 같다. 켜도 끄기와 같아야 한다.
- 그 뒤는 가상 시민이 참 위치에서 보이는 대로 답한다. 다른 것은 하나: 되말한 이름이 자기가 그 앞에 서 있는 그 장소면 「네」라고 한다
  (기본 가상 시민은 그 이름의 점이 50m 안에 있어야 「네」라고 해서, 운동장 한가운데 점에서 90m 떨어진 담장 앞 시민이 「아니요」라고 해 버린다).
- 재는 것: 첫 자리 말 뒤의 범위(90%)에 참 위치가 드나 · 끝(점 = 확정한 점이 참 위치 60m 안 · 틀린 확정 = 60m 밖) · 확정한 점의 거리 · 주고받은 횟수.
"""
import json
import lzma
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_gazetteer as B       # noqa: E402
import sim_calls as SC            # noqa: E402  (서버 · 지명 표를 함께 불러온다)

S, L, G, gaz, np = SC.S, SC.L, SC.G, SC.gaz, SC.np
ARG = SC.ARG
BIG_KINDS = ("학교", "시장", "병원", "마트", "체육시설", "관공서", "문화시설", "볼거리", "터미널")     # 사람들이 이름으로 대는 넓은 곳(이름 없는 큰 건물 · 아파트 동은 뺀다)
SMALL_KINDS = ("관공서", "병원", "은행", "경찰", "소방서", "약국")
TYPES = ("light", "litter", "parking", "noise", "smoking", "vendor", "road")
CUR = {}
_seen = SC.seen_name
SC.seen_name = lambda name, x, y, r: _seen(name, x, y, r) or gaz.norm(name) == gaz.norm(CUR.get("place", "\0"))      # 그 앞에 서 있는 그 장소를 되말하면 「네」


def usable(i):
    """한 통화에서 이름 하나로 댈 만한 곳: 이름이 서울에 한 곳뿐이고 가상 시민이 댈 수 있는 꼴."""
    return SC.VISIBLE(i) and len(G.refs(gaz.norm(G.name[i]))) == 1


def rings(src, want):
    """받은 오픈스트리트맵 파일에서 고른 장소의 실제 테두리 → {장소 번호: [(x, y) m, …]}. 가운데 점 셈은 build_gazetteer.py와 같다."""
    at = {(G.name[i], G.kind[i], f"{lo:.6f}", f"{la:.6f}"): i for i in want for lo, la in [gaz.lonlat(G.x[i], G.y[i])]}
    out = {}
    with lzma.open(next(Path(src).expanduser().glob("*.geojson.xz")), "rt", encoding="utf-8") as f:
        for line in f:
            if '"name"' not in line or "Polygon" not in line:
                continue
            s = line.strip().rstrip(",")
            if not s.startswith('{"type":"Feature"'):
                continue
            d = json.loads(s)
            g, p = d["geometry"], d.get("properties") or {}
            if g["type"] not in ("Polygon", "MultiPolygon"):
                continue
            ring = max(B.rings_of(g), key=len)
            lon, lat = sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring)
            i = at.get((" ".join((p.get("name") or "").split()), B.kind_of(p, g["type"]), f"{lon:.6f}", f"{lat:.6f}"))
            if i is not None:
                out[i] = [tuple(float(v) for v in gaz.xy(x, y)) for x, y in ring]
    return out


def fence(ring, rng):
    """테두리의 아무 점에서 바깥으로 6m."""
    arr = np.array(ring)
    for _ in range(50):
        j = rng.randrange(len(ring) - 1)
        (x1, y1), (x2, y2), t = ring[j], ring[j + 1], rng.random()
        n = math.hypot(x2 - x1, y2 - y1)
        if n < 1:
            continue
        px, py, nx, ny = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, -(y2 - y1) / n, (x2 - x1) / n
        for s in (6, -6):
            q = (px + nx * s, py + ny * s)
            if not L.in_ring(np.array([q[0]]), np.array([q[1]]), arr)[0]:
                return q
    return None


def build(src, n, seed):
    rng = random.Random(seed)
    ids = [i for i in range(G.shop0) if usable(i)]
    big = [i for i in ids if G.kind[i] in BIG_KINDS and G.ext[i] > 40]
    st = [i for i in ids if G.kind[i] == "역" and G.ext[i] > 40]
    small = [i for i in ids if G.kind[i] in SMALL_KINDS and G.ext[i] == 0]
    for lst in (big, st, small):
        rng.shuffle(lst)
    big, st, small = big[:n // 2 + 20], st[:n // 4], small[:n // 4]
    ring = rings(src, big)
    cases = []
    for i in big:
        p = fence(ring[i], rng) if i in ring else None
        if p and len(cases) < n // 2:
            cases.append({"group": "넓은 곳", "i": i, "x": p[0], "y": p[1], "first": f"{G.name[i]} 바로 앞인데요"})
    for i in st:
        ex = [j for j in range(G.shop0) if G.kind[j] == "역 출구" and G.name[j].startswith(G.name[i] + " ")]
        if ex:
            j = rng.choice(ex)
            dx, dy = SC.ring_at(rng, 5, 15)
            cases.append({"group": "역", "i": i, "x": float(G.x[j]) + dx, "y": float(G.y[j]) + dy, "first": f"{G.name[i]} 앞인데요"})
    for i in small:
        dx, dy = SC.ring_at(rng, 5, 12)
        cases.append({"group": "작은 곳(대조군)", "i": i, "x": float(G.x[i]) + dx, "y": float(G.y[i]) + dy, "first": f"{G.name[i]} 바로 앞인데요"})
    for k, c in enumerate(cases):
        i = c["i"]
        c.update(id=k + 1, cat="골목 · 상가 길", type=TYPES[k % len(TYPES)], noisy=False, place=G.name[i], kind=G.kind[i], ext=float(G.ext[i]),
                 off_m=round(math.hypot(c["x"] - G.x[i], c["y"] - G.y[i])), d_land=0.0, d_osm=0.0, on_turn=watch)
        c["first"] += f", {SC.SAY[c['type']]}"
    return cases


def watch(c, st, view, said):
    """첫 자리 말 뒤의 범위(90%)에 참 위치가 드나(가장 가까운 범위 격자점이 15m 안)."""
    if "in_range" in c:
        return
    clues, _ = S.understood(st)
    R = L.infer(clues) if clues else None
    if R is not None:
        c["in_range"] = bool(np.hypot(R["x"][R["cred"]] - c["x"], R["y"][R["cred"]] - c["y"]).min() <= 15)
        c["first_m"] = (view["size"] or {}).get("m")


def main():
    cases = build(sys.argv[1], ARG("--n", 90), ARG("--seed", 60))
    res = []
    for c in cases:
        CUR.clear(), CUR.update(place=c["place"])
        r = SC.run(c, random.Random(f"big:{c['id']}"))
        r.update({k: c.get(k) for k in ("group", "place", "kind", "ext", "off_m", "in_range", "first_m")})
        res.append(r)
    print("| 묶음 | 통화 | 참 자리 ↔ 지명 표의 점 (가운데 · 가장 먼 것) | 첫 말 뒤 범위에 참 자리가 듦 | 한 점(60m 안) | **틀린 확정** | 넓은 범위 · 자리 미확정 · 못 끝냄 | 확정한 점의 거리 (가운데 · 가장 먼 것) | 주고받기 |\n|---|---|---|---|---|---|---|---|---|")
    for g in ("넓은 곳", "역", "작은 곳(대조군)"):
        rs = [r for r in res if r["group"] == g]
        if not rs:
            continue
        e = [r["err_m"] for r in rs if r.get("narrowed")]
        n = lambda end: sum(1 for r in rs if r["end"].startswith(end))     # noqa: E731
        print(f"| {g} | {len(rs)} | {statistics.median(r['off_m'] for r in rs):.0f}m · {max(r['off_m'] for r in rs)}m | {sum(1 for r in rs if r['in_range'])} | {n('점')} | {n('틀린 확정')} | {n('넓은 범위') + n('구간')} · {n('솔직한 끝')} · {n('못 끝냄')} | "
              + (f"{statistics.median(e):.0f}m · {max(e)}m" if e else "—") + f" | {statistics.mean(r['turns'] for r in rs):.1f} |")
    bad = [r for r in res if r["end"] == "틀린 확정"]
    if bad:
        print("\n틀린 확정: " + " / ".join(f"#{r['id']} {r['place']}({r['kind']}, 크기 {r['ext']:.0f}m) {r['err_m']}m" for r in bad))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
