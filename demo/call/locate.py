"""통화로 위치 좁히기의 셈 (numpy. 모델 · 네트워크를 쓰지 않는다). 서울 지명 표(gaz.py) 위에서 돈다.

생각: 지도 위 20m 격자점마다 「진짜 자리가 여기일 가능성」을 두고, 통화에서 얻은 단서마다 「자리가 여기라면 시민이 그렇게 말했을 가능성」(우도)을 곱한다.
- 단서마다 「이 말이 틀렸을 몫」(EPS)을 남긴다: 우도 = (1 − 몫) × 그 단서가 가리키는 곳 + 몫 × 어디든 고르게.
  → 단서와 맞지 않는 점도 0으로 지워지지 않아, 시민이 한 번 틀리게 말해도 진짜 자리가 남는다.
- 화면의 범위 = 가능성이 큰 점부터 모아 합이 90%가 되는 점들. 그 점들이 퍼진 반지름이 DONE_M 이하면 「찾아갈 수 있을 만큼」.
- 다음 질문 = 답으로 남은 가능성이 가장 고르게 갈리는 질문(기대 정보량, 비트). 넘길 곳이 갈리는 질문(일의 조건 · 공원 안팎)이 먼저다.
- 격자점은 서울 전체에 깔지 않는다. 단서가 가리키는 곳(이름 둘레 · 길 · 두 표지 사이 · 구역)에만 만들고, 넓은 구역은 성기게 찍어 「거기일 가능성」만 남긴다.

단서 꼴(JSON, 화면이 들고 다닌다). k = 지명 표의 다듬은 이름, p = [x, y] m, a = ["park" | "gu" | "dong", 번호]:
  {"t":"at","k":…,"how":"바로|근처|모름"}  그 장소 · 길 · 구역(둘레)에 있다      {"t":"pt","p":…,"r":폭,"label":…}  단추로 고른 한 곳
  {"t":"in"|"out","a":…}  구역 안 · 구역 바깥 길                              {"t":"cat","c":"편의점"}  그런 종류가 보인다(약한 단서)
  {"t":"past"|"before","k"|"p":…,"how":…}  그 표지를 지났다 · 못 미쳤다         {"t":"between","k":[…,…] | "p":[…,…]}  두 표지 사이
  {"t":"toward","k":…} · {"t":"head","v":[ux,uy],"label":…}  가는 방향        {"t":"not","p":…,"r":…}  거기는 아니다
스스로 시험:  python3 demo/call/locate.py
"""
import functools
import math
import os
import re

import numpy as np

import gaz

G = gaz.load()
STEP, DONE_M, DONE_ROAD_M, MASS = 20, 50, 100, 0.9     # 끝내는 기준: 범위의 반지름 50m. 길 위는 구간 200m(차로 지나며 찾으니 넓게 잡음 — 추측)
EPS = {"anyof": 0.2, "at": 0.12, "road": 0.04, "pt": 0.05, "in": 0.07, "out": 0.07, "between": 0.07, "past": 0.07, "before": 0.07, "cat": 0.5, "cone": 0.12, "closest": 0.15, "half": 0.1, "rim": 0.1, "core": 0.1, "over": 0.12}   # 단서 종류마다 「이 말이 틀렸을 몫」(이름은 자료가 낡았을 몫까지)
WEAK = 0.3       # 비슷한 이름으로 이은 단서(받아 적기가 틀렸다고 보고 고쳐 이은 것)가 틀렸을 몫. 정확히 맞은 이름(0.12)보다 약하게(11-15)
AROUND = (450.0, 200.0)     # 「○○ 쪽」(11-16): 그 자리에서 450m 안은 고르게, 그 밖은 폭 200m로 줄어든다(90%가 드는 거리 약 800m). 짐작 — 통화 자료로 맞춘 값이 아니다
SIG = {"바로": 18.0, "가까이": 40.0, "근처": 100.0, "모름": 100.0, "보임": 150.0, "쪽": AROUND[0]}        # 「바로 앞 · 옆」 · 「근처」를 몇 m 폭(종 모양의 표준편차)으로 볼지. 90%가 드는 반지름은 그 2.1배
# 가까이 = 「바로 앞에 뭐가 보이세요?」에 댄 이름(「○○ 근처예요」라고 해도 눈앞에 보이는 것이라 40m로 본다 — 추측, 11-14 밤)
KIND_SIG = {"동네": 600.0, "산": 800.0, "역": 250.0, "시장": 200.0, "지점번호": 12.0}      # 이름만 말했을 때 넓게 볼 종류
DIST = {"바로": 40.0, "금방": 120.0, "조금": 400.0, "모름": 900.0}        # 「방금 지났다」 · 「조금 지났다」를 몇 m로 볼지(지수 곡선의 길이. 90%가 드는 거리는 그 2.3배)
# 「○○ 지나고 조금 뒤 · 조금 지나서」를 몇 m로 볼지(11-16 결함 4): 움직인 방법마다 (가까운 끝, 먼 끝) m. 그 사이는 고르게, 밖은 부드럽게 준다. 모두 짐작 — 통화 자료로 맞춘 값이 아니다
#   걷기 20~250m: 몇십 걸음~2분쯤 걸음.  차(일반 찻길) 50~600m: 시속 30km로 몇 초~1분쯤.
#   자동차전용도로 100~900m: 시속 60~80km로 몇 초~40초쯤. 오케스트레이터가 전한 「실제로는 300~900m일 수 있다」와 가상 시민의 「조금 지나서」(90~500m)를 함께 덮게 넓혔다.
#   모름 50~900m: 걷는지 차인지 말이 없으면 넓은 쪽으로. 움직인 방법은 시민의 말(server.MOVE)에서, 자동차전용도로는 길 종류에서 정한다
AFTER = {"걷기": (20.0, 250.0), "차": (50.0, 600.0), "자동차전용도로": (100.0, 900.0), "모름": (50.0, 900.0)}
# 금방 = 차로 달리며 「(다리를) 지나고 바로」: 60km/h면 15초에 250m라 걸어서 지난 「바로」(40m)보다 넓게 본다(11-14 밤, 가상 통화에서 150m 빗나간 틀린 확정이 난 자리)
BIG, MUL = 50000, 200000
SEOUL_M2 = 605e6    # 서울의 넓이(어림). 「틀린 말」의 몫은 서울 어디든 고르게 퍼진다고 본다
EXPRESSWAYS = ["올림픽대로", "동부간선도로", "동부간선로", "강변북로", "서부간선도로", "서부간선로", "언주로", "북부간선도로", "내부순환로", "국회대로", "양재대로",
               "경부고속도로", "우면산로", "강남순환로"]        # 서울시설공단이 관리하는 자동차전용도로 12개 노선(지도 자료의 이름 꼴 포함). 언주로 · 양재대로는 일부 구간만
PARTIAL_EXPRESS = {"언주로", "양재대로"}      # (roadcls, 기본 끔 · 86번) 이름째 목록에 들었지만 일부 구간만 자동차전용인 길


def _xw(i):
    """길 i가 자동차전용도로인가(이름 목록). (roadcls, 기본 끔 · 86번) 언주로 · 양재대로는 지도 자료의 길 등급이 trunk · motorway인 구간만:
    방이역 · 둔촌동역 · 올림픽공원역 앞 양재대로(primary, 일반 구간)의 불법 주차가 자동차전용도로 위로 읽혀 넘길 곳이 경찰 · 번지가 「번지 없음」이 됐다(80번 c09)."""
    r = G.roads[i]
    return r["name"] in EXPRESSWAYS and not ("roadcls" in ON and r["name"] in PARTIAL_EXPRESS and r.get("cls") not in ("trunk", "motorway"))


DIR_NAMES = {"강변북로": ("구리 방향", "일산 방향"), "올림픽대로": ("하남 방향", "김포공항 방향"), "내부순환로": ("성동 방향", "성산 방향"),
             "동부간선도로": ("의정부 방향", "수서 방향"), "동부간선로": ("의정부 방향", "수서 방향")}      # (동쪽 또는 북쪽으로 가는 방향, 반대 방향)
CITY_BRIDGES = {"광진교", "천호대교", "올림픽대교", "잠실대교", "영동대교", "성수대교", "한남대교", "반포대교", "잠수교", "한강대교", "원효대교", "마포대교", "서강대교",
                "양화대교", "성산대교", "월드컵대교", "가양대교", "동작대교", "동호대교", "잠실철교", "행주대교"}   # 서울시가 관리하는 한강 다리(서울시 「한강상 교량 현황」 21곳 중 다리 면 자료에 있는 20곳 — 구리암사대교는 자료에 없음). 청담대교(전용도로) · 강동 · 고덕토평 · 김포 · 미사(한국도로공사) · 방화 · 마곡은 뺌(11-21)
CITY_PARKS = ["서울숲", "보라매공원", "월드컵공원", "남산공원", "북서울꿈의숲", "여의도공원", "선유도공원", "서울어린이대공원", "어린이대공원",
              "북서울 꿈의 숲", "평화의공원", "하늘공원", "노을공원", "난지천공원", "푸른수목원"]   # 시가 직접 관리하는 큰 공원(일부). 지도 자료의 이름 「북서울 꿈의 숲」(띄어 씀),
# 월드컵공원을 이루는 평화의공원 · 하늘공원 · 노을공원 · 난지천공원(서울시 보도자료)은 따로 된 이름으로 들어 있다. 공원별로 맡는 곳은 routes.json의 park_to(11-21)
PROM = {"편의점": 0.8, "카페": 0.7, "은행": 0.8, "약국": 0.7, "주유소": 0.9, "빵집": 0.7, "음식점": 0.45, "가게": 0.45, "아파트": 0.5, "건물": 0.6,
        "사무실": 0.4, "학원": 0.45, "숙박": 0.6, "종교시설": 0.8, "정류장": 0.7, "시설": 0.5, "화장실": 0.7, "놀이터": 0.7, "주차장": 0.6,
        "물가": 0.5, "광장": 0.5, "숲": 0.5, "동물사": 0.5, "산책길": 0.5, "폭포": 0.5, "문": 0.5}     # 물어볼 표지로서 눈에 띄는 정도(없는 종류는 1)


def pack(ix, iy):
    return (np.asarray(ix, np.int64) + BIG) * MUL + (np.asarray(iy, np.int64) + BIG)


