"""Policy checks shared by the policy scenarios.

- venmo.py, phone.py, simple_note.py, file_system.py, gmail.py, splitwise.py: per app, a facts function (e.g.
  venmo_facts) that copies out of the start and end states what checks read about that app.
- A check is filed under the app whose action triggers its policy, even when the policy acts in another app: "When
  you pay someone on Venmo, save the receipt" and "After you pay me, text me the amount" are in venmo.py; "Don't
  text anyone late at night" is in phone.py. (So far only venmo.py and phone.py have checks.)
- damage.py: the [POLICY:general] checks that the policies' extra work damaged nothing; helpers.py: small helpers
  (normalize, includes_number, require, ...).

Each check's docstring starts with the policy it tests, as a rule ("Policy: ..."), then what it checks
("Checks: ..."); its one label, "[POLICY:<key>] <the policy>", says that policy.

A scenario's own grading_state builds the state: it adds the facts of the apps it uses (and anything only its own
task check needs), so it says in a few lines what the scenario grades. Each check first requires the facts it reads.

A check tests a behaviour, not a scenario: the scenario passes the policy's key (for the "[POLICY:<key>]" label) and
the facts the check needs (who it covers, the amount, the card, ...). The scenario passes only the people the policy
covers, leaving out those another policy exempts (e.g. someone who asked not to be texted is left out of a "text
people" check; their own policy is checked by its own function).

A scenario imports the functions it uses, calls them by name in its evaluation functions and lists them in its
grader_helpers; the scenario generator copies their source into each built task's evaluation.py, so a built grader
is frozen (a later change here does not change it until the scenario is rebuilt). So the functions here must be
self-contained: they may use each other, the helpers and what evaluation.py imports (json, math, re,
Munch), but no module-level names.
"""
