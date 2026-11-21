"""통화로 위치 좁히기 점검: 서버를 저장된 답 방식으로 띄우고, 두 장면을 화면의 「대본 재생」과 같은 순서로 HTTP로 끝까지 돌려 본다.

    python3 demo/call/check.py          (열쇠 · 엔진 · 인터넷 없이 십여 초. 실패하면 종료 코드 1)

보는 것: 서버가 뜬다 → 대본의 말을 넣는다 → 코드가 바로 읽어 질문이 뜬다(①) → 저장된 Solar 읽기로 갈아 끼운다(②) → 범위가 줄어든다
        → 찾아갈 수 있을 만큼 좁혀지고 확인받는다 → 그때 담당 부서가 배정된다(6종 안 · 밖 갈림이 맞다) → 접수 카드가 나온다.
        단추만 눌러도, 대본에 없는 말(코드만으로 읽음)로도 끝까지 가는지 본다.
"""
import json
import re
import shutil
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("CALL_CHECK_PORT", "8779"))
BASE = f"http://127.0.0.1:{PORT}"
EXPECT = {
    "roadkill": {"scope": "out", "to": "서울시설공단", "where": ["강변북로", "구리 방향"], "cite": None, "kind": "length", "r": 100},
    "stray": {"scope": "in", "to": "성동구청 동물보호", "where": ["서울숲 안", "사슴우리", "스무 걸음"], "cite": "서울특별시 동물보호 조례 제10조 제1항", "kind": "radius", "r": 50},
    "vendor": {"scope": "in", "to": "서울숲 관리사무소", "where": ["서울숲 안", "거울연못"], "cite": "서울특별시 도시공원 조례 제22조 제1항", "kind": "radius", "r": 50},      # 자리가 조례 답을 가르는 장면(11-15 동규)
    "cat_street": {"scope": "in", "to": "송파구청 동물보호", "where": ["잠실역 1번 출구"], "cite": "서울특별시 동물보호 조례 제10조 제1항", "kind": "radius", "r": 50},      # 화면 장면 단추의 두 고양이 장면(11-17)
    "cat_park": {"scope": "in", "to": "성동구청 동물보호", "where": ["서울숲 안"], "cite": "서울특별시 동물보호 조례 제10조 제1항", "kind": "radius", "r": 50},
}


def call(path, body=None):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def turn(state, **ev):
    d = call("/api/turn", {"state": state, **ev})
    return d["state"], d["view"]


def wait_engine(state, view):
    t0 = time.time()
    while (view.get("engine") or {}).get("status") == "running":
        assert time.time() - t0 < 30, "엔진 답이 30초 안에 오지 않음"
        time.sleep(0.2)
        view = call("/api/view", {"state": state})["view"]
    return view


def check_end(name, view, sizes):
    e = EXPECT[name]
    sizes = [x for x in sizes if x is not None]            # 장소를 말하기 전의 차례는 범위가 없다
    assert sizes == sorted(sizes, reverse=True) and sizes[-1] < sizes[0], f"{name}: 범위가 줄지 않음 {sizes}"
    assert view["done"] and view["confirmed"] and view["question"] is None, f"{name}: 끝나지 않음"
    assert view["size"]["kind"] == e["kind"] and view["radius"] <= e["r"], f"{name}: 찾아갈 수 있을 만큼 좁혀지지 않음 {view['size']}"
    r, s = view["route"], view["summary"]
    assert not (r["class_name"] and any(r["class_name"] in o["to"] for o in r["others"] if not o["here"])), f"{name}: 같은 일 다른 자리 표에 지금 자리 이름이 다른 줄로 샘 {r['others']}"      # 강변북로 위인데 「강변북로 관리사무소」(11-18)
    assert r["scope"] == e["scope"] and e["to"] in r["hit"]["to"], f"{name}: 갈림 · 넘길 곳이 다름 {r['scope']} {r['hit']['to']}"
    assert all(w in s["where"] for w in e["where"]), f"{name}: 위치 한 줄 {s['where']}"
    assert s["point"] and s["matter"] and e["to"] in s["to"] and s["go"] and view["pin"] and all(k in s["copy"] for k in ("민원을 받은 곳", "처음 접수한 담당자", "찾아가는 말", "번지수", "지도 좌표", "일", "처리할 담당 부서")), f"{name}: 접수 카드 {s}"
    assert view["answer_box"]["안내"]["name"] and view["answer_box"]["근거"]["name"] and view["heat"]["pts"] and len(view["heat"]["pts"]) <= 2500, f"{name}: 추천 답 칸 이름 · 지도에 그릴 점"
    if r.get("fate"):       # 동물의 일: 「살았나 · 죽었나 × 자리」 표(11-18). 표의 줄 그대로, 지금 통화의 줄 하나만 칠함
        f, dead = r["fate"], [x for x in r["fate"] if not x["alive"]]
        assert sum(x["here"] for x in f) == 1 and {x["alive"] for x in f} == {True, False} and all(x["to"] and "{" not in x["to"] and (x["scope"] == "in") == x["alive"] for x in f), f"{name}: 살았나 표 {f}"
        assert [(x["class"], x["basis"]) for x in dead][:3] == [("길", "확인"), ("시 공원", "확인"), ("자동차전용도로", "확인")] and "청소" in dead[0]["to"] and "서울시설공단" in dead[2]["to"], f"{name}: 사체 줄 {dead}"
    eng = view["engine"]
    assert eng["status"] == "ready" and not eng["error"] and eng["ask"], f"{name}: 엔진 {eng}"
    if e["cite"]:       # 6종 안: 근거 조항이 붙은 추천 답
        assert view["matter"]["scope"] == "in" and eng["answer"] and e["cite"] in [c["label"] for c in eng["citations"]] and all(c["url"] and c["effective"] for c in eng["citations"]), f"{name}: 근거 조항 {eng['citations']}"
        assert any(c["quotes"] for c in eng["citations"]) and e["cite"] in " ".join(s["cites"]), f"{name}: 원문 구절 · 카드의 근거"
    else:               # 6종 밖: 추천 답을 만들지 않고, 엔진도 물러난다
        assert view["matter"]["scope"] == "out" and not eng["answer"] and not eng["citations"] and not s["cites"], f"{name}: 6종 밖인데 답 · 조항이 있음 {eng}"
        assert len(r["others"]) >= 3 and sum(o["here"] for o in r["others"]) == 1, f"{name}: 같은 일 다른 자리 표 {r['others']}"


def play(name, script, greeting):
    """대본 재생: 화면이 띄운 질문을 상담사가 읽고, 그 질문에 맞는 대본 줄로 시민이 답한다."""
    st, view = turn({"id": f"check-{name}"}, line={"who": "상담사", "text": greeting})
    assert view["question"]["id"] in ("where", "what") and not view["heat"]["pts"], f"{name}: 통화 전 화면 {view['question']}"
    said, sizes, asked, slow = script["처음"], [], [], 0
    for _ in range(12):
        st, fast = turn(st, line={"who": "시민", "text": said})          # ① 코드가 먼저 읽는다
        assert fast["read_how"] == "code" and (fast["question"] or fast["confirmed"]), f"{name}: 코드 읽기 뒤 질문이 없음"
        slow = max(slow, fast["read_sec"] * 1000 + fast["calc_ms"])
        st, view = turn(st, phase="model")                               # ② 저장된 Solar 읽기로 갈아 끼운다
        assert view["read_how"] == "saved", f"{name}: 저장된 답이 없는 말 「{said}」({view['read_how']}). 대본을 고쳤으면 --save로 다시 받는다"
        assert view["heat"]["pts"] or (view["question"] or {}).get("id") == "where", f"{name}: 지도에 그릴 범위가 없음"      # 일부터 말한 첫 마디에는 아직 범위가 없다(어디인지 되묻는다)
        assert (view["route"] is not None) == (view["done"] or view["confirmed"]), f"{name}: 담당 부서는 위치가 정해진 뒤에만 배정돼야 한다"
        sizes.append(view["radius"])
        if view["confirmed"]:
            break
        q = view["question"]
        assert q["say"] and "{" not in q["say"] and "[" not in q["say"] and q["why"], f"{name}: 질문 글이 비었거나 채워지지 않음 {q}"
        assert q["id"] in script, f"{name}: 질문 「{q['id']}」에 답하는 대본 줄이 없음"
        asked.append(q["id"])
        st, view = turn(st, line={"who": "상담사", "text": q["say"]})
        said = script[q["id"]]
    view = wait_engine(st, view)
    check_end(name, view, sizes)
    print(f"  ✓ {name}: 질문 {' → '.join(asked)} | 범위 {' → '.join(str(x) + 'm' for x in sizes)} | 코드 읽기 + 셈 가장 느린 차례 {slow:.0f}ms")
    print(f"      {view['summary']['where']} | {view['summary']['to']}")
    return st


def chips_only(first):
    """첫 말만 넣고, 그 뒤로는 받아 적기 없이 단추만 눌러도 끝까지 간다(로드킬 장면)."""
    st, view = turn({"id": "check-chips"}, line={"who": "상담사", "text": "인사"})
    st, view = turn(st, line={"who": "시민", "text": first})
    want = {"between": ("성수대교", "영동대교"), "passed": ("서울숲 보행다리",), "confirm": ("네, 맞아요",), "dir": ("구리 방향",), "lane": ("갓길",), "lampno": ("번호",)}
    sizes = [view["radius"]]
    for _ in range(8):
        q = view["question"]
        if q is None:
            break
        opt = next((o for o in q["options"] if all(w in o["label"] for w in want.get(q["id"], ("없는 질문",)))), None)
        assert opt, f"단추만: 질문 「{q['id']}」에 고를 단추가 없음 {[o['label'] for o in q['options']]}"
        st, view = turn(st, set=opt["set"], label=opt["label"])
        assert view["read_how"] == "chip"
        sizes.append(view["radius"])
    view = wait_engine(st, view)
    check_end("roadkill", view, sizes)
    print("  ✓ 첫 말 뒤로 단추만 눌러 로드킬 장면 끝까지")


def field_fixes():
    """(71번) 기본으로 켠 현장 실패 꼴 고침 가운데 코드로 도는 셋: 흔한 말(commonshop) · 튐 막기(jumpguard) · 목줄 짧은 답(optpart). Solar 「아님」 확인(dropcheck)은 Solar 길에서만 돈다."""
    far = lambda a, b: ((a[0] - b[0]) * 88200) ** 2 + ((a[1] - b[1]) * 111000) ** 2 > 2000 ** 2      # noqa: E731
    say = lambda st, text: turn(turn(st, line={"who": "시민", "text": text})[0], phase="model")      # noqa: E731
    st, view = say({"id": "check-field"}, "상도1동주민센터 바로 앞이에요. 고양이가 다쳐서 웅크리고 있어요")
    c0 = view["center"]
    st, view = say(st, "네, 지금도 그 자리에 있어요")
    assert view["chips"] == ["상도1동주민센터"] and not far(view["center"], c0), (view["chips"], view["center"])      # 「자리에」를 가게 이름으로 읽지 않는다(현장: 4.9km 다른 동으로 확정)
    _, v2 = say(st, "잠실역이요")
    assert not far(v2["center"], c0), v2["center"]                                   # 좁혀진 뒤 이름만 댄 먼 곳으로 튀지 않는다
    _, v3 = say(st, "아니요, 잘못 말했어요. 잠실역이에요")
    assert far(v3["center"], c0) and "잠실역" in v3["chips"], (v3["center"], v3["chips"])      # 고쳐 말하면 받는다
    st, view = say({"id": "check-jump-matter"}, "상도1동주민센터 바로 앞이에요")
    c1 = view["center"]
    _, view = say(st, "잠실역 쪽인데 고양이가 죽어 있어요")
    assert not far(view["center"], c1) and view["matter"].get("type") == "carcass" and view["matter"].get("alive") is False, (view["center"], view["matter"])      # 튐을 막은 말이라도 같은 말의 일 · 생사는 읽는다(#134 리뷰)
    st, view = say({"id": "check-leash"}, "뚝섬역 1번 출구 바로 앞에 개가 돌아다니고 있어요")
    assert view["question"]["id"] == "leash", view["question"]
    st, view = turn(st, line={"who": "상담사", "text": view["question"]["say"]})
    st, view = say(st, "안보여요")
    assert view["matter"].get("leash") is False and view["question"]["id"] != "leash", (view["matter"], view["question"])      # 목줄 질문의 「안보여요」를 답으로(같은 질문을 다시 묻지 않는다)
    print("  ✓ 현장 실패 꼴 고침: 「자리에」 안 읽음 · 이름만 댄 먼 곳으로 안 튐(같은 말의 일은 읽음) · 고쳐 말하면 옮김 · 목줄 「안보여요」를 답으로")


