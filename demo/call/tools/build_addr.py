"""상가(상권)정보에서 서울 가게 자리의 번지(지번주소 · 도로명주소)만 줄인 표(data/seoul/addrs.tsv.gz)로 만든다. 받은 zip은 읽기만 한다.

    python3 -I demo/call/tools/build_addr.py <받은 zip> [지명 표 폴더, 기본 demo/call/data/seoul]

자료: build_sangga.py와 같은 zip(공공데이터포털 15083033, 이용허락범위 제한 없음).
남기는 것: 경도 · 위도 · 지번주소 · 도로명주소(앞의 「서울특별시 」는 뗀다). 같은 주소(지번 + 도로명)는 처음 나온 점 하나만.
접수 카드의 「번지수」 줄이 좁힌 자리에서 가장 가까운 점의 주소를 쓴다(그 자리의 번지가 아닐 수 있어 거리를 같이 보인다).
"""
import csv
import gzip
import io
import json
import sys
import time
import zipfile
from pathlib import Path


def main(src, out):
    src, out = Path(src).expanduser(), Path(out)
    z = zipfile.ZipFile(src)
    info = next(i for i in z.infolist() if "서울" in (i.filename if i.flag_bits & 0x800 else i.filename.encode("cp437").decode("cp949", "replace")))
    r = csv.reader(io.TextIOWrapper(z.open(info), encoding="utf-8-sig"))
    H = {h: i for i, h in enumerate(next(r))}
    seen, keep, n_read = set(), [], 0
    for row in r:
        n_read += 1
        jibun, road = (row[H[k]].removeprefix("서울특별시").strip() for k in ("지번주소", "도로명주소"))
        if not jibun or (jibun, road) in seen:
            continue
        try:
            lon, lat = float(row[H["경도"]]), float(row[H["위도"]])
        except ValueError:
            continue
        seen.add((jibun, road))
        keep.append((f"{lon:.6f}", f"{lat:.6f}", jibun, road))
    keep.sort()
    with gzip.open(out / "addrs.tsv.gz", "wt", encoding="utf-8", compresslevel=9) as f:
        f.write("\n".join("\t".join(x) for x in keep) + "\n")
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    meta["addrs"] = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"), "source": meta.get("shops", {}).get("source", src.name), "zip": src.name,
                     "seoul_rows": n_read, "kept": len(keep), "with_road": sum(1 for x in keep if x[3])}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta["addrs"], ensure_ascii=False), f"{(out / 'addrs.tsv.gz').stat().st_size:,}바이트")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).resolve().parents[1] / "data" / "seoul"))
