"""사람이 해 보는 시험: 팀원(민원인 역)이 카드에 적힌 「지나가며 본 것」만으로 전화하듯 말하고, 상담사 역은 화면으로 그 자리를 찾는다.
서비스 화면은 그대로다. 기록은 `?trial=번호` 주소에서 뜨는 「시험 기록 남기기」 단추가 data/trials_local.jsonl에 남긴다(git 무시).

    python3 demo/call/tools/human_test.py cards [--seed 1117] [--port 8774] [--out <폴더>]   카드 10장 → 카드-동욱.md · 카드-종희.md · 카드-건영.md · 상담사-주소.md · trials.json(참 위치)
    python3 demo/call/tools/human_test.py truth <번호> "<위도, 경도 또는 구글 · 카카오 지도 주소>"   통화 뒤 참 위치 한 줄 → truth.json (지인 방식, 11-15)
    python3 demo/call/tools/human_test.py score [--out <폴더>] [--log <trials_local.jsonl>]     → 결과.md · 결과.csv
    python3 demo/call/tools/human_test.py selftest

- 자리는 가상 통화(sim_calls.py)와 같은 뽑기에서 큰길 2 · 골목 2 · 공원 안 3 · 자동차전용도로 3을 고른다.
- 카드는 지나가며 본 사람이 알 만큼만 쓴다: 가게는 큰 간판(상표)만, 작은 가게는 「편의점 하나」 · 「식당」처럼 종류로, 다리 · 역 이름은 「~였던 것 같다」로.
  시스템 지명 표의 이름을 다 적으면 시험이 실제보다 쉬워진다.
- 기본 폴더는 레포 밖(레포 옆 _data/human-test/) (참 위치가 든 파일을 상담사 역이 보지 않게, 레포에 올리지 않게).
- 결과 칸: 한 점(맞음 · 틀림) · 구간(안 · 밖) · 넓은 범위(안 · 밖) · 솔직한 끝 · 못 끝냄, 오차(m), 질문 수, 걸린 시간, 못 읽힌 말.
  한 점이 맞은 기준은 가상 통화와 같다: 참 위치에서 60m(길 위 120m) 안.
"""
import csv
import importlib.util
import re
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ARG = lambda name, default: type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default   # noqa: E731
OUT = Path(ARG("--out", str(HERE.parents[1].parent / "_data" / "human-test"))).expanduser()
ON_ROAD = ("자동차전용도로", "큰길")
WANT = [("큰길", 2), ("골목 · 상가 길", 2), ("공원 안", 3), ("자동차전용도로", 3)]
WANT_CATS = tuple(c for c, _ in WANT)
PEOPLE = {"동욱": (1, 4, 7, 10), "종희": (2, 5, 8), "건영": (3, 6, 9)}
NAMED_KINDS = ("학교", "아파트", "병원", "역", "역 출구", "다리", "공원", "시장", "관공서", "종교시설")      # 지나가는 사람도 이름을 아는 큰 것
KIND_WORD = {"편의점": "편의점", "카페": "카페", "음식점": "식당", "빵집": "빵집", "약국": "약국", "은행": "은행", "마트": "마트", "숙박": "모텔 · 호텔 같은 건물",
             "주유소": "주유소", "정류장": "버스 정류장", "주차장": "주차장", "화장실": "공중화장실", "놀이터": "놀이터", "정자": "정자", "운동기구": "운동기구",
             "음수대": "음수대", "분수": "분수", "물가": "호수 · 연못", "광장": "넓은 광장 · 잔디밭", "숲": "나무가 우거진 숲", "산책길": "산책길", "학원": "학원"}
DUNNO = re.compile(r"모르|못 ?봤|아뇨|아니요|없어|없었|기억 ?(이 )?안|글쎄")
LOC_Q = {"where", "zone", "between", "passed", "mark", "finer", "near", "dir", "station", "ago", "seen", "either", "lampno", "from", "next", "dist", "closest", "mark_again"}


