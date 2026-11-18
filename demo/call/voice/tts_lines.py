"""장면마다 AI가 읽을 말과 그 음성 파일 이름을 찍는다. 모델 · 열쇠를 쓰지 않는다(저장된 답으로 대본을 돌려 본다).

    OPENBLAS_NUM_THREADS=1 python3 demo/call/voice/tts_lines.py [장면]

찍힌 이름으로 web/voice/tts/ 에 mp3를 두면 음성 통화가 그 줄을 그 파일로 읽는다(파일은 레포에 넣지 않는다. 만드는 도구도 서비스 밖이다).
"""
import os
import sys
from pathlib import Path

os.environ["CALL_MODE"] = "saved"
os.environ.setdefault("CALL_REPLAY_SEC", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as S  # noqa: E402
from voice.hub import tts_name  # noqa: E402

T = S.tab("통화 글")
for scene in sys.argv[1:] or S.scripts():
    st, view, _ = S.play(scene)
    to = (view.get("summary") or {}).get("to") or ""
    end = S.fill(T["맺음말"], **{"넘길 곳": to.replace(" · ", ", ")}) if to else T["맺음말 넘길 곳 모름"]
    for text in [x["text"] for x in st["lines"] if x["who"] == "상담사"] + [end]:
        print(f"{scene}\t{tts_name(text)}\t{text}")
