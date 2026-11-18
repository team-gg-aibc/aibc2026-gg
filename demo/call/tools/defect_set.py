"""결함 넷(11-16)의 새 사례: 사례마다 참 위치와 시민의 첫 말을 정해 두고, 그 뒤는 가상 시민(sim_calls.py)이 참 위치에서 보이는 대로 답한다.

    python3 demo/call/tools/defect_set.py --half dev [--defect 1] [--solar] [--json 파일]
    (엔진 가상 환경의 파이썬, OPENBLAS_NUM_THREADS=1. --solar면 차례마다 Solar 다시 읽기까지)

결함과 바라는 끝(통과 기준):
  1 분류에 없는 민원      종류 밖이면 「그 밖의 일」(가까운 종류로 넣지 않음) · 「어떤 일로」를 다시 묻지 않음 · 넘길 곳 「담당 확인 필요」 · 조례 근거 없음.
                           종류 안(대조군)은 고치기 전과 같은 종류.
  2 소리가 같은 길 이름    틀린 쪽으로 확정하지 않음.
  3 「○○ 쪽 · 방향 · 가는 길」  틀린 확정 없음.
  4 「지나고 조금 뒤」      그 말을 들은 차례의 범위(90%)에 참 위치가 들고, 끝까지 틀린 확정 없음.
반은 사례를 쓸 때 정했다(dev = 고칠 때 보는 반, hold = 마지막에 한 번만 돌리는 반).
"""
import json
import math
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_calls as SC        # noqa: E402  (서버 · 지명 표를 함께 불러온다)

S, L, G, gaz, np = SC.S, SC.L, SC.G, SC.gaz, SC.np
ARG = SC.ARG


def _pts(name):
    r = L.resolve(gaz.norm(name))
    return [(float(x), float(y)) for x, y in zip(r["x"], r["y"])]


def _road(name):
    return np.vstack([G.road_xy(i) for i, r in enumerate(G.roads) if r["name"] == name])


def along(road, land, dist, toward, back=False):
    """길 위에서 표지(land)를 지나는 곳(지명 표의 그 표지를 길 위로 당긴 점)부터 toward(이름) 쪽으로 dist m 간 점 → (x, y, 가는 방향).
    back이면 가는 방향을 거꾸로(시민이 그 표지 쪽으로 가는 중)."""
    P = _road(road)
    a = L._context([{"t": "at", "k": gaz.norm(road)}, {"t": "past", "k": gaz.norm(land)}])["pos"].get(1)
    lx, ly = a if a else min(_pts(land), key=lambda p: float(np.hypot(P[:, 0] - p[0], P[:, 1] - p[1]).min()))
    p0 = P[int(np.argmin(np.hypot(P[:, 0] - lx, P[:, 1] - ly)))]
    tx, ty = min(_pts(toward), key=lambda p: math.hypot(p[0] - p0[0], p[1] - p0[1]))
    h = np.array([tx - p0[0], ty - p0[1]]) / math.hypot(tx - p0[0], ty - p0[1])
    v = P - p0
    n = np.hypot(v[:, 0], v[:, 1]) + 1e-9
    ok = (v @ h) / n > 0.6
    j = int(np.argmin(np.where(ok, abs(n - dist), 1e9)))
    q = P[j]
    h = -h if back else h
    return float(q[0]), float(q[1]), [float(h[0]), float(h[1])]      # 가는 방향은 곧게(길이 거의 곧은 구간만 쓴다)


def off(land, dist, bearing):
    """표지에서 bearing(도, 북쪽 0 · 동쪽 90) 쪽으로 dist m 떨어진 점(길 위로 당기지 않는다: 골목 · 건물 사이일 수 있다)."""
    lx, ly = _pts(land)[0]
    x, y = lx + dist * math.sin(math.radians(bearing)), ly + dist * math.cos(math.radians(bearing))
    return x, y