def _sim():
    """가상 통화 도구의 자리 뽑기 · 시민 세상(W)을 그대로 쓴다(sim_calls는 가져올 때 sys.argv를 읽으므로 잠시 비운다)."""
    argv, sys.argv = sys.argv, [sys.argv[0]]
    try:
        spec = importlib.util.spec_from_file_location("sim_calls", HERE / "tools" / "sim_calls.py")
        sim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sim)
    finally:
        sys.argv = argv
    return sim


def heading_word(sim, c):
    hx, hy = c["head"]
    names = sim.L.DIR_NAMES.get(c["road"])
    if names:
        return names[0] if (hx > 0 if abs(hx) >= abs(hy) else hy > 0) else names[1]
    return ("동쪽" if hx > 0 else "서쪽") if abs(hx) >= abs(hy) else ("북쪽" if hy > 0 else "남쪽")


def how_far(d):
    return "바로 앞" if d <= 12 else "몇 걸음 옆" if d <= 25 else "스무 걸음쯤" if d <= 45 else "조금 떨어진 곳"


BIG_SIGN = re.compile(r"(대교|IC|나들목|JC|분기점|터널)$")      # 운전자가 표지판으로 아는 이름
TECH = re.compile(r"고가교|보도육교|IC교|하단|상단|램프|유수지|\d")    # 관리용 시설 이름(운전자는 모른다)
_BRANDS = {}


def thing_word(W, i):
    """지나가는 사람이 그 곳을 부를 말: 서울에 흔한 큰 간판(상표 20곳 넘게)이나 다 아는 큰 것만 이름, 나머지는 종류."""
    if not _BRANDS:
        for b in W.brand:
            if b:
                _BRANDS[b] = _BRANDS.get(b, 0) + 1
    if W.brand[i] and _BRANDS.get(W.brand[i], 0) >= 20:
        return W.brand[i]
    if W.kind[i] in NAMED_KINDS:
        return W.name[i]
    return KIND_WORD.get(W.kind[i])


def card_lines(sim, c):
    """카드 한 장의 「어디쯤」 · 「본 것」 줄들."""
    W, x, y = sim.W, c["x"], c["y"]
    near = lambda r, pred: sorted((i for i in W.near(x, y, r) if pred(int(i))), key=lambda i: math.hypot(W.x[i] - x, W.y[i] - y))     # noqa: E731
    station = next(iter(near(1200, lambda i: W.kind[i] == "역")), None)
    st_word = f"가까운 지하철역은 아마 「{W.name[station]}」(걸어서 몇 분인지는 모름)" if station is not None else "가까운 지하철역은 모름"
    where, seen = [], []
    if c["cat"] == "자동차전용도로":
        h = c["head"]
        where.append(f"「{c['road']}」를 차로 달리던 중이었다. {heading_word(sim, c)}으로 가고 있었다. 운전 중이라 둘레를 자세히 못 봤다.")
        import numpy as np
        line = np.vstack([sim.G.road_xy(k) for k, r in enumerate(sim.G.roads) if r["name"] == c["road"]])
        on_road = lambda i: float(np.hypot(line[:, 0] - W.x[i], line[:, 1] - W.y[i]).min()) <= 150      # noqa: E731  그 길에서 지나는 것만
        passed = [i for i in near(4000, lambda i: W.kind[i] in ("다리", "나들목", "터널") and BIG_SIGN.search(W.name[i]) and not TECH.search(W.name[i]) and on_road(i)) if (x - W.x[i]) * h[0] + (y - W.y[i]) * h[1] > 30]
        if passed:
            i = passed[0]
            d = math.hypot(W.x[i] - x, W.y[i] - y)
            when = "막 지나자마자" if d < 300 else "지나고 조금 뒤" if d < 900 else "지나고 1~2분쯤 뒤" if d < 2000 else "지나고 몇 분 뒤"
            josa = "이었던" if (ord(W.name[i][-1]) - 0xAC00) % 28 else "였던"      # 받침이 있으면 「분기점이었던」
            where.append(f"그 전에 {W.kind[i]} 하나를 지났다. 이름은 「{W.name[i]}」{josa} 것 같은데 자신은 없다. 본 때는 {when}.")
        else:
            where.append("다리나 나들목 이름은 기억나지 않는다.")
        where.append("가로등 번호 · 표지판 번호는 못 봤다.")
    elif c["cat"] == "큰길":
        where.append(f"「{c['road']}」 큰길 가 인도를 걸어가다 봤다. 길 이름은 버스 정류장 이름에서 본 것 같다. {st_word}.")
    elif c["cat"] == "공원 안":
        where.append(f"「{c['park']}」 안을 산책하다 봤다. 공원 어느 쪽인지는 잘 모른다.")
    else:
        where.append(f"「{c.get('dong') or '어느 동'}」 쪽 골목을 걸어가다 봤다. 동 이름은 대충 안다. {st_word}.")
    pred = (lambda i: sim.VISIBLE(i) and W.kind[i] in sim.gaz.ROADSIDE and BIG_SIGN.search(W.name[i]) and not TECH.search(W.name[i])) if c["cat"] == "자동차전용도로" else (lambda i: thing_word(W, i) is not None and W.kind[i] not in ("동네", "산"))
    used = set()
    for i in near({"자동차전용도로": 150, "공원 안": 100}.get(c["cat"], 60), pred):
        w = thing_word(W, i) if c["cat"] != "자동차전용도로" else W.name[i]
        if not w or w in used:
            continue
        used.add(w)
        seen.append(f"{w} — {how_far(math.hypot(W.x[i] - x, W.y[i] - y))}")
        if len(seen) >= 3:
            break
    return where, seen or ["눈에 띄는 간판이나 건물은 기억나지 않는다"]


