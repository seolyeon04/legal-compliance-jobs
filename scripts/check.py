"""수집 결과 점검: 이전 커밋보다 공고가 크게 줄었거나 한 사이트가 0건이면 실패한다."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
new = json.loads((ROOT / "data" / "jobs.json").read_text())
try:
    old = json.loads(subprocess.run(["git", "show", "HEAD:data/jobs.json"], cwd=ROOT, capture_output=True, check=True, text=True).stdout)
except subprocess.CalledProcessError:
    old = {"jobs": []}
n_new, n_old = len(new["jobs"]), len(old["jobs"])
by_src = new["meta"].get("rawBySource", {})
print(f"jobs {n_old} -> {n_new}, new this run {new['meta'].get('newThisRun')}, by source {by_src}")
problems = [f"{s}: 0건" for s in ("사람인", "잡코리아", "인크루트") if not by_src.get(s)]
if n_old and n_new < n_old * 0.6:
    problems.append(f"공고 수 급감 {n_old} -> {n_new}")
if problems:
    print("점검 실패:", "; ".join(problems))
    sys.exit(1)
print("점검 통과")
