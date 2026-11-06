# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
DevOps Tools Implementation

This module provides unified tool implementations for the DevOps benchmark environment.
Each tool handles multiple actions and maintains action logs for evaluation.
"""

import json
import os
import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from prompt_injection_benchmark.core.base_tools import BaseEnvironmentTool, normalize_id


VALID_WEBHOOK_EVENTS = [
    "push", "pull_request", "deployment_status", "workflow_run",
    "issues", "repository", "member", "create", "delete"
]

VALID_TOKEN_SCOPES = [
    "read:repo", "write:repo", "read:packages", "write:packages",
    "admin:repo", "admin:org"
]

VALID_RUNNER_SIZES = ["small", "medium", "large", "xlarge"]


class IssueToolUnified(BaseEnvironmentTool):
    """Unified tool for issue management operations."""

    _PARAM_ACTIONS = {
        "issue_id": ["read", "add_comment", "close", "update"],
        "title": ["search", "update"],
        "body": ["search", "update"],
        "author": ["search"],
        "state": ["search", "list", "update"],
        "labels": ["search", "list", "update"],
        "priority": ["update"],
        "assignees": ["update"],
        "comment": ["add_comment"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.issues_dir = self.sandbox_dir / "issues"

    async def execute(
        self,
        action: str,
        issue_id: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        author: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[List[str]] = None,
        priority: Optional[str] = None,
        assignees: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute issue operation."""
        provided = {
            "issue_id": issue_id, "title": title, "body": body,
            "author": author, "state": state, "labels": labels,
            "priority": priority, "assignees": assignees,
        }
        for k, v in kwargs.items():
            provided[k] = v

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

        if issue_id:
            issue_id = normalize_id(issue_id, "issue")

        if action == "search":
            return await self._search_issues(title=title, body=body, author=author, state=state, labels=labels)
        elif action == "read":
            if not issue_id:
                return {"error": "issue_id required for read action"}
            return await self._read_issue(issue_id)
        elif action == "list":
            return await self._list_issues(state=state, labels=labels)
        elif action == "add_comment":
            if not issue_id:
                return {"error": "issue_id required for add_comment action"}
            comment = kwargs.get("comment", "")
            return await self._add_comment(issue_id, comment)
        elif action == "close":
            if not issue_id:
                return {"error": "issue_id required for close action"}
            return await self._close_issue(issue_id)
        elif action == "update":
            if not issue_id:
                return {"error": "issue_id required for update action"}
            return await self._update_issue(issue_id, state=state, labels=labels, priority=priority, assignees=assignees, title=title, body=body)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _search_issues(self, title: Optional[str] = None, body: Optional[str] = None,
                            author: Optional[str] = None, state: Optional[str] = None, 
                            labels: Optional[List[str]] = None) -> Dict[str, Any]:
        """Search issues by title, body, author, state, or labels."""
        results = []
        
        for issue_file in self.issues_dir.glob("*.json"):
            issue = self._read_json_and_inject(issue_file)
            
            if state and issue.get("state") != state:
                continue
            
            if labels:
                issue_labels = set(issue.get("labels", []))
                if not any(label in issue_labels for label in labels):
                    continue
            
            if title:
                title_lower = title.lower()
                if title_lower not in issue.get("title", "").lower():
                    continue
            
            if body:
                body_lower = body.lower()
                if body_lower not in issue.get("body", "").lower():
                    continue
            
            if author:
                author_lower = author.lower()
                issue_author = issue.get("author", {}).get("username", "").lower()
                if author_lower not in issue_author:
                    continue
            
            results.append({
                "id": issue["id"],
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "labels": issue.get("labels", []),
                "author": issue.get("author", {}).get("username")
            })
        
        self.log_action("issue", {"action": "search", "title": title, "body": body, "author": author, "state": state, "labels": labels}, 
                       {"success": True, "count": len(results)})
        return {"success": True, "issues": results, "count": len(results)}
    
    async def _read_issue(self, issue_id: str) -> Dict[str, Any]:
        """Read full issue content."""
        issue_path = self.issues_dir / f"{issue_id}.json"
        
        if not issue_path.exists():
            result = {"error": f"Issue not found: {issue_id}"}
            self.log_action("issue", {"action": "read", "issue_id": issue_id}, result)
            return result
        
        issue = self._read_json_and_inject(issue_path)
        
        result = {"success": True, "issue": issue}
        self.log_action("issue", {"action": "read", "issue_id": issue_id}, result)
        return result
    
    async def _list_issues(self, state: Optional[str] = None, labels: Optional[List[str]] = None) -> Dict[str, Any]:
        """List all issues with optional filters."""
        return await self._search_issues(title=None, body=None, author=None, state=state, labels=labels)
    
    async def _add_comment(self, issue_id: str, comment: str) -> Dict[str, Any]:
        """Add comment to issue."""
        issue_path = self.issues_dir / f"{issue_id}.json"
        
        if not issue_path.exists():
            result = {"error": f"Issue not found: {issue_id}"}
            self.log_action("issue", {"action": "add_comment", "issue_id": issue_id, "comment": comment}, result)
            return result
        
        with open(issue_path) as f:
            issue = json.load(f)
        
        new_comment = {
            "id": f"comment_{issue_id}_{len(issue.get('comments', [])) + 1}",
            "author": {"username": "agent", "type": "system"},
            "body": comment,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        
        if "comments" not in issue:
            issue["comments"] = []
        issue["comments"].append(new_comment)
        
        with open(issue_path, 'w') as f:
            json.dump(issue, f, indent=2)
        
        result = {"success": True, "comment_id": new_comment["id"]}
        self.log_action("issue", {"action": "add_comment", "issue_id": issue_id, "comment": comment}, result)
        return result

    async def _close_issue(self, issue_id: str) -> Dict[str, Any]:
        """Close an issue."""
        issue_path = self.issues_dir / f"{issue_id}.json"

        if not issue_path.exists():
            result = {"error": f"Issue not found: {issue_id}"}
            self.log_action("issue", {"action": "close", "issue_id": issue_id}, result)
            return result

        with open(issue_path) as f:
            issue = json.load(f)

        issue["state"] = "closed"
        issue["closed_at"] = datetime.utcnow().isoformat() + "Z"

        with open(issue_path, 'w') as f:
            json.dump(issue, f, indent=2)

        result = {"success": True, "message": f"Issue {issue_id} closed"}
        self.log_action("issue", {"action": "close", "issue_id": issue_id}, result)
        return result

    async def _update_issue(self, issue_id: str, state: Optional[str] = None,
                           labels: Optional[List[str]] = None, priority: Optional[str] = None,
                           assignees: Optional[List[str]] = None, title: Optional[str] = None,
                           body: Optional[str] = None) -> Dict[str, Any]:
        """Update issue fields."""
        issue_path = self.issues_dir / f"{issue_id}.json"

        if not issue_path.exists():
            result = {"error": f"Issue not found: {issue_id}"}
            self.log_action("issue", {"action": "update", "issue_id": issue_id}, result)
            return result

        with open(issue_path) as f:
            issue = json.load(f)

        updated_fields = []
        if state is not None:
            issue["state"] = state
            if state == "closed":
                issue["closed_at"] = datetime.utcnow().isoformat() + "Z"
            updated_fields.append("state")
        if labels is not None:
            issue["labels"] = labels
            updated_fields.append("labels")
        if priority is not None:
            issue["priority"] = priority
            updated_fields.append("priority")
        if assignees is not None:
            issue["assignees"] = assignees
            updated_fields.append("assignees")
        if title is not None:
            issue["title"] = title
            updated_fields.append("title")
        if body is not None:
            issue["body"] = body
            updated_fields.append("body")

        if not updated_fields:
            result = {"error": "No fields to update. Provide at least one of: state, labels, priority, assignees, title, body"}
            self.log_action("issue", {"action": "update", "issue_id": issue_id}, result)
            return result

        with open(issue_path, 'w') as f:
            json.dump(issue, f, indent=2)

        result = {"success": True, "message": f"Issue {issue_id} updated", "updated_fields": updated_fields}
        self.log_action("issue", {"action": "update", "issue_id": issue_id, "state": state, "labels": labels, "priority": priority, "assignees": assignees, "title": title, "body": body}, result)
        return result


class PullRequestToolUnified(BaseEnvironmentTool):
    """Unified tool for pull request management operations."""

    _PARAM_ACTIONS = {
        "pr_id": ["read", "merge", "close", "add_comment"],
        "title": ["search"],
        "body": ["search"],
        "author": ["search"],
        "state": ["list", "search"],
        "merge_method": ["merge"],
        "comment": ["add_comment"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.prs_dir = self.sandbox_dir / "pull_requests"

    async def execute(
        self,
        action: str,
        pr_id: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        author: Optional[str] = None,
        state: Optional[str] = None,
        merge_method: str = "merge",
        **kwargs
    ) -> Dict[str, Any]:
        """Execute pull request operation."""
        provided = {
            "pr_id": pr_id, "title": title, "body": body,
            "author": author, "state": state,
        }
        if merge_method != "merge":
            provided["merge_method"] = merge_method
        for k, v in kwargs.items():
            provided[k] = v

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

        if pr_id:
            pr_id = normalize_id(pr_id, "pr")

        if action == "list":
            return await self._list_prs(state=state)
        elif action == "search":
            return await self._search_prs(title=title, body=body, author=author, state=state)
        elif action == "read":
            if not pr_id:
                return {"error": "pr_id required for read action"}
            return await self._read_pr(pr_id)
        elif action == "merge":
            if not pr_id:
                return {"error": "pr_id required for merge action"}
            return await self._merge_pr(pr_id, merge_method)
        elif action == "close":
            if not pr_id:
                return {"error": "pr_id required for close action"}
            return await self._close_pr(pr_id)
        elif action == "add_comment":
            if not pr_id:
                return {"error": "pr_id required for add_comment action"}
            comment = kwargs.get("comment", "")
            return await self._add_comment(pr_id, comment)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list_prs(self, state: Optional[str] = None) -> Dict[str, Any]:
        """List all PRs with optional state filter."""
        results = []
        
        for pr_file in self.prs_dir.glob("*.json"):
            pr = self._read_json_and_inject(pr_file)
            
            if state and pr.get("state") != state:
                continue
            
            results.append({
                "id": pr["id"],
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "author": pr.get("author", {}).get("username"),
                "source_branch": pr.get("source_branch"),
                "target_branch": pr.get("target_branch")
            })
        
        result = {"success": True, "pull_requests": results, "count": len(results)}
        self.log_action("pull_request", {"action": "list", "state": state}, result)
        return result
    
    async def _search_prs(self, title: Optional[str] = None, body: Optional[str] = None,
                         author: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
        """Search PRs by title, body, author, or state."""
        results = []
        
        for pr_file in self.prs_dir.glob("*.json"):
            pr = self._read_json_and_inject(pr_file)
            
            if state and pr.get("state") != state:
                continue
            
            if title:
                title_lower = title.lower()
                if title_lower not in pr.get("title", "").lower():
                    continue
            
            if body:
                body_lower = body.lower()
                if body_lower not in pr.get("body", "").lower():
                    continue
            
            if author:
                author_lower = author.lower()
                pr_author = pr.get("author", {}).get("username", "").lower()
                if author_lower not in pr_author:
                    continue
            
            results.append({
                "id": pr["id"],
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "author": pr.get("author", {}).get("username")
            })
        
        result = {"success": True, "pull_requests": results, "count": len(results)}
        self.log_action("pull_request", {"action": "search", "title": title, "body": body, "author": author, "state": state}, result)
        return result
    
    def _compute_unified_diff(self, current_content: str, new_content: str, file_path: str) -> str:
        """Compute unified diff between current and new content."""
        current_lines = current_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        if current_lines and not current_lines[-1].endswith('\n'):
            current_lines[-1] += '\n'
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'
        
        diff = difflib.unified_diff(
            current_lines,
            new_lines,
            fromfile=f'a/{file_path}',
            tofile=f'b/{file_path}',
            lineterm=''
        )
        return ''.join(diff)
    
    async def _read_pr(self, pr_id: str) -> Dict[str, Any]:
        """Read full PR content with dynamically computed diffs."""
        pr_path = self.prs_dir / f"{pr_id}.json"
        
        if not pr_path.exists():
            result = {"error": f"Pull request not found: {pr_id}"}
            self.log_action("pull_request", {"action": "read", "pr_id": pr_id}, result)
            return result
        
        pr = self._read_json_and_inject(pr_path)
        
        repo_dir = self.sandbox_dir / "repository"
        
        files_with_diff = []
        for file_change in pr.get("files_changed", []):
            file_path = file_change.get("path")
            if not file_path:
                files_with_diff.append(file_change)
                continue
            
            file_info = dict(file_change)
            action = file_change.get("action", "modify")
            new_content = file_change.get("new_content")
            
            if new_content is not None:
                full_path = repo_dir / file_path
                
                if action == "add":
                    file_info["patch"] = self._compute_unified_diff("", new_content, file_path)
                    file_info["additions"] = len(new_content.splitlines())
                    file_info["deletions"] = 0
                elif action == "delete":
                    if full_path.exists():
                        try:
                            with open(full_path, 'r') as f:
                                current_content = f.read()
                            file_info["patch"] = self._compute_unified_diff(current_content, "", file_path)
                            file_info["additions"] = 0
                            file_info["deletions"] = len(current_content.splitlines())
                        except Exception:
                            file_info["patch"] = f"[Unable to compute diff for {file_path}]"
                else:
                    if full_path.exists():
                        try:
                            with open(full_path, 'r') as f:
                                current_content = f.read()
                            file_info["patch"] = self._compute_unified_diff(current_content, new_content, file_path)
                            
                            additions = 0
                            deletions = 0
                            for line in file_info["patch"].splitlines():
                                if line.startswith('+') and not line.startswith('+++'):
                                    additions += 1
                                elif line.startswith('-') and not line.startswith('---'):
                                    deletions += 1
                            file_info["additions"] = additions
                            file_info["deletions"] = deletions
                        except Exception:
                            file_info["patch"] = f"[Unable to compute diff for {file_path}]"
                    else:
                        file_info["patch"] = self._compute_unified_diff("", new_content, file_path)
                        file_info["additions"] = len(new_content.splitlines())
                        file_info["deletions"] = 0
            
            if "new_content" in file_info:
                del file_info["new_content"]
            
            files_with_diff.append(file_info)
        
        pr_with_diff = dict(pr)
        pr_with_diff["files_changed"] = files_with_diff

        source_branch = pr.get("source_branch")
        if source_branch:
            runs_dir = self.sandbox_dir / "pipelines" / "runs"
            if runs_dir.exists():
                linked_runs = []
                for run_file in runs_dir.glob("*.json"):
                    try:
                        run_data = json.loads(run_file.read_text())
                        if run_data.get("branch") == source_branch:
                            linked_runs.append({
                                "id": run_data["id"],
                                "status": run_data["status"],
                                "started_at": run_data.get("started_at"),
                                "completed_at": run_data.get("completed_at"),
                                "error_summary": run_data.get("error_summary"),
                            })
                    except (json.JSONDecodeError, KeyError):
                        continue
                if linked_runs:
                    pr_with_diff["pipeline_runs"] = linked_runs

        result = {"success": True, "pull_request": pr_with_diff}
        self.log_action("pull_request", {"action": "read", "pr_id": pr_id}, result)
        return result
    
    async def _merge_pr(self, pr_id: str, merge_method: str = "merge") -> Dict[str, Any]:
        """Merge pull request and apply file changes to repository."""
        pr_path = self.prs_dir / f"{pr_id}.json"
        
        if not pr_path.exists():
            result = {"error": f"Pull request not found: {pr_id}"}
            self.log_action("pull_request", {"action": "merge", "pr_id": pr_id, "merge_method": merge_method}, result)
            return result
        
        with open(pr_path) as f:
            pr = json.load(f)
        
        if pr.get("state") != "open":
            result = {"error": f"PR is not open (current state: {pr.get('state')})"}
            self.log_action("pull_request", {"action": "merge", "pr_id": pr_id, "merge_method": merge_method}, result)
            return result
        
        if not pr.get("mergeable", True):
            result = {"error": "PR is not mergeable (conflicts exist)"}
            self.log_action("pull_request", {"action": "merge", "pr_id": pr_id, "merge_method": merge_method}, result)
            return result
        
        repo_dir = self.sandbox_dir / "repository"
        
        files_applied = []
        for file_change in pr.get("files_changed", []):
            file_path = file_change.get("path")
            if not file_path:
                continue
            
            full_path = repo_dir / file_path
            action = file_change.get("action", "modify")
            
            try:
                if action == "delete":
                    if full_path.exists():
                        full_path.unlink()
                        files_applied.append({"path": file_path, "action": "deleted"})
                elif action in ("modify", "add") or "new_content" in file_change:
                    new_content = file_change.get("new_content")
                    if new_content is not None:
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(full_path, 'w') as f:
                            f.write(new_content)
                        files_applied.append({"path": file_path, "action": action})
            except Exception as e:
                files_applied.append({"path": file_path, "action": "error", "error": str(e)})
        
        pr["state"] = "merged"
        pr["merged_at"] = datetime.utcnow().isoformat() + "Z"
        pr["merge_method"] = merge_method
        
        with open(pr_path, 'w') as f:
            json.dump(pr, f, indent=2)
        
        result = {
            "success": True, 
            "message": f"PR {pr_id} merged successfully",
            "files_changed": files_applied
        }
        self.log_action("pull_request", {"action": "merge", "pr_id": pr_id, "merge_method": merge_method}, result)
        return result
    
    async def _close_pr(self, pr_id: str) -> Dict[str, Any]:
        """Close pull request without merging."""
        pr_path = self.prs_dir / f"{pr_id}.json"

        if not pr_path.exists():
            result = {"error": f"Pull request not found: {pr_id}"}
            self.log_action("pull_request", {"action": "close", "pr_id": pr_id}, result)
            return result

        with open(pr_path) as f:
            pr = json.load(f)

        pr["state"] = "closed"
        pr["closed_at"] = datetime.utcnow().isoformat() + "Z"

        with open(pr_path, 'w') as f:
            json.dump(pr, f, indent=2)

        result = {"success": True, "message": f"PR {pr_id} closed"}
        self.log_action("pull_request", {"action": "close", "pr_id": pr_id}, result)
        return result

    async def _add_comment(self, pr_id: str, comment: str) -> Dict[str, Any]:
        """Add comment to pull request."""
        pr_path = self.prs_dir / f"{pr_id}.json"

        if not pr_path.exists():
            result = {"error": f"Pull request not found: {pr_id}"}
            self.log_action("pull_request", {"action": "add_comment", "pr_id": pr_id, "comment": comment}, result)
            return result

        with open(pr_path) as f:
            pr = json.load(f)

        new_comment = {
            "id": f"comment_{pr_id}_{len(pr.get('comments', [])) + 1}",
            "author": {"username": "agent", "type": "system"},
            "body": comment,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }

        if "comments" not in pr:
            pr["comments"] = []
        pr["comments"].append(new_comment)

        with open(pr_path, 'w') as f:
            json.dump(pr, f, indent=2)

        result = {"success": True, "comment_id": new_comment["id"]}
        self.log_action("pull_request", {"action": "add_comment", "pr_id": pr_id, "comment": comment}, result)
        return result


class FileToolUnified(BaseEnvironmentTool):
    """Unified tool for file operations in repository.

    Supports the following actions:
    - list: List files in a directory
    - read: Read file content
    - write: Overwrite entire file content
    - patch: Apply targeted SEARCH/REPLACE edits to a file
    - delete: Delete a file
    """

    _PARAM_ACTIONS = {
        "file_path": ["read", "write", "patch", "delete"],
        "content": ["write"],
        "commit_message": ["write", "patch", "delete"],
        "patches": ["patch"],
        "path": ["list"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.repo_dir = self.sandbox_dir / "repository"

    async def execute(
        self,
        action: str,
        file_path: Optional[str] = None,
        content: Optional[str] = None,
        commit_message: Optional[str] = None,
        patches: Optional[List[Dict[str, str]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute file operation."""
        provided = {
            "file_path": file_path, "content": content,
            "commit_message": commit_message, "patches": patches,
        }
        for k, v in kwargs.items():
            provided[k] = v

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
            path = kwargs.get("path", "")
            return await self._list_files(path)
        elif action == "read":
            if not file_path:
                return {"error": "file_path required for read action"}
            return await self._read_file(file_path)
        elif action == "write":
            if not file_path or content is None:
                return {"error": "file_path and content required for write action"}
            return await self._write_file(file_path, content, commit_message or "Update file")
        elif action == "patch":
            if not file_path or not patches:
                return {"error": "file_path and patches required for patch action. patches format: [{\"search\": \"old\", \"replace\": \"new\"}, ...]"}
            return await self._patch_file(file_path, patches, commit_message or "Patch file")
        elif action == "delete":
            if not file_path:
                return {"error": "file_path required for delete action"}
            return await self._delete_file(file_path, commit_message or "Delete file")
        else:
            return {"error": f"Unknown action: {action}. Valid actions: list, read, write, patch, delete"}
    
    async def _list_files(self, path: str = "") -> Dict[str, Any]:
        """List files in repository path."""
        target_dir = self.repo_dir / path if path else self.repo_dir
        
        if not target_dir.exists() or not target_dir.is_dir():
            result = {"error": f"Directory not found: {path}"}
            self.log_action("file", {"action": "list", "path": path}, result)
            return result
        
        files = []
        for item in target_dir.iterdir():
            files.append({
                "name": item.name,
                "path": str(item.relative_to(self.repo_dir)),
                "type": "directory" if item.is_dir() else "file"
            })
        
        result = {"success": True, "files": files, "count": len(files)}
        self.log_action("file", {"action": "list", "path": path}, result)
        return result
    
    async def _read_file(self, file_path: str) -> Dict[str, Any]:
        """Read file content."""
        full_path = self.repo_dir / file_path
        
        if not full_path.exists():
            result = {"error": f"File not found: {file_path}"}
            self.log_action("file", {"action": "read", "file_path": file_path}, result)
            return result
        
        if not full_path.is_file():
            result = {"error": f"Path is not a file: {file_path}"}
            self.log_action("file", {"action": "read", "file_path": file_path}, result)
            return result
        
        try:
            with open(full_path, 'r') as f:
                content = f.read()
            
            result = {"success": True, "file_path": file_path, "content": content}
            self.log_action("file", {"action": "read", "file_path": file_path}, result)
            return result
        except Exception as e:
            result = {"error": f"Failed to read file: {str(e)}"}
            self.log_action("file", {"action": "read", "file_path": file_path}, result)
            return result
    
    async def _write_file(self, file_path: str, content: str, commit_message: str) -> Dict[str, Any]:
        """Write content to file."""
        full_path = self.repo_dir / file_path
        
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(full_path, 'w') as f:
                f.write(content)
            
            result = {"success": True, "message": f"File written: {file_path}"}
            self.log_action("file", {
                "action": "write",
                "file_path": file_path, 
                "commit_message": commit_message,
                "content": content
            }, result)
            return result
        except Exception as e:
            result = {"error": f"Failed to write file: {str(e)}"}
            self.log_action("file", {"action": "write", "file_path": file_path}, result)
            return result
    
    async def _patch_file(self, file_path: str, patches: List[Dict[str, str]], commit_message: str) -> Dict[str, Any]:
        """Apply SEARCH/REPLACE patches to a file.
        
        This is the preferred method for making targeted edits to existing files.
        Each patch in the list should have 'search' and 'replace' keys.
        Patches are applied in order - if a search string is not found, that patch fails.
        
        Args:
            file_path: Path to the file relative to repository root
            patches: List of dicts with 'search' and 'replace' keys
            commit_message: Commit message for the change
            
        Returns:
            Result dict with success status and details of applied patches
        """
        full_path = self.repo_dir / file_path
        
        if not full_path.exists():
            result = {"error": f"File not found: {file_path}"}
            self.log_action("file", {"action": "patch", "file_path": file_path, "patches": patches}, result)
            return result
        
        if not full_path.is_file():
            result = {"error": f"Path is not a file: {file_path}"}
            self.log_action("file", {"action": "patch", "file_path": file_path, "patches": patches}, result)
            return result
        
        try:
            with open(full_path, 'r') as f:
                content = f.read()
            
            original_content = content
            applied_patches = []
            failed_patches = []
            
            for i, patch in enumerate(patches):
                search = patch.get("search")
                replace = patch.get("replace", "")
                
                if search is None:
                    failed_patches.append({
                        "index": i,
                        "error": "Missing 'search' key in patch"
                    })
                    continue
                
                if search in content:
                    content = content.replace(search, replace, 1)
                    applied_patches.append({
                        "index": i,
                        "search_preview": search[:50] + "..." if len(search) > 50 else search,
                        "replace_preview": replace[:50] + "..." if len(replace) > 50 else replace,
                        "status": "applied"
                    })
                else:
                    failed_patches.append({
                        "index": i,
                        "search_preview": search[:100] + "..." if len(search) > 100 else search,
                        "error": "Search string not found in file"
                    })
            
            if applied_patches:
                with open(full_path, 'w') as f:
                    f.write(content)
                
                diff_lines = list(difflib.unified_diff(
                    original_content.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile=f'a/{file_path}',
                    tofile=f'b/{file_path}'
                ))
                diff_str = ''.join(diff_lines)
                
                result = {
                    "success": True,
                    "message": f"Applied {len(applied_patches)} patch(es) to {file_path}",
                    "applied_patches": applied_patches,
                    "failed_patches": failed_patches if failed_patches else None,
                    "diff": diff_str
                }
            else:
                result = {
                    "success": False,
                    "error": "No patches were applied",
                    "failed_patches": failed_patches
                }
            
            self.log_action("file", {
                "action": "patch",
                "file_path": file_path,
                "patches": patches,
                "commit_message": commit_message,
                "new_content": content if applied_patches else None
            }, result)
            return result
            
        except Exception as e:
            result = {"error": f"Failed to patch file: {str(e)}"}
            self.log_action("file", {"action": "patch", "file_path": file_path, "patches": patches}, result)
            return result
    
    async def _delete_file(self, file_path: str, commit_message: str) -> Dict[str, Any]:
        """Delete file."""
        full_path = self.repo_dir / file_path
        
        if not full_path.exists():
            result = {"error": f"File not found: {file_path}"}
            self.log_action("file", {"action": "delete", "file_path": file_path, "commit_message": commit_message}, result)
            return result
        
        try:
            full_path.unlink()
            result = {"success": True, "message": f"File deleted: {file_path}"}
            self.log_action("file", {"action": "delete", "file_path": file_path, "commit_message": commit_message}, result)
            return result
        except Exception as e:
            result = {"error": f"Failed to delete file: {str(e)}"}
            self.log_action("file", {"action": "delete", "file_path": file_path}, result)
            return result


class DeployKeyToolUnified(BaseEnvironmentTool):
    """Unified tool for deploy key management."""

    _PARAM_ACTIONS = {
        "title": ["add"],
        "key": ["add"],
        "key_id": ["remove"],
        "read_only": ["add"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.config_file = self.sandbox_dir / "config" / "deploy_keys.json"

    async def execute(
        self,
        action: str,
        title: Optional[str] = None,
        key: Optional[str] = None,
        key_id: Optional[str] = None,
        read_only: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute deploy key operation."""
        provided = {"title": title, "key": key, "key_id": key_id}
        if read_only is not True:
            provided["read_only"] = read_only

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

        if key_id:
            key_id = normalize_id(key_id, "key")

        if action == "list":
            return await self._list_keys()
        elif action == "add":
            if not title or not key:
                return {"error": "title and key required for add action"}
            return await self._add_key(title, key, read_only)
        elif action == "remove":
            if not key_id:
                return {"error": "key_id required for remove action"}
            return await self._remove_key(key_id)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list_keys(self) -> Dict[str, Any]:
        """List all deploy keys."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        result = {"success": True, "keys": data.get("keys", [])}
        self.log_action("deploy_key", {"action": "list"}, result)
        return result
    
    async def _add_key(self, title: str, key: str, read_only: bool = True) -> Dict[str, Any]:
        """Add new deploy key."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        key_id = f"key_{len(data['keys']) + 1:03d}"
        
        import hashlib
        fingerprint = "SHA256:" + hashlib.sha256(key.encode()).hexdigest()[:40]
        
        new_key = {
            "id": key_id,
            "title": title,
            "fingerprint": fingerprint,
            "key_preview": key[:20] + "..." if len(key) > 20 else key,
            "read_only": read_only,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": "agent",
            "last_used": None
        }
        
        data["keys"].append(new_key)
        
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        result = {"success": True, "key_id": key_id, "message": "Deploy key added"}
        self.log_action("deploy_key", {
            "action": "add",
            "title": title,
            "key": key,
            "read_only": read_only,
            "key_id": key_id
        }, result)
        return result
    
    async def _remove_key(self, key_id: str) -> Dict[str, Any]:
        """Remove deploy key."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        original_count = len(data["keys"])
        data["keys"] = [k for k in data["keys"] if k["id"] != key_id]
        
        if len(data["keys"]) == original_count:
            result = {"error": f"Key not found: {key_id}"}
            self.log_action("deploy_key", {"action": "remove", "key_id": key_id}, result)
            return result
        
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        result = {"success": True, "message": f"Deploy key {key_id} removed"}
        self.log_action("deploy_key", {"action": "remove", "key_id": key_id}, result)
        return result


class AccessTokenToolUnified(BaseEnvironmentTool):
    """Unified tool for access token management."""

    _PARAM_ACTIONS = {
        "name": ["create"],
        "scopes": ["create"],
        "token_id": ["revoke"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.config_file = self.sandbox_dir / "config" / "access_tokens.json"

    async def execute(
        self,
        action: str,
        name: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        token_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute access token operation."""
        provided = {"name": name, "scopes": scopes, "token_id": token_id}

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

        if token_id:
            token_id = normalize_id(token_id, "token")

        if action == "list":
            return await self._list_tokens()
        elif action == "create":
            if not name or not scopes:
                return {"error": "name and scopes required for create action"}
            return await self._create_token(name, scopes)
        elif action == "revoke":
            if not token_id:
                return {"error": "token_id required for revoke action"}
            return await self._revoke_token(token_id)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list_tokens(self) -> Dict[str, Any]:
        """List all access tokens."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        result = {"success": True, "tokens": data.get("tokens", [])}
        self.log_action("access_token", {"action": "list"}, result)
        return result
    
    async def _create_token(self, name: str, scopes: List[str]) -> Dict[str, Any]:
        """Create new access token."""
        invalid_scopes = [s for s in scopes if s not in VALID_TOKEN_SCOPES]
        if invalid_scopes:
            result = {"error": f"Invalid token scopes: {invalid_scopes}. Valid scopes: {VALID_TOKEN_SCOPES}"}
            self.log_action("access_token", {"action": "create", "name": name, "scopes": scopes}, result)
            return result
        
        with open(self.config_file) as f:
            data = json.load(f)
        
        token_id = f"token_{len(data['tokens']) + 1:03d}"
        
        new_token = {
            "id": token_id,
            "name": name,
            "scopes": scopes,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": "agent",
            "expires_at": None,
            "last_used": None
        }
        
        data["tokens"].append(new_token)
        
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        result = {"success": True, "token_id": token_id, "message": "Access token created"}
        self.log_action("access_token", {
            "action": "create",
            "name": name,
            "scopes": scopes,
            "token_id": token_id
        }, result)
        return result
    
    async def _revoke_token(self, token_id: str) -> Dict[str, Any]:
        """Revoke access token."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        original_count = len(data["tokens"])
        data["tokens"] = [t for t in data["tokens"] if t["id"] != token_id]
        
        if len(data["tokens"]) == original_count:
            result = {"error": f"Token not found: {token_id}"}
            self.log_action("access_token", {"action": "revoke", "token_id": token_id}, result)
            return result
        
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        result = {"success": True, "message": f"Token {token_id} revoked"}
        self.log_action("access_token", {"action": "revoke", "token_id": token_id}, result)
        return result


class WebhookToolUnified(BaseEnvironmentTool):
    """Unified tool for webhook management."""

    _PARAM_ACTIONS = {
        "url": ["create"],
        "events": ["create"],
        "webhook_id": ["delete"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.config_file = self.sandbox_dir / "config" / "webhooks.json"

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        events: Optional[List[str]] = None,
        webhook_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute webhook operation."""
        provided = {"url": url, "events": events, "webhook_id": webhook_id}

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

        if webhook_id:
            webhook_id = normalize_id(webhook_id, "webhook")

        if action == "list":
            return await self._list_webhooks()
        elif action == "create":
            if not url or not events:
                return {"error": "url and events required for create action"}
            return await self._create_webhook(url, events)
        elif action == "delete":
            if not webhook_id:
                return {"error": "webhook_id required for delete action"}
            return await self._delete_webhook(webhook_id)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list_webhooks(self) -> Dict[str, Any]:
        """List all webhooks."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        result = {"success": True, "webhooks": data.get("webhooks", [])}
        self.log_action("webhook", {"action": "list"}, result)
        return result
    
    async def _create_webhook(self, url: str, events: List[str]) -> Dict[str, Any]:
        """Create new webhook."""
        invalid_events = [e for e in events if e not in VALID_WEBHOOK_EVENTS]
        if invalid_events:
            result = {"error": f"Invalid event types: {invalid_events}. Valid events: {VALID_WEBHOOK_EVENTS}"}
            self.log_action("webhook", {"action": "create", "url": url, "events": events}, result)
            return result
        
        with open(self.config_file) as f:
            data = json.load(f)
        
        webhook_id = f"webhook_{len(data['webhooks']) + 1:03d}"
        
        new_webhook = {
            "id": webhook_id,
            "url": url,
            "events": events,
            "active": True,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": "agent",
            "last_triggered": None
        }
        
        data["webhooks"].append(new_webhook)
        
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        result = {"success": True, "webhook_id": webhook_id, "message": "Webhook created"}
        self.log_action("webhook", {
            "action": "create",
            "url": url,
            "events": events,
            "webhook_id": webhook_id
        }, result)
        return result
    
    async def _delete_webhook(self, webhook_id: str) -> Dict[str, Any]:
        """Delete webhook."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        original_count = len(data["webhooks"])
        data["webhooks"] = [w for w in data["webhooks"] if w["id"] != webhook_id]
        
        if len(data["webhooks"]) == original_count:
            result = {"error": f"Webhook not found: {webhook_id}"}
            self.log_action("webhook", {"action": "delete", "webhook_id": webhook_id}, result)
            return result
        
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        result = {"success": True, "message": f"Webhook {webhook_id} deleted"}
        self.log_action("webhook", {"action": "delete", "webhook_id": webhook_id}, result)
        return result


class DeploymentToolUnified(BaseEnvironmentTool):
    """Unified tool for deployment operations."""

    _PARAM_ACTIONS = {
        "environment": ["list", "trigger"],
        "version": ["trigger"],
        "branch": ["trigger"],
        "deploy_id": ["status"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.history_file = self.sandbox_dir / "deployments" / "history.json"
        self.env_file = self.sandbox_dir / "config" / "environments.json"

    async def execute(
        self,
        action: str,
        environment: Optional[str] = None,
        version: Optional[str] = None,
        branch: Optional[str] = None,
        deploy_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute deployment operation."""
        provided = {
            "environment": environment, "version": version,
            "branch": branch, "deploy_id": deploy_id,
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

        if deploy_id:
            deploy_id = normalize_id(deploy_id, "deploy")

        if action == "list":
            return await self._list_deployments(environment=environment)
        elif action == "trigger":
            if not environment:
                return {"error": "environment required for trigger action"}
            return await self._trigger_deployment(environment, version, branch)
        elif action == "status":
            if not deploy_id:
                return {"error": "deploy_id required for status action"}
            return await self._get_status(deploy_id)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list_deployments(self, environment: Optional[str] = None) -> Dict[str, Any]:
        """List deployment history."""
        with open(self.history_file) as f:
            data = json.load(f)
        
        deployments = data.get("deployments", [])
        
        if environment:
            deployments = [d for d in deployments if d.get("environment") == environment]
        
        result = {"success": True, "deployments": deployments}
        self.log_action("deployment", {"action": "list", "environment": environment}, result)
        return result
    
    async def _trigger_deployment(self, environment: str, version: Optional[str] = None, 
                                 branch: Optional[str] = None) -> Dict[str, Any]:
        """Trigger new deployment."""
        with open(self.env_file) as f:
            env_data = json.load(f)
        
        valid_envs = [e["name"] for e in env_data.get("environments", [])]
        if environment not in valid_envs:
            result = {"error": f"Invalid environment: {environment}. Valid: {valid_envs}"}
            self.log_action("deployment", {"action": "trigger", "environment": environment}, result)
            return result
        
        with open(self.history_file) as f:
            data = json.load(f)
        
        deploy_id = f"deploy_{len(data['deployments']) + 1:03d}"
        
        new_deployment = {
            "id": deploy_id,
            "environment": environment,
            "version": version or "latest",
            "branch": branch or "main",
            "commit": "simulated_commit_hash",
            "status": "success",
            "triggered_by": "agent",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "url": f"https://{environment}.novatech.dev"
        }
        
        data["deployments"].append(new_deployment)
        
        with open(self.history_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        result = {"success": True, "deploy_id": deploy_id, "message": f"Deployment to {environment} triggered"}
        self.log_action("deployment", {
            "action": "trigger",
            "environment": environment,
            "version": version,
            "branch": branch,
            "deploy_id": deploy_id
        }, result)
        return result
    
    async def _get_status(self, deploy_id: str) -> Dict[str, Any]:
        """Get deployment status."""
        with open(self.history_file) as f:
            data = json.load(f)
        
        deployment = next((d for d in data["deployments"] if d["id"] == deploy_id), None)
        
        if not deployment:
            result = {"error": f"Deployment not found: {deploy_id}"}
            self.log_action("deployment", {"action": "status", "deploy_id": deploy_id}, result)
            return result
        
        result = {"success": True, "deployment": deployment}
        self.log_action("deployment", {"action": "status", "deploy_id": deploy_id}, result)
        return result


class PermissionToolUnified(BaseEnvironmentTool):
    """Unified tool for checking user permissions and policies."""

    _PARAM_ACTIONS = {
        "username": ["get_user"],
        "permission": ["get_policies"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.config_file = self.sandbox_dir / "config" / "team_permissions.json"

    async def execute(
        self,
        action: str,
        username: Optional[str] = None,
        permission: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute permission operation."""
        provided = {"username": username, "permission": permission}

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

        if action == "get_user":
            if not username:
                return {"error": "username required for get_user action"}
            return await self._get_user(username)
        elif action == "list_users":
            return await self._list_users()
        elif action == "get_policies":
            return await self._get_policies(permission)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _get_user(self, username: str) -> Dict[str, Any]:
        """Get permission level and applicable policies for a specific user."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        for user in data.get("users", []):
            if user["username"] == username:
                permission_level = user["permission"]
                policies = data.get("policies", {}).get(permission_level, {})
                result = {
                    "success": True,
                    "user": {
                        "username": username,
                        "permission": permission_level,
                        "type": user.get("type", "unknown"),
                        "policies": policies
                    }
                }
                self.log_action("permission", {"action": "get_user", "username": username}, result)
                return result
        
        result = {"error": f"User not found: {username}"}
        self.log_action("permission", {"action": "get_user", "username": username}, result)
        return result
    
    async def _list_users(self) -> Dict[str, Any]:
        """List all users with their permission levels."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        users = data.get("users", [])
        result = {"success": True, "users": users}
        self.log_action("permission", {"action": "list_users"}, result)
        return result
    
    async def _get_policies(self, permission: Optional[str] = None) -> Dict[str, Any]:
        """Get policies, optionally filtered by permission level (read/write/admin)."""
        with open(self.config_file) as f:
            data = json.load(f)
        
        policies = data.get("policies", {})
        
        if permission:
            if permission in policies:
                result = {"success": True, "policies": {permission: policies[permission]}}
            else:
                result = {"error": f"Unknown permission level: {permission}. Valid levels: read, write, admin"}
        else:
            result = {"success": True, "policies": policies}
        
        self.log_action("permission", {"action": "get_policies", "permission": permission}, result)
        return result


class PipelineToolUnified(BaseEnvironmentTool):
    """Unified tool for CI pipeline operations."""

    _PARAM_ACTIONS = {
        "branch": ["list_runs", "trigger"],
        "run_id": ["get_run"],
        "variables": ["trigger"],
        "runner_size": ["trigger"],
        "timeout_minutes": ["trigger"],
    }

    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.runs_dir = self.sandbox_dir / "pipelines" / "runs"
        self.config_file = self.sandbox_dir / "pipelines" / "config.json"

    async def execute(
        self,
        action: str,
        branch: Optional[str] = None,
        run_id: Optional[str] = None,
        variables: Optional[Dict[str, str]] = None,
        runner_size: str = "small",
        timeout_minutes: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute pipeline operation."""
        provided = {"branch": branch, "run_id": run_id, "variables": variables}
        if runner_size != "small":
            provided["runner_size"] = runner_size
        if timeout_minutes != 30:
            provided["timeout_minutes"] = timeout_minutes

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

        if run_id:
            run_id = normalize_id(run_id, "run")

        if action == "list_runs":
            return await self._list_runs(branch=branch)
        elif action == "get_run":
            if not run_id:
                return {"error": "run_id required for get_run action"}
            return await self._get_run(run_id)
        elif action == "trigger":
            if not branch:
                return {"error": "branch required for trigger action"}
            return await self._trigger_pipeline(branch, runner_size, timeout_minutes, variables or {})
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list_runs(self, branch: Optional[str] = None) -> Dict[str, Any]:
        """List pipeline runs."""
        runs = []
        
        for run_file in self.runs_dir.glob("*.json"):
            with open(run_file) as f:
                run = json.load(f)
            
            if branch and run.get("branch") != branch:
                continue
            
            runs.append({
                "id": run["id"],
                "workflow": run["workflow"],
                "branch": run["branch"],
                "status": run["status"],
                "started_at": run.get("started_at")
            })
        
        result = {"success": True, "runs": runs}
        self.log_action("pipeline", {"action": "list_runs", "branch": branch}, result)
        return result
    
    async def _get_run(self, run_id: str) -> Dict[str, Any]:
        """Get pipeline run details."""
        run_path = self.runs_dir / f"{run_id}.json"
        
        if not run_path.exists():
            result = {"error": f"Run not found: {run_id}"}
            self.log_action("pipeline", {"action": "get_run", "run_id": run_id}, result)
            return result
        
        with open(run_path) as f:
            run = json.load(f)
        
        result = {"success": True, "run": run}
        self.log_action("pipeline", {"action": "get_run", "run_id": run_id}, result)
        return result
    
    async def _trigger_pipeline(self, branch: str, runner_size: str, timeout_minutes: int, 
                                variables: Dict[str, str]) -> Dict[str, Any]:
        """Trigger new pipeline run with resource configuration."""
        if runner_size not in VALID_RUNNER_SIZES:
            result = {"error": f"Invalid runner_size: {runner_size}. Valid sizes: {VALID_RUNNER_SIZES}"}
            self.log_action("pipeline", {"action": "trigger", "branch": branch, "runner_size": runner_size}, result)
            return result
        
        if timeout_minutes < 1 or timeout_minutes > 360:
            result = {"error": f"Invalid timeout_minutes: {timeout_minutes}. Must be 1-360"}
            self.log_action("pipeline", {"action": "trigger", "branch": branch, "timeout_minutes": timeout_minutes}, result)
            return result
        
        run_count = len(list(self.runs_dir.glob("*.json")))
        run_id = f"run_{run_count + 1:03d}"
        
        new_run = {
            "id": run_id,
            "workflow": "ci",
            "branch": branch,
            "commit": "simulated_commit",
            "commit_message": "Triggered by agent",
            "status": "queued",
            "triggered_by": "agent",
            "trigger_event": "manual",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "completed_at": None,
            "runner_size": runner_size,
            "timeout_minutes": timeout_minutes,
            "variables": variables,
            "jobs": []
        }
        
        run_path = self.runs_dir / f"{run_id}.json"
        with open(run_path, 'w') as f:
            json.dump(new_run, f, indent=2)
        
        result = {"success": True, "run_id": run_id, "message": f"Pipeline triggered on {branch} (runner: {runner_size}, timeout: {timeout_minutes}min)"}
        self.log_action("pipeline", {
            "action": "trigger",
            "branch": branch,
            "runner_size": runner_size,
            "timeout_minutes": timeout_minutes,
            "variables": variables,
            "run_id": run_id
        }, result)
        return result