# 결함 1: 일의 종류. kind = other(종류 밖) 또는 종류 id(대조군 — 고치기 전과 같은 종류가 바라는 끝). at = 참 위치(그 표지에서 15m)
D1 = [
    ("1-01", "dev", "other", "강남역 11번 출구", "강남역 11번 출구 앞인데요, 전동 킥보드가 인도에 버려져 있어요"),
    ("1-02", "dev", "other", "신림역 4번 출구", "맨홀 뚜껑이 열려 있어서 구멍이 보여요"),
    ("1-03", "dev", "other", "합정역", "합정역 근처인데요, 가로수가 쓰러져서 길을 막고 있어요"),
    ("1-04", "dev", "other", "종로3가역 1번 출구", "신호등이 고장 나서 불이 꺼져 있어요"),
    ("1-05", "dev", "other", "건대입구역 2번 출구", "건대입구역 2번 출구 앞인데요, 킥보드가 자전거 거치대에 잔뜩 방치돼 있어요"),
    ("1-06", "dev", "other", "사당역", "가로등 옆에 오토바이가 쓰러져 있어요. 사당역 근처예요"),
    ("1-c1", "dev", "litter", "홍대입구역 9번 출구", "누가 쓰레기봉투를 잔뜩 버리고 갔어요"),
    ("1-c2", "dev", "light", "역삼역 3번 출구", "역삼역 3번 출구 앞인데요, 가로등이 깜빡거리다가 아예 꺼졌어요"),
    ("1-c3", "dev", "road", "뚝섬역", "도로에 구멍이 움푹 파여서 위험해요"),
    ("1-c4", "dev", "bike", "서울숲역", "서울숲역 앞인데요, 따릉이가 쓰러져서 길을 막고 있어요"),
    ("1-07", "hold", "other", "서울숲역", "현수막이 찢어져서 바람에 날리고 있어요. 서울숲역 앞이에요"),
    ("1-08", "hold", "other", "홍대입구역 9번 출구", "하수구에서 냄새가 너무 심하게 올라와요. 홍대입구역 9번 출구 근처예요"),
    ("1-09", "hold", "other", "잠실역 8번 출구", "잠실역 8번 출구 앞인데요, 전선이 늘어져서 머리에 닿을 것 같아요"),
    ("1-10", "hold", "other", "역삼역 3번 출구", "공사장 펜스가 넘어져서 인도를 막고 있어요"),
    ("1-11", "hold", "other", "사당역", "버스 정류장 의자가 부서져 있어요. 사당역 근처예요"),
    ("1-12", "hold", "other", "뚝섬역", "뚝섬역 근처인데요, 나무가 말라 죽어서 쓰러질 것 같아요"),
    ("1-c5", "hold", "carcass", "합정역", "합정역 근처인데요, 고양이가 차에 치여서 죽어 있어요"),
    ("1-c6", "hold", "vendor", "강남역 11번 출구", "노점상이 인도에 물건을 잔뜩 쌓아 놨어요"),
    ("1-c7", "hold", "parking", "신림역 4번 출구", "신림역 4번 출구 앞인데요, 불법 주차한 차 때문에 못 지나가요"),
    ("1-c8", "hold", "noise", "건대입구역 2번 출구", "밤마다 음악 소리가 너무 시끄러워요"),
]
# 결함 2: 소리가 같은 길 이름. (id, 반, 참 길, 첫 말(받아 적힌 이름), 일, 묶음, 참 위치를 놓을 표지 · 거리 · 쪽)
D2 = [
    ("2-01", "dev", "통일로", "동일로 타고 가는 중인데요, 도로가 움푹 파여서 위험해요", "road", "큰길", ("구파발역", 300, "연신내역")),
    ("2-02", "dev", "동일로", "동일로 타고 가는 중인데요, 가로등이 꺼져서 깜깜해요", "light", "큰길", ("상계역", 400, "노원역")),
    ("2-03", "dev", "조원로", "초원로인데요, 누가 쓰레기를 잔뜩 버리고 갔어요", "litter", "골목 · 상가 길", None),
    ("2-04", "dev", "사당로2차길", "사당로2자길 골목인데요, 가로등이 꺼져서 깜깜해요", "light", "골목 · 상가 길", None),
    ("2-05", "hold", "통일로", "통일로 타고 가는 중인데요, 동물이 차에 치여 죽어 있어요", "carcass", "큰길", ("독립문역", 300, "홍제역")),
    ("2-06", "hold", "동일로", "통일로 타고 가는 중인데요, 도로에 구멍이 났어요", "road", "큰길", ("중화역", 300, "상봉역")),
    ("2-07", "hold", "초원로", "조원로인데요, 노점이 길을 막고 있어요", "vendor", "골목 · 상가 길", None),
    ("2-08", "hold", "동호로11자길", "동호로11차길 골목이에요, 담배 피우는 사람들이 많아요", "smoking", "골목 · 상가 길", None),
]
# 결함 3: 「○○ 쪽 · 방향 · 가는 길」. (id, 반, 첫 말, 일, 묶음, 참 위치 만드는 법)
D3 = [
    ("3-01", "dev", "천호대로 타고 가는 중인데요, 길동사거리 쪽이에요. 도로가 움푹 파였어요", "road", "큰길", ("along", "천호대로", "길동사거리", 450, "천호역", True)),
    ("3-02", "dev", "강남역 쪽 골목인데요, 가로등이 꺼져 있어요", "light", "골목 · 상가 길", ("off", "강남역", 420, 40)),
    ("3-03", "dev", "서울숲 가는 길인데요, 쓰레기가 잔뜩 버려져 있어요", "litter", "골목 · 상가 길", ("off", "뚝섬역", 250, 200)),
    ("3-04", "dev", "올림픽대로 잠실 방향이요, 동물이 차에 치여 죽어 있어요", "carcass", "자동차전용도로", ("along", "올림픽대로", "반포대교", 900, "한남대교")),
    ("3-05", "hold", "테헤란로 선릉역 쪽인데요, 불법 주차한 차가 길을 막고 있어요", "parking", "큰길", ("along", "테헤란로", "선릉역", 600, "역삼역", True)),
    ("3-06", "hold", "홍대입구역에서 연남동 쪽으로 걸어가는 길이에요, 누가 쓰레기를 버리고 갔어요", "litter", "골목 · 상가 길", ("off", "홍대입구역", 320, 340)),
    ("3-07", "hold", "남부순환로 사당 방면으로 가다가 봤는데요, 고양이가 차에 치여 죽어 있어요", "carcass", "큰길", ("along", "남부순환로", "사당역", 1100, "낙성대역", True)),
    ("3-08", "hold", "보라매공원 쪽 큰길인데요, 가로등이 꺼져 있어요", "light", "골목 · 상가 길", ("off", "보라매공원", 450, 270)),
]
# 결함 4: 「지나고 조금 뒤」. (id, 반, 첫 말, 일, 묶음, (길, 지난 표지, 참 거리 m, 가는 쪽 표지))
D4 = [
    ("4-01", "dev", "강변북로 구리 방향인데요, 성수대교 지나고 조금 뒤에 고양이가 죽어 있어요", "carcass", "자동차전용도로", ("강변북로", "성수대교", 600, "영동대교")),
    ("4-02", "dev", "올림픽대로 타고 가는데요, 한남대교 지나고 조금 가서 도로에 구멍이 났어요", "road", "자동차전용도로", ("올림픽대로", "한남대교", 400, "반포대교")),
    ("4-03", "dev", "차로 테헤란로 가다가 봤는데요, 역삼역 지나고 조금 뒤에 가로등이 꺼져 있었어요", "light", "큰길", ("테헤란로", "역삼역", 350, "선릉역")),
    ("4-04", "dev", "산책하다가 봤는데요, 뚝섬역 지나서 조금 걸어가면 개 한 마리가 주인 없이 돌아다녀요", "stray", "골목 · 상가 길", ("왕십리로", "뚝섬역", 150, "서울숲역")),
    ("4-05", "hold", "내부순환로 타고 가다가요, 정릉 나들목 지나고 조금 뒤에 동물이 죽어 있어요", "carcass", "자동차전용도로", ("내부순환로", "정릉", 800, "길음역")),
    ("4-06", "hold", "동부간선로 의정부 쪽으로 가는데요, 장안교 지나고 조금 뒤에 도로가 움푹 파였어요", "road", "자동차전용도로", ("동부간선로", "장안교", 300, "월릉교")),
    ("4-07", "hold", "버스 타고 천호대로 지나가다 봤는데요, 군자역 지나고 조금 뒤에 노점이 길을 막고 있어요", "vendor", "큰길", ("천호대로", "군자역", 500, "장한평역")),
    ("4-08", "hold", "걸어가다가 봤는데요, 망원역 지나서 조금 가면 쓰레기가 잔뜩 버려져 있어요", "litter", "골목 · 상가 길", ("월드컵로", "망원역", 200, "합정역")),
    ("4-09", "hold", "종로3가역 지나고 조금 뒤에 가로등이 꺼져 있어요", "light", "큰길", ("종로", "종로3가역", 300, "종각역")),
]

