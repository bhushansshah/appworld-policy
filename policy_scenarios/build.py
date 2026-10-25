"""Build policy scenarios into AppWorld tasks, and write the dataset lists to run them.

For each scenario in policy_scenarios/scenarios/s<setting>/<name>/scenario.py and each of its versions, this makes
the task data/tasks/s<setting><name>_<version>: a copy of the scenario's base task (with the scenario's shared world
changes, then the version's own world changes, if any, applied through the apps and recorded by AppWorld) with the
version's instruction, answer and policies (loaded with load_policies), the setting's API docs (what the agent sees
of the policy APIs, see settings.py), and the scenario's grader (evaluation.py) with the version's correct outcome,
policy labels (relevance, level, app) and conflicts as private data. It then writes, for each setting n that has
scenarios, data/datasets/policy_s<n>_all.txt, policy_s<n>_v1.txt ... _v4.txt and policy_s<n>_<name>.txt.

The scenario files are kept encrypted in git; unpack them first (policy_scenarios/bundle.py).

Usage (from the repo root): .venv/bin/python -m policy_scenarios.build [s<setting>/<name> ...]  (default: all)
"""

import argparse
import importlib.util
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from appworld.common.path_store import path_store
from appworld.task import load_task_ids

from policy_scenarios.load_policies import load_policies
from policy_scenarios.scenario import SETTING_NUMBERS, Policy, Scenario, Version, policies_of
from policy_scenarios.settings import write_setting_api_docs
from policy_scenarios.task_db import record_task_changes

SCENARIOS_DIRECTORY = Path(__file__).resolve().parent / "scenarios"
COMMON_CHECKS = Path(__file__).resolve().parent / "common_checks.py"  # appended to every scenario's grader
DATASET_PREFIX = "policy"
WORLD_EXPERIMENT = "policy_scenarios_world_setup"  # temporary run outputs while applying world changes
# The base task's solution and its generator do not apply to the new versions.
BASE_GROUND_TRUTH_TO_REMOVE = [
    "solution.py", "compiled_solution.py", "generator.py", "api_calls.json", "required_apps.json",
    "required_apis.json", "__pycache__",
]


def scenario_keys() -> list[str]:
    """Every scenario's folder under policy_scenarios/scenarios/, e.g. "s1/workdinner"."""
    if not SCENARIOS_DIRECTORY.exists():
        raise FileNotFoundError(
            f"{SCENARIOS_DIRECTORY} does not exist. Unpack the scenarios first: "
            ".venv/bin/python -m policy_scenarios.bundle unpack"
        )
    paths = SCENARIOS_DIRECTORY.glob("s*/*/scenario.py")
    return sorted(str(path.parent.relative_to(SCENARIOS_DIRECTORY)) for path in paths)


