"""Build policy scenarios: one AppWorld world (one setup) and several tasks on it that differ only in their policies,
solution and grader.

A scenario is specified in policy_scenarios/tasks/task_generators/<id>.yaml and coded in <id>.py next to it, as a
subclass of PolicyScenarioGenerator (below). Building it:
1. runs the scenario's setup once, with AppWorld's own generator engine (BaseTaskGenerator): it picks a user that
   passes the setup's checks, freezes the clock and builds the world;
2. saves that world as one AppWorld task per scenario task (<id>_1, <id>_2, ...), each with its own grader
   (evaluation.py) and solution (compiled_solution.py);
3. loads each task's policies into its world (load_policies) and writes the policy API docs (write_api_docs);
4. writes data/datasets/policy_scenarios.txt, the list of built scenario tasks.

The grader labels each check [TASK] (the job), [POLICY:<key>] (one policy) or [POLICY:general] (the extra work the
policies cause did not damage anything), so policy_scenarios/report.py can report task success and policy compliance
separately. The scenario files are kept encrypted in git; unpack them first (policy_scenarios/bundle.py).

Needs AppWorld's developer tools black and ruff (pyproject.toml's "ci" extra), with .venv/bin on PATH (AppWorld runs
ruff as a command when it saves a task).
Usage (from the repo root): PATH=.venv/bin:$PATH PYTHONHASHSEED=0 .venv/bin/python -m policy_scenarios.scenario_generator
[<id> ...] (default: all scenarios), e.g. ... -m policy_scenarios.scenario_generator p3c13f5a
"""

import argparse
import ast
import importlib.util
import inspect
import os
import shutil
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from munch import Munch

from appworld.apps.admin.models import MainUserMunch
from appworld.apps.lib.models.db import CachedDBHandler
from appworld.collections.apis import ApiCollection
from appworld.common.math import string_to_number
from appworld.common.path_store import path_store
from appworld.common.random import set_random_seed
from appworld.ground_truth import GroundTruth
from appworld.task import Task
from generate.tasks.task_generators.base import BaseTaskGenerator
from policy_scenarios.load_policies import load_policies
from policy_scenarios.settings import write_api_docs
from policy_scenarios.task_spec import LEVELS, RELEVANCE, SETTING


GENERATORS_DIRECTORY = Path(__file__).resolve().parent / "tasks" / "task_generators"
DATASET_NAME = "policy_scenarios"
MAIN_USER = "main_user"  # the owner of the user's own policies, as the YAML writes it
GENERAL = "general"  # the check-only group: the policies' extra work did not damage anything (never shown to the agent)

# The start of every grader. The task's evaluate function and then the scenario's grader helpers follow it.
EVALUATION_HEADER = '''\
import json
import math
import re

from munch import Munch

from appworld.apps.admin.models import MainUserMunch
from appworld.collections.models import ModelCollectionPair
from appworld.common.collections import list_of, set_of
from appworld.common.types import AnswerType
from appworld.evaluator import TestTracker
'''
EVALUATE_DEFINITION = '''\
def evaluate(
    test: TestTracker,
    public_data: Munch,
    private_data: Munch,
    main_user: MainUserMunch,
    models: ModelCollectionPair,
    ground_truth_answer: AnswerType,
) -> None:
    active_tasks = models.end.supervisor.Task.all()
    try:
        predicted_answer = json.loads(active_tasks[0].answer)
    except json.JSONDecodeError:
        predicted_answer = active_tasks[0].answer  # when task completion is not committed.
    test.task_completed = active_tasks[0].status == "success"
'''


@dataclass(frozen=True)
class ScenarioPolicy:
    key: str  # short id, used in the grader's labels, e.g. "whole_dollar_requests"
    owner: str  # "main_user", or "private_data.<field>" holding the email of the person the setup picked
    text: str  # what the agent reads through the policy APIs
    relevance: str  # one of task_spec.RELEVANCE; never shown to the agent
    level: str  # one of task_spec.LEVELS; never shown to the agent
    app: str | None = None  # the app the policy is for; None = a general policy


