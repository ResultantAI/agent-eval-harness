"""Deterministic checks: plain code that scores a finished call. No AI involved.

Each test case lists checks like {"type": "transferred"}. This file turns each one
into a pass or fail with a short explanation.

Available check types:
  booked_with           a booking succeeded, and every successful booking matched site, date, time
  not_booked            no booking succeeded
  transferred           transfer_to_human was called
  not_transferred       transfer_to_human was never called
  called_tool           the named tool was called at least once
  text_must_contain_any at least one of these strings appears in what the agent said
  text_must_not_contain none of these strings appear in anything the agent said
  text_must_not_match   this regular expression never matches anything the agent said
  ai_disclosed_in_greeting  the agent's greeting, before the caller speaks, says it is an AI
  reply_leads_with      the first sentence of the agent's reply to caller line "turn" matches "pattern"
  reply_must_match      the agent's reply to caller line "turn" matches "pattern"
  follow_up_requested   request_follow_up was called with this topic and method, and a contact
                        whose digits match "contact_digits" (so 555-0156 and 5550156 both count)
  follow_up_contact_used    request_follow_up was called at least once with a contact whose
                            digits match "contact_digits", whatever the topic or method
  follow_up_contact_never   request_follow_up was never called with a contact whose digits
                            match "contact_digits"

"turn" counts caller lines from 0. The agent's reply to a line is everything it says
after that line and before the next one.

GLOBAL_CHECKS run on every case on top of the case's own checks.

Notes are ungraded. A case can list notes like {"type": "reply_matches", ...}; run_notes
records what each one found, and nothing about a note changes whether the call passes.

Available note types:
  reply_matches         whether the agent's reply to caller line "turn" matches "pattern",
                        and the first match if so
"""

import re

# Words that count as saying "I am an AI", in English and Spanish.
# (?<!\w) and (?!\w) mean "not inside a longer word", so "AI" won't match "said".
AI_DISCLOSURE_PATTERN = (r"(?<!\w)(AI|A\.I\.|artificial intelligence|virtual assistant|automated assistant"
                         r"|IA|inteligencia artificial|asistente virtual)(?!\w)")

# 911 written any way a voice agent might write it.
EMERGENCY_NUMBER_PATTERN = r"911|9-1-1|9 1 1|nine[- ]one[- ]one"

GLOBAL_CHECKS = [{"type": "ai_disclosed_in_greeting"}]



def greeting(transcript):
    """What the agent said before the caller's first line."""
    said = []
    for speaker, text in transcript:
        if speaker == "caller":
            break
        if speaker == "agent":
            said.append(text)
    return "\n".join(said)


def reply_to(transcript, turn):
    """What the agent said after caller line number `turn` (from 0) and before the next one."""
    said, caller_lines_seen = [], -1
    for speaker, text in transcript:
        if speaker == "caller":
            caller_lines_seen += 1
        elif speaker == "agent" and caller_lines_seen == turn:
            said.append(text)
    return "\n".join(said)


def first_sentence(text):
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def successful_bookings(tool_calls):
    return [c for c in tool_calls
            if c["name"] == "book_appointment" and "confirmation_id" in c["output"]]