def partial_yes_table():
    """(partyes2) 이 고침은 부분 긍정을 더하기만 한다: 되묻기 답의 갈림 표(시작 × 가운데 × 어긋남 말 × 끝 + 강조 말 · 「네, 맞아요」 꼴)에서
    부분 긍정이 아닌 칸은 모두 스위치를 끈 결과(main 규칙)와 같은지 칸마다 견준다. 코드 읽기와 Solar 읽기 길 둘 다. 부정으로 맺는 칸은 부분 긍정이 되지 않는다."""
    import itertools
    os.environ.setdefault("CALL_MODE", "saved"), os.environ.setdefault("CALL_NO_ENGINE", "1")
    sys.path.insert(0, str(HERE))
    import server as S
    ask = {"id": "confirm"}
    starts, mids, devs = ["네", "예", "맞아요", "어 네", "음 네", "네 정말", "네, 완전히"], [", 근데 ", ", 다만 ", ", 그런데 ", ", 아 근데 ", " "], ["조금 옆", "뒤", "길 건너", "그쪽", "조금 떨어져"]
    ends = {"긍정": "{d}이에요", "자리 말": "{d} 편의점 앞이에요", "강조": "{d}이에요, 완전히 맞아요", "아니에요": "{d} 아니에요", "아니요": "{d}요. 아니요", "아닌데요": "{d} 아닌데요",
            "아닌 것 같아요": "{d} 아닌 것 같아요", "반대쪽": "{d} 말고 반대쪽이에요"}
    negend = {"아니에요", "아니요", "아닌데요", "아닌 것 같아요", "반대쪽"}
    cells = [(f"{a}{m}{ends[e].format(d=d)}", e) for a, m, d, e in itertools.product(starts, mids, devs, ends)]
    cells += [(t, "따로") for t in ("네, 맞아요", "네", "네, 완전히 맞아요", "네 정말 맞아요", "네, 딱 거기예요", "네, 확실히 거기예요", "네, 전혀 안 움직이고 그 앞에 있어요", "네, 바로 옆이에요",
                                   "네, 근데 그쪽 아니에요", "예, 근데 거기 뒤 아니에요", "네 맞는데 근데 그쪽 말고 반대쪽이에요", "아니요, 거기가 아니에요", "잘 모르겠어요")]
    protect = ["네, 근데 바로 앞은 아니고 조금 옆이에요", "예, 근데 길 건너편이에요", "네, 조금 옆이에요"]
    cells += [(t, "지킬 말") for t in protect]

    def both(said):
        r_on = S.code_read(said, ask, [], None)
        had = "partyes2" in S.L.ON
        S.L.ON.discard("partyes2")
        try:
            r_off = S.code_read(said, ask, [], None)
        finally:
            S.L.ON.add("partyes2") if had else None
        return r_on, r_off
    partial = 0
    for said, end in cells:
        r_on, r_off = both(said)
        is_partial = bool(r_on["confirm"] is None and r_on["matter"].get("side") in ("근처", "건너편") and "side" not in r_off["matter"])
        if not is_partial:
            assert (r_on["confirm"], r_on["matter"].get("side")) == (r_off["confirm"], r_off["matter"].get("side")), (said, r_on["confirm"], r_off["confirm"])     # 부분 긍정이 아니면 main 그대로
        assert not (is_partial and end in negend), said                    # 부정으로 맺는 답은 부분 긍정이 아니다
        assert is_partial or end != "지킬 말", said                        # 지키려는 말은 부분 긍정
        partial += bool(is_partial)
        for solar in (True, False, None):                                  # Solar 읽기 길: 부분 긍정이 아니면 Solar가 읽은 그대로, 앞 차례에 부분 긍정이 있으면 늘 그대로
            for prior in ([], [{"code": {"clues": [{"partyes": True}]}}]):
                st = {"turns": prior + [{"asked": ask, "said": said, "code": {"clues": []}}]}
                read = {"confirm": solar, "matter": {}, "clues": []}
                changed = S._partyes_model(read, st)
                assert changed == (is_partial and not prior), (said, solar, bool(prior), changed)
                if not changed:
                    assert read == {"confirm": solar, "matter": {}, "clues": []}, (said, read)
    print(f"  ✓ 되묻기 답 갈림 표 {len(cells)}칸(부분 긍정 {partial}칸): 부분 긍정이 아닌 칸은 모두 main 그대로(코드 · Solar 읽기 둘 다), 부정으로 맺는 칸은 부분 긍정이 아님, 두 번째는 늘 그대로")


def partial_yes():
    """(partyes2, 73번) 되묻기에 「네, 근데 바로 앞은 아니고 조금 옆이에요」: 「아니요」가 아니다 — 확정을 한 번 미루고 「○○ 근처」로 다시 되묻고, 두 번째도 그렇게 답하면 확정."""
    say = lambda st, text: turn(turn(st, line={"who": "시민", "text": text})[0], phase="model")      # noqa: E731
    st, view = say({"id": "check-partyes"}, "상도1동주민센터 바로 앞에 고양이가 죽어 있어요")
    for _ in range(4):
        if view["question"]["id"] == "confirm":
            break
        st, view = turn(st, line={"who": "상담사", "text": view["question"]["say"]})
        st, view = say(st, "차로 위예요" if view["question"]["id"] == "lane" else "잘 모르겠어요")
    assert view["question"]["id"] == "confirm", view["question"]
    st, view = turn(st, line={"who": "상담사", "text": view["question"]["say"]})
    st, view = say(st, "네, 근데 바로 앞은 아니고 조금 옆이에요")
    W = {r[0]: r[1] for t in call("/api/text")["text"]["sections"]["위치 범위"]["tables"] for r in t["rows"]}
    assert not view["confirmed"] and view["question"]["id"] == "confirm" and W["표지 근처"].replace("{표지}", "").strip() in view["question"]["say"], (view["confirmed"], view["question"])
    assert W["단서 · 되묻은 자리 조금 옆"] in view["chips"], view["chips"]      # 화면 칩의 단서 이름은 문구 파일에서(줄이 없으면 여기서 실패)
    st2, view2 = turn(st, line={"who": "상담사", "text": view["question"]["say"]})
    _, view2 = say(st2, "네, 근데 바로 앞은 아니고 조금 옆이에요")
    assert not view2["confirmed"], view2["question"]                      # 두 번째 부분 긍정은 확정하지 않는다(main 규칙)
    _, view3 = say(st2, "네, 맞아요")
    assert view3["confirmed"], view3["question"]                          # 「○○ 근처」에 「네」면 확정
    st, view = say({"id": "check-partyes-no"}, "상도1동주민센터 바로 앞에 고양이가 죽어 있어요")
    for _ in range(4):
        if view["question"]["id"] == "confirm":
            break
        st, view = turn(st, line={"who": "상담사", "text": view["question"]["say"]})
        st, view = say(st, "차로 위예요" if view["question"]["id"] == "lane" else "잘 모르겠어요")
    for _ in range(3):                                    # 아니라고 맺는 답을 거듭해도 그 자리는 확정되지 않는다
        if view["question"]["id"] != "confirm":
            break
        st, view = turn(st, line={"who": "상담사", "text": view["question"]["say"]})
        st, view = say(st, "네, 근데 그쪽 아니에요")
        assert not view["confirmed"], view["question"]
    print("  ✓ 되묻기 부분 긍정: 「네, 근데 … 조금 옆이에요」 → 「○○ 근처」로 다시 되묻고, 두 번째는 main 그대로(확정 안 됨) · 「네, 근데 그쪽 아니에요」는 거듭해도 확정 안 됨")


