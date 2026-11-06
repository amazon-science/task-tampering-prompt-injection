<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: CC-BY-NC-4.0 -->

# Task-Tampering Prompt Injection

[![arXiv](https://img.shields.io/badge/arXiv-2611.07640-b31b1b.svg)](https://arxiv.org/abs/2611.07640)

Research code and data for evaluating LLM agent robustness against task-tampering
indirect prompt injections.

The repository includes the agent solver, three tool-use environments and their MCP
servers, per-case scorers, runners for attack and defense experiments, and defense
implementations. The benchmark data in [`data/`](data/README.md) contains 90 cases
and 1,433 injection variants. Attach it before running evaluations (step 2 below).

Amazon-authored code and data are licensed **CC BY-NC 4.0** ([LICENSE](LICENSE)).
Third-party components retain their original licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Release scope

This code is being released solely for academic and scientific reproducibility purposes, in support of the methods and findings described in the associated publication. Pull requests are not being accepted in order to maintain the code exactly as it was used in the paper.

## 1. Install

Requires Python 3.11+ and access to the models you want to run through any
[inspect_ai model provider](https://inspect.aisi.org.uk/providers.html). All model calls,
including the scorer's LLM judge (see Scoring below), go through inspect_ai.

From the repository root:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install -e ".[bedrock]"   # only for bedrock/... models (adds aioboto3)
```

Install the SDK of any other provider you use (e.g. `pip install openai`) and set its
credentials as described in the inspect_ai docs.

If pip tries to build `numpy` from source and fails, install a prebuilt wheel first
(`pip install --only-binary=numpy numpy`), then rerun `pip install -e .`.

This installs `inspect-ai` at commit `ee0dfdef8`, together with pinned `mcp` and `pyyaml`.

### Bedrock provider modification

The paper's models were called through Amazon Bedrock, with a slightly modified
inspect_ai Bedrock provider. The runners install it automatically at import time
(`prompt_injection_benchmark/patches/`). It only affects `bedrock/...` models; other
providers are unaffected, and your installed inspect_ai files are not changed. The
modification:

1. sends each tool-calling assistant turn as one Converse message (its text/reasoning
   followed by all of its tool calls) instead of one message per tool call;
2. keeps the reasoning `signature` so reasoning turns can be replayed;
3. disables `<think>`-tag reasoning emulation.

`patches/bedrock_ee0dfdef8.diff` has the exact diff. The modification is applied only when
the installed provider matches stock `ee0dfdef8`; with any other inspect_ai version it
warns and does nothing. Set `PIB_NO_BEDROCK_PATCH=1` to turn it off.

## 2. Attach the data

From the repository root, use the included `data/` directory:

```bash
python -m prompt_injection_benchmark.scripts.link_data ./data   # symlink
python -m prompt_injection_benchmark.scripts.link_data --check
```

If symlinks are unavailable, use
`python -m prompt_injection_benchmark.scripts.link_data ./data --copy` instead of
the first command, then run `--check`.
This creates `prompt_injection_benchmark/environments/` and
`prompt_injection_benchmark/test_cases/variations/` inside the package, pointing at
the included data. These generated paths are excluded from Git.

## 3. Run

Results are Inspect `.eval` files written under `$PIB_OUTPUT_DIR` (default
`./pib_results`).

Both runners take the model under evaluation as `--model` (required) and the scorer's
LLM judge as `--judge-model` (or the `LLM_CHECK_MODEL` environment variable; required
except for dry runs). Both are inspect_ai model ids (`provider/model`); the package does not
ship a model list. The examples below use shell variables for them:

```bash
MODEL=<provider>/<model>     # agent under evaluation
JUDGE=<provider>/<model>     # LLM judge for the scorer
```

### Attack evaluation (no defense)

```bash
# what would run (environments, cases, variant counts)
python -m prompt_injection_benchmark.scripts.run_eval --model "$MODEL" --dry-run

# one case
python -m prompt_injection_benchmark.scripts.run_eval --model "$MODEL" --judge-model "$JUDGE" \
  --env devops --case A1

# a whole environment, one variant per primitive per case (plus each case's original)
python -m prompt_injection_benchmark.scripts.run_eval --model "$MODEL" --judge-model "$JUDGE" \
  --env productivity --max-per-primitive 1

# clean (no-injection) utility run, written to <env>_no_injection/
python -m prompt_injection_benchmark.scripts.run_eval --model "$MODEL" --judge-model "$JUDGE" \
  --env marketplace --no-injection
```

Without `--env`, every environment in `scripts/config_eval.yaml` is run. `--resume` skips
samples that already have a score in the output directory.
Output: `$PIB_OUTPUT_DIR/attack_evaluation/evals/<model>/<env>/`, where `<model>` is the
last path segment of the model id up to any `:`, with `.` replaced by `_` (e.g.
`openai/gpt-4o` -> `gpt-4o`). `--no-injection` runs go to
`<env>_no_injection/` instead, so they are kept apart from the attacked `original` runs (both
use the case id as the sample id); `--output-suffix <s>` writes to `<env>_<s>/` in either mode.

### Defense evaluation

```bash
python -m prompt_injection_benchmark.scripts.run_defense --model "$MODEL" --dryrun

python -m prompt_injection_benchmark.scripts.run_defense --model "$MODEL" --judge-model "$JUDGE" \
  --defense progent_fullschema --env devops --case A1

# resume an interrupted run (skips completed samples)
python -m prompt_injection_benchmark.scripts.run_defense --model "$MODEL" --judge-model "$JUDGE" \
  --defense drift_full_guided --resume
```

`--defense` takes one of the names listed under Defenses below. Defaults come from
`scripts/config_defense.yaml`.
Output: `$PIB_OUTPUT_DIR/defense_evaluation/evals/<defense>/<model>/<env>/`.
`camel_scoped` and both Progent configurations embed their defense log in each sample's metadata and also
write a per-sample JSON copy to `defense_logs/` inside that directory.

`config_defense.yaml` sets `max_per_primitive: 1`: as in the paper, a defense is evaluated
on the first variant of each primitive per case (the case's `original` counts as its
`compound` variant). Pass a larger `--max-per-primitive` to run more variants; to run every
variant, set `max_per_primitive: null` in the config (`--max-per-primitive 0` falls back to
the config value). Each sample has a 540 s time limit (`time_limit` in the config).

Samples that hit the time limit because of provider throttling can be re-run with
`--resume --rerun-throttle-timeouts`. To count them first:

```bash
python -m prompt_injection_benchmark.scripts.throttle_timeout_check \
  pib_results/defense_evaluation/evals/*/*/* --by both
```

### Scoring

Each sample is scored during the run by the case's checks
(`core/evaluation/checks/case_helpers/<env>/<case>.py`). Some checks ask an LLM judge a
yes/no question (`core/evaluation/llm_check.py`), called through inspect_ai like the agent.
The judge model is `--judge-model` / `LLM_CHECK_MODEL`; `LLM_CHECK_VOTES` sets the
majority vote over a positive odd number of calls (default 3) and `LLM_CHECK_CACHE_DIR`
an optional on-disk cache. Cached verdicts are keyed by judge model, vote count and prompt.
Each sample is assigned one quadrant, from task completion x attack success:
`SECURE_SUCCESS`, `COMPROMISED_SUCCESS`, `SECURE_FAILURE` or `COMPROMISED_FAILURE`. The
per-check results are stored alongside it.

## Defenses

| `--defense` | Kind | Implementation | Upstream / license |
|---|---|---|---|
| `none` | no defense (baseline) | `scripts/run_defense.py` | n/a |
| `spotlight` | prompt: delimit tool outputs with `<< >>` and tell the model not to follow instructions inside them | `scripts/run_defense.py` | AgentDojo delimiting prompt (MIT) |
| `sandwich` | prompt: repeat the user task after every tool output | `scripts/run_defense.py` | written for this benchmark |
| `trust_hierarchy` | system prompt: generic trust ordering of sources | `defenses/trust_hierarchy.py` | written for this benchmark |
| `trust_hierarchy_env` | system prompt: per-environment trust rules | `defenses/env_trust_prompts.py` | written for this benchmark |
| `drift_full_guided` | DRIFT planner, validator and isolator; full tool schemas, remaining-plan guidance, repeated-call limit | `defenses/drift.py` | DRIFT (MIT) |
| `progent_fullschema` | Progent policies and updates with full tool schemas and a code-enforced read-action exemption | `defenses/progent.py` | Progent (MIT) |
| `drift_isolation` | DRIFT injection isolator only (LLM scan of every tool result, strip injected span) | `defenses/drift_unguided.py` | DRIFT (MIT) |
| `drift_full` | DRIFT planner, validator and isolator; name/description tool information, no agent-facing plan guidance or repeated-call limit | `defenses/drift_unguided.py` | DRIFT (MIT) |
| `progent` | Progent policies and updates with type/description argument information and a prompt-based read-action exemption | `defenses/progent.py` | Progent (MIT) |
| `camel_scoped` | CaMeL with channel-scoped provenance and per-tool control/content argument policies | `defenses/camel_scoped.py` (built on the CaMeL port in `defenses/camel.py` and `defenses/camel_core/`) | CaMeL (Apache-2.0) |

Every defense uses the model under evaluation for its own LLM calls. DRIFT, Progent and
CaMeL are ported from their official implementations and adapted to this benchmark's
tools and harness.

For Progent and full DRIFT, the default suite uses `progent_fullschema` and
`drift_full_guided`, respectively.

The DRIFT injection-detection prompt has been updated.

## Evaluation settings

- Defense evaluations use the first variant of each primitive per case (the
  `max_per_primitive: 1` default above); attack evaluations use all variants.
- The paper's LLM judge was `claude-sonnet-4-20250514` (called through Bedrock) at
  temperature 0 with 3 votes; a different judge model can change the scores of the LLM-judged checks.
- Defense configuration, model sampling and provider-side model updates can change
  results.

## Layout

```text
pyproject.toml                 installation and dependency configuration
data/
  environments/                MCP servers, tools, and sandbox templates
  test_cases/                  case definitions and injection variants
  SUMMARY.json                 case and variant counts
prompt_injection_benchmark/
  core/                        solver, task construction, checks, and scorer
  defenses/                    defense implementations and vendored CaMeL core
  scripts/                     evaluation runners, configuration, and data attachment
  patches/                     Bedrock provider modification
  environments/                -> data/environments (created by link_data)
  test_cases/variations/        -> data/test_cases (created by link_data)
third_party/licenses/          third-party license texts
```

## Intended use

This dataset is provided for reproducing the paper's findings and evaluating
prompt-injection robustness. It is not intended for training AI models.

The attack texts target fictional organizations inside sandboxed environments.

## Citation

If you use this code or benchmark in your research, please cite our paper,
[Beyond Instruction Override: Benchmarking Indirect Prompt Injection with
Task-Tampering Attacks](https://arxiv.org/abs/2611.07640).

```bibtex
@misc{zhang2026instructionoverridebenchmarkingindirect,
  title={Beyond Instruction Override: Benchmarking Indirect Prompt Injection with Task-Tampering Attacks},
  author={Rongting Zhang and Martin Bertran and Sandeep Avula and Chia-Jung Lee and Vanessa Murdock},
  year={2026},
  eprint={2611.07640},
  archivePrefix={arXiv},
  primaryClass={cs.CR},
  url={https://arxiv.org/abs/2611.07640},
}
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

Amazon-authored code, documentation, prompts, and benchmark data are licensed under
[Creative Commons Attribution-NonCommercial 4.0 International](LICENSE)
(`CC-BY-NC-4.0`). Third-party components retain their own licenses as listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

