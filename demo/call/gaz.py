"""서울 지명 표(data/seoul/)를 읽고, 시민의 말에서 지명 · 간판 · 건물 · 프랜차이즈 이름을 찾는다. 자료를 갈아 끼우는 곳은 이 파일 하나다.

- 자료: tools/build_gazetteer.py가 오픈스트리트맵 서울 발췌본에서 만든 places.tsv · roads.json · areas.json + 손으로 넣은 data/extra_places.json
  + 상가정보 가게(shops) · 공원 안 시설(park_things) · 공원 안 화장실(park_toilets) · 공원 안 이름(park_names) · 나가는 길 · 들어오는 길(ramps) · 표준노드링크의 자동차전용도로 표지(road_nodes) · 가로등 번호(lamps). 만드는 법은 README.
- 이름 맞추기는 모델 없이 한다(빠르다): 다듬기 → 다른 이름 사전 → 가장 긴 이름부터 그대로 찾기 → 장소 꼴 낱말은 자모 편집 거리로 비슷한 이름 찾기.
  흔한 낱말과 같은 가게 이름(「오늘」 · 「사슴」)이 잘못 걸리지 않게, 눈에 덜 띄는 종류는 네 글자 이상이거나 뒤에 장소를 가리키는 말이 올 때만 받는다.
- 좌표는 서울 가운데를 원점으로 한 m(동서 x, 남북 y)로 바꿔 쓴다.
"""
import functools
import gzip
import json
import math
import os
import re
import unicodedata
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DIR = HERE / "data" / "seoul"
ON = set(filter(None, os.environ.get("CALL_ON", "").split(",")))      # 켠 스위치. locate.py가 기본값(DEFAULT_ON)까지 넣은 것으로 다시 정한다(gaz.ON = ON)
LON0, LAT0, KX, KY = 127.0, 37.55, 88200.0, 111000.0
HIGH = {"역", "역 출구", "다리", "공원", "나들목", "터널", "교차로", "학교", "병원", "관공서", "마트", "볼거리", "터미널", "선착장", "동네", "산", "시장",
        "경찰", "소방서", "체육시설", "문화시설", "육교", "길", "자치구", "동", "별명"}          # 이름만 들어도 장소로 볼 종류
ALIAS_FILE = Path(os.environ.get("CALL_ALIAS_FILE") or HERE / "data" / "aliases_local.json")      # 상담사가 저장한 별명(git에 올리지 않는다). 점검은 다른 파일에
ROADSIDE = {"다리", "나들목", "터널", "교차로", "역", "육교", "주유소", "진출입로", "터미널"}       # 차를 타고 지나며 볼 만한 것
GENERIC = re.compile(r"^(\d+동|\d+호|[A-Za-z]동|제?\d+주차장|정자|어린이놀이터|놀이터|화장실|주차장|관리사무소|경비실|정문|후문|입구|출구|공원|쉼터|벤치|매점|분수|광장|약수터|운동기구|음수대|운동장|전망대|[\d\-.,·]+)$")     # 숫자뿐인 이름(「34-6」 · 「10-1」, 오픈스트리트맵의 번지 꼴 1,118개)은 표지로 쓰지 않는다(11-15)
STOP = set("""공원 화장실 주차장 편의점 카페 약국 병원 학교 교회 은행 식당 마트 놀이터 정자 입구 정문 후문 출구 사거리 삼거리 횡단보도 육교 다리 도로 방향 근처
우리 여기 저기 거기 지금 아까 사람 동물 고양이 강아지 신고 전화 차로 차선 갓길 오른쪽 왼쪽 건너편 맞은편 상가 아파트 빌딩 건물 가게 시장 버스 지하철 택시
자전거 오토바이 한강 서울 오늘 어제 내일 하루 이모 우리집 그집 이집 앞집 옆집 처음 마지막 중간 가운데 사이 하나 둘 정도 조금 바로 방금 지금쯤 운전 산책 길가
인도 차도 골목 동네 근방 부근 주변 이쪽 저쪽 그쪽 안쪽 바깥 주인 목줄 인식표 민원 접수 상담 감사 안녕 여보세요 그런데 그리고 그래서 사실 혹시 진짜 그냥""".split())
ALIAS = {"스벅": "스타벅스", "파바": "파리바게뜨", "파리바게트": "파리바게뜨", "씨유": "cu", "지에스": "gs25", "지에스25": "gs25", "지에스이십오": "gs25", "세븐": "세븐일레븐",
         "맥날": "맥도날드", "롯리": "롯데리아", "올영": "올리브영", "배라": "배스킨라빈스", "투썸": "투썸플레이스", "이디야": "이디야커피", "메가커피": "메가mgc커피",
         "잠실": "잠실역", "강남": "강남역", "건대": "건대입구역", "여의도": "여의동", "이태원": "이태원역", "신림": "신림역", "국민은행": "kb국민은행", "기업은행": "ibk기업은행", "뚜레주르": "뚜레쥬르", "던킨": "던킨도너츠", "이마트이십사": "이마트24"}
