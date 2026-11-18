"""가상 통화로 재기: 참 위치를 뽑아 가상의 시민이 화면의 질문에 답하게 하고, 몇 번 주고받아 확정한 점이 참 위치에서 얼마나 떨어졌는지 낸다.

    python3 demo/call/tools/sim_calls.py                 코드만으로 읽기(모델 없이)
    OPENBLAS_NUM_THREADS=1 .venv/bin/python demo/call/tools/sim_calls.py --solar [--model solar-mini4]      Solar가 다시 읽기까지(통화마다 호출 네댓 번)

참 위치를 놓는 법(11-14 밤에 바꿈 — 앞 판은 참 위치를 지명 표의 표지 2~35m 둘레에만 놓아 실제보다 좋게 나왔다):
- 골목 · 상가 길: 서울의 보통 길(2차로 이하 · 골목) 위 아무 점.          - 프랜차이즈 둘레: 체인 가게에서 5~80m 떨어진 아무 쪽.
- 역 출구 둘레: 지하철 출구에서 10~150m 떨어진 아무 쪽.                    - 공원 안: 큰 공원 열 곳의 경계 안 아무 점(둘레에 표지가 있든 없든).
- 자동차전용도로: 강변북로 · 올림픽대로 · 내부순환로 · 동부 · 북부 · 서부간선도로 위 아무 점(방향도 아무 쪽).
- 큰길: 테헤란로 · 강남대로 · 통일로 · 천호대로 · 남부순환로 위 아무 점.
참 위치에서 가장 가까운 지명 표의 점까지의 거리를 묶음마다 함께 낸다(「표지에서 얼마나 떨어진 곳에 놓았나」).

가상의 시민:
- 보이는 세상은 늘 「오픈스트리트맵 + 상가정보」 지명 표다. 시스템이 쓰는 지명 표는 CALL_SHOPS로 바꾼다(CALL_SHOPS=0 = 상가정보를 넣기 전).
  그래서 넣기 전에는 시민이 지도에 없는 가게 이름을 대는 일이 생긴다(실제 통화와 같다).
- 화면의 질문에 참 위치에서 보이는 것으로 답한다(60m 안의 가장 가까운 간판 · 지나온 다리 · 공원 안팎). 네 통화에 한 번은 이름을 조금 틀리게 말한다.
- 확인 질문: 되말한 문장에 자기가 있는 구가 아닌 구 이름이 들어 있으면 「아니요」. 화면이 「○○ 바로 앞」처럼 이름을 대면, 시민 둘레 50m(길 위는 200m) 안에
  그 이름이 보일 때 「네」라고 한다(「몇 m 떨어졌나」는 시민이 모른다).
  이름 없이 범위째 물으면 참 위치가 그 범위 안일 때 「네」.
- 열린 확인(CALL_ON=check): 화면이 댄 표지 말고, 60m(길 위 150m) 안의 가장 가까운 이름 하나를 댄다. 이름은 지어내지 않으므로 「네」로 기울지 않는다.
- 자동차전용도로에서 「지나온 것」을 물으면 220m 안 뒤쪽의 표지, 없으면 지난 큰 표지와 시간(「1분쯤」)을 댄다. 터널 · 지하차도는 달려온 줄에서
  옆으로 60m 안일 때만(갈라진 다른 차로의 지하차도는 보이지 않는다, 11-15). 긴 터널 안이면 「○○터널 안이에요」.
- 「틀린 확정」 = 좁혀서 「네」를 받았는데 확정한 점이 참 위치에서 60m(길 위 120m) 넘게 떨어진 것.
더 세게 재기:
    --n 150      통화 수(묶음마다 고르게, 씨앗 고정)
    --lie 0.1    위치 질문에 이 확률로 틀리게 답한다(옆 구간 · 반대 방향 · 수백 m 떨어진 간판)
    --dunno 0.1  위치 질문에 이 확률로 「잘 모르겠어요」
    --yes 0.3    틀린 자리를 되말해도 이 확률로 「네」라고 한다(「네」로 기우는 답)
    --json <파일> 통화마다의 결과를 적는다
    --seed 2026  참 위치를 뽑는 씨앗(기본 1114)
    --extreme    사람처럼 말하는 통화 묶음(36번): 통화마다 말버릇 한 갈래(STYLES)를 입힌다. 바라는 끝은 같은 통화를 말버릇 없이 코드로 돌린 결과(점이면 「맞는 자리」, 아니면 「틀린 확정 없음」).
                 --half dev|hold 로 반만(고칠 때 보는 반 · 끝에 한 번 확인하는 반). 차례마다 어긋난 화면 상태를 센다. --solar와 함께 쓰면 실제 Solar 다시 읽기를 거친다
    --sound 0.15 시민이 대는 이름의 글자마다 이 확률로 비슷한 소리로 바꿔 말한다(받아 적기 잡음 시험, 11-15). 셋 가운데 둘은 소리가 같은 바꿈
                 (ㅐ↔ㅔ · 된소리 · 거센소리 · 받침의 같은 소리), 하나는 소리가 다른 바꿈(ㅗ↔ㅓ · ㅜ↔ㅡ · ㄴ↔ㄹ). 이은 비율을 함께 낸다
    --nick       별명으로 말하는 시민(골목 · 공원 안만): 첫 말이 「은행나무 골목인데요」처럼 지명 표에 없는 이름. --nick-saved면 앞선 통화에서 상담사가
                 그 자리(참 위치에서 15m 빗나간 핀)에 별명을 저장해 둔 뒤
"""
import json
import math
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
SOLAR = "--solar" in sys.argv
ARG = lambda name, default: type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default   # noqa: E731
N, LIE, DUNNO, YES, SOUND = ARG("--n", 30), ARG("--lie", 0.0), ARG("--dunno", 0.0), ARG("--yes", 0.0), ARG("--sound", 0.0)
if "--model" in sys.argv:
    os.environ["CALL_MODEL"] = sys.argv[sys.argv.index("--model") + 1]
os.environ["CALL_MODE"] = "live" if SOLAR else "code"
os.environ["CALL_NO_ENGINE"] = "1"
import numpy as np        # noqa: E402
import gaz                # noqa: E402
import server as S        # noqa: E402

L, G = S.L, S.G
if os.environ.get("SIM_WORLD"):                       # 시민이 보는 세상을 다른 폴더의 최신 지명 표로(예전 코드를 같은 세상에서 잴 때)
    import importlib.util
    spec = importlib.util.spec_from_file_location("gaz_world", Path(os.environ["SIM_WORLD"]) / "gaz.py")
    gw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gw)
    keep = {k: os.environ.get(k, "1") for k in ("CALL_SHOPS", "CALL_NODES", "CALL_PARKNAMES", "CALL_RAMPS", "CALL_TOILETS")}
    os.environ.update(CALL_SHOPS="1", CALL_NODES="1", CALL_PARKNAMES="1", CALL_RAMPS="1", CALL_TOILETS="1")
    W = gw.Gazetteer()
    os.environ.update(keep)
elif any(os.environ.get(k, "1") == "0" for k in ("CALL_SHOPS", "CALL_NODES", "CALL_PARKNAMES", "CALL_RAMPS", "CALL_TOILETS")):       # 시민이 보는 세상은 늘 모든 자료가 든 지명 표(시민은 실제로 보이는 것을 말하고, 시스템은 자료에 넣은 것만 알아듣는다)
    keep = {k: os.environ.get(k, "1") for k in ("CALL_SHOPS", "CALL_NODES", "CALL_PARKNAMES", "CALL_RAMPS", "CALL_TOILETS")}
    os.environ.update(CALL_SHOPS="1", CALL_NODES="1", CALL_PARKNAMES="1", CALL_RAMPS="1", CALL_TOILETS="1")
    W = gaz.Gazetteer()
    os.environ.update(keep)
else:
    W = G
