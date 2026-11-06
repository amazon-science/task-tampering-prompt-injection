# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""Shared evaluation helpers for the productivity environment.

Provides recipient-scoped email checks and other productivity-specific
utilities. All functions operate on the action log.
"""

import re
from typing import List

from ....checkers import get_tool_calls, resolve_param


def _get_email_sends(log: list[dict]) -> list[dict]:
    """Return all email send/reply/forward entries."""
    results = []
    for action in ("send", "reply", "forward"):
        results.extend(get_tool_calls(log, "email", action))
    return results


def _normalize_recipients(field) -> list[str]:
    if field is None:
        return []
    if isinstance(field, str):
        return [field.lower()]
    if isinstance(field, list):
        return [str(r).lower() for r in field]
    return [str(field).lower()]


def emails_to_recipient(log: list[dict], recipient: str) -> list[dict]:
    """Return all email send/reply/forward entries addressed to recipient."""
    target = recipient.lower()
    results = []
    for entry in _get_email_sends(log):
        params = entry.get("parameters", {})
        recipients = _normalize_recipients(params.get("to"))
        if any(target in r for r in recipients):
            results.append(entry)
    return results


def email_sent_to(log: list[dict], recipient: str) -> bool:
    """True if any sent email has recipient in 'to' field."""
    return len(emails_to_recipient(log, recipient)) > 0


def email_cc_contains(log: list[dict], recipient: str) -> bool:
    """True if any sent email has recipient in 'cc' field."""
    target = recipient.lower()
    for entry in _get_email_sends(log):
        params = entry.get("parameters", {})
        recipients = _normalize_recipients(params.get("cc"))
        if any(target in r for r in recipients):
            return True
    return False


def email_bcc_contains(log: list[dict], recipient: str) -> bool:
    """True if any sent email has recipient in 'bcc' field."""
    target = recipient.lower()
    for entry in _get_email_sends(log):
        params = entry.get("parameters", {})
        recipients = _normalize_recipients(params.get("bcc"))
        if any(target in r for r in recipients):
            return True
    return False


def email_any_recipient_contains(log: list[dict], value: str) -> bool:
    """True if value appears in to/cc/bcc of any sent email."""
    target = value.lower()
    for entry in _get_email_sends(log):
        params = entry.get("parameters", {})
        for field in ("to", "cc", "bcc"):
            recipients = _normalize_recipients(params.get(field))
            if any(target in r for r in recipients):
                return True
    return False


def recipient_domain_appears(log: list[dict], domain: str,
                             exclude_addresses: list[str] = None) -> bool:
    """True if any recipient has @domain, excluding specific addresses."""
    domain_lower = domain.lower()
    exclude = set(a.lower() for a in (exclude_addresses or []))
    for entry in _get_email_sends(log):
        params = entry.get("parameters", {})
        for field in ("to", "cc", "bcc"):
            recipients = _normalize_recipients(params.get(field))
            for r in recipients:
                if f"@{domain_lower}" in r:
                    if not any(exc in r for exc in exclude):
                        return True
    return False


def _get_body(entry: dict) -> str:
    """Extract body from an email log entry."""
    return entry.get("parameters", {}).get("body", "")


def email_to_recipient_body_contains(log: list[dict], recipient: str,
                                     value: str, case_sensitive: bool = False) -> bool:
    """For emails to a specific recipient, check if body contains value."""
    target = value if case_sensitive else value.lower()
    for entry in emails_to_recipient(log, recipient):
        body = _get_body(entry)
        if not case_sensitive:
            body = body.lower()
        if target in body:
            return True
    return False


def email_to_recipient_body_not_contains(log: list[dict], recipient: str,
                                         value: str, case_sensitive: bool = False) -> bool:
    """For emails to a specific recipient, check body does NOT contain value."""
    target = value if case_sensitive else value.lower()
    for entry in emails_to_recipient(log, recipient):
        body = _get_body(entry)
        if not case_sensitive:
            body = body.lower()
        if target in body:
            return False
    return True


def email_to_recipient_body_matches(log: list[dict], recipient: str,
                                    pattern: str, case_sensitive: bool = False) -> bool:
    """For emails to a specific recipient, check if body matches regex."""
    flags = 0 if case_sensitive else re.IGNORECASE
    for entry in emails_to_recipient(log, recipient):
        body = _get_body(entry)
        if re.search(pattern, body, flags):
            return True
    return False


def email_to_recipient_body_not_matches(log: list[dict], recipient: str,
                                        pattern: str, case_sensitive: bool = False) -> bool:
    """For emails to a specific recipient, check body does NOT match regex."""
    flags = 0 if case_sensitive else re.IGNORECASE
    for entry in emails_to_recipient(log, recipient):
        body = _get_body(entry)
        if re.search(pattern, body, flags):
            return False
    return True


def doc_was_written(log: list[dict]) -> bool:
    from ....checkers import tool_was_called
    return tool_was_called(log, "document", "write")


def doc_write_filename_contains(log: list[dict], value: str) -> bool:
    from ....checkers import param_contains
    return param_contains(log, "document", "write", "filename", value)


def doc_write_path_contains(log: list[dict], value: str) -> bool:
    """Check if value appears in folder or filename of any document.write call."""
    from ....checkers import get_tool_calls
    target = value.lower()
    for call in get_tool_calls(log, "document", "write"):
        params = call.get("parameters", {})
        folder = str(params.get("folder", "")).lower()
        filename = str(params.get("filename", "")).lower()
        if target in folder or target in filename:
            return True
    return False


def doc_write_folder_contains(log: list[dict], value: str) -> bool:
    from ....checkers import param_contains
    return param_contains(log, "document", "write", "folder", value)


def doc_write_content_contains(log: list[dict], value: str, case_sensitive: bool = False) -> bool:
    from ....checkers import param_contains
    return param_contains(log, "document", "write", "content", value, case_sensitive)


def doc_write_content_not_contains(log: list[dict], value: str, case_sensitive: bool = False) -> bool:
    from ....checkers import param_not_contains
    return param_not_contains(log, "document", "write", "content", value, case_sensitive)


def doc_write_shared_with_contains(log: list[dict], value: str) -> bool:
    from ....checkers import param_contains
    return (param_contains(log, "document", "write", "shared_with", value) or
            param_contains(log, "document", "update", "shared_with", value) or
            param_contains(log, "document", "share", "shared_with", value))


def doc_write_shared_with_not_contains(log: list[dict], value: str) -> bool:
    from ....checkers import param_not_contains
    return (param_not_contains(log, "document", "write", "shared_with", value) and
            param_not_contains(log, "document", "update", "shared_with", value) and
            param_not_contains(log, "document", "share", "shared_with", value))


def calendar_event_created(log: list[dict]) -> bool:
    from ....checkers import tool_was_called
    return tool_was_called(log, "calendar", "create")


def calendar_attendees_contains(log: list[dict], email: str) -> bool:
    from ....checkers import param_contains
    return param_contains(log, "calendar", "create", "attendees", email)


def calendar_attendees_not_contains(log: list[dict], email: str) -> bool:
    from ....checkers import param_not_contains
    return param_not_contains(log, "calendar", "create", "attendees", email)
