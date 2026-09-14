#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""부울경 단기알바 수집기 v2

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

UA = "BuUlGyeongJobChecker/2.0 (+public-pages-only)"
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
    "행사", "전시", "설치", "철거", "물류", "진열", "보조", "스태프", "포장", "피킹",
    "상하차", "세팅", "정리", "매장", "창고"
)
CLOSED_WORDS = ("채용마감", "접수마감", "모집마감", "마감되었습니다", "종료", "삭제", "채용완료")
OPEN_WORDS = ("상시모집", "모집중", "지원", "채용중", "전화", "문자", "온라인")

# 공개 목록 페이지. 한 소스가 실패해도 다른 소스는 계속 진행합니다.
SOURCE_PAGES = [
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=1"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=2"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=3"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=4"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=5"),
    ("알바천국", "https://www.alba.co.kr/job/object/main"),
    ("당근알바", "https://www.daangn.com/kr/jobs/"),
    ("당근알바", "https://jobs.daangn.com/"),
]

ROBOTS_CACHE = {}

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
    # '등록 09.14', '게시일 9/14', '등록일 : 2026-09-14'
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
    rg = region_name(text)
    if not rg or is_closed(text):
        return None, "region_or_closed"

    post = posted_date_from_text(text)
    if not post and date_posted:
        try:
            post = datetime.fromisoformat(date_posted[:10]).date()
        except Exception:
            pass
    post_verified = bool(post and 0 <= (TODAY - post).days <= 3)
    if post and not post_verified:
        return None, "old_post"

    wa, wb = work_range(text)
    if not wa or not wb:
        return None, "no_work_date"
    if wa < TOMORROW:
        return None, "past_or_today"
    days = (wb - wa).days + 1
    if not 1 <= days <= 7:
        return None, "too_long"

    pay = parse_money(text)
    tm = re.search(r"(\d{1,2}:\d{2}\s*(?:~|-|–|—)\s*\d{1,2}:\d{2}(?:\s*\(익일\))?)", text)
    app = next((w for w in ("온라인지원", "간편문자지원", "문자지원", "전화연락", "전화지원", "홈페이지", "이메일지원") if w in text), "원본 공고 확인")
    task_words = [w for w in PRIORITY_WORDS if w in text]
    duration_label = "하루(1일)" if days == 1 else f"{days}일"

    title = norm(title) or text[:100]
    return {
        "source": source,
        "posted_at": post.isoformat() if post else "등록일 미확인",
        "posted_verified": post_verified,
        "work_date": wa.strftime("%m/%d") if wa == wb else f"{wa.strftime('%m/%d')}~{wb.strftime('%m/%d')}",
        "work_start": wa.isoformat(),
        "work_end": wb.isoformat(),
        "region": rg,
        "company": company,
        "title": title[:160],
        "task": ", ".join(task_words) if task_words else "단기 아르바이트",
        "work_time": tm.group(1) if tm else "시간 확인",
        "day_pay": pay,
        "apply": app,
        "url": href,
        "duration_days": days,
        "duration_label": duration_label,
        "priority_hits": len(task_words),
    }, "accepted"


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
    return hashlib.sha1(f"{core}|{j['work_start']}|{j['day_pay']}".encode()).hexdigest()


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
    jobs.sort(key=lambda j: (
        0 if j.get("posted_verified") else 1,
        0 if j["duration_days"] == 1 else 1,
        -j["day_pay"],
        -j["priority_hits"],
        j["work_start"],
    ))
    jobs = jobs[:10]

    source_summary = summarize_sources(diags)
    payload = {
        "updated_at_kst": NOW.strftime("%Y-%m-%d %H:%M"),
        "collector_status": "ok" if jobs else "수집 실행 완료 · 조건 통과 공고 0건",
        "criteria": "최근3일 등록 우선·등록일 미확인 보충·내일 이후·1~7일·하루우선·일급순",
        "jobs": jobs,
        "source_summary": source_summary,
        "diagnostics": diags,
    }

    # 전부 차단/오류인 경우만 기존 공고를 보존. '조건 불충족 0건'과 '수집 실패'를 구분한다.
    all_failed = bool(diags) and all(d["state"] != "ok" for d in diags)
    if not jobs and all_failed and prev.get("jobs"):
        payload["jobs"] = prev["jobs"]
        payload["collector_status"] = "모든 소스 접근 실패 · 이전 공고 임시 유지"
        payload["previous_data_preserved"] = True

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", len(payload.get("jobs", [])), "jobs")


if __name__ == "__main__":
    main()
