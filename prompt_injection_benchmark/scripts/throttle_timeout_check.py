# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Classify timed-out eval samples as throttle-caused (resumable) or genuinely slow.

A sample that hits its wall-clock time limit is scored by the programmatic scorer
like any other sample. A timeout has one of two causes:

  throttle      The provider returned throttling / rate-limit errors (e.g. HTTP 429)
                and retry backoff used up the time budget.
                Such samples can be re-run (see run_defense.py --rerun-throttle-timeouts).
  genuine_slow  The agent ran long with no retry signal. The result is kept.

A timed-out sample (limit.type == "time") is classified "throttle" if ANY of:
  (1) sum(model_event.retries) > 0             inspect-level retries
  (2) a logger event mentions "Throttl"        throttle warning logged during the run
  (3) metadata.camel_log.model_generate has an entry with throttle_suspect=True
      (CaMeL defenses: a single generate() call took >= 30s)
  (4) total_time - working_time > 60s          wall-clock time not spent computing,
                                               i.e. backoff sleeps inside the SDK

inspect's ModelEvent keeps only the final request/response, so (1) misses retries
handled inside the SDK; (3) and (4) cover those. Short SDK backoff (< 60s idle) on a
defense without (3) is not detected, so the throttle count is a lower bound.

Library use:

    from prompt_injection_benchmark.scripts.throttle_timeout_check import (
        classify_sample, is_resumable_throttle)

    verdict = classify_sample(sample)        # -> "throttle" | "genuine_slow" | "not_timed"
    if is_resumable_throttle(sample): ...    # -> bool (True only for "throttle")

classify_raw_sample / raw_is_resumable_throttle take a raw sample dict read from
the .eval zip instead of an EvalSample.

CLI (scan eval directories and tabulate timeouts by defense and/or model):

    python -m prompt_injection_benchmark.scripts.throttle_timeout_check DIR [DIR ...]
        [--by model|defense|both] [--list-ids] [--workers N]

    # or read the directory list from a file (one per line):
    python -m prompt_injection_benchmark.scripts.throttle_timeout_check --dirs-file dirs.txt
