"""Calibrate the citation_support judge against hand labels.

The calibration dataset, `judge-calibration/citation-support`, holds the 30 hand-labeled
claims from evals/labels plus built failure cases: supported claims changed so their
label is unsupported by construction. Each item's input is exactly what the judge sees;
its expected output is the label, in the judge's own vocabulary.

    uv run python -m evals.calibrate upload
    uv run python -m evals.calibrate run <prompt-version>

A judge is ready at about 85% agreement, and only if every label clears that bar too.
"""

import argparse
import json
import re
from collections import Counter

from langfuse import Evaluation

from evals.judges import get_judge_prompt, judge_claim
from evals.labeling import LABELS_DIR
from evals.preflight import require_openai_key
from research_agent.tracing import get_langfuse

JUDGE = "citation-support"
DATASET_NAME = f"judge-calibration/{JUDGE}"

# Built failures: (id, hand-labeled claim it starts from, failure type, new claim text,
# claim whose sources to cite instead, or None to keep the original sources).
BUILT_CASES = [
    (
        "X01",
        "C04",
        "number",
        "In terms of maintenance, heat pumps have lower average annual servicing costs "
        "estimated at around $40, while gas furnaces may incur higher maintenance costs "
        "averaging about $200 [S5][S4].",
        None,
    ),
    (
        "X02",
        "C22",
        "number",
        "In 2010, estimates for the average cost of lithium-ion battery packs ranged from "
        "approximately **$750 per kWh** to **$1,400 per kWh**[S1][S2].",
        None,
    ),
    (
        "X03",
        "C09",
        "number",
        "Some studies indicate that components of immune memory, such as memory B cells, may "
        "persist with significant presence for at least two years post-vaccination [S30].",
        None,
    ),
    (
        "X04",
        "C10",
        "added assertion",
        "The follower increases its term number, votes for itself, and requests votes from "
        "other nodes, and an election typically completes within 10 milliseconds [S6][S14].",
        None,
    ),
    (
        "X05",
        "C26",
        "added assertion",
        "Some businesses, like Salesforce, initially embraced flexible remote work models but "
        "have since noted a trend toward more in-office requirements, and Salesforce now "
        "requires all employees to work in the office five days a week [S13][S14].",
        None,
    ),
    ("X06", "C26", "wrong source", None, "C25"),
    ("X07", "C13", "wrong source", None, "C15"),
    (
        "X08",
        "C28",
        "inferred conclusion",
        "Additionally, geological evidence suggests a pattern of earthquakes in the Eastern "
        "Mediterranean that could have structurally weakened urban centers, which was the "
        "primary cause of the collapse [S3].",
        None,
    ),
    (
        "X09",
        "C17",
        "inferred conclusion",
        "Resource Disparities**: Concerns have been raised regarding the significant compliance "
        "requirements that may be challenging for various providers to meet, particularly "
        "affecting smaller entities, which will likely force many of them to withdraw from the "
        "EU [S10][S19].",
        None,
    ),
    (
        "X10",
        "C02",
        "inferred conclusion",
        "PostgreSQL's richer feature set provides strong data integrity mechanisms and "
        "extensive indexing options necessary for production-grade web services, which makes "
        "SQLite unsuitable for production use [S10].",
        None,
    ),
]


def _hand_labels() -> dict[str, tuple[str, str]]:
    """Claim ID -> (label, note) from the filled-in labeling sheet."""
    sheet = (LABELS_DIR / "citation_support.md").read_text(encoding="utf-8")
    labels = {}
    for block in re.split(r"^## (?=C\d+$)", sheet, flags=re.M)[1:]:
        claim_id = block.split("\n", 1)[0].strip()
        label = re.search(r"^label:[ \t]*(\S*)", block, re.M).group(1)
        note = re.search(r"^note:[ \t]*(.*)$", block, re.M).group(1).strip()
        labels[claim_id] = (label, note)
    return labels


