"""Load a task's policies into its own data, so the policy APIs return them when the task runs.

Policies are given as:
    {
        "supervisor": ["policy", ...],                 # the task's supervisor (the user)
        "people": {"email": ["policy", ...], ...},     # other people, by email
        "apps": {"app_name": ["policy", ...], ...},    # apps, e.g. "venmo"
    }
Every key is optional; {} removes all policies from the task.

They are written into data/tasks/<task_id>/dbs/supervisor.jsonl, the task's own changes to the supervisor DB
(the file that already sets up the supervisor's profile, cards and passwords). As AppWorld does when building
tasks, the rows are created through AppWorld's models and the SQL they run is recorded, so every line has the
format and record_hash AppWorld expects. Loading again replaces the task's previous policies.
"""

import json
import os
from typing import Any

import orjson

from appworld.apps import get_all_apps
from appworld.apps.lib.models.db import CachedDBHandler
from appworld.collections.models import ModelCollection
from appworld.common.path_store import path_store
from appworld.task import load_task_ids

POLICY_TABLES = ("person_policies", "app_policies")
APPWORLD_DATASETS = ("train", "dev", "test_normal", "test_challenge")


def load_policies(task_id: str, policies: dict[str, Any]) -> None:
    task_directory = os.path.join(path_store.data, "tasks", task_id)
    if any(task_id in load_task_ids(dataset) for dataset in APPWORLD_DATASETS):
        raise ValueError(f"{task_id} is an original AppWorld task. Load policies into a copy of it instead.")
    with open(os.path.join(task_directory, "specs.json")) as file:
        supervisor_email = json.load(file)["supervisor"]["email"]
    supervisor_policies, people_policies, app_policies = _validate(policies, supervisor_email)

    changes_path = os.path.join(task_directory, "dbs", "supervisor.jsonl")
    with open(changes_path) as file:
        original_content = file.read()
    try:
        # Drop the task's previous policy lines, then load its supervisor DB (base DB + remaining changes).
        lines = [line for line in original_content.splitlines() if not _is_policy_change(line)]
        with open(changes_path, "w") as file:
            file.write("".join(line + "\n" for line in lines))
        new_changes = _record_policy_changes(
            task_id, supervisor_email, supervisor_policies, people_policies, app_policies
        )
        with open(changes_path, "a") as file:
            for change in new_changes:
                file.write(orjson.dumps(change).decode() + "\n")
    except BaseException:
        with open(changes_path, "w") as file:  # leave the task exactly as it was
            file.write(original_content)
        raise


def _record_policy_changes(
    task_id: str,
    supervisor_email: str,
    supervisor_policies: list[str],
    people_policies: dict[str, list[str]],
    app_policies: dict[str, list[str]],
) -> list[Any]:
    """Create the policy rows in an in-memory copy of the task's supervisor DB; return the SQL they ran."""
    memory_db_home = f":memory:policy_loader-{task_id}"
    models = ModelCollection.load(
        to_db_home_path=memory_db_home,
        from_db_home_path=os.path.join(path_store.data, "tasks", task_id, "dbs"),
        load_apps=["supervisor"],
    )
    try:
        for email in people_policies:
            if not models.admin.MainUser.exists(email=email):
                raise ValueError(f"No person with the email {email!r} exists in AppWorld.")
        tracker = models.supervisor.PersonPolicy.db.tracker
        num_old_changes = len(tracker.changes)
        for email, texts in [(supervisor_email, supervisor_policies), *people_policies.items()]:
            for text in texts:
                models.supervisor.PersonPolicy.create_save(email=email, policy=text)
        for app_name, texts in app_policies.items():
            for text in texts:
                models.supervisor.AppPolicy.create_save(app_name_=app_name, policy=text)
        new_changes = tracker.changes[num_old_changes:]
    finally:
        CachedDBHandler.reset(key_substring=memory_db_home)
    assert all(_is_policy_change(orjson.dumps(change).decode()) for change in new_changes), new_changes
    return new_changes


def _is_policy_change(line: str) -> bool:
    statement = json.loads(line)[0]
    return any(statement.startswith(f"INSERT INTO {table} ") for table in POLICY_TABLES)


def _validate(
    policies: dict[str, Any], supervisor_email: str
) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    unknown_keys = set(policies) - {"supervisor", "people", "apps"}
    if unknown_keys:
        raise ValueError(f"Unknown policy groups: {sorted(unknown_keys)}. Use supervisor, people and apps.")
    supervisor_policies = _texts(policies.get("supervisor", []), "supervisor")
    people_policies = {
        email: _texts(texts, email) for email, texts in policies.get("people", {}).items()
    }
    if supervisor_email in people_policies:
        raise ValueError("Give the supervisor's own policies under 'supervisor', not 'people'.")
    valid_app_names = get_all_apps(skip_admin=True, skip_api_docs=True, skip_supervisor=True)
    app_policies = {}
    for app_name, texts in policies.get("apps", {}).items():
        if app_name not in valid_app_names:
            raise ValueError(f"Unknown app {app_name!r}. Valid apps: {', '.join(valid_app_names)}.")
        app_policies[app_name] = _texts(texts, app_name)
    return supervisor_policies, people_policies, app_policies


def _texts(texts: Any, owner: str) -> list[str]:
    if not isinstance(texts, list) or not all(isinstance(text, str) and text.strip() for text in texts):
        raise ValueError(f"Policies of {owner} must be a list of non-empty strings.")
    return [text.strip() for text in texts]