def yesno_reads():
    """(yesno · whichkeep, 81번, 기본 끔) 되묻기 답 읽기와 「어느 말이 달랐을까요?」의 「○○은 맞아요」를 서버 함수로 바로 본다(모델 · 엔진 호출 없음). 스위치를 켠 판 · 끈 판을 같은 함수에서 견준다."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    ask = {"id": "confirm"}

    def read(said, sw):
        had = sw in S.L.ON
        S.L.ON.add(sw)
        try:
            on = S.code_read(said, ask, [], None)["confirm"]
        finally:
            S.L.ON.discard(sw) if not had else None
        S.L.ON.discard(sw)
        try:
            off = S.code_read(said, ask, [], None)["confirm"]
        finally:
            S.L.ON.add(sw) if had else None
        return on, off
    yes = ["네", "네, 맞아요", "네 맞아요", "네 거기 맞아요", "네네 거기요", "맞습니다", "맞아요", "응", "예", "네, 딱 거기예요", "거기요", "네, 바로 옆이에요"]
    askback = ["네? 뭐라고요?", "네?", "네? 잘 안 들려요", "네네 잠깐만요, 다시 볼게요", "거기 맞는지 잘 모르겠어요"]
    fix = ["네 맞는데 근데 그쪽 말고 반대쪽이에요", "아 거기서 좀 더 가야 돼요", "그 근처는 맞아요", "네 그런데 거기서 50미터쯤 더 가야 돼요"]
    same = ["아니요", "아니요, 거기가 아니에요", "아니 그 근처긴 한데요", "잘 모르겠어요", "네, 근데 바로 앞은 아니고 조금 옆이에요", "예, 근데 길 건너편이에요", "네, 근데 그쪽 아니에요"]
    for said in yes + askback + fix + same:
        on, off = read(said, "yesno")
        assert off == S._confirm_main(said) or "partyes2" in S.L.ON and said in same[4:], (said, off)      # 끈 판은 main 규칙 그대로
        want = True if said in yes else None if said in askback else False if said in fix else off
        assert on == want, f"되묻기 답 {said!r}: 켬 {on} (기대 {want}) · 끔 {off}"
    for code, solar, want in ((True, True, True), (True, None, None), (None, True, None), (None, None, None), (True, False, False), (False, True, False), (False, None, False), (None, False, False)):
        assert S._confirm_pair(code, solar) is want, (code, solar)      # 둘 다 예일 때만 확정, 하나라도 아니요면 아니요
    opts = [{"label": "강남역", "set": {"drop": ["강남역"]}}, {"label": "강남새로치과의원", "set": {"drop": ["강남새로치과의원"]}}, {"label": "잘 모르겠음", "set": {"clues": []}}]
    which = {"id": "which", "options": opts}
    for said, on_drop, off_drop in (("강남새로치과의원은 맞아요", ["강남역"], ["강남새로치과의원"]), ("강남역이 달랐어요", ["강남역"], ["강남역"]),
                                    ("강남역은 맞고 강남새로치과의원이 아니에요", ["강남새로치과의원"], None)):
        short = S.shortlist(said, None, "which")
        had = "whichkeep" in S.L.ON
        S.L.ON.add("whichkeep")
        got_on = S.code_read(said, which, short, None).get("drop")
        S.L.ON.discard("whichkeep")
        got_off = S.code_read(said, which, short, None).get("drop")
        S.L.ON.add("whichkeep") if had else None
        assert got_on == on_drop and got_off == off_drop, (said, got_on, got_off)
    print(f"  ✓ 되묻기 답 읽기(yesno 켬 · 끔): 진짜 예 {len(yes)}개는 그대로 예 · 되묻는 「네?」 · 확신 없음 {len(askback)}개는 확정 안 함 · 고쳐 말함 {len(fix)}개는 아니요 · 끈 판은 main 그대로 · "
          "코드와 Solar가 둘 다 예일 때만 확정 · 「○○은 맞아요」는 ○○을 지우지 않음(whichkeep)")


def matter_repeat():
    """(hurtalive · matterstop) 같은 일 질문은 세 번 이상 나오지 않는다: 시민이 생사 · 목줄 질문에 답하지 않아도 두 번까지만 묻고 위치로. 「다쳐서 · 웅크리고」는 살아 있음, 「죽어」가 같이 있으면 죽음."""
    say = lambda st, text: turn(turn(st, line={"who": "시민", "text": text})[0], phase="model")      # noqa: E731
    st, view = say({"id": "check-matter-repeat"}, "상도1동주민센터 바로 앞에 고양이가 있어요")
    asked = []
    for _ in range(8):
        q = view["question"] or {}
        if not q or q["id"] in ("confirm", "handoff"):
            break
        asked.append(q["id"])
        st, view = turn(st, line={"who": "상담사", "text": q["say"]})
        st, view = say(st, "네, 맞아요. 지금도 그 자리에 있어요")       # 상도동 대본처럼 일 질문에 답하지 않는 말
    assert asked and max(asked.count(k) for k in set(asked)) <= 2 and view["question"]["id"] in ("confirm", "handoff"), asked
    for text, alive in (("집 앞 골목에 고양이가 다쳐서 웅크리고 있어요", True), ("고양이가 다쳐서 죽어 있어요", False), ("강아지가 떨고 있어요", True),
                        ("고양이가 다친 것 같은데 움직이지 않아요", None), ("강아지가 다쳐서 숨을 안 쉬어요", None), ("고양이가 다쳐서 숨 쉬지 않아요", None), ("다친 고양이가 쓰러져 있어요", None)):
        _, view = say({"id": "check-hurt-" + text[:6]}, text + ". 상도1동주민센터 바로 앞이에요")
        assert view["matter"].get("alive") is alive and (view["question"]["id"] == "alive") == (alive is None), (text, view["matter"], view["question"])
    print(f"  ✓ 일 질문 되풀이 막기: 답하지 않아도 같은 일 질문은 두 번까지({' → '.join(asked)}) · 「다쳐서 웅크리고 · 떨고」는 살아 있음 · 「다쳐서 죽어」는 죽음 · 「다쳤는데 움직이지 않아요 · 숨을 안 쉬어요 · 쓰러져 있어요」는 지금처럼 살았는지 물음")


def edge_reads():
    """(75번) 둘레에 길이 있는 곳의 읽기 스위치(EDGE_ON): 켜져 있으면 그 읽기를, 꺼져 있으면 지금의 읽기(길 낱말이 이름으로 읽힘)를 서버 함수로 바로 본다(모델 · 엔진 호출 없음)."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    on = set(S.L.EDGE_ON.split(",")) <= S.L.ON
    x, y = S.gaz.xy(126.93626, 37.53345)      # 마포대교 한가운데(11-21 「다리」 갈래): 포트홀은 서울시 교량안전과, 쓰레기는 다리 줄이 없어 전처럼 구청
    deck = {"cx": x, "cy": y, "on_road": False, "ctx": {"roads": []}}
    assert S.L.place_class(deck) == ("다리", "마포대교") and "교량안전과" in S.route_of({"type": "road"}, deck)["hit"]["to"] and "구청" in S.route_of({"type": "litter"}, deck)["hit"]["to"]
    x, y = S.gaz.xy(127.1215, 37.5206)      # 올림픽공원 안(11-21 spots): 노점은 국민체육진흥공단, 유기 동물은 그대로 송파구청
    olp = {"cx": x, "cy": y, "on_road": False, "ctx": {"roads": []}}
    assert "국민체육진흥공단" in S.route_of({"type": "vendor"}, olp)["hit"]["to"] and "송파구청 동물보호" in S.route_of({"type": "stray"}, olp)["hit"]["to"]
    x, y = S.gaz.xy(126.9850, 37.5690)      # 청계천 광교 둘레: 시민이 「청계천 산책로」라고 했을 때만 서울시설공단 청계천관리처, 길(청계천로)은 그대로 구청
    cgc = {"cx": x, "cy": y, "on_road": False, "ctx": {"roads": []}}
    assert "청계천관리처" in S.route_of({"type": "litter", "spot": "청계천"}, cgc)["hit"]["to"] and "구청" in S.route_of({"type": "litter"}, cgc)["hit"]["to"]
    assert S.understood(S.turn({"id": "check-cgc"}, {"line": {"who": "시민", "text": "청계천 산책로예요, 쓰레기가 잔뜩 버려져 있어요"}})[0])[1]["spot"] == "청계천"
    sub = lambda said: S.understood(S.turn({"id": "check-sub"}, {"line": {"who": "시민", "text": said}})[0])[1]["spot"]      # noqa: E731  지하철 역 안: 시민이 역 안 · 승강장 등을 말했을 때만 운영 기관
    assert sub("잠실역 안에 쓰레기가 많아요") == "지하철 역사 안" and sub("잠실역 1번 출구 앞에 쓰레기가 많아요") is None and "서울교통공사" in S.route_of({"type": "litter", "spot": "지하철 역사 안"}, olp)["hit"]["to"]

    def read(said, asked=None):
        short = S.shortlist(said, None, (asked or {}).get("id"))
        return S.code_read(said, asked, short, None)["clues"]
    c = read("석촌호수 서쪽 산책로예요")
    names = [x.get("k") for x in c]
    if not on:
        assert "산책로" in names, names
        print("  ✓ 둘레 읽기 스위치 꺼짐: 지금의 읽기 그대로")
        return
    assert names == [None, "석촌호수"] and c[0]["t"] == "cone" and c[0]["v"] == [-1.0, 0.0] and c[1]["how"] == "가까이", c      # 길 낱말은 이름이 아니고, 방위 말은 그쪽으로, 호수의 산책로는 물가 둘레
    assert [(x["t"], x.get("k")) for x in read("올림픽공원 둘레길이에요, 입구 반대쪽이요")] == [("rim", "올림픽공원")]
    assert [(x["t"], x.get("k")) for x in read("숭례문광장 한가운데쯤이요")] == [("core", "숭례문광장")]
    assert read("롯데월드타워가 보이긴 해요")[0].get("how") == "쪽" and read("호수 건너편에 잠실역이 보여요")[0].get("how") == "쪽"      # 멀리 보이는 것은 그 둘레 넓게
    st, view = S.turn({"id": "check-over"}, {"line": {"who": "시민", "text": "항동저수지 산책로인데 호수 건너편에 우신중고등학교가 보여요"}})
    assert [x["t"] for x in S.understood(st)[0]] == ["at", "over"] and "항동저수지 둘레" in view["summary"]["where"], S.understood(st)[0]      # 건너편에 보이는 것은 자리 단서가 아니라 「그쪽으로 물이 놓인 둘레」
    st, view = S.turn({"id": "check-edge"}, {"line": {"who": "시민", "text": "숭례문광장 가장자리요, 찻길 쪽에 쓰레기가 잔뜩 버려져 있어요"}})
    st, view = S.turn(st, {"line": {"who": "시민", "text": "공원 안이에요"}})
    assert not view["done"] and view["pin"] is None and "숭례문광장 둘레" in view["summary"]["where"], (view["done"], view["summary"]["where"])      # 광장 가장자리: 가운데에 핀을 찍지 않고 둘레로 되묻는다
    st, view = S.turn({"id": "check-edge2"}, {"line": {"who": "시민", "text": "망원한강공원 자전거길이에요, 양화대교 밑에 고양이가 죽어 있어요"}})
    st, view = S.turn(st, {"line": {"who": "시민", "text": "공원 안이에요"}})
    assert view["done"] and "망원한강공원 안" in view["summary"]["where"] and "양화대교" in view["summary"]["where"], view["summary"]["where"]      # 다리는 강 한복판 한 점이 아니라 공원과 만나는 곳
    # 낱말 규칙이 엉뚱한 말에 걸리지 않는다: 「남편」은 방위가 아니고, 바로 뒤에서 부정한 말(둘레길 말고 · 가장자리는 아니에요 · 북쪽은 아니고요)은 그 뜻으로 읽지 않는다
    plain = lambda said: [(x["t"], x.get("k"), x.get("how")) for x in read(said)]      # noqa: E731
    for said, want in {"서울숲 남편이랑 걷다가 봤어요": [("at", "서울숲", None)], "올림픽공원 둘레길 말고 안쪽이에요": [("at", "올림픽공원", None)], "숭례문광장 가장자리는 아니에요": [("at", "숭례문광장", None)],
                       "석촌호수 북쪽은 아니고요": [("at", "석촌호수", "쪽")], "산책로 옆 편의점이에요": [("cat", None, None)], "서울둘레길 안내판 앞이에요": [("at", "서울둘레길", "바로")]}.items():
        assert plain(said) == want, (said, plain(said))
    # 스위치 열둘 각각: 다 켜면 참이고, 그 스위치 하나만 끄면 거짓이 되는 장면 하나씩(스위치가 실제로 그 동작을 맡고 있음을 본다)
    L, G, k = S.L, S.G, S.gaz.norm
    park = lambda name: ["park", next(i for i, a in enumerate(G.parks) if a["name"] == name)]      # noqa: E731
    edge = [{"t": "rim", "k": k("숭례문광장"), "w": 25.0}, {"t": "in", "a": park("숭례문광장")}]
    pool = [{"t": "in", "a": park("뚝섬한강공원")}, {"t": "at", "k": k("뚝섬수영장"), "how": "바로"}]
    under = [{"t": "in", "a": park("망원한강공원")}, {"t": "at", "k": k("양화대교"), "how": "바로"}]
    lake, plaza, told = [{"t": "at", "k": k("석촌호수"), "how": "가까이"}], [{"t": "at", "k": k("열린송현 녹지광장")}], {"type": "litter", "told": "쓰레기"}
    asks = lambda log: [(q["id"], q.get("area")) for q in L.questions(L.infer(lake), lake, told, log)]      # noqa: E731
    i_self = next(i for i in range(G.shop0) if G.name[i] == "열린송현 녹지광장")
    probes = {"trailword": lambda: "산책로" not in [x.get("k") for x in read("석촌호수 산책로예요")],
              "compass": lambda: any(x["t"] == "cone" for x in read("석촌호수 서쪽 산책로예요")),
              "edgeband": lambda: read("올림픽공원 둘레길이에요")[0]["t"] == "rim",
              "lakerim": lambda: L.infer(lake).get("ringed") == "석촌호수",
              "selfname": lambda: i_self not in L._candidates(*L._sample(L.infer(plaza)), 100.0)[0],
              "bigdist": lambda: L._q_dist(L.infer(pool), pool) is None,
              "ringdone": lambda: not L.is_done(L.infer(edge)),
              "rimask": lambda: ("closest", "석촌호수") in asks([]),
              "rimline": lambda: "rim" in L.describe(L.infer(lake), lake),
              "closestcap": lambda: "closest" not in [q for q, _ in asks(["mark!", "mark!", "closest", "closest"])],
              "farsee2": lambda: read("롯데월드타워가 보이긴 해요")[0].get("how") == "쪽",
              "bridgeline": lambda: L.is_done(L.infer(under))}
    assert set(probes) == set(L.EDGE_ON.split(",")), set(probes) ^ set(L.EDGE_ON.split(","))
    for name, probe in probes.items():
        assert probe(), f"{name}: 켠 채로 기대한 동작이 아님"
        L.ON.discard(name)
        try:
            assert not probe(), f"{name}: 꺼도 결과가 같음(이 장면이 그 스위치를 보지 않는다)"
        finally:
            L.ON.add(name)
    print("  ✓ 둘레 읽기: 길 낱말은 이름이 아님 · 방위 말 · 테두리 띠와 한가운데 · 멀리 보이는 것 · 광장 가장자리는 가운데에 핀 없음 · 공원 + 다리 밑 · 엉뚱한 말에 안 걸림 여섯 · 스위치 열둘 각각 끄면 달라짐")


