"""영상용 음성 파일 만들기 (제작 도구. 서비스 안에서 도는 모델이 아니다).

방식:
  ① 목소리를 설명 글로 디자인한다(POST …/voices, 모델 gemini-3.8-flash-tts, type prompted) → 목소리 id
  ② 줄마다 그 목소리로 읽힌다(POST …/interactions, response_format audio, speech_config voice) → wav

    python3 demo/call/tools/make_voice_gemini.py <열쇠 파일> [--dry]

- 열쇠는 그 파일의 GEMINI_API_KEY 줄에서 이 스크립트가 직접 읽는다. 값을 찍거나 다른 곳에 적지 않는다.
- 보내는 것은 대본 재생에 나오는 가상의 통화 줄뿐이다(`server.py --lines`).
- 목소리 id와 받은 wav는 레포 밖(레포 옆 _data/voice-gemini/)에 두고, 화면이 트는 mp3와 길이 표(index.json)는 demo/call/web/voice/에 둔다(git이 무시한다).
- 이미 만든 줄(글이 같은 줄)은 다시 부르지 않는다. 끝에 부른 횟수를 찍는다.
- 알려진 함정: 숫자를 엉뚱하게 읽거나 군말을 넣는다 → 숫자는 한글로 풀어 보내고, 만든 뒤 사람이 한 번 들어 본다.
"""
import base64, hashlib, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
KEY_FILE = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "")).expanduser()
DRY = "--dry" in sys.argv
STORE = REPO.parent / "_data" / "voice-gemini"
OUT = REPO / "demo" / "call" / "web" / "voice"
GEMINI, TTS_MODEL = "https://generativelanguage.googleapis.com/v1beta", "gemini-3.8-flash-tts"
VOICES = {      # 이름: (성별, 목소리 설명, 읽을 때의 말투)
    "상담사": ("female", "30대 여성 콜센터 상담원. 차분하고 또렷한 표준어, 친절하지만 사무적이고 일정한 빠르기. 연기하듯 과장하지 않는다.", "전화 상담. 차분하고 또렷하게, 과장 없이."),
    "시민-roadkill": ("male", "40대 남성. 운전하다가 전화를 건 보통 시민. 조금 급하지만 침착한 일상 말투의 표준어. 연기하듯 과장하지 않는다.", "운전 중에 건 전화. 조금 급하지만 담백하게."),
    "시민-stray": ("female", "30대 여성. 공원에서 산책하다 전화를 건 보통 시민. 조금 걱정스러운 일상 말투의 표준어. 연기하듯 과장하지 않는다.", "공원에서 건 전화. 조금 걱정스럽게, 과장 없이."),
    "시민-vendor": ("male", "50대 남성. 공원에 나들이 왔다가 궁금해서 전화를 건 보통 시민. 조금 언짢지만 점잖은 일상 말투의 표준어. 연기하듯 과장하지 않는다.", "공원에서 건 전화. 궁금해서 묻듯이, 과장 없이."),
}
calls = 0


def key():
    if not KEY_FILE.is_file():
        sys.exit("열쇠 파일 경로를 첫 인자로 준다(GEMINI_API_KEY 줄이 든 파일)")
    for ln in KEY_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(?:export\s+)?GEMINI_API_KEY\s*=\s*['\"]?([^'\"\s]+)", ln)
        if m:
            return m.group(1)
    sys.exit("열쇠 파일에 GEMINI_API_KEY 줄이 없다")


def gemini(path, body):
    global calls
    last = ""
    for wait in (0, 15, 40, 90):                          # 한도(429) · 혼잡(503)은 쉬었다 다시
        time.sleep(wait)
        req = urllib.request.Request(f"{GEMINI}/{path}", data=json.dumps(body).encode(), headers={"x-goog-api-key": key(), "Content-Type": "application/json"})
        calls += 1
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = f"{e.code}: {e.read().decode(errors='replace')[:300]}"
            if e.code not in (429, 503):
                sys.exit(f"Gemini 오류 {last}")
    sys.exit(f"Gemini 한도 · 혼잡이 계속됨 ({last})")


def num_ko(n):
    out = ""
    for d, unit in zip(f"{int(n):04d}", ("천", "백", "십", "")):
        if d != "0":
            out += ("" if d == "1" and unit else "일이삼사오육칠팔구"[int(d) - 1]) + unit
    return out or "영"


