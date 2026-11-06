# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""LLM-based semantic checks for evaluation.

Provides llm_check(text, criterion) -> bool through inspect_ai's model API.
Results use majority voting (default N=3) and are cached by judge, vote count and prompt.

Inside the Inspect scorer, checks run in a worker thread (run_sync_with_judge) and
each judge call is sent back to the eval's event loop, sharing inspect_ai's
connection limits, retries and rate-limit handling with the eval. Called outside an
event loop (standalone scoring), each judge call runs in a fresh event loop.

Configuration via environment variables:
  LLM_CHECK_MODEL  — inspect_ai model id of the judge (provider/model). Required;
                     the runners set it from --judge-model.
  LLM_CHECK_CACHE_DIR — directory for persistent cache (default: None, in-memory only)
  LLM_CHECK_VOTES  — number of votes (default: 3, must be a positive odd integer)
"""

import asyncio
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

import anyio
import anyio.from_thread
import anyio.to_thread

logger = logging.getLogger(__name__)

_DEFAULT_VOTES = 3

_memory_cache: dict[str, bool] = {}
_thread = threading.local()


def _judge_model_id(model: Optional[str]) -> str:
    model_id = model or os.environ.get("LLM_CHECK_MODEL")
    if not model_id:
        raise RuntimeError(
            "llm_check: no judge model set. Pass --judge-model to the runner or set "
            "LLM_CHECK_MODEL to an inspect_ai model id (provider/model)."
        )
    return model_id


def _cache_key(prompt: str, model_id: str, num_votes: int) -> str:
    payload = json.dumps([model_id, num_votes, prompt])
    return hashlib.sha256(payload.encode()).hexdigest()


def _disk_cache_path(key: str) -> Optional[Path]:
    cache_dir = os.environ.get("LLM_CHECK_CACHE_DIR")
    if not cache_dir:
        return None
    p = Path(cache_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{key}.json"


def _read_cache(key: str) -> Optional[bool]:
    if key in _memory_cache:
        return _memory_cache[key]
    disk = _disk_cache_path(key)
    if disk and disk.exists():
        try:
            data = json.loads(disk.read_text())
            result = data["result"]
            _memory_cache[key] = result
            return result
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def _write_cache(key: str, result: bool, text: str, criterion: str):
    _memory_cache[key] = result
    disk = _disk_cache_path(key)
    if disk:
        disk.write_text(json.dumps({
            "criterion": criterion,
            "text_hash": hashlib.sha256(text.encode()).hexdigest(),
            "result": result,
        }))


async def _generate(model_id: str, prompt: str, memoize: bool) -> str:
    from inspect_ai.model import GenerateConfig, get_model

    judge = get_model(model_id, config=GenerateConfig(temperature=0, max_tokens=8), memoize=memoize)
    output = await judge.generate(prompt)
    return output.completion


def _single_call(model_id: str, prompt: str) -> bool:
    """Make a single judge call and return True if the answer starts with YES.

    Retries (throttling, transient errors) are handled by inspect_ai.
    """
    if getattr(_thread, "in_worker", False):
        text = anyio.from_thread.run(_generate, model_id, prompt, True)
    else:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            text = asyncio.run(_generate(model_id, prompt, False))
        else:
            raise RuntimeError(
                "llm_check was called on an event loop thread; call the checks through "
                "run_sync_with_judge()"
            )
    return text.strip().upper().startswith("YES")


async def run_sync_with_judge(fn, /, *args, **kwargs):
    """Run a synchronous function that may call llm_check from async code.

    fn runs in a worker thread; its judge calls run on the calling event loop.
    """
    def _call():
        _thread.in_worker = True
        try:
            return fn(*args, **kwargs)
        finally:
            _thread.in_worker = False

    return await anyio.to_thread.run_sync(_call)


def llm_check(text: str, criterion: str, model: Optional[str] = None) -> bool:
    """Evaluate whether text satisfies a yes/no criterion using an LLM.

    Returns True if the majority of N independent calls answer YES.

    Args:
        text: The content to evaluate (e.g., email body, document content).
        criterion: A yes/no question about the text. Must be phrased so that
            YES means the check passes (the condition is met).
        model: Override the judge's inspect_ai model id. Defaults to the
            LLM_CHECK_MODEL env var.

    Returns:
        True if the majority of LLM votes answer YES, False otherwise.
    """
    model_id = _judge_model_id(model)
    try:
        num_votes = int(os.environ.get("LLM_CHECK_VOTES", _DEFAULT_VOTES))
    except ValueError:
        raise ValueError("LLM_CHECK_VOTES must be a positive odd integer") from None
    if num_votes <= 0 or num_votes % 2 == 0:
        raise ValueError("LLM_CHECK_VOTES must be a positive odd integer")

    prompt = (
        "You are a precise text analysis tool. Answer the following question "
        "about the text below with exactly YES or NO. No explanation.\n\n"
        f"Question: {criterion}\n\n"
        f"Text:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Answer (YES or NO):"
    )

    key = _cache_key(prompt, model_id, num_votes)
    cached = _read_cache(key)
    if cached is not None:
        return cached

    yes_count = 0
    no_count = 0
    threshold = num_votes // 2 + 1

    for i in range(num_votes):
        if _single_call(model_id, prompt):
            yes_count += 1
        else:
            no_count += 1
        if yes_count >= threshold:
            break
        if no_count >= threshold:
            break

    result = yes_count >= threshold

    _write_cache(key, result, text, criterion)
    return result


def clear_cache():
    """Clear the in-memory cache (disk cache is preserved)."""
    _memory_cache.clear()
