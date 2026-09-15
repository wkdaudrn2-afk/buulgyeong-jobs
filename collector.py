#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""부울경 단기알바 수집기 v3 TOP20

원칙
- 공개 페이지에서만 수집
- 로그인/캡차/401/403/429/robots.txt 제한을 우회하지 않음
- 부산·경남·울산, 내일 이후 근무, 1~7일 단기
- 최근 3일 등록 확인 공고 우선. 등록일 미확인은 보충 후보로만 사용
- 하루알바 우선, 그 안에서 일급 높은 순
- 각 소스별 수집 상태를 jobs.json의 diagnostics에 기록
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
TODAY = NOW.date()
TOMORROW = TODAY + timedelta(days=1)
OUT = Path(__file__).with_name("jobs.json")

UA = "Mozilla/5.0 (compatible; BuUlGyeongJobChecker/3.0; +public-pages-only)"
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

REGION_WORDS = (
    "부산", "울산", "경남", "경상남도", "창원", "김해", "양산", "거제", "통영",
    "진주", "밀양", "사천", "고성", "함안", "창녕", "거창", "합천", "남해", "하동"
)
DAANGN_WANTED_WORDS = (
    "행사","행사보조","행사스태프","스태프","staff","벡스코","bexco","전시","박람회",
    "팝업","팝업스토어","백화점","신세계","롯데백화점","아울렛","설치","철거","세팅","셋팅",
    "입점","짐 옮기기","짐옮기기","물자이동","매장이동","기기운반","물품정리","물품 정리",
    "진열","현장보조","현장 보조","안전요원","안전 요원","부스","무대","전광판","led","집기","하차","상하차","상차","하역","자재","자재정리","자재 정리","자재이동","자재 이동","현장청소","현장 청소","청소보조","정리보조","정리 보조","양중","공방","타일","운반","물건운반","물건 운반","물품이동","물품 이동","가구이동","가구 이동","장농","장롱","침대이동","침대 이동","책상이동","책상 이동","이삿짐","이사짐","짐정리","짐 정리","창고정리","창고 정리","매장정리","매장 정리"
)
DAANGN_UNWANTED_WORDS = (
    "카페","베이커리","커피","주방","설거지","홀서빙","서빙","음식점","식당","배달","배송",
    "영업","세일즈","정규직","정직원","월급","피부관리","뷰티","헤어","네일","학원","과외","돌봄","요양","간병"
)

GENERAL_WANTED_WORDS = (
    "행사","이벤트","스태프","staff","공연","공연보조","운영스태프","운영 staff",
    "벡스코","bexco","전시","박람회","팝업","팝업스토어","백화점","아울렛",
    "입점","설치","철거","세팅","셋팅","진열","매장진열","매장이동",
    "짐 옮기기","짐옮기기","물자이동","물품이동","운반","상하차","하차","하역",
    "현장보조","행사보조","안전요원","부스","무대","전광판","led","집기",
    "이케아","신세계","롯데백화점","롯데아울렛","프리미엄 아울렛"
,"매장 입점","입점 작업","이벤트 스텝","이벤트 스태프","공연 STAFF","공연스태프","운영 스태프","롯데몰")
GENERAL_UNWANTED_WORDS = (
    "카페","커피","베이커리","주방","홀서빙","서빙","음식점","식당",
    
    "의료기기","안내보안","보안요원","공항보안",
    "영업","세일즈","정규직","정직원","월급"
,"상품권","와인선물","와인 선물","명절 와인","POLO","폴로매장","플로매장","입고지원","판매지원","매장 홍보","스킨케어")

PRIORITY_WORDS = (
    "벡스코", "bexco", "행사", "행사보조", "행사스태프", "전시", "박람회",
    "팝업", "팝업스토어", "백화점", "신세계", "롯데백화점", "관광공사",
    "설치", "철거", "세팅", "입점", "매장이동", "박스이동", "짐 옮기기",
    "물자이동", "진열", "보조", "스태프", "포장", "물류", "정리", "매장"
,"이벤트","공연","공연보조","운영스태프","아울렛","이케아")
CLOSED_WORDS = ("마감되었습니다", "접수가 마감", "채용이 마감", "종료된 공고", "삭제된 공고", "채용완료")
OPEN_WORDS = ("상시모집", "모집중", "지원", "채용중", "전화", "문자", "온라인")

