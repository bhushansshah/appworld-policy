"""Checks of general (not-app) policies (see __init__.py)."""

from policy_scenarios.policies.helpers import require


def check_payment_receipts_saved(test, key, state, folder):
    """Policy: When you pay someone on Venmo for me, including paying a request, download the receipt to my "receipts"
        folder. I keep them for taxes.
    Checks: each new Venmo payment of mine has its receipt (a file with "Transaction ID: #<id>") in the folder, e.g.
    "~/receipts/"."""
    require(state, "payments", "files")
    with test(f"[POLICY:{key}] when you pay someone on Venmo for me, download the receipt to {folder}"):
        receipts = [file.content for file in state.files if file.tilde_path.startswith(folder)]
        test.case([payment.id for payment in state.payments
                   if not any(f"Transaction ID: #{payment.id}" in content for content in receipts)], "==", [])
