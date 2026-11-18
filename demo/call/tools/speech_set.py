"""실제 말투 시험 묶음(11-18, 53번): 참 위치를 정해 두고, 사람이 실제로 할 법한 말투로 자리를 말하게 한 뒤 그 뒤 질문에는 가상 시민(sim_calls.py)이 참 위치에서 보이는 대로 답한다.

    python3 demo/call/tools/speech_set.py --half dev [--kind 건너편] [--solar] [--json 파일] [--show]
    (OPENBLAS_NUM_THREADS=1. --solar면 차례마다 Solar 다시 읽기까지 — 엔진 가상 환경의 파이썬과 팀 열쇠)

- 말은 팀이 지어낸 틀이다. 실제 민원 · 실제 사람이 아니다. 본보기는 구청 통화에서 들은 말투(「○○ 사거리에서 ○○ 가는 방향」 · 지나가며 본 것을 다른 곳에서 신고)와 동규가 든 예(더듬기 · 말 바꾸기 · 두루뭉술한 말)다.
- 틀에 넣는 이름은 참 위치에서 실제로 보이는 지명 표의 이름이다. 통화는 「민원 한마디 → (어디쯤인지) → 틀에 맞춘 자리 말 한두 마디 → 가상 시민」 차례로 돈다.
- 갈래마다 dev(고칠 때 보는 반) · hold(끝에 한 번만 돌리는 반)를 씨앗으로 갈랐다.
- 재는 것: ① 자리 말을 다 한 뒤의 범위에 참 위치가 드나(안 · 밖 · 범위 없음) ② 끝(점 · 넓은 범위 · 솔직한 끝 · 못 끝냄 · 틀린 확정) ③ 「못 찾은 이름」 되묻기 수
  ④ 같은 참 위치를 가상 통화의 보통 틀(「○○ 쪽인데요」)로 말했을 때의 끝(견줄 기준).
"""
import json
import math
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_calls as SC        # noqa: E402

S, L, G, gaz, np = SC.S, SC.L, SC.G, SC.gaz, SC.np
ARG = SC.ARG
SEEDS = {"dev": 5301, "hold": 5302}
PER = ARG("--per", 5)          # 갈래 · 반마다 통화 수
FACIL = ("주민센터", "우체국", "파출소", "지구대", "초등학교", "중학교", "고등학교", "도서관", "소방서", "보건소", "성당")     # 동 이름 없이 흔히 말하는 시설 낱말
CATW = {"편의점": "편의점", "카페": "카페", "약국": "약국", "은행": "은행", "종교시설": "교회", "학교": "학교", "마트": "마트", "빵집": "빵집", "주유소": "주유소"}


def has_final(word):
    c = ord(word[-1]) - 0xAC00
    return (0 <= c < 11172 and c % 28 != 0) or word[-1] in "136780LMNRlmnr"


def j(word, a, b):
    """받침에 맞는 토씨: j("농협", "이", "가") → 「농협이」."""
    return word + (a if has_final(word) else b)


def how(d):
    return "바로 앞이에요" if d <= 12 else "옆이에요" if d <= 25 else "근처예요"


def single(i):
    """이름 하나로 자리가 서는 곳인가: 서울에 그 이름이 한 곳(40m 안에 모인 것)뿐이고, 시스템이 이름으로 받아 주는 꼴."""
    key = gaz.norm(G.name[i])
    r = L.resolve(key)
    return len(r["x"]) >= 1 and float(np.ptp(r["x"]) + np.ptp(r["y"])) <= 40 and not r["roads"] and not r["areas"] and bool(G.mentions(G.name[i] + " 앞이에요"))


def marks(c, rad=60, lo=0):
    """참 위치에서 lo~rad m 안의, 이름 하나로 자리가 서는 곳들 → [(거리, 번호)] 가까운 순."""
    out = [(math.hypot(G.x[i] - c["x"], G.y[i] - c["y"]), i) for i in SC.near(c["x"], c["y"], rad) if 4 <= len(G.name[i]) <= 14 and single(i)]
    return [(d, i) for d, i in out if d >= lo]


def station(c, lo=150, hi=900):
    """참 위치에서 lo~hi m 안의 가장 가까운 지하철 출구(이름 하나로 서는 것) → (거리, 번호) 또는 None."""
    ex = [(math.hypot(G.x[i] - c["x"], G.y[i] - c["y"]), i) for i in SC.near(c["x"], c["y"], hi, lambda i: G.kind[i] == "역 출구")]
    ex = [(d, i) for d, i in ex if d >= lo]
    return ex[0] if ex else None


