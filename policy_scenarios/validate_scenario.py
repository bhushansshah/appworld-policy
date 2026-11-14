"""Check a scenario's graders by running solutions in its built tasks (no LLM is used).

For each task: the correct solution must succeed and violate no policy, and each of the scenario's mistakes (the
correct solution with a few lines changed, see Mistake in scenario_generator.py) must get exactly its expected task
success and, separately, its expected violated policies (none = policy compliant). Build the scenario first
(scenario_generator.py).

Usage (from the repo root): .venv/bin/python -m policy_scenarios.validate_scenario [<id> ...]  (default: all)
"""

import argparse
import os
import shutil
import sys

from appworld.common.path_store import path_store
from policy_scenarios.scenario_generator import Mistake, function_body, load_scenario, scenario_ids
from policy_scenarios.task_spec import Solution
from policy_scenarios.validate_task import EXPERIMENT, run_solution


def solution_code(correct_code: str, mistake: Mistake) -> str:
    if mistake.code is not None:
        return mistake.code
    for old, new in mistake.replacements:
        if correct_code.count(old) != 1:
            raise ValueError(f"{mistake.name}: {old!r} must occur exactly once in the correct solution.")
        correct_code = correct_code.replace(old, new)
    return correct_code


def outcome(task_success: bool, violated: list[str]) -> str:
    """E.g. "task success: yes, policy compliance: no (violated: expense_log)"."""
    compliance = f"no (violated: {', '.join(violated)})" if violated else "yes"
    return f"task success: {'yes' if task_success else 'no'}, policy compliance: {compliance}"


def validate_scenario(scenario_id: str) -> bool:
    generator = load_scenario(scenario_id)
    all_ok = True
    for task in generator.tasks:
        task_id = f"{scenario_id}_{task.number}"
        correct_code = function_body(task.solution)
        cases = [Mistake(task.number, "correct solution", [])]
        cases += [mistake for mistake in generator.mistakes if mistake.task_number == task.number]
        for case in cases:
            report = run_solution(task_id, "", Solution(case.name, solution_code(correct_code, case), ""))
            # task success and policy compliance are checked separately: compliance must find exactly the expected
            # violated policies (none = compliant), whatever happened to the task.
            task_ok = report["task_success"] == case.task_success
            policies_ok = set(report["violated_policies"]) == set(case.violated)
            ok = task_ok and policies_ok
            all_ok &= ok
            print(f"{'OK  ' if ok else 'FAIL'} {task_id} {case.name}: "
                  f"{outcome(report['task_success'], report['violated_policies'])}")
            if not ok:
                print(f"     expected: {outcome(case.task_success, case.violated)}")
                for failure in report["task_failures"]:
                    print(f"     failed [TASK]: {failure}")
                for policy in report["policies"]:
                    for check in policy["failed_checks"]:
                        print(f"     failed [POLICY:{policy['key']}]: {check}")
    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", help="scenario ids, e.g. p3c13f5a (default: all)")
    args = parser.parse_args()
    try:
        results = [validate_scenario(scenario_id) for scenario_id in args.scenarios or scenario_ids()]
    finally:
        shutil.rmtree(os.path.join(path_store.experiment_outputs, EXPERIMENT), ignore_errors=True)
    print("ALL SOLUTIONS GRADED AS EXPECTED" if all(results) else "SOME SOLUTIONS WERE NOT GRADED AS EXPECTED")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
