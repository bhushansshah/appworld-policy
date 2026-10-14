"""Build policy scenarios into AppWorld tasks, and write the dataset lists to run them.

For each scenario in policy_scenarios/scenarios/<name>/scenario.py and each of its versions, this makes the
task data/tasks/<name>_<version>: a copy of the scenario's base task (with the scenario's world changes, if it
has any, applied through the apps and recorded by AppWorld) with the version's instruction, its
policies (loaded with load_policies), and the scenario's grader (evaluation.py) with the version's correct
outcome and policy labels as private data. It then writes data/datasets/policy_v1.txt ... policy_v4.txt
(the tasks of each version) and policy_all.txt.

The scenario files are kept encrypted in git; unpack them first (policy_scenarios/bundle.py).

Usage (from the repo root): .venv/bin/python -m policy_scenarios.build [scenario_name ...]
"""

import argparse
import importlib.util
import json
import os
import shutil
from pathlib import Path

from appworld.common.path_store import path_store
from appworld.task import load_task_ids

from policy_scenarios.load_policies import load_policies
from policy_scenarios.scenario import Scenario, Version, policies_of

SCENARIOS_DIRECTORY = Path(__file__).resolve().parent / "scenarios"
COMMON_CHECKS = Path(__file__).resolve().parent / "common_checks.py"  # appended to every scenario's grader
DATASET_PREFIX = "policy"
WORLD_EXPERIMENT = "policy_scenarios_world_setup"  # temporary run outputs while applying world changes
# The base task's solution and its generator do not apply to the new versions.
BASE_GROUND_TRUTH_TO_REMOVE = ["solution.py", "compiled_solution.py", "generator.py", "api_calls.json", "__pycache__"]


def scenario_names() -> list[str]:
    if not SCENARIOS_DIRECTORY.exists():
        raise FileNotFoundError(
            f"{SCENARIOS_DIRECTORY} does not exist. Unpack the scenarios first: "
            ".venv/bin/python -m policy_scenarios.bundle unpack"
        )
    return sorted(path.parent.name for path in SCENARIOS_DIRECTORY.glob("*/scenario.py"))