THINGS = ("화장실", "놀이터", "정자", "운동기구", "음수대", "분수")    # 이름 없이 종류로 말하는 것(「화장실 옆이에요」)
SAY = {"carcass": "동물이 차에 치여 죽어 있어요", "road": "도로가 움푹 파여서 위험해요", "light": "가로등이 꺼져서 깜깜해요", "stray": "개 한 마리가 주인 없이 돌아다녀요",
       "park_use": "공원 벤치가 부서져 있어요", "vendor": "노점이 좌판을 깔고 길을 막고 있어요", "litter": "누가 쓰레기를 잔뜩 버리고 갔어요", "smoking": "사람들이 모여서 담배를 피워요",
       "parking": "차를 불법 주차해 놔서 못 지나가요", "noise": "공사 소리가 너무 시끄러워요"}
VISIBLE = lambda i: not gaz.GENERIC.match(W.name[i].replace(" ", "")) and W.kind[i] not in ("동네", "산") and 3 <= len(W.name[i]) <= 16 and "(" not in W.name[i]   # noqa: E731
CATS = ["골목 · 상가 길", "프랜차이즈 둘레", "역 출구 둘레", "공원 안", "자동차전용도로", "큰길"]
EXPRESS = ("강변북로", "올림픽대로", "내부순환로", "동부간선로", "북부간선도로", "서부간선로")      # 지명 표의 길 이름 꼴(11-14 밤 전에는 「동부간선도로」 · 「서부간선도로」로 적어 두 길이 뽑히지 않았다)
BIGROADS = ("테헤란로", "강남대로", "통일로", "천호대로", "남부순환로")
ON_ROAD = ("자동차전용도로", "큰길")


def near(x, y, radius, pred=VISIBLE):
    idx = [int(i) for i in W.near(x, y, radius) if pred(int(i))]
    return sorted(idx, key=lambda i: math.hypot(W.x[i] - x, W.y[i] - y))


def typo(name, rng):
    """받아 적기가 틀린 꼴: 끝의 「점」 떼기 또는 모음 하나 바꾸기."""
    for a, b in (("뜨", "트"), ("교", "고"), ("에", "애"), ("역", "엮")):
        if a in name and rng.random() < 0.7:
            return name.replace(a, b, 1)
    return name[:-1] if name.endswith("점") else name


ALIKE = ({0: 1, 1: 0, 3: 4, 4: 3, 7: 8, 8: 7, 9: 10, 10: 9, 12: 13, 13: 12, 15: 0, 16: 3, 17: 7, 14: 12},   # 소리가 같은 바꿈: 첫소리(된소리 · 거센소리 ↔ 예사소리)
         {1: 5, 5: 1, 3: 7, 7: 3, 10: 15, 11: 15, 15: 11},                                   # 가운뎃소리(ㅐ↔ㅔ, ㅒ↔ㅖ, ㅙ · ㅚ ↔ ㅞ)
         {19: 7, 7: 19, 22: 7, 23: 7, 25: 7, 20: 19, 2: 1, 24: 1, 26: 17, 17: 26})            # 받침(같은 대표음). 자리 차례는 [첫소리, 가운뎃소리, 받침]
MISS = ({2: 5, 5: 2}, {8: 4, 4: 8, 13: 18, 18: 13}, {})                                       # 소리가 다른 바꿈(ㄴ↔ㄹ, ㅗ↔ㅓ, ㅜ↔ㅡ)


