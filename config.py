"""Settings for the eval harness: which models, what they cost, and spending limits.

Model IDs and prices were checked on 2026-10-08 against:
  https://platform.claude.com/docs/en/about-claude/models/overview
  https://platform.claude.com/docs/en/about-claude/pricing
If Anthropic releases a new model or changes prices, update this file first.
"""

# The three model sizes we compare. v1 only uses the small one.
MODELS = {
    "small": "claude-haiku-5-5",
    "mid": "claude-sonnet-5-5",
    "large": "claude-opus-5-5",
}

DEFAULT_MODEL = MODELS["small"]

# Price in US dollars per 1 million tokens.
# Haiku 5.5 costs more when a single request's prompt is over 100,000 tokens.
# Our prompts are a few thousand tokens, but we handle it anyway so the math stays honest.
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50,
                         "long_input": 0.50, "long_output": 2.50, "long_threshold": 100_000},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
}

# Spending guardrails (from the project rules).
RUN_APPROVAL_LIMIT_USD = 10.00   # a single run estimated above this needs --approved
TOTAL_BUDGET_USD = 100.00        # the harness refuses to run past this total

# Per-request settings for the agent under test.
MAX_TOKENS = 4000                # cap on one reply (includes the model's thinking)
MAX_API_CALLS_PER_CASE = 20      # safety stop in case an agent loops on tool calls

# Assumptions used only for the cost estimate before a run.
EST_OUTPUT_TOKENS_PER_CALL = 800     # thinking plus spoken reply, rounded up
EST_HISTORY_GROWTH_PER_CALL = 500    # each call resends the conversation so far

COSTS_LOG = "results/costs.csv"

# The LLM judge. Fixed to Opus, whatever model is under test, so no model grades itself.
# Opus 5.5 always thinks (it cannot be turned off) and does not accept temperature,
# so the judge is not fully repeatable. Every answer must quote the transcript, and code
# checks that the quote is really there.
JUDGE_MODEL = "claude-opus-5-5"
JUDGE_EFFORT = "high"            # how hard it thinks; Opus 5.5 defaults to "medium"
JUDGE_MAX_TOKENS = 16000

# Assumptions used only for the judge's cost estimate.
EST_JUDGE_TRANSCRIPT_TOKENS = 1500   # a short call, with tool results, as the judge sees it
EST_JUDGE_OUTPUT_TOKENS = 3000       # thinking plus a quote and reason per question, rounded up


def request_cost(model, input_tokens, output_tokens):
    """Dollar cost of one API request."""
    price = PRICES[model]
    if "long_threshold" in price and input_tokens > price["long_threshold"]:
        input_rate, output_rate = price["long_input"], price["long_output"]
    else:
        input_rate, output_rate = price["input"], price["output"]
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