def unpack(keys):
    return (keys // MUL - BIG) * float(STEP), (keys % MUL - BIG) * float(STEP)


_tm = {}


def _tmpl(rc):
    if rc not in _tm:
        a = np.arange(-rc, rc + 1)
        ox, oy = np.meshgrid(a, a)
        m = ox * ox + oy * oy <= rc * rc
        _tm[rc] = (ox[m], oy[m])
    return _tm[rc]


def discs(xs, ys, radius, stride=1):
    """점들 둘레 radius m 안의 격자점(겹침 포함)."""
    s = STEP * stride
    ox, oy = _tmpl(int(radius // s) + 1)
    cx, cy = np.round(np.atleast_1d(xs) / s).astype(np.int64), np.round(np.atleast_1d(ys) / s).astype(np.int64)
    return pack((cx[:, None] + ox[None, :]).ravel() * stride, (cy[:, None] + oy[None, :]).ravel() * stride)


def box_keys(x0, y0, x1, y1, stride=1):
    s = STEP * stride
    ix, iy = np.meshgrid(np.arange(math.floor(x0 / s), math.ceil(x1 / s) + 1), np.arange(math.floor(y0 / s), math.ceil(y1 / s) + 1))
    return pack(ix.ravel() * stride, iy.ravel() * stride)


def in_ring(x, y, ring):
    inside = np.zeros(len(x), bool)
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
        if y1 != y2:
            inside ^= ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1)
    return inside


_rk = {}


def road_keys(i):
    """길 i의 선에서 40m 안의 격자점(정렬됨)."""
    if i not in _rk:
        r = G.road_xy(i)
        _rk[i] = np.unique(discs(r[:, 0], r[:, 1], 40))
    return _rk[i]


def area_of(a):
    return {"park": G.parks, "gu": G.gu, "dong": G.dong}[a[0]][a[1]]


def ring_dist(x, y, ring):
    """점들에서 고리(닫힌 꺾은선)까지의 거리(m)."""
    ax, ay = ring[:, 0], ring[:, 1]
    dx, dy = np.roll(ax, -1) - ax, np.roll(ay, -1) - ay
    l2 = np.where(dx * dx + dy * dy > 0, dx * dx + dy * dy, 1.0)
    out = np.empty(len(x))
    step = max(1, 2_000_000 // max(1, len(ax)))           # 메모리를 200만 칸 안으로 나눠 셈한다
    for j in range(0, len(x), step):
        X, Y = x[j:j + step, None], y[j:j + step, None]
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / l2, 0.0, 1.0)
        out[j:j + step] = np.hypot(X - (ax + t * dx), Y - (ay + t * dy)).min(axis=1)
    return out


def bridge_dist(i, x, y):
    """(bridgeline · 75번) 점들에서 다리 i의 면까지 거리(m, 면 안은 0)."""
    d = np.full(len(x), 1e9)
    for ring in G.bridge[i]:
        d = np.minimum(d, np.where(in_ring(x, y, np.vstack((ring, ring[:1]))), 0.0, ring_dist(x, y, ring)))
    return d


@functools.lru_cache(maxsize=None)
def bridge_span(i):
    """다리 i의 면이 걸친 길이(m, 면을 싸는 상자의 대각선)."""
    p = np.vstack(G.bridge[i])
    return float(np.hypot(*(p.max(axis=0) - p.min(axis=0))))


def _bridges(r, n=None, ctx=None):
    """resolve() 결과 가운데 면을 아는 다리의 장소 번호들. 그 통화에 그 다리와 닿는 공원 · 광장 말이 함께 있을 때만(ctx["bp"]) — 다리만 댄 말(「올림픽대교 위예요」)은 전처럼 가운데 점으로 읽는다.
    (bridgelong · 75번, 기본 끔 · BRIDGE_ON) 길이가 2 × BIG_M(120m)을 넘는 다리 · 고가는 혼자 나와도 면으로: 가운데 점 둘레 60m는 그 다리의 한 토막일 뿐이라 이름 하나로는 한 점이 서지 않는다(보라매고가는 1.6km — 「보라매고가 바로 앞」을 가운데 점으로 확정해 193m 틀림). 짧은 다리(묵동교 75m)는 전처럼 한 점."""
    if "bridgeline" not in ON or ctx is None:
        return []
    ids = [i for i in r.get("ids") or () if i in G.bridge]
    return ids if n in ctx.get("bp", ()) else [i for i in ids if "bridgelong" in ON and bridge_span(i) > 2 * BIG_M]


_wr = {}


def water_ring(r):
    """(lakerim · 75번) resolve() 결과가 호수 · 연못 하나의 테두리 점들(공원 안 이름의 「물가」, 처음과 끝이 이어지는 고리)이면 그 고리, 아니면 None.
    하천처럼 처음과 끝이 떨어진 선은 고리가 아니다."""
    ids = r.get("ids") or []
    if len(ids) < 4 or not all(G.pk0 <= i < G.pk1 and G.kind[i] == "물가" for i in ids) or len({G.name[i] for i in ids}) != 1:
        return None
    key = (ids[0], len(ids))
    if key not in _wr:
        ring = np.column_stack((r["x"], r["y"]))
        step = np.hypot(*np.diff(ring, axis=0).T)
        _wr[key] = ring if math.hypot(*(ring[0] - ring[-1])) <= max(1.5 * float(step.max()), 60.0) else None
    return _wr[key]


def _parks_of(key):
    """다듬은 이름이 가리키는 공원 · 광장 구역들(같은 이름의 공원이 둘이면 둘 다)."""
    return [area_of(a) for a in resolve(key)["areas"] if a[0] == "park"]


_self = None


def self_area(i):
    """(selfname · 75번) 장소 i가 구역(공원 · 광장)의 자기 이름 점인가: 그 구역 한가운데에 찍힌 이름표일 뿐 눈앞에 보이는 표지가 아니다."""
    global _self
    if _self is None:
        names = {gaz.norm(a["name"]) for a in G.parks}
        _self = {j for j in range(G.shop0) if G.kind[j] == "공원" and gaz.norm(G.name[j]) in names}
    return i in _self


def resolve(key):
    """다듬은 이름 → 가리키는 것들: 장소 점들 · 길 · 구역. 공원 경계가 있으면 같은 이름의 공원 점은 뺀다(경계가 더 정확하다).
    「통일로|동일로」처럼 |로 이은 이름(소리가 같아 하나로 정하지 않은 것, 11-16)은 모두를 합친다."""
    px, py, kinds, roads, areas, ids = [], [], [], [], [], []
    for kind, i in (r for k in str(key).split("|") for r in G.refs(k)):
        if kind == "p":
            px.append(G.x[i]), py.append(G.y[i]), kinds.append(G.kind[i]), ids.append(i)
        elif kind == "r":
            roads.append(i)
        else:
            areas.append((kind, i))
    if any(a[0] == "park" for a in areas):
        keep = [k != "공원" for k in kinds]
        px, py, kinds, ids = ([v for v, m in zip(lst, keep) if m] for lst in (px, py, kinds, ids))
    if "dupshop" in ON and len(ids) > 1:
        px, py, kinds, ids = _dupshop(px, py, kinds, ids)
    return {"x": np.asarray(px, float), "y": np.asarray(py, float), "kinds": kinds, "roads": roads, "areas": areas, "ids": ids}


def _dupshop(px, py, kinds, ids):
    """(dupshop · 82번) 가게 자료에 같은 지점 이름 · 같은 종류가 100m 안에 두 줄이면 한 가게로 본다(두 줄의 가운데 한 점).
    「아트박스 강남점」이 82m 떨어진 두 줄이라 「아트박스 바로 앞」이 두 덩어리로 갈려 50m 안에 들지 못하고 묻기만 거듭했다(동규 통화 11-21).
    이름 · 종류로 먼저 묶어 같은 이름끼리만 견준다(점마다 모든 점과 견주면 「GS25」 3,596곳에 1.9초)."""
    groups = {}
    for n, i in enumerate(ids):
        if G.shop0 <= i < G.shop1:                        # 가게 자료 줄만(공원 안 이름 · 물가 테두리 점은 그 뒤에 붙어 있다)
            groups.setdefault((gaz.norm(G.name[i]), kinds[n]), []).append(n)
    into = {}                                             # 합쳐지는 줄 → 남는 줄
    for idx in groups.values():
        keep = []
        for n in idx:
            j = next((k for k in keep if math.hypot(px[k] - px[n], py[k] - py[n]) <= 100), None)
            (keep.append(n) if j is None else into.setdefault(j, []).append(n))
    if not into:
        return px, py, kinds, ids
    px, py = list(px), list(py)
    for j, ns in into.items():
        px[j], py[j] = sum(px[k] for k in [j] + ns) / (len(ns) + 1), sum(py[k] for k in [j] + ns) / (len(ns) + 1)
    gone = {n for ns in into.values() for n in ns}
    return tuple([v for n, v in enumerate(lst) if n not in gone] for lst in (px, py, kinds, ids))


def _near_map(px, py, sigma):
    """점들 둘레의 우도 지도 → (정렬된 격자점, 우도). 점마다 더하지 않고 가장 가까운 한 곳으로 셈한다(지점이 몰린 곳이 근거 없이 커지지 않게)."""
    ox, oy = _tmpl(int(min(3 * sigma, 600) // STEP) + 1)
    cx, cy = np.round(px / STEP).astype(np.int64), np.round(py / STEP).astype(np.int64)
    ix, iy = cx[:, None] + ox[None, :], cy[:, None] + oy[None, :]
    d2 = (ix * STEP - px[:, None]) ** 2 + (iy * STEP - py[:, None]) ** 2
    val = np.exp(-d2 / (2 * sigma * sigma)).ravel()
    keys = pack(ix.ravel(), iy.ravel())
    order = np.argsort(keys, kind="stable")
    uk, start = np.unique(keys[order], return_index=True)
    return uk, np.maximum.reduceat(val[order], start)


def _lookup(keys, mk, mv):
    out = np.zeros(len(keys))
    if len(mk):
        pos = np.clip(np.searchsorted(mk, keys), 0, len(mk) - 1)
        hit = mk[pos] == keys
        out[hit] = mv[pos[hit]]
    return out


def _road_sig(sig, kinds, ctx):
    """(roadfloor) 자동차전용도로 이야기 중에 차에서 보이지 않을 이름(가게 · 학원 · 건물)은 폭을 150m 아래로 잡지 않는다(33번 3-2)."""
    if "roadfloor" in ON and ctx and ctx.get("roads") and any(_xw(i) for i in ctx["roads"]) and kinds and not any(k in gaz.ROADSIDE for k in kinds):
        return max(sig, 150.0)
    return sig


def _sigma(c, kinds):
    if c.get("sig"):
        return float(c["sig"])                            # 단서가 폭을 들고 왔다(열린 확인 2판의 「보이는 둘레」)
    how = c.get("how") or "모름"
    if how in ("보임", "모름", "근처") and "farsee" in ON and str(c.get("k") or "").split("|")[0] in G.far_seen():
        return 600.0                                      # (farsee, 기본 끔 · 71번) 「롯데타워가 보여요」 · 「잠실롯데타워요」: 이름난 큰 건물은 멀리서도 보여 그 이름을 댄다(현장 4번 통화의 자리는 타워에서 566m). 「바로 앞」이라고 하면 그대로
    if kinds and all(k == "별명" for k in kinds) and how != "바로":
        return 25.0                                       # 상담사가 확인받은 자리에 붙인 별명: 그 자리 둘레(핀의 오차쯤)
    if how in ("모름", "근처", "가까이") and kinds:
        return max(SIG[how], max(KIND_SIG.get(k, 0) for k in kinds))
    return SIG.get(how, 100.0)


LAKE_IN = 0.1        # (lakerim) 물 안쪽(테두리에서 10m 넘게 안)의 몫. 0이 아닌 것은 테두리 자료가 어림이고 다리 · 섬이 있어서
BIG_M = float(os.environ.get("CALL_BIGM", "60"))     # (bigplace) 이보다 작은 곳은 한 점으로 본다. 60 = 확정한 점이 60m 넘게 어긋날 수 있는 크기(가상 통화가 「한 점」으로 세는 한계와 같게). 견주어 잴 때 CALL_BIGM=40


def _exts(r, sig):
    """(bigplace, 기본 켬 · 60번) 이름의 점마다 그 장소의 크기(m, gaz.ext). BIG_M보다 작거나 지금 폭으로 선 범위(90%가 드는 반지름 = 폭 × 2.1)가 그 장소를 다 덮으면 0. 하나도 없으면 None.
    점-반지름 방법(58번 표 1의 19번)대로 기준 대상의 크기를 범위에 더한다: 학교 · 시장 · 큰 건물 · 역처럼 넓은 곳은 그 크기 안을 고르게 보고, 「바로 앞」의 폭은 그 밖에서부터 센다.
    ponytail: 장소를 원으로 어림한다(길쭉한 학교는 실제보다 넓게 잡힌다). 더 좁히려면 면의 테두리까지의 거리로."""
    if "bigplace" not in ON or not r.get("ids") or len(r["ids"]) > 40:
        return None
    e, lim = G.ext[r["ids"]], max(2.1 * sig, BIG_M)
    return np.where(e > lim, e, 0.0) if (e > lim).any() else None


def _big(i):
    """(bigplace) 장소 i를 가리키는 단서(pt)에 붙일 크기 칸. 크기 표에 없는 곳(한 점으로 봐도 되는 곳)은 빈 칸."""
    return {"ext": round(float(G.ext[i]), 1)} if "bigplace" in ON and G.ext[i] > 0 else {}


def _flat(c, sig=None):
    """(bigplace) 단서(pt)가 가리킨 장소의 크기(m). _exts와 같은 규칙으로, 작거나 그 폭으로 선 범위가 다 덮으면 0."""
    e = c.get("ext", 0)
    return e if e > max(2.1 * (c.get("r", 100.0) if sig is None else sig), BIG_M) else 0


def _context(clues):
    """단서들에서 먼저 정해 둘 것: 지금 말하는 길, 표지의 자리(길 위로 당겨 붙임), 가는 방향."""
    roads = []
    for c in clues:
        if c["t"] == "at" and "k" in c:
            r = resolve(c["k"])
            if r["roads"] and not len(r["x"]) and not r["areas"]:
                roads += r["roads"]
    rxy = np.vstack([G.road_xy(i) for i in roads]) if roads else None
    said_head = next((tuple(c["v"]) for c in reversed(clues) if c["t"] == "head"), None)

    def anchor(key=None, p=None):
        """표지 하나의 자리. 길 이야기 중이면 그 길 위의 가장 가까운 점으로 당긴다(다리 가운데 → 다리가 길과 만나는 곳)."""
        if p is None:
            r = resolve(key)
            if r["areas"] and not len(r["x"]):
                ring = area_of(r["areas"][0])["ring"]
                r = {"x": np.array([ring[:, 0].mean()]), "y": np.array([ring[:, 1].mean()]), "kinds": []}
            if not len(r["x"]):
                return None
            if r.get("ids") and all(G.rp0 <= i < G.rp1 for i in r["ids"]):        # 나가는 길 · 들어오는 길: 방향을 알면 그 방향의 점만, 모르면 어느 점이든(33번 3-3)
                q = [(float(r["x"][m]), float(r["y"][m])) for m, i in enumerate(r["ids"]) if said_head is None or float(G.rhead[i - G.rp0] @ np.asarray(said_head)) > 0]
                if not q:
                    return None
                return anchor(p=q[0]) if len(q) == 1 else {"any": [anchor(p=s_) for s_ in q]}
            if rxy is not None and len(r["x"]) >= 2 and r.get("ids"):     # 길에서 보이는(150m 안) 같은 이름이 150m 넘게 퍼져 있으면 한 점으로 정하지 않는다
                pts = np.column_stack((r["x"], r["y"]))
                on = np.hypot(pts[:, None, 0] - rxy[None, ::3, 0], pts[:, None, 1] - rxy[None, ::3, 1]).min(1) < 150
                q, ids = pts[on], [i for i, m in zip(r["ids"], on) if m]
                if len(q) >= 2:
                    dd = np.hypot(q[:, None, 0] - q[None, :, 0], q[:, None, 1] - q[None, :, 1])
                    i, j = np.unravel_index(int(dd.argmax()), dd.shape)
                    if dd[i, j] > 150:
                        if dd[i, j] < 4000 and all(getattr(G, "node0", 0) <= k < getattr(G, "node1", 0) and G.kind[k] in ("터널", "다리") for k in ids):
                            return {"ends": [anchor(p=tuple(q[i])), anchor(p=tuple(q[j]))]}      # 표준노드링크의 긴 터널 · 다리: 두 끝. 어느 끝인지는 가는 방향으로 정한다
                        keep = []
                        for s_ in q:
                            if all(math.hypot(s_[0] - k[0], s_[1] - k[1]) > 40 for k in keep):
                                keep.append(s_)
                        if len(keep) > 12:
                            return None                       # 길가에 같은 이름이 너무 많다: 기준으로 쓰지 않는다
                        return {"any": [anchor(p=tuple(s_)) for s_ in keep]}       # 분기점의 여러 갈래처럼 어느 점인지 모른다: 어느 점이든(11-14 밤, 「성산대교북단 막 지나자마자」를 1.2km 떨어진 갈래로 확정한 일)
            bridges = [n for n, kd in enumerate(r["kinds"]) if kd == "다리"]
            if bridges:                               # 같은 이름의 나들목 · 정류장보다 다리 자체를 기준으로
                j = bridges[0]
            elif rxy is not None:
                j = int(np.argmin(np.hypot(r["x"][:, None] - rxy[None, ::5, 0], r["y"][:, None] - rxy[None, ::5, 1]).min(1)))
            elif len(r["x"]) <= 3:
                j = 0
            else:
                return None                           # 지점이 많은 이름은 「지났다 · 못 미쳤다」의 기준으로 쓰지 않는다
            p = (float(r["x"][j]), float(r["y"][j]))
        if rxy is not None:
            d = np.hypot(rxy[:, 0] - p[0], rxy[:, 1] - p[1])
            if d.min() < 1500:
                p = rxy[int(np.argmin(d))]
        return (float(p[0]), float(p[1]))
    pos, ends, struct = {}, {}, set()
    pts_of = lambda a: next(iter(a.values())) if isinstance(a, dict) else [a]       # noqa: E731
    mid = lambda a: (sum(p[0] for p in pts_of(a)) / len(pts_of(a)), sum(p[1] for p in pts_of(a)) / len(pts_of(a))) if isinstance(a, dict) else a     # noqa: E731
    for n, c in enumerate(clues):
        if c["t"] in ("past", "before", "toward"):
            a = anchor(c.get("k"), c.get("p"))
            if isinstance(a, dict):
                ends[n] = pts_of(a)
                if "ends" in a:
                    struct.add(n)
            pos[n] = mid(a)
        elif c["t"] == "between":
            ab = [anchor(k) for k in c["k"]] if "k" in c else [anchor(p=p) for p in c["p"]]
            near_end = lambda a, b: min(pts_of(a), key=lambda e: math.hypot(e[0] - mid(b)[0], e[1] - mid(b)[1])) if isinstance(a, dict) and b else a    # noqa: E731
            pos[n] = [near_end(ab[0], ab[1]), near_end(ab[1], ab[0])]          # 긴 터널 · 다리 · 분기점 「사이」는 서로 마주 보는 점끼리
    head = next((tuple(c["v"]) for c in reversed(clues) if c["t"] == "head"), None)
    if head is None:                                    # 방향을 말하지 않았어도 표지의 순서로 안다: 「A 지났고 B는 아직」 → A에서 B 쪽
        first = lambda t: next((pos[n] for n, c in enumerate(clues) if c["t"] == t and pos.get(n)), None)   # noqa: E731
        a, b = first("past") or first("before"), first("before") if first("past") else None
        b = b or first("toward")
        if a and b and math.hypot(b[0] - a[0], b[1] - a[1]) > 30:
            n = math.hypot(b[0] - a[0], b[1] - a[1])
            head = ((b[0] - a[0]) / n, (b[1] - a[1]) / n)
    if head:                                            # 「○○터널 지났다」 = 가는 쪽 끝(나오는 곳)을 지났다, 「아직」 = 들어가는 끝 앞. 분기점의 여러 갈래는 방향을 알아도 어느 갈래인지 모른다
        for n in struct:
            e = ends.pop(n)
            pr = [p[0] * head[0] + p[1] * head[1] for p in e]
            pos[n] = e[int(np.argmax(pr))] if clues[n]["t"] in ("past", "toward") else e[int(np.argmin(pr))]
    bp = set()
    if "bridgeline" in ON:                               # (bridgeline · 75번) 공원 · 광장 말(그 구역의 상자에서 100m 안)이나 길 이름(그 길이 다리 면에서 60m 안을 지남)과 함께 나온 다리: 「망원한강공원 … 양화대교 밑」 · 「도림천 자전거길 … 도림천고가도로교 밑」
        boxes = [ar["box"] for c in clues if "k" in c and c["t"] in ("at", "rim", "core") for ar in _parks_of(c["k"])] + [area_of(c["a"])["box"] for c in clues if c["t"] == "in" and c["a"][0] == "park"]
        lines = [G.road_xy(i) for c in clues if c["t"] == "at" and "k" in c for i in resolve(c["k"])["roads"]] if "bridgeroad" in ON else []      # 이름이 길이면서 점이기도 한 것(「도림천 자전거길」)까지  (bridgeroad · 75번 후보 2: 길 이름과 함께 나온 다리. 끄면 #138처럼 공원 · 광장 말과 함께일 때만)
        for n, c in enumerate(clues) if boxes or lines else ():
            if c["t"] == "at" and "k" in c:
                for i in resolve(c["k"]).get("ids") or ():
                    if i in G.bridge and (any(ring[:, 0].max() > b[0] - 100 and ring[:, 0].min() < b[2] + 100 and ring[:, 1].max() > b[1] - 100 and ring[:, 1].min() < b[3] + 100 for ring in G.bridge[i] for b in boxes)
                                          or any(float(bridge_dist(i, ln[:, 0], ln[:, 1]).min()) <= 60 for ln in lines)):
                        bp.add(n)
    return {"roads": roads, "rxy": rxy, "pos": pos, "head": head, "ends": ends, "bp": bp}


def _pos_near(ctx, n, x, y):
    """단서 n의 기준 자리. 방향을 몰라 끝이 둘이면 (x, y)에 가까운 끝."""
    e = ctx.get("ends", {}).get(n)
    return min(e, key=lambda p: math.hypot(p[0] - x, p[1] - y)) if e else ctx["pos"].get(n)


SPEED = {"자동차전용도로": 1000.0, "길": 500.0}             # 지나고 「몇 분」을 거리로: 자동차전용도로 60km/h, 그 밖의 찻길 30km/h (m/분)


def _ahead(c, ctx):
    """「○○ 지나고 N분쯤」 → (가운데 거리 m, 폭 m). 폭은 거리의 절반(적어도 100m)."""
    express = any(_xw(i) for i in ctx["roads"])
    d = SPEED["자동차전용도로" if express else "길"] * float(c["min"])
    return d, max(100.0, 0.5 * d)


def _support(n, c, ctx):
    """단서가 가리키는 곳의 격자점 → (점들, 종류). fine = 촘촘히, many = 지점이 많은 이름, area = 넓은 구역(성기게). 없으면 None."""
    t = c["t"]
    if t == "pt":
        if c.get("walk"):                                 # (walkmin · 53번) 「○○에서 걸어서 N분」의 고리: 600m로 자르면 먼 쪽이 잘린다
            rad = min(c["ring"] + 2.5 * c.get("r", 100), 1800)
            return discs(c["p"][0], c["p"][1], rad, 1 if rad <= 700 else 2), "fine"
        return discs(c["p"][0], c["p"][1], min((c.get("ring") or 0) + 3 * c.get("r", 100), 600) + _flat(c)), "fine"
    if t == "anyof":                                      # (facil · 53번) 동 이름 없이 말한 시설: 지금 범위 안의 그런 곳 가운데 하나
        ps = np.asarray(c["ps"], float)
        return discs(ps[:, 0], ps[:, 1], min(3 * c.get("r", 100), 600)), "fine"
    if t == "at":
        r = resolve(c["k"])
        parts, cls = [], "fine"
        parts += [road_keys(i) for i in r["roads"]]
        if len(r["x"]) and c.get("nearest"):
            st = [k == "역" for k in r["kinds"]]
            parts.append(discs(r["x"][st], r["y"][st], 1500, 2))      # 「가장 가까운 역」: 그 역이 다른 역보다 가까운 곳(1.5km까지)
        elif len(r["x"]):
            sig = _road_sig(_sigma(c, r["kinds"]), r["kinds"], ctx)
            if len(r["x"]) > 40:
                cls = "many"
                if len(r["x"]) <= 2500:
                    parts.append(discs(r["x"], r["y"], min(2.5 * sig, 300)))
            elif c.get("how") == "쪽":
                parts.append(discs(r["x"], r["y"], AROUND[0] + 2 * AROUND[1], 2))
            elif _bridges(r, n, ctx):                         # (bridgeline · 75번) 다리는 가운데 한 점이 아니라 그 면을 따라(한강 다리는 1km 넘는다)
                pts = np.vstack([ring for i in _bridges(r, n, ctx) for ring in G.bridge[i]])
                parts.append(discs(pts[:, 0], pts[:, 1], max(min(3 * sig, 900), 60.0), 1 if sig <= 200 else 2))
                parts.append(discs(r["x"], r["y"], min(3 * sig, 900), 1 if sig <= 200 else 2))
            elif "lakerim" in ON and water_ring(r) is not None:      # (lakerim · 75번) 테두리 점 사이(많게는 160m)도 비지 않게 20m마다
                ring = water_ring(r)
                seg = np.vstack((ring, ring[:1]))
                pts = np.vstack([a + (b - a) * np.linspace(0, 1, max(2, int(math.hypot(*(b - a)) // 20) + 1))[:, None] for a, b in zip(seg[:-1], seg[1:])])
                parts.append(discs(pts[:, 0], pts[:, 1], max(min(3 * sig, 900), 60.0), 1 if sig <= 200 else 2))
            else:
                e = _exts(r, sig)
                parts.append(discs(r["x"], r["y"], min(3 * sig, 900) + (float(e.max()) if e is not None else 0), 1 if sig <= 200 else 2))
        for a in r["areas"]:
            x0, y0, x1, y1 = area_of(a)["box"]
            n_cells = (x1 - x0 + 500) * (y1 - y0 + 500) / STEP ** 2
            if a[0] == "park" and n_cells <= 60000:
                parts.append(box_keys(x0 - 250, y0 - 250, x1 + 250, y1 + 250))
            else:
                cls = cls if parts else "area"
                parts.append(box_keys(x0, y0, x1, y1, max(2, int(math.ceil(math.sqrt(n_cells / 6000))))))
        return (np.concatenate(parts), cls) if parts else None
    if t in ("in", "out"):
        x0, y0, x1, y1 = area_of(c["a"])["box"]
        n_cells = (x1 - x0 + 500) * (y1 - y0 + 500) / STEP ** 2
        return box_keys(x0 - 250, y0 - 250, x1 + 250, y1 + 250, max(1, int(math.ceil(math.sqrt(n_cells / 60000))))), "fine" if n_cells <= 60000 else "area"
    if t in ("rim", "core"):                              # (edgeband · 75번) 구역의 테두리 띠 · 한가운데
        pad, parts = 3 * c.get("w", 25.0), []
        for ar in _parks_of(c["k"]):
            x0, y0, x1, y1 = ar["box"]
            n_cells = (x1 - x0 + 2 * pad) * (y1 - y0 + 2 * pad) / STEP ** 2
            parts.append(box_keys(x0 - pad, y0 - pad, x1 + pad, y1 + pad, max(1, int(math.ceil(math.sqrt(n_cells / 60000))))))
        return (np.concatenate(parts), "fine") if parts else None
    if t == "between":
        a, b = ctx["pos"].get(n) or (None, None)
        if not a or not b:
            return None
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        pad = 0.2 * d + 120
        return box_keys(min(a[0], b[0]) - pad, min(a[1], b[1]) - pad, max(a[0], b[0]) + pad, max(a[1], b[1]) + pad, 1 if d < 3000 else 2), "fine"
    if t in ("past", "before"):
        a = ctx["pos"].get(n)
        if not a or c.get("flat"):
            return None                                   # 「지났다 · 아직」만 가르는 단서(_q_next)는 새 후보 자리를 깔지 않는다
        radius = min(2.5 * DIST[c.get("how") or "모름"], 2000)
        if c.get("how") == "조금":
            radius = AFTER[_move(c, ctx)][1] * 1.4
        if c.get("min") and "min" not in OFF:              # 「지나고 2분쯤」: 속도 × 시간만큼 앞을 가운데로
            d, sig = _ahead(c, ctx)
            radius = min(d + 2 * sig, 9000)
        step = 1 if radius <= 1000 else 2 if radius <= 3000 else 4
        return np.concatenate([discs(e[0], e[1], radius, step) for e in ctx["ends"].get(n) or [a]]), "fine"
    return None


def _like(n, c, keys, x, y, ctx):
    """단서 하나가 가리키는 정도(0~1)를 격자점들에서 셈한다. 「틀렸을 몫」은 infer가 섞는다. 쓸 수 없는 단서면 None."""
    t = c["t"]
    if t == "pt":
        s = c.get("r", 100.0)
        if _flat(c):                                      # (bigplace) 넓은 장소를 가리킨 답: 그 크기 안은 고르게, 밖은 폭 s로
            d = np.maximum(0.0, np.hypot(x - c["p"][0], y - c["p"][1]) - c["ext"])
            return np.exp(-(d - (c.get("ring") or 0.0)) ** 2 / (2 * s * s))
        if c.get("ring") is not None:                     # 「○○에서 스무 걸음쯤」: 표지 둘레의 고리(33번 2-2)
            return np.exp(-(np.hypot(x - c["p"][0], y - c["p"][1]) - c["ring"]) ** 2 / (2 * s * s))
        return np.exp(-((x - c["p"][0]) ** 2 + (y - c["p"][1]) ** 2) / (2 * s * s))
    if t == "anyof":
        ps, s = np.asarray(c["ps"], float), c.get("r", 100.0)
        return np.exp(-np.min((x[:, None] - ps[None, :, 0]) ** 2 + (y[:, None] - ps[None, :, 1]) ** 2, axis=1) / (2 * s * s))
    if t == "closest":                                    # 「(보기 넷 가운데) A가 가장 가까워요」: A가 다른 보기보다 가까운 구역, 멀수록 조금씩(33번 2-4)
        dA = np.hypot(x - c["p"][0], y - c["p"][1])
        dO = np.min([np.hypot(x - a, y - b) for a, b in c["others"]], axis=0) if c.get("others") else np.full(len(x), 1e9)
        return np.exp(-dA / c.get("s", 600.0)) / (1.0 + np.exp(np.clip((dA - dO) / 60.0, -50, 50)))
    if t == "cone":                                       # 「○○에서 △△ 쪽」: 표지에서 본 각이 60도 안(거리는 고리가 맡는다, 33번 2-3)
        vx, vy = x - c["o"][0], y - c["o"][1]
        n = np.hypot(vx, vy) + 1e-9
        return np.where((n < 5) | ((vx * c["v"][0] + vy * c["v"][1]) / n >= c.get("cos", 0.5)), 1.0, c.get("f", 0.15))      # f: (compass · 75번) 시민이 스스로 댄 방위 말은 그쪽 밖을 더 낮게(0.15로는 둘레의 3분의 2인 「밖」이 90% 범위에 그대로 남았다)
    if t == "half":                                       # 둘 중 고르기의 「○○ 쪽」: 범위를 가른 선의 그쪽 반을 고르게(그 반의 가운데에 봉우리를 두지 않는다, 11-16)
        tt = (x - c["o"][0]) * c["v"][0] + (y - c["o"][1]) * c["v"][1] - c["cut"]
        return 1.0 / (1.0 + np.exp(np.clip(-c["side"] * tt / 25.0, -50, 50)))
    if t == "not":
        return np.where(np.hypot(x - c["p"][0], y - c["p"][1]) <= c.get("r", 80), c.get("f", 0.1), 1.0)      # f: 무른 「아니다」(「둘 다 아니에요」는 0.4, 33번 1-4)
    if t == "over":                                       # (farsee2 · 75번) 「호수 건너편에 ○○가 보여요」: 그 자리에서 ○○ 쪽으로 그은 선(600m까지)이 물 위를 40m 넘게 지나는 곳. 아니면 0.15
        ring = water_ring(resolve(c["k"]))
        if ring is None:
            return None
        closed, vx, vy = np.vstack((ring, ring[:1])), c["p"][0] - x, c["p"][1] - y
        dist = np.hypot(vx, vy) + 1e-9
        steps = np.linspace(0.0, 1.0, 16)[1:]
        reach = np.minimum(dist, 600.0)
        wet = sum(in_ring(x + vx / dist * reach * s_, y + vy / dist * reach * s_, closed) for s_ in steps) * reach / len(steps)
        return np.where(wet >= 40.0, 1.0, c.get("f", 0.15))
    if t in ("rim", "core"):                              # (edgeband · 75번) 「○○ 둘레길 · 가장자리 · 끝 쪽」: 그 구역 테두리 선에서 폭 w의 띠(가운데 한 점이 아니다). 「○○ 한가운데」: 테두리에서 가장 깊은 안쪽(가장 깊은 곳의 절반보다 깊으면 고르게)
        out = np.zeros(len(x))
        for ar in _parks_of(c["k"]):
            x0, y0, x1, y1 = ar["box"]
            near = (x > x0 - 150) & (x < x1 + 150) & (y > y0 - 150) & (y < y1 + 150)
            if not near.any():
                continue
            d = ring_dist(x[near], y[near], ar["ring"])
            ins = in_ring(x[near], y[near], ar["ring"])
            deep = float(d[ins].max()) if ins.any() else 0.0
            if t == "rim":                                # 폭은 그 구역의 가장 깊은 안쪽의 4분의 1까지(작은 광장의 「가장자리」가 광장 전체가 되지 않게), 8~w m
                out[near] = np.maximum(out[near], np.exp(-d ** 2 / (2 * min(c.get("w", 25.0), max(8.0, 0.25 * deep)) ** 2)))
                continue
            if deep > 0:
                out[near] = np.maximum(out[near], np.where(ins, np.exp(-np.maximum(0.0, 0.5 * deep - d) ** 2 / (2 * max(10.0, 0.25 * deep) ** 2)), 0.0))
        return out if out.any() else None
    if t == "at":
        r = resolve(c["k"])
        out = np.zeros(len(keys))
        for i in r["roads"]:
            out = np.maximum(out, _lookup(keys, road_keys(i), np.ones(len(road_keys(i)))))
        if len(r["x"]):
            sig = _road_sig(_sigma(c, r["kinds"]), r["kinds"], ctx)
            ext = None if c.get("how") == "쪽" else _exts(r, sig)
            pad = 3 * sig + (float(ext.max()) if ext is not None else 0)
            m = (r["x"] > x.min() - pad) & (r["x"] < x.max() + pad) & (r["y"] > y.min() - pad) & (r["y"] < y.max() + pad)
            lake = water_ring(r) if "lakerim" in ON and c.get("how") != "쪽" else None
            if m.any() and lake is not None:                   # (lakerim · 75번) 호수 · 연못: 테두리 선에서 지금 폭의 띠, 물 안은 낮게(사람은 물 안에 서 있지 않다). 전에는 테두리 점마다의 봉우리라 점 사이가 비고 물 한가운데도 같은 값이었다
                d, sig = ring_dist(x, y, lake), max(sig, SIG["가까이"])      # 폭은 40m보다 좁게 잡지 않는다: 지도의 호수 테두리 · 공원 경계는 꼭짓점 수십 개로 줄인 어림이라, 18m 띠를 공원 경계와 겹치면 띠가 끊겨 범위가 오히려 흩어졌다
                out = np.maximum(out, np.exp(-d ** 2 / (2 * sig * sig)) * np.where(in_ring(x, y, np.vstack((lake, lake[:1]))) & (d > 10), LAKE_IN, 1.0))
            elif m.any() and ext is not None:                    # (bigplace) 넓은 장소: 그 크기 안은 고르게, 밖은 지금 폭으로(「○○초등학교 바로 앞」이 담장 밖에 선 자리를 덮게)
                d = np.full(len(x), 1e9)
                for a, b, e in zip(r["x"][m], r["y"][m], ext[m]):
                    d = np.minimum(d, np.maximum(0.0, np.hypot(x - a, y - b) - e))
                out = np.maximum(out, np.exp(-d ** 2 / (2 * sig * sig)))
            elif m.any() and c.get("how") == "쪽" and m.sum() <= 40:      # 「○○ 쪽」: 그 자리에 봉우리를 두지 않고 둘레를 고르게(그 자리로 찍지 않는다)
                d = np.full(len(x), 1e9)
                for a, b in zip(r["x"][m], r["y"][m]):
                    d = np.minimum(d, np.hypot(x - a, y - b))
                out = np.maximum(out, np.exp(-np.maximum(0.0, d - AROUND[0]) ** 2 / (2 * AROUND[1] ** 2)))
            elif m.any():
                out = np.maximum(out, _lookup(keys, *_near_map(r["x"][m], r["y"][m], sig)))
            for i in _bridges(r, n, ctx) if c.get("how") != "쪽" else ():      # (bridgeline · 75번) 「○○대교 밑 · 앞」: 다리 면 어디든 그 둘레(가운데 한 점만이 아니다). 「망원한강공원 … 양화대교 밑」은 공원과 다리가 만나는 곳이 된다
                out = np.maximum(out, np.exp(-bridge_dist(i, x, y) ** 2 / (2 * sig * sig)))
            if c.get("nearest"):
                out = np.maximum(out, 0.9 * _nearest_station(c["k"], r, x, y))
        for a in r["areas"]:
            ar = area_of(a)
            x0, y0, x1, y1 = ar["box"]
            near = (x > x0 - 250) & (x < x1 + 250) & (y > y0 - 250) & (y < y1 + 250)
            val = np.zeros(len(keys))
            val[near] = 0.35 if a[0] == "park" else 0.15          # 「○○ 쪽」은 공원 바로 바깥일 수도 있다
            val[near] = np.where(in_ring(x[near], y[near], ar["ring"]), 1.0, val[near])
            out = np.maximum(out, val)
        return out
    if t in ("in", "out"):
        ar = area_of(c["a"])
        x0, y0, x1, y1 = ar["box"]
        near = (x > x0 - 250) & (x < x1 + 250) & (y > y0 - 250) & (y < y1 + 250)
        ins = np.zeros(len(keys), bool)
        ins[near] = in_ring(x[near], y[near], ar["ring"])
        return np.where(ins, 1.0, 0.0) if t == "in" else np.where(ins, 0.0, np.where(near, 1.0, 0.0))
    if t in ("cat", "nocat"):
        idx = [i for i in _places_in(x.min() - 200, y.min() - 200, x.max() + 200, y.max() + 200) if G.kind[i] == c["c"]]
        if not idx or len(idx) > 4000:
            return None
        g = _lookup(keys, *_near_map(G.x[idx], G.y[idx], c.get("s") or (80.0 if t == "cat" else 60.0)))
        return g if t == "cat" else 1.0 - 0.75 * g          # 「안 보인다」: 그런 곳 바로 둘레를 낮춘다(지도에 없는 곳도 있으니 지우지는 않는다)
    if t == "between":
        a, b = ctx["pos"].get(n) or (None, None)
        if not a or not b:
            return None
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        return np.where(np.hypot(x - a[0], y - a[1]) + np.hypot(x - b[0], y - b[1]) <= 1.12 * d + 80, 1.0, 0.0)
    if t in ("past", "before"):
        if not ctx["pos"].get(n):
            return None
        return np.max([_past_like(c, t, a, x, y, ctx) for a in ctx["ends"].get(n) or [ctx["pos"][n]]], axis=0)     # 끝이 둘이면(방향 모름) 어느 끝이든
    return None


def _nearest_station(key, r, x, y):
    """점마다 「이 역이 가장 가까운 역일 가능성」: 다른 역보다 가까우면 1에 가깝고(경계 폭 60m), 멀수록 조금씩 준다(2km에 0.37)."""
    sx, sy = r["x"][[k == "역" for k in r["kinds"]]], r["y"][[k == "역" for k in r["kinds"]]]
    if not len(sx):
        return np.zeros(len(x))
    d_own = np.min(np.hypot(x[:, None] - sx[None, :], y[:, None] - sy[None, :]), axis=1)
    others = [i for i in _places_in(sx.min() - 4000, sy.min() - 4000, sx.max() + 4000, sy.max() + 4000, 20000) if G.kind[i] == "역" and gaz.norm(G.name[i]) != key]
    d_other, step = np.full(len(x), 1e9), max(1, 4_000_000 // max(1, len(x)))       # 메모리를 400만 칸 안으로 나눠 셈한다
    for j in range(0, len(others), step):
        ox, oy = G.x[others[j:j + step]], G.y[others[j:j + step]]
        d_other = np.minimum(d_other, np.min(np.hypot(x[:, None] - ox[None, :], y[:, None] - oy[None, :]), axis=1))
    return np.where(d_own <= 3000, np.exp(-d_own / 2000.0) / (1.0 + np.exp(np.clip((d_own - d_other) / 60.0, -50, 50))), 0.0)


def _move(c, ctx):
    """「조금 지나서」의 폭을 고를 움직인 방법: 자동차전용도로 위면 그것(걸어서는 못 간다), 시민이 말했으면 걷기 · 차, 아니면 모름."""
    if any(_xw(i) for i in ctx["roads"]):
        return "자동차전용도로"
    return c.get("move") if c.get("move") in AFTER else "모름"


def _past_like(c, t, a, x, y, ctx):
    """기준 자리 a 하나에 대한 「지났다 · 못 미쳤다」의 우도."""
    dd = np.hypot(x - a[0], y - a[1])
    val = np.ones(len(dd)) if c.get("flat") else np.exp(-dd / DIST[c.get("how") or "모름"])      # flat: 지났는지 · 아직인지만(거리는 말하지 않았다)
    if c.get("how") == "조금":                         # 「조금 지나서」는 바로 그 자리가 아니다: 움직인 방법 · 길 종류에 맞는 폭(AFTER) 안을 고르게(11-16, 전에는 50~350m 한 가지)
        lo, hi = AFTER[_move(c, ctx)]
        val = np.exp(-np.maximum(0.0, lo - dd) ** 2 / (2 * max(15.0, 0.3 * lo) ** 2)) * np.exp(-np.maximum(0.0, dd - hi) ** 2 / (2 * (0.2 * hi) ** 2))
    if c.get("min") and "min" not in OFF:
        d, sig = _ahead(c, ctx)
        val = np.exp(-(np.hypot(x - a[0], y - a[1]) - d) ** 2 / (2 * sig * sig))
    if ctx["head"]:
        ahead = (x - a[0]) * ctx["head"][0] + (y - a[1]) * ctx["head"][1]
        val = np.where((ahead > 0) == (t == "past"), val, val * 0.03)       # 가는 방향을 알면 지난 쪽 · 못 미친 쪽을 가른다
    return val


def _places_in(x0, y0, x1, y1, cap_m=6000):
    if x1 - x0 > cap_m or y1 - y0 > cap_m:
        return []
    out = []
    for a in range(int(x0 // 250), int(x1 // 250) + 1):
        for b in range(int(y0 // 250), int(y1 // 250) + 1):
            out += G.cell.get((a, b), ())
    return out


GENERIC_VOCAB = set("""쓰레기통 쓰레기 따릉이 대여소 거치대 입구 출구 출입구 정문 후문 입구광장 잔디밭 잔디광장 잔디 동상 말동상 구름다리 안내소 관리사무소 매표소 경비실 정류장 버스정류장 버스
앞 옆 뒤 밑 주차장 화장실 공중화장실 놀이터 어린이놀이터 빠지는 나가는 길 진출로 진입로 진출입로 램프 호수 연못 분수 분수대 산책로 벤치 정자 육교 횡단보도 계단
매점 쉼터 휴게실 휴게소 시장 공원 다리 가로등 보안등 전봇대 신호등 맨홀 화단 운동장 운동기구 음수대 약수터 전망대""".split())     # (genericname · 83번) 민원 말에 시설 · 물건 · 자리 설명으로 나오는 낱말. 「광장」은 뺀다(광장시장). 지명 · 가게 이름에 흔한 「한강 · 하나 · 약국 · 학교」 같은 낱말은 넣지 않는다
_GEN = {}


def generic_key(k):
    """(genericname · 83번) 이름 열쇠가 흔한 낱말로만 이루어졌나(「쓰레기통」 · 「따릉이대여소」 · 「시장입구」 · 「말동상」 · 「잔디밭」 · 「빠지는길」 · 「버스정류장앞」).
    지명 자료 · 시연용 표에 그런 이름의 곳이 서울에 한두 곳 있어, 곳 이름 없이 「쓰레기통 옆에 …」라고만 해도 그 한 점으로 확정하러 가던 일(80번 c15 · c24 · c25)."""
    if not isinstance(k, str) or "|" in k or len(k) < 2:
        return False
    if k not in _GEN:
        ok = [True] + [False] * len(k)
        for j in range(1, len(k) + 1):
            ok[j] = any(ok[i] and k[i:j] in GENERIC_VOCAB for i in range(j))
        _GEN[k] = ok[-1]
    return _GEN[k]


def demo_key(k):
    """(genericname · 83번) 이름 열쇠가 시연 장면용 표(extra_places.json)의 장소 · 별명만 가리키나(「큰 연못」 · 「얕은 연못」 · 「보행교」 · 「2번 출입구」 · 「사슴 있는 데」).
    서울숲 장면을 위해 단 줄이라, 장면 밖 통화(「상도역 2번 출입구 앞」 · 「아파트 단지 얕은 연못」)를 서울숲으로 끌던 일(81번 특례 27줄). 흔한 낱말 이름과 같은 규칙을 탄다."""
    refs = G.ix.get(k) if isinstance(k, str) else None
    return bool(refs) and all(r[0] == "p" and G.demo0 <= r[1] < G.demo1 for r in refs)


def _generic_drop(clues):
    """(genericname) 흔한 낱말로만 된 이름의 단서는 혼자서는 자리를 정하지 못한다: 그 단서를 뺀 나머지로 범위를 세워 보고, 그 범위 근처(800m 또는 덮는 반지름의 1.5배)에
    그 이름의 곳이 있을 때만 남긴다(「서울숲 근처인데요 … 잔디밭에」는 남고, 「공원 잔디밭에서」 · 「쓰레기통 옆에」는 빠진다). 나머지가 없으면 뺀다."""
    gen = [n for n, c in enumerate(clues) if c["t"] in ("at", "past", "before", "toward") and (generic_key(c.get("k")) or demo_key(c.get("k")))]
    if not gen:
        return clues
    rest = [c for n, c in enumerate(clues) if n not in gen]
    R0 = infer(rest) if rest else None
    keep = set()
    for n in gen if R0 is not None else ():
        r = resolve(clues[n]["k"])
        lim = max(800.0, 1.5 * R0["r_cover"])
        if len(r["x"]) and float(np.hypot(r["x"] - R0["cx"], r["y"] - R0["cy"]).min()) <= lim:
            keep.add(n)
    return [c for n, c in enumerate(clues) if n not in gen or n in keep]


SHOP_KINDS = {"가게", "음식점", "카페", "편의점", "마트", "빵집", "약국", "학원", "숙박", "사무실", "건물"}      # (farshop) 지명 자료에 빠졌거나 지점이 다를 수 있는 가게 · 건물 종류
ANCHOR_KINDS = {"역 출구", "역", "관공서", "학교", "교차로", "다리", "공원", "시장", "경찰", "소방서", "터미널", "볼거리", "문화시설", "동네"}     # (farshop) 서울에 하나뿐이고 지명 자료에 빠질 일이 드문 기준점 종류


def _farshop_drop(clues):
    """(farshop · 83번) 「명동역 6번 출구 나와서 밀리오레 앞이요」: 가게 이름(밀리오레)의 곳이 지명 자료에 둘뿐이고 둘 다 명동역에서 2km 넘게 떨어져 있어(명동 밀리오레가 자료에 없음),
    폭 18m의 「바로 앞」이 폭 100m의 역 출구보다 확률을 더 끌어 두 밀리오레 사이로 6.9km 범위가 섰다. 측량으로는 두 원이 만나지 않으니 하나가 틀렸다 —
    기준점 종류(역 출구 · 역 · 관공서 …)의 곳이 있는 단서가 있고, 가게 · 건물 이름 단서의 어느 곳도 그 기준점에서 1.5km 안에 없으면 가게 쪽을 뺀다(자료에 빠진 가게 · 다른 지점일 몫이 크다)."""
    anchors = [(c, resolve(c["k"])) for c in clues if c["t"] == "at" and isinstance(c.get("k"), str) and "|" not in c["k"]]
    anchors = [(c, r) for c, r in anchors if 0 < len(r["x"]) <= 3 and set(r["kinds"]) & ANCHOR_KINDS]
    if not anchors:
        return clues
    ax = np.concatenate([r["x"] for _, r in anchors])
    ay = np.concatenate([r["y"] for _, r in anchors])
    out = []
    for c in clues:
        if c["t"] == "at" and isinstance(c.get("k"), str) and "|" not in c["k"] and all(c is not a for a, _ in anchors):
            r = resolve(c["k"])
            if 0 < len(r["x"]) <= 40 and set(r["kinds"]) <= SHOP_KINDS and not r["roads"] and not r["areas"] and \
                    float(np.hypot(r["x"][:, None] - ax[None, :], r["y"][:, None] - ay[None, :]).min()) > 1500:
                continue
        out.append(c)
    return out


def infer(clues):
    """단서들 → 지금의 가능성 분포. 단서가 없거나 가리키는 곳이 없으면 None."""
    clues = [c for c in clues if c.get("t")]
    if "genericname" in ON:
        clues = _generic_drop(clues)
    if "farshop" in ON:
        clues = _farshop_drop(clues)
    mins = [n for n, c in enumerate(clues) if c["t"] == "past" and c.get("min")]
    if "nogain" in ON and len(mins) > 2:                  # 「○○ 지나고 N분」 대여섯 개는 같은 사람의 같은 어림: 기준 표지가 지금 범위에 가장 가까운 둘만 곱한다(33번 1-3)
        R0 = infer([c for n, c in enumerate(clues) if n not in mins[:-2]])
        pos = _context(clues)["pos"]
        if R0 is not None:
            keep = set(sorted(mins, key=lambda n: math.hypot(pos[n][0] - R0["cx"], pos[n][1] - R0["cy"]) if pos.get(n) else 1e12)[:2])
            clues = [c for n, c in enumerate(clues) if n not in mins or n in keep]
    ctx = _context(clues)
    sups = [_support(n, c, ctx) for n, c in enumerate(clues)]
    fine = [s[0] for s in sups if s and s[1] == "fine"]
    many = [s[0] for s in sups if s and s[1] == "many"]
    area = [s[0] for s in sups if s and s[1] == "area"]
    if not (fine or many or area):
        return None
    if fine:
        base = np.unique(np.concatenate(fine))
        bx, by = unpack(base)
        add = []
        for k in many:                                   # 지점이 많은 이름은 지금 범위 둘레의 지점만 더한다
            kx, ky = unpack(k)
            add.append(k[(kx > bx.min() - 400) & (kx < bx.max() + 400) & (ky > by.min() - 400) & (ky < by.max() + 400)])
        base = np.unique(np.concatenate([base] + add)) if add else base
    elif many:
        base = np.unique(np.concatenate(many))
    else:
        first = min(area, key=len)
        base, area = np.unique(first), [a for a in area if a is not first]
    if len(base) > 250000:
        base = base[::int(len(base) // 250000) + 1]
    cell = np.full(len(base), float(STEP * STEP))
    if area and (fine or many):                           # 넓은 구역은 성기게 찍어 「거기일 가능성」만 남긴다(촘촘한 점과 겹치면 촘촘한 쪽)
        extra = np.unique(np.concatenate(area))
        extra = extra[~np.isin(extra, base)]
        if len(extra) > 20000:
            extra = extra[::len(extra) // 20000 + 1]
        if len(extra) > 2:
            step = max(float(np.median(np.diff(np.unique(unpack(extra)[0])))), STEP)
            keys = np.concatenate([base, extra])
            cell = np.concatenate([cell, np.full(len(extra), step * step)])
            order = np.argsort(keys)
            base, cell = keys[order], cell[order]
    x, y = unpack(base)
    total, logw, mix = SEOUL_M2, np.log(cell), {}
    log_else = math.log(max(SEOUL_M2 - float(cell.sum()), 1.0))      # 후보로 깔지 않은 「그 밖의 서울」 한 덩어리
    for n, c in enumerate(clues):
        f = _like(n, c, base, x, y, ctx)
        if f is None:
            continue
        if c["t"] in ("not", "nocat"):
            logw += np.log(f)
            continue
        z = float((f * cell).sum())
        if z <= 0:
            continue                                      # 가리키는 곳이 지금 후보에 없다: 쓸 수 없는 단서
        eps = c.get("e") or EPS["road" if c["t"] == "at" and "k" in c and resolve(c["k"])["roads"] and not len(resolve(c["k"])["x"]) else c["t"]]
        right, wrong = (1 - eps) * f / z, eps / total     # 맞는 말이면 가리키는 곳에, 틀린 말이면 어디든 고르게
        mix[n] = right / (right + wrong)
        logw += np.log(right + wrong)
        log_else += math.log(wrong)
    top = max(float(logw.max()), log_else)
    w, w_else = np.exp(logw - top), math.exp(log_else - top)
    elsewhere = w_else / (float(w.sum()) + w_else)        # 진짜 자리가 후보 밖(단서가 모두 틀림)일 확률
    w /= w.sum()
    trust = {n: float((w * m).sum()) * (1 - elsewhere) for n, m in mix.items()}     # 단서마다 「다른 단서들까지 놓고 보니 이 말이 맞을 확률」. 낮으면 서로 어긋난 말이다
    order = np.argsort(-w)
    n90 = int(np.searchsorted(np.cumsum(w[order]), MASS)) + 1
    cred = order[:n90]
    cw = w[cred] / w[cred].sum()
    cx, cy = float((x[cred] * cw).sum()), float((y[cred] * cw).sum())                 # 가장 그럴듯한 자리(가능성으로 무게를 준 가운데)
    on_road = bool(ctx["roads"]) and bool(np.isin(base[cred], np.concatenate([road_keys(i) for i in ctx["roads"]])).mean() > 0.8)
    if on_road and n90 > 2:                               # 길 위: 길을 따라 늘어선 길이의 절반
        (ux, uy), _ = _axis(x[cred], y[cred], cw)
        t = x[cred] * ux + y[cred] * uy
        radius = max(float(t.max() - t.min()) / 2, STEP / 2)
        if "roadfloor" in ON:                             # 길 위 구간의 바닥(33번 3-2)
            for n, pts in ctx.get("ends", {}).items():    # 여러 점인 이름(분기점 갈래)이 받치는 구간은 그 점들이 길을 따라 퍼진 길이 + 120m보다 짧지 않다
                pa = np.array(pts)
                if len(pa) and np.hypot(pa[:, None, 0] - x[cred][None, ::7], pa[:, None, 1] - y[cred][None, ::7]).min() <= 150:
                    tt = pa[:, 0] * ux + pa[:, 1] * uy
                    radius = max(radius, float(tt.max() - tt.min()) / 2 + 60)
            narrow = [c for c in clues if c["t"] in ("past", "before", "between") or (c["t"] == "pt" and c.get("r", 100) <= 30)]
            if len(narrow) <= 1 and not any(c["t"] == "pt" for c in narrow):
                radius = max(radius, 75.0)                # 표지 하나의 「지났다」 한마디로 선 구간은 150m보다 짧게 치지 않는다(차의 빠르기를 모른다)
    else:                                                 # 그 밖: 범위의 넓이와 같은 원의 반지름. 덩어리가 여럿으로 떨어져 있으면 그 사이까지 친다
        half = math.hypot(x[cred].max() - x[cred].min(), y[cred].max() - y[cred].min()) / 2
        radius = max(math.sqrt(float(cell[cred].sum()) / math.pi), 0.6 * half, STEP / 2)
    r_cover = float(np.hypot(x[cred] - cx, y[cred] - cy).max()) if n90 else radius        # 가운데에서 90% 범위의 가장 먼 점까지(넓이 같은 원은 공원 모양을 다 덮지 못한다, 33번 1-2)
    alike = []                                            # 소리가 같아 하나로 정하지 않은 이름(「통일로|동일로」)이 범위 안에서 아직 둘 이상에 걸쳐 있나(11-16)
    for n, c in enumerate(clues):
        if c["t"] == "at" and "|" in str(c.get("k") or ""):
            parts = [_like(n, dict(c, k=k), base[cred], x[cred], y[cred], ctx) for k in c["k"].split("|")]
            parts = [float((w[cred] * f).sum()) if f is not None else 0.0 for f in parts]
            if sum(parts) > 0 and sum(1 for v in parts if v >= 0.1 * sum(parts)) >= 2:
                alike.append((n, [round(v / sum(parts), 3) for v in parts]))
    pk = any(_pk(resolve(c["k"])) for c in clues if "k" in c and c["t"] in ("at", "past", "before"))       # 면 · 선으로 된 공원 안 이름(park_names)이 범위를 받치고 있나
    named = [c for c in clues if c["t"] in ("at", "pt", "past", "before", "between", "in", "out", "closest", "anyof", "rim", "core")]
    heard_only = bool(named) and all(c.get("heard") for c in named)      # 자리 단서가 모두 비슷한 이름으로 이은 것뿐이다(11-15)
    blob_alt = None
    if "mainblob" in ON and not on_road and n90 > 1:     # (mainblob, 93번 다음 방향) 90% 범위가 떨어진 덩어리 여럿이고 한 덩어리가 가능성 대부분을 가지면 범위 = 그 덩어리
        part = _blobs(x[cred], y[cred])                   # 동규 장한평역 통화(11-21): 「CU랑 신한은행이요」 뒤 89%가 실제 자리 52m 안 덩어리인데 543m 밖 4% 덩어리까지 덮어 498m → 같은 간판 질문
        mass = np.bincount(part, weights=w[cred])
        top = int(mass.argmax())
        if len(mass) > 1 and mass[top] >= BLOB_SHARE * float(w.sum()):
            c1 = cred[part == top]
            cw = w[c1] / w[c1].sum()
            m1 = float((x[c1] * cw).sum()), float((y[c1] * cw).sum())
            half = math.hypot(x[c1].max() - x[c1].min(), y[c1].max() - y[c1].min()) / 2
            r1 = max(math.sqrt(float(cell[c1].sum()) / math.pi), 0.6 * half, STEP / 2)
            if r1 <= DONE_M:                              # 그 덩어리로 끝낼 수 있을 때만(넓은 덩어리로 좁히면 가상 600통 「네」로 기우는 시민에서 틀린 확정이 늘었다: 93번 다음 방향)
                g2 = max((g for g in range(len(mass)) if g != top), key=lambda g: mass[g])
                c2 = cred[part == g2]
                w2 = w[c2] / w[c2].sum()
                blob_alt = [round(float((x[c2] * w2).sum()), 1), round(float((y[c2] * w2).sum()), 1)]      # (crosspick) 남은 덩어리 가운데 가장 무거운 것: 둘 중 가르기의 견줄 자리
                cred, (cx, cy), radius = c1, m1, r1
                r_cover = float(np.hypot(x[cred] - cx, y[cred] - cy).max())
    R = {"keys": base, "x": x, "y": y, "w": w, "order": order, "cred": cred, "cx": cx, "cy": cy, "r": radius, "r_cover": max(r_cover, radius), "has_past": any(c["t"] == "past" for c in clues), "trust": trust, "elsewhere": elsewhere, "ctx": ctx, "on_road": on_road, "pk": pk, "heard_only": heard_only, "alike": alike, "blob_alt": blob_alt}
    if ON & {"ringdone", "rimask", "rimline"}:                       # (75번) 범위를 받치는 단서 가운데 「둘레」로 읽은 곳(호수 테두리 · 구역의 테두리 띠)의 이름. 다른 단서와 어긋나 버려진 것(믿음 0.35 아래)은 뺀다
        ring_k = next((c["k"] for n, c in enumerate(clues) if trust.get(n, 1.0) >= 0.35 and "k" in c and (c["t"] == "rim" or (
            c["t"] == "at" and c.get("how") != "쪽" and not c.get("across") and "lakerim" in ON and water_ring(resolve(c["k"])) is not None))), None)
        R["ringed"], R["ring_k"] = (G.display(ring_k) if ring_k else None), ring_k
        R["hole"] = bool(R["ringed"]) and float(np.hypot(x[cred] - cx, y[cred] - cy).min()) > STEP      # 범위의 가운데가 범위 밖(고리의 빈 속)이다. 속이 찬 범위면 가운데에서 가장 가까운 격자점이 15m 안에 있다
    if "guessdrop" in ON:                                 # (guessdrop, 기본 끔 · 53번) 시스템이 짐작으로 이은 단서(비슷한 이름으로 이음 · 종류 낱말로 고른 한 곳)가 시민이 또렷이 댄 이름과 어긋나면 짐작 쪽을 버린다
        weak = [n for n, c in enumerate(clues) if c.get("heard") or c.get("guess")]
        firm_low = [n for n, v in trust.items() if v < 0.35 and n not in weak and clues[n]["t"] in ("at", "pt", "past", "before", "between", "in", "out", "anyof")]
        if weak and firm_low:                             # 지금 범위가 또렷한 단서를 「틀린 말」로 치고 있다: 짐작 단서를 빼고 다시 센다. ponytail: 짐작 단서를 한꺼번에 뺀다(어느 것이 어긋났는지 가르지 않는다)
            R2 = infer([c for n, c in enumerate(clues) if n not in weak])
            if R2 is not None:
                R2["dropped"] = [clues[n].get("label") or "" for n in weak]
                return R2
    if any(c["t"] == "half" for c in clues) and is_done(R):      # 둘 중 고르기 답이 있어야만 좁혀진 것이면 아직 끝이 아니다: 이 답 하나로는 끝내지 않는다(11-16)
        R0 = infer([c for c in clues if c["t"] != "half"])
        R["needs_half"] = R0 is None or not is_done(R0)
    return R


BLOB_LINK, BLOB_SHARE = 60.0, 0.85     # (mainblob) 이 칸(m)으로 묶어 이웃 칸끼리 이은 것이 한 덩어리 · 범위를 그 덩어리로 좁히는 몫(전체 가능성 가운데. 90% 범위 안에서는 94%). 좁힌 덩어리가 DONE_M 안일 때만


def _blobs(x, y):
    """(mainblob) 점들을 BLOB_LINK 칸에 넣고 이웃 칸(8방향)끼리 이어 덩어리 번호를 매긴다 → 점마다 번호."""
    keys = list(zip(np.floor(x / BLOB_LINK).astype(int).tolist(), np.floor(y / BLOB_LINK).astype(int).tolist()))
    cells = {c: n for n, c in enumerate(dict.fromkeys(keys))}
    up = list(range(len(cells)))

    def find(a):
        while up[a] != a:
            up[a] = up[up[a]]
            a = up[a]
        return a
    for (i, j), n in cells.items():
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                m = cells.get((i + di, j + dj))
                if m is not None:
                    up[find(m)] = find(n)
    roots = {}
    return np.array([roots.setdefault(find(cells[c]), len(roots)) for c in keys])


def size_of(R):
    """화면에 보일 크기: 길 위면 구간 길이, 아니면 반지름(CALL_ON=region이고 아직 좁혀지지 않았으면 범위를 다 덮는 반지름)."""
    if R["on_road"]:
        return {"kind": "length", "m": max(STEP, int(round(2 * R["r"], -1))), "r": R["r"]}
    r = R["r_cover"] if "region" in ON and not is_done(R) else R["r"]
    return {"kind": "radius", "m": max(STEP, int(round(r, -1))), "r": r}


def _region(R):
    """범위째로 물을 때 말할 이름 붙은 구역: 가능성의 90% 넘게가 한 공원(없으면 한 동) 안이면 그 구역 → ["park" | "dong", 번호] 또는 None."""
    x, y, w = _sample(R)
    for kind, lst in (("park", G.parks), ("dong", G.dong)):
        for i, a in enumerate(lst):
            x0, y0, x1, y1 = a["box"]
            if x1 < R["cx"] - 50 or x0 > R["cx"] + 50 or y1 < R["cy"] - 50 or y0 > R["cy"] + 50:
                continue
            near = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
            share = float(w[near][in_ring(x[near], y[near], a["ring"])].sum()) if near.any() else 0.0
            if share >= 0.9:
                ring = a["ring"]
                area = 0.5 * abs(float(np.dot(ring[:, 0], np.roll(ring[:, 1], 1)) - np.dot(ring[:, 1], np.roll(ring[:, 0], 1))))
                if R["r_cover"] < 0.5 * math.sqrt(area / math.pi):
                    return None                           # 그 구역의 반보다 좁게 모였으면 「○○ 전체」가 아니라 원으로(11-15: 사슴우리 둘레 200m인데 「서울숲 전체」로 보이던 일)
                return [kind, i]
    return None


def heat(R, cap=2500):
    """지도에 그릴 가능성 구름: ([[경도, 위도, 세기(0~1)], …], 점 하나가 나타내는 폭 m). 점이 많으면 굵은 격자로 모아 보낸다."""
    idx = R["order"][:int(np.searchsorted(np.cumsum(R["w"][R["order"]]), 0.97)) + 1]
    keys, w, stride = R["keys"][idx], R["w"][idx], 1
    while len(keys) > cap:
        stride *= 2
        k2 = pack((R["keys"][idx] // MUL - BIG) // stride * stride, (R["keys"][idx] % MUL - BIG) // stride * stride)
        order = np.argsort(k2, kind="stable")
        keys, start = np.unique(k2[order], return_index=True)
        w = np.add.reduceat(R["w"][idx][order], start)
    x, y = unpack(keys)
    top, half = float(w.max()), (stride - 1) * STEP / 2
    return [[*gaz.lonlat(a + half, b + half), round(float(v) / top, 3)] for a, b, v in zip(x, y, w)], STEP * stride


def is_done(R):
    if R is not None and R.get("needs_half"):
        return False                                      # 둘 중 고르기 답 하나로 닿은 좁혀짐(11-16)
    if R is not None and R.get("alike"):
        return False                                      # 소리가 같은 이름이 아직 둘 이상에 걸쳐 있다: 다른 단서로 갈리기 전에는 끝내지 않는다(11-16)
    if R is not None and R.get("heard_only"):
        return False                                      # 비슷한 이름으로 이은 단서만으로는 끝내지 않는다: 정확히 맞은 이름이나 질문의 답이 하나 더 있어야(조용히 확정으로 가지 않게, 11-15)
    if R is not None and R["on_road"] and "road400" in ON and R["ctx"].get("head") and R.get("has_past"):
        return R["r"] <= 2 * DONE_ROAD_M                  # (road400) 방향을 받았고 「○○ 지나서」로 시작을 말할 수 있으면 400m 구간까지(33번 3-4, 동규가 정함)
    if R is not None and "ringdone" in ON and R.get("hole"):
        return False                                      # (ringdone · 75번) 둘레로 읽은 곳: 범위가 고리 모양으로 남아 그 가운데(핀을 찍을 자리)가 범위 밖이면 넓이가 작아도 끝이 아니다(숭례문광장 가장자리 → 광장 가운데에 핀, 64m 틀린 확정)
    if R is not None and R.get("pk") and R["r_cover"] > 90:
        return False                                      # 호숫가 · 산책길처럼 띠 모양으로 남은 범위는 넓이로는 작아도 길게 퍼져 있다: 덮는 반지름까지 봐야 한다(33번 2-5)
    return R is not None and R["r"] <= (DONE_ROAD_M if R["on_road"] else DONE_M)


_LAMP_XY = None


def _lamps_within(x, y, rad):
    """(x, y)에서 rad m 안에 번호를 아는 가로등이 있나."""
    global _LAMP_XY
    if _LAMP_XY is None:
        _LAMP_XY = np.array([v[1:3] for v in G.lamps.values()], float).reshape(-1, 2)
    return bool(len(_LAMP_XY) and (np.hypot(_LAMP_XY[:, 0] - x, _LAMP_XY[:, 1] - y) <= rad).any())


def _on_express(R):
    return R is not None and R["on_road"] and any(_xw(i) for i in R["ctx"]["roads"])


def _road_ok(i, R):
    """표지로 내밀 · 되말할 수 있는 곳인가: 자동차전용도로 위에서는 차에서 보이는 종류(gaz.ROADSIDE: 다리 · 나들목 · 터널 · 육교 …)만.
    질문 · 보기 · 되말 · 찾아가는 말을 고르는 곳이 모두 이 규칙을 거친다(11-15 동규: 운전자에게 길가 병원 이름을 묻던 일)."""
    return not _on_express(R) or G.kind[i] in gaz.ROADSIDE


def _pk(r):
    """resolve() 결과가 공원 안 이름(면의 테두리 · 선의 점들)인가: 한 점처럼 「그 표지에서 어느 쪽」을 물을 수 없다."""
    return any(G.pk0 <= i < G.pk1 for i in r["ids"])


# ---- 다음 질문: 답으로 남은 가능성이 얼마나 고르게 갈리나(기대 정보량, 비트)
def _bits(parts):
    p = np.array([v for v in parts if v > 1e-9])
    p = p / p.sum()
    return float(-(p * np.log2(p)).sum())


def _sample(R, cap=3000):
    idx = R["cred"] if len(R["cred"]) <= cap else np.sort(np.random.default_rng(7).choice(R["cred"], cap, replace=False))     # 많으면 고르게 뽑는다(씨앗 고정)
    w = R["w"][idx]
    return R["x"][idx], R["y"][idx], w / w.sum()


def _axis(x, y, w):
    """점들이 가장 길게 늘어선 쪽의 단위 벡터와 가운데."""
    mx, my = float((x * w).sum()), float((y * w).sum())
    cxx, cyy, cxy = float((w * (x - mx) ** 2).sum()), float((w * (y - my) ** 2).sum()), float((w * (x - mx) * (y - my)).sum())
    ang = 0.5 * math.atan2(2 * cxy, cxx - cyy)
    return (math.cos(ang), math.sin(ang)), (mx, my)


HANGUL = re.compile(r"[가-힣]")


def _ko(i):
    """(hangulopt2, 90번 2절) 보기로 바꿔 끼울 수 있는 이름인가: 한글이 한 글자라도 있다. 보기를 만드는 곳(바로 앞 · 간판 · 역 · 지나온 곳 · 가장 가까운 곳 · 둘 중 · 어느 쪽 · 간 쪽)이 모두 이것으로 가린다."""
    return bool(HANGUL.search(G.name[i]))


def _ko_swap(orig, alt, said=4):
    """(hangulopt2) 보기(장소 번호들, 원래 순서)를 말로 읽는 앞 said개(server.say_options = 넷)가 한글 이름이 되게 고쳐 놓는다. 보기 수는 늘 원래와 같다.
    1) 같은 곳들의 순서만 바꿔 한글 이름을 앞으로, 한글 없는 이름을 뒤(화면 단추에만)로. 2) 한글 이름이 읽는 자리 수에 모자라면 모자란 만큼만
    한글 이름만으로 같은 규칙대로 다시 고른 alt에서 가져와 한글 없는 이름 자리에 넣는다. 3) 그래도 모자라면 원래 그대로.
    질문 고르기(보기의 몫 · 기대 비트)는 늘 원래 후보로 셈해 켜도 질문의 종류가 같다(첫 판 hangulopt는 영어 보기를 빼 후보가 줄며 질문이 「둘 중」으로 새 600통 틀린 확정 +1)."""
    if "hangulopt2" not in ON or all(_ko(i) for i in orig):
        return orig
    ko, en = [i for i in orig if _ko(i)], [i for i in orig if not _ko(i)]
    need = max(0, min(said, len(orig)) - len(ko))
    extra = [i for i in alt if _ko(i) and i not in orig]
    if len(extra) < need:
        return orig
    return ko + extra[:need] + en[need:]


def _candidates(x, y, w, radius, kinds=None, skip=(), ko=False):
    """범위 안에서 물어볼 만한 표지를 고른다: 둘레 radius 안에 가능성이 많이 걸려 있고, 눈에 띄고, 서로 떨어진 것부터 여섯 곳. → (장소 번호들, 갈린 몫들)
    skip = 이미 내밀었던 자리들((x, y) 소수 첫째 자리)."""
    idx = [i for i in _places_in(x.min() - radius, y.min() - radius, x.max() + radius, y.max() + radius, 6000 if kinds is None else 45000)
           if (kinds is None or G.kind[i] in kinds) and G.kind[i] not in ("동네", "산") and len(G.name[i]) >= 3 and not gaz.GENERIC.match(G.name[i].replace(" ", ""))
           and not G.pk0 <= i < G.rp1     # 공원 안 이름(park_names)은 시민이 말하면 알아듣되 보기로 먼저 내밀지 않는다: 넣어도 지금의 질문 흐름이 그대로(33번 2-5)
           and not (skip and (round(float(G.x[i]), 1), round(float(G.y[i]), 1)) in skip)
           and not ("selfname" in ON and self_area(i)) and (not ko or _ko(i))]     # ko = 한글 이름만(hangulopt2의 바꿔 끼울 후보). (selfname · 75번) 공원 · 광장의 자기 이름 점은 보기로 내밀지 않는다: 고르면 그 구역 한가운데 한 점이 된다(광장 가장자리의 틀린 확정 90 · 134m)
    if not idx:
        return [], None
    idx = np.asarray(idx)
    if len(idx) > 1500:                                    # 너무 많으면 눈에 띄는 종류부터
        idx = idx[np.argsort(-np.array([PROM.get(G.kind[i], 1.0) for i in idx]), kind="stable")[:1500]]
    d = np.hypot(G.x[idx][None, :] - x[:, None], G.y[idx][None, :] - y[:, None])
    mass = (w[:, None] * (d <= radius)).sum(0)
    names = [G.name[i] for i in idx]
    seen = {}
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    score = mass * np.array([PROM.get(G.kind[i], 1.0) * (0.6 if seen[G.name[i]] > 1 else 1.0) for i in idx])   # 범위 안에 같은 이름이 여럿이면 덜 쓸모 있다
    picked = []
    for j in np.argsort(-score):
        if mass[j] < (0.03 if radius < 100 else 0.003) or len(picked) >= 6:
            break
        if all(math.hypot(G.x[idx[j]] - G.x[idx[k]], G.y[idx[j]] - G.y[idx[k]]) >= 1.2 * radius for k in picked):
            picked.append(int(j))
    if not picked:
        return [], None
    dd = d[:, picked]
    near, close = dd.argmin(1), dd.min(1) <= 1.5 * radius
    parts = [float(w[(near == k) & close].sum()) for k in range(len(picked))]
    return [int(idx[j]) for j in picked], parts + [max(0.0, 1 - sum(parts))]


LOCQ = ("zone", "between", "passed", "mark", "finer", "near", "dir", "station", "ago", "seen", "either", "which", "lampno", "from", "next", "mark_again", "dist", "closest", "again", "alike", "addr")
# 질문마다 (시민이 모를 몫, 묻고 답하는 데 드는 초). 조사 세션의 시작값(20 마-B3)에서 옮김. 실제 통화로 맞춘 값이 아니다
Q_COST = {"zone": (0.1, 8), "dir": (0.1, 8), "near": (0.1, 8), "seen": (0.1, 8), "between": (0.15, 10), "either": (0.15, 10), "ago": (0.2, 10), "station": (0.2, 8),
          "passed": (0.3, 12), "mark": (0.3, 12), "finer": (0.3, 12), "lampno": (0.7, 20), "from": (0.2, 10), "next": (0.15, 8), "dist": (0.1, 8), "closest": (0.2, 10), "alike": (0.1, 10), "addr": (0.5, 12)}
OFF = set(filter(None, os.environ.get("CALL_OFF", "").split(",")))   # 견주어 잴 때 끌 것: either,seen,which,ago,min,score (평소에는 비워 둔다)
SPEECH_ON = ("facil,exitfix,walkmin,nowthere,passby,notbut,across,fromto,branch,sayplace,hasjanha"      # 실제 말투 고침 열하나(11-18, 53번 2-나): 동 이름 없는 시설 · 출구 번호만 · 걸어서 몇 분 · 지금 있는 곳과 본 곳 · 「X가 아니라 Y」 · 건너편 · 「A에서 B 가는 방향」 · 상표와 지점 따로 · 「있잖아요」
             ",twins,fuzzy2,lamponce2"                    # 같은 이름이 둘레에 또 있으면 한 지점으로 좁히지 않기 + 머리만 비슷하게 이은 이름에 뒷말 맞추기(「천호엮 5번 출구」 → 천호역 5번 출구. 둘은 묶어서만) + 가로등 번호 「못 봤어요」 뒤 다시 안 묻기(49번)
             ",addrread,addrline"                         # 주소를 말하면 읽기(묻지는 않는다) + 주소 표에 없는 건물번호를 같은 길의 번호 사이로 어림
             ",fillerlist,finerkeep,choicekeep")          # Solar가 다시 읽을 때 코드 읽기의 규칙 셋이 풀리던 것(실제 호출 길)
STT_ON = "anizone,sttname,sttjosa,numword,bigplace"      # 받아쓰기가 틀린 글 넷 + 큰 장소의 넓이(11-19 동규, 60번). 끄려면 CALL_ON에 이것을 뺀 목록을 준다
FIELD_ON = "commonshop,jumpguard,dropcheck,optpart"     # 11/19 현장 테스트 실패 꼴 고침 묶음 가(11-20, 71번): 흔한 말 · 튐 막기 · Solar 「아님」 확인 · 보기 일부 답. 끄려면 CALL_ON에 이것을 뺀 목록을 준다
CONFIRM_ON = "partyes2"      # 되묻기에 「네, 근데 바로 앞은 아니고 조금 옆이에요」: 「아니요」가 아니라 그 자리 조금 옆으로 받기(11-20, 73번 7절). 끄려면 CALL_ON에 이것을 뺀 목록을 준다
MATTER_ON = "hurtalive,matterstop"      # 일 질문 되풀이 막기(11-20): 「다쳐서 · 웅크리고 · 떨고」는 살아 있음, 살았나 · 목줄은 두 번 물어 답을 못 읽으면 그만. 끄려면 CALL_ON에 이것을 뺀 목록을 준다
EDGE_ON = "trailword,compass,edgeband,lakerim,selfname,bigdist,ringdone,rimask,rimline,closestcap,farsee2,bridgeline"      # 둘레에 길이 있어 사람이 어디든 설 수 있는 곳(호수 · 공원 둘레길 · 광장 가장자리)의 읽기 고침(11-20, 75번). 끄려면 CALL_ON에 이것을 뺀 목록을 준다
SAMEQ = ("finer", "passed", "closest", "from", "either", "between")      # (sameopts) 보기를 내미는 위치 질문. 열린 질문(mark · station)은 답이 달라질 수 있어 뺀다
ASK_ON = "samename,closestnew,josa"      # (75번 후보 2, 기본 켬) 질문 다듬기: samename = 질문 글에서 같은 이름의 보기는 한 번만 말함(보기 자체는 그대로: 같은 이름의 두 곳이 모두 범위에 남는다, server.say_options) · closestnew = 「다 멀어요」로 지운 곳은 보기로 다시 내밀지 않음: 「어디가 가장 가까우세요」를 다시 물을 때는 새 보기로(셋이 안 되면 묻지 않음), 간판 · 바로 앞 질문의 보기에서도 뺌 · josa = 「카페(이)가」를 받침에 맞춰 「카페가 · 정류장이」로(server.fill)
# sameopts(기본 끔 · 75번): 시민이 보기에서 골라 답한 질문을 같은 보기로 다시 고르지 않음(questions의 same, server.asked_same). 영동1교 통화의 같은 「어느 쪽」 질문 되풀이는 없어지지만 가상 600통에서 한 점 421 · 397 · 416 → 414 · 390 · 405, 틀린 확정 0 · 0 · 5 → 0 · 0 · 6이라 켜지 않았다(같은 질문을 다시 물어 같은 답을 한 번 더 세는 것이 지금은 범위를 좁히는 데 쓰이고 있다)
C2_ON = "bridgeroad," + ASK_ON      # (75번 후보 2, 기본 켬) #138 뒤의 작은 고침 넷: bridgeroad = 길 이름과 함께 나온 다리(「도림천 자전거길 … 도림천고가도로교 밑」)도 다리의 면으로(bridgeline이 켜져 있을 때) + 질문 다듬기 셋. 이 묶음을 빼면 #138의 동작 그대로
FIX_ON = "genericname,yesno,whichkeep,choicebind,placebind,codekeep,keeptype,stationbind,stoponly,roadcls,hood,seenwide,handsaid,dupshop,negkeep,bridgeend,hangulopt2"      # (88번 둘째 묶음 — chainpick은 확인용 묶음 옛 잣대 93통 테두리 틀린 확정 7 → 8로 끔, 정확도 세션 17:45) 「보여요」 넓게 · 넘길 때 시민 말 · 같은 가게 두 줄 · 받지 않은 「아님」 · 다리 쪽 끝 · 보기의 영어 이름 좁힌 판 · 체인 가게 「어느 지점」 묻기를 더함(체인 가게를 기준에서 빼기 chainref · 영어 이름 첫 판 hangulopt는 평가 · 600통 틀린 확정 +1로 끔) —      # (84번, 기본 켬) 고침 모은 판에서 모든 기준을 넘은 열 + 동네 이름(hood, 87번 — 더 긴 이름 속 동네 말은 읽지 않게 고친 d12d88e로 기본 켬, 84번 5절) — 기준점과 어긋난 가게(farshop, 83번)는 확인용 묶음 93통 테두리 둘에서 틀린 확정 +1로 걸려 끔(11-21 07시). 동네 이름(hood, 87번)은 가게 지점 이름 속 동네 말(「CU 신촌피어점」의 신촌)을 동네로 읽어 600통 #92가 맞는 한 점 → 넘김이 되어 끔. 그 밖에 정류장으로만 있는 기관 이름(stoponly, 85번 좁힌 판) · 양재대로 · 언주로의 일반 구간(roadcls, 86번) 더함. 덜 묻기의 dunnoboth는 옛 잣대 한 점 −9 · −12로 끔. 처음 아홉: 흔한 낱말 이름 · 기준점과 어긋난 가게(83번) · 되묻기 답의 헛 「예」 · 「○○은 맞아요」(81번) · Solar가 말에 없는 이름을 쓰지 않기 다섯(79번). seenwide · 긴 다리 · 덜 묻기는 「정할 것」으로 끔. 끄려면 CALL_ON에 이것을 뺀 목록을 준다
BRIDGE_ON = "bridgelong"      # (75번 9절 · 10절, 모은 판에서는 기본 끔 — 켜는 판은 donggyu/locate-bridge) 길이 120m를 넘는 다리 · 고가는 이름 하나만 대도(「보라매고가 바로 앞」) 가운데 한 점이 아니라 다리의 면으로. 끄려면 CALL_ON에 이것을 뺀 목록을 준다
FOLLOW_ON = "pairseen,mainblob,saidanchor,nhalias"      # (93번, 기본 켬 후보) 보기 밖의 답을 따라가기: 함께 댄 이름 둘의 짝 · 한 덩어리에 몰린 범위 · 시민이 최근에 댄 이름을 확정 기준으로 · 「농협」 별명. 하나씩 끄려면 CALL_ON에 그 이름을 뺀 목록을 준다.  saidin(이름 하나도 둘레에서 먼저 찾기)은 기본 끔: 가상 600통에서 틀리게 답한 시민의 범위를 바로잡을 이름까지 빼서 한 점 −2 · −6, 못 끝냄 +9(93번 8절)
DEFAULT_ON = "loop,region,softnot,dist,closest,stallend,pastfix,areafix,fromcone," + SPEECH_ON + "," + STT_ON + "," + FIELD_ON + "," + CONFIRM_ON + "," + EDGE_ON + "," + C2_ON + "," + MATTER_ON + "," + FIX_ON + "," + BRIDGE_ON + "," + FOLLOW_ON      # BRIDGE_ON(긴 다리)은 88번 둘째 묶음에서 기본 켬. FOLLOW_ON은 93번(동규 11-21 21시 결정)(동규 11-21 10:1x 「긴 다리 읽기는 이번에 넣자」)     # 서비스 기본값(11-15 동규 「위치는 켜는 방향」): 33번 설계의 추천 묶음 + stallend(11-16) + 틀린 확정 고침 셋(11-18 동규, 47번 추천 1). CALL_ON을 주면 그것만(빈 값 = 모두 끔)
LOCCAP = int(os.environ.get("CALL_LOCCAP", "10"))   # 위치 질문을 몇 번까지 묻나(11-18 동규 8 → 10, 47번 추천 1. 앞 값으로 재려면 CALL_LOCCAP=8)
ON = gaz.ON = set(filter(None, os.environ.get("CALL_ON", DEFAULT_ON).split(",")))     # 켜 볼 것: check = 마지막 확인을 「○○ 말고 보이는 이름 하나」 열린 질문으로(동규가 정함, 11-15) 등
if "bridgeline" in ON:
    G.add_bridges()                                       # (bridgeline · 75번) 다리의 면(data/seoul/bridges.json.gz)
if "nhalias" in ON:                                       # (nhalias, 93번) 시민은 「농협 · 농협은행 앞이요」라고 한다: NH농협은행 지점(지명 자료 47곳)으로 잇는다. 지역 농 · 축협(「○○농협」)은 잇지 않는다
    for _al in ("농협", "농협은행"):
        G.ix[gaz.norm(_al)] = G.ix[gaz.norm("NH농협은행")]
        gaz.ALIAS_KEYS.add(gaz.norm(_al))
if "wikialias" in ON:
    G.add_wiki()                                          # (wikialias, 기본 끔 · 71번) 위키 별칭 사전(data/seoul/wiki_alias.tsv.gz)을 이름 색인에
if "hood" in ON:
    G.add_hoods()                                         # (hood, 기본 끔 · 87번) 「명동이에요」 · 「신촌이요」: 이름난 동네 말을 그 동 · 구 범위로
SEEN_KINDS = ["육교", "정류장", "편의점", "주유소", "역 출구", "다리", "터널", "학교", "은행", "약국", "카페", "놀이터", "화장실", "주차장", "교차로", "정자", "운동기구", "음수대", "분수", "전망대"]


def _score(q):
    """질문의 값어치: (1 − 모를 몫) × 기대 정보량 ÷ 드는 초."""
    p, sec = Q_COST.get(q["id"], (0.2, 10))
    return (1 - p) * (q["bits"] or 0) / sec


def _worth(q, R):
    """물을 만한가: 답으로 얻을 정보가 0.2비트는 되는가.
    (「줄어들 찾는 시간 ≥ 묻는 데 드는 시간」으로 정하는 비용 규칙도 넣어 재 봤다. 가상 통화 150개에서 성공이 같거나 낮고 주고받기만 늘어 뺐다 — 11-14)"""
    return q["id"] not in OFF and (q["bits"] or 0) >= 0.2


HANDOFF = {"id": "handoff", "bits": None, "options": [{"label": "현장에서 신고자에게 전화", "set": {"matter": {"handoff": True}}}]}     # 솔직한 끝(33번 1-1)
SYS_LABEL = re.compile(r"( 쪽| 사이| 보임| 안| 바깥 길| 아님)$| → | ~ ")      # 시스템이 만든 단서 이름표(시민이 직접 댄 이름이 아니다)


def _hinge(R, clues):
    """(check2) 좁혀진 자리를 받치는 「말 하나」: 빼면 좁혀짐이 풀리거나 가운데가 60m(길 위 150m) 넘게 움직이는 위치 단서.
    센 단서(시민이 「바로 앞 · 옆」이라고 한 한 점뿐인 이름, 읽어 준 번호)면 묻지 않는다 → 묻을 이름 또는 None(33번 4-2)."""
    lim = 150 if R["on_road"] else 60
    for n, c in enumerate(clues):
        if c["t"] not in ("at", "pt", "past", "before", "between"):
            continue
        r = resolve(c["k"]) if "k" in c else None
        if r is not None and r["roads"] and not len(r["x"]):
            continue                                      # 길 이름은 받침돌로 보지 않는다
        R1 = infer(clues[:n] + clues[n + 1:])
        if R1 is not None and is_done(R1) and math.hypot(R1["cx"] - R["cx"], R1["cy"] - R["cy"]) <= lim:
            continue
        lab = c.get("label") or (G.display(c["k"]) if "k" in c else "")
        single = r is not None and len(r["x"]) >= 1 and float(np.ptp(r["x"]) + np.ptp(r["y"])) <= 40
        strong = lab.startswith(("가로등", "국가지점번호")) or (c.get("how") == "바로" and single) or (c["t"] == "pt" and c.get("r", 100) <= SIG["바로"])
        if not strong and lab:
            return lab.split(" → ")[0].removesuffix(" 쪽")
    return None


CROSS_MAX = int(os.environ.get("CALL_CROSS_MAX", "3"))     # (cross) 한 통화에 교차 확인을 묻는 횟수의 상한(동규 11-21 23시: 세 번까지)


CROSS_WIDE = (600.0, 1500.0)     # (cross) 교차 확인의 답을 찾는 둘레(m): 보통 · 길 위. 가상 600통 첫 판에서 놓친 진짜 자리가 확정하려던 곳에서 280~553m였다


def _cross_wide(R, clues):
    """(cross) 교차 확인의 답을 찾을 넓은 범위 → [가운데 x, y, 반지름]: 지금 가운데 둘레 CROSS_WIDE.
    확정 직전의 90% 범위는 40m 안팎이라, 틀린 자리였으면 시민이 댄 진짜 둘레의 이름이 그 밖에 있다(첫 판: 「답 없음」으로 틀린 확정 4 → 8).
    받치는 말을 뺀 범위로 잡으면 체인 이름이 서울 전체로 퍼져 엉뚱한 원이 된다(아트박스: 6km 밖)."""
    return [round(R["cx"], 1), round(R["cy"], 1), CROSS_WIDE[1] if R["on_road"] else CROSS_WIDE[0]]


def _cross_pick(R, clues):
    """(crosspick, 99번 4-4절) 견줄 다른 자리가 있으면 「둘 중 가르기」: 남은 덩어리(mainblob) 또는 둘레 300m의 같은 이름 · 같은 상표 다른 지점.
    A = 확정하려는 자리 60m 안에만 있는 이름, B = 견줄 자리 60m 안에만 있는 이름(둘 다 자료에 한 곳뿐 · 상표 아님 · 시민이 댄 이름 아님) → closest 질문 또는 None.
    A를 고르면 맞음(핀 그대로), B를 고르면 갈아탐(B 쪽으로 다시 셈)."""
    P, anc = (R["cx"], R["cy"]), anchor(R, clues)
    Q = R.get("blob_alt")
    if Q is None and anc:
        t = twins(anc["name"], anc["p"], np.array([R["cx"]]), np.array([R["cy"]]), 300.0)
        b = next((G.brand[int(i)] for i in G.near(anc["p"][0], anc["p"][1], 30) if gaz.norm(G.name[int(i)]) == gaz.norm(anc["name"]) and G.brand[int(i)]), None)
        t = t or (twins(b, anc["p"], np.array([R["cx"]]), np.array([R["cy"]]), 300.0) if b else None)
        Q = min((q for q in t or [] if math.hypot(q[0] - anc["p"][0], q[1] - anc["p"][1]) > 40), key=lambda q: math.hypot(q[0] - P[0], q[1] - P[1]), default=None)
    if Q is None or math.hypot(Q[0] - P[0], Q[1] - P[1]) < 120:
        return None                                       # 견줄 자리가 없거나 너무 가까우면 가를 수 없다
    said = {gaz.norm((c.get("label") or c.get("k") or "").split(" → ")[0]) for c in clues}

    def only(near, far):
        idx = [int(i) for i in G.near(near[0], near[1], 60) if len(G.name[i]) >= 3 and not G.brand[i] and not gaz.GENERIC.match(G.name[i].replace(" ", ""))
               and G.kind[i] not in ("동네", "산") and math.hypot(G.x[i] - far[0], G.y[i] - far[1]) > 120 and gaz.norm(G.name[i]) not in said
               and len(resolve(gaz.norm(G.name[i]))["x"]) == 1]
        return min(idx, key=lambda i: math.hypot(G.x[i] - near[0], G.y[i] - near[1]) / PROM.get(G.kind[i], 1.0), default=None)
    a, b = only(P, Q), only(Q, P)
    if a is None or b is None:
        return None
    pa, pb = [round(float(G.x[a]), 1), round(float(G.y[a]), 1)], [round(float(G.x[b]), 1), round(float(G.y[b]), 1)]
    opt = lambda i, p, o, v: {"label": G.name[i], "set": {"clues": [{"t": "closest", "p": p, "others": [o], "s": round(1.5 * R["r"], 1), "sure": True, "via": "cross", "label": f"{G.name[i]}이 더 가까움"}],      # noqa: E731
                                                          "matter": {"cross": v, "cross_name": G.name[i] if v == "ok" else None}}}
    return {"id": "closest", "bits": None, "cross": "pick", "options": [opt(a, pa, pb, "ok"), opt(b, pb, pa, "switch")]}


def _many_here(name, p, cx, cy):
    """(cross) 그 이름이 범위 둘레 300m에 또 있나(같은 이름 · 같은 상표의 다른 지점)."""
    if twins(name, p, np.array([cx]), np.array([cy]), 300.0):
        return True
    b = next((G.brand[int(i)] for i in G.near(p[0], p[1], 30) if gaz.norm(G.name[int(i)]) == gaz.norm(name) and G.brand[int(i)]), None)
    return bool(b) and bool(twins(b, p, np.array([cx]), np.array([cy]), 300.0))


def _cross(R, clues, asked):
    """(cross, 99번 4-3절) 위험한 확정인가 → 교차 확인에서 「○○ 말고」로 댈 이름(받치는 이름) 또는 None.
    켜는 때: 받치는 말이 하나뿐이고 약함(_hinge) · 그 이름이 둘레에 또 있음(같은 이름 · 같은 상표 · 넓은 장소) · 앞서 「아니요」가 있었음.
    켜지 않는 때: 자동차전용도로 위 · 번호를 읽어 줬음 · 위치 질문을 여덟 번 넘게 함 · 이번 좁힘에서 이미 물음 · 한 통화 상한(CROSS_MAX) · 서로 다른 이름 둘 이상이 받침."""
    ids = [(a or "").rstrip("!") for a in asked]
    since = max((n for n, a in enumerate(asked) if a in ("confirm!", "check!")), default=-1)
    if ids.count("check") + ids.count("crosspick") >= CROSS_MAX or {"check", "crosspick"} & set(ids[since + 1:]) or sum(1 for a in ids if a in LOCQ) > 8:
        return None
    if R["on_road"] and any(_xw(i) for i in R["ctx"]["roads"]):
        return None
    labs = [c.get("label") or "" for c in clues]
    if any(lab.startswith(("가로등", "국가지점번호")) for lab in labs):
        return None
    anc = anchor(R, clues)
    hinge = _hinge(R, clues)
    if hinge is None:                                     # 받치는 말이 하나뿐이 아니면, 둘레 80m 안에 닿는 서로 다른 이름이 둘 이상인가
        near = set()
        for c in clues:
            if c["t"] in ("at", "pt") and (c.get("label") or c.get("k")):
                pts = [c["p"]] if "p" in c else list(zip(resolve(c["k"])["x"], resolve(c["k"])["y"])) if "k" in c else []
                if pts and min(math.hypot(px - R["cx"], py - R["cy"]) for px, py in pts) <= 80:
                    near.add(gaz.norm((c.get("label") or c["k"]).split(" → ")[0]))
        if len(near) >= 2:
            return None
    many = bool(anc) and (bool(anc.get("ext")) or _many_here(anc["name"], anc["p"], R["cx"], R["cy"]))
    split = "crosspick" in ON and R.get("blob_alt") is not None      # (crosspick) 가능성이 갈라짐: mainblob이 좁혔는데 다른 덩어리가 남음
    if hinge or many or split or since >= 0:
        return (anc or {}).get("name") or hinge or "이 자리"
    return None


def _fresh(asked):
    """마지막 「아니요」(confirm! · check!) 뒤에 새 위치 단서(「!」 없는 위치 질문)를 받았나. 「아니요」가 없었으면 참."""
    asked = list(asked)
    rej = [i for i, a in enumerate(asked) if a in ("confirm!", "check!")]
    return not rej or any(a in LOCQ for a in asked[rej[-1] + 1:])


def questions(R, clues, matter, asked=(), same=None):
    """지금 물을 수 있는 질문을 설 순서대로 → [{id, bits, options: [{label | word, set}], …}]. 맨 앞이 화면에 뜬다."""
    conds = []
    if matter.get("type") is None and not matter.get("told"):     # 무슨 일인지 한 번 말했으면 다시 묻지 않는다
        conds.append({"id": "what", "bits": None, "options": []})
    elif matter.get("animal_matter"):
        stuck = lambda q: "matterstop" in ON and sum(1 for a in asked if (a or "").rstrip("!") == q) >= 2      # (matterstop) 일 질문(살았나 · 목줄)은 두 번 물어 답을 못 읽으면 더 묻지 않는다(모름으로 두고 위치로)
        if matter.get("alive") is None and stuck("alive"):
            pass
        elif matter.get("alive") is None:
            conds.append({"id": "alive", "bits": None, "options": [{"word": "살아 있음", "set": {"matter": {"alive": True}}}, {"word": "죽은 것 같음", "set": {"matter": {"alive": False}}}]})
        elif matter["alive"] and matter.get("leash") is None and not stuck("leash"):
            conds.append({"id": "leash", "bits": None, "options": [{"word": "목줄 있음", "set": {"matter": {"leash": True}}}, {"word": "목줄 없음", "set": {"matter": {"leash": False}}}]})
    if R is None:
        return [{"id": "where", "bits": None, "options": []}] + conds
    confirm = {"id": "confirm", "bits": None, "options": [{"word": "맞음", "set": {"confirm": True}}, {"word": "아님", "set": {"confirm": False}}]}
    if "chainpick" in ON and any((a or "").rstrip("!") == "closest" for a in asked):
        R["chainskip"] = True                             # (chainpick · 89번) 어느 지점인지 이미 물었다: 고른 지점(한 점 단서)만 기준이 되고, 여러 지점의 상표 단서는 기준에서 뺀다(「모르겠어요」면 chainref처럼)
    x, y, w = _sample(R)
    ctx = R["ctx"]
    need_dir = R["on_road"] and ctx["head"] is None and any(_xw(i) for i in ctx["roads"])
    if need_dir and "dirstop" in ON and list(asked).count("dir!") >= 2:
        need_dir = False                                  # (dirstop · 82번) 좁혀진 뒤의 방향 질문도 다른 위치 질문처럼 두 번 물어 못 얻으면 그만(「방향은 잘 모르겠어요」에 같은 질문을 여덟 번 되풀이하다 끊긴 평가 통화 74-063)
    zone = None                                           # 공원 안 · 바깥: 넘길 곳이 갈리는 경계
    if not R["on_road"] and not any(c["t"] in ("in", "out") for c in clues):
        best = None
        for i, pk in enumerate(G.parks):
            x0, y0, x1, y1 = pk["box"]
            if x1 < x.min() or x0 > x.max() or y1 < y.min() or y0 > y.max():
                continue
            p_in = float(w[in_ring(x, y, pk["ring"])].sum())
            if 0.12 < p_in < 0.88 and (best is None or abs(p_in - 0.5) < abs(best[1] - 0.5)):
                best = (i, p_in)
        if best:
            i, p_in = best
            name = G.parks[i]["name"]
            zone = {"id": "zone", "bits": _bits([p_in, 1 - p_in]), "area": name,
                    "options": [{"label": f"{name} 안", "set": {"clues": [{"t": "in", "a": ["park", i], "label": f"{name} 안"}]}},
                                {"label": "공원 바깥 길", "set": {"clues": [{"t": "out", "a": ["park", i], "label": f"{name} 바깥 길"}]}}]}
    rejected = bool(asked) and asked[-1] in ("confirm!", "check!")     # 방금 되말한 자리가 아니라고 했다
    check2 = "check2" in ON or "check2all" in ON
    named, more = None, False
    ev = next((c for c in reversed(clues) if c.get("via") == "check"), None) if check2 else None
    if ev is not None and list(asked)[-1:] == ["check"]:  # 열린 확인 2판: 방금 댄 이름은 증거로 더했다. 다시 셈한 뒤에 가른다(33번 4-2)
        R0 = infer([c for c in clues if c is not ev])
        moved = math.hypot(R["cx"] - R0["cx"], R["cy"] - R0["cy"]) if R0 else 1e9
        if is_done(R) and moved <= (80 if R["on_road"] else 25) and ev.get("single"):
            named = ev.get("label")                       # 통과: 마지막 예 · 아니요에 그 이름을 넣는다
        elif is_done(R) and moved > (80 if R["on_road"] else 25):
            more = True                                   # 거름: 가운데가 많이 움직였다 — 확인하지 않고 한 번 더 묻는다(「거기는 아니다」는 붙이지 않는다)
    if is_done(R) and not rejected and "loop" in ON and not _fresh(asked):
        return conds + [dict(HANDOFF)]                    # 「아니요」 뒤 새 단서 없이 같은 자리로 돌아왔다: 같은 확인을 되묻지 않고 솔직하게 끝낸다(CALL_ON=loop)
    if is_done(R) and not rejected and not more:          # 가운데가 막힌 도로는 방향까지 받아야 찾아간다
        pin = [] if "pinq" in OFF else [q for q in _pin_questions(R, clues, matter) if q["id"] + "!" not in asked]     # 마무리: 이름 붙은 한 점 + 상대 위치 + 일의 종류마다 하나
        last = dict(confirm, name=named) if named else confirm
        if "cross" in ON and not named:                   # (cross, 99번 4절) 위험한 확정이면 「맞으실까요?」 앞에 다른 이름 하나를 묻는다. 답은 맞음 · 어긋남 판정에만(server.read 「check」)
            since_ = max((n for n, a in enumerate(asked) if a in ("confirm!", "check!")), default=-1)
            if matter.get("cross") == "ok" and any((a or "").rstrip("!") in ("check", "crosspick") for a in list(asked)[since_ + 1:]):
                last = dict(confirm, name=matter.get("cross_name")) if "crossname" in ON else confirm      # 맞음: 핀은 그대로. crossname이면 그 이름까지 되말한다(confirm_named — 그 이름이 보여서 「네」가 나오기 쉬워 따로 잰다)
            else:
                h = _cross(R, clues, asked)
                if h:
                    last = (_cross_pick(R, clues) if "crosspick" in ON else None) or {"id": "check", "bits": None, "name": h, "cross": True, "wide": _cross_wide(R, clues), "options": [{"word": "잘 모르겠음", "set": {"clues": []}}]}
        elif check2 and not named:
            since_ = max((n for n, a in enumerate(asked) if a in ("confirm!", "check!")), default=-1)
            if not any((a or "").rstrip("!") == "check" for a in list(asked)[since_ + 1:]):
                h = _hinge(R, clues) if "check2all" not in ON else (anchor(R, clues) or {}).get("name")
                if h:                                     # 말 하나에 기댄 확정일 때만 묻는다(check2all이면 늘)
                    last = {"id": "check", "bits": None, "name": h, "options": [{"word": "잘 모르겠음", "set": {"clues": []}}]}
        elif "check" in ON:                                 # 열린 확인: 「네」로 기우는 시민도 이름은 지어내기 어렵다. 한 번 묻고, 이름을 못 대면 예 · 아니요로
            since_ = max((n for n, a in enumerate(asked) if a in ("confirm!", "check!")), default=-1)
            anc = anchor(R, clues)
            if anc and not any((a or "").rstrip("!") == "check" for a in list(asked)[since_ + 1:]):
                last = {"id": "check", "bits": None, "name": anc["name"], "options": [{"word": "잘 모르겠음", "set": {"clues": []}}]}
        return conds + ([zone] if zone and matter.get("by_place") and "zone!" not in asked else []) + ([_q_dir(R, x, y, w)] if need_dir else []) + pin + [last]   # 넘길 곳이 갈리는 경계면 좁혀진 뒤에도 안팎을 묻는다
    ids = [(a or "").rstrip("!") for a in asked]
    miss = set()                                          # 방금 물었는데 시민이 답하지 못한 질문(끝에 ! 표시). 다른 답으로 범위가 줄기 전에는 다시 묻지 않는다
    for a in reversed(list(asked)):
        if a and a.endswith("!"):
            miss.add(a[:-1])
        elif a in LOCQ:
            break
    miss |= {q for q in LOCQ if list(asked).count(q + "!") >= 2}      # 두 번 물어 두 번 다 못 얻은 질문은 이 통화에서 더 묻지 않는다
    if "softnot" in ON and sum(1 for a in ids if a == "either") >= 3:
        miss.add("either")                                # 둘 중 고르기는 한 통화에 세 번까지
    if "lamponce" in ON and "lampno" in ids:
        miss.add("lampno")                                # (lamponce, 기본 끔 · 49번) 가로등 번호는 한 통화에 한 번: 이미 지나온 기둥은 다시 볼 수 없다
    if "lamponce2" in ON and "lampno" in (matter.get("blind") or ()):
        miss.add("lampno")                                # (lamponce2, 기본 끔 · 49번) 「번호 못 봤어요」를 들었을 때만 다시 안 묻는다(「모르겠어요」는 다시 물으면 답할 수 있다)
    if "seenonce" in ON:                                  # (seenonce, 기본 끔 · 47번 방법 1) 시민 둘레는 통화 내내 같다: 「안 보여요」 · 「번호 못 봤어요」를 한 번 들은 열린 질문은 다시 묻지 않는다
        blind = set(matter.get("blind") or ())
        miss |= ({"mark", "finer", "mark_again"} if blind & {"mark", "finer", "mark_again"} else set()) | (blind & {"lampno"})
    if "hardstop" in ON and matter.get("hard"):
        miss |= {"dist", "from"}                          # (hardstop, 기본 끔 · 71번) 「멀리 보이기만 해요」 · 「가운데요」라고 한 시민에게 몇 걸음 · 어느 쪽을 다시 묻지 않는다
    if "closestcap" in ON and ids.count("closest") >= 2:
        miss.add("closest")                               # (closestcap · 75번) 「어디가 가장 가까우세요?」는 한 통화에 두 번까지: 「다 멀어요」를 듣고도 보기만 바꿔 네댓 번 물었다(올림픽공원 둘레길 · 뚝섬한강공원)
    if zone and "zone" in miss:
        zone = None
    dup = lambda q: bool(same) and "sameopts" in ON and q["id"] in SAMEQ and same(q)     # noqa: E731  (sameopts · 75번) 이 통화에서 같은 보기로 이미 물었던 질문: 그 답으로 범위가 달라지지 않았다는 뜻이라 사다리의 다음 질문으로 넘어간다
    loc = [q for q in [_q_alike(R, clues)] if q and "alike" not in miss and ids[-1:] != ["alike"] and ids.count("alike") < 2]      # 소리가 같은 이름이 아직 갈리지 않았으면 그것부터(어느 구인지). 잇달아 묻지 않고 두 번까지
    express = R["on_road"] and any(_xw(i) for i in ctx["roads"])
    drive = R["on_road"] and not express and "drive" in ON and any(c.get("drive") for c in clues)     # 큰길을 차로 지나간 통화(33번 5-2)
    if (express or drive) and not loc:                    # 다리 · 나들목(큰길이면 교차로 · 역 출구 · 정류장 …)으로 가르는 질문
        lamp = {"id": "lampno", "bits": math.log2(max(1.0, R["r"] / 15.0)), "options": []} if express and G.lamps and R["r"] > 100 else None     # 가로등 기둥 번호: 읽을 수만 있으면 한 번에 기둥 하나로(모를 몫이 커서 점수는 낮게 나온다)
        loc = [_q_between(R, x, y, w, clues), _q_marks(R, x, y, w, "passed", clues), _q_ago(R, clues), lamp, _q_next(R, x, y, w, clues),
               _q_dir(R, x, y, w) if ctx["head"] is None and any(c["t"] in ("past", "before") for c in clues) else None]
        loc = sorted((q for q in loc if q and _worth(q, R) and q["id"] not in miss and not dup(q)), key=lambda q: -(q["bits"] if "score" in OFF else _score(q)))
    if not loc:                                           # 사다리: 넓으면 가까운 역 → 간판 · 건물 이름 → (좁혀지면) 바로 앞의 것 → 둘 중 고르기 → 보이는 것의 종류 → 「바로 앞인지」
        r = R["r"]     # 넓을 때 역 · 간판을 둘 다 모른다고 하면 범위째 확인하기 전에 둘 중 고르기 · 보이는 것을 묻는다(11-15 극한 세트)
        order = ["station", "mark", "either", "seen"] if r > 1500 else ["mark", "station", "either"] if r > 900 else ["mark", "either", "seen"] if r > 250 else ["finer", "either", "seen", "near"]
        if "addrq" in ON and not R["on_road"] and "addr" not in ids and not _area_at(G.parks, R["cx"], R["cy"]):     # (addrq, 기본 끔 · 47번 방법 2) 간판 · 건물 이름을 못 댔으면 건물 주소판(도로명 + 번호)을 한 번 묻는다. 길 위(운전 중) · 공원 안은 묻지 않는다
            k = next(n for n, qid in enumerate(order) if qid in ("mark", "finer"))
            order = order[:k + 1] + ["addr"] + order[k + 1:]
        if "closest" in ON and r > 250 and _area_at(G.parks, R["cx"], R["cy"]):
            order = ["mark", "closest", "either", "seen"]    # 넓은 공원: 이름을 떠올리기보다 보기에서 고르기(33번 2-4)
        if "dist" in ON and r <= 250 and ("distall" in ON or _area_at(G.parks, R["cx"], R["cy"])):
            order = ["dist", "finer", "either", "seen"]  # 표지까지 얼마나 떨어졌는지를 「바로 앞에 뭐가 보이세요?」보다 먼저(33번 2-2). 공원 안에서만(distall이면 어디서나)
        if "closest2" in ON and 80 < r <= 250 and _area_at(G.parks, R["cx"], R["cy"]) and sum(1 for c in clues if c["t"] == "closest") == 1:
            order = ["closest"] + order                   # (closest2) 첫 판으로 줄어든 범위 안의 것 넷으로 한 번 더
        if r <= 150 and ids.count("from") < 2 and "from" not in OFF:     # 이름 하나 둘레로 좁혀졌으면 「그 표지에서 어느 쪽」을 먼저(같은 말 「○○ 근처」만 거듭되지 않게)
            order = ["from"] + order
        if "parknum" in ON and r > 100 and "mark" in ids and "lampno" not in ids and _area_at(G.parks, R["cx"], R["cy"]) and _lamps_within(R["cx"], R["cy"], R["r_cover"]):
            order = ["lampno"] + order                    # 공원 안, 이름으로 못 좁혔고 그 범위에 번호를 아는 가로등이 있으면 기둥 번호를(33번 2-6). 지금 자료로는 서울숲 · 어린이대공원뿐
        if "rimask" in ON and R.get("ringed") and R["r_cover"] > 250 and ids.count("closest") < 2:
            order = ["closest"] + [q for q in order if q != "closest"]     # (rimask · 75번) 둘레로 읽은 곳이 아직 넓으면(석촌호수 둘레 2.5km): 둘레의 어느 쪽인지부터(둘레에 놓인 표지 넷 가운데 가장 가까운 것). 공원 안이 아니어도(호수 가운데는 물) 묻는다
        make = {"near": lambda: _q_near(R, clues), "either": lambda: _q_either(R, x, y, w, clues), "seen": lambda: _q_seen(R, x, y, w, clues), "from": lambda: _q_from(R, x, y, w, clues),
                "dist": lambda: _q_dist(R, clues), "closest": lambda: _q_closest(R, x, y, w, clues),
                "lampno": lambda: {"id": "lampno", "bits": math.log2(max(1.0, r / 15.0)), "options": []},
                "addr": lambda: {"id": "addr", "bits": math.log2(max(1.0, r / 15.0)), "options": []}}
        ask = lambda qid: make[qid]() if qid in make else _q_marks(R, x, y, w, qid, clues)   # noqa: E731
        loc = next(([q] for q in (ask(qid) for qid in order if qid not in miss) if q and _worth(q, R) and not dup(q)), [])
        if "chainpick" in ON and not R.get("chainskip") and loc and loc[0]["id"] in ("dist", "from", "near"):
            cq = _chain_q(R, clues, loc[0].get("name"))
            if cq:
                loc = [cq]                                # (chainpick · 89번) 기준이 될 상표가 범위 둘레에 여럿: 거리 · 방향 · 「바로 앞입니까」를 묻기 전에 어느 지점인지
    since = max((n for n, a in enumerate(asked) if a in ("confirm!", "check!")), default=-1)     # 「아니요」로 되돌아온 뒤에는 다시 센다
    n_loc = sum(1 for a in ids[since + 1:] if a in LOCQ)
    if rejected:                                          # 어느 말이 달랐는지부터 짚는다(한 걸음만 되돌리기)
        said = [c.get("label") for c in clues if c["t"] in ("at", "pt", "past", "before", "between", "in", "out", "head", "cat") and c.get("label")]
        if "loop" in ON:                                  # 「어느 말이 달랐을까요?」는 시민이 직접 댄 이름 둘일 때만(「○○ 쪽」 · 「A → B 쪽」은 시스템이 만든 이름표)
            said = [lab for lab in said if not SYS_LABEL.search(lab)]
            if len(said) < 2 and "mark" not in miss:
                again = _q_marks(R, x, y, w, "mark", clues) or {"bits": None, "options": []}
                loc = [dict(again, id="mark_again")]
        said = said[-2:]
        if len(said) >= 2 and "which" not in OFF:
            return conds + [{"id": "which", "bits": None, "options": [{"label": lab, "set": {"drop": [lab]}} for lab in said] + [{"word": "잘 모르겠음", "set": {"clues": []}}]}]
        if not loc and "mark" not in miss:                 # 짚을 말이 하나뿐이면 같은 자리를 다시 되묻지 않고, 보이는 것을 새로 묻는다
            loc = [q for q in [_q_marks(R, x, y, w, "mark", clues)] if q]
    if (n_loc >= LOCCAP or not (loc or zone)) and not (rejected and sum(1 for a in asked if a in ("confirm!", "check!")) < 3 and loc):
        sz = size_of(R)
        stalled = ("stallend" in ON and any((a or "").endswith("!") and a[:-1] in LOCQ for a in list(asked)[-3:])
                   and sz["m"] <= (400 if sz["kind"] == "length" else 150)
                   and not ("rimline" in ON and R.get("ringed") and not R.get("hole")))     # (rimline · 75번) 둘레의 한쪽 띠로 남은 범위는 「○○ 서쪽 둘레」로 되물어 받는다(가운데 한 점이 아니라 둘레의 자리라 틀린 쪽이면 시민이 잡는다)      # (stallend) 마지막 위치 질문들이 범위를 못 줄였는데 남은 범위가 좁은 구간: 틀릴 수 있는 구간을 「맞습니까」로 받지 않고 솔직한 끝(넓은 범위째 확인은 그대로, 11-16 갈래 2)
        return conds + [dict(HANDOFF) if ("loop" in ON and not _fresh(asked)) or stalled else confirm]      # 더 물어도 거의 안 줄면 범위째 확인받고 넘긴다(「아니요」 뒤 새 단서가 없으면 솔직한 끝)
    return conds[:1] + ([zone] if zone else []) + conds[1:] + loc


PIN_Q = {"carcass": "lane", "road": "lane", "parking": "lane", "stray": "went", "light": "plate", "bike": "plate"}    # 일의 종류마다 끝내기 전에 하나 더 알아야 찾아갈 수 있는 것
PIN_KEYS = ("side", "lane", "went", "plate", "same")     # 마무리 질문의 답이 담기는 칸(일의 칸과 함께 들고 다닌다)
KIND_WORD = {"역 출구": "지하철 출구", "정류장": "버스 정류장", "역": "역", "다리": "다리", "나들목": "나들목", "교차로": "교차로"}


def anchor(R, clues):
    """확정 문장의 기준이 될 「이름 붙은 한 점」: 시민이 말한 표지 가운데 가장 가까운 것(80m 안), 없으면 눈에 띄는 가까운 곳(60m 안).
    → {name, p, d, tight, ext} 또는 None. tight = 시민이 그 표지 「바로 앞 · 옆」이라고 이미 말했다. ext = (bigplace) 그 표지가 넓은 장소면 그 크기(m), 아니면 0 — 넓은 장소의 「바로 앞」은 p가 아니다."""
    x, y, ctx, said = R["cx"], R["cy"], R["ctx"], []
    for n, c in enumerate(clues):
        lab = c.get("name") or c.get("label") or ""
        if lab.endswith(" 쪽") or c["t"] not in ("pt", "at", "past", "before"):
            continue
        tight = (c["t"] == "pt" and c.get("r", 100.0) <= SIG["바로"]) or c.get("how") == "바로"
        if "twinsanchor" in ON and "p" in c and lab and not (c.get("sure") and c.get("name")) and not lab.startswith(("가로등", "국가지점번호")) and twins(lab.split(" → ")[0], c["p"], np.array([x]), np.array([y]), 300.0):
            continue                                      # (twinsanchor, 기본 끔 · 53번) 둘레 300m에 같은 이름이 또 있으면 그 이름으로 되말하지 않는다. twins에서 떼어 냈다: 공원 안에서 확인 문장의 기준 이름이 시민에게 안 보이는 것으로 바뀌어 맞는 자리에 「아니요」를 받았다
        if "p" in c and lab:
            e = _flat(c)                                      # (bigplace) 넓은 장소를 「바로 앞」이라고 한 단서면 그 크기만큼은 「그 장소 앞」으로 친다(「근처」처럼 넓게 말한 단서는 전처럼 그 한 점까지의 거리)
            said.append((max(0.0, math.hypot(c["p"][0] - x, c["p"][1] - y) - e) if e else math.hypot(c["p"][0] - x, c["p"][1] - y), lab, [float(c["p"][0]), float(c["p"][1])], tight, _flat(c, SIG["바로"]), bool(c.get("offopt"))))
        elif "k" in c:
            r = resolve(c["k"])
            many = "saidanchor" in ON and c.get("offopt") and c["t"] == "at" and len(r["x"]) > 40      # (saidanchor) 보기 밖에서 댄 상표는 지점이 많아도(CU 3,566곳) 가운데 가까운 지점이면 기준으로(지점 이름까지 되말함)
            if (0 < len(r["x"]) <= 40 or many) and not r["areas"] and not _pk(r):
                j = int(np.argmin(np.hypot(r["x"] - x, r["y"] - y)))
                q = _pos_near(ctx, n, x, y) or (float(r["x"][j]), float(r["y"][j]))
                if c["t"] == "at" and r["ids"][j] in _bridges(r, n, ctx) and float(bridge_dist(r["ids"][j], np.array([x]), np.array([y]))[0]) <= 40:
                    q = (x, y)                                 # (bridgeline) 범위 가운데가 그 다리 밑 · 바로 옆이면 다리의 「그 자리」로 친다(가운데 점까지의 거리로 재면 수백 m)
                lab = lab or G.display(c["k"])
                full = G.name[r["ids"][j]] if r.get("ids") else lab
                if len(r["x"]) > 1 and gaz.norm(full) != gaz.norm(lab) and gaz.norm(lab) in gaz.norm(full):
                    lab = full                                 # 같은 상표가 여럿이면 지점 이름까지 되말한다(「BYC 바로 앞」 → 「BYC 천호점 바로 앞」: 4.7km 떨어진 다른 지점으로 확정한 일, 11-14 밤)
                ext = _exts(r, _sigma(c, r["kinds"])) if c["t"] == "at" else None
                e = float(ext[j]) if ext is not None else 0
                said.append((max(0.0, math.hypot(q[0] - x, q[1] - y) - e) if e else math.hypot(q[0] - x, q[1] - y), lab, [float(q[0]), float(q[1])], tight, _flat(_big(r["ids"][j]), SIG["바로"]) if r.get("ids") else 0, bool(c.get("offopt"))))
    best = min(said, default=None)
    if best and best[0] <= 80:
        return {"name": best[1], "p": [round(best[2][0], 1), round(best[2][1], 1)], "d": best[0], "tight": best[3], "ext": best[4]}
    idx = [int(i) for i in G.near(x, y, 60) if len(G.name[i]) >= 3 and not gaz.GENERIC.match(G.name[i].replace(" ", "")) and G.kind[i] not in ("동네", "산") and _road_ok(i, R) and not ("selfname" in ON and self_area(int(i)))]
    if "twinsanchor" in ON:
        idx = [i for i in idx if not twins(G.brand[i] or G.name[i], (G.x[i], G.y[i]), np.array([x]), np.array([y]), 300.0)]
    if not idx:
        return None
    j = min(idx, key=lambda i: math.hypot(G.x[i] - x, G.y[i] - y) / PROM.get(G.kind[i], 1.0))
    return {"name": G.name[j], "p": [round(float(G.x[j]), 1), round(float(G.y[j]), 1)], "d": math.hypot(G.x[j] - x, G.y[j] - y), "tight": False}


def twins(label, p, x, y, pad=150.0):
    """(twins · 53번) 그 이름의 다른 곳이 지금 범위(점 x, y의 둘레 pad m)에 따로 있나 → 서로 40m 넘게 떨어진 자리들 [[x, y], …](p 포함, 둘 이상일 때만) 또는 None.
    같은 이름 · 같은 상표 · 그 이름으로 시작하는 지점 이름(「이마트24」 ↔ 「이마트24 경희대점」)을 같은 이름으로 본다: 시민은 「이마트24 옆이에요」라고만 말한다."""
    k = gaz.norm(label)
    if len(k) < 2:
        return None
    keep = [[float(p[0]), float(p[1])]]
    for i in _places_in(float(np.min(x)) - pad, float(np.min(y)) - pad, float(np.max(x)) + pad, float(np.max(y)) + pad, 8000):
        n = gaz.norm(G.name[i])
        if (n == k or n.startswith(k) or (G.brand[i] and gaz.norm(G.brand[i]) == k)) and all(math.hypot(G.x[i] - q[0], G.y[i] - q[1]) > 40 for q in keep):
            keep.append([round(float(G.x[i]), 1), round(float(G.y[i]), 1)])
    return keep if len(keep) >= 2 else None


def _same_name(anc):
    """확정할 이름과 같은 이름의 곳이 300m 안에 따로 있나(「서울대입구역5번출구」 버스 정류장과 지하철 출구가 90m 떨어져 있다) → 장소 번호들."""
    k = gaz.norm(anc["name"])
    idx = [int(i) for i in G.near(anc["p"][0], anc["p"][1], 300) if gaz.norm(G.name[i]) == k]
    keep = []
    for i in sorted(idx, key=lambda i: math.hypot(G.x[i] - anc["p"][0], G.y[i] - anc["p"][1])):
        if all(math.hypot(G.x[i] - G.x[j], G.y[i] - G.y[j]) > 40 for j in keep):
            keep.append(i)
    return keep[:3] if len(keep) >= 2 else []


def _pin_questions(R, clues, matter):
    """범위가 좁혀진 뒤, 원이 아니라 「이름 붙은 한 점 + 상대 위치」로 끝내기 위한 질문들."""
    out, anc = [], anchor(R, clues)
    same = _same_name(anc) if anc and matter.get("same") is None and "same" not in OFF else []
    if same:                                               # 같은 이름이 가까이 둘 이상: 어느 것인지 먼저(같은 이름의 다른 곳을 확정하지 않게)
        kw = [KIND_WORD.get(G.kind[i], G.kind[i]) for i in same]
        labels = [f"{w} 쪽" for w in kw] if len(set(kw)) == len(kw) else [f"{G.name[i]} {w} 쪽" for i, w in zip(same, kw)]
        if len(set(labels)) == len(labels):
            return [{"id": "same", "bits": None, "name": anc["name"], "options": [
                {"label": lab, "set": {"matter": {"same": G.name[i]}, "clues": [dict({"t": "pt", "p": [round(float(G.x[i]), 1), round(float(G.y[i]), 1)], "r": SIG["바로"], "sure": True, "name": G.name[i], "label": f"{G.name[i]} ({w})"}, **_big(i))]}}
                for i, w, lab in zip(same, kw, labels)] + [{"word": "잘 모르겠음", "set": {"matter": {"same": "모름"}}}]}]
    if anc and not R["on_road"] and not anc["tight"] and matter.get("side") is None:       # 그 표지의 바로 앞인지 · 옆인지 · 건너편인지
        tight = lambda word, r: dict({"t": "pt", "p": anc["p"], "r": r, "sure": True, "name": anc["name"], "label": f"{anc['name']} {word}"}, **({"ext": anc["ext"]} if anc.get("ext") else {}))   # noqa: E731
        out.append({"id": "side", "bits": None, "name": anc["name"], "options": [
            {"word": "바로 앞", "set": {"matter": {"side": "앞"}, "clues": [tight("바로 앞", 8.0)]}}, {"word": "바로 옆", "set": {"matter": {"side": "옆"}, "clues": [tight("바로 옆", 14.0)]}},
            {"word": "길 건너편", "set": {"matter": {"side": "건너편"}}}, {"word": "조금 떨어짐", "set": {"matter": {"side": "근처"}}}]})
    kind = PIN_Q.get(matter.get("type"))
    if kind == "lane" and matter.get("lane") is None:      # 길의 일: 차로 위인지 길가인지
        out.append({"id": "lane", "bits": None, "options": [{"word": w, "set": {"matter": {"lane": w}}} for w in ("차로", "갓길 · 길가", "보도")]})
    if kind == "went" and matter.get("alive") and matter.get("went") is None:      # 움직이는 동물: 마지막으로 본 곳에서 어디로 갔나
        x, y = R["cx"], R["cy"]
        idx = [int(i) for i in G.near(x, y, 250) if math.hypot(G.x[i] - x, G.y[i] - y) >= 70 and len(G.name[i]) >= 3 and not gaz.GENERIC.match(G.name[i].replace(" ", "")) and G.kind[i] not in ("동네", "산")]
        idx.sort(key=lambda i: -PROM.get(G.kind[i], 1.0))
        two = lambda idx: idx[:1] + [i for i in idx[1:] if idx and (G.x[i] - x) * (G.x[idx[0]] - x) + (G.y[i] - y) * (G.y[idx[0]] - y) < 0][:1]     # noqa: E731
        dirs = two(idx)
        if "hangulopt2" in ON and not all(_ko(i) for i in dirs):
            dirs = _ko_swap(dirs, two([i for i in idx if _ko(i)]))      # (hangulopt2) 「○○ 쪽으로 감」 보기도 같은 수만큼 한글 이름이 있을 때만     # 서로 반대쪽의 두 곳
        out.append({"id": "went", "bits": None, "options": [{"word": "그 자리에 있음", "set": {"matter": {"went": "그 자리"}}}]
                    + [{"label": f"{G.name[i]} 쪽으로 감", "set": {"matter": {"went": G.name[i]}}} for i in dirs] + [{"word": "못 봄", "set": {"matter": {"went": "모름"}}}]})
    if R["on_road"] and G.lamps and matter.get("ask_lamp") and matter.get("plate") is None and any(_xw(i) for i in R["ctx"]["roads"]):
        out.append({"id": "lampno", "bits": None, "options": [{"word": "번호 안 보임", "set": {"matter": {"plate": "없음"}}}]})      # 자동차전용도로: 마지막에 가로등 기둥 번호로 기둥 하나까지
    if kind == "plate" and matter.get("plate") is None:    # 시설물의 일: 기둥 · 시설물의 번호판이 그 시설물을 가리킨다
        out.append({"id": "plate", "bits": None, "options": [{"word": "번호 안 보임", "set": {"matter": {"plate": "없음"}}}]})
    return out


def _q_alike(R, clues):
    """소리가 같은 이름(「통일로|동일로」)이 아직 갈리지 않았을 때: 어느 구의 그 이름인지 묻는다(11-16). 보기마다 그 이름이 지나는 구(많아야 둘).
    구로 갈리지 않으면(「사당로2자길 · 2차길」은 둘 다 동작구) 보기마다 가장 가까운 역 · 큰 표지 이름으로."""
    if not R.get("alike"):
        return None
    n, shares = R["alike"][0]
    c = clues[n]
    keys = c["k"].split("|")
    pts, gus = {}, {}
    for k in keys:
        r = resolve(k)
        pts[k] = [(float(p[0]), float(p[1])) for i in r["roads"] for p in G.road_xy(i)[::6]] + list(zip(r["x"].tolist(), r["y"].tolist()))
        cnt = {}
        for p in pts[k][:400]:
            g = _area_at(G.gu, *p)
            if g:
                cnt[g] = cnt.get(g, 0) + 1
        gus[k] = [g for g, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:2]]
    by_gu = all(any(g not in gus[o] for g in gus[k]) for k in keys for o in keys if o != k)
    opts = []
    for k in keys:
        name, where = G.display(k), " · ".join(gus[k])
        if not by_gu:                                     # 구로 갈리지 않는다: 이 길에서 가깝고 다른 길에서는 100m 넘게 더 먼 역 · 큰 표지. 없으면 묻지 않는다(간판 질문이 가른다)
            mine, other = np.array(pts[k]), np.array([p for o in keys if o != k for p in pts[o]])
            near = []
            for i in {int(i) for a, b in pts[k][::3] for i in G.near(a, b, 300) if G.kind[i] in ("역", "교차로", "학교", "공원", "다리")}:
                d_own, d_other = float(np.hypot(*(mine - (G.x[i], G.y[i])).T).min()), float(np.hypot(*(other - (G.x[i], G.y[i])).T).min())
                if d_other - d_own >= 100:
                    near.append((d_own, G.name[i]))
            if not near:
                return None
            where = f"{min(near)[1]} 가까이"
        opts.append({"label": f"{where}의 {name}" if where else name, "set": {"clues": [dict(c, k=k, label=name, sure=True)], "drop": [c["k"]]}})
    return {"id": "alike", "bits": _bits(shares), "name": (c.get("label") or "").split(" · ")[0], "options": opts + [{"word": "잘 모르겠음", "set": {"clues": []}}]}


def _q_ago(R, clues):
    """자동차전용도로: 지나온 표지에서 얼마나 왔는지를 시간으로 묻는다(「○○를 지나고 얼마쯤 뒤였어요?」)."""
    if R["r"] < 300:
        return None
    for n in range(len(clues) - 1, -1, -1):
        c = clues[n]
        if c["t"] == "past" and not c.get("min") and c.get("how") != "바로" and R["ctx"]["pos"].get(n) and n not in R["ctx"]["ends"]:     # 끝이 둘인(방향 모르는) 터널은 시간으로 묻지 않는다
            pos = [round(v, 1) for v in R["ctx"]["pos"][n]]
            base = {k: v for k, v in c.items() if k not in ("how", "min", "sure")}
            opt = lambda word, **kw: {"word": word, "set": {"clues": [dict(base, anchor=pos, sure=True, **kw)]}}   # noqa: E731
            bits = min(2.0, math.log2(max(1.0, R["r"] / 820.0)))     # 시간 답은 거칠다: 1분쯤이면 ±500m(90%가 드는 폭 820m), 보기 넷이라 많아야 2비트
            return {"id": "ago", "bits": bits, "name": c.get("label") or "", "options": [opt("바로 지나서", how="금방"), opt("1분쯤", min=1), opt("2~3분", min=2.5), opt("5분쯤", min=5)]}
    return None


def _q_seen(R, x, y, w, clues):
    """보이는 것의 「종류」를 예 · 아니요로 묻는다(「근처에 육교가 보입니까?」). 답이 반반에 가깝게 갈리는 종류를 고른다."""
    asked = {c.get("c") for c in clues if c["t"] in ("cat", "nocat")}
    idx = _places_in(x.min() - 100, y.min() - 100, x.max() + 100, y.max() + 100, 3000)
    best = None
    for kind in SEEN_KINDS:
        k = [i for i in idx if G.kind[i] == kind and _road_ok(i, R)] if kind not in asked else []
        if not k or len(k) > 300:
            continue
        p = float(w[np.hypot(G.x[k][None, :] - x[:, None], G.y[k][None, :] - y[:, None]).min(1) <= 80].sum())
        if 0.15 < p < 0.85 and (best is None or abs(p - 0.5) < abs(best[1] - 0.5)):
            best = (kind, p)
    if not best:
        return None
    kind, p, e = best[0], best[1], 0.2                    # e = 지도에 없거나 시민이 못 봤을 몫
    q = p * (1 - e) + (1 - p) * e
    return {"id": "seen", "bits": max(_bits([q, 1 - q]) - _bits([e, 1 - e]), 0.0), "name": kind,
            "options": [{"word": "보임", "set": {"clues": [{"t": "cat", "c": kind, "e": e, "sure": True, "label": f"{kind} 보임"}]}},
                        {"word": "안 보임", "set": {"clues": [{"t": "nocat", "c": kind, "sure": True, "label": f"{kind} 안 보임"}]}}]}


def _q_either(R, x, y, w, clues):
    """남은 범위를 긴 쪽으로 반 갈라, 양쪽에서 눈에 띄는 표지를 하나씩 내밀어 고르게 한다(「○○ 쪽입니까, △△ 쪽입니까?」)."""
    (ux, uy), (mx, my) = _axis(x, y, w)
    t = (x - mx) * ux + (y - my) * uy
    order = np.argsort(t)
    cut = t[order][int(np.searchsorted(np.cumsum(w[order]), 0.5))]
    used = {c.get("label") for c in clues}
    sides = []
    for m in (t < cut, t >= cut):
        p = float(w[m].sum())
        if p < 0.2:
            return None
        cx, cy = float((x[m] * w[m]).sum() / p), float((y[m] * w[m]).sum() / p)
        rad = math.sqrt(float((w[m] * ((x[m] - cx) ** 2 + (y[m] - cy) ** 2)).sum() / p))
        cand = [int(i) for i in G.near(cx, cy, max(60.0, 0.8 * rad)) if len(G.name[i]) >= 3 and G.kind[i] not in ("동네", "산") and not gaz.GENERIC.match(G.name[i].replace(" ", "")) and _road_ok(int(i), R)
                and f"{G.name[i]} 쪽" not in used and f"{G.name[i]} 쪽 아님" not in used and not ("selfname" in ON and self_area(int(i)))
                and not ("rimask" in ON and G.name[i] == R.get("ringed"))]      # (rimask) 둘레로 읽은 곳 자체(「항동저수지 쪽」)는 보기가 아니다
        if not cand:
            return None
        i = max(cand, key=lambda i: PROM.get(G.kind[i], 1.0) / (1 + math.hypot(G.x[i] - cx, G.y[i] - cy) / 50))
        ko = max([j for j in cand if _ko(j)], key=lambda j: PROM.get(G.kind[j], 1.0) / (1 + math.hypot(G.x[j] - cx, G.y[j] - cy) / 50), default=None)      # (hangulopt2) 그쪽의 한글 이름(없으면 None)
        sides.append((p, cx, cy, rad, G.name[i], ko))
    (p1, x1, y1, r1, n1, k1), (p2, x2, y2, r2, n2, k2) = sides
    if n1 == n2 or math.hypot(x1 - x2, y1 - y2) < 60:
        return None
    if "hangulopt2" in ON and not (HANGUL.search(n1) and HANGUL.search(n2)) and k1 is not None and k2 is not None and G.name[k1] != G.name[k2]:
        n1, n2 = G.name[k1], G.name[k2]                   # (hangulopt2) 「○○ 쪽」의 단서는 그쪽 가운데라 이름표만 바꾼다(질문 · 단서 · 몫은 그대로). 어느 한쪽이라도 한글 이름이 없으면 원래 그대로
    half = lambda side: {"t": "half", "o": [round(mx, 1), round(my, 1)], "v": [round(ux, 4), round(uy, 4)], "cut": round(float(cut), 1), "side": side} if "half" in ON else {"t": "pt"}   # noqa: E731
    # (CALL_ON=half, 기본 끔) 고른 반을 고르게 보고 이 답 하나로는 끝내지 않는다(11-16 갈래 1). 300통 「네」 기욺의 틀린 확정이 7 → 8이라 넣는 기준에 못 미쳐 꺼 둠. 끄면 그 반의 가운데에 봉우리를 둔 원(pt)
    opt = lambda cx, cy, rad, name, side: {"label": f"{name} 쪽", "set": {"clues": [dict(half(side), p=[round(cx, 1), round(cy, 1)], r=round(max(25.0, 0.7 * rad), 1), sure=True, label=f"{name} 쪽")]}}   # noqa: E731  p · r는 그 반의 가운데 · 퍼짐(가상 시민도 씀)
    neither = [{"t": "not", "p": [round(cx, 1), round(cy, 1)], "r": round(max(60.0, 0.7 * rad), 1), "f": 0.4, "label": f"{name} 쪽 아님"}
               for cx, cy, rad, name in ((x1, y1, r1, n1), (x2, y2, r2, n2))] if "softnot" in ON else []      # 「둘 다 아니에요」도 단서: 두 쪽을 지우지 않고 0.4로 낮춘다(CALL_ON=softnot)
    return {"id": "either", "bits": _bits([p1, p2]) * 0.85, "options": [opt(x1, y1, r1, n1, -1), opt(x2, y2, r2, n2, 1), {"word": "둘 다 아님", "set": {"clues": neither}}]}


def _q_near(R, clues):
    """둘레에 더 물을 표지가 없을 때: 시민이 말한 표지 가운데 가장 가까운 것 하나에 「바로 앞」인지 묻는다."""
    best = None
    for c in clues:
        if c["t"] == "pt" and c.get("r", 100.0) > SIG["바로"] and c.get("label") and not c["label"].endswith(" 쪽"):
            if R.get("chainskip") and _big_named(c["label"], c["p"]):
                continue                                   # (chainpick · 89번) 체인 상표를 기준에서 뺀 뒤 남은 것이 넓은 곳(크기가 빠진 한 점 단서)이면 묻지 않는다 — 74-016: 한국체육대학교 「바로 앞」 → 캠퍼스의 한 점으로 좁혀 178m 틀린 확정
            px, py, ext = np.array([c["p"][0]]), np.array([c["p"][1]]), [{"ext": c["ext"]} if c.get("ext") else {}]
        elif c["t"] == "at" and c.get("how") != "바로" and "k" in c:
            r = resolve(c["k"])
            if not len(r["x"]) or r["areas"] or r["roads"] or any(k in KIND_SIG for k in r["kinds"]) or _pk(r):
                continue                                   # 역 · 동네처럼 넓은 것에는 「바로 앞」을 묻지 않는다
            if ("chainref" in ON or R.get("chainskip")) and _branches(r, R) >= 2:
                continue                                   # (chainref · 89번) 같은 상표가 범위 둘레에 여럿이면 그 가운데 한 지점을 두고 「바로 앞입니까」를 묻지 않는다
            px, py, ext = r["x"], r["y"], [_big(i) for i in r["ids"]]
        else:
            continue
        d = np.hypot(px - R["cx"], py - R["cy"])
        j = int(np.argmin(d))
        if d[j] <= R["r"] + 50 and (best is None or d[j] < best[0]):
            best = (float(d[j]), c.get("dist_of") or c.get("label") or G.display(c["k"]), [round(float(px[j]), 1), round(float(py[j]), 1)], ext[j])     # 거리 답(「○○에서 쉰 걸음쯤」)은 표지 이름으로(CALL_ON=dist): 아니면 같은 질문이 꼬리를 문다
    if not best:
        return None
    return {"id": "near", "bits": 1.0, "name": best[1], "options": [{"word": "바로 앞", "set": {"clues": [dict({"t": "pt", "p": best[2], "r": SIG["바로"], "name": best[1], "label": best[1] + " 바로 앞"}, **best[3])]}},
                                                                       {"word": "조금 떨어짐", "set": {"clues": []}}]}


def _q_dist(R, clues):
    """(CALL_ON=dist) 시민이 댄 표지에서 얼마나 떨어졌는지: 바로 앞 · 스무 걸음쯤 · 쉰 걸음쯤 · 멀리 보이기만(33번 2-2). 한 표지에 한 번."""
    if R["on_road"] or R["r"] > 250:
        return None
    if "distall" not in ON and not _area_at(G.parks, R["cx"], R["cy"]):
        return None                                       # 공원 안에서만(공원 밖에서는 「바로 앞에 뭐가 보이세요?」가 더 잘 들었다 — 잰 뒤 고친 것. 어디서나 묻는 판은 CALL_ON=dist,distall)
    anc = _said_anchor(R, clues)
    if not anc or any(c.get("dist_of") == anc[1] for c in clues):
        return None
    if "bigdist" in ON and anc[3] > BIG_M:
        return None                                       # (bigdist · 75번) 넓은 곳(수영장 · 학교 · 경기장)에는 「몇 걸음」을 묻지 않는다: 가운데 한 점에서 잰 걸음이 되어 「바로 앞」 답이 한가운데에 핀을 찍는다(뚝섬수영장 100m 틀린 확정)
    p = anc[2]
    mk = lambda word, steps, side, **kw: {"label": word, "set": {"clues": [dict({"t": "pt", "p": p, "dist_of": anc[1], "sure": True, "name": anc[1], "label": f"{anc[1]}에서 {word}"}, **kw)],   # noqa: E731
                                                                     "matter": {"side": side, "steps": steps, "steps_of": anc[1]}}}
    return {"id": "dist", "bits": 1.0, "name": anc[1], "options": [mk("바로 앞", None, "앞", r=10.0), mk("스무 걸음쯤", "스무", "근처", ring=15.0, r=8.0),
                                                                   mk("쉰 걸음쯤", "쉰", "근처", ring=40.0, r=15.0), mk("멀리 보이기만", "멀리", "근처", ring=120.0, r=50.0)]}


def _q_closest(R, x, y, w, clues):
    """(CALL_ON=closest) 넓은 공원 안: 범위 안의 눈에 띄는 큰 것 넷을 내밀고 「어디가 가장 가까우세요?」(33번 2-4). 한 통화에 한 번."""
    ringed = R.get("ringed") if "rimask" in ON else None
    if sum(1 for c in clues if c["t"] == "closest") >= (2 if "closest2" in ON or ringed else 1):
        return None                                       # (closest2, 기본 끔 · 49번) 좁혀진 범위에서 한 번 더(더 작은 것들로)
    old = ({tuple(c["p"]) for c in clues if "p" in c and (c["t"] == "closest" or (c["t"] == "not" and str(c.get("label", "")).endswith(" 쪽 아님")))}
           | {tuple(q) for c in clues if c["t"] == "closest" for q in c.get("others", ())}) if "closestnew" in ON else ()      # (closestnew · 75번) 앞서 내밀었던 보기(고른 것 · 「다 멀어요」로 지운 것)는 다시 내밀지 않는다: 같은 넷을 또 물으면 같은 답이 온다. 새 보기가 셋이 안 되면 묻지 않는다
    picked, parts = _candidates(x, y, w, max(60.0, 0.3 * R["r"]) if ringed else max(100.0, 0.35 * R["r"]), gaz.ROADSIDE if _on_express(R) else None, old)
    keep = []
    for i in picked:
        if all(math.hypot(G.x[i] - G.x[j], G.y[i] - G.y[j]) > 0.5 * R["r"] for j in keep):
            keep.append(i)
        if len(keep) == 4:
            break
    if len(keep) < 3:
        return None
    pts = [[round(float(G.x[i]), 1), round(float(G.y[i]), 1)] for i in keep]
    vx = np.array([[math.hypot(a - p[0], b - p[1]) for p in pts] for a, b in zip(x, y)])
    shares = [float(w[vx.argmin(1) == k].sum()) for k in range(len(pts))]      # 질문 고르기는 원래 후보로
    if "hangulopt2" in ON and not all(_ko(i) for i in keep):
        alt = []
        for i in _candidates(x, y, w, max(60.0, 0.3 * R["r"]) if ringed else max(100.0, 0.35 * R["r"]), gaz.ROADSIDE if _on_express(R) else None, old, ko=True)[0]:
            if all(math.hypot(G.x[i] - G.x[j], G.y[i] - G.y[j]) > 0.5 * R["r"] for j in alt):
                alt.append(i)
        keep = _ko_swap(keep, alt)
        pts = [[round(float(G.x[i]), 1), round(float(G.y[i]), 1)] for i in keep]
    s = 1.5 * R["r"]
    opts = [{"label": G.name[i], "set": {"clues": [{"t": "closest", "p": p, "others": [q for q in pts if q is not p], "s": round(s, 1), "sure": True, "label": f"{G.name[i]}이 가장 가까움"}]}} for i, p in zip(keep, pts)]
    far = [{"t": "not", "p": p, "r": 100.0, "f": 0.5, "label": f"{G.name[i]} 쪽 아님"} for i, p in zip(keep, pts)]
    return {"id": "closest", "bits": _bits(shares) * 0.8, "name": ", ".join(G.name[i] for i in keep), "options": opts + [{"label": "다 멀어요", "set": {"clues": far}}], **({"area": ringed} if ringed else {})}


def _branches(r, R):
    """(chainref · 89번) resolve() 결과 가운데 지금 범위 둘레(덮는 반지름 + 100m)에 있는 서로 40m 넘게 떨어진 자리 수."""
    near = np.hypot(r["x"] - R["cx"], r["y"] - R["cy"]) <= R["r_cover"] + 100
    keep = []
    for x, y in zip(r["x"][near], r["y"][near]):
        if all(math.hypot(x - a, y - b) > 40 for a, b in keep):
            keep.append((x, y))
    return len(keep)


def _big_named(label, p):
    """(chainpick · 89번) 그 이름의 장소가 p 둘레 1km 안에서 넓은 곳(크기가 BIG_M보다 큼)인가."""
    r = resolve(gaz.norm(label))
    return any(float(G.ext[i]) > BIG_M and math.hypot(G.x[i] - p[0], G.y[i] - p[1]) <= 1000 for i in r.get("ids") or [])


def _landmark(x, y, brand):
    """(chainpick · 89번) 그 지점 둘레 60m 안의 하나뿐인 표지 이름(역 출구 · 건물 등, 같은 상표는 뺌) 또는 None."""
    b = gaz.norm(brand)
    idx = [int(i) for i in G.near(x, y, 60) if len(G.name[i]) >= 3 and not gaz.GENERIC.match(G.name[i].replace(" ", "")) and G.kind[i] not in ("동네", "산")
           and b not in gaz.norm(G.name[i]) and len(resolve(gaz.norm(G.name[i]))["x"]) == 1]
    return G.name[min(idx, key=lambda i: math.hypot(G.x[i] - x, G.y[i] - y) / (3.0 if G.kind[i] == "역 출구" else PROM.get(G.kind[i], 1.0)))] if idx else None      # 역 출구를 먼저(시민이 흔히 출구로 말한다)


def _chain_q(R, clues, name):
    """(chainpick · 89번) name이 시민이 댄 상표이고 범위 둘레(덮는 반지름 + 100m)에 40m 넘게 떨어진 지점이 둘 이상이면, 가운데에 가까운 지점 넷까지를 보기로 「어느 ○○가 가장 가까우세요?」. 아니면 None.
    고른 지점은 「그 지점이 다른 지점보다 가깝다」(가장 가까운 곳 단서)와, 시민이 그 상표를 말한 넓이 그대로의 한 점 단서가 되어 다음 거리 · 방향 · 「바로 앞입니까」의 기준이 된다."""
    c = next((c for c in clues if c["t"] == "at" and "k" in c and "|" not in str(c["k"]) and (c.get("dist_of") or c.get("label") or G.display(c["k"])) == name), None)
    if c is None:
        return None
    r = resolve(c["k"])
    if not len(r["x"]) or not r.get("ids"):
        return None
    d = np.hypot(r["x"] - R["cx"], r["y"] - R["cy"])
    keep = []
    for j in np.argsort(d):
        if d[j] > R["r_cover"] + 100 or len(keep) == 4:
            break
        if all(math.hypot(r["x"][j] - r["x"][k], r["y"][j] - r["y"][k]) > 40 for k in keep):
            keep.append(int(j))
    if len(keep) < 2:
        return None
    ids = [r["ids"][j] for j in keep]
    labs = []
    for j, i in zip(keep, ids):
        lab = G.name[i]
        if [G.name[k] for k in ids].count(lab) > 1 or gaz.norm(lab) == gaz.norm(name):
            lm = _landmark(float(r["x"][j]), float(r["y"][j]), G.brand[i] or G.name[i])
            lab = f"{lm} 옆 {G.name[i]}" if lm else None
        labs.append(lab)
    if None in labs or len(set(labs)) < len(labs):
        return None                                       # 지점을 말로 가를 수 없으면 묻지 않고 main처럼 둔다(74-016: 따릉이 세 곳의 이름이 모두 「한국체육대학교」, 가장 가까운 곳 둘레에 가를 표지 없음)
    pts = [[round(float(r["x"][j]), 1), round(float(r["y"][j]), 1)] for j in keep]
    sig = min(_sigma(c, r["kinds"]), SIG["근처"])
    return {"id": "closest", "chain": True, "bits": None, "name": name, "options": [
        {"label": lab, "set": {"matter": {"chain": lab}, "clues": [{"t": "closest", "p": p, "others": [q for q in pts if q is not p], "s": round(1.5 * R["r"], 1), "sure": True, "label": f"{lab}이 가장 가까움"},
                                                                  {"t": "pt", "p": p, "r": sig, "sure": True, "name": lab, "label": lab}]}}
        for p, lab in zip(pts, labs)] + [{"word": "잘 모르겠음", "set": {"clues": []}}]}


def _said_anchor(R, clues):
    """시민이 말한 표지 가운데 지금 범위의 가운데에 가장 가까운 것 → (거리, 이름, [x, y]) 또는 None. 역 · 동네처럼 넓은 것은 뺀다."""
    best = None
    for c in clues:
        if c["t"] == "pt" and c.get("label") and not c["label"].endswith(" 쪽") and "→" not in c["label"]:
            px, py, ext = np.array([c["p"][0]]), np.array([c["p"][1]]), np.array([float(c.get("ext") or 0.0)])
        elif c["t"] == "at" and "k" in c:
            r = resolve(c["k"])
            if not len(r["x"]) or r["areas"] or r["roads"] or any(k in KIND_SIG for k in r["kinds"]) or _pk(r):
                continue
            if ("chainref" in ON or R.get("chainskip")) and _branches(r, R) >= 2:
                continue                                  # (chainref · 89번) 같은 상표가 지금 범위 둘레에 여럿: 어느 지점인지 모르니 거리 · 방향 질문의 기준으로 잡지 않는다(왕십리역 r27: 역사 3층 스타벅스를 기준으로 「바로 앞」 → 226m 떨어진 곳으로 확인 질문)
            px, py, ext = r["x"], r["y"], (G.ext[r["ids"]] if r.get("ids") else np.zeros(len(r["x"])))
        else:
            continue
        d = np.hypot(px - R["cx"], py - R["cy"])
        j = int(np.argmin(d))
        if d[j] <= R["r"] + 50 and (best is None or d[j] < best[0]):
            best = (float(d[j]), c.get("dist_of") or c.get("label") or G.display(c["k"]), [round(float(px[j]), 1), round(float(py[j]), 1)], float(ext[j]))      # 넷째 = 그 표지의 크기(넓은 곳이면 0보다 큼)     # 거리 답(「○○에서 쉰 걸음쯤」)은 표지 이름으로(CALL_ON=dist): 아니면 같은 질문이 꼬리를 문다
    return best


def _q_from(R, x, y, w, clues):
    """시민이 댄 표지에서 어느 쪽인지 묻는다(「○○에서 보면 어느 쪽이세요? A 쪽, B 쪽」). 보기는 그 표지에서 25~150m, 서로 70도 넘게 다른 쪽의 이름들."""
    anc = _said_anchor(R, clues)
    if not anc or anc[0] > 80:
        return None
    ax, ay = anc[2]
    used = {c.get("label") for c in clues}
    cand, wide = [], "fromwide" in ON
    BIGK = ("체육시설", "문화시설", "볼거리", "역", "다리", "주차장")
    for i in G.near(ax, ay, 400 if wide else 150):          # fromwide: 25~400m의 큰 것까지(공원 안은 150m 안에 이름이 한두 개뿐, 33번 2-3)
        i = int(i)
        d = math.hypot(G.x[i] - ax, G.y[i] - ay)
        if 25 <= d <= (400 if wide else 150) and len(G.name[i]) >= 3 and G.name[i] != anc[1] and G.kind[i] not in ("동네", "산") and not gaz.GENERIC.match(G.name[i].replace(" ", "")) and G.name[i] not in used and _road_ok(int(i), R) and not ("selfname" in ON and self_area(i)):
            score = PROM.get(G.kind[i], 1.0) * (1.5 if G.kind[i] in BIGK else 1.0) / (1 + d / 150) if wide else PROM.get(G.kind[i], 1.0) / (1 + d / 60)
            cand.append((score, i, d))
    extra = []
    pk = _area_at(G.parks, ax, ay) if wide else None
    if pk:                                                # 공원 안이면 이름 없는 보기 둘: 공원 바깥 쪽(가장 가까운 경계) · 공원 한가운데 쪽
        ring = next(a["ring"] for a in G.parks if a["name"] == pk)
        j = int(np.argmin(np.hypot(ring[:, 0] - ax, ring[:, 1] - ay)))
        for (tx, ty), lab in (((ring[j, 0], ring[j, 1]), "공원 바깥 쪽"), ((float(ring[:, 0].mean()), float(ring[:, 1].mean())), "공원 한가운데 쪽")):
            dd = math.hypot(tx - ax, ty - ay)
            if dd >= 25:
                extra.append((lab, ((tx - ax) / dd, (ty - ay) / dd), dd))
    def choose(ok):
        picked = []
        for _, i, d in sorted(cand, reverse=True):
            u = ((G.x[i] - ax) / d, (G.y[i] - ay) / d)
            if ok(i) and all(u[0] * v[0] + u[1] * v[1] < (0.5 if wide else 0.34) for _, v, _ in picked + [(None, e[1], None) for e in extra]):       # 서로 70도(fromwide 60도) 넘게 다른 쪽
                picked.append((i, u, d))
            if len(picked) + len(extra) >= (4 if wide else 3):
                break
        return picked
    picked = choose(lambda i: True)
    if len(picked) + len(extra) < 2:
        return None
    vx, vy = x - ax, y - ay
    vn = np.hypot(vx, vy) + 1e-9
    dirs = [(G.name[i], u, d) for i, u, d in picked] + extra
    parts = [float(w[((vx * u[0] + vy * u[1]) / vn >= 0.5) & (vn >= 10)].sum()) for _, u, _ in dirs]
    parts.append(max(0.0, 1 - sum(parts)))               # 질문 고르기는 원래 후보로
    if "hangulopt2" in ON and not all(_ko(i) for i, _, _ in picked):
        alt = choose(_ko)                                 # (hangulopt2) 한글 이름만으로 같은 규칙대로 다시 고른 것에서 모자란 만큼만
        at = {i: (i, u, d) for i, u, d in alt + picked}
        dirs = [(G.name[i], at[i][1], at[i][2]) for i in _ko_swap([i for i, _, _ in picked], [i for i, _, _ in alt])] + extra
    opts = []
    for name, u, d in dirs:
        dd = min(max(0.5 * d, 20.0), 45.0)
        lab = f"{name}" if name in ("공원 바깥 쪽", "공원 한가운데 쪽") else f"{name} 쪽"
        clue = ({"t": "cone", "o": [round(ax, 1), round(ay, 1)], "v": [round(u[0], 3), round(u[1], 3)], "sure": True, "label": f"{anc[1]} → {lab}"} if (wide or "fromcone" in ON) and "dist" in ON     # (fromcone, 기본 끔 · 47번) 「쪽」은 방향이지 거리가 아니다: 표지에서 20~45m 한 점 대신 부채꼴로(1118 #58)
                else {"t": "pt", "p": [round(ax + u[0] * dd, 1), round(ay + u[1] * dd, 1)], "r": 22.0, "sure": True, "label": f"{anc[1]} → {lab}"})
        opts.append({"label": lab, "set": {"clues": [clue], "dir": {"o": [ax, ay], "v": [round(u[0], 3), round(u[1], 3)]}, "matter": {"toward": lab.removesuffix(" 쪽")} if wide else {}}})
    return {"id": "from", "bits": _bits(parts) * 0.75, "name": anc[1], "options": opts + [{"word": "잘 모르겠음", "set": {"clues": []}}]}


def _q_dir(R, x, y, w):
    (ux, uy), (mx, my) = _axis(x, y, w)
    if abs(ux) >= abs(uy):
        first, labels = ((ux, uy) if ux > 0 else (-ux, -uy)), ("동쪽으로 가는 방향", "서쪽으로 가는 방향")
    else:
        first, labels = ((ux, uy) if uy > 0 else (-ux, -uy)), ("북쪽으로 가는 방향", "남쪽으로 가는 방향")
    named = DIR_NAMES.get(next((G.roads[i]["name"] for i in R["ctx"]["roads"] if G.roads[i]["name"] in DIR_NAMES), None))
    if named:
        labels = named
    elif "drive" in ON and R["ctx"]["rxy"] is not None:   # 큰길: 길 양쪽에서 가장 먼 역 · 큰 교차로 이름으로(「동쪽으로 가는 방향」보다 답하기 쉽다, 33번 5-2)
        idx = [i for i in _places_in(mx - 2000, my - 2000, mx + 2000, my + 2000, 6000) if G.kind[i] in ("역", "교차로") and 3 <= len(G.name[i]) <= 12]
        rxy = R["ctx"]["rxy"]
        idx = [i for i in idx if np.hypot(rxy[::3, 0] - G.x[i], rxy[::3, 1] - G.y[i]).min() <= 80]
        if idx:
            tt = {i: (G.x[i] - mx) * first[0] + (G.y[i] - my) * first[1] for i in idx}
            a, b = max(idx, key=tt.get), min(idx, key=tt.get)
            if tt[a] > 300 and tt[b] < -300 and G.name[a] != G.name[b]:
                labels = (f"{G.name[a]} 쪽", f"{G.name[b]} 쪽")
    opt = lambda v, lab: {"label": lab, "set": {"clues": [{"t": "head", "v": [round(v[0], 3), round(v[1], 3)], "label": lab}]}}   # noqa: E731
    return {"id": "dir", "bits": 1.0, "options": [opt(first, labels[0]), opt((-first[0], -first[1]), labels[1])]}


def _q_next(R, x, y, w, clues):
    """자동차전용도로, 가는 방향을 알 때: 남은 구간 안의 표지 하나(다리 · 나들목 · 터널 · 육교)를 「지났나, 아직인가」로 묻는다.
    가능성을 반에 가깝게 가르는 것을 고른다. 「○○ 조금 지나서」만으로는 구간이 300~500m에서 멈춰서 넣음(11-14 밤)."""
    h, rxy = R["ctx"]["head"], R["ctx"]["rxy"]
    if h is None or rxy is None or R["r"] <= DONE_ROAD_M:
        return None
    said = {gaz.norm(c.get("label") or "") for c in clues}
    best = None
    for i in _places_in(x.min() - 60, y.min() - 60, x.max() + 60, y.max() + 60, 8000):
        nm = G.name[i]
        ramp = "nextramp" in ON and G.kind[i] == "진출입로" and getattr(G, "rp0", 0) <= i < getattr(G, "rp1", 0) and not (     # (nextramp, 기본 끔 · 49번) 같은 방향의 나가는 길 · 들어오는 길도 가르는 표지로(표지판으로 보인다)
            "ramp2" in ON and sum(1 for c in clues if c.get("flat") and ("나가는 길" in (c.get("label") or "") or "들어오는 길" in (c.get("label") or ""))) >= 2)     # (ramp2) 진출입로로 묻는 것은 한 통화 두 번까지
        if ramp and float(G.rhead[i - G.rp0] @ np.asarray(h)) < 0.5:
            continue                                      # 맞은편 차로의 나가는 길은 보이지 않는다
        if not ramp and (G.kind[i] not in (("다리", "나들목", "터널", "육교") + (("교차로", "역", "역 출구", "정류장", "주유소") if "drive" in ON else ())) or not 3 <= len(nm) <= 16) or gaz.norm(nm) in said or gaz.GENERIC.match(nm.replace(" ", "")):
            continue
        same = resolve(gaz.norm(nm))
        if not ramp and int((np.hypot(same["x"] - G.x[i], same["y"] - G.y[i]) < 1500).sum()) > 1:
            continue                                      # 같은 이름이 둘레에 여럿(분기점의 갈래 · 긴 터널): 어느 것을 지났는지 묻기 어렵다(진출입로는 방향으로 이미 갈랐다)
        dr = np.hypot(rxy[:, 0] - G.x[i], rxy[:, 1] - G.y[i])
        if dr.min() > 60:
            continue                                      # 본선 위(차로 지나며 보는 것)만
        px, py = rxy[int(dr.argmin())]
        p = float(w[(x - px) * h[0] + (y - py) * h[1] > 0].sum())
        if best is None or abs(p - 0.5) < abs(best[0] - 0.5):
            best = (p, nm, [round(float(px), 1), round(float(py), 1)], ramp)
    if not best or not 0.15 < best[0] < 0.85:
        return None
    p, nm, pt, ramp = best
    express = any(_xw(i) for i in R["ctx"]["roads"])
    e = {} if express and not (ramp and "rampsoft" in ON) else {"e": 0.15}     # (rampsoft, 기본 끔 · 49번) 나가는 길을 지났는지는 다리만큼 또렷하지 않다: 틀리게 말할 몫을 큰길과 같게                    # 큰길에서는 지났는지 · 아직인지를 틀리게 말할 몫을 크게(33번 5-2)
    return {"id": "next", "bits": _bits([p, 1 - p]), "name": nm,
            "options": [{"label": f"{nm} 지났음", "set": {"clues": [dict({"t": "past", "p": pt, "flat": True, "label": nm}, **e)]}},
                        {"label": f"{nm} 아직", "set": {"clues": [dict({"t": "before", "p": pt, "flat": True, "label": nm}, **e)]}}]}


def _q_between(R, x, y, w, clues):
    """길 위: 다리 · 나들목 같은 큰 표지 두 개 사이로 가른다."""
    if any(c["t"] == "between" for c in clues) or R["r"] < 400:
        return None
    express = any(_xw(i) for i in R["ctx"]["roads"])
    kinds = ("다리", "나들목", "터널") if express else ("다리", "교차로", "역", "역 출구", "정류장", "육교", "터널", "주유소")          # 큰길을 차로 지나간 통화: 교차로 · 역 출구 · 정류장 · 주유소까지(33번 5-2)
    idx = [i for i in _places_in(x.min() - 100, y.min() - 100, x.max() + 100, y.max() + 100, 40000) if G.kind[i] in kinds]
    if len(idx) < 2:
        return None
    big = [i for i in idx if "대교" in G.name[i]]
    idx = big if len(big) >= 3 else idx                    # 긴 구간이면 큰 다리(대교)만으로 가른다
    (ux, uy), (mx, my) = _axis(x, y, w)
    rxy, marks = R["ctx"]["rxy"], []
    for i in sorted((int(i) for i in idx), key=lambda i: G.kind[i] != "다리"):      # 다리 이름을 먼저(같은 자리의 나들목은 뺀다)
        px, py = G.x[i], G.y[i]
        dr = np.hypot(rxy[:, 0] - px, rxy[:, 1] - py)
        if dr.min() > (700 if G.kind[i] == "다리" else 80):
            continue
        px, py = rxy[int(np.argmin(dr))]                    # 다리 가운데가 아니라 다리가 길과 만나는 곳
        t = (px - mx) * ux + (py - my) * uy
        m = re.search(r"[가-힣0-9]+대교", G.name[i])
        base = m.group() if m else G.name[i].replace("분기점", "").replace("북단", "").replace("남단", "").replace("교차로", "").strip()
        if not base or any(abs(t - m["t"]) < 350 or m["name"] == base for m in marks):
            continue
        marks.append({"t": float(t), "name": base, "p": [round(float(px), 1), round(float(py), 1)]})
    marks.sort(key=lambda m: m["t"])
    if len(marks) < 2:
        return None
    tt = (x - mx) * ux + (y - my) * uy
    cuts = [m["t"] for m in marks]
    parts = [float(w[(tt >= a) & (tt < b)].sum()) for a, b in zip([-1e9] + cuts, cuts + [1e9])]
    opts = [(m, {"label": f"{a['name']} ~ {b['name']}", "set": {"clues": [{"t": "between", "p": [a["p"], b["p"]], "label": f"{a['name']} ~ {b['name']} 사이"}]}})
            for a, b, m in zip(marks, marks[1:], parts[1:-1]) if m > 0.02]
    keep = sorted(sorted(range(len(opts)), key=lambda j: -opts[j][0])[:10])       # 단추는 가능성이 큰 구간 열 개까지(길의 순서대로)
    return {"id": "between", "bits": _bits(parts) * 0.85, "options": [opts[j][1] for j in keep]} if len(opts) >= 2 else None


def _q_marks(R, x, y, w, qid, clues):
    """가까이 보이는 표지(간판 · 건물 · 시설)를 묻는다. 길 위면 차에서 볼 만한 것을, 이미 좁혀졌으면 더 바짝."""
    radius = 35.0 if qid == "finer" else 600.0 if qid == "station" else 100.0
    used = {tuple(c["p"]) for c in clues if c["t"] in ("pt", "past") and "p" in c and not isinstance(c["p"][0], list)}
    if "closestnew" in ON:                                # (closestnew · 75번) 「다 멀어요」 · 「둘 다 아니에요」로 지운 곳을 「바로 앞에 뭐가 보이세요? ○○ 같은 거요」로 다시 내밀지 않는다
        used |= {tuple(c["p"]) for c in clues if c["t"] == "not" and "p" in c and str(c.get("label", "")).endswith(" 쪽 아님")}
    passed_kinds = gaz.ROADSIDE | ({"정류장", "역 출구"} if "drive" in ON and R["on_road"] and not any(_xw(i) for i in R["ctx"]["roads"]) else set())
    road = gaz.ROADSIDE if _on_express(R) else None          # 자동차전용도로 위: 길에서 보이는 종류만(_road_ok와 같은 규칙)
    picked, parts = _candidates(x, y, w, radius, passed_kinds if qid == "passed" else {"역"} if qid == "station" else road)
    if qid == "passed" and len(picked) < 2:
        picked, parts = _candidates(x, y, w, radius, road)
    keep = [n for n, i in enumerate(picked) if (round(float(G.x[i]), 1), round(float(G.y[i]), 1)) not in used]
    show = [picked[n] for n in keep]
    if "hangulopt2" in ON and not all(_ko(i) for i in show):
        alt = _candidates(x, y, w, radius, passed_kinds if qid == "passed" else {"역"} if qid == "station" else road, ko=True)[0]
        show = _ko_swap(show, [i for i in alt if (round(float(G.x[i]), 1), round(float(G.y[i]), 1)) not in used])
    open_q = qid in ("mark", "station") and not (road and not keep)     # 보기가 없어도 묻는 열린 질문(이름을 대면 지명 표에서 찾는다). 자동차전용도로 위에서 길에서 보이는 보기가 없으면 「가게 간판」은 묻지 않는다
    if (not keep and not open_q) or (len(keep) < 2 and qid == "passed"):
        return None
    opts = []
    for i in show:                                        # 보기로 내미는 곳(hangulopt2를 끄면 원래 keep 그대로)
        p = [round(float(G.x[i]), 1), round(float(G.y[i]), 1)]
        clue = {"t": "past", "p": p, "how": "바로", "label": G.name[i]} if qid == "passed" else {"t": "pt", "p": p, "r": SIG["바로"] if qid == "finer" else 300.0 if qid == "station" else SIG["근처"], "label": G.name[i]}
        clue.update(_big(i) if qid != "passed" else {})      # (bigplace) 보기로 내민 넓은 장소의 크기
        opts.append({"label": G.name[i], "kind": G.kind[i], "set": {"clues": [clue]}})
    bits = _bits(parts) * 0.75 if keep else 0.0           # 시민이 그 표지를 못 봤을 몫(4분의 1)을 뺀다
    if open_q:                                            # 이름 하나를 대면 그 둘레(90%가 드는 반지름)까지 준다고 보고 어림한다
        after = 2.1 * (300.0 if qid == "station" else SIG["근처"])
        bits = max(bits, 0.75 * math.log2(max(1.0, (R["r"] / after) ** 2)))
    return {"id": qid, "bits": bits, "options": opts}


# ---- 자리를 말로 · 넘길 곳
def _area_at(areas, x, y):
    px, py = np.array([x]), np.array([y])
    return next((g["name"] for g in areas if g["box"][0] <= x <= g["box"][2] and g["box"][1] <= y <= g["box"][3] and in_ring(px, py, g["ring"])[0]), None)


_express = None


def place_class(R):
    """넘길 곳을 가르는 장소 종류 → (자동차전용도로 | 한강공원 | 시 공원 | 공원 | 다리 | 길, 그 이름)."""
    global _express
    x, y = R["cx"], R["cy"]
    if R["on_road"]:
        name = next((G.roads[i]["name"] for i in R["ctx"]["roads"] if _xw(i)), None)
        if name:
            return "자동차전용도로", name
    if _express is None:
        _express = [(r["name"], road_keys(i)) for i, r in enumerate(G.roads) if _xw(i)]
    key = int(pack(round(x / STEP), round(y / STEP)))
    for name, ks in _express:
        j = int(np.searchsorted(ks, key))
        if j < len(ks) and ks[j] == key:
            return "자동차전용도로", name
    park = _area_at(G.parks, x, y)
    if park:
        return ("한강공원" if "한강" in park else "시 공원" if any(park.startswith(n) for n in CITY_PARKS) else "공원"), park
    G.add_bridges()
    for i in (i for i in G.bridge if G.name[i] in CITY_BRIDGES):
        if bridge_dist(i, np.array([x]), np.array([y]))[0] == 0:
            return "다리", G.name[i]      # 공원 안(다리 밑 한강공원)은 위에서 공원으로 — 위 · 밑을 가를 수 없어 공원이 먼저
    return "길", None


def describe(R, clues):
    """위치를 사람이 읽는 말로 엮을 재료(낱말은 문구 파일에서 서버가 붙인다)."""
    x, y, ctx = R["cx"], R["cy"], R["ctx"]
    size = size_of(R)
    p = {"m": size["m"], "kind": size["kind"], "center": gaz.lonlat(x, y), "gu": _area_at(G.gu, x, y), "dong": _area_at(G.dong, x, y), "park": _area_at(G.parks, x, y)}
    if "region" in ON and not R["on_road"] and not is_done(R) and R["r_cover"] > 150:
        p["region"] = _region(R)                          # 범위째로 물을 때 원 대신 이름 붙은 구역 전체(33번 1-2). 150m 안으로 모인 범위는 구역보다 원이 더 알려 준다(설계와 다르게 한 곳)
    if R["on_road"]:
        name = G.roads[min(ctx["roads"], key=lambda i: float(np.hypot(*(G.road_xy(i)[::3] - (x, y)).T).min()))]["name"]     # 길이 여럿(소리가 같은 두 길)이면 가운데에 가까운 길
        if R.get("alike"):
            name = " · ".join(dict.fromkeys(G.roads[i]["name"] for i in ctx["roads"]))      # 소리가 같은 길이 아직 안 갈렸으면 모두(11-16)
        p["road"] = name
        if ctx["head"]:
            lab = next((c["label"] for c in reversed(clues) if c["t"] == "head" and c.get("label")), None)
            if not lab:
                h = ctx["head"]
                lab = DIR_NAMES.get(name, ("동 · 북쪽으로 가는 방향", "서 · 남쪽으로 가는 방향"))[0 if (h[0] > 0 if abs(h[0]) >= abs(h[1]) else h[1] > 0) else 1]
            p["dir"] = lab
    # 가장 가까운 표지: 통화에서 나온 곳이 가까우면 그것, 아니면 눈에 띄는 가까운 곳
    said = [(c.get("dist_of") or c["label"], c["p"]) for c in clues if c["t"] in ("pt", "past") and "p" in c and c.get("label") and not c["label"].endswith(" 쪽")]
    for n, c in enumerate(clues):
        if c["t"] in ("at", "past", "before") and "k" in c:
            r = resolve(c["k"])
            if 0 < len(r["x"]) <= 40:
                j = int(np.argmin(np.hypot(r["x"] - x, r["y"] - y)))
                said.append((c.get("label") or G.display(c["k"]), _pos_near(ctx, n, x, y) or (float(r["x"][j]), float(r["y"][j]))))
    best = min(((math.hypot(q[0] - x, q[1] - y), lab) for lab, q in said), default=(1e9, None))
    p["near_said"] = best[0] <= 150                       # 가까운 표지가 통화에서 나온 이름인가(둘레 되묻기 문구를 고를 때 쓴다)
    if best[1] and "handsaid" in ON:
        p["said_best"], p["said_best_m"] = best[1], int(round(best[0], -1))      # (handsaid · 89번) 시민이 말한 이름 가운데 가장 가까운 것(멀어도)
    if best[0] > 150:
        idx = [i for i in G.near(x, y, 150) if not gaz.GENERIC.match(G.name[i].replace(" ", "")) and G.kind[i] not in ("동네", "산") and _road_ok(i, R) and not ("selfname" in ON and self_area(int(i)))]
        if idx:
            j = min(idx, key=lambda i: math.hypot(G.x[i] - x, G.y[i] - y) / PROM.get(G.kind[i], 1.0))
            best = (math.hypot(G.x[j] - x, G.y[j] - y), G.name[j])
    if best[1] and best[1] not in (p.get("park"), p.get("road"), p.get("dong"), p.get("gu")):      # 「○○공원 안, ○○공원에서 60m」처럼 같은 이름을 두 번 말하지 않는다
        p["near"], p["near_m"] = best[1], int(round(best[0], -1))
    if "rimline" in ON and R.get("ringed") and not R["on_road"] and not is_done(R):
        p["rim"] = {"name": R["ringed"], "side": _rim_side(R)}      # (rimline · 75번) 둘레로 읽은 곳: 「○○ 앞」(한 점)이 아니라 「○○ 서쪽 둘레」로 말한다
    if R["on_road"]:                                       # 길 위: 지나온 큰 표지에서 얼마나 왔나
        refs = [(pos, c.get("label") or G.display(c["k"])) for n, c in enumerate(clues) if c["t"] == "past" and (pos := _pos_near(ctx, n, x, y))]
        refs += [(pos[0], (c.get("label") or "").split(" ~ ")[0]) for n, c in enumerate(clues) if c["t"] == "between" and (pos := ctx["pos"].get(n)) and pos[0]]
        far = max(((math.hypot(q[0] - x, q[1] - y), lab) for q, lab in refs if lab), default=None)
        if far and far[0] > 150 and far[1] != p.get("near"):
            p["from"], p["from_m"] = far[1], int(round(far[0], -1))
    return p


def _rim_side(R):
    """(rimline) 둘레로 읽은 곳의 가운데에서 볼 때 지금 범위가 놓인 쪽(동 · 서 · 남 · 북). 범위의 85%가 그쪽 좌우 60도 안에 들 때만 — 갈리면 None(틀린 쪽을 되묻지 않게)."""
    r = resolve(R["ring_k"])
    boxes = [a["box"] for a in _parks_of(R["ring_k"])] or ([(r["x"].min(), r["y"].min(), r["x"].max(), r["y"].max())] if len(r["x"]) else [])
    if not boxes:
        return None
    ox, oy = min(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes)[:2] if len(boxes) == 1 else min((((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes), key=lambda o: math.hypot(o[0] - R["cx"], o[1] - R["cy"]))
    x, y, w = _sample(R)
    a = np.degrees(np.arctan2(x - ox, y - oy))            # 북 0도, 동 90도
    for word, mid in (("북", 0), ("동", 90), ("남", 180), ("서", -90)):      # 보일 말(「서쪽」)은 문구 파일에서 서버가 붙인다
        if float(w[np.abs((a - mid + 180) % 360 - 180) <= 60].sum()) >= 0.85:
            return word
    return None


STOP_SAID = re.compile(r"정류장|정류소|버스\s*(타는|서는)\s*(곳|데)")
STOP_INST = re.compile(r"(시청|구청|군청|도청|청사|병원|의료원|대학교|대학|시립대|성당|교회|사찰|세무서|경찰서|소방서|우체국|법원|검찰청|도서관|박물관|미술관|기념관|문화회관|구민회관|대사관)$")      # 정류장이 이름을 빌린 건물 · 기관(끝말)
STOP_NOT = re.compile(r"아파트|빌라|오피스텔|맨션|타운|사거리|삼거리|오거리|입구|앞$|역$|출구|정류장|[.·,(]")      # 정류장 이름으로만 쓰이는 꼴(「래미안아파트파이낸셜뉴스」 · 「○○병원앞」)


def stop_only(c, said):
    """(stoponly, 기본 끔 · 85번) 「서울시청 바로 앞이에요」: 그 이름이 지명 표에 같은 이름의 버스 정류장 점으로만 있으면,
    시민이 「정류장」이라고 하지 않았는데 그 점을 「바로 앞」의 좁은 폭으로 읽어 곧바로 39m 되묻기가 나갔다(정류장은 실제 건물에서 수백 m — 서울시청 약 230m · 명동성당 약 190m).
    ⓐ 「근처」의 넓은 폭으로 읽어 눈앞의 것을 하나 더 받게 하고 ⓑ 이름표 · 되묻기에 「○○ 버스 정류장」으로 정류장임을 밝힌다(시민이 「아니요」라고 할 수 있게).
    시민이 정류장이라고 말했으면(「○○ 정류장 앞이에요」) 그대로 둔다. 역 출구 · 관공서처럼 정류장이 아닌 점이 하나라도 있으면 그대로.
    건물 · 기관을 가리키는 이름(STOP_INST 끝말, 지명 표 4,881개 가운데 113개)에만 건다: 정류장 이름 자체(「래미안아파트파이낸셜뉴스」)는 그 정류장 자리에서 댄 말이다."""
    if c.get("t") != "at" or c.get("how") not in ("바로", "가까이") or not c.get("k") or STOP_SAID.search(said or ""):
        return c
    r = resolve(c["k"])
    if r["roads"] or r["areas"] or not r["kinds"] or any(k != "정류장" for k in r["kinds"]):
        return c
    nm = G.name[r["ids"][0]].replace(" ", "")
    if not STOP_INST.search(nm) or STOP_NOT.search(nm):
        return c                                          # 건물 · 기관 이름(끝말이 시청 · 병원 · 대학교 · 성당 …)만. 「래미안아파트파이낸셜뉴스」처럼 정류장 이름으로만 쓰이는 이름은 그 자리로(가상 600통 1118 #36, 11-21)
    return dict(c, how="근처", label=f"{c.get('label') or G.display(c['k'])} {KIND_WORD['정류장']}", stop_only=True)


def selftest_stop():
    """stoponly(85번): 정류장 점뿐인 이름난 곳은 「바로 앞」 한마디로 확정하지 않고, 정류장이라고 말한 통화 · 정류장이 아닌 곳은 그대로."""
    k = gaz.norm
    out = []
    for name in ("서울시청", "명동성당"):
        c = {"t": "at", "k": k(name), "how": "바로", "label": name, "sure": True}
        s = stop_only(c, f"{name} 바로 앞이에요")
        assert s["how"] == "근처" and s["label"] == f"{name} 버스 정류장" and s["stop_only"], s
        r0, r1 = infer([c])["r"], infer([s])["r"]
        assert r0 < 60 < 150 < r1, (name, r0, r1)
        out.append(f"{name} {r0:.0f}m → {r1:.0f}m")
    c = {"t": "at", "k": k("서울시청"), "how": "바로", "label": "서울시청"}
    assert stop_only(c, "서울시청 정류장 앞이에요") is c and stop_only(c, "서울시청 버스 정류장 바로 앞이에요") is c      # 정류장이라고 말했으면 그대로
    c = {"t": "at", "k": k("래미안아파트파이낸셜뉴스"), "how": "바로", "label": "래미안아파트파이낸셜뉴스"}
    assert stop_only(c, "래미안아파트파이낸셜뉴스 바로 앞이에요") is c      # 정류장 이름으로만 쓰이는 이름은 그 자리로(가상 600통 1118 #36)
    for name in ("잠실역 1번 출구", "상도1동주민센터", "롯데월드타워", "노량진수산시장"):
        c = {"t": "at", "k": k(name), "how": "바로", "label": name}
        assert stop_only(c, f"{name} 바로 앞이에요") is c, name      # 역 출구 · 관공서 · 볼거리 · 건물은 그대로(시연 대본 둘)
    print("stoponly 스스로 시험 통과 (" + " · ".join(out) + ", 정류장이라고 말한 통화 · 정류장 이름 · 역 출구 · 관공서는 그대로)")


def selftest_road():
    """roadcls(86번): 양재대로 일반 구간 앞 역 출구는 자동차전용도로가 아니고, 진짜 자동차전용도로(강변북로 · 양재대로 trunk 구간)는 그대로."""
    global _express
    k = gaz.norm
    had = set(ON)
    def cls(clues):
        global _express
        _express = None                                   # place_class가 모아 둔 자동차전용도로 칸을 켜고 끔에 맞춰 다시
        return place_class(infer(clues))[0]
    out = []
    for name in ("방이역 1번 출구", "둔촌동역", "올림픽공원역"):
        c = [{"t": "at", "k": k(name), "how": "바로"}]
        ON.discard("roadcls")
        before = cls(c)
        ON.add("roadcls")
        after = cls(c)
        assert before == "자동차전용도로" and after != "자동차전용도로", (name, before, after)
        out.append(f"{name} {before} → {after}")
    road = [{"t": "at", "k": k("강변북로")}, {"t": "past", "k": k("성수대교")}, {"t": "before", "k": k("영동대교")}, {"t": "past", "k": k("서울숲 보행다리"), "how": "바로"}]
    assert cls(road) == "자동차전용도로"                      # 진짜 자동차전용도로(로드킬 장면)는 켜도 그대로
    j = next(i for i, r in enumerate(G.roads) if r["name"] == "양재대로" and r["cls"] == "trunk")
    x, y = G.road_xy(j)[len(G.road_xy(j)) // 2]
    assert cls([{"t": "pt", "p": [float(x), float(y)], "r": 20.0}]) == "자동차전용도로"      # 양재대로의 자동차전용 구간(trunk)은 켜도 그대로
    ON.clear(), ON.update(had)
    _express = None
    print("roadcls 스스로 시험 통과 (" + " · ".join(out) + ", 강변북로 · 양재대로 trunk 구간은 그대로)")


def selftest_hood():
    """hood(87번): 「명동이에요」 · 「신촌이요」 같은 첫마디를 동 범위로(한 점 아님), 「명동역 6번 출구」 같은 더 좁은 말 · 「종로」 길은 그대로."""
    k = gaz.norm
    if "hood" not in ON:
        G.add_hoods()                                     # 스스로 시험에서만 켠 판과 같은 색인으로(이 프로세스 안)
    out = []
    for word, tail in (("명동", "이에요"), ("신촌", "이요"), ("종로", "요"), ("광화문", "이요"), ("압구정", "이요"), ("동대문", "이요"), ("성수", "요"), ("망원", "이요")):
        ms = G.mentions(word + tail)
        assert ms and ms[0]["key"] == k(word) + gaz.HOOD_KEY, (word, ms)
        R = infer([{"t": "at", "k": ms[0]["key"]}])
        assert R and R["r"] > 200, (word, R and R["r"])  # 한 점이 아니라 그 동 일대
        out.append(f"{word} {R['r']:.0f}m")
    for said, word in (("CU 신촌피어 근처예요", "신촌"), ("압구정엮 근처예요", "압구정"), ("명동스타벅스 앞이에요", "명동")):
        assert all(m["key"] != k(word) + gaz.HOOD_KEY for m in G.mentions(said)), (said, G.mentions(said))      # 더 긴 이름의 일부인 동네 말은 동네로 읽지 않음(600통 1114 #92)
    for said, word, main in (("광화문 앞이에요", "광화문", True), ("동대문 옆이요", "동대문", True), ("광화문 건너편이요", "광화문", True), ("을지로 따라 가다가요", "을지로", True),
                             ("종로 따라 걷다가 봤어요", "종로", False), ("명동 앞인데요", "명동", False)):
        keys = [m["key"] for m in G.mentions(said)]      # (PR #150 리뷰) 관계 말이 붙으면 동 범위로 넓히지 않고 main이 읽던 대로(광화문 · 동대문 점, 을지로 길 / 종로 · 명동 두 글자는 main도 안 읽음)
        assert k(word) + gaz.HOOD_KEY not in keys and (k(word) in keys) == main, (said, keys)
    ms = G.mentions("명동역 6번 출구 바로 앞이에요")
    assert ms and ms[0]["key"] != k("명동"), ms           # 더 좁은 말은 그대로
    assert any(r[0] == "r" for r in G.ix[k("종로")]) and any(r[0] == "r" for r in G.ix[k("을지로")])      # 같은 이름의 길은 덮지 않음
    print("hood 스스로 시험 통과 (" + " · ".join(out) + f", 「명동역 6번 출구」는 {ms[0]['name']})")


def selftest():
    k = gaz.norm
    assert infer([{"t": "at", "k": k("강변북로")}, {"t": "toward", "k": k("성동구")}, {"t": "past", "k": k("서울숲")}]) is not None      # 구 · 공원 이름을 「그쪽 · 지났다」의 기준으로 써도 돈다
    road = [{"t": "at", "k": k("강변북로")}]
    R1 = infer(road)
    assert R1 and R1["on_road"] and R1["r"] > 5000, R1 and R1["r"]
    q1 = questions(R1, road, {"type": "carcass", "animal_matter": True, "alive": False})
    assert q1[0]["id"] == "between" and any("성수대교" in o["label"] and "영동대교" in o["label"] for o in q1[0]["options"]), [(q["id"], [o["label"] for o in q["options"]]) for q in q1]
    c2 = road + [{"t": "past", "k": k("성수대교")}, {"t": "before", "k": k("영동대교")}]
    R2 = infer(c2)
    assert R2["ctx"]["head"] and R2["ctx"]["head"][0] > 0.8 and 500 < R2["r"] < 1500, (R2["ctx"]["head"], R2["r"])
    c3 = c2 + [{"t": "past", "k": k("서울숲 보행다리"), "how": "바로"}]
    R3 = infer(c3)
    d3 = describe(R3, c3)
    assert R3["r"] < 130 and d3["road"] == "강변북로" and d3["dir"] == "구리 방향" and d3["gu"] == "성동구", (R3["r"], d3)
    assert place_class(R3)[0] == "자동차전용도로"
    park = [{"t": "at", "k": k("서울숲")}]
    Ra = infer(park)
    qa = questions(Ra, park, {"type": "stray", "animal_matter": True, "alive": True, "leash": False})
    assert qa[0]["id"] == "zone", [q["id"] for q in qa]
    i_park = next(i for i, p in enumerate(G.parks) if p["name"] == "서울숲")
    cb = park + [{"t": "in", "a": ["park", i_park]}, {"t": "at", "k": k("사슴우리")}]
    Rb = infer(cb)
    cc = cb + [{"t": "at", "k": k("사슴우리 옆 화장실"), "how": "바로"}]
    Rc = infer(cc)
    assert Ra["r"] > Rb["r"] > Rc["r"] and is_done(Rc) and place_class(Rc) == ("시 공원", "서울숲"), (Ra["r"], Rb["r"], Rc["r"], place_class(Rc))
    # 한 번 틀리게 말해도 진짜 자리가 남는다: 「영동대교 지났다」고 잘못 말한 뒤 서울숲 보행다리를 대면 다시 그쪽으로 온다
    wrong = road + [{"t": "past", "k": k("영동대교"), "how": "조금"}, {"t": "past", "k": k("서울숲 보행다리"), "how": "바로"}]
    Rw = infer(wrong)
    i_fb = G.name.index("서울숲 보행다리")
    off = math.hypot(Rw["cx"] - G.x[i_fb], Rw["cy"] - G.y[i_fb])
    assert off < 400 and Rw["trust"][1] < Rw["trust"][2], (off, Rw["trust"])
    # 프랜차이즈: 서울 전체에 수백 곳 → 다른 단서와 겹치면 한두 곳
    Rs = infer([{"t": "at", "k": k("스타벅스")}])
    Rt = infer([{"t": "at", "k": k("스타벅스")}, {"t": "at", "k": k("뚝섬역")}])
    assert Rs["r"] > 5000 and Rt["r"] < 400, (Rs["r"], Rt["r"])
    pts, cell = heat(R1)
    assert len(pts) <= 2500 and cell >= STEP
    # (bigplace) 넓은 곳의 「바로 앞」은 그 크기만큼 넓게 서고, 작은 곳은 그대로다. 넓은 곳에는 한가운데 점에 핀을 찍지 않는다
    had = "bigplace" in ON
    big, small = [{"t": "at", "k": k("서울문창초등학교"), "how": "바로"}], [{"t": "at", "k": k("상도1동주민센터"), "how": "바로"}]
    ON.discard("bigplace")
    r0, s0 = infer(big)["r"], infer(small)["r"]
    ON.add("bigplace")
    Rg, s1 = infer(big), infer(small)["r"]
    ext = float(G.ext[resolve(k("서울문창초등학교"))["ids"][0]])
    assert r0 <= DONE_M < ext < Rg["r"] < ext + 60 and s0 == s1 and not is_done(Rg), (r0, ext, Rg["r"], s0, s1)
    a = anchor(Rg, big)
    assert a["ext"] == ext and a["d"] == 0 and anchor(infer(small), small)["ext"] == 0, a
    ON.add("bigplace") if had else ON.discard("bigplace")
    # (EDGE_ON · 75번) 둘레에 길이 있는 곳: 호수는 물 안이 낮고, 광장 가장자리는 가운데에 핀을 찍지 않고, 한가운데는 가운데로, 방위 말은 그쪽으로, 「공원 + 다리 밑」은 둘이 만나는 곳
    had = set(ON)
    ON.update(EDGE_ON.split(","))
    G.add_bridges()
    lake = resolve(k("항동저수지"))
    ring = water_ring(lake)
    gx, gy = unpack(box_keys(ring[:, 0].min(), ring[:, 1].min(), ring[:, 0].max(), ring[:, 1].max()))
    deep = np.where(in_ring(gx, gy, np.vstack((ring, ring[:1]))), ring_dist(gx, gy, ring), -1.0)
    mid = np.array([gx[deep.argmax()], gy[deep.argmax()]])      # 물 안에서 테두리가 가장 먼 점
    v = _like(0, {"t": "at", "k": k("항동저수지"), "how": "가까이"}, np.zeros(2), np.array([mid[0], ring[0, 0]]), np.array([mid[1], ring[0, 1]]), _context([]))
    assert deep.max() > 20 and water_ring(resolve(k("청계천"))) is None and v[0] <= LAKE_IN < 0.9 < v[1], (v, deep.max())      # 물 한가운데 ≤ 0.1, 테두리 위 ≈ 1. 하천은 고리가 아니다
    box_mid = [float(ring[:, 0].min() + ring[:, 0].max()) / 2, float(ring[:, 1].min() + ring[:, 1].max()) / 2]
    west = [{"t": "cone", "o": box_mid, "v": [-1.0, 0.0], "cos": 0.5, "f": 0.03}, {"t": "at", "k": k("항동저수지"), "how": "가까이"}]
    Rw = infer(west)
    assert Rw["cx"] < box_mid[0] - 30 and Rw["ringed"] == "항동저수지" and _rim_side(Rw) == "서" and describe(Rw, west)["rim"]["side"] == "서", (Rw["cx"] - box_mid[0], Rw.get("ringed"))
    i_pl = next(i for i, a in enumerate(G.parks) if a["name"] == "숭례문광장")
    edge = [{"t": "rim", "k": k("숭례문광장"), "w": 25.0}, {"t": "in", "a": ["park", i_pl]}]
    Re, Rm = infer(edge), infer([{"t": "core", "k": k("숭례문광장")}])
    assert Re["hole"] and not is_done(Re) and is_done(Rm) and not Rm.get("ringed"), (Re["r"], Re["hole"], Rm["r"])
    ON.discard("ringdone")
    assert is_done(Re)                                    # 그 판정이 없으면 고리 가운데(광장 한가운데)에 핀을 찍는다
    ON.add("ringdone")
    i_self = next(i for i in range(G.shop0) if G.name[i] == "열린송현 녹지광장")
    Rp = infer([{"t": "at", "k": k("열린송현 녹지광장")}])
    assert self_area(i_self) and i_self not in _candidates(*_sample(Rp), 100.0)[0]
    i_pk = next(i for i, a in enumerate(G.parks) if a["name"] == "망원한강공원")
    under = [{"t": "in", "a": ["park", i_pk]}, {"t": "at", "k": k("양화대교"), "how": "바로"}]
    Ru, i_br = infer(under), resolve(k("양화대교"))["ids"][0]
    assert is_done(Ru) and bridge_dist(i_br, np.array([Ru["cx"]]), np.array([Ru["cy"]]))[0] <= 20 and math.hypot(Ru["cx"] - G.x[i_br], Ru["cy"] - G.y[i_br]) > 300, (Ru["r"], Ru["cx"], Ru["cy"])
    had_bl = "bridgelong" in ON                               # (bridgelong, 기본 켬) 아래 다리 시험은 「다리만 댄 말은 가운데 한 점」인 끈 동작부터 본다. 켠 동작은 long1에서
    ON.discard("bridgelong")
    path = [{"t": "at", "k": k("도림천 자전거길")}, {"t": "at", "k": k("도림천고가도로교"), "how": "바로"}]      # 길 이름 + 다리 밑: 그 길이 다리 면 아래를 지나는 구간(이 고가는 하천 위로 길게 놓여 한 점이 아니다). 다리 가운데 한 점으로 끝내지 않는다
    had_br = "bridgeroad" in ON                               # (bridgeroad) 끄면 길 이름과 함께 나온 다리는 전처럼 가운데 한 점
    ON.discard("bridgeroad")
    assert not infer(path)["ctx"]["bp"] and is_done(infer(path))
    ON.add("bridgeroad")
    Rp2, i_b2 = infer(path), resolve(k("도림천고가도로교"))["ids"][0]
    assert Rp2["ctx"]["bp"] == {1} and not is_done(Rp2) and float(bridge_dist(i_b2, Rp2["x"][Rp2["cred"]], Rp2["y"][Rp2["cred"]]).max()) <= 80, (Rp2["ctx"]["bp"], Rp2["r"])
    assert is_done(infer(path[1:])) and not infer(path[1:])["ctx"]["bp"]
    (ON.add if had_br else ON.discard)("bridgeroad")
    Rsolo = infer(under[1:])
    assert math.hypot(Rsolo["cx"] - G.x[i_br], Rsolo["cy"] - G.y[i_br]) < 30      # 다리만 댄 말은 전처럼 가운데 점
    long1, short1 = [{"t": "at", "k": k("보라매고가"), "how": "바로"}], [{"t": "at", "k": k("묵동교"), "how": "바로"}]      # (bridgelong, 기본 켬) 긴 다리 · 고가는 혼자 나와도 면으로
    assert is_done(infer(long1))                                 # 끄면 전처럼 가운데 한 점으로 끝난다(1.6km 고가의 가운데)
    ON.add("bridgelong")
    Rl, i_bl = infer(long1), resolve(k("보라매고가"))["ids"][0]
    assert not is_done(Rl) and Rl["r"] > 300 and float(np.percentile(bridge_dist(i_bl, Rl["x"][Rl["cred"]], Rl["y"][Rl["cred"]]), 90)) <= 40, (Rl["r"], Rl["r_cover"])      # 범위 = 고가를 따라 난 띠(가운데 한 점이 아니다)
    assert is_done(infer(short1))                                # 짧은 다리(75m)는 켜도 한 점
    (ON.add if had_bl else ON.discard)("bridgelong")
    # (ASK_ON · 75번 후보 2, 기본 켬) 질문 다듬기 — 스위치마다 끈 동작 · 켠 동작
    had_ask = ON & (set(ASK_ON.split(",")) | {"sameopts"})                     # 기본으로 켜져 있든 꺼져 있든: 다 끄고 하나씩 켜 본 뒤 되돌린다
    ON.difference_update(had_ask)
    ring_s = water_ring(resolve(k("석촌호수")))
    mid_s = [float(ring_s[:, 0].min() + ring_s[:, 0].max()) / 2, float(ring_s[:, 1].min() + ring_s[:, 1].max()) / 2]
    i_sp = next(i for i, a in enumerate(G.parks) if a["name"] == "송파나루공원")
    lake_s = [{"t": "cone", "o": mid_s, "v": [-1.0, 0.0], "cos": 0.5, "f": 0.03}, {"t": "at", "k": k("석촌호수"), "how": "가까이"}, {"t": "in", "a": ["park", i_sp]}]      # 「석촌호수 서쪽 산책로예요」 · 「공원 안이에요」
    Rlk = infer(lake_s)
    c1 = _q_closest(Rlk, *_sample(Rlk), lake_s)
    far = lake_s + c1["options"][-1]["set"]["clues"]            # 「다 멀어요」
    again = lambda: (_q_closest(infer(far), *_sample(infer(far)), far) or {}).get("name")      # noqa: E731
    assert again() == c1["name"]                              # 끄면 같은 넷을 또 내민다(11-20 현장 서버에서 본 것)
    marks = lambda: {o["label"] for o in (_q_marks(infer(far), *_sample(infer(far)), "mark", far) or {"options": []})["options"]}      # noqa: E731
    gone = set(c1["name"].split(", "))
    assert marks() & gone                                     # 끄면 방금 「다 멀어요」라고 한 곳을 보기로 또 내민다
    ON.add("closestnew")
    assert again() and not set(again().split(", ")) & gone, again()      # 켜면 새 보기로
    assert not marks() & gone                                 # 간판 · 바로 앞 질문의 보기에서도 뺀다
    ON.discard("closestnew")
    stray = {"type": "stray", "animal_matter": True, "alive": True, "leash": False}
    first = questions(Rlk, lake_s, stray)[0]
    assert first["id"] == "closest" and questions(Rlk, lake_s, stray, (), lambda q: q["id"] == "closest")[0]["id"] == "closest"      # 끄면 same을 줘도 그대로
    ON.add("sameopts")
    assert questions(Rlk, lake_s, stray, (), lambda q: q["id"] == "closest")[0]["id"] != "closest"      # 켜면 같은 보기로 물었던 질문은 건너뛴다
    ON.discard("sameopts")
    ON.update(had_ask)
    # 스위치마다 하나씩: 넓은 곳에 걸음 안 묻기(bigdist) · 넓은 둘레에서는 둘레 질문 먼저(rimask) · 「가장 가까우세요」 두 번까지(closestcap)
    i_tk = next(i for i, a in enumerate(G.parks) if a["name"] == "뚝섬한강공원")
    pool = [{"t": "in", "a": ["park", i_tk]}, {"t": "at", "k": k("뚝섬수영장"), "how": "바로"}]
    Rq = infer(pool)
    assert G.ext[resolve(k("뚝섬수영장"))["ids"][0]] > BIG_M and _q_dist(Rq, pool) is None
    ON.discard("bigdist")
    assert _q_dist(Rq, pool) is not None                  # 그 스위치가 없으면 수영장 가운데 점에서 걸음을 묻는다
    ON.add("bigdist")
    wide = [{"t": "at", "k": k("석촌호수"), "how": "가까이"}]
    Rk, said = infer(wide), {"type": "litter", "told": "쓰레기"}
    ask = lambda log: [(q["id"], q.get("area")) for q in questions(Rk, wide, said, log)]      # noqa: E731
    assert Rk["r_cover"] > 250 and ("closest", "석촌호수") in ask([]), ask([])
    ON.discard("rimask")
    assert ("closest", "석촌호수") not in ask([])
    ON.add("rimask")
    twice = ["mark!", "mark!", "closest", "closest"]
    assert "closest" not in [q for q, _ in ask(twice)], ask(twice)
    ON.discard("closestcap")
    assert "closest" in [q for q, _ in ask(twice)], ask(twice)      # 그 스위치가 없으면 세 번째도 묻는다
    had_gn = "genericname" in ON                          # (genericname · 83번) 되짚기: 80번에서 곳 이름 없이 흔한 낱말만 댄 첫마디가 한 곳으로 묶이던 이름들
    alone = ["쓰레기통", "따릉이대여소", "시장입구", "말동상", "입구광장", "잔디밭", "빠지는길", "버스정류장앞"]
    ON.discard("genericname")
    assert all(infer([{"t": "at", "k": w, "how": "가까이"}]) is not None for w in alone)      # 끄면 그 낱말 하나로 서울 어딘가에 범위가 선다
    ON.add("genericname")
    assert all(infer([{"t": "at", "k": w, "how": "가까이"}]) is None for w in alone), [w for w in alone if infer([{"t": "at", "k": w, "how": "가까이"}]) is not None]
    i_sf = next(i for i, a in enumerate(G.parks) if a["name"] == "서울숲")
    Rg = infer([{"t": "in", "a": ["park", i_sf]}, {"t": "at", "k": "잔디밭", "how": "가까이"}])       # 「서울숲 … 잔디밭」: 그 공원 안이라 남는다(시연 노점 장면)
    i_fm = resolve("잔디밭")["ids"][0]
    assert Rg is not None and math.hypot(Rg["cx"] - G.x[i_fm], Rg["cy"] - G.y[i_fm]) < 150, Rg and (Rg["cx"], Rg["cy"])
    Ry = infer([{"t": "at", "k": "잔디밭", "how": "가까이"}, {"t": "at", "k": gaz.norm("여의도공원")}])     # 「공원 잔디밭 … 여의도공원이요」: 서울숲 가족마당은 빠지고 여의도에 선다(80번 c15 10km)
    assert Ry is not None and math.hypot(Ry["cx"] - G.x[i_fm], Ry["cy"] - G.y[i_fm]) > 5000
    assert not generic_key(gaz.norm("광장시장")) and not generic_key(gaz.norm("서울숲")) and not generic_key(gaz.norm("호수약국"))
    demo = [gaz.norm(w) for w in ("큰 연못", "얕은 연못", "보행교", "사슴 있는 데", "2번 출입구")]      # 시연 장면용 표의 장소 · 별명: 혼자서는 서지 않고, 서울숲 안이면 남는다
    assert all(demo_key(w) for w in demo) and not demo_key(gaz.norm("서울숲")) and not demo_key(gaz.norm("상도역"))
    assert all(infer([{"t": "at", "k": w, "how": "가까이"}]) is None for w in demo)
    Rd = infer([{"t": "in", "a": ["park", i_sf]}, {"t": "at", "k": gaz.norm("큰 연못"), "how": "바로"}])
    i_lk = resolve(gaz.norm("큰 연못"))["ids"][0]
    assert Rd is not None and math.hypot(Rd["cx"] - G.x[i_lk], Rd["cy"] - G.y[i_lk]) < 100
    Rsd = infer([{"t": "at", "k": gaz.norm("상도역")}, {"t": "at", "k": gaz.norm("2번 출입구"), "how": "바로"}])      # 다른 곳 이름과 같이 나온 별명은 서울숲으로 끌지 않는다
    i_sd = resolve(gaz.norm("상도역"))["ids"][0]
    assert Rsd is not None and math.hypot(Rsd["cx"] - G.x[i_sd], Rsd["cy"] - G.y[i_sd]) < 600
    (ON.add if had_gn else ON.discard)("genericname")
    had_fs = "farshop" in ON                              # (farshop · 83번) 「명동역 6번 출구 나와서 밀리오레 앞」: 자료의 밀리오레 둘은 모두 2km 넘게 떨어져 있다
    mg = [{"t": "at", "k": gaz.norm("명동역 6번 출구")}, {"t": "at", "k": gaz.norm("밀리오레"), "how": "바로"}]
    i_mx = resolve(gaz.norm("명동역 6번 출구"))["ids"][0]
    ON.discard("farshop")
    Rm0 = infer(mg)
    assert math.hypot(Rm0["cx"] - G.x[i_mx], Rm0["cy"] - G.y[i_mx]) > 1500 or Rm0["r"] > 1500, (Rm0["r"],)      # 끄면 먼 밀리오레 쪽으로 끌려 넓게 퍼진다
    ON.add("farshop")
    Rm1 = infer(mg)
    assert math.hypot(Rm1["cx"] - G.x[i_mx], Rm1["cy"] - G.y[i_mx]) < 100 and Rm1["r"] < 300, (Rm1["cx"], Rm1["cy"], Rm1["r"])
    assert infer([mg[1]]) is not None                      # 가게 이름만 댄 말은 그대로 쓴다(어긋날 기준점이 없다)
    (ON.add if had_fs else ON.discard)("farshop")
    ON.clear(), ON.update(had)
    print(f"locate 스스로 시험 통과 (강변북로 {R1['r']:.0f}m → {R2['r']:.0f}m → {R3['r']:.0f}m, 서울숲 {Ra['r']:.0f}m → {Rb['r']:.0f}m → {Rc['r']:.0f}m, 스타벅스 {Rs['r']:.0f}m → 뚝섬역과 겹쳐 {Rt['r']:.0f}m)")


if __name__ == "__main__":
    selftest()
    selftest_stop()
    selftest_road()
    selftest_hood()
