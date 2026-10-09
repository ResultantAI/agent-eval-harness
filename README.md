# Agent Eval Harness: Clinic Booking Agent

Status: v1. 10 test cases, one model, deterministic checks only. The full README (problem, results table, lessons) comes after v2.

The idea: every time the model under your agent changes, rerun the tests and see what moved.

## Setting your API key

The harness reads `ANTHROPIC_API_KEY` from your environment. It never prints it. Do not paste your key into chat or into any file in this folder.

The safest way on a Mac is to store the key in Keychain:

1. In Terminal, run this. It will prompt for the key, and what you paste will not show on screen or go into your shell history:
   ```
   security add-generic-password -a "$USER" -s anthropic-api-key -w
   ```
2. Add this line to the end of `~/.zshrc` so every new Terminal loads the key from Keychain:
   ```
   export ANTHROPIC_API_KEY="$(security find-generic-password -a "$USER" -s anthropic-api-key -w)"
   ```
3. Open a new Terminal window (or run `source ~/.zshrc`).

## Running it

```
python3 run_eval.py --estimate-only   # cost estimate only, no paid calls
python3 run_eval.py                   # run all v1 cases on claude-haiku-5-5
```

Each run writes `results/run_<timestamp>/results.json` (full transcripts and tool calls) and `results.csv` (one row per case), and adds a line to `results/costs.csv`.

## Files

| File | What it is |
|---|---|
| `config.py` | Model IDs, prices, spending limits |
| `clinic_data.json` | Fictional clinic: three sites and a fake schedule |
| `agent.py` | The agent under test: system prompt, three tools, fake backend |
| `checks.py` | Deterministic pass or fail checks |
| `cases/v1_cases.json` | The 10 test cases |
| `run_eval.py` | Runs cases, scores them, saves results and costs |

All data is synthetic. No real clinic, patient, or phone number appears anywhere.
