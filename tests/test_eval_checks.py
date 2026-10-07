from evals.checks import citations_valid, unresolved_gaps

SOURCES = [{"id": "S1", "url": "u1", "title": "t", "content": "c", "sub_question": "q"}]


def test_citations_valid_passes_when_all_ids_exist():
    result = citations_valid(output={"draft": "Claim [S1].", "sources": SOURCES})
    assert result.value is True


def test_citations_valid_names_broken_ids():
    result = citations_valid(output={"draft": "Claim [S1][S9].", "sources": SOURCES})
    assert result.value is False
    assert "S9" in result.comment


def test_unresolved_gaps_counts_gaps():
    gap = {"sub_question": "q", "claim": "c", "source_ids": [], "reason": "r"}
    assert unresolved_gaps(output={"gaps": [gap, gap]}).value == 2
