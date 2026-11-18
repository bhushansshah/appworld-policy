"""Small helpers the policy checks use (see __init__.py)."""

import re


def normalize(text):
    """Lower case, with runs of spaces made one."""
    return " ".join(str(text).lower().split())


def numbers_in(text):
    """Every number written in digits in the text: "$30", "30" and "30.00" are all 30.0."""
    return [float(number.replace(",", "")) for number in re.findall(r"\d[\d,]*(?:\.\d+)?", str(text))]


def includes_number(text, value, tolerance=0.01):
    return any(abs(number - value) <= tolerance for number in numbers_in(text))


def require(state, *names):
    """Fail loudly (not as a failed check) when the grading state lacks what a check reads: the scenario's
    grading_state must add the facts of the app (e.g. venmo_facts)."""
    missing = [name for name in names if name not in state]
    assert not missing, f"The grading state lacks {missing}: add the app's facts in the scenario's grading_state."
