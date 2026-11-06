# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Undefended benchmark evaluation runner.

For one model (--model) and each environment, runs every attack variation of every
case through the benchmark runner, with no defense applied. Logs go to $PIB_OUTPUT_DIR/attack_evaluation/evals/<model>/<env>/
(PIB_OUTPUT_DIR defaults to ./pib_results).

Usage:
  python -m prompt_injection_benchmark.scripts.run_eval --model <provider/model> --dry-run
  python -m prompt_injection_benchmark.scripts.run_eval --model <provider/model> --judge-model <provider/model> \
      --env productivity
  python -m prompt_injection_benchmark.scripts.run_eval --model <provider/model> --judge-model <provider/model> \
      --env productivity --case E1
"""
from __future__ import annotations

from prompt_injection_benchmark.patches import apply_bedrock_patches

apply_bedrock_patches()

import argparse
import json
import os
import sys
from pathlib import Path

EXPERIMENT_DIR = Path(os.environ.get("PIB_OUTPUT_DIR", "pib_results")) / "attack_evaluation"
VARIATIONS_DIR = Path(__file__).resolve().parent.parent / "test_cases" / "variations"

def get_sample_counts(output_dir: str) -> dict[str, int]:
    """Scan existing .eval files and count attempts per sample ID.

    Counts both completed samples (have samples/ entries) and start-only
    files (only _journal/start.json) where the eval never finished.
    """
    import zipfile
    from collections import defaultdict
    counts: dict[str, int] = defaultdict(int)
    out_path = Path(output_dir)
    if not out_path.exists():
        return counts
    for f in out_path.glob("*.eval"):
        try:
            with zipfile.ZipFile(f) as zf:
                names = zf.namelist()
                sample_files = [n for n in names if n.startswith("samples/")]
                if sample_files:
                    for sf in sample_files:
                        sample = json.loads(zf.read(sf))
                        sid = sample.get("id", "")
                        if sid:
                            counts[sid] += 1
                elif "_journal/start.json" in names:
                    start = json.loads(zf.read("_journal/start.json"))
                    for sid in start.get("eval", {}).get("dataset", {}).get("sample_ids", []):
                        counts[sid] += 1
        except Exception:
            pass
    return counts


def get_completed_sample_ids(output_dir: str) -> set:
    """Scan existing .eval files for completed sample IDs.
    A sample is complete only if ProgrammaticScorer has non-null task_complete
    and attack_success."""
    import zipfile
    completed = set()
    out_path = Path(output_dir)
    if not out_path.exists():
        return completed
    for f in out_path.glob("*.eval"):
        try:
            with zipfile.ZipFile(f) as zf:
                for sf in [n for n in zf.namelist() if n.startswith("samples/")]:
                    sample = json.loads(zf.read(sf))
                    sid = sample.get("id", "")
                    if not sid:
                        continue
                    scores = sample.get("scores", {})
                    ps = scores.get("ProgrammaticScorer", {})
                    if isinstance(ps, dict):
                        meta = ps.get("metadata", {})
                        if meta.get("task_complete") is not None and meta.get("attack_success") is not None:
                            completed.add(sid)
        except Exception:
            pass
    return completed


def _limit_per_primitive(variation_ids: list[str], max_per_primitive: int) -> list[str]:
    """Limit to N variation IDs per primitive prefix."""
    from collections import defaultdict
    import re
    counts: dict[str, int] = defaultdict(int)
    result = []
    for vid in variation_ids:
        if vid == "original":
            result.append(vid)
            continue
        prim = re.sub(r'_\d+$', '', vid)
        if counts[prim] < max_per_primitive:
            result.append(vid)
            counts[prim] += 1
    return result


def run_eval(env: str, model: str, case_filter: str | None = None,
             temperature: float = 0.0, max_connections: int | None = None,
             max_tasks: int | None = None, max_samples: int | None = None,
             retry_on_error: int | None = None, fail_on_error: bool | None = None,
             resume: bool = False, dry_run: bool = False,
             max_per_primitive: int | None = None, max_retries: int | None = None,
             variations_dir: Path | None = None, output_suffix: str | None = None,
             no_injection: bool = False):
    """Run evaluations for one model × environment.

    Batch pending cases in one eval() call with max_tasks concurrency.
    """
    from prompt_injection_benchmark.core.runner import analyze_results, print_results
    from prompt_injection_benchmark.core.tasks import load_benchmark_tasks
    from inspect_ai import eval
    from inspect_ai.model import GenerateConfig, get_model

    var_dir = (variations_dir or VARIATIONS_DIR) / env
    if not var_dir.exists():
        print(f"ERROR: No variations directory: {var_dir}", file=sys.stderr)
        return

    cases = sorted(f for f in var_dir.glob("*.json"))
    if case_filter:
        cases = [f for f in cases if f.stem == case_filter]

    if not cases:
        print(f"No variation files found for env={env}" +
              (f", case={case_filter}" if case_filter else ""))
        return

    model_short = model.split("/")[-1].split(":")[0].replace(".", "_")
    model_dir = model_short
    if not output_suffix and no_injection:
        output_suffix = "no_injection"
    env_dir = f"{env}_{output_suffix}" if output_suffix else env
    output_dir = str(EXPERIMENT_DIR / "evals" / model_dir / env_dir)

    completed_ids = set()
    sample_counts: dict[str, int] = {}
    if resume:
        completed_ids = get_completed_sample_ids(output_dir)
        if max_retries is not None:
            sample_counts = get_sample_counts(output_dir)
            exhausted = sum(1 for sid, cnt in sample_counts.items()
                           if sid not in completed_ids and cnt >= max_retries)
            print(f"  Resume: {len(completed_ids)} completed, {exhausted} exhausted (>={max_retries} attempts)")
        else:
            print(f"  Resume: {len(completed_ids)} samples already completed")

    print(f"\n{'='*60}")
    print(f"Attack evaluation (no defense){' [DRY RUN]' if dry_run else ''}")
    print(f"  Model: {model}")
    print(f"  Env:   {env}")
    print(f"  Cases: {len(cases)}")
    print(f"  Output: {output_dir}")
    print(f"{'='*60}\n")

    total_pending = 0
    all_tasks = []
    for case_file in cases:
        case_id = case_file.stem
        variation_filter = None

        tc = json.loads(case_file.read_text())["test_cases"][0]
        case_id_real = tc.get("id", case_file.stem)
        all_var_ids = [v["id"] for v in tc.get("injection", {}).get("variations", [])
                       if v.get("id") and v.get("viable", True)]

        if no_injection:
            all_var_ids = ["original"]

        if max_per_primitive is not None:
            all_var_ids = _limit_per_primitive(all_var_ids, max_per_primitive)

        if resume and (completed_ids or sample_counts):
            pending = []
            for vid in all_var_ids:
                if vid == "original":
                    sample_id = case_id_real
                else:
                    sample_id = f"{case_id_real}_{vid}"
                if sample_id in completed_ids:
                    continue
                if max_retries is not None and sample_counts and sample_counts.get(sample_id, 0) >= max_retries:
                    continue
                pending.append(vid)

            if not pending:
                print(f"  {case_id}: SKIP (all done)")
                continue
            variation_filter = pending
        elif max_per_primitive is not None or no_injection:
            variation_filter = all_var_ids

        if variation_filter is not None:
            total_pending += len(variation_filter)
            print(f"  {case_id}: {len(variation_filter)} samples {variation_filter}")
        else:
            total_pending += len(all_var_ids)
            print(f"  {case_id}: all {len(all_var_ids)} variations")

        if dry_run:
            continue

        tasks = load_benchmark_tasks(
            test_file=str(case_file),
            no_injection=no_injection,
            variation_filter=variation_filter,
        )
        all_tasks.extend(tasks)

    if dry_run:
        print(f"\n  DRY RUN SUMMARY: {total_pending} samples would be run")
        return

    if not all_tasks:
        print("  Nothing to run.")
        return

    print(f"\n  Running {len(all_tasks)} tasks in batch...")

    gen_config_kwargs = {}
    if temperature is not None:
        gen_config_kwargs["temperature"] = temperature
    if max_connections is not None:
        gen_config_kwargs["max_connections"] = max_connections

    if gen_config_kwargs:
        model_obj = get_model(model, config=GenerateConfig(**gen_config_kwargs))
    else:
        model_obj = model

    eval_kwargs = dict(
        tasks=all_tasks,
        model=model_obj,
        log_dir=output_dir,
    )
    if max_tasks is not None:
        eval_kwargs["max_tasks"] = max_tasks
    if max_samples is not None:
        eval_kwargs["max_samples"] = max_samples
    if retry_on_error is not None:
        eval_kwargs["retry_on_error"] = retry_on_error
    if fail_on_error is not None:
        eval_kwargs["fail_on_error"] = fail_on_error

    try:
        logs = eval(**eval_kwargs)
        if logs:
            results = analyze_results(logs)
            print_results(results)
    except Exception as e:
        print(f"  ERROR: {e}")


def _load_config() -> dict:
    """Load config_eval.yaml (environments, eval settings)."""
    import yaml
    return yaml.safe_load((Path(__file__).parent / "config_eval.yaml").read_text())


def main():
    parser = argparse.ArgumentParser(description="Run the benchmark without a defense")
    parser.add_argument("--env", help="Single environment to run (default: all from config)")
    parser.add_argument("--model", required=True, help="inspect_ai model id of the agent (provider/model)")
    parser.add_argument("--judge-model", default=os.environ.get("LLM_CHECK_MODEL"),
                        help="inspect_ai model id of the scorer's LLM judge (provider/model; "
                             "default: $LLM_CHECK_MODEL)")
    parser.add_argument("--case", help="Single case ID to run")
    parser.add_argument("--resume", action="store_true", help="Skip samples already completed")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without executing")
    parser.add_argument("--max-tasks", type=int, default=None, help="Max parallel tasks (overrides config)")
    parser.add_argument("--max-per-primitive", type=int, default=None,
                        help="Max samples per primitive per case (default: all)")
    parser.add_argument("--max-retries", type=int, default=None,
                        help="Skip samples attempted this many times without scoring")
    parser.add_argument("--variations-dir", type=str, default=None,
                        help="Override variations directory (default: <package>/test_cases/variations)")
    parser.add_argument("--output-suffix", type=str, default=None,
                        help="Suffix for output env directory (e.g. 'baseline' -> evals/<model>/<env>_baseline; "
                             "--no-injection defaults to 'no_injection')")
    parser.add_argument("--no-injection", action="store_true",
                        help="Run without injections (baseline mode); output goes to evals/<model>/<env>_no_injection")
    args = parser.parse_args()

    config = _load_config()

    models = [args.model]
    _bad = [m for m in (args.model, args.judge_model) if m and "/" not in m]
    if _bad:
        parser.error(f"models must be full inspect_ai model ids (provider/model), got {_bad}")
    if args.judge_model:
        os.environ["LLM_CHECK_MODEL"] = args.judge_model
    elif not args.dry_run:
        parser.error("--judge-model (or LLM_CHECK_MODEL) is required: some checks ask an LLM judge")
    envs = [args.env] if args.env else config["environments"]
    temperature = config.get("temperature", 0.0)
    max_connections = config.get("max_connections")
    max_tasks = args.max_tasks if args.max_tasks is not None else config.get("max_tasks")
    max_samples = config.get("max_samples")
    retry_on_error = config.get("retry_on_error")
    fail_on_error = config.get("fail_on_error")

    for model in models:
        for env in envs:
            run_eval(
                env=env,
                model=model,
                case_filter=args.case,
                temperature=temperature,
                max_connections=max_connections,
                max_tasks=max_tasks,
                max_samples=max_samples,
                retry_on_error=retry_on_error,
                fail_on_error=fail_on_error,
                resume=args.resume,
                dry_run=args.dry_run,
                max_per_primitive=args.max_per_primitive,
                max_retries=args.max_retries,
                variations_dir=Path(args.variations_dir) if args.variations_dir else None,
                output_suffix=args.output_suffix,
                no_injection=args.no_injection,
            )


if __name__ == "__main__":
    main()
