"""The API docs the agent sees in setting 3, the only policy setting.

A person, the user or someone else, can have general policies (not tied to any app) and policies for one app. Both
are read through the supervisor app: without app_name for the general policies, with app_name for one app's. The
policies do not change what counts as task success; they only choose among the task's correct end states.

AppWorld lets each task change the API docs (data/tasks/<task_id>/dbs/api_docs.jsonl, on top of
data/base_dbs/api_docs.db, which is generated from the code), so the builder writes these doc changes into every task.
"""

from typing import Any

from policy_scenarios.task_db import record_task_changes

EMAIL_PARAMETER = {
    "name": "email",
    "type": "string",
    "required": True,
    "description": "Email address of the person to show the policies of.",
    "default": None,
    "constraints": ["value is email address"],
}
APP_NAME_PARAMETER = {
    "name": "app_name",
    "type": "string",
    "required": False,
    "description": 'The app to show the policies for, e.g. "venmo". Leave it out to show the general policies, '
                   "which are not tied to any app.",
    "default": None,
    "constraints": [],
}
# Supervisor API -> fields of its doc to replace.
SUPERVISOR_DOCS = {
    "show_my_policies": {
        "description": "Show your supervisor's policies, i.e., their preferences for how you act on their behalf: "
                       "their general policies, or, with app_name, their policies for one app.",
        "parameters": [APP_NAME_PARAMETER],
    },
    "show_person_policies": {
        "description": "Show another person's policies, i.e., their preferences for how anyone acting on them "
                       "treats them: their general policies, or, with app_name, their policies for one app.",
        "parameters": [EMAIL_PARAMETER, APP_NAME_PARAMETER],
    },
}


def write_api_docs(task_id: str) -> None:
    """Change the task's API docs to what the agent sees."""

    def change_docs(models: Any) -> None:
        api_doc = models.api_docs.ApiDoc
        for api_name, fields in SUPERVISOR_DOCS.items():
            doc = api_doc.find_one(app_name_="supervisor", api_name=api_name)
            for key, value in fields.items():
                setattr(doc, key, value)
            doc.save()

    record_task_changes(task_id, "api_docs", change_docs)