def far_place(c, rng, lo=3000, hi=9000, kind="역"):
    cand = [i for i in SC.near(c["x"], c["y"], hi, lambda i: G.kind[i] == kind and 3 <= len(G.name[i]) <= 7) if math.hypot(G.x[i] - c["x"], G.y[i] - c["y"]) >= lo]
    return G.name[rng.choice(cand)] if cand else None


def wrong(c, rng):
    cand = [i for d, i in marks(c, 700, 250)]
    return G.name[rng.choice(cand)] if cand else None


# ---- 갈래마다: (참 위치 c, 난수) → 자리 말 [한 마디 또는 두 마디] 또는 None(이 자리에서는 그 말을 할 수 없다)
def k_stutter(c, rng):
    m = marks(c)
    if not m:
        return None
    d, i = m[0]
    n, cut = G.name[i], G.name[i][:2]
    return [rng.choice([f"어… 그… {cut}, {n} 있잖아요, 그 {how(d)}", f"그 뭐지… {cut}… {n}요, {n} {how(d)}", f"{c['dong']}인데요, 어… 저기 {cut}, {n} 있는 데 {how(d)}"])]


def k_filler(c, rng):
    m = [(d, i) for d, i in marks(c) if " " in G.name[i]]
    if not m:
        return None
    d, i = m[0]
    a, b = G.name[i].split(" ", 1)
    return [rng.choice([f"{a} 어… 그… {b} 음… {how(d)}", f"음… 그러니까 {a} 그 뭐지 {b}, 거기 {how(d)} 아마 그럴 거예요."])]


def k_fix_same(c, rng):
    """한 말 안에서 이름을 고침(「아니다 · 말고」가 이름 바로 뒤에 오지 않는 꼴)."""
    m, w = marks(c), wrong(c, rng)
    if c.get("exit") and rng.random() < 0.6:               # 출구 번호만 고침: 「2번 출구요. 아 잠깐만요, 3번이네요」
        mm = re.match(r"^(.+역) (\d+)번 출구$", c["exit"])
        others = [n for n in range(1, 13) if mm and str(n) != mm.group(2) and gaz.norm(f"{mm.group(1)} {n}번 출구") in G.ix]
        if mm and others:
            n2 = rng.choice(others)
            return [f"{mm.group(1)} {n2}번 출구요. 아 잠깐만요, {mm.group(2)}번이네요. {mm.group(2)}번 출구 {how(c['ad'])}"]
    if not m or not w:
        return None
    d, i = m[0]
    n = G.name[i]
    return [rng.choice([f"{w} 앞이요. 아 잠깐만요, {j(w, '이', '가')} 아니라 {j(n, '이에요', '예요')}. {n} {how(d)}", f"{j(w, '이요', '요')}. 아니 죄송해요, 다시 보니까 {j(n, '이네요', '네요')}. {n} {how(d)}"])]


def k_fix_next(c, rng):
    """다음 차례에 고침: 「X가 아니라 Y」."""
    m, w = marks(c), wrong(c, rng)
    if not m or not w:
        return None
    d, i = m[0]
    n = G.name[i]
    return [f"{w} 근처예요.", rng.choice([f"아 죄송해요, {j(w, '이', '가')} 아니라 {n} {how(d)}", f"아니다, 제가 헷갈렸네요. {w} 말고 {n} {how(d)}"])]


def k_across(c, rng):
    m = marks(c, 45, 25)
    if not m:
        return None
    d, i = m[0]
    n = G.name[i]
    return [rng.choice([f"{n} 건너편이에요.", f"{n} 맞은편이요.", f"{n} 앞이요. 아, 아니다 그 건너편이요."])]


def k_vague(c, rng):
    th = SC.near(c["x"], c["y"], 60, lambda i: G.kind[i] in CATW)
    if not th or not c.get("dong"):
        return None
    w = CATW[G.kind[th[0]]]
    return [rng.choice([f"{j(c['dong'], '이에요', '예요')}. 그 {w} 있는 데요.", f"{c['dong']} 쪽인데, 그 큰길 있잖아요, {w} 옆 골목이에요.", f"{c['dong']}인데요, 그냥 골목이에요. {j(w, '이', '가')} 하나 보여요."])]