def cards():
    sim = _sim()
    seed, port = ARG("--seed", 1117), ARG("--port", 8774)
    pool, picked = sim.make_cases(240, seed), []
    for cat, n in WANT:
        picked += [c for c in pool if c["cat"] == cat][:n]
    order = [picked[k] for k in (0, 2, 4, 5, 7, 1, 8, 6, 9, 3)]          # 사람마다 묶음이 섞이게(동욱 큰길 · 공원 · 자동차 · 골목, 종희 골목 · 자동차 · 공원, 건영 공원 · 큰길 · 자동차)
    OUT.mkdir(parents=True, exist_ok=True)
    trials = []
    for n, c in enumerate(order, 1):
        lon, lat = sim.gaz.lonlat(c["x"], c["y"])
        where, seen = card_lines(sim, c)
        trials.append({"trial": str(n), "cat": c["cat"], "type": c["type"], "say": sim.SAY.get(c["type"], c["type"]), "lon": lon, "lat": lat,
                       "road": c.get("road"), "park": c.get("park"), "where": where, "seen": seen})
    (OUT / "trials.json").write_text(json.dumps({"made": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"), "seed": seed, "trials": trials}, ensure_ascii=False, indent=1), encoding="utf-8")
    rule = ["## 지킬 것 (모든 카드 같음)", "",
            "- 카드에 적힌 것만 안다. 없는 것은 지어내지 말고 「모르겠어요」 · 「못 봤어요」라고 한다.",
            "- 처음엔 평소 전화하듯 **일부터** 말한다(「여보세요, ○○가 있어서요」). 어디인지는 아는 만큼만, 상담사가 물으면 답한다.",
            "- 카드의 말을 그대로 읽지 않는다. 자기 말투로, 흐리게(「편의점 하나 있었고요」, 「무슨 대교였는데…」).",
            "- 상담사가 보기를 읽어 주면, 카드와 맞는 것이 있을 때만 그것을 고른다. 없으면 「잘 모르겠어요」.",
            "- 마지막에 「○○ 앞, 맞으실까요?」라고 되물으면: 카드에 있는 것이 들어 있으면 「네」, 카드에 없는 이름이면 「그건 못 봤는데요」.",
            "- 같은 말을 디스코드 채팅(또는 정한 채팅방)에도 친다. 그 글이 「받아 적기」 대신이다.", ""]
    for who, nums in PEOPLE.items():
        doc = [f"# 민원인 카드 — {who} ({len(nums)}장)", "", "> 이 파일은 민원인 역만 본다. 상담사 역(화면을 잡는 사람)에게 보여 주지 않는다.", ""] + rule
        for k in nums:
            t = trials[k - 1]
            doc += [f"## {k}번 카드", "", f"- **무슨 일**: {t['say']}"] + [f"- **어디쯤**: {w}" for w in t["where"]] + [f"- **둘레에서 본 것**: {s}" for s in t["seen"]] + [""]
        (OUT / f"카드-{who}.md").write_text("\n".join(doc), encoding="utf-8")
    links = ["# 상담사 역 — 통화마다 열 주소", "", f"서버: 사람 시험용(포트 {port}, 실제 Solar 읽기). 번호마다 새 창으로 열면 바로 직접 통화(글로 넣기) 화면이다.", ""]
    links += [f"- {t['trial']}번 ({next(w for w, ns in PEOPLE.items() if int(t['trial']) in ns)}): http://127.0.0.1:{port}/?trial={t['trial']}" for t in trials]
    links += ["- 연습(기록 안 함): " + f"http://127.0.0.1:{port}/?trial=0", ""]
    (OUT / "상담사-주소.md").write_text("\n".join(links), encoding="utf-8")
    print(f"카드 {len(trials)}장 → {OUT} (카드-동욱 · 종희 · 건영.md, 상담사-주소.md, trials.json=참 위치)")
    for t in trials:
        print(f"  {t['trial']:>2} {t['cat']}")


def dist_m(a, b):
    return math.hypot((a[0] - b[0]) * 88200.0, (a[1] - b[1]) * 111000.0)


def result_of(r, t):
    """기록 한 줄 → (결과, 오차 m, 틀린 확정인가). 묶음을 모르면(지인 방식) 화면이 길 구간으로 끝냈는지로 길 위 · 밖을 가른다."""
    road = t["cat"] in ON_ROAD if t.get("cat") in ON_ROAD + WANT_CATS else r.get("size_kind") == "length"
    at = r.get("pin") or r.get("center")
    d = round(dist_m(at, (t["lon"], t["lat"]))) if at else None
    if r.get("handoff"):
        return "솔직한 끝", d, False
    if not r.get("confirmed"):
        return "못 끝냄", d, False
    if r.get("done"):
        ok = d is not None and d <= (120 if road else 60)
        return ("한 점 · 맞음" if ok else "한 점 · 틀림"), d, not ok
    reach = max(r.get("radius") or 0, (r.get("size_m") or 0) / 2 if r.get("size_kind") == "length" else 0, 120 if road else 60)
    inside = d is not None and d <= reach
    span = "구간" if (r.get("size_kind") == "length" or (r.get("radius") or 999) <= 150) and not r.get("region") else "넓은 범위"
    return f"{span} · {'안' if inside else '밖'}", d, span == "구간" and not inside


def parse_point(text):
    """「37.5431, 127.0412」 · 구글 지도 주소(…@37.54,127.04… · ?q=37.54,127.04) · 카카오맵 주소(…/link/map/이름,37.54,127.04) → (경도, 위도)."""
    nums = [float(v) for v in re.findall(r"-?\d{2,3}\.\d+", text)]
    for a, b in zip(nums, nums[1:]):
        if 33 <= a <= 39 and 124 <= b <= 132:
            return b, a
        if 124 <= a <= 132 and 33 <= b <= 39:
            return a, b
    return None


def truth():
    """통화 뒤 지인이 보내 준 자리를 번호에 붙인다(좌표 한 줄). 이름 · 연락처는 적지 않는다."""
    k, text = sys.argv[2], " ".join(sys.argv[3:])
    pt = parse_point(text)
    if not pt or not re.fullmatch(r"[A-Za-z0-9가-힣_\-]{1,20}", k):
        sys.exit("번호와 좌표(예: 37.5431, 127.0412 또는 구글 지도 주소)를 주세요. 주소 글자 · 짧은 공유 주소(maps.app.goo.gl · naver.me · kko.to)는 좌표가 없어 읽지 못한다")
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "truth.json"
    book = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    book[k] = {"lon": round(pt[0], 6), "lat": round(pt[1], 6), "at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00")}
    f.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{k}번 참 위치: 위도 {pt[1]:.6f}, 경도 {pt[0]:.6f} → {f}")


def score():
    log = Path(ARG("--log", str(HERE / "data" / "trials_local.jsonl")))
    if (OUT / "truth.json").exists():                     # 지인 방식: 통화 뒤 넣은 참 위치(있으면 이것만)
        truth = json.loads((OUT / "truth.json").read_text(encoding="utf-8"))
    else:                                                 # 카드 방식(쓰지 않음)
        truth = {t["trial"]: t for t in json.loads((OUT / "trials.json").read_text(encoding="utf-8"))["trials"]} if (OUT / "trials.json").exists() else {}
    last = {}
    for ln in log.read_text(encoding="utf-8").splitlines() if log.exists() else []:
        r = json.loads(ln)
        last[r["trial"]] = r                               # 같은 번호를 여러 번 남겼으면 마지막 것
    rows = []
    for k in sorted(set(truth) | set(last), key=lambda s: (len(s), s)):
        t, r = truth.get(k), last.get(k)
        if not r:
            rows.append({"trial": k, "cat": (t or {}).get("cat", ""), "result": "기록 없음"})
            continue
        cat = (t or {}).get("cat") or ("길 위" if r.get("size_kind") == "length" else "길 밖")
        if not t:
            rows.append({"trial": k, "cat": cat, "result": "참 위치 없음", "where": r.get("go") or r.get("where") or ""})
            continue
        res, d, wrong = result_of(r, t)
        turns = r.get("turns") or []
        unread = [x["said"] for x in turns if x.get("asked") in LOC_Q and not x.get("clues") and not x.get("picked") and not DUNNO.search(x["said"] or "")]     # 「못 봤어요」 · 「모르겠어요」는 못 읽힌 것이 아니다
        rows.append({"trial": k, "cat": cat, "result": res, "wrong": "예" if wrong else "", "dist_m": d, "questions": sum(1 for x in turns if x.get("asked")),
                     "citizen_lines": len(turns), "sec": r.get("sec"), "where": r.get("go") or r.get("where") or "", "unread": " / ".join(unread)})
    with open(OUT / "결과.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["trial", "cat", "result", "wrong", "dist_m", "questions", "citizen_lines", "sec", "where", "unread"])
        w.writeheader()
        w.writerows(rows)
    done = [r for r in rows if r["result"] not in ("기록 없음", "참 위치 없음")]
    count = lambda s: sum(1 for r in done if r["result"].startswith(s))     # noqa: E731
    hit = [r["dist_m"] for r in done if r["result"] == "한 점 · 맞음"]
    secs = [r["sec"] for r in done if r.get("sec")]
    md = [f"# 사람 시험 결과 ({time.strftime('%Y-%m-%d %H:%M')})", "",
          f"- 채점한 통화 {len(done)} / 번호 {len(rows)} · 한 점 맞음 {count('한 점 · 맞음')} · 구간 {count('구간')} · 넓은 범위 {count('넓은 범위')} · 솔직한 끝 {count('솔직한 끝')} · 못 끝냄 {count('못 끝냄')}",
          f"- **틀린 확정 {sum(1 for r in done if r.get('wrong'))}** (한 점이 60m · 길 위 120m 넘게 빗나감, 또는 구간 밖)",
          f"- 한 점으로 맞은 것의 오차: 가운데값 {statistics.median(hit):.0f}m · 가장 먼 것 {max(hit)}m" if hit else "- 한 점으로 맞은 것 없음",
          (f"- 질문 수 가운데값 {statistics.median([r['questions'] for r in done]):.0f} · 걸린 시간 가운데값 {statistics.median(secs):.0f}초" if done and secs else ""), "",
          "| 번호 | 묶음 | 결과 | 틀린 확정 | 확정한 자리 ↔ 참 위치 | 질문 수 | 걸린 시간 | 화면의 위치 | 못 읽힌 말 |", "|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['trial']} | {r['cat']} | {r['result']} | {r.get('wrong', '')} | {r.get('dist_m', '')}m | {r.get('questions', '')} | {r.get('sec') or ''}초 | {r.get('where', '')} | {r.get('unread', '')} |" for r in rows]
    (OUT / "결과.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:6]))
    print(f"→ {OUT}/결과.md · 결과.csv")


def selftest():
    """카드 뽑기 → 가짜 기록 셋(맞은 한 점 · 못 끝냄 · 솔직한 끝) → 채점이 맞게 세는지."""
    import tempfile
    global OUT
    tmp = Path(tempfile.mkdtemp())
    OUT, saved = tmp, sys.argv
    sys.argv = [saved[0]]
    cards()
    trials = json.loads((tmp / "trials.json").read_text(encoding="utf-8"))["trials"]
    assert len(trials) == 10 and {t["cat"] for t in trials} == {c for c, _ in WANT}, [t["cat"] for t in trials]
    for who in PEOPLE:
        body = (tmp / f"카드-{who}.md").read_text(encoding="utf-8")
        assert "참 위치" not in body and "lon" not in body and "openstreetmap" not in body.lower(), who      # 카드에 좌표 · 지도 링크가 없다
    t0, t1, t2 = trials[0], trials[1], trials[2]
    road0 = t0["cat"] in ON_ROAD
    recs = [{"trial": t0["trial"], "done": True, "confirmed": True, "pin": [t0["lon"] + 30 / 88200.0, t0["lat"]], "center": None, "radius": 40, "sec": 95,
             "turns": [{"said": "가", "asked": None, "clues": ["x"]}, {"said": "나", "asked": "mark", "clues": [], "picked": False}]},
            {"trial": t1["trial"], "done": False, "confirmed": False, "center": [t1["lon"], t1["lat"]], "radius": 300, "turns": []},
            {"trial": t2["trial"], "done": False, "confirmed": False, "handoff": True, "center": [t2["lon"], t2["lat"]], "radius": 300, "turns": []}]
    (tmp / "log.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    sys.argv = [saved[0], "--log", str(tmp / "log.jsonl")]
    score()
    rows = {r["trial"]: r for r in csv.DictReader(open(tmp / "결과.csv", encoding="utf-8"))}
    assert rows[t0["trial"]]["result"] == "한 점 · 맞음" and rows[t0["trial"]]["dist_m"] == "30" and rows[t0["trial"]]["unread"] == "나" and rows[t0["trial"]]["questions"] == "1", (rows[t0["trial"]], road0)
    assert rows[t1["trial"]]["result"] == "못 끝냄" and rows[t2["trial"]]["result"] == "솔직한 끝", (rows[t1["trial"]], rows[t2["trial"]])
    assert sum(1 for r in rows.values() if r["result"] == "기록 없음") == 7
    # 지인 방식: 자유 번호 · 통화 뒤 참 위치(구글 지도 주소 · 좌표 한 줄) · 길 구간으로 끝난 통화는 길 위 기준
    (tmp / "trials.json").unlink()
    assert parse_point("https://www.google.com/maps/place/@37.5431,127.0412,17z") == (127.0412, 37.5431) and parse_point("37.5, 127.0") == (127.0, 37.5)
    assert parse_point("https://map.kakao.com/link/map/여기,37.55,126.98") == (126.98, 37.55) and parse_point("서울 성동구 왕십리로") is None
    sys.argv = [saved[0], "truth", "a1", "37.5431, 127.0412"]
    truth()
    recs = [{"trial": "a1", "done": False, "confirmed": True, "size_kind": "length", "size_m": 400, "center": [127.0412 + 150 / 88200.0, 37.5431], "radius": 200, "turns": []},
            {"trial": "a2", "done": True, "confirmed": True, "pin": [127.0, 37.5], "radius": 30, "turns": []}]
    (tmp / "log2.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    sys.argv = [saved[0], "--log", str(tmp / "log2.jsonl")]
    score()
    rows = {r["trial"]: r for r in csv.DictReader(open(tmp / "결과.csv", encoding="utf-8"))}
    assert rows["a1"]["result"] == "구간 · 안" and rows["a1"]["cat"] == "길 위" and rows["a1"]["dist_m"] == "150", rows["a1"]
    assert rows["a2"]["result"] == "참 위치 없음", rows["a2"]
    sys.argv = saved
    print("human_test 스스로 시험 통과")


if __name__ == "__main__":
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    {"cards": cards, "truth": truth, "score": score, "selftest": selftest}[sys.argv[1] if len(sys.argv) > 1 else "selftest"]()
