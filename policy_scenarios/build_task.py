"""Build single policy tasks into AppWorld tasks, and write the dataset lists to run them.

A single task lives in policy_scenarios/tasks/s<setting>/<name>/ (task.py, evaluation.py, solution.py; see
policy_scenarios/task_spec.py). Building it makes the AppWorld task data/tasks/s<setting><name>_1, step by step
(see build_task below), and then writes data/datasets/policy_s<setting>_tasks.txt for each setting that has tasks.

The task files are kept encrypted in git, like the scenarios; unpack them first (policy_scenarios/bundle.py).

Usage (from the repo root): .venv/bin/python -m policy_scenarios.build_task [s<setting>/<name> ...]  (default: all)
e.g. .venv/bin/python -m policy_scenarios.build_task s3/giftbottlev1
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
from dataclasses import asdict
from pathlib import Path

from appworld.common.path_store import path_store
from appworld.task import load_task_ids

from policy_scenarios.build import (
    BASE_GROUND_TRUTH_TO_REMOVE, COMMON_CHECKS, DATASET_PREFIX, SCENARIOS_DIRECTORY, _update_json, apply_world_setup,
    set_instruction,
)
from policy_scenarios.load_policies import load_policies
from policy_scenarios.scenario import SETTING_NUMBERS, Policy, policies_of
from policy_scenarios.settings import write_setting_api_docs
from policy_scenarios.task_spec import Task, check_task

TASKS_DIRECTORY = Path(__file__).resolve().parent / "tasks"
BASE_TASK_SPLITS = ["train", "dev", "test_normal", "test_challenge"]


def task_keys() -> list[str]:
    """Every task's folder under policy_scenarios/tasks/, e.g. "s3/giftbottlev1"."""
    if not TASKS_DIRECTORY.exists():
        raise FileNotFoundError(
            f"{TASKS_DIRECTORY} does not exist. Unpack the tasks first: .venv/bin/python -m policy_scenarios.bundle unpack"
        )
    return sorted(str(path.parent.relative_to(TASKS_DIRECTORY)) for path in TASKS_DIRECTORY.glob("s*/*/task.py"))


def split_key(key: str) -> tuple[int, str]:
    """"s3/giftbottlev1" -> (3, "giftbottlev1")."""
    match = re.fullmatch(r"s(\d)/([a-z0-9]+)", key)
    if match is None:
        raise ValueError(f"{key!r}: give a task as s<setting>/<name> (name: lowercase letters and digits only).")
    return int(match.group(1)), match.group(2)


def task_id_of(key: str) -> str:
    """"s3/giftbottlev1" -> "s3giftbottlev1_1". AppWorld's task ids are <task idea>_<number> (exactly one "_"), so a
    single task is number 1 of its own task idea."""
    setting, name = split_key(key)
    return f"s{setting}{name}_1"