ALIAS_KEYS = set()      # 아래에서 채운다(다듬은 꼴)
CATEGORY = {"편의점": "편의점", "카페": "카페", "커피숍": "카페", "커피집": "카페", "약국": "약국", "은행": "은행", "주유소": "주유소", "병원": "병원", "학교": "학교",
            "초등학교": "학교", "중학교": "학교", "고등학교": "학교", "교회": "종교시설", "성당": "종교시설", "화장실": "화장실", "주차장": "주차장", "빵집": "빵집",
            "놀이터": "놀이터", "정류장": "정류장", "버스정류장": "정류장", "파출소": "경찰", "경찰서": "경찰", "소방서": "소방서", "마트": "마트", "육교": "육교",
            "정자": "정자", "운동기구": "운동기구", "음수대": "음수대", "분수": "분수", "전망대": "전망대"}
PLACE_TAIL = re.compile(r"(대교|교|역|공원|대로|로|길|터널|지하차도|병원|학교|빌딩|타워|마트|시장|아파트|센터|은행|교회|성당|사거리|삼거리|오거리|나들목|분기점|고가|광장|박물관|청|소)$")
AFTER_PLACE = re.compile(r"^.{0,3}(앞|옆|근처|건너|맞은편|간판|보여|보이|보입|있는|있어|쪽|지나|지났|에서|이라고|라고|라는|부근|인근|사이|뒤|밑|아래|위)")
SHOP_AFTER = re.compile(r"^(이|가|은|는|도|이라는|라는|이라고|라고)?(바로)?(앞|옆|건너|맞은편|간판|근처|쪽|부근|사이|뒤|있는|있어|있고|보여|보이|보입|에서|이에요|예요|이요|입니다|인데)")
SHOP_AFTER2 = re.compile(SHOP_AFTER.pattern.replace("있는|", "있는|있잖|있죠|있거든|이라는데|라는데|"))     # (hasjanha, 기본 끔 · 53번) 「프로세탁 있잖아요, 그 근처예요」
COMMON = set("""가로등 보안등 신호등 전봇대 맨홀 쓰레기 쓰레기통 벤치 노점 좌판 자전거 따릉이 거치대 공사 담배 흡연 주차 불법주차 도로 골목 인도 차도 보도 동물 고양이 강아지
사람 아이 아저씨 아줌마 할머니 할아버지 학생 경찰 구급차 소방차 버스 택시 트럭 오토바이 승용차 갓길 가드레일 중앙선 횡단보도 정류장 지하철 엘리베이터 계단 화단 나무 잔디
운동기구 산책로 분수대 연못 다리 터널 고가 육교 하천 개천 공원 놀이터 주택 빌라 원룸 상가 가게 식당 시장 마트 편의점 카페 교회 학교 학원 병원 약국 은행""".split())    # 상가정보의 가게 이름 가운데 민원 말에 흔히 나오는 낱말(「가로등이 꺼져 있어요」의 가로등은 가게가 아니다)
JOSA = re.compile(r"(이라고|라고|에서는|에서|으로는|으로|까지|부터|이랑|하고|한테|이요|인데요|인데|이고|이에요|예요|입니다|이|가|은|는|을|를|에|로|도|랑|와|과|요)$")
ENDS = re.compile(r"(이라고|라고|에서는|에서|까지|부터|이랑|하고|한테|이요|인데요|인데|이고|이에요|예요|입니다|이|가|은|는|을|를|에|도|랑|와|과|요)$")     # JOSA에서 「로 · 으로」만 뺀 것(「금천로」의 로는 길 이름이다)
NEXT_PART = re.compile(r"^(\d|아파트|빌딩|건물|타워|센터|단지|오피스텔|길|로|대로|역|공원|시장|병원|학교|교회|성당|사거리|삼거리|오거리|대교|터널)")     # 띄어 말한 뒷부분(「복걸로 6길」 · 「롯데캐슬 아파트」)
VERB_TAIL = re.compile(r"(는|은|던|고|서|면|게|며|할|된|진|간|온|큰|운|러|려|다|지|죠)$")      # 움직씨 · 꾸밈 끝(「깔고」 · 「들어오는」): 이름의 앞부분이 아니다
BLDG_TAIL = re.compile(r"(아파트|빌딩|건물|타워|센터|단지|오피스텔)$")     # 몸통만으로 찾을 꼬리: 「롯데캐슬아파트」 → 「롯데캐슬」이 든 이름
LOST_TAIL = re.compile(r"(대교|역|공원|대로|로|길|터널|지하차도|병원|학교|빌딩|타워|마트|시장|아파트|센터|은행|교회|성당|사거리|삼거리|오거리|나들목|분기점|광장|박물관|구청)$")     # 못 찾았다고 알릴 장소 꼴(한 글자 꼬리 「소 · 청 · 교」는 「주소」 같은 말과 헷갈려 뺀다)
NOT_LOST = set("""고속도로 도로 대로 찻길 차길 골목길 뒷길 샛길 큰길 산책로 산책길 자전거길 자전거도로 오솔길 교차로 사거리 삼거리 오거리 지하철역 전철역 기차역 버스정류장
저희아파트 우리아파트 동네공원 근처공원 집앞길 가는길 오는길 지하도 지하차도 고가도로 갓길 인도 차도 보도""".split())      # 장소 꼴이지만 이름이 아닌 말


