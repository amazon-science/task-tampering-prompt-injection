# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""Minimal pydantic_ai stub: provides the pydantic_ai names the vendored CaMeL code
imports (the interpreter's isinstance guards and quarantined_llm's Agent/models), so
pydantic_ai is not a dependency. The Q-LLM is implemented in defenses/camel.py
(QLLMCallable); the stub Agent is never called."""
import sys, types
if 'pydantic_ai' not in sys.modules:
    m = types.ModuleType('pydantic_ai')
    class UnexpectedModelBehavior(Exception): ...
    class Agent:
        def __init__(self, *a, **k): ...
        def run_sync(self, *a, **k): raise RuntimeError("pydantic_ai stub: Agent is not available")
    m.UnexpectedModelBehavior = UnexpectedModelBehavior
    m.Agent = Agent
    models = types.ModuleType('pydantic_ai.models')
    class KnownModelName(str): ...
    class Model: ...
    models.KnownModelName = KnownModelName
    models.Model = Model
    m.models = models
    sys.modules['pydantic_ai'] = m
    sys.modules['pydantic_ai.models'] = models
