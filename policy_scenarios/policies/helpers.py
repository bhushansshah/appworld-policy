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


def date_texts(date):
    """The common ways to write a date, lower case: 2023-05-18, 5/18, 05/18, may 18, 18 may (and with "May" short).
    date: a date, or its text "YYYY-MM-DD" (the start of str(date))."""
    year, month, day = (int(part) for part in str(date)[:10].split("-"))
    month_name = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                  "november", "december"][month - 1]
    return [f"{year}-{month:02d}-{day:02d}", f"{month}/{day}", f"{month:02d}/{day:02d}", f"{month_name} {day}",
            f"{month_name[:3]} {day}", f"{day} {month_name}", f"{day} {month_name[:3]}"]
