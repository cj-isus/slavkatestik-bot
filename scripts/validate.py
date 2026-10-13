# -*- coding: utf-8 -*-
"""Validate content.json + guides.json consistency."""
import json
import sys

with open("content.json", encoding="utf-8") as f:
    c = json.load(f)
with open("guides.json", encoding="utf-8") as f:
    g = json.load(f)

titles = [i["title"] for cat in c["categories"] for i in cat["items"]]
dupes = {t for t in titles if titles.count(t) > 1}
missing = [t for t in titles if t not in g]
str_n = sum(1 for v in g.values() if isinstance(v, str))
list_n = sum(1 for v in g.values() if isinstance(v, list))

print(f"categories={len(c['categories'])} items={len(titles)} guides={len(g)}")
print(f"guide formats: str={str_n} list={list_n}")
if dupes:
    print("DUPLICATE titles:", dupes)
if missing:
    print("MISSING guides:", missing)
if dupes or missing:
    sys.exit(1)
print("OK")
