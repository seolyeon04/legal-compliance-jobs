"""법무·컴플라이언스·특허·감사 채용공고 수집기.

사람인, 잡코리아, 인크루트의 공개 검색 목록에서 공고 요약 정보(제목, 회사, 지역, 경력, 학력,
고용형태, 등록일, 마감일, 원문 링크)만 가져온다. 상세 본문은 가져오지 않고 원문으로 연결한다.
요청 사이에 간격을 두고, 각 사이트 robots.txt가 허용하는 검색 목록 경로만 사용한다.
"""
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

from bs4 import BeautifulSoup

UA = os.environ.get("COLLECT_UA", "Mozilla/5.0 (compatible; Claude-User/1.0; +https://support.anthropic.com/)")
DELAY = 1.5
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST)
TODAY = NOW.date()
OUT = pathlib.Path(os.environ.get("JOBS_DATA_DIR") or pathlib.Path(__file__).resolve().parent.parent / "app" / "data")
RAW = pathlib.Path(os.environ.get("JOBS_CACHE_DIR") or pathlib.Path(__file__).resolve().parent.parent / "raw")


def get(url, encoding="utf-8"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read()
            time.sleep(DELAY)
            return body.decode(encoding, errors="replace")
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                print("  skip", e.code, url[:90], file=sys.stderr)
                time.sleep(DELAY)
                return ""
            print("  retry", attempt + 1, url[:90], e, file=sys.stderr)
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            print("  retry", attempt + 1, url[:90], e, file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return ""


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


# ---------------------------------------------------------------- 분류
# (그룹, 세부, 키워드들). 위에서부터 먼저 맞는 것을 쓴다.
RULES = [
    ("특허", "변리사", ["변리사"]),
    ("특허", "특허명세사", ["명세사", "명세서"]),
    ("특허", "상표·디자인", ["상표", "디자인권"]),
    ("특허", "특허·IP", ["특허", "지식재산", "지재권", "ip팀", "ip 담당", "(ip)", "ip(", "intellectual property", "patent", "ip전략", "ip 전략", "라이선싱"]),
    ("컴플라이언스", "AML", ["aml", "자금세탁", "제재", "kyc"]),
    ("컴플라이언스", "개인정보보호", ["개인정보", "privacy", "cpo", "정보보호"]),
    ("컴플라이언스", "공정거래", ["공정거래", "하도급", "cp ", "자율준수", "대리점"]),
    ("컴플라이언스", "준법감시", ["준법감시", "준법", "compliance", "컴플라이언스", "윤리경영", "윤리", "반부패", "규제대응", "내부통제기준"]),
    ("감사", "내부통제", ["내부통제", "내부회계", "icfr", "k-sox", "sox", "itgc"]),
    ("감사", "회계감사", ["회계감사", "audit associate", "감사본부", "assurance", "외부감사"]),
    ("감사", "IT감사", ["it감사", "it 감사", "정보시스템감사", "cisa"]),
    ("감사", "내부감사", ["감사", "audit", "경영진단", "진단팀"]),
    ("법무", "사내변호사", ["변호사", "legal counsel", "counsel", "lawyer", "in-house"]),
    ("법무", "송무·소송", ["송무", "소송", "분쟁", "litigation"]),
    ("법무", "법무사·법률사무", ["법무사", "법률사무", "사무장", "등기", "paralegal", "패러리걸", "송무비서", "법률비서"]),
    ("법무", "법무 일반", ["법무", "legal", "계약검토", "계약 검토", "법률"]),
]
TARGET_SECTORS = {  # 사이트 직무 분류명 → 그룹
    "법무": "법무", "사내변호사": "법무", "변호사": "법무", "법무사": "법무", "법률사무원": "법무", "송무비서": "법무",
    "법무담당자": "법무", "송무담당": "법무", "소송·민사·등기": "법무", "총무·법무·특허": None, "법무·회계": None,
    "컴플라이언스": "컴플라이언스", "준법감시": "컴플라이언스",
    "특허관리": "특허", "IP(지식재산권)": "특허", "특허분석": "특허", "변리사": "특허", "특허명세사": "특허",
    "특허컨설팅": "특허", "상표관리": "특허", "특허담당": "특허", "지적재산권": "특허",
    "감사": "감사", "내부감사": "감사", "감사담당자": "감사",
}


def classify(title, sectors):
    """제목을 우선 보고, 없으면 사이트 직무 분류로 그룹·세부 직무를 정한다."""
    t = " " + title.lower() + " "
    for g, sub, kws in RULES:
        if any(k in t for k in kws):
            return g, sub, "title"
    groups = [TARGET_SECTORS.get(s) for s in sectors if TARGET_SECTORS.get(s)]
    if groups:
        g = groups[0]
        sub = {"법무": "법무 일반", "컴플라이언스": "준법감시", "특허": "특허·IP", "감사": "내부감사"}[g]
        blob = " ".join(sectors).lower()
        for gg, s2, kws in RULES:
            if gg == g and any(k in blob for k in kws):
                sub = s2
                break
        return g, sub, "category"
    return None, None, None


MULTI_RE = re.compile(r"(전\s?부문|각\s?부문|부문별|전\s?직군|직군별|각\s?분야|분야별|신입사원|공개\s?채용|공채|정기\s?채용|수시\s?채용|대규모|신입\s?(및|/|·)\s?경력|채용\s?공고$)")
EXCLUDE_RE = re.compile(r"(국비지원|국비|수강생|교육생 모집|학원|취업반|무료교육|자격증 취득)")


def is_multi(title, how):
    """제목에 직무 키워드가 없고 직무 분류로만 잡힌 '여러 직무 공채'인지."""
    return how == "category" and bool(MULTI_RE.search(title) or len(title) < 4)


# ---------------------------------------------------------------- 공통 파서
REGION_NAMES = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "전국", "해외"]


def parse_region(s):
    s = clean(s)
    for r in REGION_NAMES:
        if s.startswith(r):
            return r, s
    if "재택" in s or "원격" in s:
        return "원격", s
    return ("기타" if s else "미기재"), s


def parse_exp(s):
    s = clean(s)
    nums = [int(x) for x in re.findall(r"(\d+)\s*년", s)]
    lo = nums[0] if nums else 0
    if "무관" in s:
        t = "경력무관"
    elif "신입" in s and "경력" in s:
        t = "신입·경력"
    elif "신입" in s:
        t = "신입"
    elif "경력" in s:
        t = "경력"
    else:
        t = "미기재"
    return t, lo, s


def parse_edu(s):
    s = clean(s)
    for k, v in [("박사", "박사"), ("석사", "석사"), ("대졸", "대졸(4년)"), ("4년", "대졸(4년)"), ("대학교", "대졸(4년)"),
                 ("초대졸", "초대졸"), ("2,3년", "초대졸"), ("2·3년", "초대졸"), ("전문대", "초대졸"), ("고졸", "고졸"), ("무관", "학력무관")]:
        if k in s:
            return v
    return "미기재"


def parse_emp(s):
    s = clean(s)
    out = []
    for k in ["정규직", "계약직", "인턴", "파견직", "프리랜서", "아르바이트", "위촉직", "병역특례"]:
        if k in s:
            out.append(k)
    return out or (["미기재"] if not s else [s[:10]])


# ---------------------------------------------------------------- 사람인
SARAMIN_CODES = {
    "법무": "2215,387,385,383,391,390",
    "컴플라이언스": "397",
    "특허": "420,424,421,384,398,422,408",
    "감사": "321,341",
}


def saramin_deadline(s):
    s = clean(s)
    m = re.search(r"(\d{1,2})/(\d{1,2})", s)
    if "상시" in s or "채용시" in s:
        return None, s
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = TODAY.year + (1 if mo < TODAY.month - 1 else 0)
        try:
            return dt.date(y, mo, d).isoformat(), s
        except ValueError:
            return None, s
    if "오늘마감" in s:
        return TODAY.isoformat(), s
    if "내일마감" in s:
        return (TODAY + dt.timedelta(days=1)).isoformat(), s
    return None, s


def collect_saramin(max_pages=6):
    jobs = {}
    for group, codes in SARAMIN_CODES.items():
        for page in range(1, max_pages + 1):
            url = ("https://www.saramin.co.kr/zf_user/search/recruit?" + urllib.parse.urlencode(
                {"cat_kewd": codes, "recruitPage": page, "recruitPageCount": 100, "recruitSort": "reg_dt"}))
            t = get(url)
            soup = BeautifulSoup(t, "html.parser")
            items = soup.select("div.item_recruit")
            print(f"saramin {group} p{page}: {len(items)}", file=sys.stderr)
            if not items:
                break
            for it in items:
                rid = it.get("value")
                a = it.select_one("h2.job_tit a")
                if not rid or not a:
                    continue
                title = clean(a.get("title") or a.get_text())
                corp_a = it.select_one(".corp_name a")
                corp = clean(corp_a.get_text()) if corp_a else ""
                csn_m = re.search(r"csn=([^&\"]+)", corp_a.get("href", "")) if corp_a else None
                cond = [clean(x.get_text(" ")) for x in it.select(".job_condition > span")]
                sectors = [clean(x.get_text()) for x in it.select(".job_sector a")]
                day = it.select_one(".job_day")
                pub = None
                if day:
                    m = re.search(r"(\d\d)/(\d\d)/(\d\d)", day.get_text())
                    if m:
                        pub = f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
                dl, dl_raw = saramin_deadline(it.select_one(".job_date .date").get_text() if it.select_one(".job_date .date") else "")
                region, region_raw = parse_region(cond[0] if cond else "")
                exp_t, exp_min, exp_raw = parse_exp(cond[1] if len(cond) > 1 else "")
                jobs[rid] = {
                    "source": "사람인", "sourceId": rid, "title": title, "company": corp,
                    "url": f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={rid}",
                    "region": region, "regionRaw": region_raw, "expType": exp_t, "expMin": exp_min, "expRaw": exp_raw,
                    "education": parse_edu(cond[2] if len(cond) > 2 else ""), "employment": parse_emp(cond[3] if len(cond) > 3 else ""),
                    "publishedAt": pub, "deadline": dl, "deadlineRaw": dl_raw, "sectors": sectors, "hintGroup": group,
                    "csn": urllib.parse.unquote(csn_m.group(1)) if csn_m else None,
                }
            if len(items) < 100:
                break
    return list(jobs.values())


# ---------------------------------------------------------------- 잡코리아
JOBKOREA_KEYWORDS = ["법무", "사내변호사", "컴플라이언스", "준법감시", "특허", "변리사", "내부감사", "내부통제", "감사팀"]
JK_TARGET_WORK = {"법무담당자", "변호사", "법무사", "변리사", "특허담당", "송무담당", "컴플라이언스", "감사", "내부감사", "준법감시", "법률사무원"}


def collect_jobkorea(max_pages=4):
    jobs = {}
    for kw in JOBKOREA_KEYWORDS:
        for page in range(1, max_pages + 1):
            url = "https://www.jobkorea.co.kr/Search/?" + urllib.parse.urlencode({"stext": kw, "tabType": "recruit", "Page_No": page, "Ord": "RegDtDesc"})
            t = get(url)
            chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', t, re.S)
            s = "".join(json.loads('"' + c + '"') for c in chunks)
            m = re.search(r'"content":(\[\{"id":".*?\}\])\s*,\s*"(?:pageable|last|sort|first|numberOfElements)"', s, re.S)
            content = []
            if m:
                try:
                    content = json.loads(m.group(1))
                except json.JSONDecodeError:
                    content = []
            if not content:  # 폴백: 객체를 하나씩 파싱
                dec = json.JSONDecoder()
                for mm in re.finditer(r'\{"id":"\d+","legacyJobNo"', s):
                    try:
                        obj, _ = dec.raw_decode(s, mm.start())
                        content.append(obj)
                    except json.JSONDecodeError:
                        pass
            soup = BeautifulSoup(t, "html.parser")
            cards = {}
            for card in soup.select('[data-sentry-component="CardJob"]'):
                a = card.select_one('a[href*="GI_Read/"]')
                if not a:
                    continue
                gid = re.search(r"GI_Read/(\d+)", a["href"]).group(1)
                texts = [clean(x.get_text(" ")) for x in card.find_all(["span", "div"]) if x.find(["span", "div"]) is None and clean(x.get_text())]
                cards[gid] = texts
            print(f"jobkorea {kw} p{page}: {len(content)}", file=sys.stderr)
            if not content:
                break
            for c in content:
                gid = str(c.get("id"))
                title = clean(c.get("title"))
                works = [w.strip() for w in (c.get("_internal_featureWorkCode") or "").split(",") if w.strip()]
                g, _, _ = classify(title, [w for w in works if w in JK_TARGET_WORK])
                if not g:
                    continue
                texts = cards.get(gid, [])
                region_raw = next((x for x in texts if any(x.startswith(r) for r in REGION_NAMES)), "")
                region, region_raw = parse_region(region_raw)
                exp_txt = next((x for x in reversed(texts) if re.match(r"^(신입|경력)", x)), "")
                if not exp_txt:
                    exp_txt = {"1": "신입", "2": "경력", "3": "신입·경력", "4": "경력무관"}.get(str(c.get("careerType") or ""), "")
                exp_t, exp_min, exp_raw = parse_exp(exp_txt)
                salary = next((x for x in texts if re.match(r"^(연봉|월급|월|시급)\s?[\d,~]", x)), None)
                end = (c.get("applicationPeriod") or {}).get("end")
                edu = {"0": "학력무관", "1": "고졸", "2": "초대졸", "3": "대졸(4년)", "4": "석사", "5": "박사"}.get(str(c.get("educationCode")), "미기재")
                emp_codes = c.get("employmentTypeCodeList") or []
                emp = []
                for e in emp_codes:
                    k = str(e).split("/")[0]
                    emp.append({"1": "정규직", "2": "계약직", "3": "인턴", "4": "파견직", "5": "도급", "6": "프리랜서", "7": "아르바이트", "8": "연수생", "9": "병역특례", "10": "위촉직"}.get(k, "기타"))
                jobs[gid] = {
                    "source": "잡코리아", "sourceId": gid, "title": title, "company": clean(c.get("postingCompanyName") or c.get("companyName")),
                    "url": f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gid}",
                    "region": region, "regionRaw": region_raw, "expType": exp_t, "expMin": exp_min,
                    "expRaw": exp_raw, "salary": salary, "allWorks": len(works), "education": edu, "employment": sorted(set(emp)) or ["미기재"],
                    "publishedAt": (c.get("createdAt") or "")[:10] or None,
                    "deadline": end[:10] if end and not end.startswith("9999") else None, "deadlineRaw": "",
                    "sectors": [w for w in works if w in JK_TARGET_WORK] or works[:4],
                    "listed": c.get("stockTypeCode") in ("1", "2"),
                }
            if len(content) < 20:
                break
    return list(jobs.values())