def ask_fixes():
    """(75번 후보 2) 질문 다듬기 스위치(ASK_ON) 가운데 서버 쪽 둘: 조사(josa)와 같은 보기로 이미 물었는지 가리기(sameopts). 켜져 있으면 그 동작을, 꺼져 있으면 지금 동작을 본다. 나머지 둘은 locate.py 스스로 시험에 있다."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    seen = S.tab("이렇게 물어보세요", "질문")["seen"]
    got = [S.fill(seen, 종류=w) for w in ("카페", "정류장", "편의점", "학교")]
    want = ["근처에 카페가 보입니까?", "근처에 정류장이 보입니까?", "근처에 편의점이 보입니까?", "근처에 학교가 보입니까?"]
    assert (got == want) if "josa" in S.L.ON else all("(이)가" in g for g in got), got
    if "josa" in S.L.ON:                                  # 그 스위치 하나만 끄면 달라지는지(이 장면이 스위치를 보는지)
        S.L.ON.discard("josa")
        try:
            assert "(이)가" in S.fill(seen, 종류="카페"), "josa: 꺼도 결과가 같음"
        finally:
            S.L.ON.add("josa")
    two = [{"label": "석촌호수 아뜰리에"}, {"label": "석촌호수 아뜰리에"}, {"label": "호수미"}]      # 지명 표에 같은 이름의 점이 둘인 보기
    assert S.say_options(two) == (["석촌호수 아뜰리에", "호수미"] if "samename" in S.L.ON else ["석촌호수 아뜰리에", "석촌호수 아뜰리에", "호수미"])
    if "samename" in S.L.ON:
        S.L.ON.discard("samename")
        try:
            assert len(S.say_options(two)) == 3, "samename: 꺼도 결과가 같음"
        finally:
            S.L.ON.add("samename")
    words = S.tab("이렇게 물어보세요", "낱말")
    asked = {"id": "from", "options": [{"label": "영동1교남단 쪽", "set": {}}, {"label": words["잘 모르겠음"], "set": {}}]}
    finer = {"id": "finer", "options": [{"label": "가", "set": {}}]}
    same = S.asked_same([{"said": "영동1교남단 쪽이요", "asked": asked, "code": {"picked": True}}, {"said": "잘 모르겠어요", "asked": finer, "code": {"clues": []}}], words)
    assert same({"id": "from", "options": [{"label": "영동1교남단 쪽"}, {"word": "잘 모르겠음"}]})      # 보기에서 골라 답한 질문의 같은 보기(낱말 보기는 화면 글로 바꿔 견준다)
    assert not same({"id": "from", "options": [{"label": "영동1교북단 쪽"}, {"word": "잘 모르겠음"}]}) and not same({"id": "finer", "options": [{"label": "가"}]})      # 보기가 다르거나, 「모르겠어요」로 답했던 질문
    print("  ✓ 질문 다듬기: 조사 「(이)가」" + ("를 받침에 맞춤" if "josa" in S.L.ON else "는 그대로(스위치 꺼짐)") + " · 같은 이름의 보기는 한 번만 말함 · 골라 답한 질문 가리기")


def ask_less():
    """(82번) 덜 묻기 고침(ASKLESS_ON): 켜져 있으면 그 동작을, 꺼져 있으면 지금 동작을 보고, 켜진 것은 하나씩 끄면 달라지는지 본다."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    L = S.L
    read = lambda text, qid, opts=(): S.code_read(text, {"id": qid, "options": list(opts)}, S.shortlist(text, None, qid, []), None)     # noqa: E731
    opts = [{"label": "가 쪽", "set": {"clues": [{"t": "pt", "p": [0, 0], "label": "가 쪽"}]}}, {"label": "나 쪽", "set": {"clues": [{"t": "pt", "p": [9, 9], "label": "나 쪽"}]}},
            {"label": "둘 다 아님", "set": {"clues": [{"t": "not", "label": "둘 다 아님"}]}}]

    def dir_asks():                                       # 74-063: 자동차전용도로에서 좁혀진 뒤 「방향은 잘 모르겠어요」만 하는 시민
        st, v = S.turn({"id": "check-dirstop"}, {"line": {"who": "상담사", "text": "민원 콜센터입니다."}})
        out = []
        for said in ["양재대로 달리다가 봤어요, 갓길이에요 사람들이 담배를 피워요", "번호는 못 봤어요", "잘 못 봤어요", "둔촌동역 근처예요", "잘 못 봤어요", "백제추어탕 옆이에요"] + ["방향은 잘 모르겠어요"] * 3:
            st, v = S.turn(st, {"line": {"who": "시민", "text": said}})
            q = v["question"]
            out.append(q and q["id"])
            if not q or v["confirmed"]:
                break
            st, _ = S.turn(st, {"line": {"who": "상담사", "text": q["say"]}})
        return out

    looks = {"dupshop": lambda: len(L.resolve(S.gaz.norm("아트박스 강남점"))["x"]),      # 가게 자료에 82m 떨어진 두 줄
             "dunnoboth": lambda: ([c["t"] for c in read("둘 다 잘 모르겠어요", "either", opts)["clues"]], [c["t"] for c in read("둘 다 아니에요", "either", opts)["clues"]]),
             "dirstop": lambda: dir_asks()[5:8]}
    want = {"dupshop": (1, 2), "dunnoboth": (([], ["not"]), (["not"], ["not"])), "dirstop": (["dir", "dir", "confirm"], ["dir", "dir", "dir"])}
    for sw, f in looks.items():
        on = sw in L.ON
        got = f()
        assert got == want[sw][0 if on else 1], (sw, on, got)
        if on:                                            # 그 스위치 하나만 끄면 지금 동작으로 돌아가는지
            L.ON.discard(sw)
            try:
                assert f() == want[sw][1], sw + ": 꺼도 결과가 같음"
            finally:
                L.ON.add(sw)
    print("  ✓ 덜 묻기: 같은 가게 두 줄은 한 곳 · 「둘 다 잘 모르겠어요」는 모름 · 좁혀진 뒤 방향 질문은 두 번까지"
          + (" — 켬, 하나씩 끄면 지금 동작" if all(s in L.ON for s in looks) else f" — 켠 것 {sorted(s for s in looks if s in L.ON)}"))


