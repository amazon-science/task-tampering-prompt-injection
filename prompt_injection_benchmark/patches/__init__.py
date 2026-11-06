# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Bedrock provider used for the experiments in the paper.

All experiments ran on inspect_ai commit ee0dfdef8 with a small modification to
`inspect_ai/model/_providers/bedrock.py` (the diff ships next to this file as
`bedrock_ee0dfdef8.diff`). The modification affects every Bedrock run, not only
Extended Thinking:

  1. A tool-calling assistant turn is sent as ONE Converse message holding the turn's
     text/reasoning content followed by all of its toolUse blocks (stock ee0dfdef8 sends
     one message per tool call and drops the turn's text). The NO_CONTENT placeholder
     text is removed from such turns.
  2. The reasoningContent `signature` is parsed and replayed.
  3. Reasoning-history emulation (<think> tags) is disabled.

`apply_bedrock_patches()` installs the modified module (`_bedrock_ee0dfdef8.py`, MIT-licensed
inspect_ai code; see THIRD_PARTY_NOTICES.md) in place of the stock provider. It only does so
when the installed provider file is byte-identical to stock ee0dfdef8; if it is already the
modified file it does nothing, and for any other inspect_ai version it warns and leaves
inspect_ai untouched. The runners call it at import time; set PIB_NO_BEDROCK_PATCH=1 to opt out.
It only changes how `bedrock/...` models are called; other inspect_ai providers are unaffected.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import warnings
from pathlib import Path

_MODULE = "inspect_ai.model._providers.bedrock"
_PATCHED_FILE = Path(__file__).with_name("_bedrock_ee0dfdef8.py")
_STOCK_SHA256 = "9780ddea9bce09fa53cb97f54026867921b9ec939aacfc53a2065a1d03d1fc74"
_PATCHED_SHA256 = "6d77c2b9b1aed17ad13379557b667af17ce593758aef3ce3c6d4e2384bf0889d"

_state: str | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_bedrock_patches() -> str:
    """Install the modified Bedrock provider.

    Returns one of "installed", "already-patched", "disabled", "skipped".
    """
    global _state
    if _state is not None:
        return _state
    if os.environ.get("PIB_NO_BEDROCK_PATCH"):
        _state = "disabled"
        return _state

    spec = importlib.util.find_spec(_MODULE)
    installed = Path(spec.origin) if spec and spec.origin else None
    digest = _sha256(installed) if installed and installed.exists() else None

    if digest == _PATCHED_SHA256:
        _state = "already-patched"
    elif digest != _STOCK_SHA256:
        warnings.warn(
            "installed inspect_ai is not commit ee0dfdef8; the Bedrock provider modification "
            "was NOT applied."
        )
        _state = "skipped"
    elif _MODULE in sys.modules:
        warnings.warn(f"{_MODULE} was imported before apply_bedrock_patches(); not applied.")
        _state = "skipped"
    else:
        assert _sha256(_PATCHED_FILE) == _PATCHED_SHA256, "vendored bedrock provider was modified"
        import inspect_ai.model._providers

        patched = importlib.util.spec_from_file_location(_MODULE, _PATCHED_FILE)
        mod = importlib.util.module_from_spec(patched)
        sys.modules[_MODULE] = mod
        patched.loader.exec_module(mod)
        _state = "installed"
    return _state
