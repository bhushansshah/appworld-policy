"""Gmail: the facts about emails that checks read (the checks are filed under the app whose action triggers their
policy, e.g. venmo.py; see __init__.py)."""

from munch import Munch


def email_facts(models):
    """New emails (id, recipients) and attachments (email id, content), how many emails were edited, how many emails,
    threads or attachments were deleted, and the threads an email was deleted from (deleting one email from a thread
    updates the thread; a reply only adds to it)."""
    facts = Munch()
    added, updated, _ = models.changed_records("gmail.Email")
    facts.emails = [Munch(id=email.id, recipient_ids=list(email.recipient_ids)) for email in added]
    facts.num_emails_updated = len(updated)
    added, _, _ = models.changed_records("gmail.Attachment")
    facts.attachments = [Munch(email_id=attachment.email_id, file_content=attachment.file_content)
                         for attachment in added]
    gmail_models = ["gmail.Email", "gmail.GlobalEmailThread", "gmail.UserEmailThread", "gmail.Attachment"]
    facts.num_emails_removed = sum(len(models.changed_records(name)[2]) for name in gmail_models)
    _, threads_end, _ = models.changed_records("gmail.UserEmailThread")
    end_ids = {thread.id: set(thread.email_ids) for thread in threads_end}
    _, threads_start, _ = models.changed_records("gmail.UserEmailThread", updated_state="start")
    facts.threads_with_deleted_emails = [thread.id for thread in threads_start
                                         if not set(thread.email_ids) <= end_ids[thread.id]]
    return facts
