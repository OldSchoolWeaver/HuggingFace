"""Evaluate the Voltway data agent against evals/dataset.jsonl.

  uv run python evals/run_evals.py              # LangSmith experiment (needs LANGSMITH_API_KEY)
  uv run python evals/run_evals.py --offline    # local run: prints scores, saves evals/results/<run>.json

Flags: --ids fleet_size,q1_distance   --limit 3   --judge (adds an LLM-as-judge score)

Evaluators (0-1, or None when they don't apply). All take (inputs, outputs, reference_outputs), as LangSmith passes them:
  route_correct        the router picked the expected layer (cube / datahub / direct)
  first_layer_correct  the first tool the agent called belongs to that layer
  facts                share of the expected facts (numbers within tolerance, or regex patterns) in the answer
  no_forbidden         nothing that must not appear (e.g. email addresses) appears in the answer
  no_tool_errors       no tool call failed
  judge (--judge)      an LLM grades the answer against the reference answer
"""

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from data_agent import AGENT_MODEL, ROUTER_MODEL, DataAgent  # noqa: E402  (also loads the .env files)

DATASET_NAME = "voltway-data-agent-evals"
NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")


# ---------------------------------------------------------------- evaluators
#
# Every evaluator gets the same three arguments (LangSmith passes them by these names):
#   inputs             {"question": "How many vehicles are in service right now?"}
#   outputs            what DataAgent.run() returned:
#                      {"answer": "37 vehicles are active ...", "route": "cube", "route_reason": "...",
#                       "tool_calls": [{"name": "cube_meta", "server": "cube", "args": {}}, ...],
#                       "sql": [...], "tool_errors": []}
#   reference_outputs  the example's line in dataset.jsonl:
#                      {"id": "fleet_size", "expected_route": "cube", "facts": [...], "must_not_contain": [],
#                       "reference": "37 vehicles are active ..."}
# and returns one score:
#   {"key": "<name of the score>", "score": 1 | 0 | 0.5 ... | None, "comment": "why"}
# score None means "doesn't apply to this example": it's left out of the averages.

def fact_found(fact: dict, answer: str) -> bool:
    """Does the answer contain this one expected fact?

    A fact is one of two shapes (written in dataset.jsonl):
      {"pattern": "bodywork"}                    a regex, searched anywhere in the answer, ignoring case
      {"numbers": [0.148, 14.8], "abs": 0.002}   any of these numbers, within a fixed (abs) or relative (rel)
                                                 margin, e.g. "rel": 0.003 means +-0.3%

    Returns True or False, e.g.
      fact_found({"numbers": [15.74], "abs": 0.06}, "The e-208 uses 15.7 kWh/100 km")  -> True   (15.7 is 0.04 away)
      fact_found({"numbers": [15.74], "abs": 0.06}, "The e-208 uses 16 kWh/100 km")    -> False  (16 is 0.26 away)
      fact_found({"pattern": "e-?208"}, "The Peugeot E208 ...")                        -> True
    """
    if "pattern" in fact:
        return re.search(fact["pattern"], answer, re.IGNORECASE) is not None
    # Every number in the answer as a float: "drove 133,697.2 km in Q1" -> [133697.2, 1.0]
    found = [float(n.replace(",", "").replace(" ", "")) for n in NUMBER.findall(answer)]
    for expected in fact["numbers"]:
        tolerance = fact.get("abs", abs(expected) * fact.get("rel", 0.0))
        if any(abs(value - expected) <= tolerance + 1e-9 for value in found):
            return True
    return False


