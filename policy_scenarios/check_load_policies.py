"""Check that load_policies puts policies into a task, that the policy APIs return them, and that grading is
not affected.

Makes a temporary copy of an AppWorld train task, loads made-up policies into it, runs fixed code in it the
same way an agent's code runs (no LLM), and prints ok/FAIL per check. The copy is deleted at the end.

Usage (from the repo root): .venv/bin/python -m policy_scenarios.check_load_policies
"""

import hashlib
import json
import os
import shutil
import sqlite3
import sys
from typing import Any

from appworld import AppWorld
from appworld.apps import get_all_apps
from appworld.common.path_store import path_store

from policy_scenarios.load_policies import load_policies

BASE_TASK_ID = "22cc237_1"  # a train task, so it comes with a correct solution
CHECK_TASK_ID = "ploadcheck_1"
EXPERIMENT_NAME = "policy_scenarios_check"
SUPERVISOR_POLICIES = ["Never ask my manager for money.", "Keep all my Venmo payments private."]
PERSON_POLICIES = ["Do not send me payment requests; I pay in cash."]
APP_POLICIES = {
    "venmo": ["Every payment and payment request must include a note.", "Request only the exact amount owed."],
    "phone": ["Do not send text messages between 10 PM and 8 AM."],
}

failures = 0


def check(passed: bool, message: str, details: Any = None) -> None:
    global failures
    failures += not passed
    print(f"{'ok  ' if passed else 'FAIL'} {message}" + ("" if passed else f"\n     got: {details}"))


def call(world: AppWorld, expression: str) -> Any:
    """Run an API call inside the task, like an agent's code; return its result (or the error text)."""
    output = world.execute(f"import json\nprint(json.dumps({expression}))")
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output.strip()


def texts(policies: Any) -> Any:
    return [policy["policy"] for policy in policies] if isinstance(policies, list) else policies


def file_hash(path: str) -> str:
    with open(path, "rb") as file:
        return hashlib.sha256(file.read()).hexdigest()


def main() -> None:
    tasks_directory = os.path.join(path_store.data, "tasks")
    task_directory = os.path.join(tasks_directory, CHECK_TASK_ID)
    changes_path = os.path.join(task_directory, "dbs", "supervisor.jsonl")
    base_changes_hash = file_hash(os.path.join(tasks_directory, BASE_TASK_ID, "dbs", "supervisor.jsonl"))
    with open(os.path.join(tasks_directory, BASE_TASK_ID, "specs.json")) as file:
        supervisor_email = json.load(file)["supervisor"]["email"]
    # Two other people, taken from AppWorld's list of people (so no AppWorld data is written in this file).
    with sqlite3.connect(os.path.join(path_store.data, "base_dbs", "admin.db")) as connection:
        person_email, other_email = [
            row[0]
            for row in connection.execute(
                "SELECT email FROM main_users WHERE email != ? ORDER BY id LIMIT 2", (supervisor_email,)
            )
        ]
    policies = {
        "supervisor": SUPERVISOR_POLICIES,
        "people": {person_email: PERSON_POLICIES},
        "apps": APP_POLICIES,
    }

    shutil.rmtree(task_directory, ignore_errors=True)
    shutil.copytree(os.path.join(tasks_directory, BASE_TASK_ID), task_directory)
    try:
        # 1. Loading: a second load replaces the first; loading the same policies again changes nothing.
        load_policies(CHECK_TASK_ID, {"supervisor": ["An old policy that must be replaced."]})
        load_policies(CHECK_TASK_ID, policies)
        hash_after_load = file_hash(changes_path)
        load_policies(CHECK_TASK_ID, policies)
        check(file_hash(changes_path) == hash_after_load, "loading the same policies twice changes nothing")

        # 2. Bad input is rejected, and the task is left as it was.
        bad_inputs = {
            "an unknown app": {"apps": {"not_an_app": ["x"]}},
            "an unknown person": {"people": {"nobody@nowhere.com": ["x"]}},
            "an empty policy": {"supervisor": [" "]},
            "the supervisor under 'people'": {"people": {supervisor_email: ["x"]}},
        }
        for name, bad_policies in bad_inputs.items():
            try:
                load_policies(CHECK_TASK_ID, bad_policies)
                rejected = False
            except ValueError:
                rejected = True
            check(rejected and file_hash(changes_path) == hash_after_load, f"rejects {name}; task unchanged")
        try:
            load_policies(BASE_TASK_ID, policies)
            rejected = False
        except ValueError:
            rejected = True
        check(rejected, "refuses to change an original AppWorld task")

        # 3. The policy APIs return exactly the loaded policies.
        with AppWorld(task_id=CHECK_TASK_ID, experiment_name=EXPERIMENT_NAME) as world:
            result = texts(call(world, "apis.supervisor.show_my_policies()"))
            check(result == SUPERVISOR_POLICIES, "show_my_policies returns the supervisor's policies", result)
            result = texts(call(world, f"apis.supervisor.show_person_policies(email='{person_email}')"))
            check(result == PERSON_POLICIES, "show_person_policies returns that person's policies", result)
            result = texts(call(world, f"apis.supervisor.show_person_policies(email='{other_email}')"))
            check(result == [], "show_person_policies returns [] for a person without policies", result)
            result = texts(call(world, f"apis.supervisor.show_person_policies(email='{supervisor_email}')"))
            check(result == SUPERVISOR_POLICIES, "show_person_policies works for the supervisor's email", result)
            result = call(world, "apis.supervisor.show_person_policies(email='nobody@nowhere.com')")
            check("No person with this email address exists." in str(result), "unknown email gives an error", result)
            for app_name in get_all_apps(skip_admin=True, skip_api_docs=True, skip_supervisor=True):
                result = texts(call(world, f"apis.{app_name}.show_policies()"))
                expected = APP_POLICIES.get(app_name, [])
                check(result == expected, f"{app_name}.show_policies returns its {len(expected)} policies", result)

        # 4. Grading is not affected: the task's correct solution still passes with policies loaded.
        # ("full" loads the solution code too; AppWorld's default leaves it out so agents cannot see it.)
        with AppWorld(task_id=CHECK_TASK_ID, experiment_name=EXPERIMENT_NAME, ground_truth_mode="full") as world:
            world.execute(world.task.ground_truth.compiled_solution_code + "\nsolution(apis, requester)")
            tracker = world.evaluate()
        failed = [failure["requirement"] for failure in tracker.failures]
        check(tracker.success, "the task's correct solution still passes grading", failed)

        check(
            file_hash(os.path.join(tasks_directory, BASE_TASK_ID, "dbs", "supervisor.jsonl")) == base_changes_hash,
            "the original task was not changed",
        )
    finally:
        shutil.rmtree(task_directory, ignore_errors=True)
        shutil.rmtree(os.path.join(path_store.experiment_outputs, EXPERIMENT_NAME), ignore_errors=True)
    print(f"\n{'All checks passed.' if failures == 0 else f'{failures} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
