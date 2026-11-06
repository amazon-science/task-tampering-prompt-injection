<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: CC-BY-NC-4.0 -->

# Third-party notices

This package is released under CC BY-NC 4.0 (see `LICENSE`). The third-party components
listed below retain their original licenses, whose full texts are in
`third_party/licenses/`. The table distinguishes copied or adapted code from the
separately installed dependency. Where a component is reimplemented rather than
copied, the original license is included for attribution.

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
Amazon-authored files and benchmark data are licensed under CC-BY-NC-4.0, except
for contributions to components retained under the licenses listed below.
The license for case JSON, sandbox fixtures, and standalone prompt files is stated
here and in the repository README rather than inserted into their contents.

| Component or dependency | Upstream | License | Relationship |
|---|---|---|---|
| `prompt_injection_benchmark/patches/_bedrock_ee0dfdef8.py`, `bedrock_ee0dfdef8.diff` | [inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai) @ `ee0dfdef8`, `src/inspect_ai/model/_providers/bedrock.py` | MIT, Copyright (c) 2024 UK AI Security Institute | Copy of the upstream file with a small modification (the diff shows exactly what changed; see `patches/__init__.py` for what it does) |
| `mcp==1.12.3` | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.12.3) | MIT, Copyright (c) 2024 Anthropic, PBC | Runtime dependency installed separately via pip; SDK source is not vendored in this repository |
| `prompt_injection_benchmark/defenses/camel_core/camel/` | [camel-prompt-injection](https://github.com/google-research/camel-prompt-injection) @ `f083b6b`, `src/camel/` | Apache-2.0, Copyright 2025 Google LLC | Vendored subset. Only `camel/interpreter/interpreter.py` is changed, as described by a notice at the top of that file. AgentDojo/backend-coupled modules are left out. License: `defenses/camel_core/LICENSE` |
| `prompt_injection_benchmark/defenses/camel.py`, `camel_scoped.py` | camel-prompt-injection (as above) | Apache-2.0 | Reimplementation of the CaMeL P-LLM / Q-LLM loop and security policy for these environments. The CaMeL language-rule and Q-LLM prompts are ported nearly word for word |
| `prompt_injection_benchmark/defenses/drift.py`, `drift_unguided.py`, `drift_repeat_cap.py` | [DRIFT](https://github.com/SaFo-Lab/DRIFT) | MIT, Copyright (c) 2026 Hao Li | Ports of the DRIFT defense (secure planner, dynamic validator, injection isolator) and its prompts, with a bounded-repeat adaptation |
| `prompt_injection_benchmark/defenses/progent.py` | [Progent](https://github.com/sunblaze-ucb/progent) | MIT, Copyright (c) 2026 Progent | Port of Progent's LLM-generated JSON-schema tool policies and their update step, with prompts |
| `spotlight` defense in `prompt_injection_benchmark/scripts/run_defense.py` | [AgentDojo](https://github.com/ethz-spylab/agentdojo) | MIT, Copyright (c) 2024 Edoardo Debenedetti et al. | Uses the delimiting instruction text of AgentDojo's spotlighting defense |

The license texts are:

- `third_party/licenses/inspect_ai.LICENSE` (also `prompt_injection_benchmark/patches/LICENSE.inspect_ai`)
- `third_party/licenses/mcp.LICENSE`
- `third_party/licenses/camel-prompt-injection.LICENSE` (also `prompt_injection_benchmark/defenses/camel_core/LICENSE`)
- `third_party/licenses/DRIFT.LICENSE`
- `third_party/licenses/progent.LICENSE`
- `third_party/licenses/agentdojo.LICENSE`

`sandwich`, `trust_hierarchy` and `trust_hierarchy_env` are prompt-level defenses written
for this benchmark.
