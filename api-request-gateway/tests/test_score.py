import pytest

from models.code_analyze import score_to_difficulty


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (1, "hard"),
        (4, "hard"),
        (5, "medium"),
        (7, "medium"),
        (8, "easy"),
        (10, "easy"),
    ],
)
def test_score_to_difficulty(score: int, expected: str) -> None:
    assert score_to_difficulty(score) == expected