def k_facility(c, rng):
    """동 이름 없이 흔한 시설 낱말로: 「○○동인데요, 주민센터 앞이에요」."""
    f = c.get("facil")
    if not f:
        return None
    st = station(c, 50, 800)
    if st and rng.random() < 0.4:                         # 동 대신 가까운 역으로 둘레를 말함
        return [f"{G.name[st[1]].split(' ')[0]} 근처인데요, {f['word']} {how(f['d'])}"]
    return [rng.choice([f"{c['dong']}인데요, {f['word']} {how(f['d'])}", f"{j(c['dong'], '이에요', '예요')}. 그 {f['word']} 있잖아요, 거기 {how(f['d'])}"])]


def k_elsewhere(c, rng):
    """지금 있는 곳과 본 곳이 다름(구청 통화: 지나가며 본 것을 다른 곳에서 신고)."""
    m, far = marks(c), far_place(c, rng)
    if not m or not far:
        return None
    d, i = m[0]
    n = G.name[i]
    return [rng.choice([f"지금은 {far} 근처 회사인데요, 아침에 {n} 앞 지나다가 봤어요.", f"저는 지금 {far} 쪽에 와 있는데요, 아까 {c['dong']} {n} 근처에서 봤거든요.", f"지금 집에 와서 전화하는 건데요, 집은 {far} 쪽이고요. 아까 {n} {how(d).replace('이에요', '에서 봤어요').replace('예요', '에서 봤어요')}"])]


def k_story(c, rng):
    """사설이 길고 다른 동네 이야기가 섞임."""
    m, far = marks(c), far_place(c, rng, 3000, 9000, "동네") or far_place(c, rng)
    if not m or not far:
        return None
    d, i = m[0]
    n = G.name[i]
    return [rng.choice([f"제가 지난달에 {far}에서도 이런 걸 봐서 신고했었거든요. 그때는 금방 오셨는데요. 이번에는 {c['dong']}인데, {n} {how(d)}",
                        f"아니 제가 원래 이런 거 신고 잘 안 하는데요, 어제도 봤거든요. 우리 애가 {far} 학원 갔다 오다가 보고 그래서요. 그 {n} 있잖아요, {c['dong']}에, 그 {how(d)}"])]


def k_fromto(c, rng):
    """「A에서 B 가는 방향」(걷는 사람): A = 지나온 쪽의 출구, B = 가는 쪽으로 더 가면 나오는 역."""
    a = station(c, 120, 600)
    if not a:
        return None
    da, ia = a
    ux, uy = (c["x"] - G.x[ia]) / da, (c["y"] - G.y[ia]) / da
    ahead = [(math.hypot(G.x[i] - c["x"], G.y[i] - c["y"]), i) for i in SC.near(c["x"], c["y"], 1800, lambda i: G.kind[i] == "역" and 3 <= len(G.name[i]) <= 8)
             if 200 <= math.hypot(G.x[i] - c["x"], G.y[i] - c["y"]) and ((G.x[i] - c["x"]) * ux + (G.y[i] - c["y"]) * uy) / math.hypot(G.x[i] - c["x"], G.y[i] - c["y"]) >= 0.8
             and G.name[i].split(" ")[0] not in G.name[ia]]
    if not ahead:
        return None
    b, an = G.name[ahead[0][1]], G.name[ia]
    return [rng.choice([f"{an}에서 {b} 가는 방향이요.", f"{an}에서 {b} 쪽으로 올라가는 길이에요.", f"{an} 나와서 {b} 가는 방향으로 좀 걸어왔어요."])]


def k_walk(c, rng):
    """「A에서 걸어서 N분」: 걸음 1분 = 약 70m, 걸은 길은 곧은 거리 ÷ 0.75(33번 2-6의 값), 사람의 어림은 ±30%쯤 흔들린다고 둔다(짐작)."""
    a = station(c, 150, 700)
    if not a:
        return None
    da, ia = a
    n = max(2, round(da / 0.75 * math.exp(rng.gauss(0, 0.3)) / 70))
    return [rng.choice([f"{G.name[ia]}에서 걸어서 {n}분쯤 온 데예요.", f"{G.name[ia]}에서 {n}분 정도 걸어왔어요.", f"{G.name[ia]} 나와서 한 {n}분 걸었어요."])]


