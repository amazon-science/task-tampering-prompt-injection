# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Environment-agnostic task loading for Inspect AI

Loads test cases from JSON files and creates Inspect AI Task objects.
Works with any environment (productivity, devops, marketplace).
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from inspect_ai import Task, task
from inspect_ai.dataset import Sample


@dataclass
class BenchmarkTask:
    """Container for benchmark test case metadata."""

    id: str
    environment: str
    type: str
    risk_category: Optional[str]
    attack_target: Optional[str]
    difficulty: Optional[str]
    description: str
    user_request: str
    system_prompt: Optional[str]
    injection_config: Dict[str, str]
    expected_behavior: Dict[str, Any]
    evaluation: Dict[str, Any]
    variation_id: str = "original"
    primitive: str = "compound"
    authority_source: str = "tool_result"

    def to_sample(self) -> Sample:
        """Convert to Inspect AI Sample format."""
        sample_id = f"{self.id}_{self.variation_id}" if self.variation_id != "original" else self.id
        return Sample(
            input=self.user_request,
            target=self.description,
            id=sample_id,
            metadata={
                "environment": self.environment,
                "type": self.type,
                "risk_category": self.risk_category,
                "attack_target": self.attack_target,
                "difficulty": self.difficulty,
                "description": self.description,
                "system_prompt": self.system_prompt,
                "injection_config": self.injection_config,
                "expected_behavior": self.expected_behavior,
                "evaluation": self.evaluation,
                "variation_id": self.variation_id,
                "primitive": self.primitive,
                "authority_source": self.authority_source,
            }
        )


def load_test_cases_json(
    json_path: Path,
    variation_filter: Optional[List[str]] = None,
) -> List[BenchmarkTask]:
    """
    Load test cases from JSON file, expanding variations if present.

    Each test case with a `variations` array in its injection block is expanded
    into one BenchmarkTask per variation. A test case without variations produces
    a single "original" BenchmarkTask from its injection `content`.

    Args:
        json_path: Path to test cases JSON file
        variation_filter: If set, only include variations whose id is in this list

    Returns:
        List of BenchmarkTask objects
    """
    with open(json_path, 'r') as f:
        data = json.load(f)

    meta = data.get("metadata", data.get("meta", {}))
    environment = meta.get("environment", "")
    if not environment:
        environment = json_path.stem.replace("test_cases_", "").replace("productivity_test_cases", "productivity")

    system_prompt_text = None
    system_prompt_file = meta.get("system_prompt_file")
    if system_prompt_file:
        benchmark_dir = Path(__file__).parent.parent
        prompt_path = benchmark_dir / "environments" / environment / system_prompt_file
        if prompt_path.exists():
            system_prompt_text = prompt_path.read_text().strip()

    tasks = []

    for test_case in data["test_cases"]:
        test_type = test_case.get("type", "attack")
        description = test_case.get("description") or test_case.get("name", "")
        use_sys_prompt = test_case.get("use_system_prompt", False)

        injection_obj = test_case.get("injection", {})
        placeholder = injection_obj.get("placeholder", "")
        base_content = injection_obj.get("content", "")
        variations = injection_obj.get("variations", [])

        if not variations:
            variations = [{
                "id": "original",
                "primitive": "compound",
                "authority_source": "tool_result",
                "content": base_content,
                "viable": True,
            }]

        for var in variations:
            if not var.get("viable", True):
                continue
            if variation_filter and var["id"] not in variation_filter:
                continue

            var_content = var.get("content", base_content)
            injection_config = {placeholder: var_content} if placeholder and var_content else {}

            task_obj = BenchmarkTask(
                id=test_case["id"],
                environment=environment,
                type=test_type,
                risk_category=test_case.get("risk_category"),
                attack_target=test_case.get("attack_target"),
                difficulty=test_case.get("difficulty"),
                description=description,
                user_request=test_case["user_request"],
                system_prompt=system_prompt_text if use_sys_prompt else None,
                injection_config=injection_config,
                expected_behavior=test_case.get("expected_behavior", {}),
                evaluation=test_case.get("evaluation", {}),
                variation_id=var["id"],
                primitive=var.get("primitive", "compound"),
                authority_source=var.get("authority_source", "tool_result"),
            )
            tasks.append(task_obj)

    return tasks


def load_benchmark_tasks(
    test_file: str,
    no_injection: bool = False,
    variation_filter: Optional[List[str]] = None,
) -> List[Task]:
    """
    Load benchmark tasks for Inspect AI from one case file.

    Args:
        test_file: Path to a case JSON file (e.g. test_cases/variations/<env>/<CASE>.json)
        no_injection: If True, disable injections (task names get a '_noinjection' suffix)
        variation_filter: Only include specific variation IDs (e.g., ["original", "b_s_1"])

    Returns:
        List of Inspect AI Task objects, one per variation
    """
    json_path = Path(test_file)
    if not json_path.exists():
        raise FileNotFoundError(f"Test cases not found: {json_path}")

    print(f"Loading test cases from: {json_path}")

    tasks = load_test_cases_json(json_path, variation_filter=variation_filter)
    return [create_inspect_task(t, no_injection=no_injection) for t in tasks]


def create_inspect_task(
    benchmark_task: BenchmarkTask,
    no_injection: bool = False,
) -> Task:
    """
    Create an Inspect AI Task from a BenchmarkTask, scored by the programmatic scorer.

    Args:
        benchmark_task: BenchmarkTask object
        no_injection: If True, disable injections and add '_noinjection' suffix to task name

    Returns:
        Inspect AI Task
    """
    from .evaluation.scorer import create_programmatic_scorer
    from .solver import MCPAgentSolver

    injection_config = {} if no_injection else benchmark_task.injection_config

    task_name = f"{benchmark_task.environment}_{benchmark_task.id}"
    if benchmark_task.variation_id != "original":
        task_name += f"_{benchmark_task.variation_id}"
    if no_injection:
        task_name += "_noinjection"

    scorer = create_programmatic_scorer(benchmark_task.environment, benchmark_task.id)

    @task
    def benchmark_test():
        return Task(
            dataset=[benchmark_task.to_sample()],
            solver=MCPAgentSolver(
                environment=benchmark_task.environment,
                injection_config=injection_config,
                system_prompt=benchmark_task.system_prompt,
            ),
            scorer=scorer,
            name=task_name,
            message_limit=500,
            time_limit=540,
            metadata={
                "environment": benchmark_task.environment,
                "type": benchmark_task.type,
                "risk_category": benchmark_task.risk_category,
                "difficulty": benchmark_task.difficulty,
                "no_injection": no_injection,
                "variation_id": benchmark_task.variation_id,
                "primitive": benchmark_task.primitive,
                "authority_source": benchmark_task.authority_source,
            }
        )

    return benchmark_test()

