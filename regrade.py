"""Regrade saved calls with the current judge. The agent is never called.

This answers one question: did a judge change move the score? The transcripts are frozen,
so the agent cannot have moved it.

Usage:
  python3 regrade.py --run results/run_20261009_100609 --estimate-only
  python3 regrade.py --run results/run_20261009_100609
  python3 regrade.py --run results/run_20261009_084704 --case emergency_01_chest_arm --repeats 3

What happens, in order:
  1. Load the saved calls from <run>/results.json and the current cases file.
  2. Estimate the judge cost. Stop if it would push total spend past the budget.
  3. For each saved call (and each repeat), rerun the code checks on the saved tool calls and
     transcript (no API), then rerun the judge on the saved transcript (one API request).
  4. Print before and after per call and per case, save regrade.json in
     results/regrade_<timestamp>/, and add a line to results/costs.csv.
"""

import argparse
import json
import os
import sys
from datetime import datetime

import checks
import config
import judge
from run_eval import load_cases, log_cost, require_api_key, spent_so_far


def load_saved(run_dir, case_filter):
    with open(os.path.join(run_dir, "results.json"), encoding="utf-8") as f:
        saved = json.load(f)
    if case_filter:
        saved = [r for r in saved if r["case_id"] == case_filter]
    if not saved:
        sys.exit(f"No saved calls in {run_dir} match case '{case_filter}'.")
    return saved


def regrade_call(client, case, old):
    transcript = old["transcript"]
    agent_text = "\n".join(text for speaker, text in transcript if speaker == "agent")
    code_results = checks.run_checks(case, old["tool_calls"], agent_text, transcript)
    old_code = [c for c in old["checks"] if not c["check"].startswith("judge")]
    code_changed = [c["check"] for c, o in zip(code_results, old_code) if c["passed"] != o["passed"]]
    judge_results, stats = judge.judge_call(client, case, transcript)
    after = code_results + judge_results
    return {
        "case_id": old["case_id"],
        "run": old["run"],
        "before_passed": old["passed"],
        "after_passed": all(c["passed"] for c in after),
        "code_checks_changed": code_changed,
        "before_checks": old["checks"],
        "after_checks": after,
        "transcript": transcript,
        "tool_calls": old["tool_calls"],
        **stats,
    }


def changed_judge_checks(r):
    before = {c["check"]: c for c in r["before_checks"] if c["check"].startswith("judge")}
    out = []
    for c in r["after_checks"]:
        b = before.get(c["check"])
        if c["check"].startswith("judge") and b is not None and b["passed"] != c["passed"]:
            out.append((c["check"], b, c))
    return out


def print_report(results):
    print()
    for r in results:
        b = "PASS" if r["before_passed"] else "FAIL"
        a = "PASS" if r["after_passed"] else "FAIL"
        print(f"{r['case_id']:<32} run {r['run']} repeat {r['repeat']}  before {b}  after {a}"
              f"  judge ${r['judge_cost_usd']:.4f}")
        if r["code_checks_changed"]:
            print(f"        WARNING: code checks changed on frozen input: {r['code_checks_changed']}")
        for name, before, after in changed_judge_checks(r):
            print(f"        {name} flipped {'PASS' if before['passed'] else 'FAIL'} -> "
                  f"{'PASS' if after['passed'] else 'FAIL'}: {after['detail']}")
    print("\nPasses per case (before -> after):")
    for case_id in dict.fromkeys(r["case_id"] for r in results):
        rows = [r for r in results if r["case_id"] == case_id]
        print(f"  {case_id:<32} {sum(r['before_passed'] for r in rows)}/{len(rows)} -> "
              f"{sum(r['after_passed'] for r in rows)}/{len(rows)}")
        names = [c["check"] for c in rows[0]["after_checks"] if c["check"].startswith("judge")]
        for name in names:
            b = sum(next(c["passed"] for c in r["before_checks"] if c["check"] == name) for r in rows)
            a = sum(next(c["passed"] for c in r["after_checks"] if c["check"] == name) for r in rows)
            if a != b:
                print(f"      {name}: passed {b}/{len(rows)} -> {a}/{len(rows)}")
    print(f"  {'TOTAL':<32} {sum(r['before_passed'] for r in results)}/{len(results)} -> "
          f"{sum(r['after_passed'] for r in results)}/{len(results)}")


def main():
    parser = argparse.ArgumentParser(description="Regrade saved calls with the current judge.")
    parser.add_argument("--run", required=True, help="A results/run_<timestamp> folder.")
    parser.add_argument("--cases", default="cases/v2_cases.json")
    parser.add_argument("--case", help="Only regrade this case id.")
    parser.add_argument("--repeats", type=int, default=1, help="Judge each saved call this many times.")
    parser.add_argument("--estimate-only", action="store_true", help="Print the estimate and stop.")
    args = parser.parse_args()

    cases = {c["id"]: c for c in load_cases(args.cases)}
    saved = load_saved(args.run, args.case)
    missing = sorted({r["case_id"] for r in saved} - cases.keys())
    if missing:
        sys.exit(f"Saved calls use case ids not in {args.cases}: {missing}")

    require_api_key()
    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    per_case = {cid: judge.estimate_judge_cost(client, cases[cid]) for cid in {r["case_id"] for r in saved}}
    estimate = sum(per_case[r["case_id"]] for r in saved) * args.repeats
    spent = spent_so_far()
    print(f"Regrading {len(saved)} saved calls from {args.run}, {args.repeats} time(s) each. Agent not called.")
    print(f"Judge: {config.JUDGE_MODEL} (effort {config.JUDGE_EFFORT})")
    print(f"Estimated judge cost: ${estimate:.4f}   Spent so far: ${spent:.4f} of ${config.TOTAL_BUDGET_USD:.2f}")
    if args.estimate_only:
        return
    if spent + estimate > config.TOTAL_BUDGET_USD:
        sys.exit("This regrade could push total spend past the budget. Stopping.")

    results = []
    for repeat in range(1, args.repeats + 1):
        for old in saved:
            print(f"Regrading {old['case_id']} (run {old['run']}, repeat {repeat}) ...", flush=True)
            r = regrade_call(client, cases[old["case_id"]], old)
            r["repeat"] = repeat
            results.append(r)

    regrade_id = datetime.now().strftime("regrade_%Y%m%d_%H%M%S")
    out_dir = os.path.join("results", regrade_id)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "regrade.json"), "w", encoding="utf-8") as f:
        json.dump({"source_run": args.run, "cases_file": args.cases, "repeats": args.repeats,
                   "results": results}, f, indent=2, ensure_ascii=False)
    actual = sum(r["judge_cost_usd"] for r in results)
    log_cost(regrade_id, f"judge-only {config.JUDGE_MODEL}", len(results), estimate, actual)

    print_report(results)
    print(f"\nActual judge cost: ${actual:.4f} (estimated ${estimate:.4f})")
    print(f"Saved to {out_dir}/")


if __name__ == "__main__":
    main()
