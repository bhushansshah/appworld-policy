"""Per-policy report of an experiment's runs on policy scenario tasks.

For each scenario task the experiment ran, this grades the run with AppWorld (as `appworld evaluate` does) and turns
the grader's labelled checks ([TASK], [FOLLOW:<keys>], [OVER:<keys>], [DORMANT:<keys>]) into one entry per policy:
- relevant policies (role "relevant" or "conflict"):
    followed      - its FOLLOW checks passed (None: it has no FOLLOW check),
    over_applied  - one of its OVER checks failed, i.e. it stopped something outside its scope (None: no OVER check
                    could be set up for it in this task's data);
- non-relevant policies (role "irrelevant" or "decoy"):
    followed          - its own condition still holds (its FOLLOW checks passed), e.g. no text to family after 9 PM,
    correctly_ignored - it did not stop or change what it does not cover (its DORMANT checks passed; None: there is
                        nothing in this task it could wrongly stop).
When a failed check names several policies, or several failed checks test the same thing, each policy's notes say
which other policies could also explain it. Also reported: whether the task passed, the job ([TASK]) mistakes, and
whether version 4's conflicts were resolved (all FOLLOW checks of the conflict's policies passed).

Writes tasks/<task_id>/evaluation/policy_report.json in the experiment's output folder, and policy_report.json and
policy_report.md (all tasks) in the experiment's output folder.

Usage (from the repo root): .venv/bin/python -m policy_scenarios.report <experiment_name> [task_id ...]
"""

import json
import os
import re
import sys
from collections import defaultdict
from typing import Any

from appworld.common.path_store import path_store
from appworld.evaluator import evaluate_task

LABEL = re.compile(r"^\[(TASK|FOLLOW|OVER|DORMANT)(?::([^\]]+))?\]\s*(.*)$", re.S)
RELEVANT_ROLES = ("relevant", "conflict")


def is_scenario_task(task_id: str) -> bool:
    path = os.path.join(path_store.data, "tasks", task_id, "ground_truth", "private_data.json")
    if not os.path.exists(path):
        return False
    with open(path) as file:
        return "scenario" in json.load(file)


def owner_type(owner: str) -> str:
    return "user" if owner == "supervisor" else "person" if "@" in owner else "app"


def task_report(task_id: str, experiment_name: str) -> dict[str, Any]:
    with open(os.path.join(path_store.data, "tasks", task_id, "ground_truth", "private_data.json")) as file:
        private_data = json.load(file)
    tracker = evaluate_task(task_id=task_id, experiment_name=experiment_name, save_report=False)
    checks = [(True, item["requirement"]) for item in tracker.passes]
    checks += [(False, item["requirement"]) for item in tracker.failures]

    job_mistakes: list[str] = []
    results: dict[tuple[str, str], list[bool]] = defaultdict(list)  # (kind, policy key) -> passed?
    notes: dict[str, list[str]] = defaultdict(list)
    failed_by_text: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)  # what failed -> (kind, keys)
    for passed, requirement in checks:
        match = LABEL.match(requirement.strip())
        if match is None:
            raise ValueError(f"{task_id}: unlabelled check: {requirement!r}")
        kind, keys_text, text = match.groups()
        if kind == "TASK":
            if not passed:
                job_mistakes.append(text.strip())
            continue
        keys = keys_text.split("+")
        for key in keys:
            results[(kind, key)].append(passed)
            if not passed:
                notes[key].append(f"{kind} check failed: {text.strip()}")
        if not passed:
            failed_by_text[text.strip()].append((kind, keys))
    for failures in failed_by_text.values():  # the same failed check can blame several policies
        blamed = sorted({key for _, keys in failures for key in keys})
        for key in blamed:
            if len(blamed) > 1:
                notes[key].append(f"could also be explained by: {', '.join(k for k in blamed if k != key)}")

    def all_passed(kind: str, key: str) -> bool | None:
        return all(results[(kind, key)]) if results[(kind, key)] else None

    policies = []
    for policy in private_data["policies"]:
        key, entry = policy["key"], dict(policy, owner_type=owner_type(policy["owner"]))
        if policy["role"] in RELEVANT_ROLES:
            over_ok = all_passed("OVER", key)
            entry |= {"followed": all_passed("FOLLOW", key), "over_applied": None if over_ok is None else not over_ok}
            if entry["followed"] is None and policy["role"] == "conflict":
                notes[key].append("loses its conflict, so it should be overridden (see the conflicts below)")
        else:
            entry |= {"followed": all_passed("FOLLOW", key), "correctly_ignored": all_passed("DORMANT", key)}
        entry["notes"] = notes[key]
        policies.append(entry)
    conflicts = [
        conflict | {"resolved": all(all_passed("FOLLOW", key) is True for key in conflict["policies"])}
        for conflict in private_data.get("conflicts", [])
    ]
    return {
        "task_id": task_id,
        "scenario": private_data["scenario"],
        "version": private_data["version"],
        "passed": tracker.success,
        "job_mistakes": job_mistakes,
        "policies": policies,
        "conflicts": conflicts,
    }


