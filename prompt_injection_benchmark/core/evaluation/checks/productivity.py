# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""Check registry for productivity environment test cases.

Each case's checks live in case_helpers/productivity/<CASE>.py, which exports a CASE dict
mapping the case id to its checks and formulas.
"""

import importlib
from pathlib import Path as _Path

PRODUCTIVITY_CHECKS = {}

_helpers_dir = _Path(__file__).parent / "case_helpers" / "productivity"
if _helpers_dir.is_dir():
    for _f in sorted(_helpers_dir.glob("*.py")):
        if _f.name.startswith("_"):
            continue
        try:
            _mod = importlib.import_module(
                f".case_helpers.productivity.{_f.stem}", package=__package__
            )
            if hasattr(_mod, "CASE"):
                PRODUCTIVITY_CHECKS.update(_mod.CASE)
        except Exception as _e:
            import warnings
            warnings.warn(f"Failed to load case helper {_f.name}: {_e}")
