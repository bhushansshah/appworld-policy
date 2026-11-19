"""File system: the facts about files that checks read (the checks are filed under the app whose action triggers
their policy, e.g. venmo.py; see __init__.py)."""

from munch import Munch


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
