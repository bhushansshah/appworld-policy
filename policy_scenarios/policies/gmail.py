"""Gmail: the facts the email checks read, and the checks of email policies (see __init__.py)."""

from munch import Munch

from policy_scenarios.policies.helpers import require


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


def check_receipt_emailed(test, key, state, gmail_user_ids, receipt):
    """Policy: when you ask me to pay for a bill, email me the receipt as well.
    Checks: each of gmail_user_ids got exactly one new email, with exactly one attachment, the receipt (its content);
    nothing to check when there is no one. (The caller passes only the people asked to pay.)"""
    require(state, "emails", "attachments")
    if not gmail_user_ids:
        return
    with test(f"[POLICY:{key}] when you ask me to pay for a bill, email me the receipt as well"):
        for gmail_user_id in gmail_user_ids:
            emails = [email for email in state.emails if gmail_user_id in email.recipient_ids]
            test.case(len(emails), "==", 1)
            attachments = [attachment for attachment in state.attachments
                           if emails and attachment.email_id == emails[0].id]
            test.case(len(attachments), "==", 1)
            test.case(attachments[0].file_content.strip(), "==", (receipt or "").strip())
