"""Simple Note: the facts the note checks read, and the checks of Simple Note policies (see __init__.py)."""

from munch import Munch

from policy_scenarios.policies.helpers import normalize, require


def note_facts(models, main_user, titles=()):
    """The notes with the given titles before and after (notes[title].start / .end; found by id, in case a title
    was changed), the titles of the edited notes, and how many notes were created or deleted."""
    facts = Munch(notes=Munch())
    note_user_id = models.start.simple_note.User.find_one(email=main_user.email).id
    for title in titles:
        note = models.start.simple_note.Note.find_one(user_id=note_user_id, title=title)
        note_id, start = note.id, note.content
        end_note = models.end.simple_note.Note.find_one(id=note_id)
        facts.notes[title] = Munch(start=start, end=end_note.content if end_note else "")
    added, _, removed = models.changed_records("simple_note.Note")
    facts.num_notes_added_or_removed = len(added) + len(removed)
    _, updated, _ = models.changed_records("simple_note.Note", updated_state="start")
    facts.updated_note_titles = [note.title for note in updated]
    return facts


def check_note_lines_marked(test, key, state, title, line_starts, suffix):
    """Policy: mark these lines of my note (e.g. what I paid back) by adding this suffix at their end.
    Checks: in the note titled title, the lines starting with any of line_starts end with suffix, and every other
    line (a header too) is unchanged, with no line added or removed (normalize_text=True); nothing to check when no
    line is to be marked. (note_facts must be given the title.)"""
    require(state, "notes")
    if not line_starts:
        return
    start_lines = [line.strip() for line in state.notes[title].start.strip().splitlines()]
    end_lines = [line.strip() for line in state.notes[title].end.strip().splitlines()]
    with test(f"[POLICY:{key}] mark these lines of the note \"{title}\" with \"{suffix}\""):
        expected = [normalize(line + suffix if line.startswith(tuple(line_starts)) else line) for line in start_lines]
        test.case([normalize(line) for line in end_lines], "==", expected)
