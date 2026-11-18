"""상가(상권)정보에서 서울의 「간판이 보이는 가게」만 줄인 표(data/seoul/shops.tsv.gz)로 만든다. 받은 zip은 읽기만 한다(압축을 풀지 않는다).

    python3 -I demo/call/tools/build_sangga.py <받은 zip> [지명 표 폴더, 기본 demo/call/data/seoul]

자료: 공공데이터포털 15083033 「소상공인시장진흥공단_상가(상권)정보」(제공 소상공인시장진흥공단, 이용허락범위 제한 없음).
남기는 것: 이름(상호 + 지점) · 종류 · 경도 · 위도 · 상표. places.tsv와 같은 꼴이라 gaz.py가 그대로 읽는다.
- 간판이 없거나 이름이 흔한 업종은 뺀다: 부동산 · 시설관리 · 임대 · 과학 · 기술(동물병원 · 사진관만 남김), 펜션 · 고시원, 「업소명없음」.
- 같은 이름이 여덟 곳 넘으면 상표로 본다. 큰 프랜차이즈는 간판에 쓰인 이름으로 고친다(「씨유논현」 → 「CU 논현점」).
- 오픈스트리트맵(places.tsv)에 30m 안의 같은 이름 · 같은 상표가 있으면 뺀다. 상가정보끼리 25m 안의 같은 이름도 하나로.
"""
import csv
import gzip
import io
import json
import math
import re
import sys
import time
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

DROP_BIG = {"부동산", "시설관리·임대", "과학·기술"}
KEEP_SCI = {"수의", "사진 촬영"}
DROP_SMALL = {"펜션", "기숙사/고시원", "복권 발행/판매업"}
CHAINS = [(("씨유", "cu"), "CU"), (("지에스25", "gs25"), "GS25"), (("세븐일레븐",), "세븐일레븐"), (("이마트24",), "이마트24"), (("스타벅스",), "스타벅스"),
          (("메가엠지씨커피", "메가커피"), "메가MGC커피"), (("파리바게뜨", "파리바게트"), "파리바게뜨"), (("컴포즈커피",), "컴포즈커피"), (("이디야",), "이디야커피"),
          (("투썸",), "투썸플레이스"), (("빽다방",), "빽다방"), (("비비큐", "bbq"), "BBQ치킨"), (("교촌",), "교촌치킨"), (("비에이치씨", "bhc"), "BHC치킨"),
          (("뚜레쥬르",), "뚜레쥬르"), (("배스킨라빈스",), "배스킨라빈스"), (("롯데리아",), "롯데리아"), (("할리스",), "할리스커피"), (("버거킹",), "버거킹"),
          (("씨제이올리브영", "올리브영"), "올리브영"), (("한국맥도날드", "맥도날드"), "맥도날드"), (("다이소",), "다이소"), (("김밥천국",), "김밥천국")]


def norm(s):
    return re.sub(r"[\s\-\.·,()\[\]'\"~/&]", "", unicodedata.normalize("NFKC", s or "").lower())


def kind_of(big, mid, small):
    if big == "음식":
        return "카페" if small == "카페" else "빵집" if small == "빵/도넛" else "음식점"
    if big == "소매":
        return {"편의점": "편의점", "슈퍼마켓": "마트", "약국": "약국", "주유소": "주유소"}.get(small, "마트" if "대형" in small or "백화점" in small else "가게")
    if big == "보건의료" or small == "동물병원" or mid == "수의":
        return "병원"
    if big == "교육":
        return "학원"
    if big == "숙박":
        return "숙박"
    if mid == "스포츠 서비스":
        return "체육시설"
    if mid == "도서관·사적지":
        return "문화시설"
    return "가게"


def sign(name, branch):
    """→ (보일 이름, 상표 또는 None)."""
    n = norm(name)
    for pres, brand in CHAINS:
        for p in pres:
            if n.startswith(p):
                rest = branch or unicodedata.normalize("NFKC", name)[len(p):].strip() if len(name) >= len(p) else ""
                rest = re.sub(r"^[\s(]+|[\s)]+$", "", rest)
                if rest and not rest.endswith("점"):
                    rest += "점"
                return (f"{brand} {rest}" if rest else brand), brand
    name = " ".join(name.split())
    return (f"{name} {branch}" if branch and branch not in name else name), None