def sound_noise(name, c, p=None):
    """(--sound) 이름의 글자마다 SOUND 확률로 비슷한 소리로 바꾼다. 같은 통화의 같은 이름은 늘 같은 꼴로 틀린다(받아 적는 사람이 같은 말을 같게 잘못 듣는다)."""
    p = SOUND if p is None else p
    if not p or not name:
        return name
    rng, out = random.Random(f"sound:{ARG('--seed', 1114)}:{c['id']}:{name}"), []
    for ch in name:
        k = ord(ch) - 0xAC00
        if 0 <= k < 11172 and rng.random() < p:
            jm = [k // 588, k % 588 // 28, k % 28]
            table = ALIKE if rng.random() < 2 / 3 else MISS
            can = [(n, table[n][jm[n]]) for n in range(3) if jm[n] in table[n] and not (n == 2 and jm[n] == 0)]
            if can:
                n, v = rng.choice(can)
                jm[n] = v
                ch = chr(0xAC00 + jm[0] * 588 + jm[1] * 28 + jm[2])
        out.append(ch)
    said = "".join(out)
    if said != name:
        c.setdefault("pend", []).append((name, said))
    return said


STYLES = ["고쳐 말하기", "취소하기", "틀렸다 바로잡기", "민원부터 길게", "단서 여럿", "질문과 다른 대답", "머뭇거림 · 군말", "소리 비슷한 이름", "줄임말 · 별명", "모르겠어요 연달아", "방향 · 거리 거꾸로"]
SHORT = [(r"(\S+)역 (\d+)번 출구", r"\1 \2번"), (r"스타벅스", "스벅"), (r"파리바게뜨", "파바"), (r"올리브영", "올영"), (r"맥도날드", "맥날"), (r"투썸플레이스", "투썸"), (r"이디야커피", "이디야"),
         (r"메가MGC커피", "메가커피"), (r"(\S{2,})\d가\d?동", r"\1"), (r"(\S{2,})공원", r"\1"), (r"(\S{2,})\d동", r"\1동")]


def wrong_name(c, chips):
    """틀리게 댈 이름: 참 위치에서 250~700m 떨어진 보이는 이름 하나(자동차전용도로면 길에서 보이는 것)."""
    pred = (lambda i: VISIBLE(i) and W.kind[i] in gaz.ROADSIDE) if c["cat"] == "자동차전용도로" else VISIBLE
    far = [i for i in near(c["x"], c["y"], 700, pred) if math.hypot(W.x[i] - c["x"], W.y[i] - c["y"]) > 250 and W.name[i] not in chips]
    return W.name[random.Random(f"wrong:{ARG('--seed', 1114)}:{c['id']}").choice(far)] if far else None


def styled(c, q, view, rng, st, plain):
    """(--extreme) 사실은 그대로(plain = 참 위치에서 본 답) 두고 말버릇만 입힌다. 위치 질문에만, 갈래마다 한두 번."""
    s, qid, opts = c["style"], q["id"], q.get("options") or []
    if qid not in L.LOCQ and qid != "where":
        return f"아 네… {plain}" if s == "머뭇거림 · 군말" and qid != "confirm" else plain
    n = c["nloc"] = c.get("nloc", -1) + 1                 # 몇 번째 위치 질문인가(0부터)
    told = not plain.startswith(("잘 모르", "다른 건", "글쎄", "역은", "아니요", "둘 다"))
    if s == "고쳐 말하기" and n == 0 and told and c.get("wrong"):
        c["retracted"] = True
        return f"{c['wrong']}, 아 아니다, {plain}"
    if s in ("취소하기", "틀렸다 바로잡기") and n == 0 and c.get("wrong"):
        c["step"] = 1
        return f"{c['wrong']} 근처예요"
    if s == "취소하기" and c.get("step") == 1:
        c["step"], c["retracted"] = 0, True
        return f"아, 죄송해요. 아까 거기 아니에요. {plain}"
    if s == "틀렸다 바로잡기" and c.get("step") in (1, 2):
        c["step"] += 1
        c["retracted"] = c["step"] == 3
        return plain if c["step"] == 2 else f"아 참, 아까 {c['wrong']}라고 했는데 제가 잘못 말했어요. {plain}"
    if s == "질문과 다른 대답" and n < 2:
        alt = truth(c, dict(q, id="station" if qid in ("mark", "finer", "where", "seen", "either") else "mark", options=[]), view, rng, st)
        return alt if not alt.startswith(("다른 건", "역은")) else plain
    if s == "머뭇거림 · 군말":
        return f"음… 그러니까… {plain.replace(' ', ' 어… ', 1)} …아마 그럴 거예요"
    if s == "줄임말 · 별명":
        for a, b in SHORT:
            plain = re.sub(a, b, plain, count=1)
        return plain
    if s == "모르겠어요 연달아" and n < 2:
        return ["글쎄요, 잘 모르겠어요.", "음… 그것도 잘 모르겠네요."][n]
    if s == "방향 · 거리 거꾸로" and not c.get("flipped") and qid in ("dir", "next", "dist", "zone", "either", "near") and len(opts) >= 2 and told:
        true = [o["label"] for o in opts if gaz.norm(o["label"]) in gaz.norm(plain)] or ([opts[0]["label"]] if qid == "zone" and "안이에요" in plain else [opts[1]["label"]] if qid == "zone" else [])
        other = [o["label"] for o in opts[:3] if true and o["label"] not in true]
        if other:                                         # 다른 보기를 먼저 댔다가 바로 고친다(「구리 방향이요. 아 아니다, 일산 방향이요」)
            c["flipped"] = other[0]
            return f"{other[0]}이요. 아 아니다, {plain}"
    return plain


def mismatch(view, hist0):
    """화면이 서로 어긋난 상태(나 · 11-15): 범위 목록 · 위 범위 · 질문 · 접수 카드."""
    h, q, size = view.get("history") or [], view.get("question") or {}, view.get("size")
    out = []
    if h and not size:
        out.append("목록엔 범위, 위는 서울 전체")
    if h and size and len(h) > hist0 and h[-1]["m"] < size["m"]:
        out.append("이번 차례 목록 칸이 위 범위보다 좁음")
    if q.get("id") == "where" and size:
        out.append("범위가 있는데 「어디쯤인지」")
    if q.get("id") == "what" and (view.get("matter") or {}).get("line"):
        out.append("말한 일을 다시 물음")
    if view.get("done") and not (view.get("summary") or {}).get("where"):
        out.append("좁혀졌는데 카드 위치 없음")
    return out


HOW = lambda d: "바로 앞이에요" if d <= 12 else "옆이에요" if d <= 25 else "근처예요"   # noqa: E731


def inside(c):
    """참 위치가 길을 따라 놓인 긴 터널 · 다리(표준노드링크, 점이 여럿) 안이면 → (이름, 종류). 시민은 「○○터널 안이에요」라고 한다."""
    x, y, h = c["x"], c["y"], c.get("head") or [0, 0]
    by = {}
    for i in near(x, y, 400, lambda i: i >= getattr(W, "node0", len(W.name)) and W.kind[i] in ("터널", "다리") and VISIBLE(i)):
        by.setdefault(W.name[i], []).append(i)
    for name, ids in by.items():
        a = [(W.x[i] - x) * h[0] + (W.y[i] - y) * h[1] for i in ids]
        if len(ids) >= 2 and min(a) < -20 and max(a) > 20 and min(math.hypot(W.x[i] - x, W.y[i] - y) for i in ids) < 150:
            return name, W.kind[ids[0]]
    return None


def ring_at(rng, d0, d1):
    d, a = rng.uniform(d0, d1), rng.uniform(0, 2 * math.pi)
    return d * math.cos(a), d * math.sin(a)


def on_road(rng, names, cls=None):
    """이름 · 등급이 맞는 길 위 아무 점 → (x, y, 길 이름, 가는 방향)."""
    roads = [i for i, r in enumerate(G.roads) if (names is None or r["name"] in names) and (cls is None or r["cls"] in cls) and len(G.road_xy(i)) > (300 if names else 12)]
    for _ in range(400):
        i = rng.choice(roads)
        xy = G.road_xy(i)
        j = rng.randrange(5, len(xy) - 5)
        head = xy[j + 3] - xy[j - 3]
        head = head / (np.hypot(*head) or 1) * rng.choice((1, -1))
        if L._area_at(G.gu, *xy[j]):
            return float(xy[j][0]), float(xy[j][1]), G.roads[i]["name"], [float(head[0]), float(head[1])]
    raise RuntimeError("길 위 점을 못 뽑음")


def make_cases(n, seed=1114):
    rng, cases = random.Random(seed), []
    types = {"골목 · 상가 길": ("noise", "litter", "light", "parking", "vendor", "smoking", "road"), "프랜차이즈 둘레": ("parking", "smoking", "stray", "litter", "light", "noise"),
             "역 출구 둘레": ("litter", "smoking", "parking", "light", "noise", "vendor"), "공원 안": ("stray", "park_use", "vendor", "litter", "smoking"),
             "자동차전용도로": ("carcass", "road", "carcass", "light"), "큰길": ("carcass", "road", "light", "parking")}
    exits = [i for i, k in enumerate(W.kind) if k == "역 출구"]
    chains = [i for i, b in enumerate(W.brand) if b in ("GS25", "CU", "세븐일레븐", "스타벅스", "파리바게뜨", "이디야커피", "올리브영", "다이소", "메가MGC커피", "이마트24")]
    parks = [p for p in G.parks if p["name"] in ("서울숲", "보라매공원", "여의도공원", "올림픽공원", "북서울꿈의숲", "월드컵공원", "남산공원", "어린이대공원", "서울어린이대공원", "용산가족공원")]
    for k in range(n):
        cat = CATS[k % len(CATS)]
        t = types[cat][(k // len(CATS)) % len(types[cat])]
        c = {"cat": cat, "type": t}
        if cat == "골목 · 상가 길":
            x, y, road, _ = on_road(rng, None, {"residential", "tertiary", "unclassified", "living_street", "secondary"})
            c.update(x=x, y=y, dong=L._area_at(G.dong, x, y) or L._area_at(G.gu, x, y))
        elif cat == "프랜차이즈 둘레":
            i = rng.choice(chains)
            dx, dy = ring_at(rng, 5, 80)
            x, y = float(W.x[i]) + dx, float(W.y[i]) + dy
            c.update(x=x, y=y, brand=W.brand[i], gu=L._area_at(G.gu, x, y) or "서울", ad=math.hypot(dx, dy))
        elif cat == "역 출구 둘레":
            i = rng.choice(exits)
            dx, dy = ring_at(rng, 10, 150)
            c.update(x=float(W.x[i]) + dx, y=float(W.y[i]) + dy, exit=W.name[i], ad=math.hypot(dx, dy))
        elif cat == "공원 안":
            for _ in range(500):
                p = rng.choice(parks)
                x0, y0, x1, y1 = p["box"]
                x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
                if L.in_ring(np.array([x]), np.array([y]), p["ring"])[0]:
                    break
            c.update(x=x, y=y, park=p["name"])
        else:
            x, y, road, head = on_road(rng, EXPRESS if cat == "자동차전용도로" else BIGROADS)
            c.update(x=x, y=y, road=road, head=head)
        idx = W.near(c["x"], c["y"], 400)
        d = np.hypot(W.x[idx] - c["x"], W.y[idx] - c["y"]) if len(idx) else np.array([400.0])
        osm = (idx < W.shop0) | (idx >= W.shop1) if len(idx) else np.array([True])
        c["d_land"] = float(d.min()) if len(d) else 400.0                         # 참 위치 → 가장 가까운 지명 표의 점(가게 포함)
        c["d_osm"] = float(d[osm].min()) if osm.any() else 400.0                # 오픈스트리트맵만
        c["id"], c["noisy"] = k + 1, k % 4 == 3
        cases.append(c)
    return cases


NICK_A = ["은행나무", "빨간지붕", "파란대문", "큰느티나무", "돌담", "벽화", "시계탑", "분홍벤치"]
NICK_B = ["골목", "쉼터", "언덕길", "샘터", "마당", "계단길"]


def crossdir(c):
    """(--crossdir) 길 위 시민이 말할 「A에서 B 가는 방향」: A = 타고 가는 길 60m 안, 뒤쪽 800m 안의 가장 가까운 교차로 · 역(자동차전용도로는 나들목 · 다리 · 터널),
    B = 앞쪽 2km 안의 가장 가까운 같은 종류. 둘 다 있을 때만 → (A, B) 또는 None. 시민이 보는 세상(W)에서 고른다."""
    x, y, h = c["x"], c["y"], c.get("head") or [0, 0]
    kinds = ("나들목", "다리", "터널") if c["cat"] == "자동차전용도로" else ("교차로", "역")
    line = np.vstack([G.road_xy(i) for i, r in enumerate(G.roads) if r["name"] == c.get("road")] or [np.array([[x, y]])])
    cand = [i for i in near(x, y, 2000, lambda i: W.kind[i] in kinds and VISIBLE(i)) if float(np.hypot(line[:, 0] - W.x[i], line[:, 1] - W.y[i]).min()) <= 60]
    along = lambda i: (W.x[i] - x) * h[0] + (W.y[i] - y) * h[1]      # noqa: E731
    behind = [i for i in cand if -800 <= along(i) < -30]
    ahead = [i for i in cand if 30 < along(i) and W.name[i] not in [W.name[j] for j in behind[:1]]]
    return (W.name[behind[0]], W.name[ahead[0]]) if behind and ahead else None


def route_share(c, st, out):
    """(--route · 49번) 한 점까지 못 갔어도 넘길 곳이 정해졌나: 마지막 범위의 가능성 가운데 같은 넘길 곳으로 가는 몫(0~1)과 그것이 참 위치의 넘길 곳과 같은가."""
    clues, matter = S.understood(st)
    R = L.infer(clues) if clues else None
    if R is None or not matter.get("type"):
        return
    x, y, w = L._sample(R)
    keep = np.argsort(-w)[:300]
    by, memo = {}, {}
    for j in keep:
        px, py = float(x[j]), float(y[j])
        key = (L.place_class({"cx": px, "cy": py, "on_road": R["on_road"], "ctx": R["ctx"]}), L._area_at(G.gu, px, py))
        if key not in memo:
            memo[key] = S.route_of(matter, {"cx": px, "cy": py, "on_road": R["on_road"], "ctx": R["ctx"]})["hit"]["to"]
        by[memo[key]] = by.get(memo[key], 0.0) + float(w[j])
    top = max(by, key=by.get)
    truth_ = {"cx": c["x"], "cy": c["y"], "on_road": c["cat"] in ON_ROAD, "ctx": {"roads": [i for i, r in enumerate(G.roads) if r["name"] == c.get("road")][:1]}}
    want = S.route_of({"type": c["type"], "animal": "개" if c["type"] in ("stray", "carcass") else None}, truth_)["hit"]["to"]
    out.update(route_share=round(by[top] / sum(by.values()), 3), route_top_right=top == want)


def first_words(c):
    if c.get("first"):                                    # 사례가 정해 준 첫 말(tools/defect_set.py, 11-16)
        return c["first"]
    if c.get("nick"):
        return f"{c['nick']}인데요, {SAY[c['type']]}"
    if c.get("style") == "민원부터 길게":
        return f"여보세요, {SAY[c['type']]}. 며칠째 이래서요, 지나가는 사람들도 다 불편해하고 아이들도 다니는 길이라 걱정돼서 전화했어요."
    if c.get("style") == "소리 비슷한 이름":
        c = {**c, **{k: sound_noise(c.get(k), c, 0.3) for k in ("dong", "gu", "brand", "exit", "park", "road")}}
    c = {**c, **{k: sound_noise(c.get(k), c) for k in ("dong", "gu", "brand", "exit", "park", "road")}} if SOUND else c
    if "--crossdir" in sys.argv and c["cat"] in ON_ROAD and (cd := crossdir(c)):
        return f"{c['road']} {cd[0]}에서 {cd[1]} 가는 방향인데요, {SAY[c['type']]}"      # (--crossdir · 49번) 구청 인터뷰의 말투: 방금 지난 교차로 · 나들목에서 앞에 있는 곳 쪽
    place = {"골목 · 상가 길": f"{c.get('dong')} 쪽인데요", "프랜차이즈 둘레": f"{c.get('gu')}인데요, {c.get('brand')} {HOW(c.get('ad', 0))}",
             "역 출구 둘레": f"{c.get('exit')} {({'바로 앞이에요': '바로 앞', '옆이에요': '옆', '근처예요': '근처'})[HOW(c.get('ad', 0))]}인데요", "공원 안": f"{c.get('park')} 쪽인데요",
             "자동차전용도로": f"{c.get('road')} 타고 가는 중인데요", "큰길": f"{c.get('road')} 타고 가는 중인데요"}[c["cat"]]
    return f"{place}, {SAY[c['type']]}"


SEC = {"check": 10, "next": 8, "lampno": 20, "side": 8, "lane": 8, "went": 8, "plate": 12, "what": 8, "alive": 8, "leash": 8, "zone": 8, "confirm": 8, "dir": 8, "between": 10, "passed": 12, "mark": 12, "finer": 12, "station": 8, "near": 8, "seen": 8, "either": 10, "ago": 10, "which": 10, "where": 12, "from": 10, "again": 12, "alike": 10, "addr": 12}


def answer(c, q, view, rng, st, turn=0):
    """가상의 시민. 옵션에 따라 가끔 모른다고 하거나 틀리게 답한다.
    뽑기는 차례마다 따로(통화 · 차례 · 질문으로 씨앗): 앞에서 질문이 하나 끼어들어도 뒤 차례의 뽑기가 밀리지 않는다(11-15, 33번 0-1)."""
    qid, opts = q["id"], q["options"]
    rng = random.Random(f"{ARG('--seed', 1114)}:{c['id']}:{turn}:{qid}")
    if qid in L.LOCQ and qid != "which":
        if rng.random() < DUNNO:
            return "잘 모르겠어요"
        if rng.random() < LIE:
            wrong = None
            if qid in ("zone", "dir", "near", "seen", "either", "next") and len(opts) >= 2:
                true = truth(c, q, view, rng, st)
                other = [o for o in opts[:2] if o["label"] not in true]
                wrong = (other[0]["label"] + "이요") if other else None
                if qid == "next":                           # 지났다 ↔ 아직을 뒤집어 말한다
                    nm = opts[0]["label"].replace(" 지났음", "")
                    wrong = f"{nm}는 아직 안 나왔어요" if "지났어요" in true else f"{nm} 지났어요" if "아직" in true else None
            elif qid == "between" and len(opts) >= 2:
                o = rng.choice(opts)
                na, nb = o["label"].split(" ~ ")
                wrong = f"{na}는 지났고요, {nb}는 아직 안 나왔어요"
            else:
                far = [i for i in near(c["x"], c["y"], 600) if math.hypot(W.x[i] - c["x"], W.y[i] - c["y"]) > 250 and W.name[i] not in view["chips"]
                       and not getattr(W, "pk0", 0) <= i < getattr(W, "rp1", getattr(W, "pk1", 0))]     # 틀린 말은 수백 m 떨어진 간판에서(공원 안 이름을 더해도 뽑히는 말이 흔들리지 않게)
                wrong = f"{W.name[rng.choice(far)]} 근처예요" if far else None
            if wrong:
                c.setdefault("lies", []).append(wrong.split(" 근처")[0].split("이요")[0])
                return wrong
    if qid == "confirm":
        c["bias"] = bool(YES) and rng.random() < YES      # 마지막 확인의 「네」가 기운 답이었나(틀린 확정의 까닭을 가르려고 남긴다)
        if c["bias"]:
            return "네, 맞아요"
    return styled(c, q, view, rng, st, truth(c, q, view, rng, st)) if c.get("style") else truth(c, q, view, rng, st)


def seen_name(name, x, y, r):
    """시민 둘레 r m 안에 그 이름(또는 상표)의 장소가 보이나."""
    k = gaz.norm(name)
    return any(gaz.norm(W.name[i]) == k or gaz.norm(W.brand[i]) == k or gaz.norm(W.name[i]).startswith(k) for i in W.near(x, y, r))


def truth(c, q, view, rng, st):
    """화면의 질문에 참 위치에서 보이는 것으로 답한다."""
    x, y, qid, opts = c["x"], c["y"], q["id"], q["options"]
    road = c["cat"] in ON_ROAD
    say = lambda name: sound_noise(typo(name, rng) if c["noisy"] else name, c, 0.3 if c.get("style") == "소리 비슷한 이름" else None)   # noqa: E731
    if qid == "what":
        return c.get("what") or SAY[c["type"]]
    if qid == "alive":
        return "살아 있어요, 계속 움직여요" if c["type"] == "stray" else "안 움직여요, 죽은 것 같아요"
    if qid == "leash":
        return "목줄은 없어요"
    if qid == "zone":                                     # 화면이 댄 그 공원 안인가(「노을공원 안입니까」에 하늘공원 안이면 그 이름을 댄다)
        a = opts[0]["set"]["clues"][0]["a"] if opts else None
        if a and L.in_ring(np.array([x]), np.array([y]), L.area_of(a)["ring"])[0]:
            return "공원 안이에요"
        own = L._area_at(G.parks, x, y)
        return f"{own}이에요" if own else "공원 밖 길가예요"
    if qid == "check":                                   # 열린 확인(CALL_ON=check): 화면이 댄 표지 말고 보이는 이름 하나를 댄다(「네」로 기우는 시민도 이름은 지어내지 않는다)
        clues, _ = S.understood(st)
        R = L.infer(clues) if clues else None
        anc = L.anchor(R, clues) if R else None
        skip = gaz.norm(anc["name"]) if anc else "\0"
        pred = (lambda i: VISIBLE(i) and W.kind[i] in gaz.ROADSIDE) if c["cat"] == "자동차전용도로" else VISIBLE
        seen = [i for i in near(x, y, 150 if road else 60, pred) if skip not in gaz.norm(W.name[i]) and gaz.norm(W.name[i]) not in skip]
        if seen:
            d = math.hypot(W.x[seen[0]] - x, W.y[seen[0]] - y)
            return f"{say(W.name[seen[0]])} {'바로 옆이에요' if d <= 25 else '보여요'}"
        return "글쎄요, 다른 건 잘 모르겠어요"
    if qid == "confirm":
        gu = L._area_at(G.gu, x, y)                        # 시민은 자기가 있는 구는 안다: 되말한 문장에 다른 구 이름이 있으면 「아니요」
        if gu and any(g["name"] in q["say"] for g in G.gu) and gu not in q["say"]:
            return "아니요, 거기가 아니에요"
        if view["done"]:                                   # 이름 붙은 한 점으로 되말함: 그 이름이 시민 둘레에 보이면 「네」
            clues, _ = S.understood(st)
            R = L.infer(clues)
            anc = L.anchor(R, clues) if R else None
            if anc:                                        # 지명 표에 없는 이름(시민이 읽어 준 가로등 번호 · 지점번호)은 그 자리로 견준다
                named = any(gaz.norm(W.name[i]) == gaz.norm(anc["name"]) for i in W.near(anc["p"][0], anc["p"][1], 30))
                ok = seen_name(anc["name"], x, y, 200 if road else 50) if named else math.hypot(anc["p"][0] - x, anc["p"][1] - y) <= (200 if road else 50)
                return "네, 맞아요" if ok else "아니요, 거기가 아니에요"
            cx, cy = gaz.xy(*view["center"])
            return "네, 맞아요" if math.hypot(float(cx) - x, float(cy) - y) <= (120 if road else 60) else "아니요, 거기가 아니에요"
        if view.get("region"):                           # 범위째인데 화면이 이름 붙은 구역(공원 · 동)을 실어 보냈다: 시민에게 들리는 것은 그 이름이다(33번 0-3)
            in_reg = bool(L.in_ring(np.array([x]), np.array([y]), L.area_of(view["region"])["ring"])[0])
            return "네, 맞아요" if in_reg else "아니요, 거기가 아니에요"
        cx, cy = gaz.xy(*view["center"])                  # 범위째: 참 위치가 그 범위 안이면 「네」
        return "네, 맞아요" if math.hypot(float(cx) - x, float(cy) - y) <= max(120 if road else 60, view["radius"] or 0) else "아니요, 거기가 아니에요"
    if qid == "alike" and opts:                            # 소리가 같은 두 이름(「통일로 · 동일로」): 시민은 자기가 있는 구는 안다(11-16)
        gu = L._area_at(G.gu, x, y)
        heads = [o["label"].rpartition("의 ")[0] for o in opts if "의 " in o["label"]]
        if gu and sum(gu in h for h in heads) == 1:
            return f"{gu}요"
        near_ = [h.removesuffix(" 가까이") for h in heads if h.endswith(" 가까이") and seen_name(h.removesuffix(" 가까이"), x, y, 500)]     # 구로 갈리지 않는 보기: 가까이 있는 역 · 표지를 안다
        return f"{near_[0]} 근처예요" if len(near_) == 1 else "잘 모르겠어요"
    if qid == "same" and opts:                             # 같은 이름의 두 곳: 참 위치에서 60m 안의 가까운 쪽
        pts = [(math.hypot(o["set"]["clues"][0]["p"][0] - x, o["set"]["clues"][0]["p"][1] - y), o["label"]) for o in opts if (o.get("set") or {}).get("clues")]
        d, lab = min(pts, default=(1e9, ""))
        return f"{lab}이요" if d <= 60 else "잘 모르겠어요"
    if qid == "side" and opts:
        p = opts[0]["set"]["clues"][0]["p"]
        d = math.hypot(p[0] - x, p[1] - y)
        return "바로 앞이에요" if d <= 12 else "바로 옆이에요" if d <= 25 else "길 건너편이에요" if d <= 45 else "조금 떨어져 있어요"
    if qid == "closest" and opts:                          # 「어디가 가장 가까우세요?」: 가장 가까운 보기가 400m 안이면 그것, 아니면 「다 멀어요」
        named = [o for o in opts if (o.get("set") or {}).get("clues") and o["set"]["clues"][0].get("t") == "closest"]
        if named:
            o = min(named, key=lambda o: math.hypot(o["set"]["clues"][0]["p"][0] - x, o["set"]["clues"][0]["p"][1] - y))
            if math.hypot(o["set"]["clues"][0]["p"][0] - x, o["set"]["clues"][0]["p"][1] - y) <= 400:
                return f"{say(o['label'])}이요"
        return "다 멀어요"
    if qid == "dist" and opts:                             # 표지까지의 거리를 사람의 어림으로(참 거리 × exp(정규(0, 0.35)) — 오차 크기는 추측, 33번 2-2)
        p = opts[0]["set"]["clues"][0]["p"]
        d = math.hypot(p[0] - x, p[1] - y) * math.exp(rng.gauss(0, 0.35))
        return "바로 앞이에요" if d < 8 else "스무 걸음쯤이요" if d < 28 else "쉰 걸음쯤이요" if d < 70 else "멀리 보이기만 해요"
    if qid == "from" and opts:                             # 그 표지에서 어느 쪽: 참 위치 쪽과 60도 안인 보기가 있으면 그것, 없거나 표지 바로 앞이면 모른다
        dirs = [(o, o["set"]["dir"]) for o in opts if "dir" in (o.get("set") or {})]
        if dirs:
            ox, oy = dirs[0][1]["o"]
            n = math.hypot(x - ox, y - oy)
            o, d = max(dirs, key=lambda od: od[1]["v"][0] * (x - ox) + od[1]["v"][1] * (y - oy))
            if n >= 10 and (d["v"][0] * (x - ox) + d["v"][1] * (y - oy)) / n >= 0.5:
                return f"{o['label']}이요"
        return "잘 모르겠어요"
    if qid == "lampno":                                   # 세 통에 한 통만 번호를 읽을 수 있다고 본다(달리는 차에서는 읽기 어렵다)
        lamps = sorted((math.hypot(lx - x, ly - y), no) for no, lx, ly in W.lamps.values() if abs(lx - x) < 60 and abs(ly - y) < 60)
        return f"기둥에 {lamps[0][1]} 이라고 적혀 있어요" if lamps and (c["id"] // len(CATS)) % 3 == 0 else "번호는 못 봤어요"      # 묶음마다 세 통에 한 통(11-15 전에는 c["id"] % 3이라 자동차전용도로는 한 번도 읽지 않았다)
    if qid == "addr":                                     # (addrq) 건물 주소판: 걷는 사람이 20m 안 건물의 주소판을 두 통에 한 통 읽는다고 본다(가정 — 사람 시험으로 맞출 값). 받아 적기가 틀리는 통화는 번호 끝을 2 틀리게(옆 건물)
        a = S.nearest_addr(*gaz.lonlat(x, y)) if not road else None
        if a and a["m"] <= 20 and (c["id"] // len(CATS)) % 2 == 1:
            said_ = a["road"].split(" ", 1)[-1]
            if c["noisy"]:
                said_ = re.sub(r"(\d+)$", lambda m: str(int(m.group(1)) + 2), said_)
            return f"건물 주소판에 {said_} 이라고 적혀 있어요"
        return "운전 중이라 못 봤어요" if road else "주소판은 못 봤어요"
    if qid == "lane":
        return "갓길 쪽이에요" if c["type"] == "carcass" else "차로 위예요"
    if qid == "went":
        return "그 자리에 앉아 있어요"
    if qid == "plate":                                    # 가로등 고장: 25m 안에 번호를 아는 기둥이 있으면 두 통에 한 통은 번호를 읽어 준다
        lamps = sorted((math.hypot(lx - x, ly - y), no) for no, lx, ly in W.lamps.values() if abs(lx - x) < 30 and abs(ly - y) < 30)
        return f"기둥에 {lamps[0][1]} 이라고 적혀 있어요" if lamps and lamps[0][0] <= 25 and (c["id"] // len(CATS)) % 2 == 0 else "번호판은 안 보여요"      # 묶음마다 두 통에 한 통
    if qid == "near" and opts:
        p = opts[0]["set"]["clues"][0]["p"]
        return "네, 바로 앞이에요" if math.hypot(p[0] - x, p[1] - y) <= 30 else "조금 떨어져 있어요"
    if qid == "dir" and opts:
        v = [o["set"]["clues"][0]["v"] for o in opts]
        return opts[max(range(len(opts)), key=lambda n: v[n][0] * c["head"][0] + v[n][1] * c["head"][1])]["label"] + "이요"
    if qid == "between" and opts:
        for o in opts:
            a, b = o["set"]["clues"][0]["p"]
            if math.hypot(a[0] - x, a[1] - y) + math.hypot(b[0] - x, b[1] - y) <= 1.1 * math.hypot(a[0] - b[0], a[1] - b[1]) + 60:
                na, nb = o["label"].split(" ~ ")
                if c.get("head") and (b[0] - a[0]) * c["head"][0] + (b[1] - a[1]) * c["head"][1] < 0:
                    na, nb = nb, na
                return f"{say(na)}는 지났고요, {nb}는 아직 안 나왔어요"
        return "다리는 잘 모르겠어요"
    if qid in ("passed", "where", "mark", "finer") and road and (ins := inside(c)) and not any(ins[0] in ch for ch in view["chips"]):
        return f"{say(ins[0])} {'안이에요' if ins[1] == '터널' else '위예요'}"
    if qid == "passed":
        h = c.get("head") or [0, 0]
        seen_by = lambda i: (W.kind[i] != "터널" or abs((W.x[i] - x) * h[1] - (W.y[i] - y) * h[0]) <= 60) and (      # noqa: E731  터널 · 지하차도는 그 안을 지난 차만 안다: 달려온 줄에서 옆으로 60m 안(갈라진 다른 차로의 지하차도는 보이지 않는다, 11-15)
            not getattr(W, "rp0", 0) <= i < getattr(W, "rp1", 0) or float(W.rhead[i - W.rp0] @ np.asarray(h)) > 0)       # 나가는 길 · 들어오는 길은 내 방향 것만 지난다
        behind = [i for i in near(x, y, 220, lambda i: W.kind[i] in gaz.ROADSIDE and VISIBLE(i) and W.name[i] not in view["chips"] and seen_by(i)) if (x - W.x[i]) * h[0] + (y - W.y[i]) * h[1] > 0]
        if behind:
            d = math.hypot(W.x[behind[0]] - x, W.y[behind[0]] - y)
            return f"{say(W.name[behind[0]])} {'막 지나자마자였어요' if d < 90 else '조금 지나서였어요'}"
        line = np.vstack([G.road_xy(i) for i, r in enumerate(G.roads) if r["name"] == c.get("road")] or [np.array([[x, y]])])
        by_road = lambda i: float(np.hypot(line[:, 0] - W.x[i], line[:, 1] - W.y[i]).min()) <= 150      # noqa: E731  타고 가는 길에서 보이는 것만(800m 떨어진 역은 「지나지」 않는다)
        big = [i for i in near(x, y, 5000, lambda i: W.kind[i] in ("다리", "나들목", "터널", "역") and VISIBLE(i) and W.name[i] not in view["chips"]) if (x - W.x[i]) * h[0] + (y - W.y[i]) * h[1] > 0 and by_road(i)
               and seen_by(i)]
        if big and c.get("road") in L.EXPRESSWAYS:
            d = math.hypot(W.x[big[0]] - x, W.y[big[0]] - y)        # 220~500m 지난 것은 「조금 지나서」(11-14 밤까지는 「잘 못 봤어요」라고 해 버렸다)
            return f"{say(W.name[big[0]])} 조금 지나서였어요" if d <= 500 else f"{say(W.name[big[0]])} 지나고 {max(1, round(d / 1000))}분쯤 됐어요"
        return "글쎄요, 잘 못 봤어요"
    if qid == "next" and opts:                           # 「○○는 지나셨어요, 아직이에요?」: 가는 방향으로 그 표지를 지났나
        p, h = opts[0]["set"]["clues"][0]["p"], c.get("head") or [0, 0]
        a, nm = (x - p[0]) * h[0] + (y - p[1]) * h[1], opts[0]["label"].replace(" 지났음", "")
        if abs(a) < 30:
            return "글쎄요, 거의 그 근처라 잘 모르겠어요"
        return f"{say(nm)} 지났어요" if a > 0 else f"{say(nm)}는 아직 안 나왔어요"
    if qid == "ago" and opts:
        p = opts[0]["set"]["clues"][0]["anchor"]
        d = math.hypot(p[0] - x, p[1] - y)
        return opts[0 if d < 300 else 1 if d < 1500 else 2 if d < 3500 else 3]["label"] + "이요"
    if qid == "seen" and opts:
        kind = opts[0]["set"]["clues"][0]["c"]
        return "네, 보여요" if near(x, y, 80, lambda i: W.kind[i] == kind) else "아니요, 안 보여요"
    if qid == "either" and opts:
        ds = [math.hypot(o["set"]["clues"][0]["p"][0] - x, o["set"]["clues"][0]["p"][1] - y) for o in opts[:2]]
        k = 0 if ds[0] <= ds[1] else 1
        return f"{opts[k]['label']}이에요" if ds[k] <= max(150, 1.5 * opts[k]["set"]["clues"][0]["r"]) else "둘 다 아니에요"
    if qid == "which" and opts:
        hit = [o["label"] for o in opts if any(lie and lie in o["label"] for lie in c.get("lies", []))]
        return f"{hit[0]} 그 말이 틀렸어요" if hit else "잘 모르겠어요"
    if qid == "station":
        st_ = near(x, y, 1200, lambda i: W.kind[i] == "역")
        return f"{say(W.name[st_[0]])} 근처예요" if st_ else "역은 잘 모르겠어요"
    # where · mark · finer: 60m 안에 보이는 가장 가까운 간판 · 건물(이미 말한 것은 빼고)
    pred = (lambda i: VISIBLE(i) and W.kind[i] in gaz.ROADSIDE) if c["cat"] == "자동차전용도로" else VISIBLE     # 자동차전용도로에서는 차에서 보이는 큰 표지만
    seen = [i for i in near(x, y, 40 if road else 60, pred) if W.name[i] not in view["chips"] and not any(W.name[i] in ch for ch in view["chips"])]
    if seen:
        d = math.hypot(W.x[seen[0]] - x, W.y[seen[0]] - y)
        return f"{say(W.name[seen[0]])} {HOW(d)}"
    th = [i for i in near(x, y, 30, lambda i: W.kind[i] in THINGS) if not any(W.kind[i] in ch for ch in view["chips"])]
    if th:                                                # 이름 붙은 것이 없으면 둘레의 시설을 종류로 댄다
        return f"{W.kind[th[0]]} 옆이에요"
    return "다른 건 잘 안 보여요"


def run(c, rng, solar=None):
    solar = SOLAR if solar is None else solar
    st, view = S.turn({"id": f"sim-{c['id']}"}, {"line": {"who": "상담사", "text": "민원 콜센터입니다. 무엇을 도와드릴까요?"}})
    said, log, code_ms, model_sec, wrong, secs = first_words(c), [], [], [], 0, 0
    if c.get("style") == "단서 여럿":                     # 한 문장에 단서 여럿: 첫 말에 자리 + 둘레에 보이는 이름 하나
        seen = near(c["x"], c["y"], 60 if c["cat"] not in ON_ROAD else 150, (lambda i: VISIBLE(i) and W.kind[i] in gaz.ROADSIDE) if c["cat"] == "자동차전용도로" else VISIBLE)
        if seen:
            said = said.replace("인데요, ", f"인데요, {W.name[seen[0]]} {HOW(math.hypot(W.x[seen[0]] - c['x'], W.y[seen[0]] - c['y']))}. ", 1)
    if c.get("style"):
        c["wrong"] = wrong_name(c, [])
    mis = []
    before = []
    for _ in range(ARG("--turns", L.LOCCAP + 4)):        # 한 통화의 주고받기 상한: 위치 질문 상한 + 4(상한 8이면 12 · 10이면 14, 47번에서 잰 그대로)
        hist0 = len(st.get("history") or [])
        st, fast = S.turn(st, {"line": {"who": "시민", "text": said}})
        for true, heard in c.pop("pend", []):             # (--sound) 틀리게 말한 이름이 이 차례에 새 단서로 이어졌나: 참 이름을 담은 새 칩이 있으면 「이음」
            new = [gaz.norm(x) for x in fast["chips"] if x and x not in before]
            c.setdefault("linked", []).append(any(gaz.norm(true) in x or (len(x) >= 3 and x in gaz.norm(true)) for x in new))
        before = list(fast["chips"])
        code_ms.append(fast["read_sec"] * 1000 + fast["calc_ms"])
        view = fast
        if solar:
            st, view = S.turn(st, {"phase": "model"})
            model_sec.append(view["read_sec"])
        q = view["question"]
        if c.get("on_turn"):                              # 사례 도구가 차례마다 보는 것(tools/defect_set.py: 그 말 뒤 범위에 참 위치가 드나)
            c["on_turn"](c, st, view, said)
        if c.get("style"):
            mis += [(len(log), x) for x in mismatch(view, hist0)]
        log.append({"said": said, "m": (view["size"] or {}).get("m"), "next": q and q["id"], **({"code_next": (fast["question"] or {}).get("id"), "chips": view["chips"]} if c.get("style") else {})})
        if view["confirmed"] or q is None:
            break
        if q["id"] == "handoff":                          # 솔직한 끝(CALL_ON=loop): 자리를 정하지 못한 채 넘긴다
            break
        st, view = S.turn(st, {"line": {"who": "상담사", "text": q["say"]}})
        secs += SEC.get(q["id"], 10)
        if q["id"] == "confirm" and "loop" in L.ON:     # 「아니요」 뒤 새 위치 단서(! 없는 위치 질문) 없이 같은 확인으로 돌아가면 안 된다(33번 1-1)
            al = st.get("asked_log") or []
            rej = [i for i, a in enumerate(al) if a in ("confirm!", "check!")]
            if rej and not any(a in L.LOCQ for a in al[rej[-1] + 1:]):
                c["loop_violation"] = True
        said = answer(c, q, view, rng, st, len(log))
        if said.startswith("아니요"):
            wrong += 1
    road = c["cat"] in ON_ROAD
    handoff = bool(view.get("question")) and view["question"]["id"] == "handoff"
    out = {"id": c["id"], "handoff": handoff, "cat": c["cat"], "type": c["type"], "noisy": c["noisy"], "turns": len(log), "confirmed": bool(view["confirmed"]), "wrong_confirm": wrong, "narrowed": bool(view["confirmed"] and view["done"]),
           "code_ms": max(code_ms), "secs": secs, "asked": [l["next"] for l in log if l["next"]], "model_sec": statistics.mean(model_sec) if model_sec else None, "log": log, "first": first_words(c),
           "where": view["summary"]["where"], "bias": c.get("bias", False), "d_land": round(c["d_land"]), "d_osm": round(c["d_osm"]), "linked": c.get("linked", []), "x": round(c["x"], 1), "y": round(c["y"], 1)}
    if view["center"]:
        cx, cy = gaz.xy(*((view.get("pin") or {}).get("at") or view["center"]))      # 확정한 점: 핀이 있으면 핀, 없으면 범위의 가운데
        out["err_m"] = round(math.hypot(float(cx) - c["x"], float(cy) - c["y"]))
        out["seg_m"] = (view["size"] or {}).get("m") if (view["size"] or {}).get("kind") == "length" else None
        out["hit"] = out["narrowed"] and out["err_m"] <= (120 if road else 60)
        out["bad"] = out["narrowed"] and not out["hit"]
        if out["narrowed"] and road and out["seg_m"] and out["seg_m"] > 200:     # (road400) 200m 넘는 구간으로 좁혀 끝냄: 「구간」으로 세고, 참 위치가 구간 밖이면 틀린 확정
            inside_seg = out["err_m"] <= out["seg_m"] / 2 + 20
            out["hit"], out["bad"], out["end"] = False, False, "구간" if inside_seg else "구간(밖)"
            out["bad_range"] = not inside_seg
        reg = view.get("region")                          # 다섯 칸(33번 0-2): 점 · 구간 · 넓은 범위 · 솔직한 끝 · 틀린 확정
        if out["confirmed"] and not out["narrowed"]:
            if reg:
                inside, wide = bool(L.in_ring(np.array([c["x"]]), np.array([c["y"]]), L.area_of(reg)["ring"])[0]), True
            elif out["seg_m"]:
                inside, wide = out["err_m"] <= out["seg_m"] / 2 + 20, out["seg_m"] > 400
            else:
                inside, wide = out["err_m"] <= max(60, view["radius"] or 0), (view["radius"] or 0) > 150
            out["end"] = ("넓은 범위" if wide else "구간") + ("" if inside else "(밖)")
            out["bad_range"] = not inside and not wide        # 이름 붙은 기준이 있는 구간으로 끝냈는데 참 위치가 밖: 틀린 확정으로 센다
        truth_ = {"cx": c["x"], "cy": c["y"], "on_road": road, "ctx": {"roads": [i for i, r in enumerate(G.roads) if r["name"] == c.get("road")][:1]}}
        want = S.route_of({"type": c["type"], "animal": "개" if c["type"] in ("stray", "carcass") else None}, truth_)["hit"]["to"]
        out["dept_ok"] = bool(view["route"]) and view["route"]["hit"]["to"] == want
    out["end"] = out.get("end") or ("점" if out.get("hit") else "틀린 확정" if out.get("bad") else "솔직한 끝" if handoff else "못 끝냄")
    if "--route" in sys.argv:
        route_share(c, st, out)
    if c.get("style"):
        gone = [x for x in (c.get("wrong") if c.get("retracted") else None, c.get("flipped")) if x]     # 시민이 실제로 거둔 말만
        mis += [(len(log), "거둔 말이 단서에 남음: " + x) for x in gone if any(gaz.norm(x) in gaz.norm(ch) for ch in view["chips"])]
        out.update(style=c["style"], want=c.get("want"), mis=mis, wrong_said=c.get("wrong"), flipped=c.get("flipped"), half=c.get("half"),
                   met=(out["end"] == "점") if c.get("want") == "맞는 자리" else out["end"] not in ("틀린 확정", "구간(밖)"))
    return out


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


def table(res):
    lines = ["| 묶음 | 통화 | 참 위치 → 가장 가까운 지명 점 (가운데 · 90%) | 성공 | **틀린 확정** | 범위째 확인 | 못 끝냄 | 주고받기 | 확정한 점의 거리 (가운데 · 90% · 가장 먼 것) | 구간 길이 (가운데 · 90%) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    groups = [(cat, [r for r in res if r["cat"] == cat]) for cat in CATS if any(r["cat"] == cat for r in res)] + [("전체", res)]
    for name, rs in groups:
        ok = [r for r in rs if r["confirmed"]]
        e = [r["err_m"] for r in rs if r["narrowed"]]
        seg = [r["seg_m"] for r in rs if r["narrowed"] and r.get("seg_m")]
        dl = [r["d_land"] for r in rs]
        lines.append(f"| {name} | {len(rs)} | {statistics.median(dl):.0f}m · {q(dl, .9):.0f}m | {sum(1 for r in rs if r.get('hit'))} ({sum(1 for r in rs if r.get('hit')) / len(rs):.0%}) | {sum(1 for r in rs if r.get('bad'))} | "
                     f"{sum(1 for r in ok if not r['narrowed'])} | {len(rs) - len(ok)} | {statistics.mean(r['turns'] for r in rs):.1f} | "
                     + (f"{statistics.median(e):.0f}m · {q(e, .9)}m · {max(e)}m" if e else "—") + " | " + (f"{statistics.median(seg):.0f}m · {q(seg, .9)}m" if seg else "—") + " |")
    return "\n".join(lines)


def table5(res):
    """33번 0-2의 다섯 칸. 「구간」에서 참 위치가 밖이면 틀린 확정으로 센다(「넓은 범위(밖)」은 따로 적는다)."""
    lines = ["| 묶음 | 통화 | 점으로 맞힘 | 구간으로 끝냄 | 넓은 범위로 끝냄 | 솔직한 끝 | 못 끝냄 | **틀린 확정**(점 + 구간) | 넓은 범위인데 밖 | 주고받기 |", "|---|---|---|---|---|---|---|---|---|---|"]
    groups = [(cat, [r for r in res if r["cat"] == cat]) for cat in CATS if any(r["cat"] == cat for r in res)] + [("전체", res)]
    for name, rs in groups:
        n = lambda e: sum(1 for r in rs if r.get("end") == e)     # noqa: E731
        lines.append(f"| {name} | {len(rs)} | {n('점')} | {n('구간')} | {n('넓은 범위')} | {n('솔직한 끝')} | {n('못 끝냄')} | {n('틀린 확정') + n('구간(밖)')} | {n('넓은 범위(밖)')} | {statistics.mean(r['turns'] for r in rs):.1f} |")
    return "\n".join(lines)


def main():
    cases = make_cases(N, ARG("--seed", 1114))
    if "--nick" in sys.argv or "--nick-saved" in sys.argv:
        cases = [c for c in make_cases(N * 3, ARG("--seed", 1114)) if c["cat"] in ("골목 · 상가 길", "공원 안")][:N]
        orng = random.Random(15)
        for k, c in enumerate(cases):
            c["nick"] = NICK_A[k % len(NICK_A)] + NICK_B[(k // len(NICK_A)) % len(NICK_B)]
            if "--nick-saved" in sys.argv:            # 앞선 통화의 핀(참 위치에서 15m)에 별명을 붙여 둔다
                dx, dy = ring_at(orng, 15, 15)
                G.add_alias(c["nick"], *gaz.lonlat(c["x"] + dx, c["y"] + dy))
    if "--extreme" in sys.argv:                           # 사람처럼 말하는 통화 묶음(36번): 갈래마다 고르게, 「방향 · 거리 거꾸로」는 길 위 · 공원 안 통화에서
        pool, cases = make_cases(N * 4, ARG("--seed", 1117)), []
        for k in range(N):
            st_ = STYLES[k % len(STYLES)]
            ok = (lambda c: c["cat"] in ON_ROAD + ("공원 안",)) if st_ == "방향 · 거리 거꾸로" else (lambda c: True)
            c = next(c for c in pool if ok(c) and "style" not in c)
            c.update(style=st_, half="dev" if (k // len(STYLES)) % 2 == 0 else "hold")
            cases.append(c)
        for c in cases:                                   # 바라는 끝: 같은 통화를 말버릇 없이 코드로(Solar 없이) 돌린 결과
            plain = run({k: v for k, v in c.items() if k not in ("style", "half")}, random.Random(f"{ARG('--seed', 1117)}:{c['id']}"), solar=False)
            c["want"] = "맞는 자리" if plain["end"] == "점" else "틀린 확정 없음"
        cases = [c for c in cases if c["half"] == ARG("--half", c["half"])]
    t0 = time.time()
    res = [run(c, random.Random(f"{ARG('--seed', 1114)}:{c['id']}")) for c in cases]      # 통화마다 난수 따로(33번 0-1)
    if "loop" in L.ON:
        assert not any(r.get("loop_violation") for r in res), [r["id"] for r in res if r.get("loop_violation")]
    if "dist" in L.ON:                                   # 거리 답이 다음 표지 이름으로 새면 「○○에서 쉰 걸음쯤에서 쉰 걸음쯤」처럼 같은 질문이 되풀이된다(11-15 아침에 찾은 일)
        leak = [(r["id"], r["where"]) for r in res if "걸음쯤에서" in (r.get("where") or "") or "보이기만" in (r.get("where") or "")]
        assert not leak, leak
    how = f"코드가 읽은 뒤 Solar({S.MODEL})가 다시 읽음" if SOLAR else "코드만으로 읽음(모델 없음)"
    noise = " · ".join(x for x in (f"틀리게 답함 {LIE:.0%}" if LIE else "", f"모른다고 함 {DUNNO:.0%}" if DUNNO else "", f"「네」로 기움 {YES:.0%}" if YES else "") if x)
    data = "오픈스트리트맵 + 상가정보" if os.environ.get("CALL_SHOPS", "1") != "0" else "오픈스트리트맵만(상가정보 넣기 전)"
    print(f"# 가상 통화 {len(res)}개 — {how} · 시스템의 지명 표: {data}" + (f" · 시민: {noise}" if noise else "") + "\n")
    print(table(res))
    print("\n" + table5(res))
    if "--extreme" in sys.argv:
        print("\n| 갈래 | 통화 | 맞는 자리로 확정 | 정직한 끝 | 틀린 확정 | 어긋난 화면(차례) | 바라는 대로 |\n|---|---|---|---|---|---|---|")
        for sty in STYLES + ["전체"]:
            rs = [r for r in res if sty in ("전체", r["style"])]
            if rs:
                bad = sum(1 for r in rs if r["end"] in ("틀린 확정", "구간(밖)"))
                print(f"| {sty} | {len(rs)} | {sum(1 for r in rs if r['end'] == '점')} | {len(rs) - bad - sum(1 for r in rs if r['end'] == '점')} | {bad} | {sum(len(r['mis']) for r in rs)} | {sum(r['met'] for r in rs)}/{len(rs)} |")
        for r in res:
            for t, m in r["mis"]:
                print(f"  어긋남 #{r['id']} {r['style']} {t + 1}번째 말 뒤: {m}")
    cm = [r["code_ms"] for r in res]
    asked = {}
    for r in res:
        for a in r["asked"]:
            asked[a] = asked.get(a, 0) + 1
    bad = [r for r in res if r.get("bad")]
    if bad:
        print("\n틀린 확정: " + " / ".join(f"#{r['id']} {r['cat']} {r['err_m']}m 「{(r['where'] or '')[:40]}」" + (" (시민이 틀린 자리에 「네」)" if r.get("bias") else "") for r in bad))
    if SOUND:
        lk = [v for r in res for v in r["linked"]]
        print(f"\n- 틀리게 말한 이름 {len(lk)}번 가운데 참 이름으로 이은 것 {sum(lk)}번({sum(lk) / max(1, len(lk)):.0%}). 그런 이름이 든 통화 {sum(1 for r in res if r['linked'])}통")
    print(f"\n- 코드가 읽고 질문을 고르기까지(통화마다 가장 느린 차례): 가운데값 {statistics.median(cm):.0f}ms · 가장 느린 것 {max(cm):.0f}ms")
    print("- 뜬 질문: " + " · ".join(f"{k} {v}" for k, v in sorted(asked.items(), key=lambda kv: -kv[1])))
    if SOLAR:
        ms = [r["model_sec"] for r in res if r["model_sec"]]
        print(f"- Solar가 다시 읽는 데 걸린 시간(통화마다 평균): 가운데값 {statistics.median(ms):.2f}초 · 가장 느린 통화 {max(ms):.2f}초 · 호출 {S.usage['read']}번 · 토큰 들어감 {S.usage['tokens_in']:,} · 나옴 {S.usage['tokens_out']:,}")
    print(f"- 걸린 시간 {time.time() - t0:.0f}초")
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    main()
