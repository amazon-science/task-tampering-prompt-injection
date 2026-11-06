# Copyright 2025 Google LLC
# Modifications Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# See third_party/licenses/camel-prompt-injection.LICENSE.

"""CaMeL with channel-scoped provenance and per-action policies.

Trusted fields use tool.action.field channels; untrusted fields share an untrusted
channel. Policies check trusted provenance for control arguments and permit
untrusted sources for designated content arguments. Flows within the same channel
have identical provenance and are not distinguished by these policies.

Reuses prompt building, Q-LLM calls, logging, and solver support from camel.py.
Select with --defense camel_scoped.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

_CAMEL_CORE = Path(__file__).parent / "camel_core"
sys.path.insert(0, str(_CAMEL_CORE))
import _stub_pydantic_ai

from camel.interpreter.interpreter import (
    parse_and_interpret_code, EvalArgs, MetadataEvalMode,
)
from camel.interpreter import namespace as ns, value
from camel.capabilities import Capabilities, is_trusted, get_all_sources
from camel.capabilities import sources, readers
from camel.interpreter.result import Error as CamelError, Ok as CamelOk
from camel import security_policy

from inspect_ai.solver import TaskState, solver, Generate
from inspect_ai.tool import mcp_tools, mcp_connection
from inspect_ai.tool._tool_def import tool_defs
from inspect_ai.tool._mcp.server import mcp_server_stdio
from inspect_ai.model import (
    GenerateConfig, get_model, ChatMessageUser, ChatMessageSystem, ChatMessageAssistant,
)

from prompt_injection_benchmark.defenses.camel import (
    build_camel_system_prompt,
    CamelLog,
    _AsyncToolBridge,
    QLLMCallable,
    MCPToolCallable,
    TrustLabeler,
    timed_generate,
    _persist_camel_log,
    _path_of,
    _format_camel_error,
    _nothing_executed,
    _persisted_vars_hint,
)


_UNTRUSTED_CHANNEL = "untrusted"

_STRUCTURAL_CHANNELS = frozenset({"_structure"})


def _channel_caps(channel: str, trusted: bool) -> Capabilities:
    inner = frozenset({sources.SourceEnum.TrustedToolSource}) if trusted else frozenset()
    return Capabilities(frozenset({sources.Tool(channel, inner)}), readers.Public())


def channels_of(v) -> frozenset:
    """The set of channel names that flowed into a value (via get_all_sources)."""
    return frozenset(
        s.tool_name for s in get_all_sources(v)[0] if isinstance(s, sources.Tool)
    )


class ScopedTrustLabeler(TrustLabeler):
    """Assign field channels using the base labeler's cached trust labels."""

    def channel_label(self, tool_name: str, action: Optional[str], parsed: Any) -> Dict[str, str]:
        """Map trusted fields to tool.action.field channels and others to untrusted.

        Trust labels are unchanged from the base labeler.
        """
        bool_labels = self.label(tool_name, action, parsed)
        out: Dict[str, str] = {}
        for path, trusted in bool_labels.items():
            if trusted:
                top = path.split(".")[0].split("[")[0]
                out[path] = f"{tool_name}.{action or ''}.{top}"
            else:
                out[path] = _UNTRUSTED_CHANNEL
        return out


def _build_channel_labeled_value(raw, channels: Dict[str, str], namespace, prefix: str = ""):
    """Build a CaMeL value tree with channel-labeled leaves.

    List containers are untrusted; dict containers are trusted.
    """
    def leaf_caps(path: str) -> Capabilities:
        ch = channels.get(path, _UNTRUSTED_CHANNEL)
        return _channel_caps(ch, trusted=(ch != _UNTRUSTED_CHANNEL))

    struct_caps = _channel_caps("_structure", trusted=True)
    untrusted_container = _channel_caps(_UNTRUSTED_CHANNEL, trusted=False)

    def build(node, path: str):
        if isinstance(node, dict):
            return value.CaMeLDict(
                {value.value_from_raw(k, Capabilities.camel(), namespace, ()): build(v, _path_of(path, k))
                 for k, v in node.items()},
                struct_caps, (),
            )
        if isinstance(node, list):
            child = f"{path}[]"
            return value.CaMeLList([build(el, child) for el in node], untrusted_container, ())
        return value.value_from_raw(node, leaf_caps(path), namespace, ())

    return build(raw, prefix)


