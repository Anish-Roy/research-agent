from evals.claims import cited_claims

DRAFT = """# Report

## Speed

SQLite is fast for reads [S1]. It has one writer at a time [S2][S3]. Nobody disputes this.
- Postgres scales to many users [S4, S5].
- Setup is harder.

Postgres needs a server. [S6]
"""


def test_extracts_only_cited_sentences_with_their_ids():
    assert cited_claims(DRAFT) == [
        {"text": "SQLite is fast for reads [S1].", "source_ids": ["S1"]},
        {"text": "It has one writer at a time [S2][S3].", "source_ids": ["S2", "S3"]},
        {"text": "Postgres scales to many users [S4, S5].", "source_ids": ["S4", "S5"]},
        {"text": "Postgres needs a server. [S6]", "source_ids": ["S6"]},
    ]


def test_ignores_headings_and_markdown_links():
    assert cited_claims("# Title [S1]\n\nSee [docs](https://x.io) for more.") == []