def load_scenario(name: str) -> Scenario:
    path = SCENARIOS_DIRECTORY / name / "scenario.py"
    spec = importlib.util.spec_from_file_location(f"policy_scenario_{name}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    scenario: Scenario = module.SCENARIO
    if scenario.name != name:
        raise ValueError(f"{path}: the scenario's name ({scenario.name!r}) must match its folder ({name!r}).")
    return scenario


def build_scenario(scenario: Scenario) -> list[str]:
    if scenario.base_task_id not in load_task_ids("train") + load_task_ids("dev"):
        raise ValueError(f"{scenario.name}: the base task must be a train or dev task (not test).")
    source_task_id = prepare_world(scenario) if scenario.world_setup else scenario.base_task_id
    try:
        return [build_version(scenario, version, source_task_id) for version in scenario.versions]
    finally:
        if source_task_id != scenario.base_task_id:
            shutil.rmtree(os.path.join(path_store.data, "tasks", source_task_id), ignore_errors=True)


def prepare_world(scenario: Scenario) -> str:
    """Make <name>_0: a copy of the base task with the scenario's world changes, as recorded by AppWorld."""
    from appworld import AppWorld

    task_id = f"{scenario.name}_0"
    task_directory = os.path.join(path_store.data, "tasks", task_id)
    shutil.rmtree(task_directory, ignore_errors=True)
    shutil.copytree(os.path.join(path_store.data, "tasks", scenario.base_task_id), task_directory)
    with AppWorld(task_id=task_id, experiment_name=WORLD_EXPERIMENT, allow_datetime_change=True) as world:
        scenario.world_setup(world)  # type: ignore[misc]
        world.save()
    saved_directory = os.path.join(path_store.experiment_outputs, WORLD_EXPERIMENT, "tasks", task_id, "dbs")
    for name in os.listdir(saved_directory):
        if name.endswith(".jsonl"):
            shutil.copy(os.path.join(saved_directory, name), os.path.join(task_directory, "dbs", name))
    shutil.rmtree(os.path.join(path_store.experiment_outputs, WORLD_EXPERIMENT), ignore_errors=True)
    return task_id


def build_version(scenario: Scenario, version: Version, source_task_id: str) -> str:
    tasks_directory = os.path.join(path_store.data, "tasks")
    task_id = scenario.task_id(version)
    task_directory = os.path.join(tasks_directory, task_id)
    shutil.rmtree(task_directory, ignore_errors=True)
    shutil.copytree(os.path.join(tasks_directory, source_task_id), task_directory)

    instruction = version.instruction or scenario.instruction
    if instruction:
        _update_json(os.path.join(task_directory, "specs.json"), {"instruction": instruction})

    load_policies(
        task_id,
        {
            "supervisor": [policy.text for policy in version.supervisor_policies],
            "people": {email: [p.text for p in policies] for email, policies in version.people_policies.items()},
            "apps": {app: [p.text for p in policies] for app, policies in version.app_policies.items()},
        },
    )

    ground_truth = os.path.join(task_directory, "ground_truth")
    for name in BASE_GROUND_TRUTH_TO_REMOVE:
        path = os.path.join(ground_truth, name)
        shutil.rmtree(path) if os.path.isdir(path) else (os.path.exists(path) and os.remove(path))
    # The grader is the scenario's evaluation.py followed by the checks shared by all scenarios.
    grader = (SCENARIOS_DIRECTORY / scenario.name / "evaluation.py").read_text() + "\n\n" + COMMON_CHECKS.read_text()
    with open(os.path.join(ground_truth, "evaluation.py"), "w") as file:
        file.write(grader)
    private_data = {
        "scenario": scenario.name,
        "version": version.number,
        "expected": version.expected,
        "conflicts": version.conflicts,
        "policies": [
            {"key": policy.key, "owner": owner, "role": policy.role, "text": policy.text}
            for owner, policy in policies_of(version)
        ],
    }
    for name, content in [("private_data.json", private_data), ("public_data.json", {}),
                          ("answer.json", scenario.answer), ("test_data.json", None)]:
        with open(os.path.join(ground_truth, name), "w") as file:
            json.dump(content, file, indent=4)
    _update_json(os.path.join(ground_truth, "metadata.json"), {"mode": "minimal"})
    return task_id


def write_datasets() -> dict[str, list[str]]:
    """One dataset per version number, and one with all tasks; only tasks that are built are listed."""
    built = set(os.listdir(os.path.join(path_store.data, "tasks")))
    datasets: dict[str, list[str]] = {f"{DATASET_PREFIX}_v{number}": [] for number in (1, 2, 3, 4)}
    for name in scenario_names():
        scenario = load_scenario(name)
        for version in scenario.versions:
            if scenario.task_id(version) in built:
                datasets[f"{DATASET_PREFIX}_v{version.number}"].append(scenario.task_id(version))
    datasets[f"{DATASET_PREFIX}_all"] = sorted(task_id for task_ids in datasets.values() for task_id in task_ids)
    for dataset_name, task_ids in datasets.items():
        with open(os.path.join(path_store.data, "datasets", f"{dataset_name}.txt"), "w") as file:
            file.write("".join(task_id + "\n" for task_id in task_ids))
    return datasets


def _update_json(path: str, updates: dict) -> None:
    with open(path) as file:
        content = json.load(file)
    with open(path, "w") as file:
        json.dump(content | updates, file, indent=4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", help="scenario names (default: all)")
    args = parser.parse_args()
    for name in args.scenarios or scenario_names():
        print(f"{name}: built {', '.join(build_scenario(load_scenario(name)))}")
    for dataset_name, task_ids in write_datasets().items():
        print(f"data/datasets/{dataset_name}.txt: {len(task_ids)} tasks")


if __name__ == "__main__":
    main()
