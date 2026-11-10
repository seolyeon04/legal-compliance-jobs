"""page.html(본문)을 감싸서 Vercel이 그대로 서빙할 index.html을 만든다."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
src = (ROOT / "page.html").read_text()
cut = src.index("</style>") + len("</style>")
head, body = src[:cut], src[cut:]
RESET = (":root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
         "body{margin:0}img{max-width:100%}[hidden]{display:none!important}")
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%231f4fd1'/%3E"
           "%3Cpath d='M9 22V10h4.5a4 4 0 0 1 0 8H13M19 10v12h5' fill='none' stroke='white' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")
html = f"""<!doctype html>
<html lang="ko" data-mode="web">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="사람인·잡코리아·인크루트의 법무·컴플라이언스·특허·감사 채용공고를 매일 모아 보여줘요.">
<meta property="og:title" content="법무 채용 레이더">
<meta property="og:description" content="법무·컴플라이언스·특허·감사 채용공고 모아보기">
<link rel="icon" href="{FAVICON}">
<style>{RESET}</style>
{head}
</head>
<body>
{body}
</body>
</html>
"""
(ROOT / "index.html").write_text(html)
print("index.html", len(html), "bytes")