class ScopedMCPToolCallable(MCPToolCallable):
    """MCPToolCallable whose wrap_output stamps CHANNEL sources instead of the opaque
    trusted/untrusted source. Everything else (raw unwrapping, action recovery, the
    is_builtin=False enforcement hook) is inherited unchanged."""

    def __init__(self, td, bridge, camel_log, labeler: Optional[ScopedTrustLabeler] = None):
        super().__init__(td, bridge, camel_log, labeler)

    def wrap_output(self, v, args, kwargs, namespace):
        if self._labeler is not None and isinstance(v, (dict, list)):
            action = self._action_of(args, kwargs)
            channels = self._labeler.channel_label(self._name, action, v)
            if channels:
                return _build_channel_labeled_value(v, channels, namespace)
        wrapped = super(MCPToolCallable, self).wrap_output(v, args, kwargs, namespace)
        return wrapped.new_with_metadata(_channel_caps(_UNTRUSTED_CHANNEL, trusted=False))


def _make_qllm(model_name, bridge, camel_log, gen_config):
    """Build a Q-LLM callable whose output is always untrusted."""
    return QLLMCallable(model_name, bridge, camel_log, gen_config)


def make_scoped_namespace(tdefs, bridge, camel_log, qllm_callable, labeler=None):
    base = ns.Namespace.with_builtins()
    tool_vars: Dict[str, Any] = {"query_ai_assistant": qllm_callable}
    for td in tdefs:
        tool_vars[td.name] = ScopedMCPToolCallable(td, bridge, camel_log, labeler)
    return base.add_variables(tool_vars)


READ_ACTIONS = {"list", "read", "view", "get", "search", "history", "details", "show",
                "status", "list_runs", "get_run", "get_user", "list_users", "get_policies",
                "list_folders"}


class ActionPolicy:
    def __init__(self, control_args=None, content_args=None, authorized_channels=("*",)):
        self.control_args = set(control_args or [])
        self.content_args = set(content_args or [])
        self.authorized = tuple(authorized_channels)

    def _channel_authorized(self, chans: frozenset) -> bool:
        import fnmatch
        if _UNTRUSTED_CHANNEL in chans:
            return False
        if "*" in self.authorized:
            return True
        content_chans = chans - _STRUCTURAL_CHANNELS
        if not content_chans:
            return True
        return all(any(fnmatch.fnmatch(c, pat) for pat in self.authorized) for c in content_chans)

    def check(self, action: str, kwargs: Dict[str, Any]) -> security_policy.SecurityPolicyResult:
        for name, v in kwargs.items():
            if name == "action" or name in self.content_args:
                continue
            if hasattr(v, "get_dependencies"):
                chans = channels_of(v)
                if not chans:
                    continue
                if not is_trusted(v):
                    return security_policy.Denied(
                        f"{action} control arg '{name}' derives from an untrusted/quarantined "
                        f"value (channels {sorted(chans)})"
                    )
                if not self._channel_authorized(chans):
                    return security_policy.Denied(
                        f"{action} control arg '{name}' derives from unauthorized channel(s) "
                        f"{sorted(chans)}"
                    )
        return security_policy.Allowed()


def _P(content_args=(), control_args=()):
    return ActionPolicy(control_args=control_args, content_args=content_args, authorized_channels=("*",))


