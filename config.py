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


def request_cost(model, input_tokens, output_tokens):
    """Dollar cost of one API request."""
    price = PRICES[model]
    if "long_threshold" in price and input_tokens > price["long_threshold"]:
        input_rate, output_rate = price["long_input"], price["long_output"]
    else:
        input_rate, output_rate = price["input"], price["output"]
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
