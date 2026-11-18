"""음성 파일마다 「화면 글의 글자가 소리 나는 시각」을 얻어 voice/index.json에 적는다(영상에서 글자가 말과 같이 올라오게).

    python3 demo/call/tools/align_voice.py        (mlx_whisper가 있는 파이썬. 스피커로 소리를 내지 않는다. 새 음성을 만들지 않는다)

방법: 줄별 mp3를 로컬 받아쓰기(mlx_whisper)로 낱말 시각까지 받아 적고, 받아 적은 글자와 화면 글의 글자를 순서대로 맞춘다.
받아 적은 표기가 달라 맞지 않는 구간(숫자 「160m」 ↔ 「백육십 미터」 등)은 앞뒤 시각 사이를 고르게 나눈다. 음성 앞의 빈 소리 동안에는 글자가 나오지 않는다.
index.json: {"<줄>.mp3": {"dur": 길이(초), "ct": [글자마다 나타날 시각(초)]}}
"""
import difflib, json, re, subprocess, sys
from pathlib import Path
import mlx_whisper

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "demo" / "call" / "web" / "voice"
book = json.loads((REPO.parent / "_data" / "voice-gemini" / "lines.json").read_text(encoding="utf-8"))
keep = lambda ch: bool(re.match(r"[0-9A-Za-z가-힣]", ch))   # noqa: E731
index, report = {}, []
for key, b in sorted(book.items()):
    mp3, screen = OUT / f"{key}.mp3", b["screen"]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)], capture_output=True, text=True).stdout)
    r = mlx_whisper.transcribe(str(mp3), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="ko", condition_on_previous_text=False, word_timestamps=True, initial_prompt=b["say"], verbose=None)
    tch, tt = [], []                                      # 받아 적은 글자와 그 시각(낱말 안에서는 고르게)
    for seg in r["segments"]:
        for w in seg.get("words") or []:
            chars = [c for c in w["word"] if keep(c)]
            for j, c in enumerate(chars):
                tch.append(c); tt.append(w["start"] + (w["end"] - w["start"]) * j / len(chars))
    pos = [i for i, c in enumerate(screen) if keep(c)]    # 화면 글에서 소리 나는 글자의 자리
    times = [None] * len(pos)
    for a, c, n in difflib.SequenceMatcher(None, [screen[i] for i in pos], tch, autojunk=False).get_matching_blocks():
        for k in range(n):
            times[a + k] = tt[c + k]
    matched = sum(t is not None for t in times)
    first = next((t for t in times if t is not None), 0.0)
    known = [(-1, first)] + [(i, t) for i, t in enumerate(times) if t is not None] + [(len(times), max(dur - 0.05, first))]
    for (i0, t0), (i1, t1) in zip(known, known[1:]):      # 맞지 않은 구간은 앞뒤 시각 사이를 고르게
        for i in range(i0 + 1, i1):
            times[i] = t0 + (t1 - t0) * (i - i0) / (i1 - i0)
    ct, last = [0.0] * len(screen), first
    it = iter(zip(pos, times))
    nxt = next(it, None)
    for i in range(len(screen)):                          # 쉼표 · 빈칸은 바로 앞 글자와 함께 나온다
        if nxt and nxt[0] == i:
            last = max(last, nxt[1]); nxt = next(it, None)
        ct[i] = round(last, 2)
    index[f"{key}.mp3"] = {"dur": round(dur, 2), "ct": ct}
    report.append((key, matched, len(pos), first, dur))
(OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
low = [f"{k}({m}/{n})" for k, m, n, _, _ in report if m < 0.8 * n]
print(f"줄 {len(report)} · 글자를 시각에 맞춘 비율 {sum(m for _, m, _, _, _ in report) / sum(n for _, _, n, _, _ in report):.0%} · 80% 못 맞춘 줄 {low or '없음'} · 첫 글자가 나오는 시각(가운데값) {sorted(f for _, _, _, f, _ in report)[len(report) // 2]:.2f}초")
