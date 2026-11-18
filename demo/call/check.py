"""통화로 위치 좁히기 점검: 서버를 저장된 답 방식으로 띄우고, 두 장면을 화면의 「대본 재생」과 같은 순서로 HTTP로 끝까지 돌려 본다.

    python3 demo/call/check.py          (열쇠 · 엔진 · 인터넷 없이 십여 초. 실패하면 종료 코드 1)

보는 것: 서버가 뜬다 → 대본의 말을 넣는다 → 코드가 바로 읽어 질문이 뜬다(①) → 저장된 Solar 읽기로 갈아 끼운다(②) → 범위가 줄어든다
        → 찾아갈 수 있을 만큼 좁혀지고 확인받는다 → 그때 담당 부서가 배정된다(6종 안 · 밖 갈림이 맞다) → 접수 카드가 나온다.
        단추만 눌러도, 대본에 없는 말(코드만으로 읽음)로도 끝까지 가는지 본다.
"""
import json
import re
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
    "cat_street": {"scope": "in", "to": "동작구청 동물보호", "where": ["상도1동주민센터"], "cite": "서울특별시 동물보호 조례 제10조 제1항", "kind": "radius", "r": 50},      # 화면 장면 단추의 두 고양이 장면(11-17)
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
        assert [(x["class"], x["basis"]) for x in dead][:3] == [("길", "확인"), ("시 공원", "추측"), ("자동차전용도로", "추측")] and "청소" in dead[0]["to"] and "서울시설공단" in dead[2]["to"], f"{name}: 사체 줄 {dead}"
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


def records(done):
    """상담 기록: 예시 기록은 넘길 곳 · 조례 안팎을 표에서 채워 오고, 위치를 확인받은 통화만 쌓이며, 처리 상태는 정해진 차례로만 바뀐다(되돌리기 없음)."""
    d = call("/api/records")
    nxt, samples = d["next"], [r for r in d["records"] if r["sample"]]
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
    recs = post({"op": "save", "state": done, "status": "sent"})["records"]
    assert sum(r["id"] == done["id"] for r in recs) == 1 and recs[0]["status"] == "sent" and [x["status"] for x in recs[0]["log"]] == ["filed", "sent"], "같은 통화가 두 건이 되거나 넘김이 안 적힘"
    assert refused({"op": "status", "id": done["id"], "status": "filed"}), "넘긴 기록을 접수됨으로 되돌림"
    for s in ("recall", "doing", "closed"):
        assert post({"op": "status", "id": done["id"], "status": s})["records"][0]["status"] == s, s
    assert all(refused({"op": "status", "id": done["id"], "status": s}) for s in nxt), "끝난 기록의 상태가 바뀜"
    first = next(r for r in samples if r["status"] == "filed")
    assert refused({"op": "status", "id": first["id"], "status": "doing"}), "넘기기 전에 처리 중으로 바뀜"
    recs = post({"op": "reset"})["records"]
    assert all(r["sample"] for r in recs) and next(r for r in recs if r["id"] == first["id"])["status"] == "filed", "처음 상태로 되돌리지 못함"
    print(f"  ✓ 상담 기록: 예시 {len(samples)}건(표에서 넘길 곳 채움) · 확인받은 통화만 쌓임 · 상태는 정해진 차례로만 · 처음 상태로")


def fix_and_copy(done):
    """「일」 고치기(57번 6): 상담사가 고른 일이 읽은 일을 이기고 통화 글 · 단서 · 질문 기록은 그대로다. 복사 글(57번 5)은 받는 사람의 차례(일 → 번지수 → 찾아가는 말)에 민원인이 한 말 · 연락처 줄."""
    view = call("/api/view", {"state": done})["view"]
    rows = [x.split(": ", 1)[0] for x in view["summary"]["copy"].split("\n")]
    assert rows[:4] == ["일", "번지수", "찾아가는 말", "민원인이 한 말"] and rows[-2:] == ["민원을 받은 곳", "처음 접수한 담당자"], f"복사 글 차례 {rows}"
    assert view["summary"]["said"].startswith("상도1동 주민센터 근처 골목") and "010" not in view["summary"]["copy"], view["summary"]["said"]
    st, fixed = turn(done, fix="carcass")
    assert fixed["read_how"] == "fix" and fixed["matter"]["type"] == "carcass" and fixed["route"]["scope"] == "out" and "청소" in fixed["route"]["hit"]["to"], (fixed["matter"], fixed["route"])
    assert st["lines"] == done["lines"] and st["asked_log"] == done["asked_log"] and fixed["radius"] == view["radius"], "일 고치기가 통화 글 · 질문 기록 · 범위를 바꿈"
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


def main():
    tmp = Path(os.environ.get("TMPDIR", "/tmp"))
    env = {**os.environ, "CALL_MODE": "saved", "CALL_PORT": str(PORT), "CALL_REPLAY_SEC": "0", "CALL_ALIAS_FILE": str(tmp / f"call-check-alias-{os.getpid()}.json"),
           "CALL_RECORD_FILE": str(tmp / f"call-check-records-{os.getpid()}.json")}
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
        alias()
        fix_and_copy(ends["cat_street"])
        records(ends["roadkill"])
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
