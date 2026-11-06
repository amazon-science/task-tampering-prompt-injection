# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Productivity environment tools (entity-action pattern).

Implements the email, calendar, document and contact tools; each takes an 'action'
parameter that selects the operation. The task and policy tools come from
prompt_injection_benchmark.core.base_tools.
"""

from pathlib import Path
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
import uuid

from prompt_injection_benchmark.core.base_tools import EmailTool, DocumentTool, CalendarTool, ContactTool, TaskTool, normalize_id


class EmailToolUnified(EmailTool):
    """Unified email tool with multiple actions."""

    _PARAM_ACTIONS = {
        "search_subject": ["search"],
        "search_body": ["search"],
        "search_from": ["search"],
        "search_to": ["search"],
        "folder": ["search"],
        "limit": ["search"],
        "email_id": ["read", "reply", "forward"],
        "to": ["send", "forward"],
        "subject": ["send"],
        "body": ["send", "reply"],
        "cc": ["send"],
        "bcc": ["send"],
        "reply_all": ["reply"],
        "message": ["forward"],
    }

    async def execute(
        self,
        action: Literal["search", "read", "send", "reply", "forward"],
        search_subject: Optional[str] = None,
        search_body: Optional[str] = None,
        search_from: Optional[str] = None,
        search_to: Optional[str] = None,
        folder: Optional[str] = "inbox",
        limit: Optional[int] = 10,
        email_id: Optional[str] = None,
        to: Optional[List[str]] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_all: Optional[bool] = False,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute email action.
        
        Args:
            action: Action to perform (search, read, send, reply, forward)
            
            Search parameters (all optional, combine to filter):
              search_subject: Filter by subject words (all words must appear, any order)
              search_body: Filter by body words (all words must appear, any order)
              search_from: Filter by sender email address (partial match)
              search_to: Filter by recipient email address (partial match)
              folder: Folder to search (inbox, sent, or all)
              limit: Max results
              
            Read/Reply/Forward parameters:
              email_id: Email ID (for read, reply, forward actions)
              
            Send parameters:
              to: Recipients list
              subject: Email subject (for send)
              body: Email body (for send, reply)
              cc: CC recipients
              bcc: BCC recipients
              
            Reply/Forward parameters:
              reply_all: Reply to all recipients (for reply action)
              message: Forwarding message (for forward action)
        
        Returns:
            Action-specific result
        """
        provided = {
            "search_subject": search_subject, "search_body": search_body,
            "search_from": search_from, "search_to": search_to,
            "email_id": email_id, "to": to, "subject": subject,
            "body": body, "cc": cc, "bcc": bcc, "message": message,
        }
        if folder != "inbox":
            provided["folder"] = folder
        if limit != 10:
            provided["limit"] = limit
        if reply_all:
            provided["reply_all"] = reply_all

        violations = []
        for param_name, value in provided.items():
            if value is None:
                continue
            valid_actions = self._PARAM_ACTIONS.get(param_name, [])
            if valid_actions and action not in valid_actions:
                violations.append(
                    f"'{param_name}' is not valid for action '{action}' "
                    f"(used by: {', '.join(valid_actions)})"
                )
        if violations:
            return {
                "error": f"Invalid parameters for action '{action}': "
                         + "; ".join(violations)
                         + ". No action was performed."
            }

        if email_id:
            email_id = normalize_id(email_id, "email")

        if action == "search":
            return await self._search(
                search_subject=search_subject,
                search_body=search_body,
                search_from=search_from,
                search_to=search_to,
                folder=folder,
                limit=limit
            )
        elif action == "read":
            return await self._read(email_id)
        elif action == "send":
            return await self._send(to, subject, body, cc, bcc)
        elif action == "reply":
            return await self._reply(email_id, body, reply_all)
        elif action == "forward":
            return await self._forward(email_id, to, message)
        else:
            return {"error": f"Unknown action: {action}"}
    
    def _words_match(self, search_words: str, text: str) -> bool:
        """Check if all words in search_words appear in text (case-insensitive, any order)."""
        if not search_words:
            return True
        words = [w.lower() for w in search_words.split() if len(w) > 1]
        if not words:
            return True
        text_lower = text.lower()
        return all(word in text_lower for word in words)
    
    async def _search(
        self,
        search_subject: Optional[str] = None,
        search_body: Optional[str] = None,
        search_from: Optional[str] = None,
        search_to: Optional[str] = None,
        folder: str = "inbox",
        limit: int = 10
    ) -> Dict[str, Any]:
        """Search emails with explicit filter parameters.
        
        All parameters are optional - provide any combination to filter:
        - search_subject: words to search in subject (all must appear, any order)
        - search_body: words to search in body (all must appear, any order)
        - search_from: sender email address (partial substring match)
        - search_to: recipient email address (partial substring match)
        - folder: inbox, sent, or all
        """
        folders_to_search = []
        if folder.lower() in ["all", "*"]:
            folders_to_search = [self.inbox_dir, self.sent_dir]
        else:
            folder_dir = self.emails_dir / folder
            if folder_dir.exists():
                folders_to_search = [folder_dir]
            else:
                if folder.lower() in ["inbox", "in"]:
                    folders_to_search = [self.inbox_dir]
                elif folder.lower() in ["sent", "out", "outbox"]:
                    folders_to_search = [self.sent_dir]
                else:
                    result = {"error": f"Folder '{folder}' not found. Available: inbox, sent, all"}
                    self.log_action("email", {
                        "action": "search",
                        "search_subject": search_subject,
                        "search_body": search_body,
                        "search_from": search_from,
                        "search_to": search_to,
                        "folder": folder,
                        "limit": limit
                    }, result)
                    return result
        
        matches = []
        
        for folder_dir in folders_to_search:
            if not folder_dir.exists():
                continue
                
            for email_file in folder_dir.glob("*.json"):
                email_data = self._read_json_and_inject(email_file)
                
                if search_subject:
                    if not self._words_match(search_subject, email_data.get("subject", "")):
                        continue
                
                if search_body:
                    if not self._words_match(search_body, email_data.get("body", "")):
                        continue
                
                if search_from:
                    if search_from.lower() not in email_data.get("from", "").lower():
                        continue
                
                if search_to:
                    to_addrs = ' '.join(email_data.get("to", [])).lower()
                    if search_to.lower() not in to_addrs:
                        continue
                
                matches.append({
                    "id": email_data["id"],
                    "from": email_data["from"],
                    "subject": email_data["subject"],
                    "date": email_data["date"],
                    "read": email_data.get("read", False),
                    "folder": folder_dir.name
                })
                
                if len(matches) >= limit:
                    break
            
            if len(matches) >= limit:
                break
        
        result = {"emails": matches, "count": len(matches)}
        self.log_action("email", {
            "action": "search",
            "search_subject": search_subject,
            "search_body": search_body,
            "search_from": search_from,
            "search_to": search_to,
            "folder": folder,
            "limit": limit
        }, result)
        return result
    
    async def _read(self, email_id: str) -> Dict[str, Any]:
        """Read email."""
        for folder in [self.inbox_dir, self.sent_dir]:
            email_file = folder / f"{email_id}.json"
            if email_file.exists():
                email_data = self._read_json_and_inject(email_file)
                result = {"success": True, **email_data}
                self.log_action("email", {"action": "read", "email_id": email_id}, result)
                return result
        
        result = {"error": f"Email '{email_id}' not found"}
        self.log_action("email", {"action": "read", "email_id": email_id}, result)
        return result
    
    async def _send(
        self, to: List[str], subject: str, body: str, 
        cc: Optional[List[str]], bcc: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Send email."""
        email_id = f"email_{uuid.uuid4().hex[:8]}"
        
        email_data = {
            "id": email_id,
            "from": "user@company.com",
            "to": to,
            "cc": cc or [],
            "bcc": bcc or [],
            "subject": subject,
            "body": body,
            "date": datetime.now().isoformat(),
            "sent": True
        }
        
        outbox_file = self.outbox_emails / f"{email_id}.json"
        with open(outbox_file, 'w') as f:
            json.dump(email_data, f, indent=2)
        
        result = {"success": True, "email_id": email_id}
        self.log_action("email", {
            "action": "send",
            "to": to,
            "subject": subject,
            "body": body,
            "cc": cc,
            "bcc": bcc
        }, result)
        return result
    
    async def _reply(self, email_id: str, body: str, reply_all: bool) -> Dict[str, Any]:
        """Reply to email."""
        original = None
        for folder in [self.inbox_dir, self.sent_dir]:
            email_file = folder / f"{email_id}.json"
            if email_file.exists():
                original = self._read_json_and_inject(email_file)
                break
        
        if not original:
            result = {"error": f"Email '{email_id}' not found"}
            self.log_action("email", 
                          {"action": "reply", "email_id": email_id, "body": body, "reply_all": reply_all}, 
                          result)
            return result
        
        to = [original["from"]]
        cc = []
        if reply_all:
            cc = [addr for addr in original.get("to", []) + original.get("cc", []) 
                  if addr != "user@company.com"]
        
        reply_id = f"email_{uuid.uuid4().hex[:8]}"
        reply_data = {
            "id": reply_id,
            "from": "user@company.com",
            "to": to,
            "cc": cc,
            "subject": f"Re: {original['subject']}",
            "body": body,
            "date": datetime.now().isoformat(),
            "thread_id": original.get("thread_id", original["id"]),
            "sent": True
        }
        
        outbox_file = self.outbox_emails / f"{reply_id}.json"
        with open(outbox_file, 'w') as f:
            json.dump(reply_data, f, indent=2)
        
        result = {"success": True, "email_id": reply_id}
        self.log_action("email", {
            "action": "reply",
            "email_id": email_id,
            "body": body,
            "reply_all": reply_all,
            "to": to,
            "cc": cc
        }, result)
        return result
    
    async def _forward(self, email_id: str, to: List[str], message: Optional[str]) -> Dict[str, Any]:
        """Forward email."""
        original = None
        for folder in [self.inbox_dir, self.sent_dir]:
            email_file = folder / f"{email_id}.json"
            if email_file.exists():
                original = self._read_json_and_inject(email_file)
                break
        
        if not original:
            result = {"error": f"Email '{email_id}' not found"}
            self.log_action("email", 
                          {"action": "forward", "email_id": email_id, "to": to, "message": message}, 
                          result)
            return result
        
        forward_id = f"email_{uuid.uuid4().hex[:8]}"
        forward_body = f"{message}\n\n" if message else ""
        forward_body += f"---------- Forwarded message ---------\n"
        forward_body += f"From: {original['from']}\nSubject: {original['subject']}\n\n"
        forward_body += original['body']
        
        forward_data = {
            "id": forward_id,
            "from": "user@company.com",
            "to": to,
            "subject": f"Fwd: {original['subject']}",
            "body": forward_body,
            "date": datetime.now().isoformat(),
            "sent": True
        }
        
        outbox_file = self.outbox_emails / f"{forward_id}.json"
        with open(outbox_file, 'w') as f:
            json.dump(forward_data, f, indent=2)
        
        result = {"success": True, "email_id": forward_id}
        self.log_action("email", {
            "action": "forward",
            "email_id": email_id,
            "to": to,
            "message": message
        }, result)
        return result


class CalendarToolUnified(CalendarTool):
    """Unified calendar tool with multiple actions."""

    _PARAM_ACTIONS = {
        "start_date": ["list"],
        "end_date": ["list"],
        "event_id": ["read", "delete"],
        "title": ["create"],
        "start": ["create"],
        "end": ["create"],
        "attendees": ["create"],
        "description": ["create"],
        "notify": ["delete"],
        "query": ["search"],
    }

    async def execute(
        self,
        action: Literal["list", "read", "create", "delete", "search"],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        event_id: Optional[str] = None,
        title: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        description: Optional[str] = None,
        notify: Optional[bool] = False,
        query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute calendar action.
        
        Args:
            action: Action to perform (list, read, create, delete, search)
            start_date: Start date for list (ISO format)
            end_date: End date for list (ISO format)
            event_id: Event ID for read/delete
            title: Event title for create
            start: Start time for create (ISO format)
            end: End time for create (ISO format)
            attendees: Attendees for create
            description: Description for create
            notify: Notify attendees on delete
            query: Search query for search action
        
        Returns:
            Action-specific result
        """
        provided = {
            "start_date": start_date, "end_date": end_date,
            "event_id": event_id, "title": title, "start": start,
            "end": end, "attendees": attendees, "description": description,
            "query": query,
        }
        if notify:
            provided["notify"] = notify

        violations = []
        for param_name, value in provided.items():
            if value is None:
                continue
            valid_actions = self._PARAM_ACTIONS.get(param_name, [])
            if valid_actions and action not in valid_actions:
                violations.append(
                    f"'{param_name}' is not valid for action '{action}' "
                    f"(used by: {', '.join(valid_actions)})"
                )
        if violations:
            return {
                "error": f"Invalid parameters for action '{action}': "
                         + "; ".join(violations)
                         + ". No action was performed."
            }

        if event_id:
            event_id = normalize_id(event_id, "evt")

        if action == "list":
            return await self._list(start_date, end_date)
        elif action == "search":
            return await self._search(query)
        elif action == "read":
            return await self._read(event_id)
        elif action == "create":
            return await self._create(title, start, end, attendees, description)
        elif action == "delete":
            return await self._delete(event_id, notify)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """List events."""
        if not self.calendar_file.exists():
            result = {"error": "Calendar file not found"}
            self.log_action("calendar", 
                          {"action": "list", "start_date": start_date, "end_date": end_date}, 
                          result)
            return result
        
        calendar_data = self._read_json_and_inject(self.calendar_file)
        events = calendar_data.get("events", [])
        
        filtered = []
        for event in events:
            if start_date <= event["start"] <= end_date:
                filtered.append({
                    "id": event["id"],
                    "title": event["title"],
                    "start": event["start"],
                    "end": event["end"],
                    "attendees": event.get("attendees", [])
                })
        
        result = {"events": filtered, "count": len(filtered)}
        self.log_action("calendar", 
                      {"action": "list", "start_date": start_date, "end_date": end_date}, 
                      result)
        return result
    
    async def _read(self, event_id: str) -> Dict[str, Any]:
        """Read event."""
        if not self.calendar_file.exists():
            result = {"error": "Calendar file not found"}
            self.log_action("calendar", {"action": "read", "event_id": event_id}, result)
            return result
        
        calendar_data = self._read_json_and_inject(self.calendar_file)
        events = calendar_data.get("events", [])
        
        for event in events:
            if event["id"] == event_id:
                result = {"success": True, **event}
                self.log_action("calendar", {"action": "read", "event_id": event_id}, result)
                return result
        
        result = {"error": f"Event '{event_id}' not found"}
        self.log_action("calendar", {"action": "read", "event_id": event_id}, result)
        return result
    
    async def _create(
        self, title: str, start: str, end: str,
        attendees: Optional[List[str]], description: Optional[str]
    ) -> Dict[str, Any]:
        """Create event."""
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        
        event_data = {
            "id": event_id,
            "title": title,
            "start": start,
            "end": end,
            "attendees": attendees or [],
            "description": description or "",
            "organizer": "user@company.com",
            "created": datetime.now().isoformat()
        }
        
        calendar_data = {"events": []}
        if self.calendar_file.exists():
            with open(self.calendar_file, 'r') as f:
                calendar_data = json.load(f)
        
        calendar_data["events"].append(event_data)
        
        with open(self.calendar_file, 'w') as f:
            json.dump(calendar_data, f, indent=2)
        
        result = {"success": True, "event_id": event_id}
        self.log_action("calendar", {
            "action": "create",
            "title": title,
            "start": start,
            "end": end,
            "attendees": attendees,
            "description": description
        }, result)
        return result
    
    async def _search(self, query: str) -> Dict[str, Any]:
        """Search events by title (supports words in any order)."""
        if not self.calendar_file.exists():
            result = {"error": "Calendar file not found"}
            self.log_action("calendar", {"action": "search", "query": query}, result)
            return result
        
        calendar_data = self._read_json_and_inject(self.calendar_file)
        events = calendar_data.get("events", [])
        
        query_lower = query.lower()
        query_words = [w for w in query_lower.split() if len(w) > 2]
        
        matches = []
        for event in events:
            title = event.get("title", "").lower()
            description = event.get("description", "").lower()
            searchable = f"{title} {description}"
            
            exact_match = query_lower in searchable
            word_match = query_words and all(word in searchable for word in query_words)
            
            if exact_match or word_match:
                matches.append({
                    "id": event["id"],
                    "title": event["title"],
                    "start": event["start"],
                    "end": event["end"],
                    "attendees": event.get("attendees", [])
                })
        
        result = {"events": matches, "count": len(matches)}
        self.log_action("calendar", {"action": "search", "query": query}, result)
        return result
    
    async def _delete(self, event_id: str, notify: bool) -> Dict[str, Any]:
        """Delete event."""
        if not self.calendar_file.exists():
            result = {"error": "Calendar file not found"}
            self.log_action("calendar", 
                          {"action": "delete", "event_id": event_id, "notify": notify}, 
                          result)
            return result
        
        with open(self.calendar_file, 'r') as f:
            calendar_data = json.load(f)
        
        events = calendar_data.get("events", [])
        found = False
        for i, event in enumerate(events):
            if event["id"] == event_id:
                events.pop(i)
                found = True
                break
        
        if not found:
            result = {"error": f"Event '{event_id}' not found"}
            self.log_action("calendar", 
                          {"action": "delete", "event_id": event_id, "notify": notify}, 
                          result)
            return result
        
        calendar_data["events"] = events
        with open(self.calendar_file, 'w') as f:
            json.dump(calendar_data, f, indent=2)
        
        result = {"success": True, "deleted": event_id}
        self.log_action("calendar", 
                      {"action": "delete", "event_id": event_id, "notify": notify}, 
                      result)
        return result


class DocumentToolUnified(DocumentTool):
    """
    Unified document tool with virtual folder support.

    Uses centralized config files:
    - _folders.json: Virtual folder definitions with sharing config
    - _documents.json: Document metadata including folder assignment

    Actions: list_folders, list, search, read, write, update, create_folder
    """

    _PARAM_ACTIONS = {
        "folder": ["list", "search", "read", "write", "update", "create_folder"],
        "filename": ["read", "write", "update"],
        "query": ["list", "search"],
        "content": ["write", "update"],
        "title": ["update", "create_folder"],
        "shared_with": ["write", "update", "create_folder"],
        "classification": ["write", "update"],
        "description": ["update", "create_folder"],
        "owner": ["update", "create_folder"],
        "access_level": ["update", "create_folder"],
    }
    
    def _load_folders_config(self) -> Dict[str, Any]:
        """Load virtual folders configuration."""
        if not self.folders_config.exists():
            return {"folders": {}}
        return self._read_json_and_inject(self.folders_config)
    
    def _load_documents_config(self) -> Dict[str, Any]:
        """Load documents metadata configuration."""
        if not self.documents_config.exists():
            return {"documents": {}}
        return self._read_json_and_inject(self.documents_config)
    
    def _save_folders_config(self, config: Dict[str, Any]) -> None:
        """Save virtual folders configuration."""
        with open(self.folders_config, 'w') as f:
            json.dump(config, f, indent=2)
    
    def _save_documents_config(self, config: Dict[str, Any]) -> None:
        """Save documents metadata configuration."""
        with open(self.documents_config, 'w') as f:
            json.dump(config, f, indent=2)
    
    def _get_effective_sharing(self, doc_id: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Compute effective sharing for a document (folder + document level).

        Returns:
            {
                "folder": [...],  # From folder config
                "document": [...],  # From document config
                "effective": [...]  # Combined unique list
            }
        """
        folders_config = self._load_folders_config()
        docs_config = self._load_documents_config()

        doc_meta = docs_config.get("documents", {}).get(doc_id, {})
        if not folder_id:
            folder_id = doc_meta.get("folder")
        folder_config = folders_config.get("folders", {}).get(folder_id, {}) if folder_id else {}

        folder_sharing = folder_config.get("shared_with", [])
        doc_sharing = doc_meta.get("shared_with", [])

        effective = list(set(folder_sharing + doc_sharing))

        return {
            "folder": folder_sharing,
            "document": doc_sharing,
            "effective": effective
        }
    
    async def execute(
        self,
        action: Literal["list", "read", "write", "search", "list_folders", "update", "create_folder"],
        folder: Optional[str] = None,
        filename: Optional[str] = None,
        query: Optional[str] = None,
        content: Optional[str] = None,
        title: Optional[str] = None,
        shared_with: Optional[List[str]] = None,
        classification: Optional[str] = None,
        description: Optional[str] = None,
        owner: Optional[str] = None,
        access_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute document action.

        Args:
            action: Action to perform (list_folders, list, search, read, write, update, create_folder)
            folder: Folder — required with filename for read/write/update. Also used as filter (list/search) or target (create_folder).
            filename: Document filename without .md extension — required with folder for read/write/update.
            query: Search query (for search)
            content: Document content (for write, update)
            title: Title (for update doc, create_folder)
            shared_with: Email addresses to share with
            classification: Document classification
            description: Description (for create_folder)
            owner: Owner email (for create_folder)
            access_level: Access level (for create_folder)

        Returns:
            Action-specific result
        """
        provided = {
            "folder": folder, "filename": filename, "query": query,
            "content": content, "title": title, "shared_with": shared_with,
            "classification": classification, "description": description,
            "owner": owner, "access_level": access_level,
        }

        violations = []
        for param_name, value in provided.items():
            if value is None:
                continue
            valid_actions = self._PARAM_ACTIONS.get(param_name, [])
            if valid_actions and action not in valid_actions:
                violations.append(
                    f"'{param_name}' is not valid for action '{action}' "
                    f"(used by: {', '.join(valid_actions)})"
                )
        if violations:
            return {
                "error": f"Invalid parameters for action '{action}': "
                         + "; ".join(violations)
                         + ". No action was performed."
            }

        if action == "list":
            return await self._list(folder, query)
        elif action == "list_folders":
            return await self._list_folders()
        elif action == "search":
            return await self._search(query, folder)
        elif action == "read":
            return await self._read(folder, filename)
        elif action == "write":
            return await self._write(folder, filename, content, shared_with, classification)
        elif action == "update":
            return await self._update(
                folder=folder,
                filename=filename,
                content=content,
                title=title,
                shared_with=shared_with,
                classification=classification,
                description=description,
                owner=owner,
                access_level=access_level
            )
        elif action == "create_folder":
            return await self._create_folder(folder, title, description, shared_with, owner, access_level)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list_folders(self) -> Dict[str, Any]:
        """List all virtual folders with sharing info."""
        folders_config = self._load_folders_config()
        docs_config = self._load_documents_config()
        
        folders = []
        for folder_id, folder_data in folders_config.get("folders", {}).items():
            doc_count = sum(
                1 for doc in docs_config.get("documents", {}).values()
                if doc.get("folder") == folder_id
            )
            
            folders.append({
                "id": folder_id,
                "name": folder_data.get("name", folder_id),
                "description": folder_data.get("description", ""),
                "shared_with": folder_data.get("shared_with", []),
                "owner": folder_data.get("owner", ""),
                "access_level": folder_data.get("access_level", "internal"),
                "document_count": doc_count
            })
        
        result = {
            "folders": sorted(folders, key=lambda x: x["name"]),
            "count": len(folders)
        }
        self.log_action("document", {"action": "list_folders"}, result)
        return result
    
    async def _list(self, folder: Optional[str], query: Optional[str]) -> Dict[str, Any]:
        """List documents in a virtual folder (or all if no folder specified)."""
        docs_config = self._load_documents_config()
        
        documents = []
        for doc_id, doc_data in docs_config.get("documents", {}).items():
            if folder and doc_data.get("folder") != folder:
                continue
            
            if query and query.lower() not in doc_data.get("title", "").lower():
                continue
            
            documents.append({
                "filename": doc_id,
                "title": doc_data.get("title", "Untitled"),
                "author": doc_data.get("author", "Unknown"),
                "folder": doc_data.get("folder", ""),
                "shared_with": doc_data.get("shared_with", []),
                "classification": doc_data.get("classification", "INTERNAL"),
                "modified": doc_data.get("modified", "")
            })

        result = {"documents": documents, "count": len(documents)}
        self.log_action("document",
                      {"action": "list", "folder": folder, "query": query},
                      result)
        return result
    
    async def _search(self, query: str, folder: Optional[str] = None) -> Dict[str, Any]:
        """Search documents by title (supports words in any order)."""
        docs_config = self._load_documents_config()
        
        documents = []
        query_lower = query.lower()
        query_words = [w for w in query_lower.split() if len(w) > 2]
        
        for doc_id, doc_data in docs_config.get("documents", {}).items():
            if folder and doc_data.get("folder") != folder:
                continue
            
            title = doc_data.get("title", doc_id)
            searchable = f"{title} {doc_id}".lower()
            
            exact_match = query_lower in searchable
            word_match = query_words and all(word in searchable for word in query_words)
            
            if exact_match or word_match:
                documents.append({
                    "filename": doc_id,
                    "title": title,
                    "author": doc_data.get("author", "Unknown"),
                    "folder": doc_data.get("folder", ""),
                    "shared_with": doc_data.get("shared_with", []),
                    "classification": doc_data.get("classification", "INTERNAL")
                })
        
        result = {"documents": documents, "count": len(documents)}
        self.log_action("document", {"action": "search", "query": query, "folder": folder}, result)
        return result
    
    async def _read(self, folder: str, filename: str) -> Dict[str, Any]:
        """Read document by folder + filename."""
        if not folder or not filename:
            result = {"error": "Both folder and filename are required for read"}
            self.log_action("document", {"action": "read", "folder": folder, "filename": filename}, result)
            return result

        docs_config = self._load_documents_config()
        doc_id = None
        doc_meta = None
        for did, meta in docs_config.get("documents", {}).items():
            if meta.get("folder") == folder and (did == filename or meta.get("file", "").replace(".md", "") == filename):
                doc_id = did
                doc_meta = meta
                break

        if not doc_meta:
            result = {"error": f"Document '{filename}' not found in folder '{folder}'"}
            self.log_action("document", {"action": "read", "folder": folder, "filename": filename}, result)
            return result

        file_path = doc_meta.get("file")
        if file_path:
            doc_file = self.documents_dir / file_path
        else:
            doc_file = self.documents_dir / f"{doc_id}.md"

        if not doc_file or not doc_file.exists():
            result = {"error": f"Document file for '{filename}' not found"}
            self.log_action("document", {"action": "read", "folder": folder, "filename": filename}, result)
            return result

        content = self._read_and_inject(doc_file)

        lines = content.split('\n')
        body_start = 0
        if lines[0] == '---':
            for i, line in enumerate(lines[1:], 1):
                if line == '---':
                    body_start = i + 1
                    break
        body = '\n'.join(lines[body_start:])

        sharing = self._get_effective_sharing(doc_id)

        result = {
            "success": True,
            "folder": folder,
            "filename": filename,
            "title": doc_meta.get("title", "Untitled"),
            "author": doc_meta.get("author", "Unknown"),
            "classification": doc_meta.get("classification", "INTERNAL"),
            "sharing": sharing,
            "created": doc_meta.get("created", ""),
            "modified": doc_meta.get("modified", ""),
            "content": body
        }
        self.log_action("document", {"action": "read", "folder": folder, "filename": filename}, result)
        return result
    
    async def _write(
        self,
        folder: str,
        filename: str,
        content: str,
        shared_with: Optional[List[str]] = None,
        classification: Optional[str] = None
    ) -> Dict[str, Any]:
        """Write document and update metadata registry. All docs are .md files."""
        if not folder or not filename:
            result = {"error": "Both folder and filename are required for write"}
            self.log_action("document", {"action": "write", "folder": folder, "filename": filename}, result)
            return result

        docs_config = self._load_documents_config()
        doc_id = filename

        existing = docs_config.get("documents", {}).get(doc_id)
        if existing and existing.get("folder") != folder:
            result = {"error": f"Document '{filename}' already exists in folder '{existing['folder']}'. Filenames must be unique across folders."}
            self.log_action("document", {"action": "write", "folder": folder, "filename": filename}, result)
            return result

        disk_filename = f"{filename}.md"
        doc_file = self.documents_dir / disk_filename

        with open(doc_file, 'w') as f:
            f.write(content)

        if doc_id not in docs_config.get("documents", {}):
            docs_config.setdefault("documents", {})[doc_id] = {
                "title": doc_id,
                "author": "user@company.com",
                "folder": folder,
                "file": disk_filename,
                "shared_with": shared_with or [],
                "classification": classification or "INTERNAL",
                "created": datetime.now().strftime("%Y-%m-%d"),
                "modified": datetime.now().strftime("%Y-%m-%d")
            }
        else:
            docs_config["documents"][doc_id]["modified"] = datetime.now().strftime("%Y-%m-%d")
            if shared_with is not None:
                docs_config["documents"][doc_id]["shared_with"] = shared_with
            if classification is not None:
                docs_config["documents"][doc_id]["classification"] = classification

        self._save_documents_config(docs_config)

        result = {"success": True, "folder": folder, "filename": filename, "shared_with": shared_with or []}
        self.log_action("document", {
            "action": "write",
            "folder": folder,
            "filename": filename,
            "content": content,
            "shared_with": shared_with,
            "classification": classification
        }, result)
        return result
    
    async def _update(
        self,
        folder: Optional[str] = None,
        filename: Optional[str] = None,
        content: Optional[str] = None,
        title: Optional[str] = None,
        shared_with: Optional[List[str]] = None,
        classification: Optional[str] = None,
        description: Optional[str] = None,
        owner: Optional[str] = None,
        access_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update document content and/or metadata, or folder metadata.

        If folder + filename: updates that document's content/metadata
        If folder only (no filename): updates folder metadata
        """
        if folder and not filename:
            folders_config = self._load_folders_config()
            if folder not in folders_config.get("folders", {}):
                result = {"error": f"Folder '{folder}' not found"}
                self.log_action("document", {"action": "update", "folder": folder}, result)
                return result

            folder_data = folders_config["folders"][folder]

            if title is not None:
                folder_data["name"] = title
            if description is not None:
                folder_data["description"] = description
            if owner is not None:
                folder_data["owner"] = owner
            if access_level is not None:
                folder_data["access_level"] = access_level
            if shared_with is not None:
                folder_data["shared_with"] = shared_with

            self._save_folders_config(folders_config)

            result = {"success": True, "folder": folder, "updated": folder_data}
            self.log_action("document", {
                "action": "update",
                "folder": folder,
                "title": title,
                "description": description,
                "shared_with": shared_with,
                "owner": owner,
                "access_level": access_level
            }, result)
            return result

        if folder and filename:
            docs_config = self._load_documents_config()
            doc_id = None
            doc_data = None
            for did, meta in docs_config.get("documents", {}).items():
                if meta.get("folder") == folder and (did == filename or meta.get("file", "").replace(".md", "") == filename):
                    doc_id = did
                    doc_data = meta
                    break

            if not doc_data:
                result = {"error": f"Document '{filename}' not found in folder '{folder}'"}
                self.log_action("document", {"action": "update", "folder": folder, "filename": filename}, result)
                return result

            if title is not None:
                doc_data["title"] = title
            if classification is not None:
                doc_data["classification"] = classification
            if shared_with is not None:
                doc_data["shared_with"] = shared_with

            if content is not None:
                doc_file = self.documents_dir / doc_data.get("file", f"{doc_id}.md")
                doc_file.parent.mkdir(parents=True, exist_ok=True)
                with open(doc_file, 'w') as f:
                    f.write(content)

            doc_data["modified"] = datetime.now().strftime("%Y-%m-%d")

            self._save_documents_config(docs_config)

            result = {"success": True, "folder": folder, "filename": filename, "updated": doc_data}
            self.log_action("document", {
                "action": "update",
                "folder": folder,
                "filename": filename,
                "content": content,
                "title": title,
                "shared_with": shared_with,
                "classification": classification
            }, result)
            return result

        result = {"error": "Provide folder + filename to update a document, or folder alone to update folder metadata"}
        self.log_action("document", {"action": "update"}, result)
        return result
    
    async def _create_folder(
        self,
        folder_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        shared_with: Optional[List[str]] = None,
        owner: Optional[str] = None,
        access_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new virtual folder."""
        folders_config = self._load_folders_config()
        
        if folder_id in folders_config.get("folders", {}):
            result = {"error": f"Folder '{folder_id}' already exists"}
            self.log_action("document", {
                "action": "create_folder",
                "folder": folder_id
            }, result)
            return result
        
        folders_config.setdefault("folders", {})[folder_id] = {
            "name": title or folder_id,
            "description": description or "",
            "shared_with": shared_with or [],
            "owner": owner or "user@company.com",
            "access_level": access_level or "internal"
        }
        
        self._save_folders_config(folders_config)
        
        result = {"success": True, "folder": folder_id, "created": folders_config["folders"][folder_id]}
        self.log_action("document", {
            "action": "create_folder",
            "folder": folder_id,
            "title": title,
            "description": description,
            "shared_with": shared_with,
            "owner": owner,
            "access_level": access_level
        }, result)
        return result


class ContactToolUnified(ContactTool):
    """Unified contact tool with list, search, add, update actions."""

    _PARAM_ACTIONS = {
        "query": ["search"],
        "category": ["list"],
        "name": ["add", "update"],
        "email": ["add", "update"],
        "company": ["add", "update"],
        "title": ["add", "update"],
        "phone": ["add", "update"],
        "contact_category": ["add"],
    }

    async def execute(
        self,
        action: Literal["list", "search", "add", "update"],
        query: Optional[str] = None,
        category: Optional[str] = None,
        name: Optional[str] = None,
        email: Optional[str] = None,
        company: Optional[str] = None,
        title: Optional[str] = None,
        phone: Optional[str] = None,
        contact_category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute contact action.
        
        Args:
            action: Action to perform (list, search, add, update)
            query: Search query (for search action)
            category: Filter by category (for list action): internal, vendors, partners, clients
            name: Contact name (for add, for update to identify contact)
            email: Contact email (for add, update)
            company: Contact company (for add, update)
            title: Contact title/role (for add, update)
            phone: Contact phone (for add, update)
            contact_category: Category for new contact (for add): internal, vendors, partners, clients
        
        Returns:
            Action-specific result
        """
        provided = {
            "query": query, "category": category, "name": name,
            "email": email, "company": company, "title": title,
            "phone": phone, "contact_category": contact_category,
        }

        violations = []
        for param_name, value in provided.items():
            if value is None:
                continue
            valid_actions = self._PARAM_ACTIONS.get(param_name, [])
            if valid_actions and action not in valid_actions:
                violations.append(
                    f"'{param_name}' is not valid for action '{action}' "
                    f"(used by: {', '.join(valid_actions)})"
                )
        if violations:
            return {
                "error": f"Invalid parameters for action '{action}': "
                         + "; ".join(violations)
                         + ". No action was performed."
            }

        if action == "list":
            return await self._list(category)
        elif action == "search":
            return await self._search(query)
        elif action == "add":
            return await self._add(name, email, company, title, phone, contact_category)
        elif action == "update":
            return await self._update(email, name, company, title, phone)
        else:
            return {"error": f"Unknown action: {action}"}
    
    def _load_contacts(self) -> Dict[str, Any]:
        """Load contacts data."""
        if not self.contacts_file.exists():
            return {"internal": [], "vendors": [], "partners": [], "clients": []}
        return self._read_json_and_inject(self.contacts_file)
    
    def _save_contacts(self, contacts_data: Dict[str, Any]) -> None:
        """Save contacts data."""
        with open(self.contacts_file, 'w') as f:
            json.dump(contacts_data, f, indent=2)
    
    def _get_all_contacts(self, contacts_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get all contacts across categories."""
        all_contacts = []
        for category in ["internal", "vendors", "partners", "clients"]:
            for contact in contacts_data.get(category, []):
                contact_copy = contact.copy()
                contact_copy["category"] = category
                all_contacts.append(contact_copy)
        return all_contacts
    
    async def _list(self, category: Optional[str] = None) -> Dict[str, Any]:
        """List contacts, optionally filtered by category."""
        contacts_data = self._load_contacts()
        
        if category:
            if category not in ["internal", "vendors", "partners", "clients"]:
                result = {"error": f"Unknown category: {category}. Available: internal, vendors, partners, clients"}
                self.log_action("contact", {"action": "list", "category": category}, result)
                return result
            contacts = [dict(**c, category=category) for c in contacts_data.get(category, [])]
        else:
            contacts = self._get_all_contacts(contacts_data)
        
        result = {"contacts": contacts, "count": len(contacts)}
        self.log_action("contact", {"action": "list", "category": category}, result)
        return result
    
    async def _search(self, query: str) -> Dict[str, Any]:
        """Search contacts by name, email, or company."""
        if not query:
            result = {"error": "Query is required for search action"}
            self.log_action("contact", {"action": "search", "query": query}, result)
            return result
        
        contacts_data = self._load_contacts()
        all_contacts = self._get_all_contacts(contacts_data)
        
        query_lower = query.lower()
        matches = []
        for contact in all_contacts:
            if (query_lower in contact.get("name", "").lower() or
                query_lower in contact.get("email", "").lower() or
                query_lower in contact.get("company", "").lower()):
                matches.append(contact)
        
        result = {"contacts": matches, "count": len(matches)}
        self.log_action("contact", {"action": "search", "query": query}, result)
        return result
    
    async def _add(
        self,
        name: str,
        email: str,
        company: Optional[str],
        title: Optional[str],
        phone: Optional[str],
        contact_category: Optional[str]
    ) -> Dict[str, Any]:
        """Add a new contact."""
        if not name or not email:
            result = {"error": "Name and email are required to add a contact"}
            self.log_action("contact", {
                "action": "add", "name": name, "email": email
            }, result)
            return result
        
        category = contact_category or "internal"
        if category not in ["internal", "vendors", "partners", "clients"]:
            result = {"error": f"Unknown category: {category}. Available: internal, vendors, partners, clients"}
            self.log_action("contact", {
                "action": "add", "name": name, "email": email, "category": category
            }, result)
            return result
        
        contacts_data = self._load_contacts()
        
        all_contacts = self._get_all_contacts(contacts_data)
        for existing in all_contacts:
            if existing.get("email", "").lower() == email.lower():
                result = {"error": f"Contact with email '{email}' already exists"}
                self.log_action("contact", {
                    "action": "add", "name": name, "email": email
                }, result)
                return result
        
        new_contact = {
            "name": name,
            "email": email,
            "company": company or "",
            "title": title or "",
            "phone": phone or ""
        }
        
        contacts_data.setdefault(category, []).append(new_contact)
        self._save_contacts(contacts_data)
        
        result = {"success": True, "contact": new_contact, "category": category}
        self.log_action("contact", {
            "action": "add",
            "name": name,
            "email": email,
            "company": company,
            "title": title,
            "phone": phone,
            "category": category
        }, result)
        return result
    
    async def _update(
        self,
        email: str,
        name: Optional[str],
        company: Optional[str],
        title: Optional[str],
        phone: Optional[str]
    ) -> Dict[str, Any]:
        """Update an existing contact by email."""
        if not email:
            result = {"error": "Email is required to identify contact for update"}
            self.log_action("contact", {"action": "update", "email": email}, result)
            return result
        
        contacts_data = self._load_contacts()
        
        found = False
        updated_contact = None
        for category in ["internal", "vendors", "partners", "clients"]:
            for contact in contacts_data.get(category, []):
                if contact.get("email", "").lower() == email.lower():
                    if name is not None:
                        contact["name"] = name
                    if company is not None:
                        contact["company"] = company
                    if title is not None:
                        contact["title"] = title
                    if phone is not None:
                        contact["phone"] = phone
                    found = True
                    updated_contact = contact.copy()
                    updated_contact["category"] = category
                    break
            if found:
                break
        
        if not found:
            result = {"error": f"Contact with email '{email}' not found"}
            self.log_action("contact", {"action": "update", "email": email}, result)
            return result
        
        self._save_contacts(contacts_data)
        
        result = {"success": True, "contact": updated_contact}
        self.log_action("contact", {
            "action": "update",
            "email": email,
            "name": name,
            "company": company,
            "title": title,
            "phone": phone
        }, result)
        return result


