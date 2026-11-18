"""교차로 이름을 대는 시민 묶음(60번): 가상 통화 600통의 시민은 교차로 이름(tools/build_cross.py)을 모른다. 그 이름을 대는 경우를 따로 만든다.

    SIM_CROSS=1 CALL_CROSS=0|1|2 OPENBLAS_NUM_THREADS=1 python3 demo/call/tools/cross_set.py [--n 80] [--seed 60] [--json 파일]
    SIM_CROSS=1 = 시민이 보는 세상에 교차로 이름이 있다(늘 켠다). CALL_CROSS = 시스템의 지명 표(0 넣기 전 · 1 알아듣기만 · 2 보기에도).

- 걷는 시민: 참 위치 = 교차로에서 8~30m. 첫 말 「○○사거리 바로 앞 · 옆 · 근처인데요」.
- 차로 지나간 시민: 참 위치 = 그 교차로를 지나는 큰길을 따라 60~300m 더 간 곳. 첫 말 「△△로 타고 가는 중인데요, ○○사거리 조금 지나서 …」.
- 그 뒤는 가상 시민이 참 위치에서 보이는 대로 답한다(시민의 세상에는 교차로 이름이 있다).
- 재는 것: 첫 말 뒤의 범위 크기와 그 범위(90%)에 참 위치가 드나 · 끝 · 주고받은 횟수.
"""
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_calls as SC            # noqa: E402

S, L, G, W, gaz, np = SC.S, SC.L, SC.G, SC.W, SC.gaz, SC.np
ARG = SC.ARG
BIG = ("trunk", "primary", "secondary")


def past(i, rng):
    """교차로 i를 지나는 큰길을 따라 60~300m 더 간 점 → (x, y, 길 이름, 가는 방향) 또는 None."""
    x, y = float(W.x[i]), float(W.y[i])
    for n, r in enumerate(G.roads):
        if r["cls"] not in BIG or len(r["name"]) < 3 or r["name"] in L.EXPRESSWAYS:
            continue
        xy = G.road_xy(n)
        d = np.hypot(xy[:, 0] - x, xy[:, 1] - y)
        j = int(d.argmin())
        if d[j] > 30:
            continue
        k = int(rng.uniform(60, 300) // 20) * rng.choice((1, -1))
        a, b = sorted((j, j + k))
        if a < 3 or b >= len(xy) - 3 or float(np.hypot(*np.diff(xy[a:b + 1], axis=0).T).max()) > 25:
            continue                                      # 한 줄로 이어진 구간만
        h = (xy[j + k] - xy[j]) / (np.hypot(*(xy[j + k] - xy[j])) or 1)
        return float(xy[j + k][0]), float(xy[j + k][1]), r["name"], [float(h[0]), float(h[1])]
    return None


def watch(c, st, view, said):
    if "in_range" in c:
        return
    clues, _ = S.understood(st)
    R = L.infer(clues) if clues else None
    c["in_range"] = bool(R is not None and np.hypot(R["x"][R["cred"]] - c["x"], R["y"][R["cred"]] - c["y"]).min() <= 15)
    c["first_m"], c["first_chips"] = (view["size"] or {}).get("m"), view["chips"]


def build(n, seed):
    assert W is not G and W.cross1 > W.cross0, "SIM_CROSS=1로 돌린다(시민의 세상에 교차로 이름이 있어야 한다)"
    rng = random.Random(seed)
    ids = [i for i in range(W.cross0, W.cross1) if SC.VISIBLE(i)]
    rng.shuffle(ids)
    cases = []
    for i in ids:
        walk, drive = sum(c["group"] == "걷는 시민" for c in cases), sum(c["group"] == "차로 지나간 시민" for c in cases)
        if walk >= n // 2 and drive >= n // 2:
            break
        p = past(i, rng) if drive < n // 2 else None
        if p:
            cases.append({"group": "차로 지나간 시민", "cat": "큰길", "x": p[0], "y": p[1], "road": p[2], "head": p[3], "type": ("carcass", "road", "light", "parking")[drive % 4],
                          "first": f"{p[2]} 타고 가는 중인데요, {W.name[i]} 조금 지나서 "})
        elif walk < n // 2:
            dx, dy = SC.ring_at(rng, 8, 30)
            cases.append({"group": "걷는 시민", "cat": "골목 · 상가 길", "x": float(W.x[i]) + dx, "y": float(W.y[i]) + dy, "type": ("light", "litter", "parking", "noise", "vendor", "road")[walk % 6],
                          "first": f"{W.name[i]} {SC.HOW(math.hypot(dx, dy)).replace('이에요', '').replace('예요', '')}인데요, "})
        else:
            continue
        cases[-1].update(place=W.name[i], off_m=round(math.hypot(cases[-1]["x"] - W.x[i], cases[-1]["y"] - W.y[i])))
    for k, c in enumerate(cases):
        c.update(id=k + 1, noisy=False, d_land=0.0, d_osm=0.0, on_turn=watch)
        c["first"] += SC.SAY[c["type"]]
    return cases


def main():
    res = []
    for c in build(ARG("--n", 80), ARG("--seed", 60)):
        r = SC.run(c, random.Random(f"cross:{c['id']}"))
        r.update({k: c.get(k) for k in ("group", "place", "off_m", "in_range", "first_m", "first_chips")})
        res.append(r)
    print("| 묶음 | 통화 | 첫 말에서 자리를 세움 | 첫 말 뒤 범위(가운데값) | 그 범위에 참 자리가 듦 | 한 점 | **틀린 확정** | 넓은 범위 · 구간 | 자리 미확정 | 못 끝냄 | 주고받기 |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for g in ("걷는 시민", "차로 지나간 시민"):
        rs = [r for r in res if r["group"] == g]
        n = lambda end: sum(1 for r in rs if r["end"].startswith(end))     # noqa: E731
        fm = [r["first_m"] for r in rs if r["first_m"]]
        print(f"| {g} | {len(rs)} | {len(fm)} | {statistics.median(fm):.0f}m | {sum(1 for r in rs if r['in_range'])} | {n('점')} | {n('틀린 확정') + sum(1 for r in rs if r['end'] == '구간(밖)')} | {n('넓은 범위') + sum(1 for r in rs if r['end'] == '구간')} | "
              f"{n('솔직한 끝')} | {n('못 끝냄')} | {statistics.mean(r['turns'] for r in rs):.1f} |")
    bad = [r for r in res if r["end"] in ("틀린 확정", "구간(밖)")]
    if bad:
        print("\n틀린 확정: " + " / ".join(f"#{r['id']} {r['place']} {r['err_m']}m 「{(r['where'] or '')[:40]}」" for r in bad))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
