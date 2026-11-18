"""통화로 위치 좁히기 점검: 서버를 저장된 답 방식으로 띄우고, 두 장면을 화면의 「대본 재생」과 같은 순서로 HTTP로 끝까지 돌려 본다.

    python3 demo/call/check.py          (열쇠 · 엔진 · 인터넷 없이 십여 초. 실패하면 종료 코드 1)

보는 것: 서버가 뜬다 → 대본의 말을 넣는다 → 코드가 바로 읽어 질문이 뜬다(①) → 저장된 Solar 읽기로 갈아 끼운다(②) → 범위가 줄어든다
        → 찾아갈 수 있을 만큼 좁혀지고 확인받는다 → 그때 담당 부서가 배정된다(6종 안 · 밖 갈림이 맞다) → 접수 카드가 나온다.
        단추만 눌러도, 대본에 없는 말(코드만으로 읽음)로도 끝까지 가는지 본다.
"""
import json
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
    assert r["scope"] == e["scope"] and e["to"] in r["hit"]["to"], f"{name}: 갈림 · 넘길 곳이 다름 {r['scope']} {r['hit']['to']}"
    assert all(w in s["where"] for w in e["where"]), f"{name}: 위치 한 줄 {s['where']}"
    assert s["point"] and s["matter"] and e["to"] in s["to"] and s["go"] and view["pin"] and all(k in s["copy"] for k in ("민원을 받은 곳", "처음 접수한 담당자", "찾아가는 말", "번지수", "지도 좌표", "일", "처리할 담당 부서")), f"{name}: 접수 카드 {s}"
    assert view["answer_box"]["안내"]["name"] and view["answer_box"]["근거"]["name"] and view["heat"]["pts"] and len(view["heat"]["pts"]) <= 2500, f"{name}: 추천 답 칸 이름 · 지도에 그릴 점"
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


def main():
    env = {**os.environ, "CALL_MODE": "saved", "CALL_PORT": str(PORT), "CALL_REPLAY_SEC": "0", "CALL_ALIAS_FILE": str(Path(os.environ.get("TMPDIR", "/tmp")) / f"call-check-alias-{os.getpid()}.json")}
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
        assert 'id="ask"' in html and "call.js" in html
        greeting = next(r[1] for t in text["text"]["sections"]["통화 글"]["tables"] for r in t["rows"] if r[0] == "인사")
        for name in EXPECT:
            play(name, text["scripts"][name], greeting)
        chips_only("강변북로에 고양이가 차에 치여서 죽어 있어요.")      # 단추만으로 가려면 첫 말에 큰 장소는 있어야 한다
        free_text()
        alias()
        print("통화로 위치 좁히기 점검 통과")
    finally:
        server.terminate()
        server.wait(timeout=5)
        Path(env["CALL_ALIAS_FILE"]).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"점검 실패: {e}", file=sys.stderr)
        sys.exit(1)