# ---------------------------------------------------------------- 인크루트
INCRUIT_KEYWORDS = ["법무", "사내변호사", "컴플라이언스", "준법감시", "특허", "변리사", "내부감사", "내부통제"]


def incruit_deadline(s):
    s = clean(s)
    m = re.search(r"~\s*(\d{1,2})\.(\d{1,2})", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = TODAY.year + (1 if mo < TODAY.month - 1 else 0)
        try:
            return dt.date(y, mo, d).isoformat()
        except ValueError:
            return None
    return None


def collect_incruit(max_pages=3):
    jobs = {}
    for kw in INCRUIT_KEYWORDS:
        for page in range(max_pages):
            url = "https://search.incruit.com/list/search.asp?" + urllib.parse.urlencode({"col": "job", "kw": kw, "startno": page * 60, "psize": 60, "SortCd": "reg"})
            t = get(url, encoding="cp949")
            soup = BeautifulSoup(t, "html.parser")
            rows = soup.select("ul.c_row[jobno]")
            print(f"incruit {kw} p{page}: {len(rows)}", file=sys.stderr)
            if not rows:
                break
            for r in rows:
                jid = r["jobno"]
                a = r.select_one(".cell_mid .cl_top a")
                if not a:
                    continue
                title = clean(a.get_text())
                corp = clean(r.select_one("a.cpname").get_text()) if r.select_one("a.cpname") else ""
                md = [clean(x.get_text()) for x in r.select(".cell_mid .cl_md span")]
                sectors = [clean(x.get_text()).rstrip(",") for x in r.select(".cell_mid .cl_btm span")]
                g, _, _ = classify(title, sectors)
                if not g:
                    continue
                last = [clean(x.get_text()) for x in r.select(".cell_last .cl_btm span")]
                dl_raw = last[0] if last else ""
                pub = None
                m = re.match(r"(\d\d)(\d\d)(\d\d)", jid)
                if m:
                    try:
                        pub = dt.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
                    except ValueError:
                        pub = None
                region, region_raw = parse_region(md[0] if md else "")
                exp_t, exp_min, exp_raw = parse_exp(md[1] if len(md) > 1 else "")
                jobs[jid] = {
                    "source": "인크루트", "sourceId": jid, "title": title, "company": corp,
                    "url": f"https://job.incruit.com/jobdb_info/jobpost.asp?job={jid}",
                    "region": region, "regionRaw": region_raw, "expType": exp_t, "expMin": exp_min, "expRaw": exp_raw,
                    "education": parse_edu(md[2] if len(md) > 2 else ""), "employment": parse_emp(md[3] if len(md) > 3 else ""),
                    "publishedAt": pub, "deadline": incruit_deadline(dl_raw), "deadlineRaw": dl_raw, "sectors": sectors,
                }
            if len(rows) < 60:
                break
    return list(jobs.values())


# ---------------------------------------------------------------- 합치기
def norm_company(s):
    s = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(재\)|재단법인|사단법인|\(사\)|\s", "", s or "")
    return s.lower()


def norm_title(s):
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】", " ", s or "")
    s = re.sub(r"[^0-9a-zA-Z가-힣]", "", s)
    return s.lower()


def main():
    which = sys.argv[1:] or ["saramin", "jobkorea", "incruit"]
    fns = {"saramin": collect_saramin, "jobkorea": collect_jobkorea, "incruit": collect_incruit}
    RAW.mkdir(exist_ok=True)
    raw = []
    for name, fn in fns.items():
        cache = RAW / f"collected_{name}.json"
        if name in which:
            data = fn()
            cache.write_text(json.dumps(data, ensure_ascii=False))
        elif cache.exists():
            data = json.loads(cache.read_text())
        else:
            data = []
        raw += data

    merged = {}
    for j in raw:
        g, sub, how = classify(j["title"], j.get("sectors", []))
        if not g and j.get("hintGroup"):
            g, sub, how = j["hintGroup"], {"법무": "법무 일반", "컴플라이언스": "준법감시", "특허": "특허·IP", "감사": "내부감사"}[j["hintGroup"]], "category"
        if not g or EXCLUDE_RE.search(j["title"]):
            continue
        if how == "category" and j.get("allWorks", 0) > 8:
            how = "category-wide"
        # 마감이 지난 공고 제외
        if j.get("deadline") and j["deadline"] < TODAY.isoformat():
            continue
        key = norm_company(j["company"]) + "|" + norm_title(j["title"])
        listing = {"source": j["source"], "url": j["url"], "sourceId": j["sourceId"]}
        if key in merged:
            m = merged[key]
            if j.get("csn") and not m.get("csn"):
                m["csn"] = j["csn"]
            if j["source"] not in [l["source"] for l in m["listings"]]:
                m["listings"].append(listing)
            for f in ("deadline", "publishedAt"):
                if not m.get(f) and j.get(f):
                    m[f] = j[f]
            if j.get("publishedAt") and m.get("publishedAt") and j["publishedAt"] < m["publishedAt"]:
                m["publishedAt"] = j["publishedAt"]
            continue
        merged[key] = {
            "id": f"{ {'사람인': 'sr', '잡코리아': 'jk', '인크루트': 'ic'}[j['source']] }{j['sourceId']}".replace(" ", ""),
            "title": j["title"], "company": j["company"], "roleGroup": g, "role": sub, "classifiedBy": how, "multi": is_multi(j["title"], how) or how == "category-wide",
            "broad": how != "title",
            "salary": j.get("salary"),
            "region": j["region"], "regionRaw": j["regionRaw"], "expType": j["expType"], "expMin": j["expMin"], "expRaw": j["expRaw"],
            "education": j["education"], "employment": j["employment"], "publishedAt": j["publishedAt"],
            "deadline": j["deadline"], "deadlineRaw": j.get("deadlineRaw", ""), "sectors": j.get("sectors", [])[:6],
            "listings": [listing], "csn": j.get("csn"),
        }
    # 이전 수집 결과에서 '처음 발견된 시각'을 이어받는다 (없으면 지금이 처음)
    prev_path = OUT / "jobs.json"
    prev_seen, prev_meta = {}, {}
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text())
            prev_meta = prev.get("meta", {})
            for pj in prev.get("jobs", []):
                k = norm_company(pj["company"]) + "|" + norm_title(pj["title"])
                prev_seen[k] = pj.get("firstSeen") or prev_meta.get("collectedAt")
        except (json.JSONDecodeError, KeyError):
            pass
    now_iso = NOW.isoformat(timespec="minutes")
    for k, m in merged.items():
        m["firstSeen"] = prev_seen.get(k) or now_iso
    new_count = sum(1 for k in merged if k not in prev_seen)
    jobs = sorted(merged.values(), key=lambda x: (x["publishedAt"] or "", x["id"]), reverse=True)
    counts = {}
    for j in raw:
        counts[j["source"]] = counts.get(j["source"], 0) + 1
    meta = {
        "collectedAt": now_iso, "total": len(jobs), "rawBySource": counts,
        "firstCollectedAt": prev_meta.get("firstCollectedAt") or prev_meta.get("collectedAt") or now_iso,
        "newThisRun": new_count if prev_seen else 0,
        "sources": [
            {"name": "사람인", "url": "https://www.saramin.co.kr/"},
            {"name": "잡코리아", "url": "https://www.jobkorea.co.kr/"},
            {"name": "인크루트", "url": "https://www.incruit.com/"},
        ],
        "note": "각 사이트 공개 검색 목록의 요약 정보입니다. 상세 내용과 지원은 원문 사이트에서 확인하세요.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "jobs.json").write_text(json.dumps({"meta": meta, "jobs": jobs}, ensure_ascii=False, separators=(",", ":")))
    from collections import Counter
    print("raw", counts, "merged", len(jobs), "new", new_count if prev_seen else "(first run)")
    print(Counter(j["roleGroup"] for j in jobs))
    print(Counter(j["role"] for j in jobs).most_common())
    print("multi-source", sum(1 for j in jobs if len(j["listings"]) > 1))


if __name__ == "__main__":
    main()