def show(value: bool | None, yes: str, no: str) -> str:
    return "—" if value is None else yes if value else no


def to_markdown(experiment_name: str, reports: list[dict[str, Any]]) -> str:
    lines = [f"# Policy report: {experiment_name}", ""]
    for report in reports:
        lines += [
            f"## {report['task_id']} (scenario {report['scenario']}, version {report['version']}): "
            f"{'PASS' if report['passed'] else 'FAIL'}",
            "",
            "Failed job ([TASK]) checks: " + ("; ".join(report["job_mistakes"]) or "none")
            + (" (some may be caused by the policy results below)" if report["job_mistakes"] and report["policies"] else ""),
            "",
        ]
        if report["policies"]:
            lines += ["| Policy | Owner | Role | Followed | Over-applied | Correctly ignored | Notes |",
                      "|---|---|---|---|---|---|---|"]
            for p in report["policies"]:
                relevant = p["role"] in RELEVANT_ROLES
                lines.append(
                    f"| {p['key']} | {p['owner_type']} | {p['role']} "
                    f"| {show(p.get('followed'), 'yes', '**NO (broken)**')} "
                    f"| {show(p.get('over_applied'), '**YES**', 'no') if relevant else ''} "
                    f"| {'' if relevant else show(p['correctly_ignored'], 'yes', '**NO (applied)**')} "
                    f"| {'; '.join(p['notes'])} |"
                )
            lines.append("")
        for conflict in report["conflicts"]:
            lines.append(f"- Conflict ({conflict['type']}): {', '.join(conflict['policies'])}: "
                         f"{'resolved correctly' if conflict['resolved'] else '**not resolved correctly**'}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    experiment_name, task_ids = sys.argv[1], sys.argv[2:]
    tasks_directory = os.path.join(path_store.experiment_outputs, experiment_name, "tasks")
    if not task_ids:  # every scenario task the experiment ran
        task_ids = sorted(task_id for task_id in os.listdir(tasks_directory) if is_scenario_task(task_id))
    reports = [task_report(task_id, experiment_name) for task_id in task_ids]
    for report in reports:
        with open(os.path.join(tasks_directory, report["task_id"], "evaluation", "policy_report.json"), "w") as file:
            json.dump(report, file, indent=2)
    output_directory = os.path.join(path_store.experiment_outputs, experiment_name)
    with open(os.path.join(output_directory, "policy_report.json"), "w") as file:
        json.dump(reports, file, indent=2)
    markdown = to_markdown(experiment_name, reports)
    with open(os.path.join(output_directory, "policy_report.md"), "w") as file:
        file.write(markdown)
    print(markdown)


if __name__ == "__main__":
    main()
