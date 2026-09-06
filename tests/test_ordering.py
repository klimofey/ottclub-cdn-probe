"""Round order: least-measured CDNs first.

A round that always restarts at the top of the list re-measures the opening
CDNs after every interruption and never reaches the tail - observed live as
one CDN with five rounds beside another with one. Ordering by coverage makes
the next round repair that instead of compounding it.
"""

from collections import Counter


def order(labels, seen):
    """The ordering rule as the daemon applies it."""
    original = list(labels)
    return sorted(labels, key=lambda l: (seen[l], original.index(l)))


class TestRoundOrder:
    def test_least_measured_comes_first(self):
        seen = Counter({"A": 5, "B": 1, "C": 3})
        assert order(["A", "B", "C"], seen) == ["B", "C", "A"]

    def test_a_never_measured_cdn_leads(self):
        seen = Counter({"A": 2, "B": 2})
        assert order(["A", "B", "New"], seen)[0] == "New"

    def test_ties_keep_the_provider_order(self):
        """Stable within a tie, so the walk stays predictable."""
        seen = Counter({"A": 1, "B": 1, "C": 1})
        assert order(["A", "B", "C"], seen) == ["A", "B", "C"]

    def test_an_interrupted_round_is_repaired_by_the_next(self):
        labels = ["A", "B", "C", "D"]
        seen = Counter()
        # First round dies after two CDNs.
        for cdn in order(labels, seen)[:2]:
            seen[cdn] += 1
        # The next round starts with exactly the ones that were missed.
        assert order(labels, seen)[:2] == ["C", "D"]

    def test_repeated_interruptions_still_even_out(self):
        labels = list("ABCDEFGH")
        seen = Counter()
        for _ in range(8):                      # eight rounds, each dying early
            for cdn in order(labels, seen)[:2]:
                seen[cdn] += 1
        assert max(seen.values()) - min(seen.values()) <= 1

    def test_without_the_rule_the_tail_is_never_reached(self):
        """The bug this replaces: fixed order plus interruptions starves the end."""
        labels = list("ABCDEFGH")
        seen = Counter()
        for _ in range(8):
            for cdn in labels[:2]:              # always the same two
                seen[cdn] += 1
        assert seen["H"] == 0
