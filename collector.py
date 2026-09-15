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
PRIORITY_WORDS = (
    "벡스코", "bexco", "행사", "행사보조", "행사스태프", "전시", "박람회",
    "팝업", "팝업스토어", "백화점", "신세계", "롯데백화점", "관광공사",
    "설치", "철거", "세팅", "입점", "매장이동", "박스이동", "짐 옮기기",
    "물자이동", "진열", "보조", "스태프", "포장", "물류", "정리", "매장"
)
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

    # 해운대/센텀/벡스코 인접권 확대
    # 공개 당근 검색에서 확인된 지역 ID
    ("당근알바", "https://jobs.daangn.com/s?regionId=6028"),  # 해운대구 좌동
    ("당근알바", "https://jobs.daangn.com/s?regionId=6027"),  # 해운대구 재송동

    # 해운대권 단기/보조성 업무 결과 노출 확대
    ("당근알바", "https://jobs.daangn.com/s?regionId=6028&jobTask=LIGHT_WORK"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=6028&jobTask=OTHER"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=6027&jobTask=LIGHT_WORK"),
    ("당근알바", "https://jobs.daangn.com/s?regionId=6027&jobTask=OTHER"),
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
    rg = region_name(text)
    if not rg or is_closed(text):
        return None, "region_or_closed"

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
    )
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


def parse_daangn_index(url: str):
    """당근알바 공개 검색결과 전용 파서."""
    r, fetch_diag = fetch(url)
    diag = {
        "source": "당근알바",
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
    out, seen = [], set()

    # 실제 공고 링크만 처리한다. 검색/내비게이션 링크는 제외.
    for a in soup.find_all("a", href=True):
        href = urljoin(r.url, a.get("href", ""))
        low = href.lower()
        if "jobs.daangn.com/job-posts/" not in low:
            continue
        if href in seen:
            continue
        seen.add(href)

        text2 = daangn_card_text(a)
        if len(text2) < 25 or not region_name(text2):
            continue
        if not re.search(r"(시급|일급|일당|건당|월급)", text2):
            continue
        diag["candidates"] += 1
        title = norm(a.get_text(" ", strip=True))
        if len(title) < 5:
            title = re.split(r"\s+(?:시급|일급|일당|건당|월급)\s*", text2, maxsplit=1)[0][:160]

        j, why = job_from_text("당근알바", title, "", text2, href)
        if j:
            out.append(j)
            diag["accepted"] += 1
        else:
            diag["rejected"][why] = diag["rejected"].get(why, 0) + 1

    if diag["candidates"] == 0:
        diag["reason"] = "당근 공개 검색 페이지 응답 정상 · 실제 공고 카드 미확인"
    elif diag["accepted"] == 0:
        diag["reason"] = "당근 공고 후보는 찾았지만 현재 조건 통과 0건"
    else:
        diag["reason"] = f"당근 공개 검색결과 정상 · {diag['accepted']}건 통과"
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
        j, why = job_from_text(source, title, "", text, href)
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
    for source, url in SOURCE_PAGES:
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
        time.sleep(0.8)

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

    # 일반창: 알바몬 + 알바천국 TOP20
    general_jobs = [j for j in jobs if j.get("source") in ("알바몬", "알바천국")][:20]

    # 당근알바 별도창 TOP20
    daangn_jobs = [j for j in jobs if j.get("source") == "당근알바"][:20]

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
