"""What a policy task is: one AppWorld task with its own policies and, if needed, its own instruction and world changes.

A task is defined in policy_scenarios/tasks/s<setting>/<name>/ (name: lowercase letters and digits only):
- task.py: `TASK = Task(...)`, what the task is (below);
- evaluation.py: the grader, with [TASK] checks (the job) and [POLICY:<key>] checks (one policy each);
- solution.py: hand-written solutions and the verdict the grader must give each one (see validate_task.py).
policy_scenarios/build_task.py turns it into the AppWorld task data/tasks/s<setting><name>_1.

Settings (see policy_scenarios/settings.py): 1 = the user's and other people's policies plus the app companies' own
rules; 2 = only people's policies (the user's and others'), each for one app; 3 = like 2, but people can also have
general policies (not tied to any app), and the policies do not change what counts as task success (they only choose
among the task's correct end states, so a policy never conflicts with the task instruction).

Terms (agreed with the user):
- relevant policy: it applies to the task; irrelevant policy: it does not (the task never touches what it is about,
  or its condition is not met in this world, e.g. "don't text me after 8 PM" when it is 3 PM).
- simple policy: the agent can tell what to do (including that it does not apply) from the policy, the task
  instruction and the data the task itself needs (e.g. the amounts in the dinner note); advanced policy: the agent
  must gather other information from the apps to handle it (e.g. who the manager is, who asked for more time).
- Design goal: tasks that are tricky for agents but realistic, so results show real performance.
- Contradiction: two rules that cannot both be followed. The designer decides which rule wins and which is
  overridden. Setting 1's precedence: app policy > (user policy = other people's policies) > task instruction; a tie
  is the user's policy vs another person's, and either may win. Settings 2 and 3: a policy always wins over the task
  instruction, and between two policies the task decides. A rule can be overridden only in part (see `scope`).

The grader runs two sets of checks:
- [TASK] checks (in the task's evaluation.py, or the base task's own grader): the job was done exactly right.
- [POLICY:<key>] checks (listed in expected["checks"]): each tests one policy's exact condition in this task.
  A policy is violated if any of its checks fails, and followed if all pass. An overridden rule gets no checks
  for its overridden part.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

RELEVANCE = ("relevant", "irrelevant")
LEVELS = ("simple", "advanced")
INSTRUCTION = "instruction"  # stands for the task instruction in a Conflict
SETTING_NUMBERS = (1, 2, 3)


@dataclass(frozen=True)
class Policy:
    key: str  # short id, used in the grader's test names, e.g. "no_manager_requests"
    text: str  # what the agent reads through the policy APIs
    relevance: str  # one of RELEVANCE; never shown to the agent
    level: str  # one of LEVELS; never shown to the agent
    app: str | None = None  # settings 2 and 3: the app a user's or person's policy is for; None = a general policy


@dataclass(frozen=True)
class Conflict:
    """A contradiction (or tie) between rules, and how it must be resolved."""

    winners: list[str]  # policy keys that must be followed
    overridden: list[str]  # policy keys, or INSTRUCTION, that give way
    scope: str  # what is given up, in words, e.g. "the text to Sabrina (it still applies to Stephen)"


@dataclass(frozen=True)
class Solution:
    name: str
    code: str  # run after the task's PRELUDE; must end with apis.supervisor.complete_task()
    verdict: str  # "success", "policy violation" or "job mistake" (setting 3: "compliant", "not compliant", "task failed")
    violated: list[str] = field(default_factory=list)  # the policy keys the grader must find violated


@dataclass
class Task:
    base_task_id: str  # an AppWorld task (any split) whose world this task starts from
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
    # True: the task is the base task unchanged plus policies. Task success is the base task's own grader, run as it
    # is with each of its checks labeled [TASK], and its public data, private data and answer are kept; evaluation.py
    # adds only the [POLICY] checks. No instruction, world setup or answer may be given.
    base_grader: bool = False


def owner_type(owner: str) -> str:
    """"user" (the supervisor), "person" (an email) or "app"."""
    return "user" if owner == "supervisor" else "person" if "@" in owner else "app"


def policies_of(task: Task) -> list[tuple[str, Policy]]:
    """(owner, policy) for every policy of a task; owner is "supervisor", an email, or an app name."""
    owned = [("supervisor", policy) for policy in task.supervisor_policies]
    owned += [(email, policy) for email, policies in task.people_policies.items() for policy in policies]
    owned += [(app, policy) for app, policies in task.app_policies.items() for policy in policies]
    return owned


def check_task(task: Task, setting: int, task_id: str) -> None:
    """Raise a ValueError if the task does not fit its setting's rules."""
    if setting not in SETTING_NUMBERS:
        raise ValueError(f"{task_id}: setting must be one of {SETTING_NUMBERS}, got {setting!r}.")
    if task.base_grader and (task.instruction or task.world_setup or task.answer is not None):
        raise ValueError(f"{task_id}: with base_grader, the base task is kept as it is (no instruction, world setup "
                         "or answer).")
    if task.answer is not None and not isinstance(task.answer, str | int | float):  # what complete_task takes
        raise ValueError(f"{task_id}: the answer must be None, a string or a number, got {task.answer!r}.")
    owned = policies_of(task)
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