# 11-16 이어서(갈래 1~3). 5 = 둘 중 고르기의 「○○ 쪽」 답: 큰길 · 골목 통화를 새 씨앗으로(가상 시민이 그대로 답함).
# 6 = 같은 질문 되풀이: 자동차전용도로 통화를 새 씨앗으로, 「네」 기욺 조건(틀림 10% · 틀린 자리에 「네」 30%).
# 7 = 낱말 속 동물 글자(「냄새가」) · 「○○이 길」: (id, 반, 동물이어야 하나, 자리 표지, 첫 말)
D5 = {"dev": (3101, 3102), "hold": (3201, 3202)}
D6 = {"dev": (3301,), "hold": (3401,)}
D7 = [
    ("7-01", "dev", False, "신림역 4번 출구", "하수구 냄새가 너무 심해요. 신림역 4번 출구 앞이에요"),
    ("7-02", "dev", False, "합정역", "맨홀 덮개가 열려 있어요. 합정역 근처예요"),
    ("7-03", "dev", False, "강남역 11번 출구", "노점이 길을 막고 있어요. 강남역 11번 출구 앞이에요"),
    ("7-04", "dev", False, "역삼역 3번 출구", "트럭이 길을 막고 서 있어요. 역삼역 3번 출구 앞이에요"),
    ("7-c1", "dev", True, "뚝섬역", "강아지가 혼자 돌아다녀요. 뚝섬역 근처예요"),
    ("7-c2", "dev", True, "서울숲역", "새가 다쳐서 못 날아요. 서울숲역 앞이에요"),
    ("7-05", "hold", False, "홍대입구역 9번 출구", "베개가 길에 버려져 있어요. 홍대입구역 9번 출구 근처예요"),
    ("7-06", "hold", False, "사당역", "개인택시가 정류장을 막고 있어요. 사당역 근처예요"),
    ("7-07", "hold", False, "잠실역 8번 출구", "물이 길에 고여 있어요. 잠실역 8번 출구 앞이에요"),
    ("7-08", "hold", False, "건대입구역 2번 출구", "공사 자재가 길을 막고 있어요. 건대입구역 2번 출구 앞이에요"),
    ("7-c3", "hold", True, "역삼역 3번 출구", "고양이가 길에 쓰러져 있어요. 역삼역 3번 출구 앞이에요"),
    ("7-c4", "hold", True, "합정역", "비둘기가 많이 죽어 있어요. 합정역 근처예요"),
]