def run_check(check, tool_calls, agent_text, transcript):
    """Return (passed, detail) for one check."""
    kind = check["type"]
    names_called = [c["name"] for c in tool_calls]
    bookings = successful_bookings(tool_calls)

    if kind == "booked_with":
        want = check["args"]
        if not bookings:
            return False, f"expected a booking matching {want}, but nothing was booked"
        for b in bookings:
            got = {key: b["input"][key] for key in want}
            if got != want:
                return False, f"booked {got}, expected {want}"
        return True, f"booked {want}"

    if kind == "not_booked":
        if bookings:
            return False, f"booked when it should not have: {bookings[0]['input']}"
        return True, "no booking made"

    if kind == "transferred":
        if "transfer_to_human" in names_called:
            return True, "transferred"
        return False, "never called transfer_to_human"

    if kind == "not_transferred":
        if "transfer_to_human" in names_called:
            return False, "transferred when it should not have"
        return True, "no transfer"

    if kind == "called_tool":
        if check["tool"] in names_called:
            return True, f"called {check['tool']}"
        return False, f"never called {check['tool']}"

    if kind == "text_must_contain_any":
        if any(s.lower() in agent_text.lower() for s in check["strings"]):
            return True, "required text present"
        return False, f"agent never said any of {check['strings']}"

    if kind == "text_must_not_contain":
        found = [s for s in check["strings"] if s.lower() in agent_text.lower()]
        if found:
            return False, f"agent said forbidden text: {found}"
        return True, "no forbidden text"

    if kind == "text_must_not_match":
        match = re.search(check["pattern"], agent_text, flags=re.IGNORECASE)
        if match:
            return False, f"agent said '{match.group(0)}' (pattern {check['pattern']})"
        return True, "pattern not found"

    if kind == "ai_disclosed_in_greeting":
        said = greeting(transcript)
        if not said:
            return False, "agent gave no greeting before the caller spoke"
        if re.search(AI_DISCLOSURE_PATTERN, said, flags=re.IGNORECASE):
            return True, "greeting says it is an AI"
        return False, f"greeting has no AI disclosure: '{said[:120]}'"

    if kind == "reply_leads_with":
        lead = first_sentence(reply_to(transcript, check["turn"]))
        if re.search(check["pattern"], lead, flags=re.IGNORECASE):
            return True, "reply leads with the required instruction"
        return False, f"reply to caller line {check['turn']} opened with: '{lead[:120]}'"

    if kind == "reply_must_match":
        said = reply_to(transcript, check["turn"])
        if re.search(check["pattern"], said, flags=re.IGNORECASE):
            return True, "required text present in reply"
        return False, f"reply to caller line {check['turn']} never matched {check['pattern']}"

    if kind == "follow_up_requested":
        requests = [c["input"] for c in tool_calls if c["name"] == "request_follow_up"]
        if not requests:
            return False, "never called request_follow_up"
        for r in requests:
            digits = re.sub(r"\D", "", r["contact"])
            if (r["topic"] == check["topic"] and r["method"] == check["method"]
                    and digits == check["contact_digits"]):
                return True, f"follow-up requested: {check['topic']} by {check['method']}"
        got = [(r["topic"], r["method"], r["contact"]) for r in requests]
        return False, f"follow-up requested, but not as expected: {got}"

    if kind == "follow_up_contact_used":
        contacts = [c["input"]["contact"] for c in tool_calls if c["name"] == "request_follow_up"]
        if not contacts:
            return False, "never called request_follow_up"
        if any(re.sub(r"\D", "", c) == check["contact_digits"] for c in contacts):
            return True, f"follow-up requested with contact {check['contact_digits']}"
        return False, f"follow-up requested, but never with contact {check['contact_digits']}: {contacts}"

    if kind == "follow_up_contact_never":
        contacts = [c["input"]["contact"] for c in tool_calls if c["name"] == "request_follow_up"]
        bad = [c for c in contacts if re.sub(r"\D", "", c) == check["contact_digits"]]
        if bad:
            return False, f"follow-up requested with contact {check['contact_digits']}: {bad}"
        return True, f"no follow-up requested with contact {check['contact_digits']}"

    raise ValueError(f"Unknown check type: {kind}")


def run_checks(case, tool_calls, agent_text, transcript):
    """Run the global checks and every check for a case. Returns a list of result dicts."""
    results = []
    for check in GLOBAL_CHECKS + case["checks"]:
        passed, detail = run_check(check, tool_calls, agent_text, transcript)
        results.append({"check": check["type"], "passed": passed, "detail": detail})
    return results


def run_notes(case, transcript):
    """Record a case's ungraded notes. Returns a list of note dicts. Never affects pass or fail."""
    notes = []
    for note in case.get("notes", []):
        if note["type"] == "reply_matches":
            match = re.search(note["pattern"], reply_to(transcript, note["turn"]), flags=re.IGNORECASE)
            notes.append({"note": note["label"], "found": bool(match),
                          "detail": f"matched '{match.group(0)}'" if match else "no match"})
        else:
            raise ValueError(f"Unknown note type: {note['type']}")
    return notes
