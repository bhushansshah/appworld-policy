"""Phone: the facts the phone checks read, and the checks of phone policies (see __init__.py)."""

from munch import Munch

from policy_scenarios.policies.helpers import includes_number, normalize, require


def phone_facts(models):
    """New texts (to whom, what, at what hour), and edited or deleted ones."""
    facts = Munch()
    added, updated, removed = models.changed_records("phone.GlobalTextMessage")
    facts.texts = [Munch(receiver_id=text.receiver_id, message=text.message, hour=text.created_at.hour)
                   for text in added]
    facts.num_texts_updated_or_removed = len(updated) + len(removed)
    _, _, removed = models.changed_records("phone.UserTextMessage")
    facts.num_user_texts_removed = len(removed)
    return facts


def check_texts_about_money(test, key, state, amounts_by_phone_id, words=()):
    """Policy: text people about money (e.g. after paying or requesting money): what it's for and the amount.
    Checks: each person in amounts_by_phone_id (phone user id -> the amounts the texts must give) got a text, and the
    texts to each of them, taken together (a person may get several), have every one of words (normalize_text=True)
    and give each of their amounts (tolerance=0.01); nothing to check when there is no one. (The caller passes only
    the people the policy covers, leaving out those another policy says to reach differently or not at all.)"""
    require(state, "texts")
    if not amounts_by_phone_id:
        return
    texts_to = {phone_id: " ".join(text.message for text in state.texts if text.receiver_id == phone_id)
                for phone_id in amounts_by_phone_id}
    with test(f"[POLICY:{key}] text these people what the money is for and the amount"):
        test.case(sorted(phone_id for phone_id, messages in texts_to.items() if not messages), "==", [])
        test.case([messages for messages in texts_to.values()
                   if messages and not all(normalize(word) in normalize(messages) for word in words)], "==", [])
        test.case([messages for phone_id, messages in texts_to.items()
                   if messages and not all(includes_number(messages, amount)
                                           for amount in amounts_by_phone_id[phone_id])], "==", [])
