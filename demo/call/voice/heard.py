"""영상용: 받아쓴 민원인 말에 대한 Solar 읽기를 미리 받아 두고, 저장된 답 방식에서 찾아 쓴다. CALL_VOICE=1 · CALL_MODE=saved일 때만 붙는다.

대본 장면을 음성 길로 돌리면 민원인의 말은 받아쓴 글로 들어간다. 받아쓴 글이 대본과 한 글자라도 다르면(「여보세요,」 → 「여보세요?」)
data/saved.json에 받아 둔 읽기를 못 찾아 코드 읽기만 쓰고, 질문이 하나 더 나온다(56번 12-4 · 16절).
그래서 받아쓴 글로 한 번 실제 호출을 돌려 읽기를 heard_reads.json에 받아 두고, 찾을 때는
  ① 원래 열쇠(말 그대로)로 먼저(대본 글 · 친 글은 지금과 똑같다), ② 없으면 띄어쓰기 · 문장 부호를 뺀 열쇠로 찾는다
     (받아쓰기는 찍을 때마다 「상도 1동」 · 「상도1동」처럼 이 몫이 흔들린다. 글자가 다르면 못 찾고 지금처럼 코드 읽기로 간다).
data/saved.json · server.py는 고치지 않는다.

받아 두기(실제 호출: 팀 Upstage 열쇠를 UPSTAGE_API_KEY로. 엔진 답은 saved.json에 같은 열쇠가 있으면 다시 쓴다.
질문 순서가 saved.json의 대본 순서와 다르면 저장하지 않는다):
    python3 demo/call/voice/heard.py <음성 한 세트 결과.json(통화 글)> [장면]
점검(열쇠 없이):
    python3 demo/call/voice/heard.py --check
"""
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path

FILE = Path(__file__).with_name("heard_reads.json")
CALL = Path(__file__).resolve().parents[1]
norm = lambda s: re.sub(r"[\W_]+", "", s or "")      # noqa: E731  띄어쓰기 · 문장 부호를 뺀다(한글 · 숫자 · 영문은 남는다)


def norm_key(st):
    said = [norm(t["said"]) for t in st["turns"] if t.get("said")]
    return "n:" + hashlib.sha1(json.dumps([said, (st["turns"][-1].get("asked") or {}).get("id")], ensure_ascii=False).encode()).hexdigest()[:16]


def attach(mod):
    """server 모듈의 저장된 답에 받아 둔 읽기 · 엔진 답을 더하고(있는 것은 그대로), read_key를 「원래 열쇠 → 없으면 뺀 열쇠」로 감싼다."""
    if mod.MODE != "saved" or not FILE.exists():
        return
    for sc in json.loads(FILE.read_text(encoding="utf-8"))["scenes"].values():
        for k, v in sc["reads"].items():
            mod.saved["reads"].setdefault(k, v)
        for k, v in sc["engine"].items():
            mod.saved["engine"].setdefault(k, v)
    exact = mod.read_key

    def read_key(st):
        k = exact(st)
        if k in mod.saved["reads"]:
            return k
        n = norm_key(st)
        return n if n in mod.saved["reads"] else k
    mod.read_key = read_key      # ponytail: server.py의 이름(read_key · saved · MODE)에 기대어 감싼다. 이름이 바뀌면 --check(check_voice ⑦)가 깨져 알린다


def script_order(scene):
    d = json.loads((CALL / "data" / "saved.json").read_text(encoding="utf-8"))
    return [s["next"] for s in ((d.get(f"made_{scene}") or d.get("made") or {}).get("steps") or {}).get(scene) or []]


def server(mode):
    os.environ.pop("CALL_MODE", None) if mode == "live" else os.environ.update(CALL_MODE=mode, CALL_VOICE="1", CALL_REPLAY_SEC="0", CALL_VOICE_STT="fake")
    sys.path.insert(0, str(CALL))
    import server as S
    assert S.MODE == mode, S.MODE
    return S


