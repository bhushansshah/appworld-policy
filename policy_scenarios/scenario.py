"""What a policy scenario is: one AppWorld task turned into up to 4 task versions that differ in their policies.

A scenario file (policy_scenarios/scenarios/<name>/scenario.py) defines `SCENARIO = Scenario(...)`, next to
its grader (evaluation.py). policy_scenarios/build.py turns it into the tasks <name>_1 ... <name>_4.

Terms (agreed with the user):
- relevant policy: it applies to the task; irrelevant policy: it does not (the task never touches what it is about,
  or its condition is not met in this world, e.g. "don't text me after 8 PM" when it is 3 PM).
- simple policy: the agent can tell what to do from the policy and the task instruction alone; advanced policy: the
  agent must gather information from the apps to handle it (e.g. who the manager is, who asked for more time).
- Versions: 1 no policies; 2 simple relevant + irrelevant; 3 version 2's policies + advanced ones; 4 contradictions
  and ties (may also have advanced policies).
- Contradiction: two rules that cannot both be followed. The designer decides which rule wins and which is
  overridden, by precedence: app policy > (user policy = other people's policies) > task instruction. A tie is
  the user's policy vs another person's; either may win. A rule can be overridden only in part (see `scope`).

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
LEVELS = ("simple", "advanced")  # relevant policies only
INSTRUCTION = "instruction"  # stands for the task instruction in a Conflict
OWNER_RANK = {"app": 3, "user": 2, "person": 2, INSTRUCTION: 1}  # precedence: higher wins
SCENARIO_ANSWER = "<the scenario's answer>"  # a version's default answer: the same as the scenario's


@dataclass(frozen=True)
class Policy:
    key: str  # short id, used in the grader's test names, e.g. "no_manager_requests"
    text: str  # what the agent reads through the policy APIs
    relevance: str  # one of RELEVANCE; never shown to the agent
    level: str | None = None  # one of LEVELS for a relevant policy; None for an irrelevant one


@dataclass(frozen=True)
class Conflict:
    """A contradiction (or tie) in version 4, and how it must be resolved."""

    winners: list[str]  # policy keys that must be followed
    overridden: list[str]  # policy keys, or INSTRUCTION, that give way
    scope: str  # what is given up, in words, e.g. "the text to Sabrina (it still applies to Stephen)"


@dataclass
class Version:
    number: int  # 1: no policies, 2: simple relevant + irrelevant, 3: 2's + advanced, 4: contradictions and ties
    # The correct outcome, given to the grader as private data. Its "checks" are the [POLICY] checks, each with
    # "policy" (the key it tests) and "type" plus its fields (what to check in the data, see the grader).
    expected: dict[str, Any]
    supervisor_policies: list[Policy] = field(default_factory=list)
    people_policies: dict[str, list[Policy]] = field(default_factory=dict)  # by email
    app_policies: dict[str, list[Policy]] = field(default_factory=dict)  # by app name
    instruction: str | None = None  # None: the scenario's instruction
    conflicts: list[Conflict] = field(default_factory=list)
    answer: Any = SCENARIO_ANSWER  # the answer the agent must give in this version (None: no answer)
    # Changes to the world for this version only, made after the scenario's shared world_setup (same rules as
    # Scenario.world_setup). None: the shared world as is.
    world_setup: Callable[[Any], None] | None = None


@dataclass
class Scenario:
    name: str  # lowercase letters and digits only; the task ids are <name>_<version number>
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
                if (policy.level in LEVELS) != (policy.relevance == "relevant"):
                    raise ValueError(f"{where}: policy {policy.key!r}: a relevant policy needs a level "
                                     f"({' or '.join(LEVELS)}); an irrelevant one has none.")
            for check in version.expected.get("checks", []):
                if check.get("policy") not in owners or "type" not in check:
                    raise ValueError(f"{where}: check {check} must name one of the version's policies.")
            for conflict in version.conflicts:
                keys = [*conflict.winners, *conflict.overridden]
                if set(keys) - set(owners) - {INSTRUCTION} or not conflict.winners or not conflict.overridden:
                    raise ValueError(f"{where}: bad conflict {conflict}.")
                rank = {key: OWNER_RANK[owner] for key, owner in {**owners, INSTRUCTION: INSTRUCTION}.items()}
                if min(rank[key] for key in conflict.winners) < max(rank[key] for key in conflict.overridden):
                    raise ValueError(f"{where}: in {conflict}, a winner has lower precedence than an overridden rule.")

    def task_id(self, version: Version) -> str:
        return f"{self.name}_{version.number}"


def owner_type(owner: str) -> str:
    """"user" (the supervisor), "person" (an email) or "app"."""
    return "user" if owner == "supervisor" else "person" if "@" in owner else "app"


def policies_of(version: Version) -> list[tuple[str, Policy]]:
    """(owner, policy) for every policy of a version; owner is "supervisor", an email, or an app name."""
    owned = [("supervisor", policy) for policy in version.supervisor_policies]
    owned += [(email, policy) for email, policies in version.people_policies.items() for policy in policies]
    owned += [(app, policy) for app, policies in version.app_policies.items() for policy in policies]
    return owned