def load_scenario(key: str) -> Scenario:
    path = SCENARIOS_DIRECTORY / key / "scenario.py"
    spec = importlib.util.spec_from_file_location(f"policy_scenario_{key.replace('/', '_')}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    scenario: Scenario = module.SCENARIO
    if scenario.key != key:
        raise ValueError(f"{path}: the scenario's setting and name ({scenario.key!r}) must match its folder ({key!r}).")
    return scenario


def build_scenario(scenario: Scenario) -> list[str]:
    if scenario.base_task_id not in load_task_ids("train") + load_task_ids("dev"):
        raise ValueError(f"{scenario.key}: the base task must be a train or dev task (not test).")
    try:
        source_task_id = prepare_world(scenario) if scenario.world_setup else scenario.base_task_id
        return [build_version(scenario, version, source_task_id) for version in scenario.versions]
    finally:  # version 0 is only a temporary task (see prepare_world)
        shutil.rmtree(os.path.join(path_store.data, "tasks", scenario.task_id(0)), ignore_errors=True)


def prepare_world(scenario: Scenario) -> str:
    """Make version 0: a copy of the base task with the scenario's shared world changes."""
    task_id = scenario.task_id(0)
    task_directory = os.path.join(path_store.data, "tasks", task_id)
    shutil.rmtree(task_directory, ignore_errors=True)
    shutil.copytree(os.path.join(path_store.data, "tasks", scenario.base_task_id), task_directory)
    apply_world_setup(task_id, scenario.world_setup)  # type: ignore[arg-type]
    return task_id


def apply_world_setup(task_id: str, world_setup: Callable[[Any], None]) -> None:
    """Run world_setup in the task's world and save the changes, as recorded by AppWorld, into the task's dbs."""
    from appworld import AppWorld

    try:
        with AppWorld(task_id=task_id, experiment_name=WORLD_EXPERIMENT, allow_datetime_change=True) as world:
            world_setup(world)
            world.save()
        saved_directory = os.path.join(path_store.experiment_outputs, WORLD_EXPERIMENT, "tasks", task_id, "dbs")
        task_dbs = os.path.join(path_store.data, "tasks", task_id, "dbs")
        for name in os.listdir(saved_directory):
            if name.endswith(".jsonl"):
                shutil.copy(os.path.join(saved_directory, name), os.path.join(task_dbs, name))
    finally:
        shutil.rmtree(os.path.join(path_store.experiment_outputs, WORLD_EXPERIMENT), ignore_errors=True)


def set_instruction(task_id: str, instruction: str) -> None:
    """Set the task's instruction in specs.json (what agents are given) and in its supervisor DB task row (what
    supervisor.show_active_task returns). As in load_policies, the row is changed through AppWorld's models and
    the SQL it runs is recorded into the task's supervisor DB changes."""
    task_directory = os.path.join(path_store.data, "tasks", task_id)
    _update_json(os.path.join(task_directory, "specs.json"), {"instruction": instruction})

    def change_instruction(models: Any) -> None:
        (task,) = models.supervisor.Task.all()
        task.instruction = instruction
        task.save()

    record_task_changes(task_id, "supervisor", change_instruction)


def build_version(scenario: Scenario, version: Version, source_task_id: str) -> str:
    tasks_directory = os.path.join(path_store.data, "tasks")
    task_id = scenario.task_id(version)
    task_directory = os.path.join(tasks_directory, task_id)
    shutil.rmtree(task_directory, ignore_errors=True)
    shutil.copytree(os.path.join(tasks_directory, source_task_id), task_directory)
    try:
        fill_version(scenario, version, task_id)
    except BaseException:
        shutil.rmtree(task_directory, ignore_errors=True)  # never leave a half-built task (it has the base grader)
        raise
    return task_id


def fill_version(scenario: Scenario, version: Version, task_id: str) -> None:
    """Turn the copy of the source task at data/tasks/<task_id> into the version's task."""
    task_directory = os.path.join(path_store.data, "tasks", task_id)
    if version.world_setup:  # this version's own world changes, on top of the shared ones
        apply_world_setup(task_id, version.world_setup)

    instruction = version.instruction or scenario.instruction
    if instruction:
        set_instruction(task_id, instruction)

    def person_policies(policies: list[Policy]) -> list[Any]:
        return [p.text if p.app is None else {"app": p.app, "policy": p.text} for p in policies]

    load_policies(
        task_id,
        {
            "supervisor": person_policies(version.supervisor_policies),
            "people": {email: person_policies(policies) for email, policies in version.people_policies.items()},
            "apps": {app: [p.text for p in policies] for app, policies in version.app_policies.items()},
        },
    )
    write_setting_api_docs(task_id, scenario.setting)

    ground_truth = os.path.join(task_directory, "ground_truth")
    for name in BASE_GROUND_TRUTH_TO_REMOVE:
        path = os.path.join(ground_truth, name)
        shutil.rmtree(path) if os.path.isdir(path) else (os.path.exists(path) and os.remove(path))
    # The grader is the scenario's evaluation.py followed by the checks shared by all scenarios.
    grader = (SCENARIOS_DIRECTORY / scenario.key / "evaluation.py").read_text() + "\n\n" + COMMON_CHECKS.read_text()
    with open(os.path.join(ground_truth, "evaluation.py"), "w") as file:
        file.write(grader)
    private_data = {
        "scenario": scenario.name,
        "setting": scenario.setting,
        "version": version.number,
        "expected": version.expected,
        "conflicts": [asdict(conflict) for conflict in version.conflicts],
        "policies": [
            {"key": policy.key, "owner": owner, "app": policy.app, "relevance": policy.relevance,
             "level": policy.level, "text": policy.text}
            for owner, policy in policies_of(version)
        ],
    }
    for name, content in [("private_data.json", private_data), ("public_data.json", {}),
                          ("answer.json", scenario.answer_of(version)), ("test_data.json", None)]:
        with open(os.path.join(ground_truth, name), "w") as file:
            json.dump(content, file, indent=4)
    _update_json(os.path.join(ground_truth, "metadata.json"), {"mode": "minimal"})


def write_datasets() -> dict[str, list[str]]:
    """Per setting that has scenarios: one dataset per version number, one per scenario, and one with all its
    tasks; only tasks that are built are listed."""
    built = set(os.listdir(os.path.join(path_store.data, "tasks")))
    scenarios = [load_scenario(key) for key in scenario_keys()]
    datasets: dict[str, list[str]] = {}
    for setting in SETTING_NUMBERS:
        prefix = f"{DATASET_PREFIX}_s{setting}"
        in_setting = [scenario for scenario in scenarios if scenario.setting == setting]
        if not in_setting:
            continue
        by_version: dict[str, list[str]] = {f"{prefix}_v{number}": [] for number in (1, 2, 3, 4)}
        for scenario in in_setting:
            task_ids = [scenario.task_id(v) for v in scenario.versions if scenario.task_id(v) in built]
            datasets[f"{prefix}_{scenario.name}"] = task_ids
            for version in scenario.versions:
                if scenario.task_id(version) in built:
                    by_version[f"{prefix}_v{version.number}"].append(scenario.task_id(version))
        datasets |= by_version
        datasets[f"{prefix}_all"] = sorted(task_id for task_ids in by_version.values() for task_id in task_ids)
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
    parser.add_argument(
        "scenarios", nargs="*", help="scenarios as s<setting>/<name>, e.g. s1/workdinner (default: all)"
    )
    args = parser.parse_args()
    for key in args.scenarios or scenario_keys():
        print(f"{key}: built {', '.join(build_scenario(load_scenario(key)))}")
    for dataset_name, task_ids in write_datasets().items():
        print(f"data/datasets/{dataset_name}.txt: {len(task_ids)} tasks")


if __name__ == "__main__":
    main()
