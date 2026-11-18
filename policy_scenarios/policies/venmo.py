"""Venmo: the facts the Venmo checks read, and the checks of Venmo policies (see __init__.py)."""

from munch import Munch

from policy_scenarios.policies.helpers import require


def venmo_facts(models, main_user):
    """My new payments and the other new transactions, balance top-ups and withdrawals, Venmo friends, and my
    balance before and after (values copied out right away: models.start/end switch the shared model classes)."""
    facts = Munch()
    my_venmo_id = models.start.venmo.User.find_one(email=main_user.email).id
    facts.start_balance = models.start.venmo.User.by_id(my_venmo_id).venmo_balance
    facts.end_balance = models.end.venmo.User.by_id(my_venmo_id).venmo_balance
    added, updated, removed = models.changed_records("venmo.Transaction")
    facts.transactions = [Munch(id=transaction.id, sender_id=transaction.sender_id,
                                receiver_id=transaction.receiver_id, amount=transaction.amount,
                                description=transaction.description, private=transaction.private,
                                card=transaction.payment_card_digits) for transaction in added]
    facts.num_transactions_updated, facts.num_transactions_removed = len(updated), len(removed)
    facts.payments = [transaction for transaction in facts.transactions if transaction.sender_id == my_venmo_id]
    added, _, _ = models.changed_records("venmo.BankTransfer")
    facts.top_ups = [Munch(amount=transfer.amount, card=transfer.payment_card_digits) for transfer in added
                     if transfer.user_id == my_venmo_id and transfer.transfer_type == "card_to_venmo"]
    facts.withdrawals = [Munch(amount=transfer.amount, card=transfer.payment_card_digits) for transfer in added
                         if transfer.user_id == my_venmo_id and transfer.transfer_type == "venmo_to_card"]
    added, _, removed = models.changed_records("venmo.Friendship")
    facts.new_venmo_friend_ids = [friendship.friend_id for friendship in added if friendship.user_id == my_venmo_id]
    facts.num_venmo_friendships_removed = len(removed)
    return facts


def check_payments_private(test, key, state, receiver_ids):
    """Policy: send money to these people privately.
    Checks: every new payment of mine to receiver_ids is private. (The caller passes only the people the policy
    covers, leaving out those another policy covers.)"""
    require(state, "payments")
    with test(f"[POLICY:{key}] send money to these people privately"):
        test.case([payment.amount for payment in state.payments
                   if payment.receiver_id in receiver_ids and not payment.private], "==", [])


def check_payments_from_balance(test, key, state):
    """Policy: pay people from my Venmo balance, not from a card.
    Checks: no new payment of mine was paid with a card."""
    require(state, "payments")
    with test(f"[POLICY:{key}] pay people from my Venmo balance, not from a card"):
        test.case([payment.card for payment in state.payments if payment.card], "==", [])


def check_exact_payback(test, key, state, amounts_owed):
    """Policy: when paying someone back, pay the exact amount, cents included.
    Checks: every new payment of mine to a person in amounts_owed (venmo user id -> what I owe them) is for exactly
    what I owe them. (The caller passes the people being paid back; payments to others are not judged here.)"""
    require(state, "payments")
    with test(f"[POLICY:{key}] when paying someone back, pay the exact amount, cents included"):
        test.case([payment.amount for payment in state.payments if payment.receiver_id in amounts_owed
                   and round(payment.amount, 2) != round(amounts_owed[payment.receiver_id], 2)], "==", [])


def check_card_used(test, key, state, card_digits):
    """Policy: when something on Venmo has to come from a card, use this card.
    Checks: every new card payment and balance top-up of mine used the card ending in card_digits."""
    require(state, "payments", "top_ups")
    with test(f"[POLICY:{key}] when something on Venmo has to come from a card, use the card ending in "
              f"{card_digits}"):
        cards = [payment.card for payment in state.payments if payment.card]
        cards += [top_up.card for top_up in state.top_ups]
        test.case([card for card in cards if card != card_digits], "==", [])


def check_keep_min_balance(test, key, state, minimum, card_digits):
    """Policy: keep at least this much in my Venmo balance; if a payment takes it below that, top it back up to it
    from this card.
    Checks: the balance ends at least at the minimum (to the cent); if it was topped up, it ends at exactly the
    minimum (to the cent), and every top-up used the card ending in card_digits. (Paying from a card leaves the
    balance as it was, so no top-up is needed then.)"""
    require(state, "end_balance", "top_ups")
    with test(f"[POLICY:{key}] keep at least ${minimum} in my Venmo balance, topped back up from the card ending in "
              f"{card_digits}"):
        test.case(round(state.end_balance, 2), ">=", minimum)
        if state.top_ups:
            test.case(round(state.end_balance, 2), "==", minimum)
            test.case([top_up.card for top_up in state.top_ups if top_up.card != card_digits], "==", [])


def check_venmo_friends_added(test, key, state, venmo_user_ids):
    """Policy: add these people (e.g. the people I pay who aren't my Venmo friends yet) as Venmo friends.
    Checks: each of venmo_user_ids is now my Venmo friend; nothing to check when there is no one. (The caller passes
    only the people the policy covers, leaving out those another policy covers.)"""
    require(state, "new_venmo_friend_ids")
    if not venmo_user_ids:
        return
    with test(f"[POLICY:{key}] add these people as Venmo friends"):
        test.case(sorted(set(venmo_user_ids) - set(state.new_venmo_friend_ids)), "==", [])


def check_no_withdrawals(test, key, state):
    """Policy: never move money out of my Venmo balance (to a bank or card).
    Checks: no withdrawal from my Venmo balance was made."""
    require(state, "withdrawals")
    with test(f"[POLICY:{key}] never move money out of my Venmo balance"):
        test.case([withdrawal.amount for withdrawal in state.withdrawals], "==", [])
