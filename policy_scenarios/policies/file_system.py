"""File system: the facts about files and folders, and the checks of policies that a file action triggers: making,
moving or naming files and folders (see __init__.py)."""

import re

from munch import Munch

from policy_scenarios.policies.helpers import require


def file_facts(models, main_user, paths=()):
    """New files (where, what), how many files were added, edited or deleted (and the paths of the edited ones),
    the new folders and how many folders were added or deleted, the names of my files before, and the content of the
    given files before and after (file_contents[path].start / .end, None if the file is missing)."""
    facts = Munch()
    added, updated, removed = models.changed_records("file_system.File")
    facts.files = [Munch(tilde_path=file.tilde_path, content=file.content) for file in added]
    facts.num_files_added = len(added)
    facts.num_files_updated_or_removed = len(updated) + len(removed)
    facts.num_files_removed = len(removed)
    facts.updated_file_paths = [file.tilde_path for file in updated]
    added, _, removed = models.changed_records("file_system.Directory")
    facts.new_directories = [directory.tilde_path for directory in added]
    facts.num_directories_added, facts.num_directories_removed = len(added), len(removed)
    user_id = models.start.file_system.User.find_one(email=main_user.email).id
    facts.start_file_names = {file.tilde_path.split("/")[-1]
                              for file in models.start.file_system.File.find_all(user_id=user_id)}
    facts.file_contents = Munch()
    for path in paths:
        contents = []
        for which in ("start", "end"):  # one state at a time: models.start/end switch the shared model classes
            files = [file.content for file in getattr(models, which).file_system.File.find_all(user_id=user_id)
                     if file.tilde_path == path]
            contents.append(files[0] if files else None)
        facts.file_contents[path] = Munch(start=contents[0], end=contents[1])
    return facts


def check_new_folders_lowercase(test, key, state):
    """Policy: When you make folders for me, name them in lowercase with underscores, like "grand_canyon".
    Checks: every new folder's name has only lowercase letters, digits and underscores."""
    require(state, "new_directories")
    names = [path.rstrip("/").split("/")[-1] for path in state.new_directories]
    with test(f"[POLICY:{key}] when you make folders for me, name them in lowercase with underscores"):
        test.case([name for name in names if not re.fullmatch(r"[a-z0-9_]+", name)], "==", [])


def check_new_file_names_lowercase(test, key, state):
    """Policy: Keep my file names lowercase, like "grocery_list.md". Mixed case trips me up when I search for files.
    Checks: every new file with a new name (not the name of a file I already had, so a moved file keeping its name
    is fine) has no capital letters in its name."""
    require(state, "files", "start_file_names")
    names = [file.tilde_path.split("/")[-1] for file in state.files]
    with test(f"[POLICY:{key}] keep my file names lowercase"):
        test.case([name for name in names if name not in state.start_file_names and name != name.lower()], "==", [])


def check_same_name_not_replaced(test, key, state, clash_paths):
    """Policy: If a file with the same name is already where you're moving one, don't replace it. Add "-1" to the new
        file's name.
    Checks: each file at clash_paths (one that was already where the task moves a file with the same name) still has
    its old content, and a new file sits next to it with "-1" added before the extension (e.g. "~/trash/notes.txt" ->
    "~/trash/notes-1.txt"). (file_facts must be given the clash paths.)"""
    require(state, "files", "file_contents")
    new_paths = [file.tilde_path for file in state.files]
    with test(f"[POLICY:{key}] if a file with the same name is already there, don't replace it; add \"-1\" to the new "
              "file's name"):
        test.case([path for path in clash_paths
                   if state.file_contents[path].end != state.file_contents[path].start], "==", [])
        expected = [re.sub(r"(\.[^./]+)?$", lambda match: "-1" + match.group(0), path, count=1) for path in clash_paths]
        test.case([path for path in expected if path not in new_paths], "==", [])


def check_receipts_named_date_first(test, key, state, folder, date):
    """Policy: When you save a receipt for me, name it with the date first, like "2023-05-18_venmo_david.txt".
    Checks: every new file in folder (where the receipts are saved, e.g. "~/receipts/") has a name starting with the
    date as YYYY-MM-DD; nothing to check when no file was saved there."""
    require(state, "files")
    names = [file.tilde_path.split("/")[-1] for file in state.files if file.tilde_path.startswith(folder)]
    if not names:
        return
    day = f"{date.year}-{date.month:02d}-{date.day:02d}"
    with test(f"[POLICY:{key}] when you save a receipt for me, name it with the date first, like \"{day}_...\""):
        test.case([name for name in names if not name.startswith(day)], "==", [])