def build():
    cases, rng = [], random.Random(1116)
    for cid, half, kind, at, first in D1:
        x, y = _pts(at)[0]
        dx, dy = SC.ring_at(rng, 10, 20)
        cases.append({"cid": cid, "defect": 1, "half": half, "first": first, "type": kind, "cat": "역 출구 둘레", "x": x + dx, "y": y + dy, "exit": at,
                      "what": first if kind == "other" else None})
    for cid, half, road, first, kind, cat, spec in D2:
        if spec:
            x, y, head = along(road, *spec)
        else:
            P = _road(road)
            x, y = (float(v) for v in P[len(P) // 2])
            head = None
        cases.append({"cid": cid, "defect": 2, "half": half, "first": first, "type": kind, "cat": cat, "x": x, "y": y, "road": road, "head": head, "truth_road": road})
    for cid, half, first, kind, cat, spec in D3:
        if spec[0] == "along":
            x, y, head = along(*spec[1:])
            road = spec[1]
        else:
            x, y = off(*spec[1:])
            head, road = None, None
        cases.append({"cid": cid, "defect": 3, "half": half, "first": first, "type": kind, "cat": cat, "x": x, "y": y, "road": road, "head": head})
    for cid, half, first, kind, cat, (road, land, dist, toward) in D4:
        x, y, head = along(road, land, dist, toward)
        cases.append({"cid": cid, "defect": 4, "half": half, "first": first, "type": kind, "cat": cat, "x": x, "y": y, "road": road, "head": head, "past": land, "dist": dist})
    for half, seeds in D5.items():
        for seed in seeds:
            for c in [c for c in SC.make_cases(60, seed) if c["cat"] in ("큰길", "골목 · 상가 길")][:12]:
                cases.append(dict(c, cid=f"5-{seed}-{c['id']}", defect=5, half=half))
    for half, seeds in D6.items():
        for seed in seeds:
            for c in [c for c in SC.make_cases(90, seed) if c["cat"] == "자동차전용도로"][:12]:
                cases.append(dict(c, cid=f"6-{seed}-{c['id']}", defect=6, half=half, cond={"LIE": 0.1, "YES": 0.3}))
    for cid, half, animal, at, first in D7:
        x, y = _pts(at)[0]
        dx, dy = SC.ring_at(rng, 10, 20)
        cases.append({"cid": cid, "defect": 7, "half": half, "first": first, "type": "other", "cat": "역 출구 둘레", "x": x + dx, "y": y + dy, "exit": at, "animal": animal, "what": first})
    for n, c in enumerate(cases, 1):
        idx = G.near(c["x"], c["y"], 400)
        d = np.hypot(G.x[idx] - c["x"], G.y[idx] - c["y"]) if len(idx) else np.array([400.0])
        c.update(id=9000 + n, noisy=False, d_land=float(d.min()), d_osm=float(d.min()), gu=L._area_at(G.gu, c["x"], c["y"]), dong=L._area_at(G.dong, c["x"], c["y"]))
    return cases


def watch(c, st, view, said):
    """차례마다: 이 말 뒤의 90% 범위에 참 위치가 드나(그 범위의 격자점 가운데 가장 가까운 것이 45m 안)."""
    clues, matter = S.understood(st)
    R = L.infer(clues) if clues else None
    inside = None
    if R is not None:
        px, py = R["x"][R["cred"]], R["y"][R["cred"]]
        inside = bool(np.hypot(px - c["x"], py - c["y"]).min() <= 45)
    c.setdefault("trace", []).append({"said": said, "q": (view.get("question") or {}).get("id"), "m": (view.get("size") or {}).get("m"), "inside": inside,
                                      "type": matter.get("type"), "chips": view.get("chips"), "route": ((view.get("route") or {}).get("hit") or {}).get("to"),
                                      "cites": (view.get("summary") or {}).get("cites"), "scope": (view.get("matter") or {}).get("scope"), "line": (view.get("matter") or {}).get("line"),
                                      "done": view.get("done"), "animal": matter.get("animal"), "unfound": view.get("unfound")})


def judge(c, r, base_type=None):
    """사례 하나의 바라는 끝을 지켰나 → (지켰나, 까닭)."""
    tr = c.get("trace") or []
    bad = r["end"] in ("틀린 확정", "구간(밖)")
    if c["defect"] == 1:
        final = tr[-1]["type"] if tr else None
        asked_what = any(t["q"] == "what" for t in tr[1:]) or (tr and tr[0]["q"] == "what")
        route = r.get("route_to") or ""
        if c["type"] == "other":
            ok = final == "other" and not asked_what and "담당 확인" in route and not r.get("cites")
            return ok, f"종류 {final} · 「어떤 일로」 {'물음' if asked_what else '없음'} · 넘길 곳 {route or '-'} · 근거 {r.get('cites') or '없음'}"
        want = base_type or c["type"]
        return final == want and not asked_what, f"종류 {final}(바라는 것 {want}) · 「어떤 일로」 {'물음' if asked_what else '없음'}"
    if c["defect"] == 4:
        k = next((n for n, t in enumerate(tr) if "조금" in (t["said"] or "")), None)
        inside = tr[k]["inside"] if k is not None else None
        return bool(inside) and not bad, f"그 말 뒤 범위에 참 위치 {'듦' if inside else '없음'}({tr[k]['m'] if k is not None else '-'}m) · 끝 {r['end']}"
    if c["defect"] == 5:                                  # 둘 중 고르기 답 하나로 끝(좁혀짐)에 닿았나
        by_either = [n for n in range(1, len(tr)) if tr[n - 1]["q"] == "either" and tr[n]["done"] and not tr[n - 1]["done"]]
        return not bad and not by_either, f"끝 {r['end']} · 둘 중 고르기 답으로 끝냄 {len(by_either)} · 둘 중 고르기 {sum(t['q'] == 'either' for t in tr)}번"
    if c["defect"] == 6:                                  # 같은 위치 질문이 범위를 15% 넘게 줄이지 못한 채 세 번 넘게 잇달았나
        run, worst = 1, 1
        for n in range(1, len(tr)):
            same = tr[n]["q"] == tr[n - 1]["q"] and tr[n]["q"] in L.LOCQ and (tr[n]["m"] or 0) > 0.85 * (tr[n - 1]["m"] or 1)
            run = run + 1 if same else 1
            worst = max(worst, run)
        return not bad and worst <= 2, f"끝 {r['end']} · 같은 질문 잇달음 {worst}번 · 질문 {'·'.join(r['asked'])}"
    if c["defect"] == 7:
        animal = tr[-1]["animal"] if tr else None
        again = any(t["q"] == "again" for t in tr) or any(t["unfound"] for t in tr)
        return bool(animal) == c["animal"] and not again, f"동물 {animal or '없음'}(바라는 것 {'있음' if c['animal'] else '없음'}) · 못 찾은 이름 {'있음' if again else '없음'} · 종류 {tr[-1]['type'] if tr else None}"
    return not bad, f"끝 {r['end']} · 확정 거리 {r.get('err_m')}m · {r.get('where')}"


def real():
    """동규가 실제 통화에서 겪은 문장들(11-15)이 여전히 통과하는지 → 실패한 것 목록. --solar면 Solar 다시 읽기까지."""
    def call(*lines):
        st, v = S.turn({"id": "real"}, {"line": {"who": "상담사", "text": "민원 콜센터입니다. 무엇을 도와드릴까요?"}})
        views = []
        for said in lines:
            st, v = S.turn(st, {"line": {"who": "시민", "text": said}})
            if SC.SOLAR:
                st, v = S.turn(st, {"phase": "model"})
            views.append(v)
            if v["question"]:
                st, v = S.turn(st, {"line": {"who": "상담사", "text": v["question"]["say"]}})
        return views
    bad = []
    v = call("복걸로 6길이에요. 금천로 롯데케슬아파트 앞이에요.")[-1]
    ok = "복걸로 6길" in v["unfound"] and v["question"]["id"] == "again" and any("롯데캐슬" in c for c in v["chips"])
    print(f"{'✓' if ok else '✗'} 「복걸로 6길 · 금천로 롯데케슬아파트」 → 못 찾음 {v['unfound']} · 질문 {v['question']['id']} · 단서 {v['chips']}")
    bad += [] if ok else ["복걸로"]
    v = call("신림역 3번 출구, 아 아니다 4번 출구 앞이에요. 쓰레기가 잔뜩 버려져 있어요")[-1]
    ok = "신림역 4번 출구" in v["chips"] and not any("3번" in c for c in v["chips"])
    print(f"{'✓' if ok else '✗'} 「3번 출구, 아 아니다 4번 출구」 → 단서 {v['chips']} · {v['summary']['where']}")
    bad += [] if ok else ["고쳐 말하기"]
    for first in ("가로등이 꺼져서 깜깜해요", "맨홀 뚜껑이 열려 있어서 위험해요"):
        vs = call(first, "신림역 4번 출구 앞이에요")
        qs = [x["question"]["id"] for x in vs if x["question"]]
        ok = "what" not in qs and vs[-1]["matter"]["line"] and vs[0]["question"]["id"] == "where"
        print(f"{'✓' if ok else '✗'} 민원 먼저 「{first}」 → 위치 → 질문 {' → '.join(qs)} · 일 {vs[-1]['matter']['line']}")
        bad += [] if ok else ["민원 먼저"]
    return bad


def main():
    if "--real" in sys.argv:
        bad = real()
        print("실제 통화 문장: " + ("모두 통과" if not bad else f"실패 {bad}"))
        sys.exit(1 if bad else 0)
    cases =[c for c in build() if c["half"] == ARG("--half", c["half"]) and str(c["defect"]) == ARG("--defect", str(c["defect"]))]
    base = json.loads(Path(sys.argv[sys.argv.index("--base") + 1]).read_text(encoding="utf-8")) if "--base" in sys.argv else {}
    out, met = [], 0
    for c in cases:
        c["on_turn"] = watch
        keep = {k: getattr(SC, k) for k in (c.get("cond") or {})}
        for k, v in (c.get("cond") or {}).items():
            setattr(SC, k, v)                             # 이 사례만 시민의 말버릇(틀림 · 「네」 기욺)
        r = SC.run(c, random.Random(f"defect:{c['cid']}"))
        for k, v in keep.items():
            setattr(SC, k, v)
        r["route_to"] = (r.get("route") or {}).get("to") or (c["trace"][-1]["route"] if c.get("trace") else None)
        r["cites"] = c["trace"][-1]["cites"] if c.get("trace") else None
        ok, why = judge(c, r, (base.get(c["cid"]) or {}).get("type"))
        met += ok
        row = {"cid": c["cid"], "defect": c["defect"], "half": c["half"], "ok": ok, "why": why, "end": r["end"], "type": c["trace"][-1]["type"] if c.get("trace") else None,
               "first": r["first"], "asked": r["asked"], "trace": [{k: v for k, v in t.items() if k != "chips"} for t in c["trace"]], "chips": c["trace"][-1]["chips"] if c.get("trace") else []}
        out.append(row)
        print(f"{'✓' if ok else '✗'} {c['cid']} [{c['half']}] {why}\n    「{r['first']}」 → 질문 {' → '.join(r['asked'])}")
    print(f"\n바라는 대로 {met}/{len(out)}" + (f" · Solar 다시 읽기 {S.usage['read']}번 · 토큰 들어감 {S.usage['tokens_in']:,} · 나옴 {S.usage['tokens_out']:,}" if SC.SOLAR else ""))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
