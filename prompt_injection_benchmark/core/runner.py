# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Result summaries for benchmark runs.

Aggregates the programmatic scorer's per-sample metadata (task_complete,
attack_success, quadrant) into rates by primitive and risk category. Used by
scripts.run_eval to print a summary after each run.
"""

from typing import List

from inspect_ai.log import EvalLog


def _extract_sample_metadata(log: EvalLog) -> dict:
    """Extract scorer metadata from an EvalLog's sample results."""
    meta = {}
    try:
        if log.samples and len(log.samples) > 0:
            sample = log.samples[0]
            if sample.scores:
                for scorer_name, score_obj in sample.scores.items():
                    if hasattr(score_obj, 'metadata') and score_obj.metadata:
                        meta = dict(score_obj.metadata)
                        break
    except Exception:
        pass
    return meta


def analyze_results(logs: List[EvalLog]) -> dict:
    """
    Analyze benchmark results using scorer metadata (quadrant, task_complete, attack_success).

    Args:
        logs: Evaluation logs from eval()

    Returns:
        Dict with computed metrics.
    """
    from collections import defaultdict

    details = []
    error_count = 0

    for log in logs:
        task_meta = log.eval.metadata or {}
        status = log.status

        if status == "error":
            error_count += 1
            details.append({
                "test_id": task_meta.get("test_case_id", log.eval.task),
                "variation_id": task_meta.get("variation_id", "original"),
                "primitive": task_meta.get("primitive", "compound"),
                "status": "error",
                "error": getattr(log, "error", None),
                "task_complete": None,
                "attack_success": None,
                "quadrant": "ERROR",
            })
            continue

        sample_meta = _extract_sample_metadata(log)

        task_complete = sample_meta.get("task_complete", False)
        attack_success = sample_meta.get("attack_success", False)
        quadrant = sample_meta.get("quadrant", "UNKNOWN")

        details.append({
            "test_id": task_meta.get("test_case_id", log.eval.task),
            "variation_id": task_meta.get("variation_id", "original"),
            "primitive": task_meta.get("primitive", "compound"),
            "risk_category": task_meta.get("risk_category", ""),
            "status": status,
            "task_complete": task_complete,
            "task_robust": sample_meta.get("task_robust", False),
            "attack_success": attack_success,
            "attack_partial": sample_meta.get("attack_partial", False),
            "quadrant": quadrant,
            "task_checks": sample_meta.get("task_checks", {}),
            "attack_checks": sample_meta.get("attack_checks", {}),
        })

    completed = [d for d in details if d["status"] != "error"]
    total = len(completed)

    if total == 0:
        return {"total": 0, "errors": error_count, "details": details}

    tc = sum(1 for d in completed if d["task_complete"])
    atk = sum(1 for d in completed if d["attack_success"])
    ss = sum(1 for d in completed if d["quadrant"] == "SECURE_SUCCESS")

    quadrant_counts = defaultdict(int)
    for d in completed:
        quadrant_counts[d["quadrant"]] += 1

    by_prim = defaultdict(lambda: {"total": 0, "task_complete": 0, "attack_success": 0, "secure_success": 0})
    for d in completed:
        p = d["primitive"]
        by_prim[p]["total"] += 1
        if d["task_complete"]:
            by_prim[p]["task_complete"] += 1
        if d["attack_success"]:
            by_prim[p]["attack_success"] += 1
        if d["quadrant"] == "SECURE_SUCCESS":
            by_prim[p]["secure_success"] += 1

    by_risk = defaultdict(lambda: {"total": 0, "task_complete": 0, "attack_success": 0, "secure_success": 0})
    for d in completed:
        r = d.get("risk_category", "unknown")
        by_risk[r]["total"] += 1
        if d["task_complete"]:
            by_risk[r]["task_complete"] += 1
        if d["attack_success"]:
            by_risk[r]["attack_success"] += 1
        if d["quadrant"] == "SECURE_SUCCESS":
            by_risk[r]["secure_success"] += 1

    return {
        "total": total,
        "errors": error_count,
        "task_completion_rate": tc / total,
        "attack_success_rate": atk / total,
        "secure_success_rate": ss / total,
        "quadrant_counts": dict(quadrant_counts),
        "by_primitive": dict(by_prim),
        "by_risk": dict(by_risk),
        "details": details,
    }


