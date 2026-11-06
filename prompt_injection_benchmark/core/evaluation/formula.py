# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""Boolean formula parser and evaluator for check results."""

import re
from typing import Dict


def evaluate_formula(formula: str, results: Dict[str, bool]) -> bool:
    """Evaluate a boolean formula string against check results.

    Supports: AND, OR, NOT, parentheses, check IDs.

    Examples:
        "E1_U1 AND E1_U2" with {"E1_U1": True, "E1_U2": False} -> False
        "E1_I1 OR E1_I2" with {"E1_I1": False, "E1_I2": True} -> True
        "NOT E1_I3" with {"E1_I3": True} -> False
    """

    expr = formula

    ids = sorted(results.keys(), key=len, reverse=True)
    for check_id in ids:
        expr = re.sub(r'\b' + re.escape(check_id) + r'\b',
                      'True' if results[check_id] else 'False', expr)

    expr = expr.replace(' AND ', ' and ')
    expr = expr.replace(' OR ', ' or ')
    expr = expr.replace('NOT ', 'not ')

    try:
        safe_tokens = {'True', 'False', 'and', 'or', 'not', '(', ')'}
        tokens = re.findall(r'\w+|[()]', expr)
        for token in tokens:
            if token not in safe_tokens:
                raise ValueError(f"Unsafe token in formula: {token}")
        return bool(eval(expr))
    except Exception:
        return False
