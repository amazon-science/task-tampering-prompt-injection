# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Base Tool Classes for Benchmark Environments

Provides base classes and utilities for implementing environment-specific tools.
All tools inherit from BaseEnvironmentTool which provides sandbox access,
action logging, and injection management.
"""

from pathlib import Path
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any, List


def normalize_id(value: str, prefix: str, zero_pad: int = 3) -> str:
    """Normalize an ID to canonical format: prefix_NNN.

    Accepts variations like '47', '#47', 'issue-47', 'issue_47', 'issue047',
    'pr 23', 'PR#23' and normalizes to e.g. 'issue_047' or 'pr_023'.

    Returns the original value unchanged if it already matches or cannot be parsed.
    """
    if not value:
        return value
    value = value.strip()
    canonical = f"{prefix}_"
    if value.startswith(canonical) and value[len(canonical):].isdigit():
        return f"{prefix}_{int(value[len(canonical):]):0{zero_pad}d}"
    stripped = re.sub(r'^[#\s]*', '', value)
    stripped = re.sub(rf'^{re.escape(prefix)}[\s\-_#]*', '', stripped, flags=re.IGNORECASE)
    stripped = stripped.lstrip('0') or '0'
    if stripped.isdigit():
        return f"{prefix}_{int(stripped):0{zero_pad}d}"
    return value


class BaseEnvironmentTool:
    """
    Base class for all environment tools.
    
    Provides:
    - Sandbox directory access
    - Action logging infrastructure
    - Injection replacement via InjectionManager
    - Common file operations
    """
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        """
        Initialize tool with sandbox directory.
        
        Args:
            sandbox_dir: Path to sandbox directory for this test
            injection_manager: InjectionManager instance for handling placeholders
        """
        self.sandbox_dir = Path(sandbox_dir)
        self.actions_log = self.sandbox_dir / "actions_log.jsonl"
        self.outbox = self.sandbox_dir / "outbox"
        self.outbox.mkdir(exist_ok=True)
        self.injection_manager = injection_manager
    
    def log_action(
        self, 
        tool_name: str, 
        parameters: Dict[str, Any], 
        result: Dict[str, Any]
    ) -> None:
        """
        Log the tool name, all supplied parameters, and result for evaluation.
        
        Args:
            tool_name: Name of the tool being called
            parameters: Dictionary of all parameters passed to the tool
            result: Result returned by tool
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "parameters": parameters,
            "result": result
        }
        
        with open(self.actions_log, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def _read_and_inject(self, file_path: Path) -> str:
        """
        Read file and replace injection placeholders.
        
        Args:
            file_path: Path to file in sandbox
        
        Returns:
            File content with injections applied
        """
        with open(file_path, 'r') as f:
            content = f.read()
        
        if self.injection_manager:
            content = self.injection_manager.replace_placeholders(content)
        
        return content
    
    def _read_json_and_inject(self, file_path: Path) -> Dict[str, Any]:
        """
        Read JSON file and replace injection placeholders in string fields.
        
        Args:
            file_path: Path to JSON file in sandbox
        
        Returns:
            Parsed JSON with injections applied to string values
        """
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        if self.injection_manager:
            data = self._inject_into_dict(data)
        
        return data
    
    def _inject_into_dict(self, obj: Any) -> Any:
        """
        Recursively apply injection replacements to dictionary/list structures.
        
        Args:
            obj: Dictionary, list, or primitive value
        
        Returns:
            Object with placeholders replaced in all string values
        """
        if isinstance(obj, dict):
            return {key: self._inject_into_dict(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._inject_into_dict(item) for item in obj]
        elif isinstance(obj, str):
            return self.injection_manager.replace_placeholders(obj)
        else:
            return obj
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the tool. Must be implemented by subclasses.
        
        Returns:
            Dictionary with tool results
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement execute()"
        )


class EmailTool(BaseEnvironmentTool):
    """Base class for email-related tools."""
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.emails_dir = self.sandbox_dir / "emails"
        self.inbox_dir = self.emails_dir / "inbox"
        self.sent_dir = self.emails_dir / "sent"
        self.outbox_emails = self.outbox / "sent_emails"
        self.outbox_emails.mkdir(exist_ok=True)


class DocumentTool(BaseEnvironmentTool):
    """Base class for document-related tools."""
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.documents_dir = self.sandbox_dir / "documents"
        self.outbox_docs = self.outbox / "documents"
        self.outbox_docs.mkdir(exist_ok=True)
        
        self.folders_config = self.documents_dir / "_folders.json"
        self.documents_config = self.documents_dir / "_documents.json"
        
        self._doc_index: Dict[str, Path] = {}
        self._build_document_index()
    
    def _build_document_index(self) -> None:
        """
        Build an index mapping document metadata IDs to file paths.
        
        Scans all .md files in documents_dir, parses their YAML frontmatter,
        and maps the 'id' field to the file path.
        Also indexes by filename (stem) as fallback.
        """
        if not self.documents_dir.exists():
            return
            
        for md_file in self.documents_dir.rglob("*.md"):
            try:
                content = md_file.read_text()
                lines = content.split('\n')
                
                if lines[0] == '---':
                    for line in lines[1:]:
                        if line == '---':
                            break
                        if line.startswith('id:'):
                            metadata_id = line.split(':', 1)[1].strip()
                            self._doc_index[metadata_id] = md_file
                            break
                
                self._doc_index[md_file.stem] = md_file
                
            except Exception:
                continue
    
    def _get_doc_path(self, doc_id: str) -> Optional[Path]:
        """
        Look up document path by ID (O(1) lookup).
        
        Args:
            doc_id: Document ID (metadata ID or filename stem)
        
        Returns:
            Path to document file, or None if not found
        """
        return self._doc_index.get(doc_id)


class CalendarTool(BaseEnvironmentTool):
    """Base class for calendar-related tools."""
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.calendar_file = self.sandbox_dir / "calendar" / "events.json"


class ContactTool(BaseEnvironmentTool):
    """Base class for contact-related tools."""
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.contacts_file = self.sandbox_dir / "contacts" / "contacts.json"


class TaskTool(BaseEnvironmentTool):
    """Base class for task-related tools."""

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.tasks_file = self.sandbox_dir / "tasks" / "tasks.json"


class PolicyToolBase(BaseEnvironmentTool):
    """
    Base policy tool that parses a markdown policy document into sections.

    Expects a markdown file with ## and ### headings following the pattern:
      ## N. Section Title
      ### N.M Subsection Title

    Provides list and read actions for browsing policy sections.
    Policy documents are read without injection replacement — they represent
    the organization's ground truth.
    """

    def __init__(self, sandbox_dir: str, policy_file_path: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.policy_file = self.sandbox_dir / policy_file_path
        self._section_cache = None

    def _parse_sections(self) -> Dict[str, Dict[str, Any]]:
        """Parse markdown into sections keyed by ID (e.g., "1", "1.1")."""
        if self._section_cache is not None:
            return self._section_cache

        if not self.policy_file.exists():
            return {}

        import re

        with open(self.policy_file, 'r') as f:
            content = f.read()

        lines = content.split('\n')
        sections = {}
        current_id = None
        current_title = None
        current_lines = []

        for line in lines:
            main_match = re.match(r'^##\s+(\d+)\.\s+(.+)$', line)
            sub_match = re.match(r'^###\s+(\d+\.\d+)\s+(.+)$', line)

            if main_match or sub_match:
                if current_id is not None:
                    sections[current_id] = {
                        "id": current_id,
                        "title": current_title,
                        "content": '\n'.join(current_lines).strip()
                    }

                match = main_match or sub_match
                current_id = match.group(1)
                current_title = match.group(2).strip()
                current_lines = []
            else:
                if current_id is not None:
                    current_lines.append(line)

        if current_id is not None:
            sections[current_id] = {
                "id": current_id,
                "title": current_title,
                "content": '\n'.join(current_lines).strip()
            }

        self._section_cache = sections
        return sections

    async def execute(
        self,
        action: str,
        section_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        if action == "list":
            return await self._list()
        elif action == "read":
            return await self._read(section_id)
        else:
            return {"error": f"Unknown action: {action}"}

    async def _list(self) -> Dict[str, Any]:
        """List all policy sections with IDs and titles."""
        sections = self._parse_sections()
        if not sections:
            result = {"error": "Policy document not found"}
            self.log_action("policy", {"action": "list"}, result)
            return result

        policy_list = []
        for sid, data in sorted(
            sections.items(),
            key=lambda x: [int(p) for p in x[0].split('.')]
        ):
            policy_list.append({"id": sid, "title": data["title"]})

        result = {"policies": policy_list, "count": len(policy_list)}
        self.log_action("policy", {"action": "list"}, result)
        return result

    async def _read(self, section_id: Optional[str] = None) -> Dict[str, Any]:
        """Read a specific policy section."""
        if not section_id:
            result = {"error": "section_id is required. Use action='list' to see available sections."}
            self.log_action("policy", {"action": "read", "section_id": section_id}, result)
            return result

        sections = self._parse_sections()
        if not sections:
            result = {"error": "Policy document not found"}
            self.log_action("policy", {"action": "read", "section_id": section_id}, result)
            return result

        section_id = section_id.strip()
        if section_id not in sections:
            result = {
                "error": f"Section '{section_id}' not found. Available: {list(sections.keys())}"
            }
            self.log_action("policy", {"action": "read", "section_id": section_id}, result)
            return result

        section = sections[section_id]
        result = {
            "success": True,
            "section_id": section_id,
            "title": section["title"],
            "content": section["content"]
        }
        self.log_action("policy", {"action": "read", "section_id": section_id}, result)
        return result


class TaskToolBase(BaseEnvironmentTool):
    """
    Base task tool for work assignments (like Jira tickets or support queue entries).

    Supports list, read, create, and update actions. Pre-seeded tasks represent
    externally-assigned work items. The agent can also create new tasks and
    update existing ones (e.g., mark as resolved).

    Pre-seeded task data is read without injection replacement — it represents
    the correct assignment (ground truth for objectives).
    """

    def __init__(self, sandbox_dir: str, task_file_path: str = "tasks/tasks.json", injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.task_file = self.sandbox_dir / task_file_path
        self._task_cache = None

    def _load_tasks(self) -> List[Dict]:
        """Load tasks from JSON file without injection."""
        if self._task_cache is not None:
            return self._task_cache

        if not self.task_file.exists():
            self._task_cache = []
            return self._task_cache

        with open(self.task_file, 'r') as f:
            data = json.load(f)

        self._task_cache = data.get("tasks", [])
        return self._task_cache

    def _save_tasks(self):
        """Persist current task list to disk."""
        self.task_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.task_file, 'w') as f:
            json.dump({"tasks": self._task_cache}, f, indent=2)

    def _next_id(self) -> str:
        """Generate the next task ID based on existing tasks."""
        tasks = self._load_tasks()
        if not tasks:
            return "T-001"
        import re
        max_num = 0
        for t in tasks:
            match = re.search(r'(\d+)$', t["id"])
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"T-{max_num + 1:03d}"

    async def execute(
        self,
        action: str,
        task_id: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        if action == "list":
            return await self._list()
        elif action == "read":
            return await self._read(task_id)
        elif action == "create":
            return await self._create(title=title, description=description, priority=priority)
        elif action == "update":
            return await self._update(task_id=task_id, status=status, priority=priority, description=description)
        else:
            return {"error": f"Unknown action: {action}. Valid actions: list, read, create, update"}

    async def _list(self) -> Dict[str, Any]:
        """List all tasks with summary fields."""
        tasks = self._load_tasks()
        if not tasks:
            result = {"tasks": [], "count": 0}
            self.log_action("task", {"action": "list"}, result)
            return result

        summary = [
            {
                "id": t["id"],
                "title": t["title"],
                "status": t.get("status", "pending"),
                "priority": t.get("priority", "medium")
            }
            for t in tasks
        ]
        result = {"tasks": summary, "count": len(summary)}
        self.log_action("task", {"action": "list"}, result)
        return result

    async def _read(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Read full details of a specific task."""
        if not task_id:
            result = {"error": "task_id is required. Use action='list' to see available tasks."}
            self.log_action("task", {"action": "read", "task_id": task_id}, result)
            return result

        tasks = self._load_tasks()
        task_id = task_id.strip()
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            available = [t["id"] for t in tasks]
            result = {"error": f"Task '{task_id}' not found. Available: {available}"}
            self.log_action("task", {"action": "read", "task_id": task_id}, result)
            return result

        result = {"success": True, **task}
        self.log_action("task", {"action": "read", "task_id": task_id}, result)
        return result

    async def _create(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new task."""
        if not title:
            result = {"error": "title is required for create action."}
            self.log_action("task", {"action": "create"}, result)
            return result

        tasks = self._load_tasks()
        new_task = {
            "id": self._next_id(),
            "title": title,
            "description": description or "",
            "assigned_to": "current_user",
            "status": "pending",
            "priority": priority or "medium",
            "created": datetime.now().isoformat() + "Z"
        }
        tasks.append(new_task)
        self._task_cache = tasks
        self._save_tasks()

        result = {"success": True, "message": f"Task {new_task['id']} created.", **new_task}
        self.log_action("task", {"action": "create", "title": title}, result)
        return result

    async def _update(
        self,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update an existing task's status, priority, or description."""
        if not task_id:
            result = {"error": "task_id is required for update action."}
            self.log_action("task", {"action": "update"}, result)
            return result

        tasks = self._load_tasks()
        task_id = task_id.strip()
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            available = [t["id"] for t in tasks]
            result = {"error": f"Task '{task_id}' not found. Available: {available}"}
            self.log_action("task", {"action": "update", "task_id": task_id}, result)
            return result

        updated_fields = []
        if status is not None:
            task["status"] = status
            updated_fields.append("status")
        if priority is not None:
            task["priority"] = priority
            updated_fields.append("priority")
        if description is not None:
            task["description"] = description
            updated_fields.append("description")

        if not updated_fields:
            result = {"error": "No fields to update. Provide status, priority, or description."}
            self.log_action("task", {"action": "update", "task_id": task_id}, result)
            return result

        self._save_tasks()

        result = {"success": True, "message": f"Task {task_id} updated ({', '.join(updated_fields)}).", **task}
        self.log_action("task", {"action": "update", "task_id": task_id, "updated_fields": updated_fields}, result)
        return result
