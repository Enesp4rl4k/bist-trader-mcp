import re

import httpx

r = httpx.get(
    "https://www.turib.com.tr/endeks-anasayfa/",
    timeout=20,
    headers={"User-Agent": "Mozilla/5.0"},
)
print("status", r.status_code)
for pat in [r"admin-ajax\.php[^\"']*", r"wp-json[^\"']*", r"Endeks[^<]{0,40}"]:
    for m in re.finditer(pat, r.text, re.I):
        print(m.group(0)[:100])
