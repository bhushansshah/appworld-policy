"""What a single policy task is: one AppWorld task with its own instruction, world changes and policies.

Unlike a scenario (policy_scenarios/scenario.py: one world, up to 4 versions), a single task is defined on its own,
in policy_scenarios/tasks/s<setting>/<name>/ (name: lowercase letters and digits only):
- task.py: `TASK = Task(...)`, what the task is (below);
- evaluation.py: the grader, with [TASK] checks (the job) and [POLICY:<key>] checks (one policy each);
- solution.py: hand-written solutions and the verdict the grader must give each one (see validate_task.py).
policy_scenarios/build_task.py turns it into the AppWorld task data/tasks/s<setting><name>_1.

Policies, conflicts, relevance and levels mean the same as in scenarios (see policy_scenarios/scenario.py).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from policy_scenarios.scenario import INSTRUCTION, LEVELS, RELEVANCE, SETTING_NUMBERS, Conflict, Policy, policies_of


@dataclass
class Task:
    base_task_id: str  # an AppWorld train or dev task whose world this task starts from
    # The correct outcome, given to the grader as private data. Its "checks" are the [POLICY] checks, each with
    # "policy" (the key it tests) and "type" plus its fields (what to check in the data, see the grader).
    expected: dict[str, Any]
    instruction: str | None = None  # None: the base task's instruction
    answer: Any = None  # the answer the agent must give (None: no answer)
    # Changes to the world, made before the policies are loaded. Called with an AppWorld of the base task
    # (allow_datetime_change=True); it should act through the apps or their models, so AppWorld records the changes.
    world_setup: Callable[[Any], None] | None = None
    supervisor_policies: list[Policy] = field(default_factory=list)  # the user's
    people_policies: dict[str, list[Policy]] = field(default_factory=dict)  # other people's, by email
    app_policies: dict[str, list[Policy]] = field(default_factory=dict)  # the app companies' (setting 1 only)
    conflicts: list[Conflict] = field(default_factory=list)


def check_task(task: Task, setting: int, task_id: str) -> None:
    """Raise a ValueError if the task does not fit its setting's rules."""
    if setting not in SETTING_NUMBERS:
        raise ValueError(f"{task_id}: setting must be one of {SETTING_NUMBERS}, got {setting!r}.")
    if task.answer is not None and not isinstance(task.answer, str | int | float):  # what complete_task takes
        raise ValueError(f"{task_id}: the answer must be None, a string or a number, got {task.answer!r}.")
    owned = policies_of(task)  # type: ignore[arg-type]  # a Task has the same policy fields as a Version
    keys = {policy.key for _, policy in owned}
    if len(keys) != len(owned):
        raise ValueError(f"{task_id}: policy keys must be distinct.")
    for _, policy in owned:
        if policy.relevance not in RELEVANCE or policy.level not in LEVELS:
            raise ValueError(f"{task_id}: policy {policy.key!r} has unknown relevance or level.")
    if setting == 1 and any(policy.app for _, policy in owned):
        raise ValueError(f"{task_id}: in setting 1, people's policies are general (no app).")
    if setting != 1 and task.app_policies:
        raise ValueError(f"{task_id}: only setting 1 has app company policies (app_policies).")
    if setting == 2 and any(not policy.app for _, policy in owned):
        raise ValueError(f"{task_id}: in setting 2, every policy belongs to one app (Policy(app=...)).")
    for check in task.expected.get("checks", []):
        if check.get("policy") not in keys or "type" not in check:
            raise ValueError(f"{task_id}: check {check} must name one of the task's policies and have a type.")
    for conflict in task.conflicts:
        if set(conflict.winners + conflict.overridden) - keys - {INSTRUCTION}:
            raise ValueError(f"{task_id}: conflict {conflict} names an unknown policy.")
        if setting == 3 and INSTRUCTION in conflict.winners + conflict.overridden:
            raise ValueError(f"{task_id}: setting 3's policies never conflict with the task instruction.")