def print_results(results: dict):
    """Print formatted benchmark results."""
    total = results.get("total", 0)
    errors = results.get("errors", 0)

    print(f"\n{'='*70}")
    print("BENCHMARK RESULTS")
    print(f"{'='*70}")

    if total == 0:
        print(f"\nNo completed results. Errors: {errors}")
        return

    print(f"\n  Total completed: {total}" + (f"  (errors: {errors})" if errors else ""))
    print(f"  Task Completion Rate: {results['task_completion_rate']:.1%}")
    print(f"  Attack Success Rate:  {results['attack_success_rate']:.1%}  (lower is better)")
    print(f"  Secure Success Rate:  {results['secure_success_rate']:.1%}  (higher is better)")

    qc = results.get("quadrant_counts", {})
    print(f"\n  Quadrants:")
    for q in ["SECURE_SUCCESS", "SECURE_FAILURE", "COMPROMISED_SUCCESS", "COMPROMISED_FAILURE"]:
        c = qc.get(q, 0)
        print(f"    {q:<25} {c:>3} ({c/total:.1%})")

    by_prim = results.get("by_primitive", {})
    if by_prim:
        PRIM_ORDER = ["compound", "b(U)", "b(s)", "b(A)", "b(T)", "b(O)", "b(pi)"]
        PRIM_LABELS = {
            "b(U)": "Objective", "b(s)": "Situation", "b(A)": "Capability",
            "b(T)": "Consequence", "b(O)": "Interpretation", "b(pi)": "Behavioral",
            "compound": "Compound (orig)",
        }
        print(f"\n{'='*70}")
        print("BY PRIMITIVE")
        print(f"{'='*70}")
        print(f"  {'Prim':<8} {'Label':<18} {'ASR':>12} {'TCR':>12} {'SSR':>12}")
        for p in PRIM_ORDER:
            if p not in by_prim:
                continue
            m = by_prim[p]
            t = m["total"]
            label = PRIM_LABELS.get(p, p)
            print(f"  {p:<8} {label:<18} {m['attack_success']:>2}/{t:<2} = {m['attack_success']/t:.1%}  "
                  f"{m['task_complete']:>2}/{t:<2} = {m['task_complete']/t:.1%}  "
                  f"{m['secure_success']:>2}/{t:<2} = {m['secure_success']/t:.1%}")

    by_risk = results.get("by_risk", {})
    if by_risk and len(by_risk) > 1:
        print(f"\n{'='*70}")
        print("BY RISK CATEGORY")
        print(f"{'='*70}")
        print(f"  {'Category':<25} {'ASR':>12} {'TCR':>12} {'SSR':>12}")
        for r, m in sorted(by_risk.items()):
            t = m["total"]
            print(f"  {r:<25} {m['attack_success']:>2}/{t:<2} = {m['attack_success']/t:.1%}  "
                  f"{m['task_complete']:>2}/{t:<2} = {m['task_complete']/t:.1%}  "
                  f"{m['secure_success']:>2}/{t:<2} = {m['secure_success']/t:.1%}")

    details = [d for d in results.get("details", []) if d["status"] != "error"]
    if details:
        print(f"\n{'='*70}")
        print("PER-TEST RESULTS")
        print(f"{'='*70}")
        print(f"  {'Test':<8} {'Var':<10} {'Prim':<8} {'Task':<6} {'Atk':<5} {'Quadrant'}")
        print(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*5} {'-'*22}")
        for d in sorted(details, key=lambda x: (x["test_id"], x["variation_id"])):
            task = "PASS" if d["task_complete"] else "FAIL"
            atk = "YES" if d["attack_success"] else "NO"
            print(f"  {d['test_id']:<8} {d['variation_id']:<10} {d['primitive']:<8} {task:<6} {atk:<5} {d['quadrant']}")

    error_details = [d for d in results.get("details", []) if d["status"] == "error"]
    if error_details:
        print(f"\n{'='*70}")
        print(f"ERRORS ({len(error_details)})")
        print(f"{'='*70}")
        for d in error_details:
            print(f"  {d['test_id']:<8} {d['variation_id']:<10} {d.get('error', 'unknown error')}")

    print(f"\n{'='*70}")
