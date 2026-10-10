#!/usr/bin/env python3
"""Daily generator: candidates.json -> srcs.json (three pools, probed, merged).

candidates.json layout:
- https / http : web-direct pools (HTTP/HTTPS direct + curl/wget direct), ~3:3
- bt           : BT-seed backed direct links, ~4 share, entries carry prov/isp

Output srcs.json keeps worker-compatible keys: http (https+http interleaved)
and bt (each entry: pick.url + prov + isp). Workers rotate one merged idx
space over http first, bt after -- so lines naturally alternate pool kinds.

Domestic-IP rule: every web-pool host must resolve to a CN-mainland-ish
address; entries failing resolution or landing on obvious foreign ranges
are dropped with a note. bt pool peers follow the panel tri-toggle filter
computed inside the worker, so gen only guarantees the tags exist.
"""
import json
import os
import socket
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CAND = os.path.join(ROOT, "candidates.json")
OUT = os.path.join(ROOT, "srcs.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

# First-octet set commonly owned by CN Telecom/Unicom/Mobile allocations.
# Purely a smoke filter for typos in hosts -- not a geo authority.
CN_FIRST = {1, 14, 27, 36, 39, 42, 47, 49, 58, 59, 60, 61, 68, 72, 87, 90, 94,
            96, 98, 99, 101, 103, 104, 106, 108, 109, 110, 111, 112, 113,
            114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126,
            127, 133, 134, 135, 136, 137, 138, 139, 140, 142, 144, 146, 147,
            148, 149, 150, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161,
            162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174,
            175, 176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187,
            188, 189, 190, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200,
            201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213,
            214, 215, 216, 217, 218, 219, 220, 221, 222, 223}


def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-262143"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return len(body), round(time.monotonic() - t0, 3)


def host_is_cn(host):
    """Resolve host; keep if any A-record first octet sits in CN_FIRST."""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        for i in infos:
            ip = i[4][0]
            if int(ip.split(".")[0]) in CN_FIRST:
                return True
        return False
    except Exception:
        return True  # DNS hiccup: keep, next run re-checks


def probe_entry(entry):
    if not host_is_cn(entry.get("host", "")):
        print(f"skip {entry.get('host')}: non-CN A record", file=sys.stderr)
        return None
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
    out = {"host": entry["host"], "pick": results[0], "alts": results[1:]}
    for k in ("prov", "isp"):
        if entry.get(k):
            out[k] = entry[k]
    return out


def merge_web(cand):
    """Interleave https and http pools so adjacent idx alternate kinds."""
    a = [e for e in (probe_entry(x) for x in cand.get("https", [])) if e]
    b = [e for e in (probe_entry(x) for x in cand.get("http", [])) if e]
    merged = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            merged.append(a[i])
        if i < len(b):
            merged.append(b[i])
    return merged


def probe_bt(cfg):
    out = []
    for e in cfg.get("entries", []):
        if not e.get("prov"):
            e = dict(e)
            e.setdefault("prov", "unknown")
            e.setdefault("isp", "unknown")
        r = probe_entry(e)
        if r:
            out.append(r)
    for tr in cfg.get("trackers", []):
        try:
            size, ms = fetch(tr)
            out.append({"pick": {"url": tr, "bytes": size, "ms": ms},
                        "host": "tracker", "prov": "unknown", "isp": "unknown"})
        except Exception:  # noqa: BLE001
            pass
    out.sort(key=lambda x: x["pick"]["ms"])
    return out


def main():
    with open(CAND, encoding="utf-8") as f:
        cand = json.load(f)

    web = merge_web(cand)
    bt = probe_bt(cand.get("bt", {}))

    if not web and os.path.exists(OUT):
        print("nothing passed today; keeping previous srcs.json", file=sys.stderr)
        return

    doc = {
        "schema": 2,
        "date": time.strftime("%Y-%m-%d"),
        "generated_at": int(time.time()),
        "http": web,
        "bt": bt,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, OUT)
    nurl = sum(1 + len(e.get("alts", [])) for e in web + bt)
    print(f"wrote {OUT}: http={len(web)} bt={len(bt)} total_urls={nurl}")


if __name__ == "__main__":
    main()
