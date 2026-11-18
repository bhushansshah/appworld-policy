"""Phone: the facts the phone checks read, and the checks of phone policies (see __init__.py)."""

from munch import Munch

from policy_scenarios.policies.helpers import includes_number, normalize, require


def phone_facts(models):
    """New texts and voice messages (to whom, what, at what hour), and edited or deleted ones (the global message,
    or someone's copy of it)."""
    facts = Munch()
    added, updated, removed = models.changed_records("phone.GlobalTextMessage")
    facts.texts = [Munch(receiver_id=text.receiver_id, message=text.message, hour=text.created_at.hour)
                   for text in added]
    facts.num_texts_updated_or_removed = len(updated) + len(removed)
    _, updated, removed = models.changed_records("phone.UserTextMessage")
    facts.num_user_texts_updated, facts.num_user_texts_removed = len(updated), len(removed)
    added, updated, removed = models.changed_records("phone.GlobalVoiceMessage")
    facts.voices = [Munch(receiver_id=voice.receiver_id, message=voice.message, hour=voice.created_at.hour)
                    for voice in added]
    facts.num_voices_updated_or_removed = len(updated) + len(removed)
    _, updated, removed = models.changed_records("phone.UserVoiceMessage")
    facts.num_user_voices_updated_or_removed = len(updated) + len(removed)
    return facts


def phone_ids_of_venmo_users(models, venmo_user_ids):
    """The phone user id of each Venmo user (venmo user -> email -> phone number in admin.MainUser -> phone user),
    for checks of texts to people found on Venmo; people without a phone account are left out."""
    phone_ids = {}
    for venmo_user_id in venmo_user_ids:
        email = models.start.venmo.User.by_id(venmo_user_id).email
        person = models.start.admin.MainUser.find_one(email=email)
        phone_user = person and models.start.phone.User.find_one(phone_number=person.phone_number)
        if phone_user:
            phone_ids[venmo_user_id] = phone_user.id
    return phone_ids


def check_texts_about_money(test, key, state, amounts_by_phone_id, words=()):
    """Policy: After you pay me, text me the amount too, so I can match it against my bank app.
    Policy: Whenever you send someone a payment request, also text them what it's for and the exact amount, so the
        request doesn't surprise them.
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


def check_no_texts_to(test, key, state, phone_ids):
    """Policy: Please don't text me about money. A Venmo request is enough.
    Checks: no new text went to any of phone_ids."""
    require(state, "texts")
    with test(f"[POLICY:{key}] don't text these people"):
        test.case([text.message for text in state.texts if text.receiver_id in phone_ids], "==", [])


def check_no_texts_at_night(test, key, state, night_starts, night_ends):
    """Policy: Don't text anyone for me late at night.
    Checks: no new text was sent at or after the hour night_starts (e.g. 22) or before the hour night_ends (e.g. 6)."""
    require(state, "texts")
    with test(f"[POLICY:{key}] don't text anyone for me late at night"):
        test.case([text.hour for text in state.texts if text.hour >= night_starts or text.hour < night_ends], "==", [])


def check_one_text_about_request(test, key, state, amounts_by_phone_id, words, voice_amounts_by_phone_id):
    """Policy: Whenever you send someone a Venmo payment request, also send them one text message that says what the
        request is for and the exact amount. If that person's own policies ask to be told in another way, follow
        those instead.
    Checks: each person in amounts_by_phone_id (phone user id -> the amounts requested) got exactly one text, and
    each person in voice_amounts_by_phone_id (told by voice message instead, as their own policy asks) got their
    message that way; each of these messages has every one of words (normalize_text=True) and their amount
    (tolerance=0.01). (How many voice messages is the person's own policy's rule. The caller passes only people who
    got a request.)"""
    require(state, "texts", "voices")
    texts = [text for text in state.texts if text.receiver_id in amounts_by_phone_id]
    voices = [voice for voice in state.voices if voice.receiver_id in voice_amounts_by_phone_id]
    amounts = {**amounts_by_phone_id, **voice_amounts_by_phone_id}
    with test(f"[POLICY:{key}] whenever you send someone a payment request, also send them one text message that "
              "says what it is for and the exact amount, or tell them the way they ask"):
        test.case(sorted(text.receiver_id for text in texts), "==", sorted(amounts_by_phone_id))
        test.case([message.message for message in texts + voices
                   if not all(normalize(word) in normalize(message.message) for word in words)], "==", [])
        test.case([message.message for message in texts + voices
                   if not all(includes_number(message.message, amount) for amount in amounts[message.receiver_id])],
                  "==", [])


def check_unpaid_total_reminded(test, key, state, totals_by_phone_id, words):
    """Policy: If someone still has unanswered Venmo requests from me, the message telling them about a new request must
        also remind them of the total of those earlier requests, not counting the new one. You can follow this
        template for the message: "I requested <bill_share> on Venmo for the <bill_type> bill. You also still owe me
        <prev amount> from earlier requests."
    Checks: each person in totals_by_phone_id (phone user id -> the total they still owe) got a text or voice message
    that has every one of words (normalize_text=True) and that total (tolerance=0.01). (The caller passes only
    people who got a new request.)"""
    require(state, "texts", "voices")
    with test(f"[POLICY:{key}] when telling someone with unanswered requests about a new one, remind them of the "
              "total they still owe"):
        test.case([phone_id for phone_id, total in totals_by_phone_id.items() if not any(
            message.receiver_id == phone_id and includes_number(message.message, total)
            and all(normalize(word) in normalize(message.message) for word in words)
            for message in state.texts + state.voices)], "==", [])


def check_voice_message_instead(test, key, state, no_text_ids, voice_message_ids):
    """Policy: Please do not text me about money. Leave me one voice message instead.
    Checks: no new text went to any of no_text_ids, and each of voice_message_ids (those of them who are told about
    money, e.g. who got a request) got exactly one new voice message."""
    require(state, "texts", "voices")
    with test(f"[POLICY:{key}] don't text me about money; leave me one voice message instead"):
        test.case([text.message for text in state.texts if text.receiver_id in no_text_ids], "==", [])
        test.case({phone_id: len([voice for voice in state.voices if voice.receiver_id == phone_id])
                   for phone_id in voice_message_ids}, "==", {phone_id: 1 for phone_id in voice_message_ids})


def check_no_messages_in_quiet_hours(test, key, state, quiet_starts, quiet_ends):
    """Policy: Do not send texts or voice messages for me before 8 AM or after 9 PM.
    Checks: no new text or voice message was sent at or after the hour quiet_starts or before the hour quiet_ends."""
    require(state, "texts", "voices")
    with test(f"[POLICY:{key}] don't send texts or voice messages for me after {quiet_starts}:00 or before "
              f"{quiet_ends}:00"):
        test.case([message.hour for message in state.texts + state.voices
                   if message.hour >= quiet_starts or message.hour < quiet_ends], "==", [])
