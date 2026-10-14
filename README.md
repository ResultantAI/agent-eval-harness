# Clinic Booking Agent: Safety and Behavior Evals

## What this is

This harness tests a voice-based booking agent against safety and behavior cases: an emergency call, a mid-call switch to Spanish, an unknown insurance plan, a spouse fishing for another patient's appointment, and a prompt-injection attempt.

## Where it comes from

This is modeled on my Aria deployment for a senior-living org in Arizona, not that deployment itself. It uses synthetic data only, a made-up clinic, with no real patient data ever. The agent under test runs on Haiku, not the live model. And it is text, not voice: the real system is voice on Retell, with speech-to-text, accents, interruptions, and the like.

## How it grades

It grades in three ways. First, code checks, the mechanical half: was a tool called, did the booking happen, the exact slot booked. It is repeatable and has no judgment. Second, the judge, the meaning half: a separate, stronger model working from a written rubric, catching what code can't, like contradictions, presuppositions, made-up answers, and wrong language. Third, the quote check, the backstop: every judge answer has to quote the agent's exact words, and code verifies the quote is really in the transcript, so a made-up quote fails as a judge error instead of passing.

## The scoreboard

Here is how the scoreboard went. The baseline was 0 of 15, because every call failed to greet the caller with the disclosure check; 8 would have passed without it. It was a broken test as much as a broken agent. The next run was 11 of 15, where we added AI disclosure and took the transfer out of emergencies. On run 3 we tightened the emergency reply and the privacy refusal, but I flagged it as overstated: Case 4 still presupposed an appointment. On the regrade we saw 12 of 15, the judge only, with the agent frozen. This was the honest number, once the judge stopped grading the same behavior two ways. Then run 4, a fresh run with the agent unchanged, came in at 13 of 15, where one Case 4 call happened to word its refusal cleanly. Then run 5, the held-out set: five new cases, run once, never tuned against, and scored separately from the tuned five. I wrote my predictions down before the run: 13 of 15. It came in at 12 of 15. I was right on the first three held-out cases, scoring 3/3 for the reasons in my predictions. I was wrong on H5, because I didn't realize the agent would not be able to correct a phone number. This is a tools failure.

## Known limits

A few things I most want a reader to see. First, three runs per case is a small sample, and Case 4 can swing, so this would need more runs. Second, this is text, not voice, on Haiku, not the live model. It is a bench test, definitely not the last gate before production. Third, the agent and the judge both run on Claude models, so they could share blind spots. Fourth, the tuned five were fitted to themselves. The held-out set shows that overfitting cases to the test and agent instructions can hide actions the agent should take in real world scenarios, and that tool failures may have been hidden in my first 4 runs. Fifth, I would trust the held-out score more if it tested other languages for the switching, and tested whether a booking question instead of an insurance question would change the scoring of H5.

## Running it

### Setting your API key

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

### Commands

```
python3 run_eval.py --estimate-only          # cost estimate only, no paid calls
python3 run_eval.py --runs 3                 # play every case three times on claude-haiku-5-5
python3 regrade.py --run results/run_20261009_100609              # rerun the judge on saved transcripts, agent not called
python3 regrade.py --run results/probe_case4_20261012 --repeats 3 # grade the hand-labeled Case 4 judge probes
```

Each run writes `results/run_<timestamp>/results.json` (full transcripts, tool calls, and every check) and `results.csv` (one row per call). Each regrade writes `results/regrade_<timestamp>/regrade.json` with the before and after for every call. Both add a line to `results/costs.csv`, and both refuse to run past the total budget in `config.py`.

### Files

| File | What it is |
|---|---|
| `config.py` | Model IDs, prices, spending limits |
| `clinic_data.json` | Fictional clinic: three sites and a fake schedule |
| `agent.py` | The agent under test: system prompt, tools, fake backend |
| `checks.py` | Deterministic pass or fail checks |
| `judge.py` | The LLM judge and the quote check |
| `cases/v2_cases.json` | The five test cases, their code checks, and their judge questions |
| `cases/heldout_cases.json` | Five held-out cases, run once, never tuned against |
| `run_eval.py` | Runs cases, scores them, saves results and costs |
| `regrade.py` | Reruns the judge on saved transcripts without calling the agent |
| `probes/make_case4_probes.py` | Builds hand-edited Case 4 transcripts, labeled before grading, to test the judge |
| `results/` | Every run, regrade, and probe set, plus `costs.csv` |
| `predictions/` | My predictions, committed before each run |
| `findings/` | My view after each run, in my own words |
| `run5_transcripts.md` | All 15 held-out calls in one document |
| `STATUS.md` | Current state, scoreboard, and open items for the next session |
