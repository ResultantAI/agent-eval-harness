"""The do-nothing agent (Test 2): a floor, not a real agent.

It gives one fixed English reply on every turn, including the greeting. It says it is an AI,
tells the caller to call 911 or call back during office hours, and never calls a tool.
It makes no decisions and no API calls. Its score is the highest that pure do-no-harm can reach.

Used only by run_eval.py --agent do_nothing. The real agent in agent.py is not touched.
"""

# Used in place of a model ID in results and in results/costs.csv, so a do-nothing run
# can never be mistaken for a real agent run.
LABEL = "do_nothing_agent"

REPLY = ("Hi, this is the clinic's automated AI assistant, not a person. If this is an emergency, "
         "hang up and call 911. Otherwise, please call back during office hours.")


def reply(line):
    """Return the fixed reply, whatever the caller said. No tool calls, no API calls."""
    return REPLY