def record(run_json, scene):
    S = server("live")
    script, old = S.scripts()[scene], json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {"scenes": {}}
    heard = [t for who, _, t in json.loads(Path(run_json).read_text(encoding="utf-8"))["통화 글"] if who in ("시민", "민원인")]
    pick = {k: max(heard, key=lambda h: difflib.SequenceMatcher(None, norm(v), norm(h)).ratio()) for k, v in script.items()}
    pick = {k: h for k, h in pick.items() if difflib.SequenceMatcher(None, norm(script[k]), norm(h)).ratio() >= 0.8}      # 받아쓴 글이 없는 질문(side · lane)은 대본 글 그대로
    n = {"chat": 0, "embed": 0}
    for f in n:
        g = getattr(S.upstage, f)
        setattr(S.upstage, f, lambda *a, _f=f, _g=g, **k: (n.__setitem__(_f, n[_f] + 1), _g(*a, **k))[1])
    run = S._run_engine

    def engine(key, said, tname, place, job, question=None):      # 엔진 답은 받아쓴 글과 상관없는 열쇠(일 | 자리 | 물음)라 saved.json에 있으면 그대로
        hit = S.saved["engine"].get(key)
        return job.update(res={**hit, "how": "saved"}, ready_at=0) if hit else run(key, said, tname, place, job, question)
    S._run_engine, S.read_key, S.scripts = engine, norm_key, lambda: {scene: {**script, **pick}}
    S.recording = {"reads": {}, "engine": {}}
    st, view, steps = S.play(scene)
    got, want = [s["next"] for s in steps], script_order(scene)
    print(f"Upstage 호출: Solar 대화 {n['chat']}번 · 임베딩 {n['embed']}번")
    for s in steps:
        print("   ", s["read"], s["next"], "|", s["said"])
    print("끝난 자리:", view["summary"].get("where"), "| 질문 순서", got, "| 대본", want)
    if got != want or any(s["read"] != "live" for s in steps):
        raise SystemExit("질문 순서가 대본과 다르거나 못 읽은 차례가 있어 저장하지 않았다. 다시 돌린다(Solar는 같은 입력에 다른 출력을 낼 수 있다)")
    old["scenes"][scene] = {"heard": pick, "order": got, "where": view["summary"].get("where"), "reads": S.recording["reads"], "engine": S.recording["engine"],
                            "made": {"model": S.MODEL, "from": Path(run_json).name, "upstage": n, "engine_settings": S.config.digest(S.ENGINE_CFG)}}
    FILE.write_text(json.dumps({"note": __doc__.split("\n\n")[0], **old}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {FILE.name} ({scene}: 읽기 {len(S.recording['reads'])} · 새 엔진 답 {len(S.recording['engine'])})")


def check():
    """받아 둔 장면마다: 받아쓴 글 그대로 · 띄어쓰기와 문장 부호를 바꾼 글 · 대본 글로 저장된 답 방식을 돌려, 모든 차례가 저장된 읽기를 찾고 대본 순서대로 묻는지."""
    S = server("saved")
    play, script = S.play, S.scripts
    for scene, sc in json.loads(FILE.read_text(encoding="utf-8"))["scenes"].items():
        base = script()[scene]
        for name, lines in (("받아쓴 글", {**base, **sc["heard"]}), ("띄어쓰기 · 부호 바꿈", {k: re.sub(r"\s+", "", v).replace(".", ",") for k, v in {**base, **sc["heard"]}.items()}), ("대본 글", base)):
            S.scripts = lambda lines=lines: {scene: lines}
            _, view, steps = play(scene, wait_engine=False)
            bad = [s["said"] for s in steps if s["read"] != "saved"]
            assert not bad and [s["next"] for s in steps] == sc["order"] == script_order(scene), (scene, name, bad, [s["next"] for s in steps])
            assert view["summary"].get("where") == sc["where"], (scene, name, view["summary"].get("where"))
            print(f"  ✓ {scene} · {name}: 모든 차례 저장된 읽기, 질문 순서 {sc['order'][:-1]}, 끝난 자리 {sc['where']}")
    S.scripts = script


if __name__ == "__main__":
    if sys.argv[1:2] == ["--check"]:
        check()
    else:
        record(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "cat_street")
