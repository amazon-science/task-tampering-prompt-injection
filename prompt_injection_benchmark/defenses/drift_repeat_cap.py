# Copyright (c) 2026 Hao Li
# Modifications Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT
# See third_party/licenses/DRIFT.LICENSE.

"""Per-call repeat cap for drift_full_guided.

Calls are keyed by function name and JSON-serialized arguments. Calls with
REPEAT_RETRY_LIMIT + 1 prior occurrences are dropped. Counts use earlier turns
only, so same-turn duplicates are retained; gate-refused calls are excluded.
A turn with no remaining tool calls ends the run.
"""
import json
from collections import Counter
from typing import Callable, List, Optional

REPEAT_RETRY_LIMIT = 4


def call_signature(tool_call) -> tuple:
    """Return the repeat key: function name and JSON-serialized arguments."""
    return (tool_call.function, json.dumps(tool_call.arguments))


def cap_repeat_calls(history, message, is_refused: Callable[[str], bool] = lambda text: False,
                     log: Optional[List[dict]] = None, limit: int = REPEAT_RETRY_LIMIT):
    """`message` without the calls that already ran `limit` + 1 times in `history`
    (tool_calls None if none are left). Dropped calls are appended to `log`."""
    if not message.tool_calls:
        return message
    refused = {m.tool_call_id for m in history if m.role == "tool" and is_refused(m.text)}
    runs = Counter(call_signature(tc) for m in history if m.role == "assistant"
                   for tc in (m.tool_calls or []) if tc.id not in refused)
    kept = [tc for tc in message.tool_calls if runs[call_signature(tc)] <= limit]
    if len(kept) == len(message.tool_calls):
        return message
    if log is not None:
        log.append({
            "dropped": [{"function": tc.function, "arguments": tc.arguments}
                        for tc in message.tool_calls if tc not in kept],
            "kept": len(kept),
            "limit": limit,
        })
    return message.model_copy(update={"tool_calls": kept or None})
