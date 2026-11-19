"""Splitwise: the facts about Splitwise payments that checks read (the checks are filed under the app whose action
triggers their policy, e.g. venmo.py; see __init__.py)."""

from munch import Munch


def splitwise_facts(models):
    """New Splitwise payments (who paid whom, by email, and how much)."""
    facts = Munch()
    added, _, _ = models.changed_records("splitwise.Payment")
    facts.splitwise_payments = [Munch(payer_email=models.end.splitwise.User.by_id(payment.payer_id).email,
                                      receiver_email=models.end.splitwise.User.by_id(payment.receiver_id).email,
                                      amount=payment.amount) for payment in added]
    return facts