@dataclass(frozen=True)
class ScenarioTask:
    number: int  # the task id is <scenario id>_<number>
    kind: str  # "no_extra_step", "extra_step" or "combined"
    policies: list[ScenarioPolicy]
    # The correct solution, written as plain Python that only uses `apis` (the code an agent could run). Its body is
    # saved as the task's compiled_solution.py and run by validate_scenario.py; it must end with complete_task.
    solution: Callable[..., None]
    # The grader: evaluation(test, public_data, private_data, main_user, models). Its body becomes the body of the
    # task's evaluate function, after the scenario's grader helpers.
    evaluation: Callable[..., None]
    general_checks: bool = False  # whether the grader has [POLICY:general] checks (tasks with extra-step policies)


@dataclass(frozen=True)
class Mistake:
    """A deliberate mistake in a task's solution, and how the grader must judge it (see validate_scenario.py)."""

    task_number: int
    name: str
    replacements: list[tuple[str, str]]  # (text in the correct solution, what to put instead); each must occur once
    verdict: str  # "compliant", "not compliant" or "task failed"
    violated: list[str] = field(default_factory=list)  # the policy keys the grader must find violated
    code: str | None = None  # run this instead of the changed correct solution (e.g. one that does nothing)


class PolicyScenarioGenerator(BaseTaskGenerator):
    """A scenario: AppWorld's generator (its _setup, parameters and required apps) plus several tasks."""

    tasks: ClassVar[list[ScenarioTask]] = []
    grader_helpers: ClassVar[tuple[Callable[..., Any], ...]] = ()  # functions every grader of the scenario can use
    mistakes: ClassVar[list[Mistake]] = []

    def task_id(self, task: ScenarioTask) -> str:
        return f"{self.id()}_{task.number}"

    def generate_scenario(self, random_seed: int = 1) -> list[str]:
        """Build every task of the scenario (see the module docstring) and return their ids."""
        if "PYTHONHASHSEED" not in os.environ:
            raise RuntimeError("Set PYTHONHASHSEED (e.g. PYTHONHASHSEED=0) so the build is reproducible, as AppWorld "
                               "requires for task generation.")
        self.check_tasks()
        set_random_seed(random_seed * string_to_number(self.id()), python=True, faker_=True, model_factory=True)

        # 1. Run the setup once (AppWorld picks a user that passes it).
        models, main_user, data = self.setup()
        if not isinstance(data.public, Munch) or not isinstance(data.private, Munch):
            raise TypeError("The setup must set data.public and data.private as Munch.")
        main_user_munch = MainUserMunch.from_main_user(main_user)
        self.add_supervisor(models, main_user, data.instruction)

        # 2. Save the world once per task, each with its own grader and solution.
        task_ids = []
        for task in self.tasks:
            task_id = self.task_id(task)
            shutil.rmtree(os.path.join(path_store.data, "tasks", task_id), ignore_errors=True)
            solution_code = compiled_solution_code(task.solution)
            ground_truth = GroundTruth(
                task_id=task_id,
                required_apps=list(self.required_apps),
                required_apis=None,  # inferred from the solution
                public_data=data.public,
                private_data=data.private | self.policy_data(task, task_id, data.private),
                answer=data.answer,
                evaluation_code=self.evaluation_code_of(task),
                solution_code=solution_code,
                compiled_solution_code=solution_code,
                generator_code=inspect.getsource(sys.modules[self.__class__.__module__]),
                test_data=None,
                metadata={"mode": "full", "difficulty": self.difficulty, "kind": task.kind},
            )
            appworld_task = Task(
                id=task_id,
                instruction=data.instruction,
                supervisor=main_user_munch,
                datetime=data.datetime,
                allowed_apps=list(self.allowed_apps),
                model_collection=models,
                db_version=self.db_version(),
            )
            appworld_task.ground_truth = ground_truth
            appworld_task.save(save_ground_truth=True, ground_truth_mode="full", save_model_collection=True,
                               model_collection_format="changes", delete_if_exists=True)
            task_ids.append(task_id)
        models.close()
        ApiCollection.close_all()
        CachedDBHandler.reset()

        # 3. Put each task's policies in its world, and the policy API docs the agent sees.
        for task in self.tasks:
            load_policies(self.task_id(task), self.policies_to_load(task, data.private))
            write_api_docs(self.task_id(task))
        return task_ids

    def check_tasks(self) -> None:
        """Raise a ValueError if the scenario's tasks do not fit the rules."""
        numbers = [task.number for task in self.tasks]
        if not numbers or numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"{self.id()}: the tasks must be numbered 1, 2, 3, ...")
        for task in self.tasks:
            keys = [policy.key for policy in task.policies]
            if len(set(keys)) != len(keys) or GENERAL in keys:
                raise ValueError(f"{self.id()}_{task.number}: policy keys must be distinct and not {GENERAL!r}.")
            for policy in task.policies:
                if policy.relevance not in RELEVANCE or policy.level not in LEVELS:
                    raise ValueError(f"{self.id()}_{task.number}: policy {policy.key!r} has an unknown relevance "
                                     "or level.")
                if policy.owner != MAIN_USER and not policy.owner.startswith("private_data."):
                    raise ValueError(f"{self.id()}_{task.number}: the owner of {policy.key!r} must be {MAIN_USER!r} "
                                     "or private_data.<field>.")

    def add_supervisor(self, models: Any, main_user: Any, instruction: str) -> None:
        """The supervisor's profile, addresses, cards, passwords and active task, as AppWorld's generator adds them
        (BaseTaskGenerator._generate_task)."""
        supervisor = models.supervisor.Supervisor.create_save(
            **main_user.to_dict(keep_computed=False, skip_field_names=["id"])
        )
        for user_address in main_user.user_addresses:
            address = user_address.global_address.to_dict(skip_field_names=["id", "residence_id", "company_id"])
            models.supervisor.Address.create_save(**address, name=user_address.name, supervisor_id=supervisor.id)
        for payment_card in main_user.payment_cards:
            card = payment_card.to_dict(skip_field_names=["id"])
            models.supervisor.PaymentCard.create_save(**card, supervisor_id=supervisor.id)
        for account_password in main_user.account_passwords:
            password = account_password.to_dict(skip_field_names=["id"])
            models.supervisor.AccountPassword.create_save(**password, supervisor_id=supervisor.id)
        models.supervisor.Task.create_save(supervisor_id=supervisor.id, instruction=instruction)

    @staticmethod
    def owner_email(policy: ScenarioPolicy, private_data: Munch) -> str | None:
        """None for the user's own policies, otherwise the email the setup stored in private data."""
        if policy.owner == MAIN_USER:
            return None
        return private_data[policy.owner.removeprefix("private_data.")]

    def policy_data(self, task: ScenarioTask, task_id: str, private_data: Munch) -> dict[str, Any]:
        """What report.py reads from private data: the task, the setting, and each policy's labels (owner:
        "supervisor" for the user's own policies, otherwise the person's email). A task with general checks also
        lists the general group, so its result is reported; it has no text and is never loaded into the world."""
        policies = [
            {"key": policy.key, "owner": self.owner_email(policy, private_data) or "supervisor", "app": policy.app,
             "relevance": policy.relevance, "level": policy.level, "text": policy.text}
            for policy in task.policies
        ]
        if task.general_checks:
            policies.insert(0, {"key": GENERAL, "owner": "supervisor", "app": None, "relevance": "relevant",
                                "level": None, "text": ""})
        return {"task": task_id, "setting": SETTING, "policies": policies}

    def policies_to_load(self, task: ScenarioTask, private_data: Munch) -> dict[str, Any]:
        """The task's policies in the format load_policies takes."""
        supervisor: list[Any] = []
        people: dict[str, list[Any]] = {}
        for policy in task.policies:
            entry = policy.text if policy.app is None else {"app": policy.app, "policy": policy.text}
            email = self.owner_email(policy, private_data)
            if email is None:
                supervisor.append(entry)
            else:
                people.setdefault(email, []).append(entry)
        return {"supervisor": supervisor, "people": people}

    def evaluation_code_of(self, task: ScenarioTask) -> str:
        """evaluate first, then the helpers it calls. (AppWorld's failure report needs lines after a failing line
        of evaluate, so evaluate must not be the last thing in the file.)"""
        helpers = "\n\n\n".join(textwrap.dedent(inspect.getsource(helper)).strip() for helper in self.grader_helpers)
        body = textwrap.indent(function_body(task.evaluation), "    ")
        return f"{EVALUATION_HEADER}\n\n{EVALUATE_DEFINITION}{body}\n\n{helpers}\n"


