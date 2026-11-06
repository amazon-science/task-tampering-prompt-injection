# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""Trajectory text formatting for the LLM-judge scorer: truncates tool results
and marks the injected span."""
import json


RESULT_TRUNCATE = 300


def _injection_phrases(injection_text: str) -> list[str]:
    """Build phrase variants for injection matching.

    Produces raw, JSON-escaped, and Python-repr-escaped forms to handle
    tool results serialized via either str(dict) or json.dumps(dict).
    """
    phrases = []
    seen = set()
    for line in injection_text.strip().split("\n"):
        line = line.strip()
        if len(line) > 15:
            if line not in seen:
                phrases.append(line)
                seen.add(line)
            json_esc = json.dumps(line, ensure_ascii=False)[1:-1]
            if json_esc != line and json_esc not in seen:
                phrases.append(json_esc)
                seen.add(json_esc)
            py_esc = line.replace("'", "\\'")
            if py_esc != line and py_esc not in seen:
                phrases.append(py_esc)
                seen.add(py_esc)
    return phrases


def _escape_variants(s: str) -> list[str]:
    """Return the raw string plus its JSON- and Python-repr-escaped forms.

    Tool results are serialized via either str(dict) or json.dumps(dict), and some
    injection payloads themselves contain literal backslash-escapes, so the injection
    text can appear in the result under any of these forms.
    """
    out = [s]
    seen = {s}
    json_esc = json.dumps(s, ensure_ascii=False)[1:-1]
    if json_esc not in seen:
        out.append(json_esc)
        seen.add(json_esc)
    py_esc = s.replace("'", "\\'")
    if py_esc not in seen:
        out.append(py_esc)
        seen.add(py_esc)
    return out


def _mark(text: str, start: int, end: int) -> str:
    """Wrap text[start:end] in injection markers."""
    return (
        text[:start]
        + ">>>INJECTION_START>>>\n"
        + text[start:end]
        + "\n<<<INJECTION_END<<<"
        + text[end:]
    )


def _highlight_injection(text: str, full_injection: str, phrases: list[str]) -> tuple[str, bool]:
    """Mark an injection using a full-block match or a region spanning phrase matches.
    """
    lower = text.lower()
    clean_inj = full_injection.strip()

    for cand in _escape_variants(clean_inj):
        if len(cand) < 1:
            continue
        idx = lower.find(cand.lower())
        if idx >= 0:
            return _mark(text, idx, idx + len(cand)), True

    spans: list[tuple[int, int]] = []
    for phrase in phrases:
        p = phrase.lower()
        if not p:
            continue
        start = 0
        while True:
            i = lower.find(p, start)
            if i < 0:
                break
            spans.append((i, i + len(phrase)))
            start = i + 1

    if not spans:
        return text, False

    spans.sort()
    GAP = 8
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1] + GAP:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    best_start, best_end = max(merged, key=lambda se: se[1] - se[0])
    return _mark(text, best_start, best_end), True


def _truncate_text(text: str, limit: int, full_injection: str, phrases: list[str]) -> tuple[str, bool]:
    """Truncate text, preserving injection context with markers."""
    has_injection = any(p.lower() in text.lower() for p in phrases)
    if has_injection:
        marked, _ = _highlight_injection(text, full_injection, phrases)
        return marked, True
    if len(text) <= limit:
        return text, False
    return text[:limit] + "...[truncated]", False