"""
from __future__ import annotations

import argparse
import glob
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor


IDLE_GAP_THRESHOLD_S = 60.0


def _sum_model_retries(sample) -> int:
    """Total inspect-level retries across all model events in a sample."""
    total = 0
    for e in (getattr(sample, "events", None) or []):
        if getattr(e, "event", None) == "model":
            total += getattr(e, "retries", None) or 0
    return total


def _has_throttle_logger(sample) -> bool:
    """True if any logger event mentions a throttle."""
    for e in (getattr(sample, "events", None) or []):
        if getattr(e, "event", None) == "logger":
            if "Throttl" in str(getattr(e, "message", "")):
                return True
    return False


def _has_throttle_suspect(sample) -> bool:
    """True if the CaMeL camel_log flagged any model_generate call as throttle_suspect.

    Set by the CaMeL defenses' timed_generate wrapper when a single model.generate()
    takes >=30s (SDK-internal throttle backoff at that call).
    """
    md = getattr(sample, "metadata", None) or {}
    clog = md.get("camel_log") if isinstance(md, dict) else None
    if not isinstance(clog, dict):
        return False
    for ev in (clog.get("model_generate") or []):
        if isinstance(ev, dict) and ev.get("throttle_suspect"):
            return True
    return False


def _idle_gap(sample) -> float:
    """total_time - working_time (s): wall-clock spent NOT computing (backoff proxy)."""
    tt = getattr(sample, "total_time", None) or 0
    wt = getattr(sample, "working_time", None) or 0
    return tt - wt


def is_timed_out(sample) -> bool:
    lim = getattr(sample, "limit", None)
    return bool(lim) and getattr(lim, "type", None) == "time"


def classify_sample(sample) -> str:
    """Return 'throttle' | 'genuine_slow' | 'not_timed' for one eval sample.

    'throttle'      => timed out AND any throttle signal (see module docstring) => RESUMABLE
    'genuine_slow'  => timed out with no throttle signal                        => keep result
    'not_timed'     => did not hit the time limit
    """
    if not is_timed_out(sample):
        return "not_timed"
    if (
        _sum_model_retries(sample) > 0
        or _has_throttle_logger(sample)
        or _has_throttle_suspect(sample)
        or _idle_gap(sample) > IDLE_GAP_THRESHOLD_S
    ):
        return "throttle"
    return "genuine_slow"


def is_resumable_throttle(sample) -> bool:
    """Convenience predicate for resume logic: True only for transient throttle timeouts."""
    return classify_sample(sample) == "throttle"


def _raw_sum_model_retries(sample: dict) -> int:
    total = 0
    for e in (sample.get("events") or []):
        if isinstance(e, dict) and e.get("event") == "model":
            total += e.get("retries") or 0
    return total


def _raw_has_throttle_logger(sample: dict) -> bool:
    for e in (sample.get("events") or []):
        if isinstance(e, dict) and e.get("event") == "logger":
            if "Throttl" in str(e.get("message", "")):
                return True
    return False


def _raw_has_throttle_suspect(sample: dict) -> bool:
    md = sample.get("metadata") or {}
    clog = md.get("camel_log") if isinstance(md, dict) else None
    if not isinstance(clog, dict):
        return False
    for ev in (clog.get("model_generate") or []):
        if isinstance(ev, dict) and ev.get("throttle_suspect"):
            return True
    return False


def _raw_idle_gap(sample: dict) -> float:
    return (sample.get("total_time") or 0) - (sample.get("working_time") or 0)


def raw_is_timed_out(sample: dict) -> bool:
    lim = sample.get("limit")
    return isinstance(lim, dict) and lim.get("type") == "time"


def classify_raw_sample(sample: dict) -> str:
    """Same verdicts as classify_sample() but operating on a raw sample dict."""
    if not raw_is_timed_out(sample):
        return "not_timed"
    if (
        _raw_sum_model_retries(sample) > 0
        or _raw_has_throttle_logger(sample)
        or _raw_has_throttle_suspect(sample)
        or _raw_idle_gap(sample) > IDLE_GAP_THRESHOLD_S
    ):
        return "throttle"
    return "genuine_slow"


def raw_is_resumable_throttle(sample: dict) -> bool:
    """Resume predicate for run_defense.py: True only for transient throttle timeouts."""
    return classify_raw_sample(sample) == "throttle"


def _defense_of(d: str) -> str:
    return d.split("/evals/")[1].split("/")[0] if "/evals/" in d else "?"


def _model_of(d: str) -> str:
    parts = d.split("/evals/")
    if len(parts) < 2:
        return "?"
    seg = parts[1].split("/")
    return seg[1] if len(seg) > 1 else "?"


def _scan_file(path: str):
    """Return (total, timed, throttle, genuine, throttle_ids). Lazy import so the
    library half stays importable without inspect installed at module load."""
    from inspect_ai.log import read_eval_log
    try:
        log = read_eval_log(path)
    except Exception:
        return (0, 0, 0, 0, [])
    total = timed = throttle = genuine = 0
    ids = []
    for s in (log.samples or []):
        total += 1
        v = classify_sample(s)
        if v == "not_timed":
            continue
        timed += 1
        if v == "throttle":
            throttle += 1
            ids.append(str(getattr(s, "id", getattr(s, "sample_id", "?"))))
        else:
            genuine += 1
    return (total, timed, throttle, genuine, ids)


def scan(dirs: list[str], workers: int = 16):
    """Scan a list of eval dirs. Returns (per_defense, per_model, per_def_model, all_throttle_ids)."""
    files = []
    for d in dirs:
        for f in glob.glob(f"{d}/*.eval"):
            files.append((_defense_of(d), _model_of(d), f))
    per_def = defaultdict(lambda: [0, 0, 0, 0])
    per_model = defaultdict(lambda: [0, 0, 0, 0])
    per_dm = defaultdict(lambda: [0, 0, 0, 0])
    throttle_ids = defaultdict(list)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for (defn, md, path), r in zip(files, ex.map(_scan_file, [f for _, _, f in files], chunksize=16)):
            tot, timed, thr, gen, ids = r
            for tgt in (per_def[defn], per_model[md], per_dm[(defn, md)]):
                tgt[0] += tot; tgt[1] += timed; tgt[2] += thr; tgt[3] += gen
            if ids:
                throttle_ids[(defn, md)].extend(f"{path}::{i}" for i in ids)
    return per_def, per_model, per_dm, throttle_ids, len(files)


def _print_table(title, rows):
    print(f"\n==== {title} ====", flush=True)
    print(f"{'key':32s} {'total':>7s} {'timed':>6s} {'THROTTLE':>9s} {'genuine':>8s} {'%thr':>6s}", flush=True)
    gt = gtl = gthr = ggen = 0
    for key in sorted(rows):
        t, tl, thr, gen = rows[key]
        gt += t; gtl += tl; gthr += thr; ggen += gen
        k = " / ".join(key) if isinstance(key, tuple) else str(key)
        print(f"{k:32s} {t:7d} {tl:6d} {thr:9d} {gen:8d} {(100*thr/t if t else 0):5.1f}%", flush=True)
    print(f"{'TOTAL':32s} {gt:7d} {gtl:6d} {gthr:9d} {ggen:8d} {(100*gthr/gt if gt else 0):5.1f}%", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="*", help="Eval directories to scan (each globbed for *.eval)")
    ap.add_argument("--dirs-file", help="File listing eval dirs, one per line")
    ap.add_argument("--by", choices=["defense", "model", "both"], default="both")
    ap.add_argument("--list-ids", action="store_true", help="Print resumable throttle sample IDs (file::id)")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    dirs = list(args.dirs)
    if args.dirs_file:
        dirs += [l.strip() for l in open(args.dirs_file) if l.strip()]
    if not dirs:
        ap.error("provide dirs positionally or via --dirs-file")

    per_def, per_model, per_dm, throttle_ids, nfiles = scan(dirs, workers=args.workers)
    print(f"scanned {nfiles} .eval files across {len(dirs)} dirs", flush=True)

    if args.by in ("defense", "both"):
        _print_table("THROTTLE (resumable) by DEFENSE", per_def)
    if args.by in ("model", "both"):
        _print_table("THROTTLE (resumable) by MODEL", per_model)
    if args.by == "both":
        nz = {k: v for k, v in per_dm.items() if v[2] > 0}
        _print_table("DEFENSE x MODEL (nonzero throttle only)", nz)

    if args.list_ids:
        print("\n==== RESUMABLE THROTTLE SAMPLE IDS ====", flush=True)
        for key in sorted(throttle_ids):
            for ref in throttle_ids[key]:
                print(ref, flush=True)


if __name__ == "__main__":
    main()
