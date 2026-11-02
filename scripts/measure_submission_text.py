# Measures the submission form text against its limits and audits the content
# rules, so the numbers pasted into the portal are reproducible rather than
# remembered. Limits: description strictly under 1000 characters and free of
# addresses and URLs, review outcome strictly under 500, post under 280.
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXTS = os.path.join(ROOT, "docs", "submission")

SPECS = [
    ("one-liner.txt", 200, {"address": False, "url": False}),
    ("description.txt", 1000, {"address": False, "url": False}),
    ("review-outcome.txt", 500, {"address": True, "url": True}),
    ("x-post.txt", 280, {"address": True, "url": True}),
]

ADDRESS = re.compile(r"0x[0-9a-fA-F]{6,}")
URL = re.compile(r"https?://|\b[\w.-]+\.(com|io|gg|dev)\b")
EM_DASH = "\u2014"

failed = 0
for name, limit, allow in SPECS:
    path = os.path.join(TEXTS, name)
    if not os.path.exists(path):
        print(f"  FAIL  {name}: missing")
        failed += 1
        continue
    text = open(path, encoding="utf-8").read().strip()
    n = len(text)
    checks = [(f"under {limit} characters", n < limit, f"{n} chars")]
    if not allow["address"]:
        checks.append(("no contract address", not ADDRESS.search(text), "clean" if not ADDRESS.search(text) else "found"))
    if not allow["url"]:
        checks.append(("no URL", not URL.search(text), "clean" if not URL.search(text) else "found"))
    checks.append(("no em dash", EM_DASH not in text and " -- " not in text, "clean"))
    for label, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {label} ({detail})")
        failed += 0 if ok else 1

print(f"submission text: {'all limits hold' if failed == 0 else str(failed) + ' failure(s)'}")
sys.exit(1 if failed else 0)
