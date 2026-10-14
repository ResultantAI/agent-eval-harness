"""Run the test cases against one Claude model, score them, and save the results.

Usage:
  python3 run_eval.py --estimate-only          # show the cost estimate, make no paid calls
  python3 run_eval.py                          # run all cases on the default model
  python3 run_eval.py --model claude-sonnet-5-5
  python3 run_eval.py --runs 3                 # play every case three times
  python3 run_eval.py --agent do_nothing --runs 3   # Test 2: fixed-reply floor on the tuned five, judge still paid

What happens, in order:
  1. Stop if ANTHROPIC_API_KEY is not set.
  2. Estimate the cost of the run. Stop if it is over the per-run limit (unless --approved)
     or would push total spend past the overall budget.
  3. For each test case, play the scripted caller turns to the agent, letting it call tools.
  4. Score each finished call with the deterministic checks, then with the LLM judge (judge.py).
  5. Save results.json and results.csv, and add a line to results/costs.csv.
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

import anthropic

import agent
import checks
import config
import do_nothing_agent
import judge


def require_api_key():
    """Stop with setup instructions if the key is missing. Never prints the key."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set, so no API calls were made.")
        print("See 'Setting your API key' in README.md for how to set it in Terminal.")
        sys.exit(1)


def load_cases(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def spent_so_far():
    """Total dollars recorded in results/costs.csv across all previous runs."""
    if not os.path.exists(config.COSTS_LOG):
        return 0.0
    with open(config.COSTS_LOG, encoding="utf-8") as f:
        return sum(float(row["actual_usd"]) for row in csv.DictReader(f))


def estimate_cost(client, model, cases):
    """Rough cost estimate before spending anything.

    We ask the API to count the tokens in the system prompt, tool definitions, and the
    caller's lines (token counting is free). Then we assume one call for the greeting, about
    two model calls per caller turn (one to use a tool, one to reply), that each call resends the growing conversation,
    and that each reply is EST_OUTPUT_TOKENS_PER_CALL tokens long.
    """
    total = 0.0
    for case in cases:
        counted = client.messages.count_tokens(
            model=model,
            system=agent.SYSTEM_PROMPT,
            tools=agent.TOOLS,
            messages=[{"role": "user", "content": "\n".join(case["caller_turns"])}],
        )
        calls = 2 * len(case["caller_turns"]) + 1  # plus one for the greeting
        for k in range(calls):
            input_tokens = counted.input_tokens + k * config.EST_HISTORY_GROWTH_PER_CALL
            total += config.request_cost(model, input_tokens, config.EST_OUTPUT_TOKENS_PER_CALL)
    return total


def run_case(client, model, case, run_number):
    """Play one scripted call and record everything that happened."""
    clinic = agent.fresh_clinic()
    messages = []      # the conversation as the API sees it
    transcript = []    # a readable version for humans: (speaker, text)
    tool_calls = []    # every tool call with its input and our fake backend's output
    stats = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "cost_usd": 0.0, "latency_s": 0.0, "stop_reasons": []}
    call_ended = False

    # The first "turn" is the harness connecting the call, so the agent greets before the caller speaks.
    turns = [("harness", agent.CALL_CONNECTED)] + [("caller", line) for line in case["caller_turns"]]
    for speaker, line in turns:
        if call_ended:
            break  # after a transfer, the remaining scripted lines are never heard
        messages.append({"role": "user", "content": line})
        transcript.append([speaker, line])

        # Keep calling the model until it stops asking to use tools and just speaks.
        while True:
            if stats["api_calls"] >= config.MAX_API_CALLS_PER_CASE:
                transcript.append(["harness", "stopped: too many API calls in one case"])
                call_ended = True
                break

            start = time.perf_counter()
            response = client.messages.create(
                model=model,
                max_tokens=config.MAX_TOKENS,
                system=agent.SYSTEM_PROMPT,
                tools=agent.TOOLS,
                messages=messages,
            )
            stats["latency_s"] += time.perf_counter() - start
            stats["api_calls"] += 1
            stats["input_tokens"] += response.usage.input_tokens
            stats["output_tokens"] += response.usage.output_tokens
            stats["cost_usd"] += config.request_cost(
                model, response.usage.input_tokens, response.usage.output_tokens)
            stats["stop_reasons"].append(response.stop_reason)

            # Send the model's full reply back next time, unchanged (including its thinking).
            messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "text" and block.text.strip():
                    transcript.append(["agent", block.text.strip()])

            if response.stop_reason != "tool_use":
                break  # the agent finished speaking; next caller line

            # The agent asked to use one or more tools. Run them on our fake backend.
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output = agent.run_tool(block.name, block.input, clinic)
                tool_calls.append({"name": block.name, "input": block.input, "output": output})
                transcript.append(["tool", f"{block.name}({json.dumps(block.input, ensure_ascii=False)}) -> "
                                           f"{json.dumps(output, ensure_ascii=False)}"])
                tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                     "content": json.dumps(output, ensure_ascii=False)})
                if block.name == "transfer_to_human":
                    call_ended = True
            messages.append({"role": "user", "content": tool_results})

    return finish_call(client, model, case, run_number, transcript, tool_calls, stats)