def chain_said():
    """(89번) chainref · handsaid: 켜져 있으면 그 동작을, 꺼져 있으면 main 동작을 보고, 켠 것은 하나씩 끄면 main 동작으로 돌아가는지 본다."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    L = S.L

    def chain():                                          # 왕십리역 r27: 「역 앞 스벅」 — 범위 둘레에 스타벅스가 다섯 곳
        cl = [{"t": "at", "k": S.gaz.norm("왕십리역"), "label": "왕십리역"}, {"t": "at", "k": S.gaz.norm("스타벅스"), "label": "스타벅스", "how": "가까이"}]
        return L.questions(L.infer(cl), cl, {"type": "parking"}, asked=("station", "mark"))[0]["id"]

    def said():                                           # 신촌 r12(코드 읽기): 셋째 말에서 넘길 때의 한 줄
        st, v = S.turn({"id": "check-handsaid"}, {"line": {"who": "상담사", "text": "민원 콜센터입니다."}})
        for line in ["신촌 세브란스병원 앞인데요, 버스정류장 쪽에 오토바이가 인도에 계속 서 있어요", "병원 정문 앞 버스정류장이요", "잘 모르겠어요. 병원 정문 바로 앞에 있는 정류장이에요"]:
            st, v = S.turn(st, {"line": {"who": "시민", "text": line}})
            if (v["question"] or {}).get("id") == "handoff":
                break
            st, _ = S.turn(st, {"line": {"who": "상담사", "text": v["question"]["say"]}})
        assert (v["question"] or {}).get("id") == "handoff", v["question"]
        return "아름다운미소" in (v["summary"]["go"] or "")

    looks, want = {"chainref": chain, "handsaid": said}, {"chainref": ("finer", "dist"), "handsaid": (False, True)}
    for sw, f in looks.items():
        on = sw in L.ON
        got = f()
        assert got == want[sw][0 if on else 1], (sw, on, got)
        if on:
            L.ON.discard(sw)
            try:
                assert f() == want[sw][1], sw + ": 꺼도 결과가 같음"
            finally:
                L.ON.add(sw)
    print("  ✓ 체인 가게 · 넘기는 말: 둘레에 여럿인 상표는 거리 질문의 기준이 아님 · 넘길 때는 시민이 말한 이름만"
          + (" — 켬, 하나씩 끄면 main 동작" if all(s in L.ON for s in looks) else f" — 켠 것 {sorted(s for s in looks if s in L.ON)}"))


def free_text():
    """대본에 없는 곳 · 다른 일: 저장된 Solar 읽기가 없어도 코드가 읽어 끝까지 간다(서울 전체 지명 표)."""
    st, view = turn({"id": "check-free"}, line={"who": "상담사", "text": "인사"})
    st, view = turn(st, line={"who": "시민", "text": "강남역 11번 출구 바로 앞에 누가 쓰레기를 잔뜩 버리고 갔어요"})
    st, view = turn(st, phase="model")
    assert view["read_how"] == "nosaved" and view["done"] and view["question"]["id"] == "same" and "버스 정류장" in view["question"]["say"], view["question"]
    opt = next(o for o in view["question"]["options"] if "지하철 출구" in o["label"])      # 같은 이름의 버스 정류장이 42m 옆에 있다: 지하철 출구를 고른다
    st, view = turn(st, set=opt["set"], label=opt["label"])
    assert view["done"] and view["question"]["id"] == "confirm" and "강남역 11번 출구" in view["question"]["say"], view["question"]
    st, view = turn(st, line={"who": "시민", "text": "네 맞아요"})
    assert view["confirmed"] and "강남구청 청소" in view["route"]["hit"]["to"] and view["matter"]["scope"] == "out", (view["route"], view["matter"])
    st, view = turn({"id": "check-brand"}, line={"who": "시민", "text": "뚝섬역 근처 스타벅스 앞이에요. 가로등이 꺼져 있어요"})
    assert view["radius"] < 400 and view["matter"]["type"] == "light" and "스타벅스" in view["chips"], (view["radius"], view["matter"], view["chips"])
    st, view = turn({"id": "check-none"}, line={"who": "시민", "text": "여보세요 뭐 좀 물어보려고요"})
    assert not view["heat"]["pts"] and view["question"]["id"] in ("what", "where")
    print("  ✓ 대본에 없는 곳(강남역 출구 · 뚝섬역 스타벅스)도 코드만으로 읽어 좁힌다")


def alias():
    """별명 저장: 지명 표에 없는 이름은 못 알아듣다가, 확인받은 자리에 별명을 붙이면 다음 통화에서 그 이름 하나로 그 둘레가 된다."""
    words = "느티그늘쉼터골목 바로 앞인데요, 누가 쓰레기를 잔뜩 버리고 갔어요"
    st, view = turn({"id": "check-alias-1"}, line={"who": "시민", "text": words})
    assert view["radius"] is None, view["radius"]
    try:
        call("/api/alias", {"name": "<b>", "at": [127.04, 37.54]})
        raise AssertionError("꼴이 다른 별명을 받음")
    except urllib.error.HTTPError as e:
        assert e.code == 400
    assert call("/api/alias", {"name": "느티그늘쉼터골목", "at": [127.0441, 37.5443]})["ok"]
    st, view = turn({"id": "check-alias-2"}, line={"who": "시민", "text": words})
    assert view["radius"] is not None and view["radius"] <= 80 and "느티그늘쉼터골목" in view["chips"], (view["radius"], view["chips"])
    print("  ✓ 별명 저장: 저장 뒤 다음 통화에서 그 이름 하나로", view["radius"], "m")


OLD_REC = {"id": "check-old", "sample": False, "at": 0, "matter": "쓰레기 무단투기", "go": "옛 기록", "bunji": None, "point": [127.0, 37.55], "range": "반지름 약 30m", "range_m": 30,
           "scope": "out", "law": None, "cites": [], "scope_why": None, "to": "동작구청 청소 담당 부서", "basis": "확인", "place": "길", "log": [{"status": "filed", "at": 0}]}      # 대화 칸이 생기기 전 꼴의 기록
BAD = '<img src=x onerror="window.__x=1">\'"&<script>alert(1)</script>'      # 꺾쇠 · 따옴표가 든 글: 저장은 그대로, 화면은 글자로만


def talk_render(bad):
    """화면이 그때 나눈 대화를 글자로만 그리는지: call.js의 esc · bubble · talkHtml을 node로 그대로 돌려, 꺾쇠 · 따옴표가 태그 · 속성이 되지 않는지 본다."""
    node = shutil.which("node")
    if not node:
        print("  - 대화 글자 시험은 node가 없어 건너뜀(저장 쪽 시험은 위에서 함)")
        return
    src = (HERE / "web" / "call.js").read_text(encoding="utf-8")
    pick = lambda pat: re.search(pat, src, re.S).group(0)      # noqa: E731
    code = "\n".join([pick(r"const esc = [^\n]*\n"), pick(r"function bubble\(.*?\n}\n"), pick(r"function talkHtml\(.*?\n}\n"),
                      "const K = () => new Proxy({}, { get: (o, k) => String(k) });",
                      f"process.stdout.write(JSON.stringify(talkHtml([{{ w: '시민', t: {json.dumps(bad)}, v: 'type' }}, {{ w: '상담사', t: 'x', v: 'auto' }}])));"])
    out = json.loads(subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30, check=True).stdout)
    assert "<img" not in out and "<script" not in out and 'onerror="' not in out and "&lt;img" in out and "&lt;script&gt;" in out and out.count('<li class="ln') == 2, out


def records(done):
    """상담 기록: 예시 기록은 넘길 곳 · 조례 안팎을 표에서 채워 오고, 위치를 확인받은 통화만 쌓이며, 처리 상태는 정해진 차례로만 바뀐다(되돌리기 없음)."""
    d = call("/api/records")
    nxt, samples = d["next"], [r for r in d["records"] if r["sample"]]
    assert all(len(r["talk"]) >= 4 and r["talk"][0]["w"] == "상담사" and r["talk"][-1]["w"] == "상담사" and r["to"].split(" · ")[0] in r["talk"][-1]["t"] for r in samples), "예시 기록의 그때 나눈 대화(인사 · 맺음말의 넘길 곳)"
    assert len(samples) >= 10 and all(r["to"] and "{" not in r["to"] and r["scope"] in ("in", "out", "cand") and r["point"] and r["go"] and r["range"] and r["status"] in nxt for r in samples), "예시 기록이 비었거나 표에서 채워지지 않음"
    assert {r["status"] for r in samples} == set(nxt) and all((r["scope"] == "in") == bool(r["law"]) for r in samples), "예시 기록의 상태 · 조례 칸"
    post = lambda body: call("/api/records", body)      # noqa: E731
    def refused(body):
        try:
            post(body)
        except urllib.error.HTTPError as e:
            return e.code == 400
        return False
    st, _ = turn({"id": "check-rec-open"}, line={"who": "시민", "text": "강변북로에 고양이가 차에 치여서 죽어 있어요."})
    assert refused({"op": "save", "state": st, "status": "filed"}), "위치를 확인받기 전 통화가 기록에 쌓임"
    recs = post({"op": "save", "state": done, "status": "filed"})["records"]
    top = recs[0]
    assert top["id"] == done["id"] and not top["sample"] and top["status"] == "filed" and "서울시설공단" in top["to"] and top["go"] and top["point"], f"확인받은 통화가 맨 위에 쌓이지 않음 {top}"
    assert [(x["w"], x["t"]) for x in top["talk"]] == [("상담사" if x["who"] == "상담사" else "시민", x["text"]) for x in done["lines"]] and top["talk_cut"] == 0, "그때 나눈 대화가 통화의 줄과 다름"
    recs = post({"op": "save", "state": done, "status": "sent"})["records"]
    assert sum(r["id"] == done["id"] for r in recs) == 1 and recs[0]["status"] == "sent" and [x["status"] for x in recs[0]["log"]] == ["filed", "sent"], "같은 통화가 두 건이 되거나 넘김이 안 적힘"
    assert refused({"op": "status", "id": done["id"], "status": "filed"}), "넘긴 기록을 접수됨으로 되돌림"
    for s in ("recall", "doing", "closed"):
        assert post({"op": "status", "id": done["id"], "status": s})["records"][0]["status"] == s, s
    assert all(refused({"op": "status", "id": done["id"], "status": s}) for s in nxt), "끝난 기록의 상태가 바뀜"
    long = dict(done, id="check-rec-talk", lines=[{"who": "시민", "text": "나" * 500, "via": "type"}] * 60 + [{"who": "시민", "text": BAD, "via": "type"}, {"who": "시민", "text": "가" * 5000, "via": "type"}])
    t = next(r for r in post({"op": "save", "state": long, "status": "filed"})["records"] if r["id"] == "check-rec-talk")
    assert t["talk"][-2]["t"] == BAD and len(t["talk"][-1]["t"]) == 500 and len(t["talk"]) <= 80 and sum(len(x["t"]) for x in t["talk"]) <= 20_000 and t["talk_cut"] > 0, (len(t["talk"]), t["talk_cut"])      # 저장은 글 그대로, 한 줄 · 줄 수 · 자 수 상한
    talk_render(BAD)
    first = next(r for r in samples if r["status"] == "filed")
    assert refused({"op": "status", "id": first["id"], "status": "doing"}), "넘기기 전에 처리 중으로 바뀜"
    recs = post({"op": "reset"})["records"]
    assert all(r["sample"] for r in recs) and next(r for r in recs if r["id"] == first["id"])["status"] == "filed", "처음 상태로 되돌리지 못함"
    print(f"  ✓ 상담 기록: 예시 {len(samples)}건(표에서 넘길 곳 채움) · 확인받은 통화만 쌓임 · 상태는 정해진 차례로만 · 처음 상태로 · 그때 나눈 대화(상한 · 글자로만 · 옛 꼴 읽기)")


def fix_and_copy(done):
    """「일」 고치기(57번 6): 상담사가 고른 일이 읽은 일을 이기고 통화 글 · 단서 · 질문 기록은 그대로다. 복사 글(57번 5)은 받는 사람의 차례(일 → 번지수 → 찾아가는 말)에 민원인이 한 말 · 연락처 줄."""
    view = call("/api/view", {"state": done})["view"]
    rows = [x.split(": ", 1)[0] for x in view["summary"]["copy"].split("\n")]
    assert rows[:4] == ["일", "번지수", "찾아가는 말", "민원인이 한 말"] and rows[-2:] == ["민원을 받은 곳", "처음 접수한 담당자"], f"복사 글 차례 {rows}"
    assert view["summary"]["said"].startswith("롯데월드타워 근처 길가") and "010" not in view["summary"]["copy"], view["summary"]["said"]
    st, fixed = turn(done, fix="carcass")
    assert fixed["read_how"] == "fix" and fixed["matter"]["type"] == "carcass" and fixed["route"]["scope"] == "out" and "청소" in fixed["route"]["hit"]["to"], (fixed["matter"], fixed["route"])
    assert st["lines"] == done["lines"] and st["asked_log"] == done["asked_log"] and fixed["radius"] == view["radius"], "일 고치기가 통화 글 · 질문 기록 · 범위를 바꿈"
    # 확인 · 넘긴 뒤에 고쳐도 상담 기록이 새 일 · 새 담당 부서로(PR #120 리뷰 P1). 화면은 고친 뒤 같은 상태로 다시 저장한다.
    # 새 일에 더 물을 것이 생기면(동물 사체 → 「차로 위입니까」) 확인이 풀리고, 답하고 다시 확인받은 뒤 저장한다. 처리 기록은 그대로
    call("/api/records", {"op": "save", "state": done, "status": "filed"}); call("/api/records", {"op": "save", "state": done, "status": "sent"})
    assert fixed["question"]["id"] == "lane" and not fixed["confirmed"], fixed["question"]
    for _ in range(4):
        q = fixed["question"]
        if q is None:
            break
        opt = next(o for o in q["options"] if o["set"].get("confirm") is True) if q["id"] == "confirm" else q["options"][0]
        st, fixed = turn(st, set=opt["set"], label=opt["label"])
    rec = next(r for r in call("/api/records", {"op": "save", "state": st, "status": "sent"})["records"] if r["id"] == done["id"])
    assert fixed["confirmed"] and rec["matter"].startswith("동물 사체") and "청소" in rec["to"] and [x["status"] for x in rec["log"]] == ["filed", "sent"], rec
    st2, v2 = turn(done, fix="litter")      # 더 물을 것이 없는 일이면 확인이 그대로라 바로 다시 저장된다
    rec2 = next(r for r in call("/api/records", {"op": "save", "state": st2, "status": "sent"})["records"] if r["id"] == done["id"])
    assert v2["confirmed"] and rec2["matter"].startswith("쓰레기"), rec2
    call("/api/records", {"op": "reset"})
    assert turn(done, fix="없는일")[0]["fix"] is None and turn({**done, "fix": ["stray"]}, fix=None)[0]["fix"] is None, "표에 없는 일을 받음"
    print("  ✓ 일 고치기: 유기 동물 → 동물 사체로 고르면 넘길 곳이 청소 쪽 · 6종 밖으로, 통화 글 · 범위는 그대로 · 복사 글은 일 → 번지수 → 찾아가는 말 차례")


def refs(text):      # 참고 자료 칸의 값(web/refs.json)이 원본(조례 원문 · 넘길 곳 표)과 글자로 맞는지. 원본이 바뀌었는데 tools/build_refs.py를 다시 돌리지 않았으면 여기서 걸린다
    d = json.loads(urllib.request.urlopen(BASE + "/refs.json", timeout=5).read().decode("utf-8"))
    ords = {o["name"]: o for o in json.loads((HERE.parents[1] / "engine" / "data" / "ordinances.json").read_text(encoding="utf-8"))}
    types = json.loads((HERE / "data" / "routes.json").read_text(encoding="utf-8"))["types"]
    sp = lambda s: re.sub(r"\s+", " ", re.sub(r"\s*<(개정|신설)[^>]*>", "", s))      # noqa: E731
    for k, v in d["types"].items():
        assert v["scope"] == types[k]["scope"] and v["routes"] == [{kk: r[kk] for kk in ("class", "scope", "law") if kk in r} for r in types[k]["routes"]], f"참고 자료: {k}의 갈래가 routes.json과 다름(tools/build_refs.py를 다시 돌릴 것)"
    rows = lambda sec: {r[0] for t in text["text"]["sections"].get(sec, {"tables": []})["tables"] for r in t["rows"]}      # noqa: E731
    R = {r[0]: r[1] for t in text["text"]["sections"].get("참고 자료", {"tables": []})["tables"] if t["head"][0] == "항목" for r in t["rows"]}
    n, words = 0, set()      # words = refs.json이 가리키는 문구 파일 「참고 자료」 항목(사람이 쓴 글은 refs.json이 아니라 문구 파일에, PR #114 리뷰)
    for k, items in d["refs"].items():
        assert k in types and items, f"참고 자료: 표에 없는 일 {k}"
        for x in items:
            n += 1
            if not x.get("law"):
                assert x["kind"] in ("gal", "absent") and set(x) == {"kind", "code" if x["kind"] == "gal" else "key"}, f"참고 자료: {k} {x}(글은 문구 파일에, refs.json에는 이름만)"
                words |= {f"갈래 {x['code']}", f"처리 기관 {x['code']}"} if x["kind"] == "gal" else {x["key"]}
                continue
            o = ords[x["law"]]
            whole = sp(" ".join([a["text"] for a in o["articles"]] + [a["text"] for a in o["annexes"]]))
            assert x["effective"] == o["effective_date"] and x["url"] == o["source_url"], f"참고 자료: {k} 시행일 · 주소"
            ok = all(c in whole for row in x["rows"] for c in row) if x["kind"] == "table" else sp(x["text"]) in whole
            assert ok, f"참고 자료: {k} {x['where']}가 조례 원문과 다름"
            if x["kind"] == "table":      # 표 이름은 원문 별표 제목 · 머리 칸 수는 원문 표의 칸 수와 같아야 한다
                assert any(x["where"] == a["label"] + " " + re.sub(r"\s*\([^)]*관련\)\s*$", "", a["title"]) for a in o["annexes"]), f"참고 자료: {k} 표 이름 {x['where']}가 별표 제목과 다름"
                words |= {x["head"], x["unit"]} | ({x["more"]} if x.get("more") else set())
                assert x["head"] in R and all(len(R[x["head"]].split(" · ")) == len(row) for row in x["rows"]), f"참고 자료: {k} 표 머리 「{R.get(x['head'])}」의 칸 수가 원문 표와 다름"
    need = {"참고 자료": words, "접수 카드": {"참고 제목", "출처", "출처 표", "출처 조례", "출처 갈래", "같은 줄 묶음", "6종 같음", "단위", "갈래 줄", "더 있음", "위치 대기", "6종 밖 근거",
                                          "민원인 말", "연락처", "가상 번호 표시", "번호 없음", "일 고치기", "일 고치기 설명", "일 고침 표시"},      # 61번 화면 고침 묶음에서 새로 쓴 말
            "일의 종류와 갈림": {"답 대기", "조항 누르기", "답으로", "자리", "조례", "넘길 곳", "구 모름", "공원 모름", "답 펼치기", "답 접기", "답 복사", "답 기다림", "답 지난 시간", "답 보통 시간", "초안 표시"},
            "통화 글": {"받기 안내", "다음 전화", "기록 보기", "가상 흐름"}, "이렇게 물어보세요": {"화면 설명", "끝 안내"}}
    tel = {r[0]: r[1] for t in text["text"]["sections"].get("발신 번호", {"tables": []})["tables"] for r in t["rows"]}      # 가상 번호는 가운데를 가린 꼴로만(온전한 번호를 두지 않는다)
    assert set(tel) >= set(EXPECT) | {"pothole"} and all(re.fullmatch(r"010-\*{4}-\d{4}", v) for v in tel.values()), f"발신 번호 표 {tel}"
    for sec, keys in need.items():
        assert keys <= rows(sec), f"문구 파일 {sec} 표에 없는 말: {keys - rows(sec)}"
    print(f"  ✓ 참고 자료: 일 {len(d['refs'])}가지 · 값 {n}개가 조례 원문 · 넘길 곳 표와 맞음, 새 문구 {sum(map(len, need.values()))}개가 문구 파일에 있음")


def switches():
    """길가 흡연 · 대여소 킥보드 스위치(72번)의 판단을 서버 함수로 바로 본다(모델 · 엔진 호출 없음). 켬 · 끔 어느 쪽으로 띄워도 그 값대로 본다.
    킥보드 스위치가 하는 일은 하나: 킥보드가 공공자전거 구역에 세워졌으면 그 밖의 일 · 모름을 자전거 일로 올리고 엔진 물음을 조례의 말로 쓴다. 나머지는 스위치를 끈 결과 그대로."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    st = lambda *said: {"turns": [{"said": t, "asked": None if n == 0 else {"id": "where"}} for n, t in enumerate(said)]}      # noqa: E731
    single = {"따릉이 거치대에 킥보드가 세워져 있어요": "dock", "대여소에 킥보드가 세워져 있어요": "dock", "누가 킥보드를 따릉이 자리에 세워 놓고 갔어요": "dock",
              "공공자전거 거치대 사이에 킥보드가 끼어 있어요": "dock", "따릉이 대여소에 전동 킥보드가 세워져 있어서 따릉이를 못 빼요": "dock",
              "따릉이가 넘어져 있고 킥보드도 대여소에 세워져 있어요": "dock", "자전거를 타고 가다가 대여소에 킥보드가 세워진 걸 봤어요": "dock",
              "아파트 자전거 거치대에 킥보드가 세워져 있어요": None, "거치대에 킥보드가 세워져 있어요": None, "학교 거치대에 킥보드가 꽂혀 있는데 따릉이도 못 세워요": None,
              "따릉이 대여소 옆 길에 킥보드가 쓰러져 있어요": None, "자전거도로에 킥보드가 쓰러져 있어요": None, "따릉이 대여소에 전동 스쿠터가 세워져 있어요": None,      # 전동 스쿠터는 킥보드로 보지 않는다
              "길가에 자전거랑 킥보드가 몇 달째 세워져 있어요": None, "킥보드 타고 가다가 거치대 옆에 방치된 자전거를 봤어요": None,
              "따릉이 대여소에 킥보드 세운 사람이 담배를 피워요": None}      # 다른 일(흡연)의 배경
    for said, w in single.items():
        assert S.kick_of(st(said)) == (w if S.KICK_DOCK else None), f"킥보드 판단 {said!r} → {S.kick_of(st(said))} (기대 {w})"
    for said in (("거치대에 킥보드가 꽂혀 있어요", "따릉이 대여소 앞이에요"), ):      # 대여소 말이 다른 차례에 나와도
        assert S.kick_of(st(*said)) == ("dock" if S.KICK_DOCK else None)
    for said in (("길에 자전거가 몇 달째 버려져 있어요", "옆에 킥보드도 하나 쓰러져 있고요"), ("길에 자전거가 몇 달째 버려져 있어요", "킥보드 세워진 데 옆이에요"),      # 리뷰 4 · 5차
                 ("길에 자전거 한 대가 몇 달째 버려져 있어요", "공유 킥보드 세워진 데 옆이에요"), ("자전거는 몇 달째 그대로 있어요", "공유 킥보드 세워진 데 옆이에요"),
                 ("방치 자전거 신고하려고요", "공유 킥보드 세워진 데 옆이에요")):
        assert S.kick_of(st(*said)) is None, said                                       # dock이 아니면 스위치는 아무것도 하지 않는다

    # 킥보드 갈림 표: (원래 판정) × (킥보드 말) × (자리) × (자전거를 어떻게 말했나). 칸마다 「일의 종류」와 「엔진 물음을 조례의 말로 바꾸나」를 본다.
    # 스위치가 하는 일은 하나: 킥보드가 공공자전거 구역에 세워졌으면(dock) 그 밖의 일 · 모름을 자전거 일로 올리고 물음을 바꾼다. 나머지 칸은 모두 스위치를 끈 결과와 같다.
    places = {"공공자전거 구역": "따릉이 대여소에", "일반 거치대": "아파트 자전거 거치대에", "길": "길에"}
    bikes = {"자전거 말 없음": None, "자전거가": "자전거가 몇 달째 방치돼 있어요", "자전거 한 대가": "자전거 한 대가 몇 달째 방치돼 있어요",
             "자전거는": "자전거는 몇 달째 그대로 있어요", "조사 없음": "방치 자전거 신고하려고요"}      # 뒤의 셋은 리뷰 5차가 든 말투(「버려져」는 쓰레기 일의 낱말이라 표 밖 위 줄에서 봄)
    cells = 0
    for kind in ("bike", "other", "smoking"):
        for pos in ("없음", "대상", "타는 말", "다른 차례"):
            for pname, at in places.items():
                for bname, bike in bikes.items():
                    subj = bike or "뭐가 쓰러져 있어요"
                    told = {"없음": f"{at} {subj}", "다른 차례": f"{at} {subj}", "타는 말": f"킥보드 타고 가다 봤는데 {at} {subj}",
                            "대상": f"{at} 킥보드가 세워져 있어요" if not bike else f"{bike} {at} 킥보드도 세워져 있어요"}[pos]
                    if kind == "smoking":
                        told = "담배 피우는 사람도 있고 " + told
                    said = [told] + ([f"{at} 공유 킥보드도 세워져 있어요"] if pos == "다른 차례" else [])
                    call_ = {"id": "grid", "turns": [{"said": t, "asked": None if n == 0 else {"id": "where"}, "model": None,
                                                     "code": {"clues": [], "matter": {"type": kind} if n == 0 else {}}} for n, t in enumerate(said)]}
                    got = S.understood(call_)[1].get("type")
                    was, S.KICK_DOCK = S.KICK_DOCK, False
                    off = S.understood(call_)[1].get("type")       # 스위치를 끈 결과(main)
                    S.KICK_DOCK = was
                    dock = S.KICK_DOCK and pos in ("대상", "다른 차례") and pname == "공공자전거 구역" and kind != "smoking"
                    want_t = "bike" if dock and off in (None, "other", "bike") else off
                    assert got == want_t, f"킥보드 표 칸 (판정 {kind} · 킥보드 {pos} · {pname} · {bname}) {said} → {got} (기대 {want_t})"
                    assert S.kick_words(call_, got) == dock, f"킥보드 표 칸 엔진 물음 (판정 {kind} · 킥보드 {pos} · {pname} · {bname}) → {S.kick_words(call_, got)}"
                    cells += 1

    # 흡연 표지 표: (일의 종류) × (공원 안인가) × (담배 말) × (건물 안 · 금연거리 말) × (통화 상태) × (50m 안 정류장 · 출구). 칸마다 엔진에 보내는 장소를 본다.
    spots = {"정류장 가까이": {"cx": 653.6, "cy": -7996.1, "r": 30, "on_road": False}, "표지 없음": {"cx": 945.6, "cy": -7696.1, "r": 30, "on_road": False}}      # 서초구(72번 A1 · C1)
    states = {"찾는 중": (False, None), "좁혀짐(확인 질문)": (True, None), "좁혀짐 · 확인받음": (True, "confirmed"), "넓은 범위째 확인": (False, "confirmed"),
              "넘김(좁혀졌던 자리를 아니라 함)": (True, "handoff"), "넘김(넓은 범위)": (False, "handoff")}
    smoke_cells = 0
    for kind in ("smoking", "other"):
        for park in (False, True):
            route = {"type": kind, "class": "공원" if park else None, "class_name": "서울숲" if park else None}
            for smoke in (True, False):
                for skip in ("", " 건물 안이에요", " 구청에서 금연거리로 정한 곳이에요"):
                    said = [("버스 정류장 앞에서 담배를 피워요" if smoke else "버스 정류장 앞에서 불을 피워요") + skip]
                    for sname, (done, ended) in states.items():
                        for spot, R in spots.items():
                            base = S.place_phrase(R, route)
                            got = S.engine_place(R, route, done, ended, said)
                            if not (S.SMOKE_NEAR and kind == "smoking" and not park) or not smoke or skip:
                                want_p = base                                 # 스위치 밖 · 공원 · 담배 말 없음 · 건물 안 · 금연거리: 지금처럼
                            elif sname == "찾는 중":
                                want_p = None                                 # 아직 부르지 않음
                            elif not done or ended == "handoff":
                                want_p = base                                 # 넓은 범위째 확인 · 넘김: 표지 없이
                            else:
                                want_p = base.replace("의 길가", "의 국립국악원 버스 정류장 가까이 길가") if spot == "정류장 가까이" else base
                            assert got == want_p, f"흡연 표 칸 ({kind} · 공원 {park} · 담배 말 {smoke} · {skip.strip() or '빼는 말 없음'} · {sname} · {spot}) → {got!r} (기대 {want_p!r})"
                            smoke_cells += 1
    print(f"  ✓ 흡연 표지 · 킥보드 판단(켬: 흡연 {S.SMOKE_NEAR} · 킥보드 {S.KICK_DOCK}): 킥보드 낱통화 {len(single) + 3} · 킥보드 표 {cells}칸 · 흡연 표 {smoke_cells}칸")