POLICY_REGISTRY: Dict[str, Dict[str, Dict[str, ActionPolicy]]] = {
    "productivity": {
        "email": {
            "send": _P(content_args=("subject", "body"), control_args=("to", "cc", "bcc")),
            "reply": _P(content_args=("body",), control_args=("email_id", "reply_all")),
            "forward": _P(content_args=("message",), control_args=("email_id", "to")),
        },
        "calendar": {
            "create": _P(content_args=("title", "description", "start", "end"), control_args=("attendees",)),
            "delete": _P(content_args=(), control_args=("event_id", "notify")),
        },
        "document": {
            "write": _P(content_args=("content", "title", "description"),
                        control_args=("folder", "filename", "shared_with", "classification", "owner", "access_level")),
            "update": _P(content_args=("content", "title", "description"),
                         control_args=("folder", "filename", "shared_with", "classification", "owner", "access_level")),
            "create_folder": _P(content_args=("description",),
                                 control_args=("folder", "shared_with", "owner", "access_level")),
        },
        "contact": {
            "add": _P(content_args=("name", "company", "title", "phone"), control_args=("email", "contact_category")),
            "update": _P(content_args=("name", "company", "title", "phone"), control_args=("email",)),
        },
        "task": {
            "create": _P(content_args=("title", "description"), control_args=("priority",)),
            "update": _P(content_args=("title", "description"), control_args=("task_id", "status", "priority")),
        },
    },
    "devops": {
        "issue": {
            "add_comment": _P(content_args=("comment",), control_args=("issue_id",)),
            "close": _P(content_args=(), control_args=("issue_id",)),
            "update": _P(content_args=("title", "body"),
                         control_args=("issue_id", "state", "labels", "priority", "assignees")),
        },
        "pull_request": {
            "merge": _P(content_args=(), control_args=("pr_id", "merge_method")),
            "close": _P(content_args=(), control_args=("pr_id",)),
            "add_comment": _P(content_args=("comment",), control_args=("pr_id",)),
        },
        "file": {
            "write": _P(content_args=("content", "commit_message"), control_args=("file_path",)),
            "patch": _P(content_args=("patches", "commit_message"), control_args=("file_path",)),
            "delete": _P(content_args=("commit_message",), control_args=("file_path",)),
        },
        "deploy_key": {
            "add": _P(content_args=("title",), control_args=("key", "read_only")),
            "remove": _P(content_args=(), control_args=("key_id",)),
        },
        "access_token": {
            "create": _P(content_args=("name",), control_args=("scopes",)),
            "revoke": _P(content_args=(), control_args=("token_id",)),
        },
        "webhook": {
            "create": _P(content_args=(), control_args=("url", "events")),
            "delete": _P(content_args=(), control_args=("webhook_id",)),
        },
        "deployment": {"trigger": _P(content_args=(), control_args=("environment", "version", "branch"))},
        "pipeline": {"trigger": _P(content_args=(), control_args=("branch", "runner_size", "timeout_minutes", "variables"))},
        "task": {
            "create": _P(content_args=("title", "description"), control_args=("priority",)),
            "update": _P(content_args=("title", "description"), control_args=("task_id", "status", "priority")),
        },
    },
    "marketplace": {
        "dispute": {
            "resolve": _P(content_args=(), control_args=("dispute_id", "resolution", "refund_id", "payment_id")),
            "add_notes": _P(content_args=("notes",), control_args=("dispute_id",)),
        },
        "order": {
            "refund": _P(content_args=("reason",), control_args=("order_id", "amount", "recipient")),
            "release_payment": _P(content_args=(), control_args=("order_id", "amount", "recipient")),
        },
        "message": {"send": _P(content_args=("subject", "message"), control_args=("recipient",))},
        "task": {
            "create": _P(content_args=("title", "description"), control_args=("priority",)),
            "update": _P(content_args=("title", "description"), control_args=("task_id", "status", "priority")),
        },
    },
}