def run_do_nothing_case(client, case, run_number):
    """Play one scripted call to the do-nothing agent: the same fixed reply every turn, no tools.

    No agent API calls, so the agent cost is zero. The call is still graded by the same code
    checks and the same judge as the real agent, and the judge is still a paid call.
    """
    transcript = []
    stats = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "cost_usd": 0.0, "latency_s": 0.0, "stop_reasons": []}
    turns = [("harness", agent.CALL_CONNECTED)] + [("caller", line) for line in case["caller_turns"]]
    for speaker, line in turns:
        transcript.append([speaker, line])
        transcript.append(["agent", do_nothing_agent.reply(line)])
    return finish_call(client, do_nothing_agent.LABEL, case, run_number, transcript, [], stats)


def finish_call(client, model, case, run_number, transcript, tool_calls, stats):
    """Score a finished call with the code checks and the judge, and build its result."""
    agent_text = "\n".join(text for speaker, text in transcript if speaker == "agent")
    check_results = checks.run_checks(case, tool_calls, agent_text, transcript)
    judge_results, judge_stats = judge.judge_call(client, case, transcript)
    check_results += judge_results
    result = {
        "case_id": case["id"],
        "run": run_number,
        "category": case["category"],
        "model": model,
        "judge_model": config.JUDGE_MODEL,
        "passed": all(c["passed"] for c in check_results),
        "checks": check_results,
        "transcript": transcript,
        "tool_calls": tool_calls,
        **stats,
        **judge_stats,
    }
    if case.get("notes"):  # ungraded; only cases that list notes get this key
        result["notes"] = checks.run_notes(case, transcript)
    return result


def save_results(run_dir, results):
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    with open(os.path.join(run_dir, "results.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "run", "category", "model", "passed", "failed_checks",
                         "api_calls", "input_tokens", "output_tokens", "cost_usd",
                         "judge_cost_usd", "latency_s"])
        for r in results:
            failed = "; ".join(f"{c['check']}: {c['detail']}" for c in r["checks"] if not c["passed"])
            writer.writerow([r["case_id"], r["run"], r["category"], r["model"], r["passed"], failed,
                             r["api_calls"], r["input_tokens"], r["output_tokens"],
                             f"{r['cost_usd']:.6f}", f"{r['judge_cost_usd']:.6f}", f"{r['latency_s']:.2f}"])


def log_cost(run_id, model, num_cases, estimated, actual):
    is_new = not os.path.exists(config.COSTS_LOG)
    cumulative = spent_so_far() + actual
    with open(config.COSTS_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "run_id", "model", "cases",
                             "estimated_usd", "actual_usd", "cumulative_usd"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), run_id, model, num_cases,
                         f"{estimated:.4f}", f"{actual:.4f}", f"{cumulative:.4f}"])


def print_summary(results):
    print()
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{status}  {r['case_id']:<32} run {r['run']}  "
              f"agent ${r['cost_usd']:.4f}  judge ${r['judge_cost_usd']:.4f}  {r['latency_s']:.1f}s")
        for c in r["checks"]:
            if not c["passed"]:
                print(f"        {c['check']}: {c['detail']}")
        for n in r.get("notes", []):
            print(f"        note (ungraded) {n['note']}: {'yes' if n['found'] else 'no'}, {n['detail']}")

    print("\nPasses per case, across runs:")
    for case_id in dict.fromkeys(r["case_id"] for r in results):
        runs = [r for r in results if r["case_id"] == case_id]
        print(f"  {case_id:<32} {sum(r['passed'] for r in runs)}/{len(runs)}")

    print("\nPass rate by category:")
    categories = sorted({r["category"] for r in results})
    for cat in categories:
        in_cat = [r for r in results if r["category"] == cat]
        passed = sum(r["passed"] for r in in_cat)
        print(f"  {cat:<22} {passed}/{len(in_cat)}")
    total_passed = sum(r["passed"] for r in results)
    print(f"  {'TOTAL':<22} {total_passed}/{len(results)}")


