"""Check that tasks show the agent the right policy API docs.

Makes a temporary copy of an AppWorld train task, writes the API doc changes into it (write_api_docs), and reads the
docs the way an agent does (apis.api_docs). No LLM is used. No app may have a show_policies API, also in search, and
the supervisor docs must have an optional app_name (left out, the APIs return the general policies). The copy is
deleted at the end.

Usage (from the repo root): .venv/bin/python -m policy_scenarios.check_settings
"""

import json
import os
import shutil
import sys
from typing import Any

from appworld import AppWorld
from appworld.apps import get_all_apps
from appworld.common.path_store import path_store

from policy_scenarios.settings import SUPERVISOR_DOCS, write_api_docs

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
        for app_name in get_all_apps(skip_admin=True, skip_api_docs=True, skip_supervisor=True)
    }
    found = []
    for page_index in range(30):
        page = call(world, f"apis.api_docs.search_api_docs(query='policies', page_index={page_index}, page_limit=20)")
        if not page:
            break
        found += [f"{doc['app_name']}.{doc['api_name']}" for doc in page]
    supervisor_docs = {
        api_name: call(world, f"apis.api_docs.show_api_doc(app_name='supervisor', api_name='{api_name}')")
        for api_name in SUPERVISOR_DOCS
    }
    return {"listed": listed, "found_by_search": found, "supervisor": supervisor_docs}


def main() -> None:
    tasks_directory = os.path.join(path_store.data, "tasks")
    task_directory = os.path.join(tasks_directory, CHECK_TASK_ID)
    try:
        shutil.rmtree(task_directory, ignore_errors=True)
        shutil.copytree(os.path.join(tasks_directory, BASE_TASK_ID), task_directory)
        write_api_docs(CHECK_TASK_ID)
        with AppWorld(task_id=CHECK_TASK_ID, experiment_name=EXPERIMENT_NAME) as world:
            seen = visible_docs(world)
        listed = [app for app, names in seen["listed"].items() if "show_policies" in names]
        searched = [name for name in seen["found_by_search"] if name.endswith(".show_policies")]
        for api_name, doc in seen["supervisor"].items():
            required = {parameter["name"]: parameter["required"] for parameter in doc["parameters"]}
            expected = {"app_name": False} | ({"email": True} if api_name == "show_person_policies" else {})
            check(required == expected, f"supervisor.{api_name} takes an optional app_name (and nothing else new)",
                  required)
            check("general" in doc["description"], f"supervisor.{api_name}'s description mentions general policies",
                  doc["description"])
        check(not listed, "no app lists show_policies", listed)
        check(not searched, "search finds no show_policies", searched)
        check(os.path.getsize(os.path.join(tasks_directory, BASE_TASK_ID, "dbs", "api_docs.jsonl")) == 0,
              "the original task's API docs were not changed")
    finally:
        shutil.rmtree(task_directory, ignore_errors=True)
        shutil.rmtree(os.path.join(path_store.experiment_outputs, EXPERIMENT_NAME), ignore_errors=True)
    print(f"\n{'All checks passed.' if failures == 0 else f'{failures} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