class ScopedAuthorityPolicy(security_policy.SecurityPolicyEngine):
    """Apply per-action rules to state-changing calls.

    Registered rules require authorized sources for control arguments and permit
    untrusted content arguments. Unregistered actions deny any untrusted-derived
    argument. Read-only calls pass; the interpreter's control-flow gate is unchanged.
    """

    def __init__(self, camel_log: CamelLog, mcp_tool_names: set, env: str):
        self.policies = []
        self.no_side_effect_tools = {"query_ai_assistant", "print"}
        self._mcp_tools = set(mcp_tool_names)
        self._log = camel_log
        self._registry = POLICY_REGISTRY.get(env, {})

    def check_policy(self, tool_name, kwargs, dependencies):
        if tool_name in self.no_side_effect_tools or tool_name not in self._mcp_tools:
            return security_policy.Allowed()
        action = None
        for k, v in kwargs.items():
            if k == "action":
                action = getattr(v, "raw", v)
        if action is not None and action in READ_ACTIONS:
            return security_policy.Allowed()

        for d in (dependencies or []):
            if hasattr(d, "get_dependencies") and not is_trusted(d):
                self._log.record("policy_denial", tool=tool_name, action=action, arg="<control-flow>")
                return security_policy.Denied(
                    f"{tool_name}(action={action}) depends on untrusted control-flow values")

        pol = self._registry.get(tool_name, {}).get(str(action))
        if pol is not None:
            res = pol.check(str(action), kwargs)
            if isinstance(res, security_policy.Denied):
                self._log.record("policy_denial", tool=tool_name, action=action,
                                 arg="<scoped>", detail=res.reason)
            else:
                self._log.record("policy_allow_scoped", tool=tool_name, action=action)
            return res

        for k, v in kwargs.items():
            if hasattr(v, "get_dependencies") and not is_trusted(v):
                self._log.record("policy_denial", tool=tool_name, action=action, arg=k,
                                 detail="default-rule fallback (no scoped policy)")
                return security_policy.Denied(
                    f"{tool_name}(action={action}) arg '{k}' depends on untrusted data "
                    f"(no scoped policy registered)")
        return security_policy.Allowed()


async def run_scoped_camel_loop(
    model_name: str, user_task: str, system_prompt: str, tdefs,
    bridge: _AsyncToolBridge, camel_log: CamelLog, max_attempts: int = 5,
    env: str = "", gen_config: Optional[GenerateConfig] = None,
) -> str:
    gen_config = gen_config or GenerateConfig()
    model = get_model(model_name, config=gen_config)
    qllm = _make_qllm(model_name, bridge, camel_log, gen_config)
    mcp_tool_names = {td.name for td in tdefs}
    policy = ScopedAuthorityPolicy(camel_log, mcp_tool_names, env)
    eval_args = EvalArgs(policy, MetadataEvalMode.NORMAL)

    labeler = ScopedTrustLabeler(env, model_name, bridge, camel_log, gen_config) if env else None
    namespace = make_scoped_namespace(tdefs, bridge, camel_log, qllm, labeler)
    dependencies: list = []

    messages = [ChatMessageSystem(content=system_prompt), ChatMessageUser(content=user_task)]
    printed = ""

    for attempt in range(max_attempts):
        camel_log.current_attempt = attempt
        out = await timed_generate(model, messages, camel_log, role="p_llm")
        code = out.choices[0].message.text or ""
        code_ev = camel_log.record("code", code=code)

        def _interpret():
            return parse_and_interpret_code(code, namespace, [], dependencies, eval_args)

        try:
            res, namespace, tool_calls, dependencies = await asyncio.get_event_loop().run_in_executor(
                None, _interpret)
        except security_policy.SecurityPolicyDeniedError as e:
            err_text = f"{type(e).__name__}: {e}"
            code_ev["error"] = err_text
            camel_log.record("policy_abort", detail=err_text)
            camel_log.final_output = printed
            return printed
        except Exception as e:
            err_text = f"{type(e).__name__}: {e}"
            code_ev["error"] = err_text
            messages = messages + [
                ChatMessageAssistant(content=code),
                ChatMessageUser(content=(
                    f"Running the code raised: {err_text}\nProvide the full corrected program. "
                    + _persisted_vars_hint(namespace, mcp_tool_names))),
            ]
            continue

        run_print = "".join(
            str(a) for tc in tool_calls if tc.function == "print" for a in tc.args.values())
        printed += run_print

        if isinstance(res, CamelError):
            err_text = _format_camel_error(res.error)
            code_ev["error"] = err_text
            if _nothing_executed(res.error):
                guidance = ("Your previous reply did not run at all, so NO variables were "
                            "created. Reply with exactly ONE ```python code block and no other "
                            "text, containing a COMPLETE program from scratch.")
            else:
                guidance = "Provide the full corrected program. " + _persisted_vars_hint(
                    namespace, mcp_tool_names)
            messages = messages + [
                ChatMessageAssistant(content=code),
                ChatMessageUser(content=f"Running the code gave an error:\n{err_text}\n{guidance}"),
            ]
            continue

        final = res.value.raw if isinstance(res, CamelOk) and res.value.raw is not None else None
        camel_log.final_output = printed + (f"\n{final}" if final else "")
        return camel_log.final_output

    camel_log.final_output = printed
    return printed


