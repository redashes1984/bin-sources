bin-sources: daily src list generator

- candidates.json edits the source pool (data-driven, nothing hardcoded)
- gen.py probes candidates and writes srcs.json (sorted by latency, atomic replace)
- worker pulls srcs.json via jsDelivr mirror, falls back to local cache