def k_branch(c, rng):
    """상표와 지점 이름을 따로 말함: 「GS25 앞이요. 상도래미안점이요」."""
    for d, i in [(math.hypot(G.x[i] - c["x"], G.y[i] - c["y"]), i) for i in SC.near(c["x"], c["y"], 60, lambda i: bool(G.brand[i]))]:
        mm = re.match(r"^(\S+) (\S+점)$", G.name[i])
        if mm and gaz.norm(mm.group(1)) == gaz.norm(G.brand[i]) and len(L.resolve(gaz.norm(G.name[i]))["x"]) == 1:
            return [rng.choice([f"{mm.group(1)} {how(d).replace('이에요', '이요').replace('예요', '요')} {mm.group(2)}이요.", f"{mm.group(1)} 있잖아요, {mm.group(2)}. 그 {how(d)}"])]
    return None


KINDS = [("더듬기", k_stutter), ("군말", k_filler), ("한 말 안에서 고침", k_fix_same), ("다음 차례에 고침", k_fix_next), ("건너편", k_across), ("두루뭉술", k_vague), ("동 이름 없는 시설", k_facility),
         ("지금 있는 곳과 본 곳", k_elsewhere), ("사설 속 다른 동네", k_story), ("A에서 B 가는 방향", k_fromto), ("걸어서 몇 분", k_walk), ("상표와 지점 따로", k_branch)]


def facility_cases(rng, n):
    """흔한 시설(주민센터 · 초등학교 …)에서 8~35m 떨어진 참 위치. 낱말은 그 시설 이름의 끝."""
    idx = [(i, w) for i in range(G.shop0) for w in FACIL if G.name[i].endswith(w) and len(G.name[i]) > len(w) + 1 and G.kind[i] in ("관공서", "학교", "경찰", "소방서", "문화시설", "종교시설", "병원", "시설", "건물")]
    out = []
    for i, w in rng.sample(idx, min(len(idx), n * 6)):
        dx, dy = SC.ring_at(rng, 8, 35)
        x, y = float(G.x[i]) + dx, float(G.y[i]) + dy
        dong = L._area_at(G.dong, x, y)
        if dong and len(out) < n:
            out.append({"cat": "골목 · 상가 길", "type": rng.choice(("litter", "light", "parking", "noise")), "x": x, "y": y, "dong": dong, "facil": {"word": w, "name": G.name[i], "d": math.hypot(dx, dy)}})
    return out


def build(half):
    seed = SEEDS[half]
    rng = random.Random(seed)
    pool = [c for c in SC.make_cases(420, seed) if c["cat"] in ("골목 · 상가 길", "프랜차이즈 둘레", "역 출구 둘레")]
    for c in pool:
        c["dong"] = L._area_at(G.dong, c["x"], c["y"]) or c.get("dong")
    rng.shuffle(pool)
    cases, used = [], set()
    for kind, fn in KINDS:
        src = facility_cases(random.Random(f"{seed}:facil"), PER * 3) if kind == "동 이름 없는 시설" else pool
        got = 0
        for c in src:
            if got >= PER or id(c) in used or not c.get("dong"):
                continue
            lines = fn(c, random.Random(f"{seed}:{kind}:{c['x']:.0f}"))
            if not lines:
                continue
            used.add(id(c))
            got += 1
            cases.append(dict(c, kind=kind, half=half, lines=lines))
    for n, c in enumerate(cases, 1):
        idx = G.near(c["x"], c["y"], 400)
        d = np.hypot(G.x[idx] - c["x"], G.y[idx] - c["y"]) if len(idx) else np.array([400.0])
        c.update(id=7000 + n + (500 if half == "hold" else 0), noisy=False, d_land=float(d.min()), d_osm=float(d.min()), gu=L._area_at(G.gu, c["x"], c["y"]))
    return cases


def watch(c, st, view, said):
    clues, _ = S.understood(st)
    R = L.infer(clues) if clues else None
    row = {"said": said, "q": (view.get("question") or {}).get("id"), "m": (view.get("size") or {}).get("m"), "chips": list(view.get("chips") or []), "unfound": view.get("unfound"), "inside": None, "off": None}
    if R is not None:
        px, py = R["x"][R["cred"]], R["y"][R["cred"]]
        row.update(inside=bool(np.hypot(px - c["x"], py - c["y"]).min() <= 45), off=round(math.hypot(R["cx"] - c["x"], R["cy"] - c["y"])))
    c.setdefault("trace", []).append(row)


