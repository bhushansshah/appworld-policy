"""Run a critic's probe solutions against one scenario's grader and print how each is graded (no LLM is used).

A probe file is Python that defines PROBES = [(version number, name, code, expected verdict as free text), ...]. It runs
with every name of the scenario's solutions.py already defined (PRELUDE, helpers like requests/texts/only, emails,
DONE), so probes can reuse them. Each probe runs in a fresh world of the built task s<setting><name>_<version>, after
the scenario's PRELUDE, exactly as policy_scenarios/validate.py runs a solution. Nothing in the repo is changed; the
run outputs go to experiments/outputs/policy_scenarios_critic, which is deleted at the end.

Usage (from the repo root):
    .venv/bin/python .claude/skills/critic-evaluator/probe.py s2/workdinner <probes file>
"""

import importlib.util
import os
import shutil
import sys

sys.path.insert(0, os.getcwd())

import policy_scenarios.validate as validate  # noqa: E402
from appworld.common.path_store import path_store  # noqa: E402
from policy_scenarios.build import SCENARIOS_DIRECTORY, load_scenario  # noqa: E402

validate.EXPERIMENT = "policy_scenarios_critic"  # keep away from validate.py's own outputs


def main() -> None:
    key, probes_path = sys.argv[1], sys.argv[2]
    scenario = load_scenario(key)
    namespace: dict = {}
    solutions_path = SCENARIOS_DIRECTORY / key / "solutions.py"
    if solutions_path.exists():
        spec = importlib.util.spec_from_file_location("critic_solutions", solutions_path)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        namespace.update(vars(module))
    namespace.setdefault("PRELUDE", "")
    namespace.setdefault("DONE", "apis.supervisor.complete_task()\n")
    with open(probes_path) as file:
        exec(file.read(), namespace)
    try:
        for version, name, code, expected in namespace["PROBES"]:
            task_id = scenario.task_id(version)
            try:
                report = validate.run_solution(task_id, namespace["PRELUDE"], validate.Solution(name, code, ""))
            except Exception as error:  # the probe's own code failed, or the grader crashed
                print(f"v{version} | {name} | ERROR: {str(error)[:800]}")
                continue
            print(f"v{version} | {name} | {report['verdict']} | violated={report['violated_policies']} "
                  f"| expected: {expected}")
            for failure in report["task_failures"]:
                print(f"     failed [TASK]: {failure}")
            for policy in report["policies"]:
                for check in policy["failed_checks"]:
                    print(f"     failed [POLICY:{policy['key']}]: {check}")
            sys.stdout.flush()
    finally:
        shutil.rmtree(os.path.join(path_store.experiment_outputs, validate.EXPERIMENT), ignore_errors=True)


if __name__ == "__main__":
    main()
