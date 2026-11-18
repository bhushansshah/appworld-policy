"""File system: the facts the file checks read, and the checks of file policies (see __init__.py)."""

from munch import Munch

from policy_scenarios.policies.helpers import normalize, require


def file_facts(models, main_user, paths=()):
    """New files (where, what), how many files were added, edited or deleted (and the paths of the edited ones),
    how many folders were added or deleted, and the content of the given files before and after
    (file_contents[path].start / .end, None if the file is missing)."""
    facts = Munch()
    added, updated, removed = models.changed_records("file_system.File")
    facts.files = [Munch(tilde_path=file.tilde_path, content=file.content) for file in added]
    facts.num_files_added = len(added)
    facts.num_files_updated_or_removed = len(updated) + len(removed)
    facts.num_files_removed = len(removed)
    facts.updated_file_paths = [file.tilde_path for file in updated]
    added, _, removed = models.changed_records("file_system.Directory")
    facts.num_directories_added, facts.num_directories_removed = len(added), len(removed)
    user_id = models.start.file_system.User.find_one(email=main_user.email).id
    facts.file_contents = Munch()
    for path in paths:
        contents = []
        for which in ("start", "end"):  # one state at a time: models.start/end switch the shared model classes
            files = [file.content for file in getattr(models, which).file_system.File.find_all(user_id=user_id)
                     if file.tilde_path == path]
            contents.append(files[0] if files else None)
        facts.file_contents[path] = Munch(start=contents[0], end=contents[1])
    return facts


def check_expense_line_added(test, key, state, path, expected_fields):
    """Policy: Every time you split a household bill, add one line for it to ~/bills/shared_expenses.csv. You can look
        at the existing rows for reference to add this one.
    Checks: exactly one line was added to the file at path, at the end, the old lines are kept in the same order, and
    the new line's comma-separated fields are expected_fields (numbers within 0.01, "$" ignored; text with
    normalize_text=True). (The caller checks it only when a bill was split. file_facts must be given the path.)"""
    require(state, "file_contents")
    start_lines = (state.file_contents[path].start or "").strip().splitlines()
    end_lines = (state.file_contents[path].end or "").strip().splitlines()
    fields = [field.strip() for field in end_lines[-1].split(",")] if end_lines else []
    with test(f"[POLICY:{key}] every time you split a household bill, add one line for it to {path}"):
        test.case(len(end_lines), "==", len(start_lines) + 1)
        test.case(end_lines[:-1], "==", start_lines)
        test.case(len(fields), "==", len(expected_fields))
        for field, expected in zip(fields, expected_fields):
            if isinstance(expected, (int, float)):
                test.case(float(field.replace("$", "")), "==", expected, tolerance=0.01)
            else:
                test.case(normalize(field), "==", normalize(expected))
