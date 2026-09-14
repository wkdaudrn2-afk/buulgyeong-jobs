#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
부울경 단기알바 공개 페이지 수집기 (best effort)
- 접근제한/로그인/캡차/401/403/429 우회 금지
- robots.txt 허용 여부 확인
- 최근 3일, 내일 이후, 1~7일, 모집중/상시모집 중심
- 하루(1일) 우선, 그 다음 일급 높은 순
사이트 구조 변경 시 해당 소스는 자동으로 건너뜁니다.
"""
from __future__ import annotations
import json, re, hashlib, time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
TODAY = NOW.date()
TOMORROW = TODAY + timedelta(days=1)
OUT = Path(__file__).with_name("jobs.json")

UA = "Mozilla/5.0 (compatible; BuUlGyeongJobChecker/1.0; public-page-only)"
HEADERS = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

REGION_WORDS = ("부산","울산","경남","창원","김해","양산","거제","통영","진주","밀양","사천")
PRIORITY_WORDS = ("행사","전시","설치","철거","물류","진열","보조","스태프","포장","피킹","상하차")
CLOSED_WORDS = ("마감","종료","삭제","채용완료","접수마감")
OPEN_WORDS = ("상시모집","모집중","온라인지원","간편문자지원","전화연락","홈페이지")

# 공개 목록 페이지. 사이트가 robots 정책 또는 구조를 바꾸면 자동으로 스킵됩니다.
SOURCE_PAGES = [
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=1"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=2"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?areas=H000&page=3"),
    ("알바몬", "https://www.albamon.com/jobs/short-term?page=1"),
    ("알바천국", "https://www.alba.co.kr/job/object/main"),
    ("당근알바", "https://www.daangn.com/kr/jobs/"),
]

def robots_allowed(url: str) -> bool:
    p = urlparse(url)
    robots = f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        rp = RobotFileParser()
        rp.set_url(robots)
        rp.read()
        return rp.can_fetch(UA, url)
    except Exception:
        return False

def get(url: str):
    if not robots_allowed(url):
        print("robots skip:", url)
        return None
    try:
        r = SESSION.get(url, timeout=18, allow_redirects=True)
        if r.status_code in (401,403,429):
            print("access skip:", r.status_code, url)
            return None
        if r.status_code >= 400:
            return None
        low = r.text.lower()
        if "captcha" in low or "access denied" in low or "로그인 후" in r.text[:5000]:
            print("challenge skip:", url)
            return None
        return r
    except requests.RequestException:
        return None

def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def parse_money(text):
    text = text.replace(",","")
    # 일급 우선
    m = re.search(r"일급\s*([0-9]{4,7})\s*원?", text)
    if m: return int(m.group(1))
    m = re.search(r"일\s*(?:최대)?\s*([0-9]{1,3})\s*만", text)
    if m: return int(m.group(1))*10000
    # 시급 x 명시 시간 범위
    hm = re.search(r"시급\s*([0-9]{4,6})\s*원?", text)
    tm = re.search(r"(\d{1,2}):(\d{2})\s*[~\-]\s*(\d{1,2}):(\d{2})", text)
    if hm and tm:
        wage=int(hm.group(1))
        s=int(tm.group(1))+int(tm.group(2))/60
        e=int(tm.group(3))+int(tm.group(4))/60
        if e <= s: e += 24
        hrs=max(0,e-s)
        if 0 < hrs <= 16: return int(wage*hrs)
    return 0

def parse_mmdd(s):
    m=re.search(r"(?<!\d)(\d{1,2})[./월]\s*(\d{1,2})(?:일)?", s)
    if not m: return None
    try: return datetime(TODAY.year,int(m.group(1)),int(m.group(2)),tzinfo=KST).date()
    except: return None

def posted_date_from_text(text):
    # '23시간전', '2일전', '9/12' 지원
    m=re.search(r"(\d+)\s*분전", text)
    if m: return TODAY
    m=re.search(r"(\d+)\s*시간전", text)
    if m:
        return (NOW-timedelta(hours=int(m.group(1)))).date()
    m=re.search(r"(\d+)\s*일전", text)
    if m:
        return (NOW-timedelta(days=int(m.group(1)))).date()
    # 등록일 근처 날짜
    m=re.search(r"(?:등록일|게시일)?\s*(\d{1,2})[./](\d{1,2})", text)
    if m:
        try:return datetime(TODAY.year,int(m.group(1)),int(m.group(2)),tzinfo=KST).date()
        except:return None
    return None

def work_range(text):
    # 9/20~9/24, 9월20일~24일, 하루(1일)
    matches=list(re.finditer(r"(\d{1,2})[./월]\s*(\d{1,2})(?:일)?\s*[~\-]\s*(?:(\d{1,2})[./월]\s*)?(\d{1,2})(?:일)?", text))
    for m in matches:
        sm,sd=int(m.group(1)),int(m.group(2))
        em=int(m.group(3)) if m.group(3) else sm
        ed=int(m.group(4))
        try:
            a=datetime(TODAY.year,sm,sd,tzinfo=KST).date()
            b=datetime(TODAY.year,em,ed,tzinfo=KST).date()
            if b>=a and (b-a).days <= 31:
                return a,b
        except: pass
    d=parse_mmdd(text)
    if d and ("하루" in text or "1일" in text):
        return d,d
    return None,None

def region_ok(text):
    return any(w in text for w in REGION_WORDS)

def duration_label(a,b,text):
    if "하루" in text or (a and b and a==b): return "하루(1일)"
    if a and b: return f"{(b-a).days+1}일"
    return "단기"

def candidate_blocks(soup):
    # 링크 주변 텍스트를 후보 블록으로 만들고 중복 제거
    seen=set()
    for a in soup.find_all("a", href=True):
        href=a.get("href","")
        label=norm(a.get_text(" ",strip=True))
        if not label or len(label)<4: continue
        parent=a
        for _ in range(4):
            if parent.parent is None: break
            parent=parent.parent
            t=norm(parent.get_text(" ",strip=True))
            if 80 <= len(t) <= 1400: break
        text=norm(parent.get_text(" ",strip=True))
        key=(href,text[:180])
        if key in seen: continue
        seen.add(key)
        yield a, text

def parse_page(source,url):
    r=get(url)
    if not r: return []
    soup=BeautifulSoup(r.text,"html.parser")
    out=[]
    for a,text in candidate_blocks(soup):
        if not region_ok(text): continue
        if any(x in text for x in CLOSED_WORDS) and not any(x in text for x in OPEN_WORDS): continue
        post=posted_date_from_text(text)
        if not post or (TODAY-post).days < 0 or (TODAY-post).days > 3: continue
        wa,wb=work_range(text)
        # 날짜가 확인되지 않으면 엄격 조건상 제외
        if not wa or not wb: continue
        if wa < TOMORROW: continue
        days=(wb-wa).days+1
        if not (1 <= days <= 7): continue
        href=urljoin(r.url,a.get("href",""))
        title=norm(a.get_text(" ",strip=True))
        if len(title)<6:
            # 블록 첫 부분을 임시 제목으로
            title=text[:90]
        pay=parse_money(text)
        task=", ".join([w for w in PRIORITY_WORDS if w in text]) or "단기 아르바이트"
        # 지역 표시
        rg=next((w for w in REGION_WORDS if w in text),"부울경")
        tm=re.search(r"(\d{1,2}:\d{2}\s*[~\-]\s*\d{1,2}:\d{2}(?:\s*\(익일\))?)",text)
        app=next((w for w in ("온라인지원","간편문자지원","전화연락","홈페이지","이메일지원") if w in text),"원본 공고 확인")
        out.append({
            "source":source,"posted_at":post.isoformat(),
            "work_date": wa.strftime("%m/%d") if wa==wb else f"{wa.strftime('%m/%d')}~{wb.strftime('%m/%d')}",
            "work_start":wa.isoformat(),"work_end":wb.isoformat(),
            "region":rg,"company":"","title":title[:140],"task":task,
            "work_time":tm.group(1) if tm else "시간 확인",
            "day_pay":pay,"apply":app,"url":href,
            "duration_days":days,"duration_label":duration_label(wa,wb,text),
            "priority_hits":sum(1 for w in PRIORITY_WORDS if w in text)
        })
    return out

def key(j):
    # 소스 간 중복 완화: 제목 핵심 + 근무일 + 급여
    core=re.sub(r"[^가-힣A-Za-z0-9]","",j["title"])[:32]
    return hashlib.sha1(f'{core}|{j["work_start"]}|{j["day_pay"]}'.encode()).hexdigest()

def main():
    prev={}
    if OUT.exists():
        try: prev=json.loads(OUT.read_text(encoding="utf-8"))
        except: prev={}
    jobs=[]
    for src,url in SOURCE_PAGES:
        try:
            jobs += parse_page(src,url)
        except Exception as e:
            print("source error:",src,url,type(e).__name__)
        time.sleep(1.2)
    ded={}
    for j in jobs:
        k=key(j)
        if k not in ded or (j["source"]=="알바몬" and ded[k]["source"]!="알바몬"):
            ded[k]=j
    jobs=list(ded.values())
    jobs.sort(key=lambda j:(0 if j["duration_days"]==1 else 1, -j["day_pay"], -j["priority_hits"], j["work_start"]))
    jobs=jobs[:10]

    # 모든 소스가 막힌 경우 기존 데이터는 유지하되 상태 표시
    if not jobs and prev.get("jobs"):
        payload=prev
        payload["last_attempt_at_kst"]=NOW.strftime("%Y-%m-%d %H:%M")
        payload["collector_status"]="이번 수집에서 검증 가능한 신규 데이터가 없어 이전 결과 유지"
    else:
        payload={
            "updated_at_kst":NOW.strftime("%Y-%m-%d %H:%M"),
            "collector_status":"ok",
            "criteria":"최근3일 등록·내일 이후·1~7일·하루우선·일급순",
            "jobs":jobs
        }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print("saved",len(payload.get("jobs",[])),"jobs")

if __name__=="__main__":
    main()
