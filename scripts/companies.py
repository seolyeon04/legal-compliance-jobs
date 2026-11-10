"""공고에 나온 기업의 사람인 기업정보(업력, 사원수, 매출액, 업종, 평균연봉)를 모은다.

사람인 robots.txt가 허용하는 /zf_user/company-info/ 경로만 사용한다.
이미 받은 기업은 캐시에서 다시 쓰므로, 다시 돌리면 새 기업만 요청한다.
"""
import json
import pathlib
import re
import sys
import urllib.parse

from bs4 import BeautifulSoup

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collect import OUT, RAW, clean, get, norm_company  # noqa: E402

CACHE = RAW / "companies_cache.json"


def money_to_eok(s):
    """'1,082억 7,985만원' / '5조 2,000억' / '3,500만원' → 억 단위 실수."""
    s = s.replace(",", "")
    jo = re.search(r"(\d+(?:\.\d+)?)\s*조", s)
    eok = re.search(r"(\d+(?:\.\d+)?)\s*억", s)
    man = re.search(r"(\d+(?:\.\d+)?)\s*만", s)
    if not (jo or eok or man):
        return None
    v = 0.0
    if jo:
        v += float(jo.group(1)) * 10000
    if eok:
        v += float(eok.group(1))
    if man and not jo:
        v += float(man.group(1)) / 10000
    return round(v, 1)


def parse_company(csn):
    q = urllib.parse.quote(csn, safe="")
    info = {"csn": csn, "url": f"https://www.saramin.co.kr/zf_user/company-info/view?csn={q}"}
    t = get(info["url"])
    if not t:
        return None
    soup = BeautifulSoup(t, "lxml")
    name = soup.select_one(".company_name, .tit_company, h1")
    if name:
        info["name"] = clean(name.get_text())
    for li in soup.select("li.company_summary_item"):
        tit = clean(li.select_one(".company_summary_tit").get_text(" ")) if li.select_one(".company_summary_tit") else ""
        desc = clean(li.select_one(".company_summary_desc").get_text(" ")) if li.select_one(".company_summary_desc") else clean(li.get_text(" "))
        if "업력" in tit or "설립" in desc:
            m = re.search(r"(\d+)\s*년차", tit)
            info["years"] = int(m.group(1)) if m else None
            y = re.search(r"(\d{4})년", desc)
            info["founded"] = int(y.group(1)) if y else None
        elif "사원수" in desc or tit.endswith("명"):
            m = re.search(r"([\d,]+)\s*명", tit)
            if m:
                info["employees"] = int(m.group(1).replace(",", ""))
        elif "매출" in desc:
            info["revenue"] = money_to_eok(tit)
            info["revenueRaw"] = tit
        elif "기업형태" in desc or tit in ("대기업", "중견기업", "중소기업", "공기업", "외국계", "스타트업"):
            info["type"] = tit
        elif "영업이익" in desc:
            info["operatingIncome"] = money_to_eok(tit)
    for dl in soup.select(".company_details_group dl, dl.company_details_group, .company_details dl"):
        dt_ = clean(dl.select_one("dt").get_text()) if dl.select_one("dt") else ""
        dd = clean(dl.select_one("dd").get_text(" ")) if dl.select_one("dd") else ""
        if dt_ == "업종":
            info["industry"] = dd[:40]
        elif dt_ == "기업형태" and "type" not in info:
            info["type"] = dd[:20]
    if "industry" not in info:
        txt = clean(soup.get_text(" "))
        m = re.search(r"업종\s+(.{2,40}?)\s+(홈페이지|사업내용|주소|대표자)", txt)
        if m:
            info["industry"] = m.group(1)
    # 평균연봉
    st = get(f"https://www.saramin.co.kr/zf_user/company-info/view-inner-salary?csn={q}")
    if st:
        txt = clean(BeautifulSoup(st, "lxml").get_text(" "))
        m = re.search(r"권장해 드립니다\.?\s*([\d,]+)\s*만원", txt) or re.search(r"평균연봉[^\d]{0,80}?([\d,]{3,})\s*만원", txt)
        if m:
            info["avgSalary"] = int(m.group(1).replace(",", ""))
        y = re.search(r"(\d{4})년 평균연봉", txt)
        if y:
            info["salaryYear"] = int(y.group(1))
    return info


def main(limit=None):
    data = json.loads((OUT / "jobs.json").read_text())
    jobs = data["jobs"]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    # 캐시 파일이 없으면(새 환경) 게시된 companies.json에서 이어받는다
    if (OUT / "companies.json").exists():
        try:
            for c in json.loads((OUT / "companies.json").read_text()).get("companies", []):
                if c.get("csn") and c["csn"] not in cache:
                    cache[c["csn"]] = {k: v for k, v in c.items() if k not in ("id", "jobCount")}
        except json.JSONDecodeError:
            pass
    # 회사명 → csn (사람인에서 본 것)
    name2csn = {}
    for j in jobs:
        if j.get("csn"):
            name2csn.setdefault(norm_company(j["company"]), j["csn"])
    # 단일 직무 공고의 회사를 먼저, 공고가 많은 회사부터
    order = {}
    for j in jobs:
        csn = j.get("csn") or name2csn.get(norm_company(j["company"]))
        if csn:
            order[csn] = order.get(csn, 0) + (3 if not j.get("multi") else 1)
    todo = [c for c, _ in sorted(order.items(), key=lambda x: -x[1]) if c not in cache]
    if limit:
        todo = todo[:limit]
    print("companies", len(order), "cached", len(cache), "to fetch", len(todo), file=sys.stderr)
    for i, csn in enumerate(todo, 1):
        try:
            info = parse_company(csn)
        except Exception as e:  # noqa: BLE001
            print("  fail", csn, e, file=sys.stderr)
            continue
        if info:
            cache[csn] = info
        if i % 20 == 0:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False))
            print(f"  {i}/{len(todo)}", file=sys.stderr)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))

    companies = {}
    for csn in order:
        if csn in cache:
            c = dict(cache[csn])
            c["id"] = "c" + re.sub(r"[^0-9A-Za-z]", "", csn)[:24]
            companies[csn] = c
    for j in jobs:
        csn = j.get("csn") or name2csn.get(norm_company(j["company"]))
        j["companyId"] = companies[csn]["id"] if csn in companies else None
    for c in companies.values():
        c["jobCount"] = sum(1 for j in jobs if j.get("companyId") == c["id"])
        c["name"] = next((j["company"] for j in jobs if j.get("companyId") == c["id"]), c.get("name", "")).strip()
    (OUT / "jobs.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    out = {"meta": {"collectedAt": data["meta"]["collectedAt"], "source": "사람인 기업정보 (사원수: 국민연금, 매출액: NICE 등 사람인 표기 출처)"},
           "companies": sorted(companies.values(), key=lambda c: -(c.get("revenue") or 0))}
    (OUT / "companies.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    with_info = sum(1 for j in jobs if j.get("companyId"))
    print("companies saved", len(companies), "jobs with company info", with_info, "/", len(jobs))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
