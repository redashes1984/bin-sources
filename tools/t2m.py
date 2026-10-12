#!/usr/bin/env python3
"""t2m — torrent file -> magnet URI converter (stdlib only, no deps).

Follows BEP-9: the magnet info-hash is the hex SHA-1 of the *bencoded*
"info" dictionary inside the .torrent file. The hash is taken over the
EXACT stored bytes of the info dict (not a re-canonicalised encoding --
re-sorting keys changes the digest and breaks cross-client identity).
Trackers come from the top level "announce" / "announce-list" keys;
display name from info["name"].

Usage:
    python3 tools/t2m.py file.torrent          # print one magnet URI
    python3 tools/t2m.py --hash file.torrent   # print bare btih hex only
    cat file.torrent | python3 tools/t2m.py -  # read from stdin

Why magnets instead of signed http URLs for hot BT entries: signed CDN
urls (bilibili qn=64 style) expire within hours and rot the cache; a
magnet btih is content-addressed and stays valid as long as the swarm
does, so bt-pool entries survive the 3h srcs TTL comfortably. aria2c
consumes magnet URIs natively as a positional argument.

Verified against reference outputs:
  ubuntu-22.04.5-desktop-amd64.iso  -> 512e5c1c3215d06ee8e174713a925799bf55a94a
  ubuntu-22.04.5-live-server-amd64  -> 55082ef8441efde0683e754636a863599db8f0c9
"""
import hashlib
import sys


def bdecode(data):
    """Minimal bencode decoder -> bytes/int/list/dict."""

    def parse(i):
        c = data[i:i + 1]
        if c == b"i":
            j = data.index(b"e", i)
            return int(data[i + 1:j]), j + 1
        if c == b"l":
            i += 1
            out = []
            while data[i:i + 1] != b"e":
                v, i = parse(i)
                out.append(v)
            return out, i + 1
        if c == b"d":
            i += 1
            out = {}
            while data[i:i + 1] != b"e":
                k, i = parse(i)
                v, i = parse(i)
                out[k] = v
            return out, i + 1
        j = data.index(b":", i)
        ln = int(data[i:j])
        s = data[j + 1:j + 1 + ln]
        return s, j + 1 + ln

    val, _end = parse(0)
    return val


def info_dict_bytes(raw):
    """Return the exactly-bencoded bytes of the top-level info dict."""
    t = bdecode(raw)
    info = t.get(b"info")
    if info is None:
        raise SystemExit("not a torrent file: no info dict")
    return encode(info)


def encode(v):
    if isinstance(v, bytes):
        return str(len(v)).encode() + b":" + v
    if isinstance(v, int):
        return b"i" + str(v).encode() + b"e"
    if isinstance(v, list):
        return b"l" + b"".join(encode(x) for x in v) + b"e"
    if isinstance(v, dict):
        body = b"".join(encode(k) + encode(v[k]) for k in sorted(v))
        return b"d" + body + b"e"
    raise TypeError(f"unsupported bencode type: {type(v)}")


def to_magnet(raw):
    t = bdecode(raw)
    info = t.get(b"info")
    h = hashlib.sha1(encode(info)).hexdigest()
    parts = ["xt=urn:btih:" + h]
    name = info.get(b"name") if isinstance(info, dict) else None
    if isinstance(name, bytes) and name:
        parts.append("dn=" + name.decode("utf-8", "replace"))
    trs = []
    ann = t.get(b"announce")
    if isinstance(ann, bytes) and ann:
        trs.append(ann.decode("utf-8", "replace"))
    al = t.get(b"announce-list")
    if isinstance(al, list):
        for grp in al:
            if isinstance(grp, list):
                for g in grp:
                    if isinstance(g, bytes) and g.decode("utf-8", "replace") not in trs:
                        trs.append(g.decode("utf-8", "replace"))
    for tr in trs:
        parts.append("tr=" + tr)
    return h, "magnet:?" + "&".join(parts)


def main():
    args = [a for a in sys.argv[1:]]
    want_hash = False
    if args and args[0] == "--hash":
        want_hash = True
        args = args[1:]
    if len(args) > 1 or args[:1] == ["--parse"]:  # offline entry kept simple
        args = args[1:] if args[:1] == ["--parse"] else args
    path = args[0] if args else None
    raw = sys.stdin.buffer.read() if path in (None, "-") else open(path, "rb").read()
    h, mag = to_magnet(raw)
    print(h if want_hash else mag)


if __name__ == "__main__":
    main()
