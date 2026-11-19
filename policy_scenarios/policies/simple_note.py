"""Simple Note: the facts about notes that checks read (the checks are filed under the app whose action triggers
their policy, e.g. venmo.py; see __init__.py)."""

from munch import Munch


def note_facts(models, main_user, titles=()):
    """The notes with the given titles before and after (notes[title].start / .end; found by id, in case a title
    was changed), the titles of the edited notes, the new notes (title, content), and how many notes were created or deleted."""
    facts = Munch(notes=Munch())
    note_user_id = models.start.simple_note.User.find_one(email=main_user.email).id
    for title in titles:
        note = models.start.simple_note.Note.find_one(user_id=note_user_id, title=title)
        note_id, start = note.id, note.content
        end_note = models.end.simple_note.Note.find_one(id=note_id)
        facts.notes[title] = Munch(start=start, end=end_note.content if end_note else "")
    added, _, removed = models.changed_records("simple_note.Note")
    facts.added_notes = [Munch(title=note.title, content=note.content) for note in added]
    facts.num_notes_added_or_removed = len(added) + len(removed)
    _, updated, _ = models.changed_records("simple_note.Note", updated_state="start")
    facts.updated_note_titles = [note.title for note in updated]
    return facts
