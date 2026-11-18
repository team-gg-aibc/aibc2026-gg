"""서울의 공개 지도 자료(오픈스트리트맵)를 내려받는다. 열쇠 · 가입 없이, 표준 라이브러리만.

    python3 -I demo/call/tools/osm_fetch.py <받을 빈 폴더>        예: ../_data/osm-seoul (레포 밖)

받는 것: BBBike가 매주 만들어 두는 오픈스트리트맵 서울 발췌본 한 파일(Seoul.osm.geojson.xz, 75MB쯤. 점 · 선 · 면과 그 표시가 한 줄에 하나씩).
받은 파일은 레포에 넣지 않는다. 줄인 지명 표는 build_gazetteer.py가 만든다. 받은 날과 크기를 fetched.json에 적는다.
자료: © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright). 발췌: https://download.bbbike.org/osm/bbbike/Seoul/
(Overpass API로 갈래별로 받는 길도 해 봤으나 공개 서버가 10분 넘게 답하지 않아 정적 파일로 바꿨다, 2026-11-14.)
"""
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

URL = "https://download.bbbike.org/osm/bbbike/Seoul/Seoul.osm.geojson.xz"


def main(out):
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    f = out / URL.rsplit("/", 1)[1]
    if f.exists() and f.stat().st_size > 1_000_000:
        print(f"{f.name}: 이미 있음 ({f.stat().st_size:,}바이트)")
        return
    t0 = time.time()
    req = urllib.request.Request(URL, headers={"User-Agent": "seoul-gazetteer-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(f.with_suffix(".part"), "wb") as w:
        modified = r.headers.get("Last-Modified")
        shutil.copyfileobj(r, w, 1 << 20)
    f.with_suffix(".part").rename(f)
    (out / "fetched.json").write_text(json.dumps({f.name: {"bytes": f.stat().st_size, "from": URL, "at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
                                                           "source_modified": modified, "sec": round(time.time() - t0)}}, ensure_ascii=False, indent=1))
    print(f"{f.name}: {f.stat().st_size:,}바이트 ({round(time.time() - t0)}초)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
