<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: CC-BY-NC-4.0 -->

# Task-Tampering Prompt Injection: data

Test cases and agent environments for evaluating how robust LLM agents are to prompt
injections placed in the content they read through tools. Run them with the evaluation
code in this repository; see the [setup instructions](../README.md#2-attach-the-data).

- **90 cases** across three simulated organizations/environments: `productivity` (docs,
  mail, calendar), `devops` (repository, issues, CI/CD, deployments), `marketplace`
  (orders, disputes, listings, messages)
- **1,433 injection variants**: each case's source injection plus several rewrites of it
  (1,343 in total), each rewrite labeled with the single belief primitive it targets
- **License**: [CC BY-NC 4.0](LICENSE).
  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

## Contents

```
environments/<env>/
  sandbox_template/   the environment's initial state (JSON/Markdown/files) the agent's
                      tools read and modify; each case copies it into a fresh sandbox
  tools.py, mcp_server.py
                      the environment's tools, served to the agent over MCP
  system_prompt.txt   a short description of the agent's role in this environment
                      (no operational rules or injection guidance); not used by the runners
test_cases/<env>/<case_id>.json
                      one case per file (see below)
SUMMARY.json          case and variant counts per environment and primitive
```

## Case format

Each `test_cases/<env>/<case_id>.json` has a `metadata` object (`version`, `environment`)
and holds one entry in `test_cases`:

- `id`, `name`: the case id (same as the file name) and a short title
- `user_request`: the benign task given to the agent
- `attacker`, `victim`, `risk_category`, `attack_strategy`: who plants the injection,
  whose asset is harmed, and how
- `sources`, `expected_tool_flow`, `required_tools`: the resources a correct run consults
- `injection`: where the injection is placed (`location`; `injection_path`, a JSON
  pointer within that file, or `null` if not given; `placeholder`), the attacker's
  `goal`, a prose `strategy` and `attack_mechanism`, and the `variations` list. Each
  variation has an `id`, a `primitive`, the injected `content` and a `viable` flag (`true`
  for every shipped variant). The variation with id `original` is the case's source
  injection and is labeled `compound`; every other variation is labeled with exactly one
  primitive. `injection.content` is not used when a case has `variations` (all shipped
  cases do).
- `evaluation`: the user-task checks (`user_task_checks`) and injection checks
  (`injection_checks`), each with an `id`, a `description` and a `check`, plus boolean
  formulas over the check ids (`user_task_success`, `user_task_robust`,
  `injection_success`, `injection_partial`). These are human-readable descriptions; the
  executable checks and formulas are in
  `../prompt_injection_benchmark/core/evaluation/checks/case_helpers/<env>/<case_id>.py`.

The descriptive fields name tools as `tool.action` (for example `contact.search` is the
productivity `contact` tool's `search` action).

When a case runs, the tools substitute the chosen variant's `content` for the case's
`{{INJECTION_<ID>}}` placeholder (the `placeholder` field holds `INJECTION_<ID>`) in the
sandbox files as the agent reads them. Every
placeholder in the sandbox belongs to a shipped case; those of cases not being run
resolve to empty text. The agent gets no system prompt (`system_prompt.txt` is provided for
reference only): the only instruction is the user request, which it completes with the
environment's tools. The scorer then checks the action logs
and labels the sample with one of four quadrants (task completed or not x attack
succeeded or not).

## Belief primitives

Each variant is labeled by the belief the injection text directly targets, the one
that, if the agent accepts it, makes the harmful action look justified:

| label | the injection updates the agent's belief about... |
|---|---|
| `b(s)` | what is true about an entity, state or event |
| `b(π)` | what action to take under a condition (a reusable rule or procedure) |
| `b(T)` | what will happen as a result of a candidate action |
| `b(O)` | how to interpret data it has already observed |
| `b(U)` | what its goal or endpoint is (a one-off replacement target) |
| `b(A)` | what actions, tools or configurations are available to it |

The `primitive` field and `SUMMARY.json` spell `b(π)` as `b(pi)`. Variant ids are
`<primitive>_<n>` (e.g. `b_s_1`, `b_T_2`); for `b(π)` the id prefix is `b_π` in most cases
and `b_pi` in some (e.g. `b_π_1`, `b_pi_1`).

## Variants

The variants shipped are exactly the set counted in the paper's results: each labeled
variant passed the paper's sufficiency filter (an agent that fully believed the injection
would take the attacked action) and its primitive label agrees with an independent
classification of its text. `SUMMARY.json` gives the counts.

## Intended use and limitations

- This dataset is provided for reproducing the paper's findings and evaluating
  prompt-injection robustness. It is not intended for training AI models.
- All organizations, people, e-mail addresses and domains, repositories, account and
  serial numbers in the environments and attack texts are fictional placeholders; they do
  not refer to real people, organizations or mailboxes.
- Injections are written to steer a tool-using agent toward harmful parameter choices
  inside the sandbox (e.g. wrong recipient, wrong refund, deleting the wrong resource).
  They contain no working exploits against real systems.