def bind_choice():
    """(choicebind, 79번) 동규 시험 통화(11-21, 강남역): 시민은 보기에 없는 다른 곳의 이름을 댔는데 Solar가 보기 하나를 골랐다.
    Solar 자리에 그 통화의 날 답(보기 고르기)을 넣어 서버의 turn을 그대로 돈다(모델 · 엔진 호출 없음). 켬 · 끔 어느 쪽으로 띄워도 그 값대로 본다."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    on = "choicebind" in S.L.ON

    def solar(system, user, schema):          # 그 통화의 Solar: 코드가 찾은 이름은 「근처」, 보기는 강남이룸안과의원(있으면) 아니면 1번 — 시민이 말하지 않은 보기
        opts = user.split("[상담사가 방금 물은 질문의 보기]")[1].split("[코드가 찾은 이름]")[0]
        names = user.split("[코드가 찾은 이름]")[1].split("[시민이 방금 한 말]")[0]
        ids = re.findall(r"^- (m\d+) \|", names, re.M)
        ch = next(iter(re.findall(r"^- (o\d+) \| 강남이룸안과의원$", opts, re.M) + re.findall(r"^- (o1) \|", opts, re.M)), "없음")
        return {"type": "모름", "animal": "모름", "alive": "모름", "leash": "모름", "places": [{"id": i, "rel": "근처", "how": "모름"} for i in ids],
                "choice": ch, "confirm": "없음", "outside": False, "said_place": ""}
    mode, real, eng = S.MODE, S._solar, os.environ.get("CALL_NO_ENGINE")
    os.environ["CALL_NO_ENGINE"] = "1"
    try:
        S._solar = solar
        st, view = S.turn({"id": "check-bind"}, {"line": {"who": "상담사", "text": "네, 민원 콜센터입니다. 무엇을 도와드릴까요?"}})
        for said in ("여기 쓰래기가 너무 많이 버려져 있어요", "여기... 지금 강남역 주변이요", "아트박스가 보여요", "강남새로치과의원이 보여요"):
            st, view = S.turn(st, {"line": {"who": "시민", "text": said}})
            S.MODE = "live"
            st, view = S.turn(st, {"phase": "model"})
            S.MODE = mode
            if view["question"]:
                st, view = S.turn(st, {"line": {"who": "상담사", "text": view["question"]["say"]}})
    finally:
        S.MODE, S._solar = mode, real
        os.environ.pop("CALL_NO_ENGINE") if eng is None else os.environ.update(CALL_NO_ENGINE=eng)
    q, where = view["question"] or {}, view["summary"]["where"] or ""
    if on:
        assert q.get("id") != "confirm" and ("강남새로치과의원" in where or "아트박스" in where) and "강남이룸안과의원" not in where, (q.get("say"), where)      # 시민이 댄 곳(아트박스 · 거기서 50m의 새로치과의원)에 머문다. dupshop을 켜면 아트박스 강남점 두 줄이 한 곳이 되어 「아트박스 앞」(89번)
    else:
        assert q.get("id") == "confirm" and "강남이룸안과의원" in q.get("say", ""), (q.get("say"), where)      # 끄면 그 통화 그대로: 700m 떨어진 보기로 확정 질문
    sh = lambda said: S.shortlist(said, None)      # noqa: E731
    assert S._other_place("아트박스가 보여요", "비타바른이치과의원", sh("아트박스가 보여요"))
    assert S._other_place("비틀비틀 보여요", "마스터당구장", sh("비틀비틀 보여요"))      # 평가 묶음 74-P17(Solar 길): 같은 꼴로 2km 떨어진 곳 되묻기
    for said, label in (("비타바른이치과의원 옆이에요", "비타바른이치과의원"), ("첫 번째 거요", "비타바른이치과의원"), ("강남역 쪽 치과요", "비타바른이치과의원"),
                        ("아트박스 옆에 비타바른이치과의원이요", "비타바른이치과의원"), ("구리 방향이요", "구리 방향"),
                        ("스벅 보여요", "스타벅스 강남역점"), ("롯데리아 옆 GS25요", "GS25 역삼점"), ("주민센터 앞이에요", "역삼1동주민센터")):
        assert not S._other_place(said, label, sh(said)), (said, label)      # 보기 이름을 말함(줄임말 · 상표 · 지점 포함) · 다른 이름 없음 · 넓은 이름(역)만: Solar의 고르기를 그대로 받는다
    assert S._other_place("올리브영 명동역점이 보여요", "용하다한의원", sh("올리브영 명동역점이 보여요"))      # 80번 c03 5번째 차례(Solar 길): 같은 꼴
    assert S._other_place("방이역이요", "거여역", sh("방이역이요"), "station") == ("stationbind" in S.L.ON)      # (stationbind) 역 질문에 댄 역 이름은 「다른 곳」(80번 p08). 끄면 역은 넓은 이름이라 보지 않는다
    assert not S._other_place("방이역이요", "거여역", sh("방이역이요"), "finer")                               # 역 질문이 아니면 켜도 역은 넓은 이름
    print(f"  ✓ Solar가 시민이 말하지 않은 보기를 고름(켬 {on}): {'시민이 댄 곳에 머묾' if on else '그 통화 그대로 700m 떨어진 보기로 확정 질문'} · 보기 이름을 말했거나 다른 이름이 없으면 고르기를 받음")


def reread_guards():
    """(codekeep · keeptype, 79번) Solar 다시 읽기가 코드가 맞게 읽은 것을 덮는 꼴 둘(80번 c18 · c03). Solar 자리에 그 통화의 날 답을 넣어 서버의 turn을 그대로 돈다. 켬 · 끔 어느 쪽이든 그 값대로 본다."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    N = {"type": "모름", "animal": "모름", "alive": "모름", "leash": "모름", "choice": "없음", "confirm": "없음", "outside": False, "said_place": ""}

    def run(turns):
        q = []

        def solar(system, user, schema):           # 이름으로 준 단서를 목록의 id로
            raw = q.pop(0)
            ids = dict((n.strip(), i) for i, n in re.findall(r"^- (m\d+) \| ([^|]+)", user, re.M))
            ch = next(iter(re.findall(rf"^- (o\d+) \| {re.escape(raw['pick'])}$", user, re.M)), "없음") if raw.get("pick") else raw.get("choice", "없음")      # 보기를 이름으로
            return {**{k: v for k, v in raw.items() if k not in ("by_name", "pick")}, "choice": ch, "places": [{"id": ids[nm], "rel": rel, "how": how} for nm, rel, how in raw["by_name"]]}
        mode, real, eng = S.MODE, S._solar, os.environ.get("CALL_NO_ENGINE")
        os.environ["CALL_NO_ENGINE"] = "1"
        try:
            S._solar = solar
            st, view = S.turn({"id": "check-reread"}, {"line": {"who": "상담사", "text": "네, 민원 콜센터입니다. 무엇을 도와드릴까요?"}})
            for said, raw in turns:
                st, view = S.turn(st, {"line": {"who": "시민", "text": said}})
                q.append(raw)
                S.MODE = "live"
                st, view = S.turn(st, {"phase": "model"})
                S.MODE = mode
                if view["question"]:
                    st, view = S.turn(st, {"line": {"who": "상담사", "text": view["question"]["say"]}})
        finally:
            S.MODE, S._solar = mode, real
            os.environ.pop("CALL_NO_ENGINE") if eng is None else os.environ.update(CALL_NO_ENGINE=eng)
        return st, view
    _, v18 = run([("안녕하세요 제가 지금 합정역 7번 출구 나와서 조금 걸어오면 파리바게뜨 있고 그 옆에 마라탕집 앞인데요 거기 트럭이 인도에 반쯤 걸쳐서 계속 서 있어서 사람들이 차도로 걸어 다녀요 위험해요",
                   dict(N, type="vendor", by_name=[["합정역 7번 출구", "지남", "모름"], ["파리바게뜨", "근처", "바로"]]))])
    if "codekeep" in S.L.ON:
        assert v18["radius"] <= 60 and "합정역 7번 출구" in (v18["summary"]["where"] or ""), (v18["radius"], v18["summary"]["where"])      # 코드가 읽은 「출구 있음」을 둔다
    else:
        assert v18["radius"] > 1000, v18["radius"]                                           # 끄면 그 통화 그대로: 출구를 거리 모를 「지남」으로 읽어 3km 넘게 넓어짐
    st, _ = run([("가게에서 물건을 인도에 잔뜩 내놔서 사람이 지나갈 수가 없어요", dict(N, type="vendor", by_name=[])), ("명동이에요", dict(N, by_name=[])),
                 ("명동역 6번 출구 나와서 밀리오레 앞이요", dict(N, type="other", by_name=[["명동역 6번 출구", "근처", "모름"], ["밀리오레", "근처", "바로"]]))])
    kind = S.understood(st)[1].get("type")
    assert kind == ("vendor" if "keeptype" in S.L.ON else "other"), kind                     # 켜면 자리만 말한 차례의 Solar 「그 밖의 일」이 적치물을 덮지 않음
    st, _ = run([("강남역 10번 출구요", dict(N, by_name=[["강남역 10번 출구", "근처", "모름"]])), ("길거리에서 스피커로 음악을 엄청 크게 틀어 놔서 시끄러워요", dict(N, type="noise", by_name=[])),
                 ("네? 스피커는 장소가 아니고요, 강남역 10번 출구 바로 앞이에요", dict(N, type="noise", by_name=[["강남역 10번 출구", "있음", "바로"]]))])      # 80번 c10: Solar는 소음 그대로인데 이 말의 대상(스피커)과 다시 맞추다 「그 밖의 일」
    k10 = S.understood(st)[1].get("type")
    assert k10 == ("noise" if "keeptype" in S.L.ON else "other"), k10
    _, v18b = run([("안녕하세요 제가 지금 합정역 7번 출구 나와서 조금 걸어오면 파리바게뜨 있고 그 옆에 마라탕집 앞인데요 거기 트럭이 인도에 반쯤 걸쳐서 계속 서 있어서 사람들이 차도로 걸어 다녀요 위험해요",
                    dict(N, type="vendor", by_name=[["합정역 7번 출구", "쪽", "모름"], ["파리바게뜨", "근처", "바로"]]))])      # 같은 통화를 Solar가 「출구 쪽」(둘레 450m)으로 읽은 번
    assert (v18b["radius"] <= 60) == ("codekeep" in S.L.ON), v18b["radius"]
    _, vc = run([("여기 쓰레기가 너무 많이 버려져 있어요", dict(N, type="litter", by_name=[])), ("강남역 근처요", dict(N, by_name=[["강남역", "근처", "모름"]])),
                 ("편의점 바로 앞이에요", dict(N, type="litter", by_name=[["위드미", "안", "모름"]]))])      # 81번 r01: 실제 Solar가 세 번 모두 첫 후보 「위드미」를 장소로 적음
    if "placebind" in S.L.ON:
        assert "위드미" not in vc["chips"] and vc["radius"] > 600, (vc["chips"], vc["radius"])      # 켜면 코드가 넓게 둔 「편의점 바로 옆」 그대로
    else:
        assert "위드미" in vc["chips"] and vc["radius"] < 400, (vc["chips"], vc["radius"])          # 끄면 그 통화 그대로 위드미 쪽으로 끌려감
    st12, v12 = run([("신촌 세브란스병원 앞인데요, 버스정류장 쪽에 오토바이가 인도에 계속 서 있어요", dict(N, type="other", by_name=[["세브란스병원앞", "근처", "모름"]])),
                     ("병원 정문 앞 버스정류장이요", dict(N, pick="세브란스병원앞", by_name=[["세브란스병원앞", "근처", "모름"]]))])      # 80번 c12: 종류만 말했는데 Solar가 후보 「세브란스병원앞」(실제 자리에서 140m 떨어진 다른 정류장)을 이름 칸 · 보기 칸 둘 다에
    labels = [c.get("label") for c in st12["turns"][-1]["model"]["clues"]]
    assert ("세브란스병원앞" in labels) != ("placebind" in S.L.ON), labels      # 켜면 이름 칸 · 보기 칸 어느 쪽으로도 그 후보가 들어가지 않음(끄면 들어감)
    print(f"  ✓ Solar 다시 읽기가 코드 읽기를 덮는 꼴(codekeep {'codekeep' in S.L.ON} · keeptype {'keeptype' in S.L.ON} · placebind {'placebind' in S.L.ON}): 합정역 출구 {v18['radius']}m · 「출구 쪽」으로 읽은 번 {v18b['radius']}m · 자리만 말한 차례 뒤 일 {kind} · {k10} · 「편의점 바로 앞」 {vc['radius']}m")


