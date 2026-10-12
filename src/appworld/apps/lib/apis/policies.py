import sys

from fastapi import FastAPI
from inflection import titleize

from appworld.apps.lib.responses import PolicyResponse, response_args
from appworld.common.imports import import_models_module
from appworld.common.types import ListOfDicts


def add_show_policies_api(app: FastAPI, app_name: str) -> None:
    """Add the show_policies API to an app. Its policies are stored per task in the supervisor DB."""

    def show_policies() -> ListOfDicts:
        supervisor_models = import_models_module("supervisor")
        policies = supervisor_models.AppPolicy.find_all(app_name_=app_name)
        return [policy.to_dict(humanize=True) for policy in sorted(policies, key=lambda p: p.id)]

    # Set before registering the route: FastAPI builds the API's documentation from the docstring.
    titleized_name = titleize(app_name.replace("_", " "))
    show_policies.__doc__ = f"""
    description: Show the policies of the {titleized_name} app, i.e., the rules anyone using this app must follow.
    model: AppPolicy
    ---
    success:
    [
        {{
            "policy_id": 1,
            "policy": "string"
        }}
    ]
    failure:
    {{"message": "string"}}
    """
    app.get("/policies", **response_args(list[PolicyResponse]))(show_policies)
    # AppWorld finds an app's APIs among the functions of its apis module (see get_name_to_apis),
    # so also add it there. setup_app runs while that module is being imported.
    setattr(sys.modules[f"appworld.apps.{app_name}.apis"], "show_policies", show_policies)
