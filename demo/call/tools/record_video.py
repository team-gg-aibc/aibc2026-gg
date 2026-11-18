"""대본 재생을 창 없는 크로미움으로 녹화하고(소리 없음), 페이지는 소리를 내지 않고(--mute-audio, ?rec=1) 줄마다 시작 시각만 남기며, 그 시각에 음성 파일을 ffmpeg로 얹어 mp4 두 개(소리 · 자막만)를 만든다.

    먼저: CALL_MODE=saved CALL_PORT=8773 python3 demo/call/server.py  (저장된 답 방식 서버), 음성 파일은 web/voice/에 미리 둔다(레포에 없음)
    python3 demo/call/tools/record_video.py <cat_street|cat_park|roadkill> <mp4를 둘 폴더> <임시 폴더>
필요한 것: playwright(크로미움) · ffmpeg. 올리지 않는다. 목소리는 서비스가 부르는 모델이 아니다(제작 도구).
"""
import json, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
scene, out_dir, W, H = sys.argv[1], Path(sys.argv[2]), 1280, 800
tmp = Path(sys.argv[3]); tmp.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--mute-audio"])
    ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp), record_video_size={"width": W, "height": H})
    t_page = time.time(); pg = ctx.new_page()
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"http://127.0.0.1:8773/?auto={scene}&voice=1&rec=1&speed={sys.argv[4] if len(sys.argv) > 4 else 1}")      # 넷째 값 = 빠르기(음성 파일이 없을 때 1.15쯤이면 2분 안에 든다)
    # 녹화 파일의 시작과 페이지 시계를 맞추는 표시: 화면을 한 번 하얗게 깜빡이고 그때의 페이지 시각을 받는다(이 앞부분은 영상에서 잘라 낸다)
    pg.wait_for_function("window.CALL", timeout=40000)
    flash = pg.evaluate("""() => new Promise((res) => { const d = document.createElement('div'); d.style.cssText = 'position:fixed;inset:0;background:#fff;z-index:99999';
        document.body.appendChild(d); requestAnimationFrame(() => requestAnimationFrame(() => { const t = performance.now(); setTimeout(() => { d.remove(); res(t); }, 200); })); })""")
    pg.wait_for_function("window.CALL && window.CALL.ui.ended && (!window.CALL.V.engine || window.CALL.V.engine.status === 'ready')", timeout=300000)
    pg.wait_for_timeout(2500)
    pg.evaluate("document.getElementById('side').scrollTo({ top: 99999, behavior: 'smooth' })")       # 접수 카드의 아래쪽(추천 답 · 근거)까지 보이게
    pg.wait_for_timeout(5000)
    FLASH = """() => new Promise((res) => { const d = document.createElement('div'); d.style.cssText = 'position:fixed;inset:0;background:#fff;z-index:99999';
        document.body.appendChild(d); requestAnimationFrame(() => requestAnimationFrame(() => { const t = performance.now(); setTimeout(() => { d.remove(); res(t); }, 240); })); })"""
    flash2 = pg.evaluate(FLASH)                           # 끝에도 한 번 깜빡인다: 녹화 앞부분은 시각이 밀릴 수 있어, 시계는 끝의 표시로 맞춘다
    pg.wait_for_timeout(500)
    marks, origin = pg.evaluate("window.__marks || []"), pg.evaluate("performance.timeOrigin")
    events = pg.evaluate("window.__events || []")         # 「지금 물을 말」이 바뀐 때(차례별 시각 표용)
    info = pg.evaluate("JSON.stringify({lines: window.CALL.S.lines.length, to: window.CALL.V.summary.to, go: window.CALL.V.summary.go, notice: window.CALL.ui.notice})")
    video = pg.video.path(); ctx.close(); b.close()
print("끝 화면:", info, "| 화면 오류", errs[:2], "| 줄", len(marks), "| 음성 파일이 있는 줄", sum(1 for m in marks if m[2]))
probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"], capture_output=True, text=True).stdout
white, t_now = [], 0.0
for ln in probe.splitlines():                             # 하얗게 깜빡인 프레임들의 영상 시각
    if "pts_time:" in ln:
        t_now = float(ln.split("pts_time:")[1].split()[0])
    elif "YAVG=" in ln and float(ln.split("=")[1]) > 170:
        white.append(t_now)
if not white or white[-1] - white[0] < 5:
    sys.exit(f"깜빡임 표시 둘을 영상에서 못 찾았다(시계를 맞출 수 없음): {white[:3]} … {white[-3:]}")
seen = white[0]                                            # 앞 표시(여기까지는 잘라 낸다)
seen2 = next(t for t in white if t > white[-1] - 1.0)      # 끝 표시의 첫 프레임
shift = seen2 * 1000 - flash2                              # 영상 시각(ms) = 페이지 시각(ms) + shift (끝 표시 기준)
cut, end = seen + 0.6, seen2 - 0.2                         # 앞 표시 뒤부터 끝 표시 앞까지만 쓴다
delays = [(m[0], int(m[1] + shift - cut * 1000)) for m in marks if m[2]]      # 음성 파일이 있는 줄만 얹는다. 잘라 낸 영상 기준의 시작 시각(ms)
print(f"시계 맞춤: 끝 표시 기준 · 앞 표시로 셈했을 때와의 차이 {(shift - (seen * 1000 - flash)) / 1000:+.2f}초(앞부분이 밀린 만큼) · 쓰는 구간 {cut:.2f}~{end:.2f}초")
(tmp / "marks.json").write_text(json.dumps(delays, ensure_ascii=False), encoding="utf-8")      # 줄마다 영상 안에서 소리가 시작되는 때(ms). 글자 시각 대조에 쓴다
(tmp / "events.json").write_text(json.dumps([[e[0], int(e[1] + shift - cut * 1000), e[2], e[3]] for e in events], ensure_ascii=False), encoding="utf-8")      # 질문이 화면에 뜬 때(영상 시각 ms)
cmd = ["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{cut:.3f}", "-to", f"{end:.3f}", "-i", str(video)]
for f, _ in delays:
    cmd += ["-i", f"demo/call/web/{f}"]
flt = ";".join(f"[{n + 1}:a]adelay={d}|{d}[a{n}]" for n, (_, d) in enumerate(delays)) + ";" + "".join(f"[a{n}]" for n in range(len(delays))) + f"amix=inputs={len(delays)}:normalize=0[a]"
enc = ["-c:v", "libx264", "-crf", "27", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart"]
name = {"cat_street": "다친고양이-골목", "cat_park": "다친고양이-공원", "roadkill": "로드킬", "stray": "유기견", "vendor": "공원노점"}.get(scene, scene)      # 표에 없는 장면은 장면 이름 그대로
if delays:
    subprocess.run(cmd + ["-filter_complex", flt, "-map", "0:v", "-map", "[a]"] + enc + ["-c:a", "aac", "-b:a", "96k", str(out_dir / f"시연-{name}-소리.mp4")], check=True)
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{cut:.3f}", "-to", f"{end:.3f}", "-i", str(video)] + enc + ["-an", str(out_dir / f"시연-{name}-자막만.mp4")], check=True)
print(json.dumps(delays[:3], ensure_ascii=False))
