"""Change a task's own data through AppWorld's models, and save the changes the way AppWorld builds tasks.

A task's data is the shared base DBs (data/base_dbs/<app>.db) plus the task's own changes to them
(data/tasks/<task_id>/dbs/<app>.jsonl, one SQL statement per line). Making a change through AppWorld's models
and recording the SQL it runs gives every line the format and record_hash AppWorld expects.
"""

import os
from collections.abc import Callable
from typing import Any

import orjson

from appworld.apps.lib.models.db import CachedDBHandler
from appworld.collections.models import ModelCollection
from appworld.common.path_store import path_store


def record_task_changes(task_id: str, app_name: str, change: Callable[[Any], None]) -> list[Any]:
    """Load the task's data for one app in memory, call change(models), and append the SQL it ran to the task's
    dbs/<app_name>.jsonl. Returns the recorded changes. (admin and supervisor are always loaded too.)"""
    task_dbs = os.path.join(path_store.data, "tasks", task_id, "dbs")
    memory_db_home = f":memory:policy_scenarios-{app_name}-{task_id}"
    models = ModelCollection.load(to_db_home_path=memory_db_home, from_db_home_path=task_dbs, load_apps=[app_name])
    try:
        tracker = models[app_name].SQLModel.db.tracker
        num_old_changes = len(tracker.changes)
        change(models)
        new_changes = tracker.changes[num_old_changes:]
    finally:
        CachedDBHandler.reset(key_substring=memory_db_home)
    with open(os.path.join(task_dbs, f"{app_name}.jsonl"), "a") as file:
        for new_change in new_changes:
            file.write(orjson.dumps(new_change).decode() + "\n")
    return new_changes