def _recite(claim: str, sources: list[dict]) -> str:
    """The claim with its citations replaced by citations of `sources`."""
    bare = re.sub(r"\s*\[S\d+(?:,\s*S\d+)*\]", "", claim).rstrip().rstrip(".")
    return f"{bare} {''.join(f'[{s["id"]}]' for s in sources)}."


def calibration_items() -> list[dict]:
    manifest = json.loads((LABELS_DIR / "manifest.json").read_text(encoding="utf-8"))
    claims = {c["id"]: c for c in manifest["claims"]}
    labels = _hand_labels()

    def item(case_id, claim, claim_text, sources, label, metadata):
        return {
            "id": f"{JUDGE}-{case_id}",
            "input": {"question": claim["question"], "claim": claim_text, "sources": sources},
            "expected_output": label,
            "metadata": {"case": case_id, "trace_id": claim["trace_id"], **metadata},
        }

    items = []
    for claim_id, (label, note) in labels.items():
        if label not in ("supported", "unsupported"):
            continue  # skipped while labeling
        c = claims[claim_id]
        meta = {
            "origin": "hand-labeled",
            "note": note,
            "self_check_flagged": c["self_check_flagged"],
        }
        items.append(item(claim_id, c, c["claim"], c["sources"], label, meta))
    for case_id, base_id, failure, text, sources_from in BUILT_CASES:
        c = claims[base_id]
        sources = c["sources"]
        if sources_from:
            sources = claims[sources_from]["sources"]
            text = _recite(c["claim"], sources)
        meta = {"origin": "built", "failure_type": failure, "built_from": base_id}
        items.append(item(case_id, c, text or c["claim"], sources, "unsupported", meta))
    return items


def upload() -> None:
    langfuse = get_langfuse()
    langfuse.create_dataset(
        name=DATASET_NAME,
        description="Ground truth for the citation_support judge: hand-labeled claims from "
        "the baseline run plus built unsupported cases.",
    )
    items = calibration_items()
    for i in items:
        langfuse.create_dataset_item(dataset_name=DATASET_NAME, **i)
    langfuse.flush()
    counts = Counter(i["expected_output"] for i in items)
    print(f"uploaded {len(items)} items to {DATASET_NAME}: {dict(counts)}")


def judge_output_correct(*, output: str, expected_output: str, **kwargs) -> Evaluation:
    return Evaluation(
        name=f"{JUDGE}-judge-output-correct", value=output == expected_output, data_type="BOOLEAN"
    )


def run(version: int) -> None:
    require_openai_key()
    langfuse = get_langfuse()
    prompt = get_judge_prompt(JUDGE, version)

    async def task(*, item, **kwargs) -> str:
        verdict = await judge_claim(prompt, **item.input)
        return verdict.verdict

    dataset = langfuse.get_dataset(DATASET_NAME)
    result = dataset.run_experiment(
        name=f"{JUDGE} v{version}",
        description=f"Calibration of prompt {prompt.name} v{version}",
        task=task,
        evaluators=[judge_output_correct],
        max_concurrency=5,
        metadata={"prompt_version": str(version)},
    )
    langfuse.flush()

    by_label: dict[str, list[bool]] = {}
    mistakes = []
    for r in result.item_results:
        expected, actual = r.item.expected_output, r.output
        by_label.setdefault(expected, []).append(actual == expected)
        if actual != expected:
            mistakes.append((r.item.metadata["case"], expected, actual, r.item.input["claim"]))
    total = [ok for oks in by_label.values() for ok in oks]
    print(f"overall: {sum(total)}/{len(total)} = {sum(total) / len(total):.0%}")
    for label, oks in sorted(by_label.items()):
        print(f"  {label}: {sum(oks)}/{len(oks)} = {sum(oks) / len(oks):.0%}")
    for case, expected, actual, claim in sorted(mistakes):
        print(f"{case}\texpected={expected}\tactual={actual}\t{claim}")
    print(result.dataset_run_url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["upload", "run"])
    parser.add_argument("version", nargs="?", type=int)
    args = parser.parse_args()
    if args.action == "upload":
        upload()
    else:
        run(args.version)
