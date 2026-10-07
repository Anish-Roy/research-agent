"""The eval test set, `research-questions-v0`, and its upload to Langfuse.

Items have only an input. Every metric is reference-free: claims are checked against
the run's own sources and the report against the run's own approved sub-questions.
Metadata tags each item so scores can be split by question type.

Upload (idempotent, items are upserted by ID):
    uv run python -m evals.dataset
"""

from research_agent.tracing import get_langfuse

DATASET_NAME = "research-questions-v0"

# (question, question_type, domain, time_sensitive)
QUESTIONS = [
    (
        "What are the main tradeoffs between SQLite and Postgres for small web apps?",
        "comparison",
        "tech",
        False,
    ),
    (
        "How do heat pumps compare to gas furnaces for heating homes in cold climates?",
        "comparison",
        "energy",
        False,
    ),
    ("How do mRNA vaccines train the immune system?", "how-it-works", "science", False),
    ("How does the Raft consensus algorithm handle leader failure?", "how-it-works", "tech", False),
    (
        "What are the main new features in the most recent stable Python release?",
        "time-sensitive",
        "tech",
        True,
    ),
    (
        "What is the current status of the EU AI Act's obligations for general-purpose AI models?",
        "time-sensitive",
        "policy",
        True,
    ),
    (
        "How do beekeepers manage Varroa mites without synthetic chemical treatments?",
        "niche",
        "agriculture",
        False,
    ),
    (
        "How much has the cost per kWh of lithium-ion battery packs fallen since 2010?",
        "numbers",
        "economics",
        False,
    ),
    ("Is remote work good for productivity?", "vague", "workplace", False),
    (
        "What caused the collapse of the Bronze Age civilizations around 1177 BC?",
        "contested",
        "history",
        False,
    ),
]


def upload() -> None:
    langfuse = get_langfuse()
    langfuse.create_dataset(
        name=DATASET_NAME,
        description="End-to-end research questions across question types and domains. "
        "Input only; all metrics are reference-free.",
        metadata={"version": "v0"},
    )
    for i, (question, question_type, domain, time_sensitive) in enumerate(QUESTIONS, 1):
        langfuse.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=f"{DATASET_NAME}-{i:02d}",
            input={"question": question},
            metadata={
                "question_type": question_type,
                "domain": domain,
                "time_sensitive": time_sensitive,
            },
        )
    langfuse.flush()
    print(f"uploaded {len(QUESTIONS)} items to {DATASET_NAME}")


if __name__ == "__main__":
    upload()
