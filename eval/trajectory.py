"""궤적 화면: 한 실행의 문항마다 단계별 입력 · 프롬프트 · 모델 출력 · 시간 · 토큰을 사람이 읽기 쉽게 보여 준다.

  python3 eval/trajectory.py <실행>              eval/results/<실행>.html을 만든다(점수 틀이 끝까지 잰 실행마다 저절로 만든다)
  python3 eval/trajectory.py <실행> <문항 id>    그 문항 하나를 마크다운으로 화면에 낸다(PR 「검증」에 붙이기 좋다)
<실행>은 eval/runs/<실행>.json의 이름(예: 20261106-194924-baseline-dev)이나 그 파일 경로.
문항별 결과(eval/results/<실행>.jsonl)가 있는 컴퓨터에서만 된다(git에 안 올림). holdout은 문항별 결과가 없어 안 된다.
"""
import html
import json
import sys
from pathlib import Path

from run import RESULTS, RUNS, match, upstage

STAGES = ["받기", "검색", "고르기 · 답 쓰기", "판정", "출력"]


def load(run):
    run_id = Path(run).name.removesuffix(".json")
    summary = json.loads((RUNS / f"{run_id}.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in open(RESULTS / f"{run_id}.jsonl", encoding="utf-8")]
    return summary, rows


def gold_mark(label, gold):
    best = max((match(label, a) for alts in gold for a in alts), default=0.0)
    return "✓" if best == 1 else "½" if best else ""


def parts(row):
    """문항 하나를 (제목, [(종류, 내용)…]) 절들로 나눈다. 종류: text · pre · table."""
    t = row.get("trace") or {}
    gold = row["gold"]
    out = [("문제", [("text", f"질문: {row['question']}"),
                     ("text", "정답 조항: " + (" / ".join(" 또는 ".join(alts) for alts in gold) if gold else "없음(함정)")),
                     ("text", f"정답 열쇠: {row.get('answer_key', '')}"),
                     ("text", f"점수 {row['score']} · 원인 {row['cause'] or '맞음'} · 까닭 {t.get('reason') or '—'}"
                              + (f" · 오류 {row['error']}" if row.get("error") else "") + f" · {row['sec']}초")])]
    if not t:
        return out + [("응답", [("pre", json.dumps(row["response"], ensure_ascii=False, indent=1))])]
    for stage in STAGES:
        if stage not in t.get("steps", {}):
            continue
        calls = [c for c in t["calls"] if c.get("stage") == stage]
        cost = upstage.cost_usd(calls) or 0
        items = []
        if stage == "받기":
            items.append(("text", f"입력: {t['question']}"))
        if stage == "검색":
            items.append(("text", f"검색: {t.get('retrieval')} · 모델 {t['models']['embed_query']}"))
            items.append(("table", ["#", "라벨", "혼합", "키워드", "의미", "정답"],
                          [[str(i), c["label"], c["score"], c["kw"], c["cos"], gold_mark(c["label"], gold)]
                           for i, c in enumerate(t["candidates"], 1)]))
        for c in calls:
            if c["kind"] != "chat":
                continue
            items.append(("text", f"호출: {c['model']} · 입력 {c['in']}토큰(캐시 {c['cached']}) · 출력 {c['out']}토큰 · "
                                  f"{c['sec']}초 · ${upstage.cost_usd([c]) or 0:.5f}"))
            for msg in c.get("sent") or []:
                items.append(("pre", f"[{msg['role']}]\n{msg['content']}"))
            items.append(("pre", f"[모델 출력]\n{c.get('output')}"))
        if stage == "고르기 · 답 쓰기":
            draft = t.get("draft") or {}
            items.append(("text", f"고른 번호: {t.get('evidence_ids')} → 인용 {draft.get('citation', [])}"))
        if stage == "판정":
            items.append(("text", f"판정: {t.get('verdict') or '—'}"))
        if stage == "출력":
            items.append(("pre", json.dumps(row["response"], ensure_ascii=False, indent=1)))
        out.append((f"{stage} · {t['steps'][stage]}초" + (f" · ${cost:.5f}" if calls else ""), items))
    if t.get("reason") and "출력" not in t.get("steps", {}):
        out.append(("응답", [("pre", json.dumps(row["response"], ensure_ascii=False, indent=1))]))
    return out


def markdown(row):
    lines = [f"# {row['id']} · {row['type']}"]
    for title, items in parts(row):
        lines += ["", f"## {title}", ""]
        for kind, *body in items:
            if kind == "text":
                lines.append(f"- {body[0]}")
            elif kind == "pre":
                lines += ["```text", body[0], "```"]
            else:
                head, rows = body
                lines += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                lines += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def html_page(summary, rows):
    e = html.escape
    m = summary["metrics"]
    causes = sorted({r["cause"] or "맞음" for r in rows})
    types = sorted({r["type"] for r in rows})
    body = [f"<h1>{e(summary['run_id'])}</h1>",
            f"<p>{e(summary['args']['split'])} · {len(rows)}문항 · 가중 {m.get('weighted')} · 비용 ${summary.get('cost_usd')}</p>",
            "<p>원인 <select id='cause'><option value=''>모두</option>"
            + "".join(f"<option>{e(c)}</option>" for c in causes) + "</select> 유형 <select id='type'><option value=''>모두</option>"
            + "".join(f"<option>{e(t)}</option>" for t in types) + "</select></p>",
            "<table><tr><th>문항</th><th>유형</th><th>점수</th><th>원인</th><th>초</th><th>질문</th></tr>"]
    for r in rows:
        body.append(f"<tr data-cause='{e(r['cause'] or '맞음')}' data-type='{e(r['type'])}'><td><a href='#q-{e(r['id'])}'>{e(r['id'])}</a></td>"
                    f"<td>{e(r['type'])}</td><td>{r['score']}</td><td>{e(r['cause'] or '맞음')}</td><td>{r['sec']}</td>"
                    f"<td>{e(r['question'][:60])}</td></tr>")
    body.append("</table>")
    for r in rows:
        sec = []
        for title, items in parts(r):
            sec.append(f"<h3>{e(title)}</h3>")
            for kind, *b in items:
                if kind == "text":
                    sec.append(f"<p>{e(b[0])}</p>")
                elif kind == "pre":
                    sec.append(f"<pre>{e(b[0])}</pre>")
                else:
                    sec.append("<table><tr>" + "".join(f"<th>{e(h)}</th>" for h in b[0]) + "</tr>"
                               + "".join("<tr>" + "".join(f"<td>{e(str(x))}</td>" for x in row) + "</tr>" for row in b[1]) + "</table>")
        body.append(f"<details id='q-{e(r['id'])}' data-cause='{e(r['cause'] or '맞음')}' data-type='{e(r['type'])}'>"
                    f"<summary>{e(r['id'])} · {e(r['type'])} · 점수 {r['score']} · {e(r['cause'] or '맞음')} · {e(r['question'][:80])}</summary>"
                    + "".join(sec) + "</details>")
    style = ("body{font:15px/1.6 -apple-system,'Pretendard',sans-serif;max-width:1100px;margin:0 auto;padding:16px;"
             "background:#fff;color:#1d1d1f}table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ccc;padding:2px 8px;"
             "font-size:13px;text-align:left}pre{white-space:pre-wrap;background:#f4f4f6;padding:8px;border-radius:6px;font-size:12.5px}"
             "details{border-top:1px solid #ddd;padding:6px 0}summary{cursor:pointer;font-weight:600}a{color:#0b57d0}"
             "@media (prefers-color-scheme: dark){body{background:#1c1c1e;color:#eee}pre{background:#2c2c2e}td,th{border-color:#444}"
             "a{color:#8ab4f8}}")
    script = ("for(const s of ['cause','type'])document.getElementById(s).onchange=()=>{const c=document.getElementById('cause').value,"
              "t=document.getElementById('type').value;for(const el of document.querySelectorAll('[data-cause]'))"
              "el.style.display=(!c||el.dataset.cause===c)&&(!t||el.dataset.type===t)?'':'none'};")
    return (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>궤적 {e(summary['run_id'])}</title><style>{style}</style></head><body>"
            + "".join(body) + f"<script>{script}</script></body></html>")


def write_html(summary, rows, out_dir=RESULTS):
    path = Path(out_dir) / f"{summary['run_id']}.html"
    path.write_text(html_page(summary, rows), encoding="utf-8")
    return path


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    summary, rows = load(sys.argv[1])
    if summary["args"]["mode"] != "full":
        sys.exit("✗ 검색만 잰 실행은 궤적이 없습니다(끝까지 잰 실행만).")
    if len(sys.argv) > 2:
        row = next((r for r in rows if r["id"] == sys.argv[2]), None)
        sys.exit(f"✗ 그 실행에 문항 {sys.argv[2]}가 없습니다.") if row is None else print(markdown(row))
    else:
        print(write_html(summary, rows))


if __name__ == "__main__":
    main()
