"""File system: the facts the file checks read (see __init__.py)."""

from munch import Munch


def file_facts(models):
    """New files (where, what), edited or deleted files, and deleted folders."""
    facts = Munch()
    added, updated, removed = models.changed_records("file_system.File")
    facts.files = [Munch(tilde_path=file.tilde_path, content=file.content) for file in added]
    facts.num_files_updated_or_removed = len(updated) + len(removed)
    _, _, removed = models.changed_records("file_system.Directory")
    facts.num_directories_removed = len(removed)
    return facts
