# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
MCP-based Agent Solver for Inspect AI

Generic solver that connects to MCP servers for any environment.
Handles sandbox initialization, injection configuration, and agent execution.
"""

import os
import sys
import tempfile
import shutil
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

from inspect_ai.solver import TaskState, solver
from inspect_ai.solver import Generate
from inspect_ai.tool import ToolResult
from inspect_ai.tool._tool_def import ToolDef, tool_defs

logger = logging.getLogger(__name__)

SERVER_SIDE_TOOLS = frozenset({"configure_injections", "sandbox_reset"})


def agent_tools(tools: list) -> list:
    """Drop SERVER_SIDE_TOOLS from a list of Tools or ToolDefs."""
    return [t for t in tools
            if (t.name if isinstance(t, ToolDef) else ToolDef(t).name) not in SERVER_SIDE_TOOLS]


def sidecar_log_path(log_dir: str, state) -> Path:
    """Per-sample JSON path under log_dir, unique across variants, epochs and retries."""
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(state.sample_id or "sample"))
    uuid_tag = (str(state.uuid) if state.uuid else "nouuid")[:8]
    path = Path(log_dir) / f"{safe_id}_ep{state.epoch}_{uuid_tag}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def call_tool_directly(
    tool_name: str,
    tool_args: Dict[str, Any],
    tools: List[ToolDef]
) -> ToolResult:
    """
    Directly call a tool bypassing the conversation flow.
    
    This uses the same calling path as inspect_ai's call_tool() function,
    ensuring proper argument conversion and result formatting.
    Useful for system-level setup operations.
    
    Args:
        tool_name: Name of the tool to call
        tool_args: Arguments to pass to the tool
        tools: List of available tool definitions
    
    Returns:
        Tool result in proper inspect_ai format
    """
    from inspect_ai.model._call_tools import tool_params
    
    tool_def = next((t for t in tools if t.name == tool_name), None)
    if not tool_def:
        raise ValueError(f"Tool {tool_name} not found")
    
    arguments = tool_params(tool_args, tool_def.tool)
    
    result: ToolResult = await tool_def.tool(**arguments)
    
    return result


class MCPServerManager:
    """Manages MCP server lifecycle and communication."""
    
    def __init__(self, environment: str, sandbox_dir: Path):
        self.environment = environment
        self.sandbox_dir = sandbox_dir
        self.template_dir = None
        
    def initialize_sandbox(self):
        """Initialize sandbox from template."""
        benchmark_dir = Path(__file__).parent.parent
        self.template_dir = benchmark_dir / "environments" / self.environment / "sandbox_template"
        
        if not self.template_dir.exists():
            raise FileNotFoundError(f"Template not found: {self.template_dir}")
        
        if self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir)
        shutil.copytree(self.template_dir, self.sandbox_dir)
        
        actions_log = self.sandbox_dir / "actions_log.jsonl"
        actions_log.touch()
        
        outbox = self.sandbox_dir / "outbox"
        outbox.mkdir(exist_ok=True)
        (outbox / "sent_emails").mkdir(exist_ok=True)
        (outbox / "shared_documents").mkdir(exist_ok=True)
        
    def get_actions_log(self) -> List[Dict[str, Any]]:
        """Read all actions from log."""
        actions_log = self.sandbox_dir / "actions_log.jsonl"
        actions = []
        
        if actions_log.exists():
            with open(actions_log, 'r') as f:
                for line in f:
                    if line.strip():
                        actions.append(json.loads(line))
        
        return actions
    
    def get_outbox_files(self) -> Dict[str, List[Dict]]:
        """Read all outbox files."""
        outbox = {}
        outbox_dir = self.sandbox_dir / "outbox"
        
        sent_emails = []
        emails_dir = outbox_dir / "sent_emails"
        if emails_dir.exists():
            for email_file in emails_dir.glob("*.json"):
                with open(email_file, 'r') as f:
                    sent_emails.append(json.load(f))
        outbox["sent_emails"] = sent_emails
        
        shared_docs = []
        docs_dir = outbox_dir / "shared_documents"
        if docs_dir.exists():
            for doc_file in docs_dir.glob("*.json"):
                with open(doc_file, 'r') as f:
                    shared_docs.append(json.load(f))
        outbox["shared_documents"] = shared_docs
        
        return outbox


@solver
def MCPAgentSolver(
    environment: str,
    injection_config: Dict[str, str],
    system_prompt: Optional[str] = None,
):
    """
    Solver that uses MCP tools to execute benchmark tasks.

    Args:
        environment: Environment name (productivity, devops, marketplace)
        injection_config: Injection placeholder mappings
        system_prompt: Optional system prompt (None in the benchmark runs)

    Returns:
        Solver function
    """
    
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        """Execute one benchmark task."""
        from inspect_ai.tool import mcp_connection, mcp_tools
        from inspect_ai.tool._mcp.server import mcp_server_stdio
        from inspect_ai.agent import react
        
        with tempfile.TemporaryDirectory(prefix=f"benchmark_{environment}_") as temp_dir:
            sandbox_dir = Path(temp_dir)
            
            server_mgr = MCPServerManager(environment, sandbox_dir)
            
            try:
                server_mgr.initialize_sandbox()
                
                benchmark_dir = Path(__file__).parent.parent
                server_script = benchmark_dir / "environments" / environment / "mcp_server.py"
                
                env = os.environ.copy()
                env[f"{environment.upper()}_SANDBOX_DIR"] = str(sandbox_dir)
                project_root = str(Path(__file__).parent.parent.parent)
                env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
                
                mcp_server = mcp_server_stdio(
                    name=f"{environment.title()} MCP Server",
                    command=sys.executable,
                    args=[str(server_script)],
                    env=env
                )
                
                async with mcp_connection(mcp_server):
                    tools_source = mcp_tools(mcp_server)
                    tools = await tools_source.tools()
                    
                    tdefs = await tool_defs(tools)
                    
                    if injection_config:
                        logger.info(f"Configuring {len(injection_config)} injections...")
                        result = await call_tool_directly(
                            "configure_injections",
                            {"config": injection_config},
                            tdefs
                        )
                        logger.info(f"Injection configuration result: {result}")
                    
                    state.metadata["injection_config"] = injection_config
                    state.metadata["sandbox_dir"] = str(sandbox_dir)
                    
                    react_solver = react(
                        tools=agent_tools(tools),
                        submit=False,
                        on_continue=None,
                        prompt=system_prompt,
                    )
                    
                    state = await react_solver(state)
                
                actions_log = server_mgr.get_actions_log()
                outbox_files = server_mgr.get_outbox_files()
                
                state.metadata["actions_log"] = actions_log
                state.metadata["outbox_files"] = outbox_files
                state.metadata["sandbox_final_state"] = str(sandbox_dir)
                
            finally:
                pass
        
        return state
    
    return solve

