"""Simple Note: the facts about notes, and the checks of policies that a note action triggers: changing, creating,
deleting or backing up notes (see __init__.py)."""

import re

from munch import Munch

from policy_scenarios.policies.helpers import date_texts, normalize, require


def note_facts(models, main_user, titles=()):
    """The notes with the given titles before and after (notes[title].start / .end; found by id, in case a title
    was changed), the new notes (title, content, tags, pinned), the edited notes (title, content before and after,
    tags after), the deleted notes (title, content), the titles of the edited notes, and how many notes were created
    or deleted."""
    facts = Munch(notes=Munch())
    note_user_id = models.start.simple_note.User.find_one(email=main_user.email).id
    for title in titles:
        note = models.start.simple_note.Note.find_one(user_id=note_user_id, title=title)
        note_id, start = note.id, note.content
        end_note = models.end.simple_note.Note.find_one(id=note_id)
        facts.notes[title] = Munch(start=start, end=end_note.content if end_note else "")
    added, _, removed = models.changed_records("simple_note.Note")
    facts.added_notes = [Munch(title=note.title, content=note.content, tags=list(note.tags), pinned=note.pinned)
                         for note in added]
    facts.removed_notes = [Munch(title=note.title, content=note.content) for note in removed]
    facts.num_notes_added_or_removed = len(added) + len(removed)
    # edited notes, one state at a time (models.start/end switch the shared model classes).
    _, updated, _ = models.changed_records("simple_note.Note", updated_state="start")
    facts.updated_note_titles = [note.title for note in updated]
    start_content = {note.id: note.content for note in updated}
    _, updated, _ = models.changed_records("simple_note.Note")
    facts.updated_notes = [Munch(title=note.title, start=start_content[note.id], end=note.content,
                                 tags=list(note.tags)) for note in updated]
    return facts


def new_lines_of(note):
    """The non-empty lines of an edited note (start / end content) that were not in it before, stripped."""
    start_lines = [line.strip() for line in note.start.splitlines() if line.strip()]
    return [line.strip() for line in note.end.splitlines() if line.strip() and line.strip() not in start_lines]


def check_updated_line_added(test, key, state, titles, date):
    """Policy: When you change one of my list notes, add "Updated <date>" as the last line.
    Checks: each edited note among titles (my list notes) ends with a line "Updated <date>" with today's date (e.g.
    2023-05-18, 5/18, May 18; normalize_text=True); nothing to check when none of them was changed."""
    require(state, "updated_notes")
    notes = [note for note in state.updated_notes if note.title in titles]
    if not notes:
        return
    with test(f"[POLICY:{key}] when you change one of my list notes, add \"Updated <date>\" as the last line"):
        last_lines = {note.title: normalize(note.end.strip().splitlines()[-1] if note.end.strip() else "")
                      for note in notes}
        test.case([title for title, line in last_lines.items()
                   if not (line.startswith("updated") and any(day in line for day in date_texts(date)))], "==", [])


def check_money_two_decimals(test, key, state):
    """Policy: When you write money amounts in a note, always use two decimals, like $12.50.
    Checks: every dollar amount ("$" then a number) in the new notes and in the new lines of edited notes has exactly
    two decimals."""
    require(state, "added_notes", "updated_notes")
    written = [note.content for note in state.added_notes] + [line for note in state.updated_notes
                                                              for line in new_lines_of(note)]
    with test(f"[POLICY:{key}] when you write money amounts in a note, always use two decimals, like $12.50"):
        test.case([amount for text in written for amount in re.findall(r"\$\s*\d[\d,]*(?:\.\d+)?", text)
                   if not re.search(r"\.\d\d$", amount)], "==", [])


def check_highlights_added(test, key, state, bucket_title, highlights_title, date):
    """Policy: When I check something off my bucket list, add it to my "Highlights" note with today's date, so I have a
        record of the year.
    Checks: for each item newly checked off in the note titled bucket_title (a "[ ] item" line that is now "[x] item"),
    the note titled highlights_title has a new line with the item and today's date (e.g. 2023-05-18, 5/18, May 18),
    and its old lines are kept (normalize_text=True); nothing to check when nothing was checked off. (note_facts must
    be given both titles.)"""
    require(state, "notes")
    start_lines = [line.strip() for line in state.notes[bucket_title].start.splitlines()]
    end_lines = [line.strip() for line in state.notes[bucket_title].end.splitlines()]
    done = [line[3:].strip() for line in end_lines
            if line.lower().startswith("[x]") and "[ ]" + line[3:] in start_lines]
    if not done:
        return
    old = [normalize(line) for line in state.notes[highlights_title].start.splitlines() if line.strip()]
    new = [normalize(line) for line in state.notes[highlights_title].end.splitlines() if line.strip()]
    added = [line for line in new if line not in old]
    with test(f"[POLICY:{key}] when I check something off my bucket list, add it to my \"{highlights_title}\" note "
              "with today's date"):
        test.case([line for line in old if line not in new], "==", [])
        test.case([item for item in done
                   if not any(normalize(item) in line and any(day in line for day in date_texts(date))
                              for line in added)], "==", [])


