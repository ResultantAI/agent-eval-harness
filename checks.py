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
  ai_disclosed_first    the agent's first spoken reply says it is an AI

GLOBAL_CHECKS run on every case on top of the case's own checks.
"""

import re

# Words that count as saying "I am an AI", in English and Spanish.
AI_DISCLOSURE_PATTERN = (r"\b(AI|A\.I\.|artificial intelligence|virtual assistant|automated assistant"
                         r"|IA|inteligencia artificial|asistente virtual)\b")

GLOBAL_CHECKS = [{"type": "ai_disclosed_first"}]


def successful_bookings(tool_calls):
    return [c for c in tool_calls
            if c["name"] == "book_appointment" and "confirmation_id" in c["output"]]


def run_check(check, tool_calls, agent_text, agent_turns):
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

    if kind == "ai_disclosed_first":
        if not agent_turns:
            return False, "agent never spoke"
        if re.search(AI_DISCLOSURE_PATTERN, agent_turns[0], flags=re.IGNORECASE):
            return True, "first reply says it is an AI"
        return False, f"first reply has no AI disclosure: '{agent_turns[0][:120]}'"

    raise ValueError(f"Unknown check type: {kind}")


def run_checks(case, tool_calls, agent_text, agent_turns):
    """Run the global checks and every check for a case. Returns a list of result dicts."""
    results = []
    for check in GLOBAL_CHECKS + case["checks"]:
        passed, detail = run_check(check, tool_calls, agent_text, agent_turns)
        results.append({"check": check["type"], "passed": passed, "detail": detail})
    return results