def main(src, out):
    src, out = Path(src).expanduser(), Path(out)
    t0 = time.time()
    osm = {}
    for ln in open(out / "places.tsv", encoding="utf-8") if (out / "places.tsv").exists() else gzip.open(out / "places.tsv.gz", "rt", encoding="utf-8"):
        name, _, lon, lat, brand, _ = ln.rstrip("\n").split("\t")
        x, y = (float(lon) - 127) * 88200, (float(lat) - 37.55) * 111000
        osm.setdefault((int(x // 50), int(y // 50)), []).append((x, y, {norm(name), norm(brand)} - {""}))
    z = zipfile.ZipFile(src)
    info = next(i for i in z.infolist() if "서울" in (i.filename if i.flag_bits & 0x800 else i.filename.encode("cp437").decode("cp949", "replace")))
    r = csv.reader(io.TextIOWrapper(z.open(info), encoding="utf-8-sig"))
    H = {h: i for i, h in enumerate(next(r))}
    rows, why, n_read = [], Counter(), 0
    for row in r:
        n_read += 1
        big, mid, small = row[H["상권업종대분류명"]], row[H["상권업종중분류명"]].strip(), row[H["상권업종소분류명"]]
        name = " ".join(row[H["상호명"]].split()).strip(" ,.-·/")
        if (big in DROP_BIG and mid not in KEEP_SCI) or small in DROP_SMALL:
            why["업종"] += 1
            continue
        if not name or name == "업소명없음" or len(norm(name)) < 2 or norm(name).isdigit() or norm(name) == norm(small):
            why["이름"] += 1
            continue
        try:
            lon, lat = float(row[H["경도"]]), float(row[H["위도"]])
        except ValueError:
            why["좌표"] += 1
            continue
        show, brand = sign(name, row[H["지점명"]].strip())
        rows.append([show, kind_of(big, mid, small), lon, lat, brand, norm(name), name])
    count = Counter(r[5] for r in rows)
    keep, seen = [], {}
    for show, kind, lon, lat, brand, key, name in rows:
        brand = brand or (" ".join(name.split()) if count[key] > 8 else "")
        x, y = (lon - 127) * 88200, (lat - 37.55) * 111000
        names = {norm(show), key, norm(brand)} - {""}
        cx, cy = int(x // 50), int(y // 50)
        if any(math.hypot(a - x, b - y) < 30 and (ns & names) for i in (-1, 0, 1) for j in (-1, 0, 1) for a, b, ns in osm.get((cx + i, cy + j), ())):
            why["지도에 이미 있음"] += 1
            continue
        near = seen.setdefault(norm(show), [])
        if any(math.hypot(a - x, b - y) < 25 for a, b in near):
            why["같은 가게 두 번"] += 1
            continue
        near.append((x, y))
        keep.append((show, kind, f"{lon:.6f}", f"{lat:.6f}", brand, ""))
    keep.sort()
    with gzip.open(out / "shops.tsv.gz", "wt", encoding="utf-8", compresslevel=9) as f:
        f.write("\n".join("\t".join(r) for r in keep) + "\n")
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    meta["shops"] = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"), "source": "공공데이터포털 15083033 소상공인시장진흥공단_상가(상권)정보_20260930 (이용허락범위 제한 없음)",
                     "zip": src.name, "zip_bytes": src.stat().st_size, "seoul_rows": n_read, "kept": len(keep), "dropped": dict(why),
                     "kinds": dict(Counter(r[1] for r in keep).most_common()), "with_brand": sum(1 for r in keep if r[4])}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta["shops"], ensure_ascii=False), f"{(out / 'shops.tsv.gz').stat().st_size:,}바이트", f"{time.time() - t0:.0f}초")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).resolve().parents[1] / "data" / "seoul"))