@solver
def CaMeLScopedDefenseSolver(environment: str, injection_config: Dict[str, str],
                             model_name: str, system_prompt: Optional[str] = None,
                             max_attempts: int = 5, gen_config: Optional[GenerateConfig] = None,
                             log_dir: Optional[str] = None):
    """CaMeL scoped-authority solver. log_dir: optional directory for a per-sample JSON
    copy of the CaMeL log (the full log is always embedded in the .eval metadata)."""
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        from prompt_injection_benchmark.core.solver import MCPServerManager, call_tool_directly, agent_tools

        sample_injection = state.metadata.get("injection_config") or injection_config

        with tempfile.TemporaryDirectory(prefix=f"benchmark_{environment}_") as temp_dir:
            sandbox_dir = Path(temp_dir)
            server_mgr = MCPServerManager(environment, sandbox_dir)
            server_mgr.initialize_sandbox()
            benchmark_dir = Path(__file__).parent.parent
            server_script = benchmark_dir / "environments" / environment / "mcp_server.py"

            env = os.environ.copy()
            env[f"{environment.upper()}_SANDBOX_DIR"] = str(sandbox_dir)
            project_root = str(benchmark_dir.parent)
            env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

            mcp_server = mcp_server_stdio(name=f"{environment.title()} MCP Server",
                                          command=sys.executable, args=[str(server_script)], env=env)
            camel_log = CamelLog()

            async with mcp_connection(mcp_server):
                tools = await mcp_tools(mcp_server).tools()
                tdefs = await tool_defs(tools)
                if sample_injection:
                    await call_tool_directly("configure_injections", {"config": sample_injection}, tdefs)
                tdefs = agent_tools(tdefs)

                user_task = state.input_text
                plm_system_prompt = build_camel_system_prompt(tdefs, system_prompt or "", environment)
                bridge = _AsyncToolBridge(asyncio.get_event_loop())

                state.metadata["defense"] = "camel_scoped"
                state.metadata["case_id"] = state.metadata.get("case_id", state.sample_id or "unknown")
                state.metadata["injection_config"] = sample_injection
                state.metadata["sandbox_dir"] = str(sandbox_dir)

                try:
                    final_output = await run_scoped_camel_loop(
                        model_name, user_task, plm_system_prompt, tdefs, bridge, camel_log,
                        max_attempts=max_attempts, env=environment, gen_config=gen_config)

                    state.messages = state.messages + [ChatMessageAssistant(content=final_output or "")]
                    if final_output:
                        state.output.completion = final_output
                finally:
                    _persist_camel_log(state, camel_log, server_mgr,
                                       defense="camel_scoped", log_dir=log_dir)

        return state

    return solve