def spoken(text):
    """화면의 글 → 읽을 글: 숫자와 단위는 한글로, 기호는 쉼표로."""
    t = re.sub(r"(\d[\d,]*)\s*m\b", lambda m: num_ko(m.group(1).replace(",", "")) + " 미터", text)
    t = re.sub(r"강_(\d+)-(\d+)", lambda m: f"강 {num_ko(m.group(1))} 다시 {num_ko(m.group(2))}", t)
    return re.sub(r"\s*,(\s*,)*", ",", t.replace(" · ", ", ").replace("·", ", ").replace("(", ", ").replace(")", "")).replace(",", ", ").replace("  ", " ").strip()      # 「유실·유기동물」의 붙은 가운뎃점도 쉼표로(11-15)


def main():
    STORE.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    lines = [ln.split("\t") for ln in subprocess.run([sys.executable, "demo/call/server.py", "--lines"], capture_output=True, text=True, cwd=REPO, env={**os.environ, "CALL_MODE": "saved"}).stdout.splitlines() if ln.count("\t") == 2]
    by = STORE / "by-tag"                                 # 글(목소리 + 읽을 글)마다 한 번만 만든다. 줄 번호가 바뀌어도 다시 부르지 않는다
    by.mkdir(exist_ok=True)
    for old in STORE.glob("*.json"):                      # 예전 꼴(줄 번호로 둔 것)을 옮겨 둔다
        if old.name not in ("voices.json", "lines.json") and old.with_suffix(".wav").exists():
            t = json.loads(old.read_text(encoding="utf-8")).get("tag")
            if t and not (by / f"{t}.wav").exists():
                (by / f"{t}.wav").write_bytes(old.with_suffix(".wav").read_bytes())
    redo, book = set((next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--redo=")), "")).split(",")), {}
    vfile = STORE / "voices.json"
    voices = json.loads(vfile.read_text(encoding="utf-8")) if vfile.exists() else {}
    index = {}
    for k, who, text in lines:
        scene = k.split("-")[0]
        name = "상담사" if who == "상담사" else f"시민-{scene}"
        say, mp3 = spoken(text), OUT / f"{k}.mp3"
        tag = hashlib.sha1(f"{name}|{say}".encode()).hexdigest()[:10]
        wav = by / f"{tag}.wav"
        book[k] = {"voice": name, "screen": text, "say": say, "tag": tag}
        if DRY:
            print(f"{k}\t{name}\t{say}")
            continue
        if not wav.exists() or k in redo:
            if name not in voices:                        # ① 목소리 디자인(이름마다 한 번)
                gender, desc, _ = VOICES[name]
                r = gemini("voices", {"store": True, "voice": {"model": TTS_MODEL, "type": "prompted", "display_name": f"gg-call-{name}", "gender": gender, "language_code": "ko-KR", "prompted": {"input": desc}}})
                vid = (r.get("id") or r.get("name") or "").split("/")[-1]
                if not vid:
                    sys.exit(f"목소리 id 없음: {json.dumps(r, ensure_ascii=False)[:300]}")
                voices[name] = {"id": vid, "desc": desc}
                vfile.write_text(json.dumps(voices, ensure_ascii=False, indent=1), encoding="utf-8")
            r = gemini("interactions", {"model": TTS_MODEL, "input": [{"type": "user_input", "content": [{"type": "text", "text": say, "annotations": [{"type": "speech_metadata", "style": VOICES[name][2]}]}]}],
                                        "response_format": {"type": "audio"}, "generation_config": {"speech_config": [{"voice": voices[name]["id"]}]}})      # ② 읽히기
            audio = [c for s in r.get("steps", []) if s.get("type") == "model_output" for c in s.get("content", []) if c.get("type") == "audio"]
            if not audio:
                sys.exit(f"{k}: 오디오 없음 {json.dumps(r, ensure_ascii=False)[:300]}")
            wav.write_bytes(base64.b64decode(audio[-1]["data"]))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-af", "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse", "-ac", "1", "-b:a", "96k", str(mp3)], check=True)
        d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)], capture_output=True, text=True).stdout)
        index[f"{k}.mp3"] = round(d, 2)
        print(f"{k} {name} {d:4.1f}초 | 글자당 {d / max(len(say), 1) * 1000:3.0f}ms | {say[:46]}")
    if not DRY:
        for stale in OUT.glob("*.mp3"):                   # 지금 대본에 없는 번호의 파일은 치운다(레포 밖 원본은 by-tag에 남는다)
            if stale.name not in index:
                stale.unlink()
        (STORE / "lines.json").write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
        tot = {}
        for f, d in index.items():
            tot[f.split("-")[0]] = tot.get(f.split("-")[0], 0) + d
        print({k: round(v, 1) for k, v in tot.items()}, "| 이번에 부른 횟수", calls)


if __name__ == "__main__":
    main()