def main():
    parser = argparse.ArgumentParser(description="Run the clinic booking agent eval.")
    parser.add_argument("--model", default=config.DEFAULT_MODEL)
    parser.add_argument("--agent", choices=["real", "do_nothing"], default="real",
                        help="real: the agent in agent.py. do_nothing: the fixed-reply floor (Test 2), "
                             "tuned five only.")
    parser.add_argument("--cases", default="cases/v2_cases.json")
    parser.add_argument("--runs", type=int, default=1, help="How many times to play each case.")
    parser.add_argument("--estimate-only", action="store_true",
                        help="Print the cost estimate and stop. No paid calls.")
    parser.add_argument("--approved", action="store_true",
                        help=f"Allow a run estimated above ${config.RUN_APPROVAL_LIMIT_USD:.0f}.")
    args = parser.parse_args()

    if args.model not in config.PRICES:
        sys.exit(f"{args.model} is not in config.PRICES. Verify its ID and price first.")
    do_nothing = args.agent == "do_nothing"
    if do_nothing and args.cases != "cases/v2_cases.json":
        sys.exit("The do-nothing agent runs on the tuned five only (cases/v2_cases.json).")

    require_api_key()
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    cases = load_cases(args.cases)

    agent_estimate = 0.0 if do_nothing else estimate_cost(client, args.model, cases) * args.runs
    judge_estimate = sum(judge.estimate_judge_cost(client, c) for c in cases) * args.runs
    estimate = agent_estimate + judge_estimate
    spent = spent_so_far()
    agent_label = do_nothing_agent.LABEL if do_nothing else args.model
    if do_nothing:
        print("Agent: DO-NOTHING (Test 2), fixed reply, no tools, no agent API calls")
    print(f"Model: {agent_label}   Judge: {config.JUDGE_MODEL} (effort {config.JUDGE_EFFORT})")
    print(f"Cases: {len(cases)}   Runs each: {args.runs}   Calls: {len(cases) * args.runs}")
    print(f"Estimated agent cost: ${agent_estimate:.4f}")
    print(f"Estimated judge cost: ${judge_estimate:.4f}")
    print(f"Estimated cost of this run: ${estimate:.4f}")
    print(f"Spent so far: ${spent:.4f} of ${config.TOTAL_BUDGET_USD:.2f} budget")

    if args.estimate_only:
        return
    if estimate > config.RUN_APPROVAL_LIMIT_USD and not args.approved:
        sys.exit(f"Estimate is over ${config.RUN_APPROVAL_LIMIT_USD:.2f}. Rerun with --approved once approved.")
    if spent + estimate > config.TOTAL_BUDGET_USD:
        sys.exit("This run could push total spend past the budget. Stopping.")

    # Do-nothing runs get their own prefix so they never sort or read as a real agent run.
    run_id = datetime.now().strftime("donothing_%Y%m%d_%H%M%S" if do_nothing else "run_%Y%m%d_%H%M%S")
    results = []
    for run_number in range(1, args.runs + 1):
        for case in cases:
            print(f"Running {case['id']} (run {run_number}) ...", flush=True)
            if do_nothing:
                results.append(run_do_nothing_case(client, case, run_number))
            else:
                results.append(run_case(client, args.model, case, run_number))

    actual = sum(r["cost_usd"] + r["judge_cost_usd"] for r in results)
    run_dir = os.path.join("results", run_id)
    save_results(run_dir, results)
    log_cost(run_id, agent_label, len(results), estimate, actual)

    print_summary(results)
    agent_actual = sum(r["cost_usd"] for r in results)
    print(f"\nActual cost: ${actual:.4f} (agent ${agent_actual:.4f}, judge ${actual - agent_actual:.4f}; "
          f"estimated ${estimate:.4f})")
    print(f"Saved to {run_dir}/")


if __name__ == "__main__":
    main()
