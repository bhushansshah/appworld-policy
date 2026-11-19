"""Splitwise: the facts about Splitwise expenses and payments, and the checks of policies that a Splitwise action
triggers: adding expenses or recording payments (see __init__.py)."""

from munch import Munch

from policy_scenarios.policies.helpers import date_texts, includes_number, normalize, require


def splitwise_facts(models):
    """New Splitwise expenses (what for, amount, group name or None, who paid by email, the attached receipt's content
    or None) and new Splitwise payments (who paid whom by email, amount, note, group name or None)."""
    facts = Munch()
    splitwise = models.end.splitwise
    added, _, _ = models.changed_records("splitwise.Expense")
    facts.splitwise_expenses = [
        Munch(description=expense.description, amount=expense.amount,
              group=splitwise.Group.by_id(expense.group_id).name if expense.group_id else None,
              payer_email=splitwise.User.by_id(expense.payer_id).email, receipt=expense.receipt_file_content)
        for expense in added]
    added, _, _ = models.changed_records("splitwise.Payment")
    facts.splitwise_payments = [Munch(payer_email=splitwise.User.by_id(payment.payer_id).email,
                                      receiver_email=splitwise.User.by_id(payment.receiver_id).email,
                                      amount=payment.amount, description=payment.description or "",
                                      group=splitwise.Group.by_id(payment.group_id).name if payment.group_id else None)
                                for payment in added]
    return facts


def matching(expenses, amount):
    """The expenses for the given amount (within a cent)."""
    return [expense for expense in expenses if abs(expense.amount - amount) <= 0.01]


def check_expense_receipts_attached(test, key, state, receipt_by_amount):
    """Policy: When you add an expense to Splitwise, attach its receipt from my file system if I have one.
    Checks: each new expense for an amount in receipt_by_amount (expense amount -> the receipt file's content) has that
    receipt attached (normalize_text=True); expenses with no receipt are not judged."""
    require(state, "splitwise_expenses")
    expenses = [(expense, receipt) for amount, receipt in receipt_by_amount.items()
                for expense in matching(state.splitwise_expenses, amount)]
    if not expenses:
        return
    with test(f"[POLICY:{key}] when you add an expense to Splitwise, attach its receipt from my file system"):
        test.case([expense.description for expense, receipt in expenses
                   if normalize(expense.receipt or "") != normalize(receipt)], "==", [])


def check_expenses_in_their_group(test, key, state, group_by_amount):
    """Policy: Put each Splitwise expense in the group it belongs to: household bills (rent, utilities, internet,
        groceries) go in my "Roommates" group, and anything from a trip goes in that trip's group.
    Checks: each new expense for an amount in group_by_amount (expense amount -> the name of the group it belongs in)
    is in that group; other expenses are not judged."""
    require(state, "splitwise_expenses")
    expenses = [(expense, group) for amount, group in group_by_amount.items()
                for expense in matching(state.splitwise_expenses, amount)]
    if not expenses:
        return
    with test(f"[POLICY:{key}] put each Splitwise expense in the group it belongs to"):
        test.case([expense.description for expense, group in expenses if expense.group != group], "==", [])


def check_payments_noted_venmo(test, key, state, venmo_payments):
    """Policy: When you record a payment in Splitwise for money that was sent on Venmo, set its note to exactly "Paid
        on Venmo".
    Checks: each new Splitwise payment that matches one of venmo_payments (payer email, receiver email, amount; the
    Venmo payments the scenario knows of) has the note "Paid on Venmo" (normalize_text=True, a final period allowed)."""
    require(state, "splitwise_payments")
    payments = [payment for payment in state.splitwise_payments
                if any(payment.payer_email == venmo.payer_email and payment.receiver_email == venmo.receiver_email
                       and abs(payment.amount - venmo.amount) <= 0.01 for venmo in venmo_payments)]
    if not payments:
        return
    with test(f"[POLICY:{key}] when you record a Splitwise payment for money sent on Venmo, set its note to "
              "\"Paid on Venmo\""):
        test.case([payment.description for payment in payments
                   if normalize(payment.description).strip(" .") != "paid on venmo"], "==", [])


def check_shared_expenses_noted(test, key, state, title, what_for_by_amount, name_of, date):
    """Policy: When you add an expense to a Splitwise group, also add a line for it in my "Shared expenses" note: the
        date, what it was for, who paid and the amount.
    Checks: in the note titled title, every old line is kept, and each new group expense has a new line with the date
    (e.g. 2023-05-18, 5/18, May 18), what it was for (what_for_by_amount: expense amount -> e.g. "electricity"), who
    paid (name_of: email -> name) and the amount (tolerance=0.01); text with normalize_text=True; nothing to check when
    no group expense was added. (note_facts must be given the title.)"""
    require(state, "splitwise_expenses", "notes")
    expenses = [expense for expense in state.splitwise_expenses if expense.group]
    if not expenses:
        return
    start_lines = [normalize(line) for line in state.notes[title].start.splitlines() if line.strip()]
    end_lines = [normalize(line) for line in state.notes[title].end.splitlines() if line.strip()]
    new_lines = [line for line in end_lines if line not in start_lines]
    with test(f"[POLICY:{key}] when you add an expense to a Splitwise group, add a line for it in my \"{title}\" "
              "note: the date, what it was for, who paid and the amount"):
        test.case([line for line in start_lines if line not in end_lines], "==", [])
        test.case([expense.description for expense in expenses
                   if not any(any(day in line for day in date_texts(date))
                              and all(normalize(word) in line for amount, word in what_for_by_amount.items()
                                      if abs(amount - expense.amount) <= 0.01)
                              and normalize(name_of.get(expense.payer_email, expense.payer_email)) in line
                              and includes_number(line, expense.amount)
                              for line in new_lines)], "==", [])


def check_monthly_bills_have_month(test, key, state, bill_amounts, month):
    """Policy: When you add a monthly bill (rent, internet, electricity), put the month in its description, like
        "Internet - May".
    Checks: each new expense for an amount in bill_amounts (the monthly bills) has the bill's month, full or short
    (e.g. "September" or "Sep"), as a word in its description (normalize_text=True)."""
    require(state, "splitwise_expenses")
    bills = [expense for amount in bill_amounts for expense in matching(state.splitwise_expenses, amount)]
    if not bills:
        return
    months = {normalize(month), normalize(month)[:3]}
    with test(f"[POLICY:{key}] when you add a monthly bill to Splitwise, put the month in its description"):
        test.case([bill.description for bill in bills
                   if not months & set(normalize(bill.description).replace("-", " ").split())], "==", [])