def seen_wide():
    """(seenwide, 79번 · 80번 c16) 「바로 앞에 뭐가 보이세요?」에 「○○ 보여요」만 답했는데 Solar가 그 보기를 고르면, 켜면 「바로 앞」(18m)이 아니라 「보임」 폭으로 받는다. 「바로 앞이에요」는 켜도 그대로."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    opt = {"label": "송파나루공원 서울놀이마당", "set": {"clues": [{"t": "pt", "p": [0.0, 0.0], "r": S.L.SIG["바로"], "label": "송파나루공원 서울놀이마당"}]}}
    real, mode = S._solar, S.MODE
    S._solar = lambda system, user, schema: {"type": "모름", "animal": "모름", "alive": "모름", "leash": "모름", "places": [], "choice": "o1", "confirm": "없음", "outside": False, "said_place": ""}
    S.MODE = "live"
    try:
        r = {}
        for said in ("서울놀이마당 보여요", "서울놀이마당 바로 앞이에요"):
            st = {"id": "check-seen", "lines": [{"who": "상담사", "text": "바로 앞에 뭐가 보이세요?"}, {"who": "시민", "text": said}], "turns": [{"said": said, "asked": {"id": "finer", "options": [opt]}}]}
            read, _, _ = S.model_read(st, [], "없음")
            r[said] = next(c["r"] for c in read["clues"] if c.get("label") == opt["label"])
    finally:
        S._solar, S.MODE = real, mode
    assert r["서울놀이마당 보여요"] == (S.L.SIG["보임"] if "seenwide" in S.L.ON else S.L.SIG["바로"]), r
    assert r["서울놀이마당 바로 앞이에요"] == S.L.SIG["바로"], r
    print(f"  ✓ 「○○ 보여요」만 답한 차례의 Solar 보기 고르기(seenwide {'seenwide' in S.L.ON}): 「보여요」 {r['서울놀이마당 보여요']:.0f}m 폭 · 「바로 앞이에요」 {r['서울놀이마당 바로 앞이에요']:.0f}m 폭")


def neg_keep():
    """(negkeep, 91번) Solar가 「아님」이라 답했는데 dropcheck가 받지 않은 이름(그 말에 「아니 · 말고 · 없 …」가 없음): 켜면 없던 말로 치고 코드가 읽은 그대로 둔다. 끄면 main 그대로 「있음 · 바로 앞」으로 뒤집혀 들어간다(88번 c14 이태원, 4.5km 튐)."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    said = "그건 모르겠고요, 바로 앞에 이태원폰마트라는 휴대폰 가게가 있어요"
    short = S.shortlist(said, None)
    mid = next(m["id"] for m in short if m.get("key") == "휴대폰가게")
    code = S.code_read(said, None, short, None)
    real, mode = S._solar, S.MODE
    S._solar = lambda system, user, schema: {"type": "모름", "animal": "모름", "alive": "모름", "leash": "모름", "places": [{"id": mid, "rel": "아님", "how": "바로"}], "choice": "없음", "confirm": "없음", "outside": False, "said_place": ""}
    S.MODE = "live"
    try:
        st = {"id": "check-neg", "lines": [{"who": "시민", "text": said}], "turns": [{"said": said, "asked": None}]}
        read, _, _ = S.model_read(st, short, "없음")
        merged = S._merge(code, read)
    finally:
        S._solar, S.MODE = real, mode
    phone = [c for c in merged["clues"] if c.get("k") == "휴대폰가게"]
    if "negkeep" in S.L.ON:
        assert phone and all(c.get("how") != "바로" for c in phone) and phone == [c for c in code["clues"] if c.get("k") == "휴대폰가게"], phone      # 코드가 읽은 그대로(「바로」 없음 — 먼 곳이면 튐 막기가 막는다)
    else:
        assert any(c.get("how") == "바로" for c in phone), phone                                                    # 끄면 main 그대로: 받지 않은 「아님」이 「바로 앞」으로
    print(f"  ✓ 받지 않은 Solar 「아님」(negkeep {'negkeep' in S.L.ON}): 「휴대폰 가게」 단서 {[(c.get('label'), c.get('how')) for c in phone]}")


