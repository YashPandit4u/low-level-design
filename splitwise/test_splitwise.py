import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

from splitwise import (
    Debt, EqualSplit, ExactSplit, Expense, Group, PercentageSplit, SplitwiseService,
)


class SplitwiseTests(unittest.TestCase):
    def test_equal_rounding_and_input_order(self):
        expected = {"A": 3334, "B": 3333, "C": 3333}
        self.assertEqual(EqualSplit(["C", "A", "B"]).allocate(10000), expected)
        self.assertEqual(EqualSplit(["A", "B", "C"]).allocate(10000), expected)
        self.assertEqual(EqualSplit(["A", "B", "C"]).allocate(1), {"A": 1, "B": 0, "C": 0})

    def test_percentage_rounding_and_conservation(self):
        split = PercentageSplit({"A": 3333, "B": 3333, "C": 3334})
        self.assertEqual(split.allocate(101), {"A": 34, "B": 33, "C": 34})
        for total in range(1, 301):
            for a in (0, 1, 3333, 5000, 9999, 10000):
                allocation = PercentageSplit({"A": a, "B": 10000 - a, "C": 0}).allocate(total)
                self.assertEqual(sum(allocation.values()), total)
                self.assertEqual(allocation["C"], 0)
                for uid, weight in (("A", a), ("B", 10000 - a)):
                    self.assertLessEqual(abs(allocation[uid] * 10000 - total * weight), 10000)

    def test_opposite_expenses_and_partial_settlement(self):
        group = Group(["A", "B", "C"])
        group.add_expense("A", 90000, EqualSplit(["A", "B", "C"]))
        group.add_expense("B", 30000, EqualSplit(["A", "B"]))
        self.assertEqual(group.get_balances(), (Debt("B", "A", 15000), Debt("C", "A", 30000)))
        group.record_settlement("B", "A", 10000)
        self.assertEqual(group.get_balances()[0], Debt("B", "A", 5000))
        group.record_settlement("B", "A", 5000)
        self.assertEqual(group.get_balances(), (Debt("C", "A", 30000),))
        self.assertEqual(len(group.get_history()), 4)

    def test_payer_can_be_excluded_or_only_participant(self):
        group = Group(["A", "B", "C"])
        group.add_expense("A", 20000, EqualSplit(["B", "C"]))
        self.assertEqual(group.get_balances(), (Debt("B", "A", 10000), Debt("C", "A", 10000)))
        group.add_expense("A", 500, EqualSplit(["A"]))
        self.assertEqual(len(group.get_balances()), 2)
        self.assertEqual(len(group.get_history()), 2)

    def test_debt_direction_can_reverse(self):
        group = Group(["A", "B"])
        group.add_expense("A", 100, ExactSplit({"B": 100}))
        group.add_expense("B", 150, ExactSplit({"A": 150}))
        self.assertEqual(group.get_balances(), (Debt("A", "B", 50),))

    def test_invalid_operations_leave_balances_and_history_unchanged(self):
        group = Group(["A", "B"])
        group.add_expense("A", 100, ExactSplit({"B": 100}))
        before = group.get_balances(), group.get_history()
        operations = [
            lambda: group.add_expense("X", 100, ExactSplit({"B": 100})),
            lambda: group.add_expense("A", 100, ExactSplit({"X": 100})),
            lambda: group.add_expense("A", 100, ExactSplit({"A": 40, "B": 50})),
            lambda: group.add_expense("A", 100, ExactSplit({"A": -1, "B": 101})),
            lambda: group.add_expense("A", 100, PercentageSplit({"B": 9999})),
            lambda: group.add_expense("A", 100, ExactSplit({})),
            lambda: group.add_expense("A", 0, EqualSplit(["A"])),
            lambda: group.add_expense("A", True, EqualSplit(["A"])),
            lambda: group.record_settlement("B", "A", 101),
            lambda: group.record_settlement("A", "B", 1),
            lambda: group.record_settlement("A", "A", 1),
            lambda: group.record_settlement("B", "A", 0),
        ]
        for operation in operations:
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual((group.get_balances(), group.get_history()), before)

    def test_invalid_strategy_output_is_rejected(self):
        class BrokenSplit:
            def allocate(self, total):
                return {"B": total + 1}
        group = Group(["A", "B"])
        with self.assertRaises(ValueError):
            group.add_expense("A", 100, BrokenSplit())
        self.assertEqual(group.get_history(), ())

    def test_duplicate_and_empty_participants(self):
        for users in ([], ["A", "A"], [""]):
            with self.assertRaises(ValueError):
                EqualSplit(users)

    def test_defensive_copies_and_immutable_results(self):
        amounts = {"B": 100}
        strategy = ExactSplit(amounts)
        amounts["B"] = 900
        group = Group(["A", "B"])
        expense = group.add_expense("A", 100, strategy)
        with self.assertRaises(FrozenInstanceError):
            expense.total = 0
        self.assertEqual(expense.shares, (("B", 100),))
        snapshot = group.get_balances()
        group.record_settlement("B", "A", 100)
        self.assertEqual(snapshot, (Debt("B", "A", 100),))

    def test_history_replay(self):
        group = Group(["A", "B", "C"])
        group.add_expense("A", 101, PercentageSplit({"A": 3333, "B": 3333, "C": 3334}))
        group.add_expense("B", 10000, EqualSplit(["C", "B", "A"]))
        group.add_expense("C", 100, ExactSplit({"A": 100}))
        group.record_settlement("A", "B", 1000)
        replay = {}
        def add(debtor, creditor, amount):
            if debtor == creditor:
                return
            pair = tuple(sorted((debtor, creditor)))
            signed = amount if debtor == pair[0] else -amount
            replay[pair] = replay.get(pair, 0) + signed
        for event in group.get_history():
            if isinstance(event, Expense):
                for uid, amount in event.shares:
                    add(uid, event.payer, amount)
            else:
                add(event.debtor, event.creditor, -event.amount)
        replay = {pair: value for pair, value in replay.items() if value}
        current = {}
        for debt in group.get_balances():
            pair = tuple(sorted((debt.debtor, debt.creditor)))
            current[pair] = debt.amount if debt.debtor == pair[0] else -debt.amount
        self.assertEqual(replay, current)

    def test_competing_settlements(self):
        group = Group(["A", "B"])
        group.add_expense("A", 10000, ExactSplit({"B": 10000}))
        barrier = Barrier(2)
        def settle(_):
            barrier.wait()
            try:
                group.record_settlement("B", "A", 8000)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(settle, range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(group.get_balances(), (Debt("B", "A", 2000),))
        self.assertEqual(len(group.get_history()), 2)

    def test_concurrent_expenses_do_not_lose_updates(self):
        group = Group(["A", "B"])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: group.add_expense("A", 1, ExactSplit({"B": 1})), range(200)))
        self.assertEqual(group.get_balances(), (Debt("B", "A", 200),))
        self.assertEqual(len(group.get_history()), 200)

    def test_group_isolation_and_unknown_group(self):
        service = SplitwiseService({"trip": ["A", "B"], "home": ["A", "B"]})
        service.add_expense("trip", "A", 100, ExactSplit({"B": 100}))
        self.assertEqual(service.get_balances("home"), ())
        with self.assertRaises(ValueError):
            service.get_balances("missing")


if __name__ == "__main__":
    unittest.main()
