"""Check each scenario's grader against hand-written solutions (no LLM is used).

A scenario folder can have solutions.py next to scenario.py, with:
- PRELUDE: code run first in the task's world (e.g. log in and define helper functions);
- SOLUTIONS: {version number: [Solution(name, code, verdict, violated)]}: code that does the task in some way (good or
  with a deliberate mistake) and the result the grader must give it: the verdict ("success", "policy violation" or
  "job mistake") and the exact set of violated policies.
Every version is also run with a "do nothing" solution (just complete_task), which must be a job mistake.

Each solution runs in a fresh world of the built task (build the scenarios first), is graded with the task's grader,
and is reported as OK when the verdict and the violated policies are exactly the ones expected.

Usage (from the repo root): .venv/bin/python -m policy_scenarios.validate [scenario_name ...]
"""

import argparse
import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass, field

from appworld.common.path_store import path_store

from policy_scenarios.build import SCENARIOS_DIRECTORY, load_scenario, scenario_names
from policy_scenarios.report import task_report

EXPERIMENT = "policy_scenarios_validate"


@dataclass(frozen=True)
class Solution:
    name: str
    code: str  # run after the scenario's PRELUDE; must end with apis.supervisor.complete_task()
    verdict: str  # "success", "policy violation" or "job mistake"
    violated: list[str] = field(default_factory=list)  # the policy keys the grader must find violated


DO_NOTHING = Solution("do nothing", "apis.supervisor.complete_task()", "job mistake")


def load_solutions(name: str) -> tuple[str, dict[int, list[Solution]]]:
    path = SCENARIOS_DIRECTORY / name / "solutions.py"
    if not path.exists():
        return "", {}
    spec = importlib.util.spec_from_file_location(f"policy_solutions_{name}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.PRELUDE, module.SOLUTIONS


def run_solution(task_id: str, prelude: str, solution: Solution) -> dict:
    from appworld import AppWorld

    shutil.rmtree(os.path.join(path_store.experiment_outputs, EXPERIMENT, "tasks", task_id), ignore_errors=True)
    with AppWorld(task_id=task_id, experiment_name=EXPERIMENT) as world:
        for code in (prelude, solution.code):
            output = world.execute(code) if code else ""
            if "Execution failed" in output:
                raise RuntimeError(f"{task_id} / {solution.name}: the solution's code failed:\n{output}")
    return task_report(task_id, EXPERIMENT)


def validate_scenario(name: str) -> bool:
    scenario = load_scenario(name)
    prelude, solutions = load_solutions(name)
    all_ok = True
    for version in scenario.versions:
        task_id = scenario.task_id(version)
        for solution in [DO_NOTHING, *solutions.get(version.number, [])]:
            report = run_solution(task_id, prelude, solution)
            ok = report["verdict"] == solution.verdict and set(report["violated_policies"]) == set(solution.violated)
            all_ok &= ok
            print(f"{'OK  ' if ok else 'FAIL'} {task_id} {solution.name}: {report['verdict']}"
                  + (f" (violated: {', '.join(report['violated_policies'])})" if report["violated_policies"] else ""))
            if not ok:
                print(f"     expected: {solution.verdict}"
                      + (f" (violated: {', '.join(solution.violated)})" if solution.violated else ""))
                for failure in report["task_failures"]:
                    print(f"     failed [TASK]: {failure}")
                for policy in report["policies"]:
                    for check in policy["failed_checks"]:
                        print(f"     failed [POLICY:{policy['key']}]: {check}")
    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", help="scenario names (default: all)")
    args = parser.parse_args()
    try:
        results = [validate_scenario(name) for name in args.scenarios or scenario_names()]
    finally:
        shutil.rmtree(os.path.join(path_store.experiment_outputs, EXPERIMENT), ignore_errors=True)
    print("ALL SOLUTIONS GRADED AS EXPECTED" if all(results) else "SOME SOLUTIONS WERE NOT GRADED AS EXPECTED")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