def load_task(key: str) -> Task:
    path = TASKS_DIRECTORY / key / "task.py"
    spec = importlib.util.spec_from_file_location(f"policy_task_{key.replace('/', '_')}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.TASK


def build_task(key: str) -> str:
    """Build the task in policy_scenarios/tasks/<key>/ into data/tasks/<task id>, and return the task id."""
    setting, name = split_key(key)
    task = load_task(key)
    task_id = task_id_of(key)
    check_task(task, setting, task_id)
    if (SCENARIOS_DIRECTORY / f"s{setting}" / name).exists():
        raise ValueError(f"{key}: a scenario has the same name, so their task ids would clash; rename the task.")
    if task.base_task_id not in sum((load_task_ids(split) for split in BASE_TASK_SPLITS), []):
        raise ValueError(f"{key}: the base task must be an AppWorld task ({', '.join(BASE_TASK_SPLITS)}).")

    # 1. Copy the base task's folder: its world (dbs/), instruction and user (specs.json) and grader (ground_truth/).
    task_directory = os.path.join(path_store.data, "tasks", task_id)
    shutil.rmtree(task_directory, ignore_errors=True)
    shutil.copytree(os.path.join(path_store.data, "tasks", task.base_task_id), task_directory)
    try:
        # 2. Change the world (e.g. empty the cart). AppWorld records the changes into the task's dbs/.
        if task.world_setup:
            apply_world_setup(task_id, task.world_setup)

        # 3. Set the instruction the agent is given (in specs.json and in the supervisor's task row).
        if task.instruction:
            set_instruction(task_id, task.instruction)

        # 4. Put the policies in the world, so the policy APIs (e.g. supervisor.show_policies) return them.
        def person_policies(policies: list[Policy]) -> list:
            return [p.text if p.app is None else {"app": p.app, "policy": p.text} for p in policies]

        load_policies(task_id, {
            "supervisor": person_policies(task.supervisor_policies),
            "people": {email: person_policies(policies) for email, policies in task.people_policies.items()},
            "apps": {app: [p.text for p in policies] for app, policies in task.app_policies.items()},
        })

        # 5. Change the API docs to what the agent sees in this setting (which policy APIs exist).
        write_setting_api_docs(task_id, setting)

        # 6. Replace the base task's solution and grader with ours: evaluation.py followed by the checks shared by
        # all scenarios and tasks (policy_scenarios/common_checks.py). With base_grader, the base task's grader comes
        # first, unchanged except that its evaluate is renamed base_evaluate (our evaluate runs it for the [TASK]
        # checks), and its data files are read before they are rewritten below.
        ground_truth = os.path.join(task_directory, "ground_truth")
        base_data = {}
        base_grader = ""
        if task.base_grader:
            for file_name in ["public_data.json", "private_data.json", "answer.json"]:
                with open(os.path.join(ground_truth, file_name)) as file:
                    base_data[file_name] = json.load(file)
            base_grader, renamed = re.subn(r"^def evaluate\(", "def base_evaluate(",
                                           Path(ground_truth, "evaluation.py").read_text(), flags=re.M)
            if renamed != 1:
                raise ValueError(f"{key}: the base task's grader must define evaluate exactly once.")
            base_grader += "\n\n"
        for file_name in BASE_GROUND_TRUTH_TO_REMOVE:
            path = os.path.join(ground_truth, file_name)
            shutil.rmtree(path) if os.path.isdir(path) else (os.path.exists(path) and os.remove(path))
        grader = base_grader + (TASKS_DIRECTORY / key / "evaluation.py").read_text() + "\n\n" + COMMON_CHECKS.read_text()
        with open(os.path.join(ground_truth, "evaluation.py"), "w") as file:
            file.write(grader)

        # 7. Write what the grader and the report read: the correct outcome and the policy labels (private data),
        # and the answer. The report (policy_scenarios/report.py) reads "scenario" and "version"; a single task has
        # neither.
        private_data = {
            "scenario": None,
            "task": name,
            "setting": setting,
            "version": None,
            "expected": task.expected,
            "conflicts": [asdict(conflict) for conflict in task.conflicts],
            "policies": [
                {"key": policy.key, "owner": owner, "app": policy.app, "relevance": policy.relevance,
                 "level": policy.level, "text": policy.text}
                for owner, policy in policies_of(task)  # type: ignore[arg-type]
            ],
        }
        public_data, answer = {}, task.answer
        if task.base_grader:  # the base grader's data, with ours added to its private data
            if set(private_data) & set(base_data["private_data.json"]):
                raise ValueError(f"{key}: the base task's private data uses one of our keys: {sorted(private_data)}.")
            private_data = base_data["private_data.json"] | private_data
            public_data, answer = base_data["public_data.json"], base_data["answer.json"]
        for file_name, content in [("private_data.json", private_data), ("public_data.json", public_data),
                                   ("answer.json", answer), ("test_data.json", None)]:
            with open(os.path.join(ground_truth, file_name), "w") as file:
                json.dump(content, file, indent=4)
        _update_json(os.path.join(ground_truth, "metadata.json"), {"mode": "minimal"})
    except BaseException:
        shutil.rmtree(task_directory, ignore_errors=True)  # never leave a half-built task (it has the base grader)
        raise
    return task_id


def write_datasets() -> dict[str, list[str]]:
    """data/datasets/policy_s<setting>_tasks.txt for each setting that has tasks; only built tasks are listed."""
    built = set(os.listdir(os.path.join(path_store.data, "tasks")))
    datasets: dict[str, list[str]] = {}
    for setting in SETTING_NUMBERS:
        keys = [key for key in task_keys() if split_key(key)[0] == setting]
        if keys:
            datasets[f"{DATASET_PREFIX}_s{setting}_tasks"] = [task_id_of(k) for k in keys if task_id_of(k) in built]
    for dataset_name, task_ids in datasets.items():
        with open(os.path.join(path_store.data, "datasets", f"{dataset_name}.txt"), "w") as file:
            file.write("".join(task_id + "\n" for task_id in task_ids))
    return datasets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", nargs="*", help="tasks as s<setting>/<name>, e.g. s3/giftbottlev1 (default: all)")
    args = parser.parse_args()
    for key in args.tasks or task_keys():
        print(f"{key}: built {build_task(key)}")
    for dataset_name, task_ids in write_datasets().items():
        print(f"data/datasets/{dataset_name}.txt: {len(task_ids)} tasks")


if __name__ == "__main__":
    main()
