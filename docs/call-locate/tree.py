"""위치 가설 나무: 손으로 쓴 docs/call-locate/tree.json → tree.html (python3 docs/call-locate/tree.py).

엔진 나무(eval/board.py --tree)와 같은 화면 틀 eval/tree_template.html을 쓴다. 틀의 엔진 전용 글
(dev 가중 점수 · 주기 · 계획 표 꼬리말)만 위치 나무의 글로 바꿔 끼우고, 틀 파일은 고치지 않는다.
위치 고침은 이슈가 아니라 PR · 측정 보고로 진행해서, 숫자는 PR 본문 · 측정 보고의 값을 손으로 옮긴다.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parents[1] / "eval" / "tree_template.html"

SWAPS = [   # (틀의 글, 위치 나무의 글) — 틀이 바뀌어 하나라도 못 찾으면 멈춘다
    ("<title>가설 나무 · 팀 GG</title>", "<title>위치 가설 나무 · 팀 GG</title>"),
    ("<h1>가설 나무 <span", "<h1>위치 가설 나무 <span"),
    ('add(sub, h("span", {}, "dev 가중 ", h("span", {class: "num"}, n.score ?? "—")), h("span", {}, "흔들림 폭 " + (n.band ?? "—") + "점"), h("span", {}, n.label));',
     'add(sub, h("span", {}, n.label));'),
    (re.compile(r'add\(box, dl\(\[\["점수".*?\["잰 날", n\.date\]\]\)\);', re.S),
     'add(box, dl([["첫 판", n.label], ["그때 숫자", n.start], ["잣대", n.yardstick], ["넣는 기준", n.rule], ["잰 날", n.date]]));'),
    ('who(n.owner) || h("span", {}, "담당 없음")', "who(n.owner)"),
    ('["담당", who(n.owner) || "아직 없음"]', '["담당", who(n.owner)]'),
    ('"아직 없음(고르면 그때 만든다)"', "null"),
    ('h("span", {}, n.cycle + "주기"), ', ""),
    ('["주기", n.cycle + "주기"]', '["주기", null]'),
    ('n.compare ? h("li", {}, link(n.compare, "기준과 문항별 비교")) : h("li", {class: "hint"}, "비교 문서 없음(python3 eval/compare.py <실행>)")',
     'n.pr ? h("li", {}, link(n.pr.url, "PR #" + n.pr.number)) : h("li", {class: "hint"}, "PR 없음(넣지 않은 고침)")'),
    ('"뿌리는 출발 판, 가지는 가설 → 실험 → 다음 가설. 숫자는 리더보드와 같은 값 · 만든 때 "',
     '"뿌리는 첫 판, 가지는 가설(무엇이 틀렸나) → 실험(고침 · 스위치 · PR) → 결과(숫자) → 다음 가설. 숫자는 PR 본문 · 측정 보고의 값 · 만든 때 "'),
    ('"자료: 계획 표(docs/engine/plan.md 2-1 · 2-3 · 4-1절, 「부모」 칸) · 실행 요약(eval/runs) · 결론 · 배운 점 · GitHub 이슈 · PR 상태. python3 eval/board.py --tree가 만든다. holdout은 넣지 않는다."',
     '"자료: docs/call-locate/tree.json(손으로 씀) — PR 본문 · 측정 보고의 숫자. python3 docs/call-locate/tree.py가 만든다. 따로 떼어 둔 확인용 묶음은 합계만 적는다."'),
]


def build(tree, page):
    for old, new in SWAPS:
        page, n = (old.subn(lambda _: new, page) if isinstance(old, re.Pattern) else (page.replace(old, new), page.count(old)))
        assert n >= 1, f"틀에서 못 찾음: {getattr(old, 'pattern', old)[:60]}"
    data = json.dumps(tree, ensure_ascii=False).replace("<", "\\u003c")   # board.write_tree와 같은 이스케이프
    return page.replace("/*DATA*/null", data)


def check(tree):
    ids, statuses = [], set(tree["status"])
    def walk(n):
        ids.append(n["id"])
        assert n["status"] in statuses, n["id"]
        assert n["kind"] in ("root", "hypothesis", "experiment"), n["id"]
        for c in n.get("children", []):
            walk(c)
    walk(tree["tree"])
    assert len(ids) == len(set(ids)), "마디 id가 겹침"
    return ids


if __name__ == "__main__":
    tree = json.loads((HERE / "tree.json").read_text(encoding="utf-8"))
    check(tree)
    html = build(tree, TEMPLATE.read_text(encoding="utf-8"))
    (HERE / "tree.html").write_text(html, encoding="utf-8")
    print("위치 가설 나무 → docs/call-locate/tree.html")