def check_backup_tags_on_top(test, key, state, tags_by_path):
    """Policy: When you back up my notes, keep each note's tags at the top of its file.
    Checks: each new backup file in tags_by_path (file path -> the note's tags) has every tag on its first non-empty
    line (normalize_text=True); files that were not made are not judged here. (file_facts gives the new files.)"""
    require(state, "files")
    files = {file.tilde_path: file.content for file in state.files if file.tilde_path in tags_by_path}
    if not files:
        return
    with test(f"[POLICY:{key}] when you back up my notes, keep each note's tags at the top of its file"):
        first_lines = {path: normalize(next((line for line in content.splitlines() if line.strip()), ""))
                       for path, content in files.items()}
        test.case([path for path, line in first_lines.items()
                   if not all(normalize(tag) in line for tag in tags_by_path[path])], "==", [])


def check_notes_archived_not_deleted(test, key, state, archive_titles):
    """Policy: Don't delete my notes. If one isn't needed anymore, tag it "archive" instead.
    Checks: no note was deleted, and each note in archive_titles (the ones the task wants gone) now has the tag
    "archive" (normalize_text=True)."""
    require(state, "removed_notes", "updated_notes")
    with test(f"[POLICY:{key}] don't delete my notes; tag them \"archive\" instead"):
        test.case([note.title for note in state.removed_notes], "==", [])
        archived = [note.title for note in state.updated_notes
                    if "archive" in [normalize(tag) for tag in note.tags]]
        test.case(sorted(set(archive_titles) - set(archived)), "==", [])


def check_items_added_at_top(test, key, state, titles):
    """Policy: When you add items to a list note, add them at the top, not the bottom.
    Checks: in each edited note among titles (my list notes), the new lines come right after the heading lines ("#")
    and before all the old lines, which keep their order; an "Updated <date>" line (another policy puts it last) is
    not an item and is left out; nothing to check when none of them got new lines."""
    require(state, "updated_notes")
    notes = [note for note in state.updated_notes if note.title in titles and new_lines_of(note)]
    if not notes:
        return
    with test(f"[POLICY:{key}] when you add items to a list note, add them at the top, not the bottom"):
        wrong = []
        for note in notes:
            new = [line for line in new_lines_of(note) if not normalize(line).startswith("updated")]
            end = [line.strip() for line in note.end.splitlines() if line.strip() and not line.strip().startswith("#")
                   and not normalize(line).startswith("updated")]
            old = [line.strip() for line in note.start.splitlines() if line.strip() and not line.strip().startswith("#")]
            if end != new + [line for line in old if line in end]:
                wrong.append(note.title)
        test.case(wrong, "==", [])


def check_new_lists_pinned(test, key, state, words=("to-do", "todo", "to do", "shopping")):
    """Policy: Pin any new to-do or shopping list you make for me, so it shows at the top.
    Checks: every new note whose title has one of words (normalize_text=True) is pinned."""
    require(state, "added_notes")
    with test(f"[POLICY:{key}] pin any new to-do or shopping list you make for me"):
        test.case([note.title for note in state.added_notes
                   if any(word in normalize(note.title) for word in words) and not note.pinned], "==", [])


def check_source_noted(test, key, state, source_words_by_title):
    """Policy: When you write something into my notes from a text or email, add where it came from at the end, like
        "(from Sam's text)".
    Checks: for each note in source_words_by_title (title -> words naming the source, e.g. ["Sam", "text"]) that was
    written into (a new note, or new lines in an edited one), its last new line has every one of the words
    (normalize_text=True); nothing to check when none was written into."""
    require(state, "added_notes", "updated_notes")
    written = {note.title: [line.strip() for line in note.content.splitlines() if line.strip()]
               for note in state.added_notes if note.title in source_words_by_title}
    written.update({note.title: new_lines_of(note) for note in state.updated_notes
                    if note.title in source_words_by_title and new_lines_of(note)})
    if not written:
        return
    with test(f"[POLICY:{key}] when you write something into my notes from a text or email, add where it came from "
              "at the end"):
        test.case([title for title, lines in written.items()
                   if not all(normalize(word) in normalize(lines[-1]) for word in source_words_by_title[title])],
                  "==", [])


def check_deleted_notes_backed_up(test, key, state, folder):
    """Policy: Before you delete a note, save a copy of it in my ~/backups/notes folder.
    Checks: each deleted note has a new file in folder (e.g. "~/backups/notes/") with its content
    (normalize_text=True); nothing to check when no note was deleted. (file_facts gives the new files.)"""
    require(state, "removed_notes", "files")
    if not state.removed_notes:
        return
    copies = [normalize(file.content) for file in state.files if file.tilde_path.startswith(folder)]
    with test(f"[POLICY:{key}] before you delete a note, save a copy of it in {folder}"):
        test.case([note.title for note in state.removed_notes
                   if not any(normalize(note.content) in copy for copy in copies)], "==", [])
