"""What a policy scenario is: one AppWorld task turned into up to 4 task versions that differ in their policies.

A scenario file (policy_scenarios/scenarios/<name>/scenario.py) defines `SCENARIO = Scenario(...)`, next to
its grader (evaluation.py). policy_scenarios/build.py turns it into the tasks <name>_1 ... <name>_4.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Hidden label of each policy, for analysis: does it matter for this version, and how?
POLICY_ROLES = ("relevant", "irrelevant", "decoy", "conflict")


@dataclass(frozen=True)
class Policy:
    key: str  # short id, used in the grader's test names, e.g. "no_manager_requests"
    text: str  # what the agent reads through the policy APIs
    role: str  # one of POLICY_ROLES; never shown to the agent


@dataclass
class Version:
    number: int  # 1: no policies, 2: relevant + irrelevant, 3: look-alike decoys, 4: contradictions
    expected: dict[str, Any]  # the correct outcome; given to the grader as private data
    supervisor_policies: list[Policy] = field(default_factory=list)
    people_policies: dict[str, list[Policy]] = field(default_factory=dict)  # by email
    app_policies: dict[str, list[Policy]] = field(default_factory=dict)  # by app name
    instruction: str | None = None  # None: the scenario's instruction


@dataclass
class Scenario:
    name: str  # lowercase letters and digits only; the task ids are <name>_<version number>
    base_task_id: str  # an AppWorld train or dev task (these come with a correct solution)
    versions: list[Version]
    instruction: str | None = None  # None: the base task's instruction
    answer: Any = None  # the task's answer, if it asks a question
    # Changes to the world shared by all versions, e.g. someone sending the user an email. Called with an AppWorld
    # of the base task (allow_datetime_change=True); it should act through the apps (world.execute), so AppWorld
    # records the changes. None: the base task's world as is.
    world_setup: Callable[[Any], None] | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]+", self.name):
            raise ValueError(f"Scenario name {self.name!r} must be lowercase letters and digits only.")
        numbers = [version.number for version in self.versions]
        if len(set(numbers)) != len(numbers) or not set(numbers) <= {1, 2, 3, 4}:
            raise ValueError(f"{self.name}: version numbers must be distinct and in 1-4, got {numbers}.")
        for version in self.versions:
            keys = [policy.key for _, policy in policies_of(version)]
            if len(set(keys)) != len(keys):
                raise ValueError(f"{self.name} version {version.number}: policy keys must be distinct.")
            for _, policy in policies_of(version):
                if policy.role not in POLICY_ROLES:
                    raise ValueError(f"{self.name}: policy {policy.key!r} has unknown role {policy.role!r}.")

    def task_id(self, version: Version) -> str:
        return f"{self.name}_{version.number}"


def policies_of(version: Version) -> list[tuple[str, Policy]]:
    """(owner, policy) for every policy of a version; owner is "supervisor", an email, or an app name."""
    owned = [("supervisor", policy) for policy in version.supervisor_policies]
    owned += [(email, policy) for email, policies in version.people_policies.items() for policy in policies]
    owned += [(app, policy) for app, policies in version.app_policies.items() for policy in policies]
    return owned
