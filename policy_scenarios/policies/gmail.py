"""Gmail: the facts the email checks read (see __init__.py)."""

from munch import Munch


def email_facts(models):
    """How many emails, threads or attachments were deleted."""
    gmail_models = ["gmail.Email", "gmail.GlobalEmailThread", "gmail.UserEmailThread", "gmail.Attachment"]
    return Munch(num_emails_removed=sum(len(models.changed_records(name)[2]) for name in gmail_models))