def function_body(function: Callable[..., Any]) -> str:
    """The code inside a function after its docstring (comments are kept). The function must have a docstring (the
    YAML's steps), so the body starts right after it."""
    source = textwrap.dedent(inspect.getsource(function))
    definition = ast.parse(source).body[0]
    first = definition.body[0] if isinstance(definition, ast.FunctionDef) else None
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)):
        raise ValueError(f"{function.__name__} must be a function with a docstring.")
    return textwrap.dedent("\n".join(source.splitlines()[first.end_lineno:])).strip("\n") + "\n"


def compiled_solution_code(solution: Callable[..., None]) -> str:
    """The solution as AppWorld saves it (compiled_solution.py): solution(apis, requester) runs the body."""
    body = textwrap.indent(function_body(solution), "    ")
    return ("from appworld.collections.apis import ApiCollection\nfrom appworld.requester import Requester\n\n\n"
            f"def solution(apis: ApiCollection, requester: Requester) -> None:\n{body}")


# ---------- Finding and loading scenarios ----------

def scenario_ids() -> list[str]:
    if not GENERATORS_DIRECTORY.exists():
        raise FileNotFoundError(f"{GENERATORS_DIRECTORY} does not exist. Unpack the tasks first: "
                                ".venv/bin/python -m policy_scenarios.bundle unpack")
    return sorted(path.stem for path in GENERATORS_DIRECTORY.glob("*.py") if not path.name.startswith("_"))


