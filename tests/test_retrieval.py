from __future__ import annotations

from contextos.retrieval import detect_trigger


def test_trigger_phrases() -> None:
    assert detect_trigger("As we discussed earlier, the schema is X.")
    assert detect_trigger("Referring back to the previous implementation")
    assert detect_trigger("We already decided on the table layout")


def test_no_trigger() -> None:
    assert not detect_trigger("Here is a fresh function.")
    assert not detect_trigger("")