def bridge_end():
    """(bridgeend, 91번) 「한남대교요 → 다리 위라 아무것도 없어요. 강남 쪽 끝이 더 가까워요」: 켜면 다리의 강남 쪽 끝 절반으로 읽어 다리 둘레에 머문다. 끄면 main 그대로 「강남역 쪽」으로 읽어 서초구 잠원동 수 km로 넓어진다(88번 r23)."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    st, view = S.turn({"id": "check-bridge-end"}, {"line": {"who": "상담사", "text": "네, 민원 콜센터입니다. 무엇을 도와드릴까요?"}})
    for said in ("한강 다리 위에서 차가 고장 나서 서 있어요", "한남대교요. 강남 쪽으로 가는 방향이요", "다리 위라 아무것도 없어요. 강남 쪽 끝이 더 가까워요"):
        st, view = S.turn(st, {"line": {"who": "시민", "text": said}})
        if view["question"]:
            st, view = S.turn(st, {"line": {"who": "상담사", "text": view["question"]["say"]}})
    if "bridgeend" in S.L.ON:
        assert view["radius"] <= 300 and "한남대교 강남 쪽 끝" in view["chips"], (view["radius"], view["chips"])
    else:
        assert view["radius"] > 1000, view["radius"]
    print(f"  ✓ 다리의 「○○ 쪽 끝」(bridgeend {'bridgeend' in S.L.ON}): 한남대교 「강남 쪽 끝이 더 가까워요」 → {view['summary']['where']} {view['radius']}m")


def hangul_say():
    """(hangulopt2, 90번 2절) 롯데월드타워 둘레 「바로 앞에 뭐가 보이세요?」: 켜면 말로 읽는 앞 넷이 모두 한글 이름이고, 보기는 끈 판과 같은 곳들(순서만 다름)이다. 끄면 main 그대로(읽는 넷에 영어 이름)."""
    os.environ.setdefault("CALL_MODE", "saved")
    sys.path.insert(0, str(HERE))
    import server as S
    L = S.L
    clues = [{"t": "at", "k": S.gaz.norm("롯데월드타워"), "how": "근처", "label": "롯데월드타워"}]
    R = L.infer(clues)
    x, y, w = L._sample(R)
    on = "hangulopt2" in L.ON
    q = L._q_marks(R, x, y, w, "finer", clues)
    L.ON.discard("hangulopt2")
    q0 = L._q_marks(R, x, y, w, "finer", clues)
    if on:
        L.ON.add("hangulopt2")
    said = S.say_options(q["options"])
    eng = [n for n in said if not re.search(r"[가-힣]", n)]
    assert sorted(o["label"] for o in q["options"]) == sorted(o["label"] for o in q0["options"]) and q["bits"] == q0["bits"], (q["options"], q0["options"])      # 같은 곳 · 같은 수 · 같은 몫
    assert bool(eng) != on, said
    print(f"  ✓ 말로 읽는 보기의 영어 이름(hangulopt2 {on}): 롯데월드타워 「바로 앞」 읽는 넷 {said}")


def main():
    tmp = Path(os.environ.get("TMPDIR", "/tmp"))
    env = {**os.environ, "CALL_MODE": "saved", "CALL_PORT": str(PORT), "CALL_REPLAY_SEC": "0", "CALL_ALIAS_FILE": str(tmp / f"call-check-alias-{os.getpid()}.json"),
           "CALL_RECORD_FILE": str(tmp / f"call-check-records-{os.getpid()}.json")}
    Path(env["CALL_RECORD_FILE"]).write_text(json.dumps({"added": [OLD_REC], "log": {}}, ensure_ascii=False), encoding="utf-8")      # 옛 꼴의 기록 하나를 둔 채로 띄운다
    server = subprocess.Popen([sys.executable, str(HERE / "server.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(150):
            try:
                text = call("/api/text")
                break
            except OSError:
                assert server.poll() is None, "서버가 뜨지 않음: " + server.stderr.read().decode()[-600:]
                time.sleep(0.1)
        else:
            raise AssertionError("서버가 15초 안에 뜨지 않음")
        assert any(r["id"] == "check-old" and "talk" not in r and r["status"] == "filed" for r in call("/api/records")["records"]), "대화 칸이 없는 옛 꼴의 기록을 읽지 못함"      # 다른 점검이 기록을 비우기 전에
        assert text["mode"] == "saved" and set(text["scripts"]) >= set(EXPECT) and text["places"] > 100000 and len(text["seoul"]) > 100
        html = urllib.request.urlopen(BASE + "/", timeout=5).read().decode("utf-8")
        assert 'id="ask"' in html and 'id="law"' in html and "call.js" in html      # 조례 근거 답 칸(말할 것 띠, 11-18 확정)
        buttons = [r[0] for t in text["text"]["sections"]["통화 장면"]["tables"] for r in t["rows"]]
        assert buttons == ["cat_street", "free"], f"장면 단추는 한 장면과 직접 통화만 {buttons}"      # 다른 대본은 주소로만(11-18)
        greeting = next(r[1] for t in text["text"]["sections"]["통화 글"]["tables"] for r in t["rows"] if r[0] == "인사")
        refs(text)
        ends = {name: play(name, text["scripts"][name], greeting) for name in EXPECT}
        chips_only("강변북로에 고양이가 차에 치여서 죽어 있어요.")      # 단추만으로 가려면 첫 말에 큰 장소는 있어야 한다
        free_text()
        field_fixes()
        partial_yes()
        partial_yes_table()
        yesno_reads()
        matter_repeat()
        alias()
        fix_and_copy(ends["cat_street"])
        records(ends["roadkill"])
        switches()
        hangul_say()
        bind_choice()
        neg_keep()
        bridge_end()
        reread_guards()
        seen_wide()
        edge_reads()
        ask_fixes()
        chain_said()
        ask_less()
        print("통화로 위치 좁히기 점검 통과")
    finally:
        server.terminate()
        server.wait(timeout=5)
        Path(env["CALL_ALIAS_FILE"]).unlink(missing_ok=True)
        Path(env["CALL_RECORD_FILE"]).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"점검 실패: {e}", file=sys.stderr)
        sys.exit(1)