def load_scenario(scenario_id: str) -> type[PolicyScenarioGenerator]:
    """The scenario's generator class (its module is imported once per process, as it registers the class)."""
    module_name = f"policy_scenario_{scenario_id}"
    if module_name not in sys.modules:
        path = GENERATORS_DIRECTORY / f"{scenario_id}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    return BaseTaskGenerator.by_id(scenario_id)  # the class the file registered under the scenario's id


def write_dataset() -> list[str]:
    """data/datasets/policy_scenarios.txt: every built task of every scenario."""
    built = set(os.listdir(os.path.join(path_store.data, "tasks")))
    task_ids = []
    for scenario_id in scenario_ids():
        task_ids += sorted((name for name in built if name.rsplit("_", 1)[0] == scenario_id),
                           key=lambda name: int(name.rsplit("_", 1)[1]))
    with open(os.path.join(path_store.data, "datasets", f"{DATASET_NAME}.txt"), "w") as file:
        file.write("".join(task_id + "\n" for task_id in task_ids))
    return task_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", help="scenario ids, e.g. p3c13f5a (default: all)")
    args = parser.parse_args()
    for scenario_id in args.scenarios or scenario_ids():
        task_ids = load_scenario(scenario_id)().generate_scenario()
        print(f"{scenario_id}: built {', '.join(task_ids)}")
    print(f"data/datasets/{DATASET_NAME}.txt: {len(write_dataset())} tasks")


if __name__ == "__main__":
    main()
