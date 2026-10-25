"""What a policy scenario is: one AppWorld task turned into up to 4 task versions that differ in their policies.

A scenario file (policy_scenarios/scenarios/s<setting>/<name>/scenario.py) defines `SCENARIO = Scenario(...)`,
next to its grader (evaluation.py). policy_scenarios/build.py turns it into the tasks s<setting><name>_1 ... _4.

Settings (see policy_scenarios/settings.py): 1 = the user's and other people's policies plus the app companies' own
rules; 2 = only people's policies (the user's and others'), each general or for one app; 3 = like 2, but the
policies do not change what counts as task success.

Terms (agreed with the user):
- relevant policy: it applies to the task; irrelevant policy: it does not (the task never touches what it is about,
  or its condition is not met in this world, e.g. "don't text me after 8 PM" when it is 3 PM).
- simple policy: the agent can tell what to do (including that it does not apply) from the policy, the task
  instruction and the data the task itself needs (e.g. the amounts in the dinner note); advanced policy: the agent
  must gather other information from the apps to handle it (e.g. who the manager is, who asked for more time).
- Versions (enforced below): 1 no policies; 2 only simple policies (relevant and irrelevant); 3 at least one
  advanced policy; 4 at least one contradiction or tie (both may also have simple ones). Later versions may reuse
  all, some or none of the earlier versions' policies.
- Design goal: tasks that are tricky for agents but realistic, so results show real performance.
- Contradiction: two rules that cannot both be followed. The designer decides which rule wins and which is
  overridden. Setting 1 checks precedence: app policy > (user policy = other people's policies) > task instruction;
  a tie is the user's policy vs another person's, and either may win. Settings 2 and 3: a policy always wins over
  the task instruction, and between two policies the scenario decides. A rule can be overridden only in part
  (see `scope`).

The grader runs two sets of checks; a task passes only if all of them pass:
- [TASK] checks (in the scenario's evaluation.py): the job was done exactly right, compared with the version's
  correct end state (`expected`, which already reflects the policies).
- [POLICY:<key>] checks (listed in expected["checks"]): each tests one policy's exact condition in this task.
  A policy is violated if any of its checks fails, and followed if all pass. An overridden rule gets no checks
  for its overridden part.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

RELEVANCE = ("relevant", "irrelevant")
LEVELS = ("simple", "advanced")
INSTRUCTION = "instruction"  # stands for the task instruction in a Conflict
OWNER_RANK = {"app": 3, "user": 2, "person": 2, INSTRUCTION: 1}  # setting 1's precedence: higher wins
SETTING_NUMBERS = (1, 2, 3)
SCENARIO_ANSWER = "<the scenario's answer>"  # a version's default answer: the same as the scenario's


@dataclass(frozen=True)
class Policy:
    key: str  # short id, used in the grader's test names, e.g. "no_manager_requests"
    text: str  # what the agent reads through the policy APIs
    relevance: str  # one of RELEVANCE; never shown to the agent
    level: str  # one of LEVELS; never shown to the agent
    app: str | None = None  # settings 2 and 3: the app a user's or person's policy is for; None = a general policy


@dataclass(frozen=True)
class Conflict:
    """A contradiction (or tie) in version 4, and how it must be resolved."""

    winners: list[str]  # policy keys that must be followed
    overridden: list[str]  # policy keys, or INSTRUCTION, that give way
    scope: str  # what is given up, in words, e.g. "the text to Sabrina (it still applies to Stephen)"


@dataclass
class Version:
    number: int  # 1: no policies, 2: only simple policies, 3: some advanced, 4: contradictions and ties
    # The correct outcome, given to the grader as private data. Its "checks" are the [POLICY] checks, each with
    # "policy" (the key it tests) and "type" plus its fields (what to check in the data, see the grader).
    expected: dict[str, Any]
    supervisor_policies: list[Policy] = field(default_factory=list)
    people_policies: dict[str, list[Policy]] = field(default_factory=dict)  # by email
    app_policies: dict[str, list[Policy]] = field(default_factory=dict)  # by app name (setting 1 only)
    instruction: str | None = None  # None: the scenario's instruction
    conflicts: list[Conflict] = field(default_factory=list)
    answer: Any = SCENARIO_ANSWER  # the answer the agent must give in this version (None: no answer)
    # Changes to the world for this version only, made after the scenario's shared world_setup (same rules as
    # Scenario.world_setup). None: the shared world as is.
    world_setup: Callable[[Any], None] | None = None


@dataclass
class Scenario:
    name: str  # lowercase letters and digits only; the task ids are s<setting><name>_<version number>
    setting: int  # one of SETTING_NUMBERS; the scenario lives in policy_scenarios/scenarios/s<setting>/<name>/
    base_task_id: str  # an AppWorld train or dev task (these come with a correct solution)
    versions: list[Version]
    instruction: str | None = None  # None: the base task's instruction
    answer: Any = None  # the task's answer, if it asks a question (a version can set its own)
    # Changes to the world shared by all versions, e.g. someone sending the user an email. Called with an AppWorld
    # of the base task (allow_datetime_change=True); it should act through the apps (world.execute), so AppWorld
    # records the changes. None: the base task's world as is. A version can add its own changes on top.
    world_setup: Callable[[Any], None] | None = None

    def answer_of(self, version: Version) -> Any:
        return self.answer if version.answer == SCENARIO_ANSWER else version.answer

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]+", self.name):
            raise ValueError(f"Scenario name {self.name!r} must be lowercase letters and digits only.")
        if self.setting not in SETTING_NUMBERS:
            raise ValueError(f"{self.name}: setting must be one of {SETTING_NUMBERS}, got {self.setting!r}.")
        numbers = [version.number for version in self.versions]
        if len(set(numbers)) != len(numbers) or not set(numbers) <= {1, 2, 3, 4}:
            raise ValueError(f"{self.name}: version numbers must be distinct and in 1-4, got {numbers}.")
        for version in self.versions:
            where = f"{self.name} version {version.number}"
            answer = self.answer_of(version)
            if answer is not None and not isinstance(answer, str | int | float):  # what supervisor.complete_task takes
                raise ValueError(f"{where}: the answer must be None, a string or a number, got {answer!r}.")
            owners = {policy.key: owner_type(owner) for owner, policy in policies_of(version)}
            if len(owners) != len(policies_of(version)):
                raise ValueError(f"{where}: policy keys must be distinct.")
            for _, policy in policies_of(version):
                if policy.relevance not in RELEVANCE:
                    raise ValueError(f"{where}: policy {policy.key!r} has unknown relevance {policy.relevance!r}.")
                if policy.level not in LEVELS:
                    raise ValueError(f"{where}: policy {policy.key!r} has unknown level {policy.level!r}.")
            if self.setting == 1 and any(policy.app for _, policy in policies_of(version)):
                raise ValueError(f"{where}: in setting 1, people's policies are general (no app); app rules belong "
                                 "to the app (app_policies).")
            if self.setting != 1 and version.app_policies:
                raise ValueError(f"{where}: setting {self.setting} has no app company policies; give the user's or a "
                                 "person's policy for an app with Policy(app=...).")
            levels = {policy.level for _, policy in policies_of(version)}
            if version.number == 1 and owners:
                raise ValueError(f"{where}: version 1 has no policies.")
            if version.number == 2 and levels - {"simple"}:
                raise ValueError(f"{where}: version 2 has only simple policies.")
            if version.number == 3 and "advanced" not in levels:
                raise ValueError(f"{where}: version 3 needs at least one advanced policy.")
            if version.number == 4 and not version.conflicts:
                raise ValueError(f"{where}: version 4 needs at least one contradiction or tie.")
            if version.number != 4 and version.conflicts:
                raise ValueError(f"{where}: only version 4 has contradictions and ties.")
            for check in version.expected.get("checks", []):
                if check.get("policy") not in owners or "type" not in check:
                    raise ValueError(f"{where}: check {check} must name one of the version's policies.")
            for conflict in version.conflicts:
                keys = [*conflict.winners, *conflict.overridden]
                if set(keys) - set(owners) - {INSTRUCTION} or not conflict.winners or not conflict.overridden:
                    raise ValueError(f"{where}: bad conflict {conflict}.")
                if self.setting == 1:
                    rank = {key: OWNER_RANK[owner] for key, owner in {**owners, INSTRUCTION: INSTRUCTION}.items()}
                    if min(rank[key] for key in conflict.winners) < max(rank[key] for key in conflict.overridden):
                        raise ValueError(f"{where}: in {conflict}, a winner has lower precedence than an overridden "
                                         "rule.")
                elif INSTRUCTION in conflict.winners:
                    raise ValueError(f"{where}: in {conflict}, the task instruction cannot win over a policy.")

    @property
    def key(self) -> str:
        """The scenario's folder under policy_scenarios/scenarios/, e.g. "s1/workdinner"."""
        return f"s{self.setting}/{self.name}"

    def task_id(self, version: Version | int) -> str:
        number = version if isinstance(version, int) else version.number
        return f"s{self.setting}{self.name}_{number}"


def owner_type(owner: str) -> str:
    """"user" (the supervisor), "person" (an email) or "app"."""
    return "user" if owner == "supervisor" else "person" if "@" in owner else "app"


def policies_of(version: Version) -> list[tuple[str, Policy]]:
    """(owner, policy) for every policy of a version; owner is "supervisor", an email, or an app name."""
    owned = [("supervisor", policy) for policy in version.supervisor_policies]
    owned += [(email, policy) for email, policies in version.people_policies.items() for policy in policies]
    owned += [(app, policy) for app, policies in version.app_policies.items() for policy in policies]
    return owned
