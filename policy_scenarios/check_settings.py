"""Check that each policy setting's tasks show the agent the right policy API docs.

For each setting, makes a temporary copy of an AppWorld train task, writes the setting's API doc changes into it
(write_setting_api_docs), and reads the docs the way an agent does (apis.api_docs). No LLM is used. Setting 1 must
show exactly its saved supervisor docs and every app's show_policies; settings 2 and 3 must show the supervisor
docs with policy_type and app_name and hide every show_policies, also from search. The copies are deleted at the end.

Usage (from the repo root): .venv/bin/python -m policy_scenarios.check_settings
"""

import json
import os
import shutil
import sys
from typing import Any

from appworld import AppWorld
from appworld.common.path_store import path_store

from policy_scenarios.settings import APPS_WITH_SHOW_POLICIES, SETTING_1_SUPERVISOR_DOCS, SETTINGS, write_setting_api_docs

BASE_TASK_ID = "22cc237_1"  # a train task
CHECK_TASK_ID = "psettingcheck_1"
EXPERIMENT_NAME = "policy_scenarios_settings_check"

failures = 0


def check(passed: bool, message: str, details: Any = None) -> None:
    global failures
    failures += not passed
    print(f"{'ok  ' if passed else 'FAIL'} {message}" + ("" if passed else f"\n     got: {details}"))


def call(world: AppWorld, expression: str) -> Any:
    return json.loads(world.execute(f"import json\nprint(json.dumps({expression}))"))


def visible_docs(world: AppWorld) -> dict[str, Any]:
    """What an agent can see about the policy APIs in this task."""
    listed = {
        app_name: [doc["name"] for doc in call(world, f"apis.api_docs.show_api_descriptions(app_name='{app_name}')")]
        for app_name in APPS_WITH_SHOW_POLICIES
    }
    found = []
    for page_index in range(30):
        page = call(world, f"apis.api_docs.search_api_docs(query='policies', page_index={page_index}, page_limit=20)")
        if not page:
            break
        found += [f"{doc['app_name']}.{doc['api_name']}" for doc in page]
    supervisor_docs = {
        api_name: call(world, f"apis.api_docs.show_api_doc(app_name='supervisor', api_name='{api_name}')")
        for api_name in SETTING_1_SUPERVISOR_DOCS
    }
    return {"listed": listed, "found_by_search": found, "supervisor": supervisor_docs}


def main() -> None:
    tasks_directory = os.path.join(path_store.data, "tasks")
    task_directory = os.path.join(tasks_directory, CHECK_TASK_ID)
    try:
        for number in SETTINGS:
            shutil.rmtree(task_directory, ignore_errors=True)
            shutil.copytree(os.path.join(tasks_directory, BASE_TASK_ID), task_directory)
            write_setting_api_docs(CHECK_TASK_ID, number)
            with AppWorld(task_id=CHECK_TASK_ID, experiment_name=EXPERIMENT_NAME) as world:
                seen = visible_docs(world)
            listed = [app for app, names in seen["listed"].items() if "show_policies" in names]
            searched = [name for name in seen["found_by_search"] if name.endswith(".show_policies")]
            if number == 1:
                for api_name, saved in SETTING_1_SUPERVISOR_DOCS.items():
                    doc = seen["supervisor"][api_name]
                    same = {key: doc[key] for key in saved} == saved
                    check(same, f"setting 1: supervisor.{api_name} doc is exactly the saved one", doc)
                check(len(listed) == len(APPS_WITH_SHOW_POLICIES), "setting 1: every app lists show_policies", listed)
            else:
                for api_name, doc in seen["supervisor"].items():
                    names = [parameter["name"] for parameter in doc["parameters"]]
                    check({"policy_type", "app_name"} <= set(names),
                          f"setting {number}: supervisor.{api_name} has policy_type and app_name", names)
                check(not listed, f"setting {number}: no app lists show_policies", listed)
                check(not searched, f"setting {number}: search finds no show_policies", searched)
        check(os.path.getsize(os.path.join(tasks_directory, BASE_TASK_ID, "dbs", "api_docs.jsonl")) == 0,
              "the original task's API docs were not changed")
    finally:
        shutil.rmtree(task_directory, ignore_errors=True)
        shutil.rmtree(os.path.join(path_store.experiment_outputs, EXPERIMENT_NAME), ignore_errors=True)
    print(f"\n{'All checks passed.' if failures == 0 else f'{failures} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
