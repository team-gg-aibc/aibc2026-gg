"""장면마다 AI가 읽을 말과 그 음성 파일 이름을 찍는다. 모델 · 열쇠를 쓰지 않는다(저장된 답으로 대본을 돌려 본다).

    OPENBLAS_NUM_THREADS=1 python3 demo/call/voice/tts_lines.py [장면]
    OPENBLAS_NUM_THREADS=1 CALL_VOICE_TTS=elevenlabs python3 demo/call/voice/tts_lines.py --make [장면]      없는 파일을 일레븐랩스 음성 합성으로 만들어 둔다(열쇠 필요)
    OPENBLAS_NUM_THREADS=1 python3 demo/call/voice/tts_lines.py --citizen [장면]      「대본을 음성 길로」의 시민 역 소리(web/voice/citizen/)를 일레븐랩스 다른 목소리로 만든다(열쇠 필요)

찍힌 이름으로 web/voice/tts/ 에 mp3를 두면 음성 통화가 그 줄을 그 파일로 읽는다(파일은 레포에 넣지 않는다. 만드는 도구도 서비스 밖이다).
"""
import os
import sys
from pathlib import Path

os.environ["CALL_MODE"] = "saved"
os.environ.setdefault("CALL_REPLAY_SEC", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as S  # noqa: E402
from voice import hub  # noqa: E402
from voice.hub import tts_name  # noqa: E402

import wave  # noqa: E402

MAKE, CITIZEN = "--make" in sys.argv, "--citizen" in sys.argv
T = S.tab("통화 글")
for scene in [a for a in sys.argv[1:] if not a.startswith("--")] or S.scripts():
    st, view, _ = S.play(scene)
    to = (view.get("summary") or {}).get("to") or ""
    end = S.fill(T["맺음말"], **{"넘길 곳": to.replace(" · ", ", ")}) if to else T["맺음말 넘길 곳 모름"]
    if CITIZEN:
        for text in dict.fromkeys(S.scripts()[scene].values()):      # 대본의 시민 줄 전부(받아쓴 글이 대본과 조금 달라 질문 순서가 바뀌어도 답할 수 있게)
            f = hub.citizen_file(text)
            if not f.is_file():
                pcm = hub.synth(text, voice=hub.CITIZEN_VOICE, fmt="pcm_16000")
                f.parent.mkdir(exist_ok=True)
                with wave.open(str(f), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(pcm)
            print(f"{scene}\t시민\t{f.name}\t{text}")
        continue
    for text in [x["text"] for x in st["lines"] if x["who"] == "상담사"] + [end]:
        f = hub.tts_file(text, make=MAKE)
        print(f"{scene}\t{tts_name(text)}\t{'있음' if f else '없음'}\t{text}")
if MAKE or CITIZEN:
    print("일레븐랩스에 쓴 양:", hub.stt.used)