_answer = SC.answer


def answer(c, q, view, rng, st, turn=0):
    """자리 말이 남아 있으면 위치를 묻는 질문에 그 말로 답한다(일의 질문은 가상 시민이 답한다)."""
    if c.get("script") and (q["id"] in L.LOCQ or q["id"] == "where"):
        c["scripted"] = c.get("scripted", 0) + 1
        return c["script"].pop(0)
    return _answer(c, q, view, rng, st, turn)


SC.answer = answer


def one(c, plain=False):
    c = dict(c)
    c.pop("trace", None)
    if plain:                                             # 견줄 기준: 같은 참 위치를 가상 통화의 보통 틀로
        c = {k: v for k, v in c.items() if k not in ("kind", "lines", "facil")}
        return SC.run(c, random.Random(f"speech:{c['id']}"), solar=False)
    c.update(first=SC.SAY[c["type"]] + ".", script=list(c["lines"]), on_turn=watch)
    r = SC.run(c, random.Random(f"speech:{c['id']}"))
    tr = c.get("trace") or []
    k = next((n for n in range(len(tr) - 1, -1, -1) if tr[n]["said"] in c["lines"]), None)      # 마지막 자리 말을 한 차례
    at = tr[k] if k is not None else {}
    r.update(kind=c["kind"], lines=c["lines"], after="범위 없음" if at.get("inside") is None else "안" if at["inside"] else "밖", after_m=at.get("m"), after_off=at.get("off"), after_chips=at.get("chips"),
             again=sum(1 for t in tr if t["q"] == "again"), trace=tr)
    return r


def main():
    half = ARG("--half", "dev")
    cases = [c for c in build(half) if c["kind"] == ARG("--kind", c["kind"])]
    if "--show" in sys.argv:
        for c in cases:
            print(f"{c['id']} [{c['kind']}] {c['cat']} · {c['dong']} → {' / '.join(c['lines'])}")
        return
    out = []
    for c in cases:
        r = one(c)
        r["plain_end"] = one(c, plain=True)["end"] if "--noplain" not in sys.argv else None
        out.append(r)
        bad = r["end"] in ("틀린 확정", "구간(밖)")
        print(f"{'✗' if bad or r['after'] == '밖' else '△' if r['after'] == '범위 없음' or r['again'] else '✓'} {r['id']} [{r['kind']}] 자리 말 뒤 {r['after']}({r['after_m']}m, 가운데 {r['after_off']}m) · 끝 {r['end']}({r.get('err_m')}m) · 보통 틀이면 {r['plain_end']} · 되묻기 {r['again']}\n"
              f"    「{' / '.join(r['lines'])}」 → 단서 {r['after_chips']} → 질문 {' → '.join(r['asked'])}")
    print("\n| 갈래 | 통화 | 자리 말 뒤: 안 · 밖 · 범위 없음 | 끝: 점 · 넓은 범위 · 솔직한 끝 · 못 끝냄 · **틀린 확정** | 보통 틀이면 점 | 「못 찾은 이름」 되묻기 | 주고받기 |\n|---|---|---|---|---|---|---|")
    for kind in [k for k, _ in KINDS] + ["전체"]:
        rs = [r for r in out if kind in ("전체", r["kind"])]
        if rs:
            n = lambda f: sum(1 for r in rs if f(r))      # noqa: E731
            print(f"| {kind} | {len(rs)} | {n(lambda r: r['after'] == '안')} · {n(lambda r: r['after'] == '밖')} · {n(lambda r: r['after'] == '범위 없음')} | {n(lambda r: r['end'] == '점')} · {n(lambda r: r['end'].startswith('넓은 범위'))} · "
                  f"{n(lambda r: r['end'] == '솔직한 끝')} · {n(lambda r: r['end'] == '못 끝냄')} · **{n(lambda r: r['end'] in ('틀린 확정', '구간(밖)'))}** | {n(lambda r: r['plain_end'] == '점')} | {sum(r['again'] for r in rs)} | {sum(r['turns'] for r in rs) / len(rs):.1f} |")
    if SC.SOLAR:
        print(f"\nSolar 다시 읽기 {S.usage['read']}번 · 토큰 들어감 {S.usage['tokens_in']:,} · 나옴 {S.usage['tokens_out']:,}")
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