def route_correct(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """Did the router send the question to the expected layer?

    1 if the route matches, 0 if not, None if the example has no expected route (no_driver_emails).
      expected "cube", got "cube"     -> {"key": "route_correct", "score": 1, "comment": "expected cube, got cube"}
      expected "datahub", got "cube"  -> {"key": "route_correct", "score": 0, "comment": "expected datahub, got cube"}
    """
    expected, got = reference_outputs["expected_route"], outputs.get("route")
    score = None if expected is None else int(got == expected)
    return {"key": "route_correct", "score": score, "comment": f"expected {expected}, got {got}"}


def first_layer_correct(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """Did the first tool the agent called come from the expected layer's MCP server?

    Only scored when the expected route is cube or datahub (direct questions may use no tools at all).
      first call cube_meta (server "cube"), expected cube  -> {"score": 1, "comment": "first tool from: cube"}
      no tool calls, expected datahub                      -> {"score": 0, "comment": "first tool from: None"}
    """
    expected = reference_outputs["expected_route"]
    first = (outputs.get("tool_calls") or [{}])[0].get("server")  # None when the agent called no tool
    score = int(first == expected) if expected in ("cube", "datahub") else None
    return {"key": "first_layer_correct", "score": score, "comment": f"first tool from: {first}"}


def facts(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """Which share of the expected facts appears in the answer? (see fact_found)

    For most_efficient_model, facts = [{"pattern": "e-?208"}, {"numbers": [15.74], "abs": 0.06}]:
      "The Peugeot e-208, at 15.7 kWh/100 km"  -> {"score": 1.0, "comment": "missing: []"}
      "The Peugeot e-208, about 16 kWh/100 km" -> {"score": 0.5, "comment": "missing: [{'numbers': [15.74], ...}]"}
    None when the example lists no facts (e.g. the greeting).
    """
    expected = reference_outputs["facts"]
    missing = [f for f in expected if not fact_found(f, outputs.get("answer") or "")]
    score = 1 - len(missing) / len(expected) if expected else None
    return {"key": "facts", "score": score, "comment": f"missing: {missing}"}


def no_forbidden(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """Is the answer free of everything in must_not_contain (e.g. an email-address regex)?

      "Emails are personal data, so I can't list them"  -> {"score": 1, "comment": "matched: []"}
      "ana.silva@voltway.pt, ..."                       -> {"score": 0, "comment": "matched: ['[\\w.+-]+@...']"}
    """
    hits = [p for p in reference_outputs["must_not_contain"] if re.search(p, outputs.get("answer") or "", re.I)]
    return {"key": "no_forbidden", "score": int(not hits), "comment": f"matched: {hits}"}


def no_tool_errors(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """Did every tool call succeed? Failed calls are sent back to the model to retry, so the answer can still be
    right, but each one costs time and tokens and usually means a bad query or a confusing tool description.

      no errors              -> {"score": 1, "comment": "[]"}
      a DuckDB syntax error  -> {"score": 0, "comment": "[{'name': 'execute_query', 'error': 'Parser Error: ...'}]"}
    """
    errors = outputs.get("tool_errors") or []
    return {"key": "no_tool_errors", "score": int(not errors), "comment": str(errors)[:500]}


def make_judge():
    """Build the optional LLM-as-judge evaluator (only with --judge).

    Returns a judge(inputs, outputs, reference_outputs) function like the evaluators above. It asks JUDGE_MODEL
    to compare the answer with the example's reference answer, and returns e.g.
      {"key": "judge", "score": 0.5, "comment": "Names the right model but gives 16 instead of about 15.7."}
    The models and imports are only loaded here, so runs without --judge don't need them.
    """
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel, Field

    class Grade(BaseModel):
        score: float = Field(description="1.0 correct and complete, 0.5 partly correct, 0.0 wrong or missing")
        reasoning: str = Field(description="One or two sentences")

    grader = ChatOpenAI(model=os.getenv("JUDGE_MODEL", "gpt-4o-mini"), temperature=0).with_structured_output(Grade)

    def judge(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        grade = grader.invoke(
            "Grade a data analyst agent's answer against the reference answer. Rounding and extra correct detail "
            "are fine. For guardrail examples, grade whether it behaved as the reference says.\n\n"
            f"Question: {inputs['question']}\nReference: {reference_outputs['reference']}\nAnswer: {outputs.get('answer')}")
        return {"key": "judge", "score": grade.score, "comment": grade.reasoning}

    return judge


# ---------------------------------------------------------------- run

async def main():
    """Read the flags, load the examples, start the agent once, and run them offline or in LangSmith.

    Prints the agent and router models and the number of examples, then whatever run_offline or run_langsmith
    prints. Example: python evals/run_evals.py --offline --ids fleet_size,q1_distance
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="run locally, without LangSmith")
    parser.add_argument("--judge", action="store_true", help="add the LLM-as-judge evaluator (JUDGE_MODEL)")
    parser.add_argument("--ids", help="comma-separated example ids")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    # One example per line of dataset.jsonl, optionally narrowed by --ids and --limit.
    cases = [json.loads(line) for line in (HERE / "dataset.jsonl").read_text().splitlines() if line.strip()]
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids.split(",")]
    cases = cases[:args.limit]
    evaluators = [route_correct, first_layer_correct, facts, no_forbidden, no_tool_errors]
    if args.judge:
        evaluators.append(make_judge())
    run_tag = f"voltway-{datetime.now():%Y%m%d-%H%M%S}"  # tags this run's traces, and names the offline results file

    # Each example runs in a fresh, throwaway thread: no need to save them in the agent_state database.
    async with DataAgent(checkpointer="memory") as agent:
        async def target(inputs: dict) -> dict:
            """Ask the agent one question. {"question": ...} -> the outputs dict the evaluators receive.
            A fresh thread per example, so no example sees another's conversation."""
            return await agent.run(inputs["question"], thread_id=f"eval-{uuid.uuid4().hex[:8]}",
                                   tags=["eval", run_tag])

        print(f"Agent {AGENT_MODEL}, router {ROUTER_MODEL}, {len(cases)} examples\n")
        if args.offline:
            await run_offline(target, cases, evaluators, run_tag)
        else:
            await run_langsmith(target, cases, evaluators)


async def run_langsmith(target, cases: list[dict], evaluators: list):
    """Run the examples as one LangSmith experiment.

    1. Make sure the dataset "voltway-data-agent-evals" exists and has every example in the file (new ones are
       added, matched by id; nothing is deleted or updated).
    2. Run aevaluate: for each example it calls target(), then every evaluator, and uploads the scores.
    Output: a new experiment "voltway-<suffix>" on the dataset's page in LangSmith, one row per example and one
    column per score key, each row linked to its full trace. The terminal shows a progress bar and the link.
    """
    from langsmith import Client
    from langsmith.evaluation import aevaluate

    client = Client()
    # Create the dataset the first time, and add examples the file has but the dataset doesn't (matched by id).
    if not client.has_dataset(dataset_name=DATASET_NAME):
        client.create_dataset(DATASET_NAME)
    existing = {ex.metadata.get("case_id"): ex for ex in client.list_examples(dataset_name=DATASET_NAME)}
    new = [c for c in cases if c["id"] not in existing]
    if new:
        client.create_examples(dataset_name=DATASET_NAME, examples=[
            {"inputs": {"question": c["question"]}, "outputs": c, "metadata": {"case_id": c["id"]}} for c in new])
        existing = {ex.metadata.get("case_id"): ex for ex in client.list_examples(dataset_name=DATASET_NAME)}

    await aevaluate(
        target,
        data=[existing[c["id"]] for c in cases],
        evaluators=evaluators,
        experiment_prefix="voltway",
        metadata={"agent_model": AGENT_MODEL, "router_model": ROUTER_MODEL},
        max_concurrency=1,  # the MCP sessions are shared, so examples run one after another
        client=client,
    )


async def run_offline(target, cases: list[dict], evaluators: list, run_tag: str):
    """Run the examples locally, without LangSmith experiments (traces are still sent if tracing is on).

    Prints one line per example, then the average of each score over the examples it applies to:
      fleet_size               route=cube     route_correct=1  first_layer_correct=1  facts=1.0  no_forbidden=1  ...
      no_driver_emails         route=direct   route_correct=None  first_layer_correct=None  facts=None  no_forbidden=1 ...

      Averages
        route_correct        0.94 (n=17)
        facts                0.88 (n=16)
    and saves every answer, tool call and score to evals/results/<run_tag>.json.
    """
    rows = []
    for case in cases:
        inputs = {"question": case["question"]}
        outputs = await target(inputs)
        scores = [evaluate(inputs, outputs, case) for evaluate in evaluators]
        rows.append({"id": case["id"], "outputs": outputs, "scores": scores})
        print(f"{case['id']:<24} route={outputs['route']!s:<8} " + "  ".join(f"{s['key']}={s['score']}" for s in scores))

    print("\nAverages")
    for key in [s["key"] for s in rows[0]["scores"]]:
        values = [s["score"] for row in rows for s in row["scores"] if s["key"] == key and s["score"] is not None]
        print(f"  {key:<20} {sum(values) / len(values):.2f} (n={len(values)})" if values else f"  {key:<20} -")

    out_file = HERE / "results" / f"{run_tag}.json"
    out_file.parent.mkdir(exist_ok=True)
    out_file.write_text(json.dumps(rows, indent=2, default=str))
    print(f"\nSaved {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