# 공개 목록 페이지. 한 소스가 실패해도 다른 소스는 계속 진행합니다.
SOURCE_PAGES = [
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=1"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=2"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=3"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=4"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=5"),
    ("알바천국", "https://www.alba.co.kr/job/object/Main?hidsortcnt=50&pagesize=50&page=1"),
    ("알바천국", "https://www.alba.co.kr/job/object/Main?hidsortcnt=50&pagesize=50&page=2"),
    ("알바천국", "https://www.alba.co.kr/job/object/Main?hidsortcnt=50&pagesize=50&page=3"),

    # 당근알바는 메인 페이지가 아니라 실제 지역 검색 결과 페이지를 확인한다.
    # 부산 주요 권역을 나눠 조회하면 한 페이지의 주변지역 반경 결과까지 함께 잡힌다.
    ("당근알바", "https://jobs.daangn.com/s?regionId=5917"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=594"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=5923"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=671"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=648"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=648&jobTask=LIGHT_WORK"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=648&jobTask=OTHER"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=648&jobTask=INSTALLATION_REPAIR"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=648&jobTask=LOGISTICS_PACKING"),

    # 해운대/센텀/벡스코 인접권 확대
    # 공개 당근 검색에서 확인된 지역 ID
    ("당근알바", "https://jobs.daangn.com/s?regionId=6028"),  # 해운대구 좌동
    ("당근알바", "https://jobs.daangn.com/s?regionId=6027"),  # 해운대구 재송동

    # 해운대권 단기/보조성 업무 결과 노출 확대
    ("당근알바", "https://jobs.daangn.com/s?regionId=6028&jobTask=LIGHT_WORK"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=6028&jobTask=OTHER"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=6027&jobTask=LIGHT_WORK"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=6027&jobTask=OTHER"),
    "https://www.albamon.com/jobs/short-term?areas=H000&page=6",
    "https://www.albamon.com/jobs/short-term?areas=H000&page=7",
    "https://www.albamon.com/jobs/short-term?areas=H000&page=8",

]


ROBOTS_CACHE = {}



def daangn_posted_at(text):
    """당근의 '몇 분 전/몇 시간 전/오늘 HH:MM/어제 HH:MM'을 로컬 datetime으로 변환."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", text)

    m = re.search(r"(\d+)\s*분\s*전", t)
    if m:
        return NOW - timedelta(minutes=int(m.group(1)))

    m = re.search(r"(\d+)\s*시간\s*전", t)
    if m:
        return NOW - timedelta(hours=int(m.group(1)))

    if re.search(r"(방금|몇\s*초\s*전|1\s*분\s*미만)", t):
        return NOW

    m = re.search(r"오늘\s*(\d{1,2}):(\d{2})", t)
    if m:
        return datetime.combine(TODAY, datetime.min.time()).replace(
            hour=int(m.group(1)), minute=int(m.group(2))
        )

    m = re.search(r"어제\s*(\d{1,2}):(\d{2})", t)
    if m:
        d = TODAY - timedelta(days=1)
        return datetime.combine(d, datetime.min.time()).replace(
            hour=int(m.group(1)), minute=int(m.group(2))
        )

    # yyyy.mm.dd HH:MM / yyyy-mm-dd HH:MM
    m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\s+(\d{1,2}):(\d{2})", t)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(4)), int(m.group(5)))
        except ValueError:
            return None
    return None

def daangn_detail_links(html, base_url="https://jobs.daangn.com"):
    """당근 목록 HTML에서 상세 공고 URL을 먼저 최대한 확보한다."""
    if not html:
        return []
    html2 = html.replace("\\u002F", "/").replace("\\/", "/")
    patterns = [
        r'href=["\']([^"\']*/job-posts/[^"\']+)["\']',
        r'https://jobs\.daangn\.com/job-posts/[A-Za-z0-9%_\-가-힣]+',
        r'["\'](/job-posts/[^"\']+)["\']',
    ]
    found = []
    for pat in patterns:
        found.extend(re.findall(pat, html2, flags=re.I))
    result, seen = [], set()
    for u in found:
        if isinstance(u, tuple):
            u = next((x for x in u if x), "")
        u = u.replace("&amp;", "&").strip()
        if u.startswith("/"):
            u = base_url + u
        elif u.startswith("job-posts/"):
            u = base_url + "/" + u
        if "/job-posts/" not in u:
            continue
        u = u.split("#")[0]
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def robots_allowed(url: str):
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    if origin in ROBOTS_CACHE:
        rp = ROBOTS_CACHE[origin]
    else:
        rp = RobotFileParser()
        rp.set_url(origin + "/robots.txt")
        try:
            rp.read()
            ROBOTS_CACHE[origin] = rp
        except Exception as e:
            # robots.txt를 확인할 수 없으면 안전하게 수집하지 않음
            return False, f"robots 확인 실패: {type(e).__name__}"
    try:
        ok = rp.can_fetch(UA, url)
        return ok, "robots 허용" if ok else "robots 제한"
    except Exception as e:
        return False, f"robots 판정 실패: {type(e).__name__}"


def fetch(url: str):
    allowed, reason = robots_allowed(url)
    if not allowed:
        return None, {"state": "blocked", "reason": reason, "http": None}
    try:
        r = SESSION.get(url, timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        return None, {"state": "error", "reason": type(e).__name__, "http": None}
    if r.status_code in (401, 403, 429):
        return None, {"state": "blocked", "reason": f"HTTP {r.status_code}", "http": r.status_code}
    if r.status_code >= 400:
        return None, {"state": "error", "reason": f"HTTP {r.status_code}", "http": r.status_code}
    low = r.text[:200000].lower()
    if "captcha" in low or "access denied" in low or "비정상적인 접근" in r.text[:200000]:
        return None, {"state": "blocked", "reason": "캡차/접근제한 화면", "http": r.status_code}
    return r, {"state": "ok", "reason": "공개 페이지 응답", "http": r.status_code}


def parse_hourly(text: str) -> int:
    """명시된 시급을 추출한다. 시급 표기가 없으면 0."""
    t = (text or "").replace(",", "")
    m = re.search(r"시급\s*[:：]?\s*([0-9]{4,6})\s*원?", t)
    return int(m.group(1)) if m else 0


def pay_type_from_text(text: str) -> str:
    t = text or ""
    if re.search(r"(?:일급|일당|하루)\s*[:：]?\s*[0-9]", t):
        return "일급"
    if re.search(r"시급\s*[:：]?\s*[0-9]", t):
        return "시급"
    if re.search(r"건당\s*[:：]?\s*[0-9]", t):
        return "건당"
    return "급여 확인"


def total_work_days_from_text(text: str):
    """당근의 '총 2일 / 9월16~23일'처럼 기간 폭과 실제 근무일수가 다른 경우 사용."""
    m = re.search(r"총\s*(\d{1,2})\s*일", text or "")
    if m:
        n = int(m.group(1))
        if 1 <= n <= 31:
            return n
    return None


def parse_money(text: str) -> int:
    t = text.replace(",", "")
    patterns = [
        r"일급\s*[:：]?\s*([0-9]{4,7})\s*원?",
        r"일당\s*[:：]?\s*([0-9]{4,7})\s*원?",
        r"하루\s*[:：]?\s*([0-9]{4,7})\s*원?",
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            return int(m.group(1))
    m = re.search(r"(?:일급|일당|하루)[^0-9]{0,8}([0-9]{1,3})\s*만(?:원)?", t)
    if m:
        return int(m.group(1)) * 10000
    hm = re.search(r"시급\s*[:：]?\s*([0-9]{4,6})\s*원?", t)
    tm = re.search(r"(\d{1,2}):(\d{2})\s*(?:~|-|–|—)\s*(\d{1,2}):(\d{2})", t)
    if hm and tm:
        wage = int(hm.group(1))
        start = int(tm.group(1)) + int(tm.group(2)) / 60
        end = int(tm.group(3)) + int(tm.group(4)) / 60
        if end <= start:
            end += 24
        hours = end - start
        if 0 < hours <= 16:
            return int(wage * hours)
    return 0


def safe_date(month: int, day: int):
    # 연말에 1월 공고가 보일 때는 다음 해로 처리
    year = TODAY.year
    if TODAY.month >= 11 and month <= 2:
        year += 1
    try:
        return datetime(year, month, day, tzinfo=KST).date()
    except ValueError:
        return None


def posted_date_from_text(text: str):
    m = re.search(r"(\d+)\s*분\s*전", text)
    if m:
        return (NOW - timedelta(minutes=int(m.group(1)))).date()
    m = re.search(r"(\d+)\s*시간\s*전", text)
    if m:
        return (NOW - timedelta(hours=int(m.group(1)))).date()
    m = re.search(r"(\d+)\s*일\s*전", text)
    if m:
        return (NOW - timedelta(days=int(m.group(1)))).date()
    # 알바천국 상세 상단처럼 라벨 없이 2026.09.14 13:24가 표시되는 경우
    head = text[:900]
    m = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})(?:\s+\d{1,2}:\d{2})?", head)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=KST).date()
        except ValueError:
            pass
    # '등록 09.14', '게시일 9/14'
    m = re.search(r"(?:등록일?|게시일?|작성일?)\s*[:：]?\s*(?:20\d{2}[./-])?(\d{1,2})[./-](\d{1,2})", text)
    if m:
        return safe_date(int(m.group(1)), int(m.group(2)))
    return None


def work_range(text: str):
    # 9/20~9/24, 9.20-9.24, 9월20일~24일
    rgx = r"(\d{1,2})\s*[./월]\s*(\d{1,2})(?:일)?\s*(?:~|-|–|—)\s*(?:(\d{1,2})\s*[./월]\s*)?(\d{1,2})(?:일)?"
    for m in re.finditer(rgx, text):
        sm, sd = int(m.group(1)), int(m.group(2))
        em = int(m.group(3)) if m.group(3) else sm
        ed = int(m.group(4))
        a, b = safe_date(sm, sd), safe_date(em, ed)
        if a and b and b >= a and (b - a).days <= 31:
            return a, b
    # 날짜 1개 + 하루/1일 근무 표현
    m = re.search(r"(?<!\d)(\d{1,2})\s*[./월]\s*(\d{1,2})(?:일)?", text)
    if m and re.search(r"(?:하루|1일\s*(?:근무|알바)|당일)", text):
        d = safe_date(int(m.group(1)), int(m.group(2)))
        if d:
            return d, d
    return None, None


def daangn_work_range(title: str, text: str):
    """당근 카드에서 다른 공고 날짜가 섞이지 않도록 날짜 우선순위를 제한한다."""
    # 1. 공고 제목에 명시된 날짜를 최우선 사용
    a, b = work_range(title or "")
    if a and b:
        return a, b

    # 2. '총 N일 / 9월 16~18일' 형태에서 '/' 뒤 날짜 부분 우선
    t = text or ""
    m = re.search(
        r"총\s*\d{1,2}\s*일\s*[/·|]\s*"
        r"(\d{1,2})\s*[./월]\s*(\d{1,2})(?:일)?\s*"
        r"(?:~|-|–|—)\s*(?:(\d{1,2})\s*[./월]\s*)?(\d{1,2})(?:일)?",
        t
    )
    if m:
        sm, sd = int(m.group(1)), int(m.group(2))
        em = int(m.group(3)) if m.group(3) else sm
        ed = int(m.group(4))
        a, b = safe_date(sm, sd), safe_date(em, ed)
        if a and b and b >= a and (b - a).days <= 31:
            return a, b

    # 3. 카드 텍스트 전체에서 일반 날짜 추출
    return work_range(t)


def daangn_card_text(a):
    """당근 공고 링크 하나에 대응하는 작은 카드 영역만 선택한다."""
    best = norm(a.get_text(" ", strip=True))
    node = a
    for _ in range(6):
        node = getattr(node, "parent", None)
        if node is None:
            break
        txt = norm(node.get_text(" ", strip=True))
        # 제목 + 지역 + 급여 + 날짜가 들어갈 만큼 충분하지만,
        # 이웃 공고가 섞일 정도로 큰 컨테이너는 피한다.
        if 35 <= len(txt) <= 850:
            has_pay = bool(re.search(r"(시급|일급|일당|건당|월급)", txt))
            has_date = bool(re.search(r"(총\s*\d+\s*일|\d{1,2}\s*[./월]\s*\d{1,2})", txt))
            if has_pay and has_date:
                best = txt
                break
    return best


def region_name(text: str):
    for w in REGION_WORDS:
        if w in text:
            if w == "경상남도":
                return "경남"
            return w
    return None


def is_closed(text: str) -> bool:
    if any(w in text for w in CLOSED_WORDS):
        return not any(w in text for w in OPEN_WORDS)
    return False


def candidate_blocks(soup: BeautifulSoup):
    """링크와 그 주변 카드 텍스트를 넓게 추출한다."""
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href or href.startswith(("javascript:", "#")):
            continue
        node = a
        chosen = None
        for _ in range(6):
            if node is None:
                break
            text = norm(node.get_text(" ", strip=True))
            if 60 <= len(text) <= 2200:
                chosen = text
            if len(text) > 700:
                break
            node = node.parent
        text = chosen or norm(a.get_text(" ", strip=True))
        if len(text) < 20:
            continue
        key = (href, text[:220])
        if key in seen:
            continue
        seen.add(key)
        yield a, text


def iter_jsonld_jobs(soup: BeautifulSoup, base_url: str):
    """사이트가 제공하는 schema.org JobPosting JSON-LD가 있으면 우선 사용."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        stack = obj if isinstance(obj, list) else [obj]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if x.get("@type") == "JobPosting":
                    title = norm(x.get("title", ""))
                    desc = BeautifulSoup(str(x.get("description", "")), "html.parser").get_text(" ", strip=True)
                    org = x.get("hiringOrganization") or {}
                    company = norm(org.get("name", "")) if isinstance(org, dict) else ""
                    date_posted = str(x.get("datePosted", ""))
                    valid_through = str(x.get("validThrough", ""))
                    url = x.get("url") or base_url
                    location = json.dumps(x.get("jobLocation", ""), ensure_ascii=False)
                    text = norm(" ".join([title, desc, company, date_posted, valid_through, location]))
                    yield {"title": title, "company": company, "text": text, "url": url, "datePosted": date_posted}
                for v in x.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(x, list):
                stack.extend(x)




def clean_company_name(value: str) -> str:
    v = norm(value)
    if not v:
        return ""
    v = re.sub(r"\s*(?:채용정보|채용공고)\s*$", "", v).strip(" -|·")
    bad = ("알바몬", "알바천국", "당근알바", "채용정보", "채용공고", "상세정보", "모집내용", "근무조건", "지원방법")
    if v in bad or len(v) < 2 or len(v) > 80:
        return ""
    if re.match(r"^(?:시급|일급|월급|주급|급여|근무|모집|지원|등록|지역|시간)", v):
        return ""
    return v

def company_from_soup(soup: BeautifulSoup, title: str = "") -> str:
    # 1) JobPosting 구조화 데이터의 hiringOrganization.name
    for x in iter_jsonld_jobs(soup, ""):
        c = clean_company_name(x.get("company", ""))
        if c:
            return c
    # 2) 자주 쓰이는 메타 태그
    for attrs in (
        {"property":"og:site_name"}, {"name":"author"},
        {"name":"company"}, {"name":"hiringOrganization"}
    ):
        tag=soup.find("meta", attrs=attrs)
        if tag:
            c=clean_company_name(tag.get("content", ""))
            if c and c not in ("알바몬","알바천국","당근"):
                return c
    # 3) 업체/기업/회사/공고등록자 라벨 옆 텍스트
    lines=[norm(x) for x in soup.get_text("\n", strip=True).splitlines() if norm(x)]
    labels=("기업명","업체명","회사명","근무회사","고용주","공고등록자","등록자명","상호명")
    for i,x in enumerate(lines):
        for label in labels:
            if x == label and i+1 < len(lines):
                c=clean_company_name(lines[i+1])
                if c and c != title: return c
            if x.startswith(label):
                c=clean_company_name(re.sub(r"^"+re.escape(label)+r"\s*[:：]?\s*", "", x))
                if c and c != title: return c
    return ""

def company_from_card(a, card_text: str, title: str = "") -> str:
    # 카드 내부에서 company/employer/store/business 계열 요소 우선
    node=a
    for _ in range(5):
        if node is None: break
        for tag in node.find_all(True):
            classes=" ".join(tag.get("class",[])).lower()
            ident=str(tag.get("id","")).lower()
            if any(k in classes+" "+ident for k in ("company","corp","employer","business","store","brand","name")):
                c=clean_company_name(tag.get_text(" ",strip=True))
                if c and c != title and c not in card_text[:len(c)]:
                    return c
        node=node.parent
    # 텍스트 라벨 fallback
    m=re.search(r"(?:기업명|업체명|회사명|공고등록자|상호명)\s*[:：]?\s*([^|·/]{2,50})", card_text)
    return clean_company_name(m.group(1)) if m else ""


def job_from_text(source: str, title: str, company: str, text: str, href: str, date_posted: str = ""):
    """부울경 공개 공고를 최대한 넓게 수집한다.

    제외:
    - 부산·울산·경남이 아닌 공고
    - 명확히 마감/삭제된 공고

    더 이상 제외하지 않음:
    - 등록일 오래됨/미확인
    - 오늘/과거 날짜 표기
    - 1주 초과
    - 시급 12,000원 미만
    - 근무일 미확인
    """
    company = clean_company_name(company)
    rg = region_name(text)
    if not rg or is_closed(text):
        return None, "region_or_closed"

    # 당근알바 지역은 region_name()이 판정한 실제 근무지역 기준으로 제한한다.
    # 부산은 그대로 허용하고, 경남으로 판정된 공고는 김해/양산만 허용한다.
    # 본문에 부산이라는 단어가 우연히 포함된 거제 등 타지역 공고가 통과하는 문제를 방지한다.
    if source == "당근알바":
        if rg == "부산":
            pass
        elif rg == "경남":
            if not re.search(r"(?:김해(?:시)?|양산(?:시)?)", text):
                return None, "daangn_outside_target_area"
        else:
            return None, "daangn_outside_target_area"

        # 원하는 행사·설치·철거·현장보조형 공고만 통과
        low_text = f"{title} {company} {text}".lower()
        if not any(w.lower() in low_text for w in DAANGN_WANTED_WORDS):
            return None, "daangn_not_preferred"

        # 카페·음식점·영업·장기직은 제외. 핵심 현장형 키워드가 명확하면 유지.
        strong = ("행사","벡스코","bexco","설치","철거","세팅","셋팅","부스","무대",
                  "전시","박람회","팝업","짐 옮기기","짐옮기기","상하차","하차","하역",
                  "자재이동","자재 이동","현장청소","현장 청소","양중","운반",
                  "물품이동","물품 이동","가구이동","가구 이동","장농","장롱",
                  "이삿짐","이사짐","짐정리","짐 정리","창고정리","창고 정리")
        if any(w.lower() in low_text for w in DAANGN_UNWANTED_WORDS) and not any(w in low_text for w in strong):
            return None, "daangn_unwanted_job"

    # 사용자 지정 제외 키워드: 제목/업체명/공고본문 어디에 있어도 제외
    # 제외업종/브랜드
    # "물류"라는 일반 업무 단어 자체는 제외하지 않는다.
    # 쿠팡·컬리 계열 물류/배송, 메리츠 보험, 편의점 공고만 제외한다.
    haystack = f"{title} {company} {text}".lower()
    brand_excludes = (
        "쿠팡", "coupang", "쿠팡로지스틱스", "쿠팡풀필먼트",
        "마켓컬리", "컬리", "kurly",
        "메리츠", "메리츠화재", "메리 보험", "메리보험",
        "편의점", "gs25", "세븐일레븐", "7-eleven", "이마트24", "미니스톱",
        "택배", "택배상하차", "택배 분류", "택배분류", "택배 배송", "택배배송"
    ,"포인트 지급")
    # CU는 영문 일반문자열 오탐이 많아 단어 경계로만 판정
    if any(w.lower() in haystack for w in brand_excludes) or re.search(r"(?<![a-z])cu(?![a-z])", haystack):
        return None, "excluded_keyword"

    post = posted_date_from_text(text)
    if not post and date_posted:
        try:
            post = datetime.fromisoformat(date_posted[:10]).date()
        except Exception:
            pass
    post_verified = bool(post)

    # 등록시간 필터
    # 당근알바: 현재 수집시각 기준 최근 12시간 이내 등록이 확인되는 공고만.
    # 상세/카드 텍스트의 '몇 분 전/몇 시간 전/오늘/어제 HH:MM'을 실제 시각으로 변환한다.
    # 알바몬/알바천국: 기존대로 등록일 확인 시 최근 3일 이내.
    if source == "당근알바":
        # 당근알바는 등록시간/근무기간으로 제외하지 않는다.
        # 현재 공개 검색 페이지에 노출되는 공고를 매 수집 때 반영한다.
        posted_at = daangn_posted_at(text)
        post_age_rank = 0 if posted_at else 1
    elif post and not (0 <= (TODAY - post).days <= 3):
        return None, "older_than_3_days"

    # 날짜를 찾으면 사용하고, 없으면 미확인으로 유지
    wa, wb = daangn_work_range(title, text) if source == "당근알바" else work_range(text)

    stated_days = total_work_days_from_text(text)
    if stated_days is not None:
        days = stated_days
    elif wa and wb:
        days = max(1, (wb - wa).days + 1)
    elif re.search(r"(하루\s*알바|하루\s*근무|당일\s*알바|당일\s*근무|1일\s*(?:알바|근무))", text or ""):
        days = 1
    else:
        days = 99

    # 당근은 근무기간을 필터 조건으로 사용하지 않는다.
    # 알바몬/알바천국만 명확한 8일 이상 공고를 제외한다.
    if source != "당근알바" and days != 99 and (days < 1 or days > 7):
        return None, "over_7_days"

    hourly = parse_hourly(text)
    pay = parse_money(text)
    ptype = pay_type_from_text(text)

    tm = re.search(r"(\d{1,2}:\d{2}\s*(?:~|-|–|—)\s*\d{1,2}:\d{2}(?:\s*\(익일\))?)", text)
    app = next((w for w in ("온라인지원", "간편문자지원", "문자지원", "전화연락", "전화지원", "홈페이지", "이메일지원") if w in text), "원본 공고 확인")
    task_words = [w for w in PRIORITY_WORDS if w in text]

    if days == 1:
        duration_label = "하루(1일)"
    elif 2 <= days <= 7:
        duration_label = f"{days}일"
    else:
        duration_label = "기간 미확인"

    title = norm(title) or text[:100]

    if wa and wb:
        work_date = wa.strftime("%m/%d") if wa == wb else f"{wa.strftime('%m/%d')}~{wb.strftime('%m/%d')}"
        work_start = wa.isoformat()
        work_end = wb.isoformat()
    else:
        work_date = "근무일 확인"
        work_start = ""
        work_end = ""

    # 시급 공고의 일급 환산값은 랭킹의 '일급'으로 사용하지 않도록 실제 일급만 별도 계산
    explicit_day_pay = 0
    raw = (text or "").replace(",", "")
    m = re.search(r"(?:일급|일당|하루)\s*[:：]?\s*([0-9]{4,7})\s*원?", raw)
    if m:
        explicit_day_pay = int(m.group(1))
    else:
        m = re.search(r"(?:일급|일당|하루)[^0-9]{0,8}([0-9]{1,3})\s*만(?:원)?", raw)
        if m:
            explicit_day_pay = int(m.group(1)) * 10000

    # 근무일 기준 평일/주말 분류
    day_group = "미확인"
    if wa and wb:
        d = wa
        has_weekday = has_weekend = False
        while d <= wb:
            if d.weekday() >= 5:
                has_weekend = True
            else:
                has_weekday = True
            d += timedelta(days=1)
        day_group = "평일+주말" if has_weekday and has_weekend else ("주말" if has_weekend else "평일")

    return {
        "source": source,
        "posted_at": post.isoformat() if post else "등록일 미확인",
        "posted_verified": post_verified,
        "work_date": work_date,
        "work_start": work_start,
        "work_end": work_end,
        "region": rg,
        "company": company,
        "title": title[:160],
        "task": ", ".join(task_words) if task_words else "아르바이트",
        "work_time": tm.group(1) if tm else "시간 확인",
        "day_pay": pay,
        "explicit_day_pay": explicit_day_pay,
        "hourly_pay": hourly,
        "pay_type": ptype,
        "pay_display": (
            f"일급 {explicit_day_pay:,}원" if explicit_day_pay
            else f"시급 {hourly:,}원" if hourly
            else f"{pay:,}원" if pay
            else "급여 확인"
        ),
        "apply": app,
        "url": href,
        "duration_days": days,
        "duration_label": duration_label,
        "day_group": day_group,
        "post_age_rank": (post_age_rank if source == "당근알바" else 0),
        "priority_hits": len(task_words),
    }, "accepted"

def alba_detail_links(soup: BeautifulSoup, base_url: str):
    """알바천국 목록에서 부산·경남·울산의 최근 공고 상세 링크만 추린다."""
    out, seen = [], set()
    for a, text in candidate_blocks(soup):
        href = urljoin(base_url, a.get("href", ""))
        if "alba.co.kr/job/" not in href.lower() or "adid=" not in href.lower():
            continue
        if not region_name(text):
            continue
        # 목록 텍스트에 '시간 전/분 전/오늘' 등이 있으면 최근 후보로 간주
        key = re.search(r"adid=(\d+)", href, re.I)
        key = key.group(1) if key else href
        if key in seen:
            continue
        seen.add(key)
        out.append(href)
    return out[:50]


def parse_alba_detail(url: str):
    r, fd = fetch(url)
    if not r:
        return None, fd
    soup = BeautifulSoup(r.text, "html.parser")
    text = norm(soup.get_text(" ", strip=True))

    # 제목/업체명: OG title이 '업체 채용정보 : 공고제목 - 알바천국' 형식인 경우 우선
    title, company = "", ""
    og = soup.find("meta", attrs={"property": "og:title"})
    ogt = norm(og.get("content", "")) if og else ""
    m = re.match(r"(.+?)\s+채용정보\s*:\s*(.+?)\s*-\s*알바천국", ogt)
    if m:
        company, title = norm(m.group(1)), norm(m.group(2))
    if not title:
        h = soup.find(["h1", "h2"])
        title = norm(h.get_text(" ", strip=True)) if h else ""
    if not company:
        # 상세 페이지 상단의 첫 줄이 업체명인 경우가 많음
        lines = [norm(x) for x in soup.get_text("\n", strip=True).splitlines() if norm(x)]
        for x in lines[:30]:
            if x == title or "채용정보" in x or x.startswith("2026.") or x in ("인쇄하기", "공유하기", "닫기"):
                continue
            if 1 < len(x) < 60 and not re.search(r"^(일급|시급|월급|기간|요일|시간|모집)", x):
                company = x
                break
    company = clean_company_name(company) or company_from_soup(soup, title)
    j, why = job_from_text("알바천국", title, company, text, r.url)
    return j, {"state":"ok","reason":why,"http":r.status_code}


def parse_alba_index(url: str):
    r, fetch_diag = fetch(url)
    diag = {"source":"알바천국","url":url,"state":fetch_diag["state"],"reason":fetch_diag["reason"],"http":fetch_diag.get("http"),"candidates":0,"accepted":0,"rejected":{}}
    if not r:
        return [], diag
    soup = BeautifulSoup(r.text, "html.parser")
    links = alba_detail_links(soup, r.url)
    diag["candidates"] = len(links)
    out=[]
    for href in links:
        try:
            j, info = parse_alba_detail(href)
            if j:
                out.append(j); diag["accepted"] += 1
            else:
                why = info.get("reason", "detail_rejected") if isinstance(info,dict) else "detail_rejected"
                diag["rejected"][why] = diag["rejected"].get(why,0)+1
        except Exception as e:
            k=f"detail_{type(e).__name__}"; diag["rejected"][k]=diag["rejected"].get(k,0)+1
        time.sleep(0.25)
    if not links:
        diag["reason"]="목록 응답은 정상이나 부울경 상세공고 링크를 찾지 못함"
    elif out:
        diag["reason"]=f"알바천국 상세공고 {len(out)}건 통과"
    else:
        diag["reason"]="상세공고 후보는 찾았지만 현재 필터 조건 통과 0건"
    return out, diag



def daangn_nearby_region_urls(url: str, limit: int = 30):
    """공개 당근 검색 페이지에 노출된 주변 지역 regionId 링크를 자동 발견."""
    r, _ = fetch(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(r.url, a.get("href", ""))
        m = re.search(r"jobs\.daangn\.com/s\?[^#]*regionId=(\d+)", href, re.I)
        if not m:
            continue
        rid = m.group(1)
        if rid in seen:
            continue
        seen.add(rid)
        out.append(f"https://jobs.daangn.com/s?regionId={rid}")
        if len(out) >= limit:
            break
    return out

DAANGN_DETAIL_FETCHED = set()
DAANGN_DETAIL_CACHE = {}
DAANGN_DETAIL_MAX = 80

def parse_daangn_index(url: str):
    """당근 공개 검색결과: 카드 + 개별 상세공고 본문까지 확인."""
    r, fetch_diag = fetch(url)
    diag = {
        "source": "당근알바", "url": url, "state": fetch_diag["state"],
        "reason": fetch_diag["reason"], "http": fetch_diag.get("http"),
        "candidates": 0, "accepted": 0, "rejected": {}, "detail_checked": 0,
    }
    if not r:
        return [], diag

    soup = BeautifulSoup(r.text, "html.parser")
    out, seen = [], set()

    # 검색목록에 노출된 실제 상세 공고 링크를 모두 후보로 확보한다.
    for a in soup.find_all("a", href=True):
        href = urljoin(r.url, a.get("href", ""))
        if "jobs.daangn.com/job-posts/" not in href.lower():
            continue
        href = href.split("#")[0]
        if href in seen:
            continue
        seen.add(href)
        if href in DAANGN_DETAIL_FETCHED:
            continue
        if len(DAANGN_DETAIL_FETCHED) >= DAANGN_DETAIL_MAX:
            break
        DAANGN_DETAIL_FETCHED.add(href)
        diag["candidates"] += 1

        card_text = daangn_card_text(a)
        card_title = norm(a.get_text(" ", strip=True))
        company = company_from_card(a, card_text, card_title)

        # 핵심 변경: 카드가 짧거나 지역/급여가 빠져도 버리지 않고 상세페이지를 연다.
        detail_text = ""
        detail_title = card_title
        try:
            dr, _ = fetch(href)
            if dr:
                ds = BeautifulSoup(dr.text, "html.parser")
                detail_text = norm(ds.get_text(" ", strip=True))
                if ds.find("h1"):
                    detail_title = norm(ds.find("h1").get_text(" ", strip=True)) or detail_title
                elif ds.title:
                    detail_title = norm(ds.title.get_text(" ", strip=True)) or detail_title
                diag["detail_checked"] += 1
        except Exception:
            pass

        merged = norm(" ".join(x for x in (card_text, detail_text) if x))
        if not merged:
            continue
        title = detail_title or card_title
        j, why = job_from_text("당근알바", title, company, merged, href)
        if j:
            out.append(j)
            diag["accepted"] += 1
        else:
            diag["rejected"][why] = diag["rejected"].get(why, 0) + 1
        time.sleep(0.03)

    if diag["candidates"] == 0:
        diag["reason"] = "당근 공개 검색 페이지 응답 정상 · 상세 공고 링크 미확인"
    elif diag["accepted"] == 0:
        diag["reason"] = f"상세 공고 {diag['detail_checked']}건 확인 · 현재 조건 통과 0건"
    else:
        diag["reason"] = f"상세 공고 {diag['detail_checked']}건 확인 · {diag['accepted']}건 통과"
    return out, diag


def parse_page(source: str, url: str):
    r, fetch_diag = fetch(url)
    diag = {
        "source": source,
        "url": url,
        "state": fetch_diag["state"],
        "reason": fetch_diag["reason"],
        "http": fetch_diag.get("http"),
        "candidates": 0,
        "accepted": 0,
        "rejected": {},
    }
    if not r:
        return [], diag

    soup = BeautifulSoup(r.text, "html.parser")
    out = []

    # 1) 구조화 데이터 우선
    jsonld = list(iter_jsonld_jobs(soup, r.url))
    for x in jsonld:
        diag["candidates"] += 1
        j, why = job_from_text(source, x["title"], x["company"], x["text"], x["url"], x["datePosted"])
        if j:
            out.append(j)
            diag["accepted"] += 1
        else:
            diag["rejected"][why] = diag["rejected"].get(why, 0) + 1

    # 2) 일반 카드/링크 텍스트
    for a, text in candidate_blocks(soup):
        if not region_name(text):
            continue
        diag["candidates"] += 1
        href = urljoin(r.url, a.get("href", ""))
        title = norm(a.get_text(" ", strip=True))
        company = company_from_card(a, text, title)
        j, why = job_from_text(source, title, company, text, href)
        if j:
            out.append(j)
            diag["accepted"] += 1
        else:
            diag["rejected"][why] = diag["rejected"].get(why, 0) + 1

    if diag["state"] == "ok" and diag["candidates"] == 0:
        diag["reason"] = "페이지 응답은 정상이나 공고 카드/구조화데이터를 찾지 못함"
    elif diag["state"] == "ok" and diag["accepted"] == 0:
        diag["reason"] = "공고 후보는 찾았지만 현재 필터 조건 통과 0건"
    else:
        diag["reason"] = f"공개 페이지 정상 · {diag['accepted']}건 통과"
    return out, diag


def dedupe_key(j):
    core = re.sub(r"[^가-힣A-Za-z0-9]", "", j["title"])[:36]
    return hashlib.sha1(f"{core}|{j.get('work_start','')}|{j.get('explicit_day_pay',0)}|{j.get('hourly_pay',0)}".encode()).hexdigest()


def summarize_sources(diags):
    summary = {}
    for d in diags:
        s = summary.setdefault(d["source"], {"pages": 0, "ok_pages": 0, "blocked_pages": 0, "error_pages": 0, "candidates": 0, "accepted": 0, "messages": []})
        s["pages"] += 1
        if d["state"] == "ok":
            s["ok_pages"] += 1
        elif d["state"] == "blocked":
            s["blocked_pages"] += 1
        else:
            s["error_pages"] += 1
        s["candidates"] += d.get("candidates", 0)
        s["accepted"] += d.get("accepted", 0)
        msg = d.get("reason", "")
        if msg and msg not in s["messages"]:
            s["messages"].append(msg)
    return summary


def main():
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    jobs, diags = [], []

    # 기본 페이지 + 당근 공개 페이지에서 발견되는 주변 지역을 자동 확장
    pages = list(SOURCE_PAGES)
    seed_daangn = [u for s, u in SOURCE_PAGES if s == "당근알바" and "jobTask=" not in u]
    known_urls = {u for _, u in pages}
    discovered = []
    for seed in seed_daangn:
        try:
            for u in daangn_nearby_region_urls(seed, limit=30):
                if u not in known_urls:
                    known_urls.add(u)
                    discovered.append(("당근알바", u))
                    if len(discovered) >= 80:
                        break
        except Exception as e:
            print("daangn region discovery error:", seed, repr(e))
        if len(discovered) >= 80:
            break
        time.sleep(0.25)
    pages.extend(discovered)
    print("daangn nearby region pages added (target 부산·김해·양산):", len(discovered))

    for source, url in pages:
        try:
            if source == "알바천국":
                found, diag = parse_alba_index(url)
            elif source == "당근알바":
                found, diag = parse_daangn_index(url)
            else:
                found, diag = parse_page(source, url)
            jobs.extend(found)
            diags.append(diag)
            print(f"[{source}] {diag['state']} candidates={diag['candidates']} accepted={diag['accepted']} {diag['reason']}")
        except Exception as e:
            diags.append({"source": source, "url": url, "state": "error", "reason": f"파서 오류: {type(e).__name__}", "http": None, "candidates": 0, "accepted": 0, "rejected": {}})
            print("source error:", source, url, repr(e))
        time.sleep(0.35)

    deduped = {}
    for j in jobs:
        k = dedupe_key(j)
        old = deduped.get(k)
        if old is None or (j.get("posted_verified") and not old.get("posted_verified")):
            deduped[k] = j
    jobs = list(deduped.values())
    # 순위 규칙:
    # 1) 하루알바 우선
    # 2) 실제 일급 높은 순
    # 3) 시급 높은 순
    # 4) 근무일이 확인되는 경우 빠른 날짜
    def rank_key(j):
        day_pay = -int(j.get("explicit_day_pay") or 0)
        hourly = -int(j.get("hourly_pay") or 0)
        priority = -int(j.get("priority_hits") or 0)
        date_key = j.get("work_start") or "9999-12-31"
        if j.get("source") == "당근알바":
            # 당근: 현재 공개된 공고 중 원하는 행사형 → 일급 → 시급 순.
            return (0, priority, day_pay, hourly, date_key, j.get("title",""))
        d = int(j.get("duration_days") or 99)
        duration_rank = 0 if d == 1 else (1 if 2 <= d <= 7 else 2)
        # 알바몬/알바천국: 하루/단기 우선 + 원하는 유형 가중
        return (1, duration_rank, priority, day_pay, hourly, date_key, j.get("title",""))

    jobs.sort(key=rank_key)

    # 표시 순서: 일급 공고 → 시급 공고 → 급여 확인 공고
    # 같은 급여형태 안에서는 금액이 높은 순으로 정렬
    def display_rank(j):
        if int(j.get("explicit_day_pay") or 0) > 0:
            pay_group = 0
            amount = -int(j.get("explicit_day_pay") or 0)
        elif int(j.get("hourly_pay") or 0) > 0:
            pay_group = 1
            amount = -int(j.get("hourly_pay") or 0)
        else:
            pay_group = 2
            amount = 0
        priority = -int(j.get("priority_hits") or 0)
        date_key = j.get("work_start") or "9999-12-31"
        return (pay_group, amount, priority, date_key, j.get("title",""))

    # 일반창: 알바몬 + 알바천국 TOP25
    general_pool = [j for j in jobs if j.get("source") in ("알바몬", "알바천국")]
    general_jobs = sorted(general_pool, key=display_rank)[:25]

    # 당근알바 별도창 TOP25
    daangn_pool = [j for j in jobs if j.get("source") == "당근알바"]
    daangn_jobs = sorted(daangn_pool, key=display_rank)[:25]

    display_jobs = general_jobs + daangn_jobs

    source_summary = summarize_sources(diags)
    payload = {
        "updated_at_kst": NOW.strftime("%Y-%m-%d %H:%M"),
        "collector_status": "ok" if display_jobs else "수집 실행 완료 · 공개 공고 0건",
        "criteria": "알바몬/알바천국 기존 최근3일 단기우선 유지; 당근은 현재 공개 페이지 실시간 수집(등록시간/근무기간 필터 없음); 평일/주말 구분; 행사형 우선; 쿠팡/컬리/메리츠보험/편의점/택배 제외",
        "general_jobs": general_jobs,
        "daangn_jobs": daangn_jobs,
        "jobs": display_jobs,
        "source_summary": source_summary,
        "diagnostics": diags,
    }

    # 전부 차단/오류인 경우만 기존 공고를 보존. '조건 불충족 0건'과 '수집 실패'를 구분한다.
    all_failed = bool(diags) and all(d["state"] != "ok" for d in diags)
    if not display_jobs and all_failed and prev.get("jobs"):
        payload["jobs"] = prev.get("jobs", [])
        payload["general_jobs"] = prev.get("general_jobs", [])
        payload["daangn_jobs"] = prev.get("daangn_jobs", [])
        payload["collector_status"] = "모든 소스 접근 실패 · 이전 공고 임시 유지"
        payload["previous_data_preserved"] = True

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", len(payload.get("general_jobs", [])), "general +", len(payload.get("daangn_jobs", [])), "daangn jobs")



if __name__ == "__main__":
    main()