def _fill_alias_keys():
    ALIAS_KEYS.update(norm(a) for a in ALIAS)


def xy(lon, lat):
    return (np.asarray(lon, float) - LON0) * KX, (np.asarray(lat, float) - LAT0) * KY


def lonlat(x, y):
    return [round(LON0 + float(x) / KX, 6), round(LAT0 + float(y) / KY, 6)]


JIJUM = re.compile(r"([가나다라마바사])\s?([가나다라마바사아])\s?(\d{4})\s?(\d{4})")


def jijum(text):
    """말 속의 국가지점번호(「다사 5381 5262」) → [(읽은 꼴, x, y)]. 번호가 곧 좌표다: 100km 칸 글자 둘 + 동쪽 · 북쪽 10m 단위 네 자리씩(UTM-K, GRS80).
    칸 글자의 기준(가 = 동 700km · 북 1,300km)과 투영 값은 내가 아는 꼴을 따랐고 공식 고시문과 대조하지 못했다. 역변환 식은 정방향 식으로 되돌려 0.1m 안으로 맞는 것만 확인했다."""
    out = []
    for m in JIJUM.finditer(text or ""):
        e = 700000 + "가나다라마바사".index(m.group(1)) * 100000 + int(m.group(3)) * 10 + 5
        n = 1300000 + "가나다라마바사아".index(m.group(2)) * 100000 + int(m.group(4)) * 10 + 5
        a, f, k0, lon0, lat0 = 6378137.0, 1 / 298.257222101, 0.9996, math.radians(127.5), math.radians(38.0)
        e2 = f * (2 - f)
        ep2, e1 = e2 / (1 - e2), (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
        arc = lambda p: a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * p - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * p)   # noqa: E731
                             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * p) - (35 * e2 ** 3 / 3072) * math.sin(6 * p))
        mu = (arc(lat0) + (n - 2000000) / k0) / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
        p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu) + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
        c1, t1 = ep2 * math.cos(p1) ** 2, math.tan(p1) ** 2
        n1, r1 = a / math.sqrt(1 - e2 * math.sin(p1) ** 2), a * (1 - e2) / (1 - e2 * math.sin(p1) ** 2) ** 1.5
        d = (e - 1000000) / (n1 * k0)
        lat = p1 - (n1 * math.tan(p1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24 + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
        lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(p1)
        x, y = xy(math.degrees(lon), math.degrees(lat))
        out.append((f"{m.group(1)}{m.group(2)} {m.group(3)} {m.group(4)}", float(x), float(y)))
    return out


def norm_lamp(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).replace("번", " ")


def lamp_key(no):
    """가로등 관리번호를 찾기 좋은 꼴로: 한글 · 영문 앞말(붙여서) / 숫자 묶음(앞의 0은 뗀다) / 사이 글자."""
    m = re.match(r"^\s*([가-힣A-Za-z ]+?)\s*[_\-]?\s*(\d+.*)$", unicodedata.normalize("NFKC", no))
    if not m:
        return None
    parts = [m.group(1).replace(" ", "").lower()] + [str(int(t)) if t.isdigit() else t.lower() for t in re.findall(r"\d+|[A-Za-z]+", m.group(2))]
    return "/".join(parts)


def norm(s):
    """이름 다듬기: 전각 → 반각, 소문자, 공백 · 기호 지우기."""
    return re.sub(r"[\s\-\.·,()\[\]'\"~/&]", "", unicodedata.normalize("NFKC", s or "").lower())


def ic_variants(name):
    """나들목 이름의 같은 말들(다듬은 꼴): IC = 나들목 = 아이씨, JC = 분기점 = 제이씨. 「길음」처럼 맨이름이면 「길음나들목」 · 「길음ic」."""
    n = norm(name)
    m = re.match(r"^(.{2,}?)(ic|나들목|아이씨|jc|분기점|제이씨)$", n)
    if not m:
        return {n, n + "나들목", n + "ic"} if 2 <= len(n) <= 5 else {n}
    return {n} | {m.group(1) + t for t in (("ic", "나들목", "아이씨") if m.group(2) in ("ic", "나들목", "아이씨") else ("jc", "분기점", "제이씨"))}


def jamo(s):
    out = []
    for ch in s:
        c = ord(ch) - 0xAC00
        out.append(chr(0x1100 + c // 588) + chr(0x1161 + c % 588 // 28) + (chr(0x11A7 + c % 28) if c % 28 else "") if 0 <= c < 11172 else ch)
    return "".join(out)


_SV = {1: 5, 3: 7, 10: 15, 11: 15}                                                            # 가운뎃소리: ㅐ→ㅔ · ㅒ→ㅖ · ㅙ · ㅚ → ㅞ
_SI = {1: 0, 4: 3, 8: 7, 10: 9, 13: 12, 14: 12, 15: 0, 16: 3, 17: 7}                           # 첫소리: 된소리 · 거센소리 → 예사소리
_SF = {2: 1, 3: 1, 9: 1, 24: 1, 5: 4, 6: 4, 19: 7, 20: 7, 22: 7, 23: 7, 25: 7, 27: 7, 11: 8, 12: 8, 13: 8, 15: 8, 10: 16, 14: 17, 18: 17, 26: 17}   # 받침: 대표음 일곱


@functools.lru_cache(maxsize=None)
def _ear1(ch):
    c = ord(ch) - 0xAC00
    if not 0 <= c < 11172:
        return ch
    i, v, f = _SI.get(c // 588, c // 588), _SV.get(c % 588 // 28, c % 588 // 28), _SF.get(c % 28, c % 28)
    return chr(0x1100 + i) + chr(0x1161 + v) + (chr(0x11A7 + f) if f else "")


def ear(s):
    """소리 열쇠: 받아 적기 · 빨리 친 글이 자주 헷갈리는 차이(ㅐ/ㅔ, 된소리 · 거센소리, 받침의 같은 소리)를 지운 자모 줄(11-15 「롯데케슬」 → 「롯데캐슬」)."""
    return "".join(_ear1(ch) for ch in s)


def ear_grams(s):
    """두 글자 조각을 소리 열쇠로(「증싼역」과 「증산역」이 같은 조각을 갖게)."""
    return {_ear1(s[j]) + _ear1(s[j + 1]) for j in range(len(s) - 1)}


def phrases(text):
    """정확히 못 찾았을 때 견줄 말 조각 → [(보일 꼴, 다듬은 꼴들, 시작, 끝)]. 낱말 하나, 그리고 뒷낱말이 숫자 · 장소 꼬리로 시작하면 둘을 붙인 것(붙인 것이 먼저)."""
    ws, out = list(re.finditer(r"[가-힣A-Za-z0-9]+", text or "")), []
    for n, m in enumerate(ws):
        head = norm(ENDS.sub("", m.group()))
        pair = (n + 1 < len(ws) and NEXT_PART.match(ws[n + 1].group()) and not text[m.end():ws[n + 1].start()].strip() and len(head) >= 2 and head not in STOP
                and not VERB_TAIL.search(m.group()) and not re.search(r"(?<!\d)(이|가|을|를|은|는|에|의)$", m.group()))          # 띄어쓰기로만 떨어진 이름의 뒷부분. 토씨가 붙은 앞 낱말(「노점이 길을」)은 붙이지 않는다(「종로3가 3번 출구」의 3가는 이름). 「저기요, 공원에」 · 「우리 아파트」 · 「깔고 길을」 · 「들어오는 길」은 붙이지 않는다
        for a, b in ([(m.start(), ws[n + 1].end())] if pair else []) + [(m.start(), m.end())]:
            forms = [f for f in dict.fromkeys((norm(ENDS.sub("", text[a:b])), norm(JOSA.sub("", text[a:b])))) if len(f) >= 3]
            if forms:
                out.append((ENDS.sub("", text[a:b]).strip(), forms, a, b))
    return out


def same_digits(a, b):
    return re.findall(r"\d+", a) == re.findall(r"\d+", b)


def similar(a, b, by_ear=False):
    """자모 단위 편집 거리로 잰 비슷함(0~1). 받아 적기가 한 자모쯤 틀려도 걸린다. by_ear면 소리 열쇠로 견준다."""
    a, b = (ear(a), ear(b)) if by_ear else (jamo(a), jamo(b))
    if abs(len(a) - len(b)) > 3:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1 - prev[-1] / max(len(a), len(b), 1)


def _ring(flat):
    a = np.asarray(flat, float).reshape(-1, 2)
    return np.column_stack(xy(a[:, 0] / 1e5 + 126, a[:, 1] / 1e5 + 37))


def _open(name):
    f = DIR / name
    return gzip.open(str(f) + ".gz", "rt", encoding="utf-8") if not f.exists() else open(f, encoding="utf-8")


class Gazetteer:
    def __init__(self):
        rows = [ln.rstrip("\n").split("\t") for ln in _open("places.tsv")]
        self.shop0 = len(rows)                # 여기부터 상가(상권)정보의 가게(tools/build_sangga.py). CALL_SHOPS=0이면 넣지 않는다(넣기 전과 견줄 때)
        if os.environ.get("CALL_SHOPS", "1") != "0" and (DIR / "shops.tsv.gz").exists():
            rows += [ln.rstrip("\n").split("\t") for ln in gzip.open(DIR / "shops.tsv.gz", "rt", encoding="utf-8")]
        self.shop1 = len(rows)
        if (DIR / "park_things.tsv.gz").exists():     # 공원 안의 이름 없는 시설(화장실 · 정자 · 음수대 …): 이름은 종류 낱말이라 이름 찾기에는 안 걸리고 「보이는 종류」 질문에만 쓴다
            rows += [[k, k, lo, la, "", ""] for k, lo, la in (ln.rstrip("\n").split("\t") for ln in gzip.open(DIR / "park_things.tsv.gz", "rt", encoding="utf-8"))]
        if os.environ.get("CALL_TOILETS", "1") != "0" and (DIR / "park_toilets.tsv.gz").exists():     # 서울시 공중화장실 위치정보 가운데 공원 안의 것(tools/build_toilets.py). 종류 낱말뿐이라 「보이는 종류」 질문에만 쓴다. CALL_TOILETS=0이면 넣지 않는다
            rows += [[k, k, lo, la, "", ""] for k, lo, la in (ln.rstrip("\n").split("\t") for ln in gzip.open(DIR / "park_toilets.tsv.gz", "rt", encoding="utf-8"))]
        self.pk0 = len(rows)
        if os.environ.get("CALL_PARKNAMES", "1") != "0" and (DIR / "park_names.tsv.gz").exists():     # 공원 안의 이름 붙은 호수 · 광장 · 숲 · 산책길(tools/build_park_names.py, 33번 2-5). 면은 테두리 점들. CALL_PARKNAMES=0이면 넣지 않는다
            rows += [r[:4] + ["", ""] for r in (ln.rstrip("\n").split("\t") for ln in gzip.open(DIR / "park_names.tsv.gz", "rt", encoding="utf-8"))]
        self.pk1 = len(rows)
        heads = []
        if os.environ.get("CALL_RAMPS", "1") != "0" and (DIR / "ramps.tsv.gz").exists():     # 자동차전용도로의 나가는 길 · 들어오는 길(tools/build_ramps.py, 33번 3-3). 방향이 있는 점. CALL_RAMPS=0이면 넣지 않는다
            for ln in gzip.open(DIR / "ramps.tsv.gz", "rt", encoding="utf-8"):
                r = ln.rstrip("\n").split("\t")
                rows.append(r[:4] + ["", ""])
                heads.append((float(r[5]), float(r[6])))
        self.rp0, self.rp1 = self.pk1, len(rows)
        self.rhead = np.array(heads, float).reshape(-1, 2)      # 그 점에서 본선의 가는 방향(단위 벡터)
        self.node0 = len(rows)                # 여기부터 표준노드링크의 자동차전용도로 표지(나들목 · 터널 · 다리, tools/build_nodelink.py). CALL_NODES=0이면 넣지 않는다(넣기 전과 견줄 때)
        if os.environ.get("CALL_NODES", "1") != "0" and (DIR / "road_nodes.tsv.gz").exists():
            rows += [r[:4] + ["", ""] for r in (ln.rstrip("\n").split("\t") for ln in gzip.open(DIR / "road_nodes.tsv.gz", "rt", encoding="utf-8"))]
        self.node1 = len(rows)
        extra = json.loads((HERE / "data" / "extra_places.json").read_text(encoding="utf-8"))["places"] if (HERE / "data" / "extra_places.json").exists() else []
        if ALIAS_FILE.exists():                       # 상담사가 저장한 별명(사람들이 부르는 이름 → 확인받은 자리). 레포에 올리지 않는 로컬 파일
            extra += [dict(a, kind="별명") for a in json.loads(ALIAS_FILE.read_text(encoding="utf-8"))]
        rows += [[e["name"], e["kind"], str(e["lon"]), str(e["lat"]), "", ""] for e in extra]
        self.name, self.kind, self.brand = [r[0] for r in rows], [r[1] for r in rows], [r[4] for r in rows]
        self.x, self.y = xy([float(r[2]) for r in rows], [float(r[3]) for r in rows])
        areas = json.load(_open("areas.json"))
        self.parks = [{"name": p["name"], "ring": _ring(p["ring"])} for p in areas["parks"]]
        self.gu = [{"name": g["name"], "ring": _ring(g["ring"])} for g in areas["gu"]]
        self.dong = [{"name": d["name"], "ring": _ring(d["ring"])} for d in areas["dong"]]
        self.seoul = _ring(areas["seoul"])
        for a in self.parks + self.gu + self.dong:
            r = a["ring"]
            a["box"] = (r[:, 0].min(), r[:, 1].min(), r[:, 0].max(), r[:, 1].max())
        self.roads = json.load(_open("roads.json"))["roads"]
        # 가로등 관리번호 → 자리(서울시 관리분: 자동차전용도로와 한강 다리). 번호는 「앞말 + 숫자 묶음」으로 쪼개 찾는다(「강_36-30」 = 강 / 36 / 30)
        self.lamps, self.lamp_pre, self.lamp_err = {}, set(), {}      # lamp_err = 번호 → 자리의 오차(m). 주소로 맞춘 구청 가로등은 30m
        if (DIR / "lamps.tsv.gz").exists():
            for ln in gzip.open(DIR / "lamps.tsv.gz", "rt", encoding="utf-8"):
                no, lo, la, *err = ln.rstrip("\n").split("\t")
                key = lamp_key(no)
                if key:
                    self.lamps[key] = (no, *(float(v) for v in xy(float(lo), float(la))))
                    self.lamp_err[no] = float(err[0]) if err else 12.0
                    self.lamp_pre.add(key.split("/")[0])
            self.lamp_re = re.compile(r"(?<![가-힣0-9A-Za-z])(" + "|".join(sorted((re.escape(p) for p in self.lamp_pre), key=len, reverse=True)) + r")\s*[_\-]?\s*(\d{1,3})\s*동?\s*([A-Za-z])?\s*(?:[_\-]|다시|에|번)?\s*(\d{1,4})?", re.I)   # 「당산1동-189」의 「동」도 건너뛴다
        self._road_xy = {}
        # 이름 → 가리키는 것들: ("p", 장소 번호) · ("r", 길 번호) · ("park" | "gu" | "dong", 번호)
        ix = {}
        add = lambda key, ref: ix.setdefault(key, []).append(ref) if len(key) >= 2 else None   # noqa: E731
        for i, (n, k, b) in enumerate(zip(self.name, self.kind, self.brand)):
            if GENERIC.match(n.replace(" ", "")):
                continue
            add(norm(n), ("p", i))
            if k == "나들목":
                for v in ic_variants(n) - {norm(n)}:     # 「신내IC」 = 「신내 나들목」, 「성수JC」 = 「성수 분기점」
                    add(v, ("p", i))
            if b and norm(b) != norm(n):
                add(norm(b), ("p", i))
            m = re.match(r"^(.{2,}?)\s+\S*(점|지점|본점|센터)$", n)          # 「스타벅스 성수역점」 → 「스타벅스」로도 찾게
            if m and norm(m.group(1)) not in (norm(b), norm(n)):
                add(norm(m.group(1)), ("p", i))
        for i, e in enumerate(extra, len(rows) - len(extra)):
            for al in e.get("aliases") or []:
                add(norm(al), ("p", i))
        for i, r in enumerate(self.roads):
            add(norm(r["name"]), ("r", i))
        for kind, lst in (("park", self.parks), ("gu", self.gu), ("dong", self.dong)):
            for i, a in enumerate(lst):
                add(norm(a["name"]), (kind, i))
                short = re.sub(r"(동)?(\d+가)?(제?\d+|본)?동$", "동", a["name"]) if kind == "dong" else a["name"]     # 「성수1가1동」 · 「역삼1동」 → 「성수동」 · 「역삼동」
                if short != a["name"]:
                    add(norm(short), (kind, i))
        for al, to in ALIAS.items():
            if norm(to) in ix:
                ix[norm(al)] = ix[norm(to)]
        self.ix = ix
        self.maxlen = 18
        # 비슷한 이름 찾기용: 눈에 띄는 종류의 이름만 두 글자 조각(소리 열쇠)으로 색인한다
        self.gram = {}
        for key, refs in ix.items():
            if len(key) >= 3 and not self.shop_only(refs) and any(self.ref_kind(r) in HIGH or self.brand_like(key) for r in refs[:3]):     # 가게 이름만 있는 이름은 서울 전체에서 비슷한 이름을 찾지 않는다(흔한 낱말과 헷갈림)
                for g in ear_grams(key):
                    self.gram.setdefault(g, []).append(key)
        # 소리가 같은 다른 이름(11-16 결함 2: 「통일로」 · 「동일로」). 길 · 역 · 다리처럼 이름 하나로 자리가 서는 것만(가게 이름은 뺀다)
        self.ear_ix = {}
        for key, refs in ix.items():
            if len(key) >= 3 and not self.shop_only(refs) and any(self.ref_kind(r) in HIGH for r in refs[:40]):
                self.ear_ix.setdefault(ear(key), []).append(key)
        # 가까운 장소 찾기용 격자(250m)
        self.cell = {}
        for i, (cx, cy) in enumerate(zip((self.x // 250).astype(int), (self.y // 250).astype(int))):
            self.cell.setdefault((cx, cy), []).append(i)

    def add_alias(self, name, lon, lat):
        """별명 하나를 지금 떠 있는 지명 표에 더한다(파일에 적는 것은 서버가 한다)."""
        x, y = xy(lon, lat)
        i = len(self.name)
        self.name.append(name), self.kind.append("별명"), self.brand.append("")
        self.x, self.y = np.append(self.x, float(x)), np.append(self.y, float(y))
        self.ix.setdefault(norm(name), []).append(("p", i))
        self.cell.setdefault((int(float(x) // 250), int(float(y) // 250)), []).append(i)
        return i

    def alike(self, key):
        """소리 열쇠가 같은 다른 이름들(받아 적기로는 가를 수 없다). 없으면 [].
        ponytail: 길 · 역 · 다리 같은 이름만 본다. 가게 이름끼리 소리가 같은 것(「그린세탁」 · 「크린세탁」)은 보지 않는다 — 가게 이름에도 쓰려면 범위 안에서만 견주게."""
        return sorted(k for k in self.ear_ix.get(ear(key), ()) if k != key) if len(key) >= 3 else []

    def lamp_in(self, text):
        """말 속의 가로등 관리번호 → [(번호, x, y)]. 「강 36 다시 30」 · 「강_36-30」 · 「올 14A-9」."""
        out = []
        for m in (self.lamp_re.finditer(norm_lamp(text)) if self.lamps else ()):
            key = "/".join(x for x in (m.group(1).lower(), str(int(m.group(2))), (m.group(3) or "").lower(), str(int(m.group(4))) if m.group(4) else "") if x)
            if key in self.lamps:
                out.append(self.lamps[key])
        return out

    def shop_only(self, refs):
        return all(r[0] == "p" and self.shop0 <= r[1] < self.shop1 for r in refs[:40])

    def brand_like(self, key):
        return len(self.ix.get(key, ())) >= 8

    def ref_kind(self, ref):
        return self.kind[ref[1]] if ref[0] == "p" else {"r": "길", "park": "공원", "gu": "자치구", "dong": "동"}[ref[0]]

    def road_xy(self, i):
        """길 i의 선을 20m마다 찍은 점들(x, y). 처음 쓸 때 만들어 둔다."""
        if i not in self._road_xy:
            pts = []
            for line in self.roads[i]["lines"]:
                r = _ring(line)
                for (x1, y1), (x2, y2) in zip(r, r[1:]):
                    n = max(1, int(math.hypot(x2 - x1, y2 - y1) // 20))
                    t = np.arange(n) / n
                    pts.append(np.column_stack((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)))
                pts.append(r[-1:])
            self._road_xy[i] = np.vstack(pts)
        return self._road_xy[i]

    def near(self, x, y, radius):
        """(x, y)에서 radius m 안의 장소 번호들."""
        out, c = [], int(radius // 250) + 1
        cx, cy = int(x // 250), int(y // 250)
        for a in range(cx - c, cx + c + 1):
            for b in range(cy - c, cy + c + 1):
                out += self.cell.get((a, b), ())
        out = np.asarray(out, int)
        return out[np.hypot(self.x[out] - x, self.y[out] - y) <= radius] if len(out) else out

    def mentions(self, text):
        """시민의 말에서 찾은 이름들 → [{key, said, name, kinds, n, fuzzy, after}]. after = 그 이름 바로 뒤의 말(관계를 읽는 데 쓴다)."""
        t = norm(text)
        out, i, covered = [], 0, []
        while i < len(t):
            hit = None
            for ln in range(min(self.maxlen, len(t) - i), 1, -1):
                key = t[i:i + ln]
                refs = self.ix.get(key)
                if refs and self._accept(key, refs, t[i + ln:i + ln + 8]):
                    hit = (key, ln)
                    break
            if hit:
                key, ln = hit
                m = re.search(r"(앞|옆|입구|근처|건너편|맞은편|뒤|사거리)$", key)      # 「GS25앞」이라는 정류장보다 「GS25」 + 「앞」으로 읽는다
                if m and self.brand_like(key[:m.start()]) and len(self.ix[key]) < 3:
                    key, ln = key[:m.start()], ln - len(m.group())
                out.append(self._mention(key, key, False, t[i + ln:i + ln + 14]))
                covered.append((i, i + ln))
                i += ln
            else:
                i += 1
        for n, (m, (a, b)) in enumerate(zip(out, covered)):     # 관계 말(「방향」 · 「쪽」 · 「지나서」)은 바로 앞 이름의 것: 다른 이름이 나오기 전까지만(「올림픽대로 잠실 방향」의 방향은 잠실의 것, 11-16). 같은 이름을 되풀이한 것(「성수대교요. 성수대교 지났고」)은 이어 본다
            nxt = next((c[0] for o, c in zip(out[n + 1:], covered[n + 1:]) if o["key"] != m["key"]), len(t))
            m["own"] = m["after"][:max(0, nxt - b)]
        # 그대로는 없지만 장소 꼴인 말은 비슷한 이름을 찾는다(받아 적기 오류 · 틀리게 부른 이름). 띄어 말한 것은 붙여 보고(「복걸로 6길」),
        # 소리 열쇠로 견주고(「롯데케슬」 = 「롯데캐슬」), 숫자는 같아야 한다(「6길」 ≠ 「16길」). 그래도 없으면 몸통이 구 · 동인지 본다(「금천로」 → 금천구)
        used = []
        for raw, forms, a, b in phrases(text):
            if any(a < y and x < b for x, y in used):
                continue
            for tok in forms:
                if tok in STOP or tok in self.ix or any(o["key"] in tok or tok in o["key"] for o in out):
                    continue
                need = 0.84 if PLACE_TAIL.search(tok) else 0.87 if len(tok) >= 4 else 2      # 장소 꼴이 아닌 낱말은 더 엄하게, 세 글자는 받지 않는다
                best = self.near_name(tok)
                key = best[1] if best[0] >= need else self.tail_swap(tok)
                if key:
                    out.append(self._mention(key, raw, True, norm(text[a:b])[len(tok):] + norm(text[b:b + 14])))
                    used.append((a, b))
                    break
        return out

    def near_name(self, tok):
        """서울 전체의 눈에 띄는 이름 가운데 소리가 가장 가까운 것 → (비슷함, 이름)."""
        cands = {}
        for g in ear_grams(tok):
            for key in self.gram.get(g, ()):
                cands[key] = cands.get(key, 0) + 1
        return max(((similar(tok, key, True), key) for key, c in cands.items() if c >= max(1, (len(tok) - 1) // 2) and abs(len(key) - len(tok)) <= 1 and same_digits(tok, key)), default=(0, None))

    def tail_swap(self, tok):
        """없는 이름인데 꼬리를 떼면 구 · 동 이름의 몸통과 같다(「금천로」 → 금천구, 「성수로」 → 성수동) → 그 구 · 동."""
        m = re.match(r"^(.{2,}?)(로|길|구|동)$", tok)
        for t in ("구", "동") if m else ():
            if m.group(1) + t != tok and any(r[0] in ("gu", "dong") for r in self.ix.get(m.group(1) + t, ())):
                return m.group(1) + t
        return None

    def _accept(self, key, refs, after):
        if key in STOP or key in CATEGORY or GENERIC.match(key) or key.isdigit():      # 숫자뿐인 이름(「8-15」)은 번호를 읽어 준 말과 헷갈려 받지 않는다
            return False
        if self.shop_only(refs) and key not in ALIAS_KEYS:            # 상가정보에만 있는 가게 이름은 바로 뒤에 「앞 · 옆 · 간판 · 보여 …」가 올 때만(「갤러리」 · 「가로등」 같은 흔한 낱말)
            return len(key) >= 3 and key not in COMMON and bool((SHOP_AFTER2 if "hasjanha" in ON else SHOP_AFTER).match(after))
        kinds = {self.ref_kind(r) for r in refs[:40]}
        if kinds & HIGH or self.brand_like(key) or key in ALIAS_KEYS:
            return len(key) >= 3 or key in ALIAS_KEYS or key == "cu" or bool(kinds & {"자치구", "역"})
        return len(key) >= 4 or (len(key) >= 3 and bool(AFTER_PLACE.match(after)))      # 눈에 덜 띄는 종류(가게 · 음식점 등)

    def _mention(self, key, said, fuzzy, after):
        refs = self.ix[key]
        r0 = next((r for r in refs if r[0] in ("gu", "dong", "park")), refs[0])      # 구 · 동 · 공원 이름이면 그 이름으로 보인다(「마포구 ○○센터」가 아니라 「마포구」)
        name = self.name[r0[1]] if r0[0] == "p" else self.roads[r0[1]]["name"] if r0[0] == "r" else {"park": self.parks, "gu": self.gu, "dong": self.dong}[r0[0]][r0[1]]["name"]
        if len(refs) > 1 and r0[0] == "p" and self.brand[r0[1]]:
            name = self.brand[r0[1]]
        kinds = sorted({self.ref_kind(r) for r in refs[:60]}, key=(lambda k: (k not in HIGH, k not in ("자치구", "동", "공원"), k)) if "kindorder" in ON else (lambda k: k not in HIGH))
        # (kindorder, 기본 끔 · 53번) 눈에 띄는 종류가 둘 이상이면 차례가 파이썬 해시 씨앗에 따라 달라져, 같은 말이 프로세스마다 다르게 읽혔다(49번 1125 #56). 구 · 동 · 공원을 먼저, 나머지는 글자 차례로
        return {"key": key, "said": said, "name": name, "kinds": kinds[:3], "n": len(refs), "fuzzy": fuzzy, "after": after}

    def display(self, key):
        """다듬은 이름 → 보일 이름."""
        refs = self.ix.get(key)
        return self._mention(key, key, False, "")["name"] if refs else key

    def categories(self, text):
        t = norm(text)
        return sorted({v for k, v in CATEGORY.items() if k in t})

    def refs(self, key):
        return self.ix.get(key, [])


_fill_alias_keys()
_G = None


def load():
    global _G
    if _G is None:
        _G = Gazetteer()
    return _G


if __name__ == "__main__":
    import time
    t0 = time.time()
    g = load()
    print(f"지명 표: 장소 {len(g.name):,} · 길 {len(g.roads):,} · 공원 {len(g.parks)} · 구 {len(g.gu)} · 동 {len(g.dong)} · 이름 {len(g.ix):,} ({time.time() - t0:.1f}초)")
    for s in ["저기요, 운전하다가 봤는데요. 강변북로에 동물이 차에 치여서 죽어 있어요. 고양이 같았어요.", "성수대교는 지났고요, 영동대교는 아직 안 나왔어요.",
              "서울숲 쪽인데요, 개 한 마리가 주인도 없이 혼자 돌아다니고 있어요.", "사슴 우리 옆에 화장실이 있는데요, 그 바로 앞에 앉아 있어요.",
              "스벅 앞이에요. 건너편에 올리브영도 보이고요.", "성수대고 지나서요", "강남역 11번 출구 앞 파리바게트 근처요", "오늘 아침에 봤어요 지금도 있을 거예요", "뚝섬역 3번 출구 쪽 GS25 앞"]:
        t1 = time.time()
        ms = g.mentions(s)
        print(f"{(time.time() - t1) * 1000:.0f}ms {s[:26]} → {[(m['name'], m['kinds'][0], m['n'], '≈' if m['fuzzy'] else '', m['after'][:6]) for m in ms]} {g.categories(s)}")
    assert similar("성수대고", "성수대교") > 0.84 and similar("파리바게트", "파리바게뜨") > 0.84 and similar("오늘", "오금") < 0.84
    assert similar("롯데케슬아파트", "롯데캐슬아파트", True) == 1.0 and not same_digits("벚꽃로6길", "벚꽃로16길") and g.tail_swap("금천로") == "금천구"
    assert [p[0] for p in phrases("복걸로 6길이에요. 금천로 롯데케슬아파트 앞이에요.")] == ["복걸로 6길", "복걸로", "금천로", "롯데케슬아파트"]
    assert [p[0] for p in phrases("저기요, 공원에 큰 개가 우리 아파트 앞")] == ["아파트"]
    assert not [p for p in phrases("노점이 좌판을 깔고 길을 막고 있어요. 한강공원입구 들어오는 길 막 지나서") if " " in p[0]]
