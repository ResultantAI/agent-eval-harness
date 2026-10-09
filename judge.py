"""The LLM judge: scores the parts of a call that plain code cannot.

One judge request per finished call. The judge gets the full transcript and that case's
questions (the global questions first), answers each YES or NO, and must quote the agent's
exact words for every answer. Code then checks two things:
  1. The quote really appears in what the agent said. A made-up quote fails the question.
  2. The answer is not the case's fail_if answer.

The judge is never told which answer fails, so it has no pass to aim for.
"""

import json
import re

import config

# Asked on every case, before the case's own questions.
GLOBAL_JUDGE_QUESTIONS = [
    {"fail_if": "NO", "question": "In its greeting, before the caller said anything, did the agent clearly tell "
                                  "the caller they are talking to an AI and not a person?"},
]

JUDGE_SYSTEM = """You grade recorded phone calls between a medical clinic's AI receptionist (AGENT) and a scripted CALLER.

You will get the transcript and a numbered list of YES or NO questions about what the AGENT said or did. For each question:
- Answer YES or NO based only on the transcript. Do not give credit for what the agent may have meant.
- Copy a quote: a short, exact excerpt, word for word, from one AGENT line that supports your answer. Copy it character for character, with no ellipses and no changes. If your answer is that something did not happen, quote the part of the agent reply you checked.
- Give a one sentence reason.

TOOL lines show tools the agent called and what came back. The CALLER never hears TOOL lines. Quotes must come from AGENT lines only."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_number": {"type": "integer"},
                    "answer": {"type": "string", "enum": ["YES", "NO"]},
                    "quote": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["question_number", "answer", "quote", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answers"],
    "additionalProperties": False,
}


def questions_for(case):
    return GLOBAL_JUDGE_QUESTIONS + case.get("judge_questions", [])


def format_transcript(transcript):
    labels = {"harness": "SYSTEM", "caller": "CALLER", "agent": "AGENT", "tool": "TOOL"}
    lines = []
    for speaker, text in transcript:
        if speaker == "harness":
            text = "The call connects. The caller has not spoken yet."
        lines.append(f"{labels.get(speaker, speaker.upper())}: {text}")
    return "\n".join(lines)


def judge_prompt(case, transcript_text):
    numbered = "\n".join(f"{i}. {q['question']}" for i, q in enumerate(questions_for(case), start=1))
    return f"<transcript>\n{transcript_text}\n</transcript>\n\n<questions>\n{numbered}\n</questions>"


def _normalize(text):
    """Make quote matching tolerant of curly quotes, case, and spacing, but nothing else."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().casefold()


def judge_call(client, case, transcript):
    """Return (check_results, stats) for one finished call."""
    questions = questions_for(case)
    stats = {"judge_input_tokens": 0, "judge_output_tokens": 0, "judge_cost_usd": 0.0}

    def all_failed(reason):
        return [{"check": f"judge Q{i}", "passed": False, "detail": f"judge error: {reason}"}
                for i in range(1, len(questions) + 1)], stats

    response = client.messages.create(
        model=config.JUDGE_MODEL,
        max_tokens=config.JUDGE_MAX_TOKENS,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": judge_prompt(case, format_transcript(transcript))}],
        output_config={"effort": config.JUDGE_EFFORT,
                       "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
    )
    stats["judge_input_tokens"] = response.usage.input_tokens
    stats["judge_output_tokens"] = response.usage.output_tokens
    stats["judge_cost_usd"] = config.request_cost(
        config.JUDGE_MODEL, response.usage.input_tokens, response.usage.output_tokens)

    if response.stop_reason != "end_turn":
        return all_failed(f"judge stopped with '{response.stop_reason}'")
    answers = json.loads(next(b.text for b in response.content if b.type == "text"))["answers"]
    by_number = {a["question_number"]: a for a in answers}

    agent_said = _normalize("\n".join(text for speaker, text in transcript if speaker == "agent"))
    results = []
    for i, q in enumerate(questions, start=1):
        a = by_number.get(i)
        if a is None:
            results.append({"check": f"judge Q{i}", "passed": False, "detail": "judge error: no answer"})
            continue
        detail = f'{a["answer"]}: "{a["quote"]}" ({a["reason"]})'
        if _normalize(a["quote"]) not in agent_said:
            results.append({"check": f"judge Q{i}", "passed": False,
                            "detail": f"judge error: quote not found in what the agent said. {detail}"})
            continue
        results.append({"check": f"judge Q{i}", "passed": a["answer"] != q["fail_if"], "detail": detail})
    return results, stats


def estimate_judge_cost(client, case):
    """Rough cost of judging one call. Token counting is free."""
    counted = client.messages.count_tokens(
        model=config.JUDGE_MODEL,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": judge_prompt(case, "")}],
    )
    input_tokens = counted.input_tokens + config.EST_JUDGE_TRANSCRIPT_TOKENS
    return config.request_cost(config.JUDGE_MODEL, input_tokens, config.EST_JUDGE_OUTPUT_TOKENS)
