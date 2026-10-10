#!/usr/bin/env python3
"""Daily generator: candidates.json -> srcs.json (probed, latency-sorted).

Rules:
- Everything data-driven from candidates.json; no sources hardcoded here.
- A candidate entry survives only if HEAD + a small Range fetch succeed today.
- Output keeps: date, entries sorted by measured latency, per-entry last-good.
- On total failure (no entry passes), reuse yesterday's srcs.json so the
  worker pool never goes empty.
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CAND = os.path.join(ROOT, "candidates.json")
OUT = os.path.join(ROOT, "srcs.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-262143"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return len(body), round(time.monotonic() - t0, 3)


def probe_http(entry):
    results = []
    for p in entry.get("paths", [""]):
        url = entry["base"].rstrip("/") + "/" + p.lstrip("/") if p else entry["base"]
        try:
            size, ms = fetch(url)
            results.append({"url": url, "bytes": size, "ms": ms})
        except Exception as e:  # noqa: BLE001
            print(f"skip {url}: {e}", file=sys.stderr)
    if not results:
        return None
    results.sort(key=lambda x: x["ms"])
    return {
        "host": entry["host"],
        "pick": results[0],
        "alts": results[1:],
    }


def probe_bt(cfg):
    out = []
    for e in cfg.get("entries", []):
        r = probe_http(e)
        if r:
            out.append(r)
    for tr in cfg.get("trackers", []):
        try:
            size, ms = fetch(tr)
            out.append({"pick": {"url": tr, "bytes": size, "ms": ms}, "host": "tracker"})
        except Exception:  # noqa: BLE001
            pass
    out.sort(key=lambda x: x["pick"]["ms"])
    return out


def main():
    with open(CAND, encoding="utf-8") as f:
        cand = json.load(f)

    http_entries = [e for e in (probe_http(x) for x in cand["http"]) if e]
    bt_entries = probe_bt(cand.get("bt", {}))

    if not http_entries and os.path.exists(OUT):
        print("nothing passed today; keeping previous srcs.json", file=sys.stderr)
        return

    doc = {
        "schema": 1,
        "date": time.strftime("%Y-%m-%d"),
        "generated_at": int(time.time()),
        "http": http_entries,
        "bt": bt_entries,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, OUT)
    print(f"wrote {OUT}: http={len(http_entries)} bt={len(bt_entries)}")


if __name__ == "__main__":
    main()
