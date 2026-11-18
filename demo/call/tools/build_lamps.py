"""가로등 위치 파일(관리번호 · 좌표) → 줄인 표 data/seoul/lamps.tsv.gz (관리번호 \t 경도 \t 위도 \t 오차 m).

    python3 -I demo/call/tools/build_lamps.py <서울시 가로등 폴더> [<구 가로등 폴더> <상가정보 zip>]

출처(모두 공공데이터포털, 이용허락범위 제한 없음, 가입 · 열쇠 없이 그 쪽 내려받기 단추가 부르는 주소 그대로 받음. 받은 파일은 레포 밖에 두고 읽기만 한다):
- 15107934 「서울특별시_가로등 위치 정보_20221108」(서울특별시): 관리번호 · 위도 · 경도 19,316개. 자동차전용도로와 한강 다리(「강_36-30」 꼴).
- 15070592 「서울특별시 광진구_가로등 위치정보_20220214」: 관리번호(「아차산로2-6」 꼴) · 위도 · 경도.
- 15107876 「서울특별시 영등포구_가로등 위치정보_20240826」: 관리번호(「당산1동-189」) · 도로명주소 → 좌표가 없어 상가정보의 같은 주소 건물 자리로 맞춘다(오차 30m로 둠).
- 15062578 「서울특별시 서대문구_가로등 현황_20240101」: 관리번호(「가재울로1-15」) · 지번주소 → 같은 식으로 맞춘다.
  (15037330 동작구 파일은 번호가 숫자뿐이고 좌표 · 도로명이 없어 넣지 않았다.)
같은 번호가 서로 500m 넘게 떨어져 두 번 나오면 어느 쪽인지 몰라 뺀다.
"""
import csv
import gzip
import io
import math
import re
import sys
import zipfile
from pathlib import Path

out = Path(__file__).resolve().parents[1] / "data" / "seoul" / "lamps.tsv.gz"
rows = []                                          # (번호, 경도, 위도, 오차 m, 출처)


def ok(la, lo):
    return 37.4 < la < 37.72 and 126.7 < lo < 127.3


for line in (Path(sys.argv[1]) / "lamps.csv").read_text(encoding="cp949").splitlines()[1:]:
    no, lat, lon = (line.split(",") + ["", ""])[:3]
    try:
        la, lo = float(lat), float(lon)
    except ValueError:
        continue
    if no.strip() and ok(la, lo):                  # 좌표가 비었거나 서울 밖인 줄은 뺀다
        rows.append((no.strip(), lo, la, 12, "서울시"))

if len(sys.argv) > 3:
    gu_dir = Path(sys.argv[2])
    read = lambda pk: list(csv.reader(io.StringIO((gu_dir / pk / f"{pk}.csv").read_bytes().decode("cp949"))))[1:]   # noqa: E731
    for no, lat, lon in (r[:3] for r in read("15070592")):
        try:
            if ok(float(lat), float(lon)):
                rows.append((no.strip(), float(lon), float(lat), 12, "광진구"))
        except ValueError:
            pass
    # 주소 → 좌표: 상가정보에서 같은 주소에 든 가게들의 가운데
    z = zipfile.ZipFile(sys.argv[3])
    info = next(i for i in z.infolist() if "서울" in (i.filename if i.flag_bits & 0x800 else i.filename.encode("cp437").decode("cp949", "replace")))
    r = csv.reader(io.TextIOWrapper(z.open(info), encoding="utf-8-sig"))
    H = {h: i for i, h in enumerate(next(r))}
    acc = {}
    for row in r:
        gu = row[H["시군구명"]]
        if gu not in ("영등포구", "서대문구"):
            continue
        try:
            lo, la = float(row[H["경도"]]), float(row[H["위도"]])
        except ValueError:
            continue
        road = row[H["도로명"]].split(" ")[-1]
        keys = [(gu, road, row[H["건물본번지"]], row[H["건물부번지"]] or "0"), (gu, road, row[H["건물본번지"]], "*"),
                (gu, row[H["법정동명"]], row[H["지번본번지"]], row[H["지번부번지"]] or "0"), (gu, row[H["법정동명"]], row[H["지번본번지"]], "*")]
        for k in keys:
            acc.setdefault(k, []).append((lo, la))
    where = {k: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for k, v in acc.items()}
    miss = {"영등포구": 0, "서대문구": 0}
    for no, addr, *_ in read("15107876"):
        m = re.search(r"영등포구\s*(\S+?(?:로|길))\s*(\d+)(?:-(\d+))?\s*$", addr)       # 「당산로18길1-4」 → 당산로18길 · 1 · 4
        p = m and (where.get(("영등포구", m.group(1), m.group(2), m.group(3) or "0")) or where.get(("영등포구", m.group(1), m.group(2), "*")))
        if p:
            rows.append((no.strip(), *p, 30, "영등포구"))
        else:
            miss["영등포구"] += 1
    for _, _, addr, _, no in (r[:5] for r in read("15062578")):
        m = re.match(r"\s*(\S+동)\s*(?:산\s*)?(\d+)(?:-(\d+))?", addr)
        p = m and (where.get(("서대문구", m.group(1), m.group(2), m.group(3) or "0")) or where.get(("서대문구", m.group(1), m.group(2), "*")))
        if p:
            rows.append((re.sub(r"\s+", "", no), *p, 30, "서대문구"))
        else:
            miss["서대문구"] += 1
    print("주소로 맞추지 못한 번호:", miss)

seen = {}
for row in rows:
    seen.setdefault(row[0], []).append(row)
keep, amb = [], 0
for no, rs in seen.items():
    if any(math.hypot((a[1] - b[1]) * 88200, (a[2] - b[2]) * 111000) > 500 for a in rs for b in rs):
        amb += 1
        continue
    keep.append(rs[0])
with gzip.open(out, "wt", encoding="utf-8") as f:
    f.write("\n".join(f"{no}\t{lo:.6f}\t{la:.6f}\t{e}" for no, lo, la, e, _ in keep) + "\n")
by = {}
for k in keep:
    by[k[4]] = by.get(k[4], 0) + 1
print(f"가로등 {len(keep):,}개 {by} (같은 번호가 멀리 두 번 나와 뺀 것 {amb}) → {out} ({out.stat().st_size:,}바이트)")
