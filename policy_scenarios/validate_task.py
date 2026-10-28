"""Check a single task's grader against hand-written solutions (no LLM is used).

A task folder (policy_scenarios/tasks/s<setting>/<name>/) has solution.py next to task.py, with:
- PRELUDE: code run first in the task's world (e.g. log in and define helper functions);
- SOLUTIONS: [Solution(name, code, verdict, violated)]: code that does the task in some way (good or with a
  deliberate mistake) and the result the grader must give it, as in scenarios (see policy_scenarios/validate.py).
The task is also run with a "do nothing" solution (just complete_task), which must be a job mistake (setting 3:
task failed).

Each solution runs in a fresh world of the built task (build it first with build_task.py), is graded with the
task's grader, and is reported as OK when the verdict and the violated policies are exactly the ones expected.

Usage (from the repo root): .venv/bin/python -m policy_scenarios.validate_task [s<setting>/<name> ...]  (default: all)
e.g. .venv/bin/python -m policy_scenarios.validate_task s3/giftbottlev1
"""

import argparse
import importlib.util
import os
import shutil
import sys

from appworld.common.path_store import path_store

from policy_scenarios.build_task import TASKS_DIRECTORY, split_key, task_id_of, task_keys
from policy_scenarios.validate import EXPERIMENT, Solution, do_nothing, run_solution


def load_solutions(key: str) -> tuple[str, list[Solution]]:
    path = TASKS_DIRECTORY / key / "solution.py"
    if not path.exists():
        return "", []
    spec = importlib.util.spec_from_file_location(f"policy_task_solution_{key.replace('/', '_')}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.PRELUDE, module.SOLUTIONS


def validate_task(key: str) -> bool:
    setting, _ = split_key(key)
    task_id = task_id_of(key)
    prelude, solutions = load_solutions(key)
    all_ok = True
    for solution in [do_nothing(setting), *solutions]:
        # Run the solution in a fresh world of the task, then grade it (see policy_scenarios/report.py).
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
    parser.add_argument("tasks", nargs="*", help="tasks as s<setting>/<name>, e.g. s3/giftbottlev1 (default: all)")
    args = parser.parse_args()
    try:
        results = [validate_task(key) for key in args.tasks or task_keys()]
    finally:
        shutil.rmtree(os.path.join(path_store.experiment_outputs, EXPERIMENT), ignore_errors=True)
    print("ALL SOLUTIONS GRADED AS EXPECTED" if all(results) else "SOME SOLUTIONS WERE NOT GRADED AS EXPECTED")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
