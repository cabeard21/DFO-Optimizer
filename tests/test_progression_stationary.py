"""Compare repeated stationary releases with the independent one-release tally."""

from copy import deepcopy
from itertools import product

from dfo_optimizer import progression_replay as reference


def test_grouped_stationary_tally_matches_single_release_across_thresholds():
    for skill, raw, cadence, challenge, count in product(
        (16, 20, 22), (99, 100, 125, 175, 199, 200), (0, 1400, 60000, 101050), (1, 25, 34), (1, 3, 11, 64)
    ):
        base = {
            "skills": [0] * 35,
            "uses": [19999] * 35,
            "mastered": [skill],
            "fractions": [0.99125] * 35,
            "spam_recent": [36.75] * 35,
            "spam_at": [1000] * 35,
            "challenge_level": challenge,
            "challenge_at": 1000,
            "real_ms": 1000,
        }
        base["skills"][skill] = raw
        grouped = deepcopy(base)
        for _ in range(count):
            base["real_ms"] += cadence
            base["challenge_at"] = base["real_ms"]
            reference._tally(base, skill, 1)
        reference._stationary(grouped, skill, 1, count, cadence, challenge)
        assert grouped == base
