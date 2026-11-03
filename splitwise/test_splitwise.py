import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier
from splitwise import Debt, EqualSplitStrategy, ExactSplitStrategy, Expense, Group, PercentageSplitStrategy, SplitwiseService

class SplitwiseTests(unittest.TestCase):

    def test_equal_rounding_and_input_order(self):
        expected = {'A': 3334, 'B': 3333, 'C': 3333}
        self.assertEqual(EqualSplitStrategy().allocate(10000, ['C', 'A', 'B']), expected)
        self.assertEqual(EqualSplitStrategy().allocate(10000, ['A', 'B', 'C']), expected)
        self.assertEqual(EqualSplitStrategy().allocate(1, ['A', 'B', 'C']), {'A': 1, 'B': 0, 'C': 0})

    def test_percentage_rounding_and_conservation(self):
        split = PercentageSplitStrategy()
        self.assertEqual(split.allocate(101, ['A', 'B', 'C'], [3333, 3333, 3334]), {'A': 34, 'B': 33, 'C': 34})
        for total in range(1, 301):
            for a in (0, 1, 3333, 5000, 9999, 10000):
                allocation = PercentageSplitStrategy().allocate(total, ['A', 'B', 'C'], [a, 10000 - a, 0])
                self.assertEqual(sum(allocation.values()), total)
                self.assertEqual(allocation['C'], 0)
                for (uid, weight) in (('A', a), ('B', 10000 - a)):
                    self.assertLessEqual(abs(allocation[uid] * 10000 - total * weight), 10000)

    def test_opposite_expenses_and_partial_settlement(self):
        group = Group(['A', 'B', 'C'])
        group.add_expense('A', 90000, EqualSplitStrategy(), ['A', 'B', 'C'])
        group.add_expense('B', 30000, EqualSplitStrategy(), ['A', 'B'])
        self.assertEqual(group.get_balances(), (Debt('B', 'A', 15000), Debt('C', 'A', 30000)))
        group.record_settlement('B', 'A', 10000)
        self.assertEqual(group.get_balances()[0], Debt('B', 'A', 5000))
        group.record_settlement('B', 'A', 5000)
        self.assertEqual(group.get_balances(), (Debt('C', 'A', 30000),))
        self.assertEqual(len(group.get_history()), 4)

    def test_payer_can_be_excluded_or_only_participant(self):
        group = Group(['A', 'B', 'C'])
        group.add_expense('A', 20000, EqualSplitStrategy(), ['B', 'C'])
        self.assertEqual(group.get_balances(), (Debt('B', 'A', 10000), Debt('C', 'A', 10000)))
        group.add_expense('A', 500, EqualSplitStrategy(), ['A'])
        self.assertEqual(len(group.get_balances()), 2)
        self.assertEqual(len(group.get_history()), 2)

    def test_debt_direction_can_reverse(self):
        group = Group(['A', 'B'])
        group.add_expense('A', 100, ExactSplitStrategy(), ['B'], [100])
        group.add_expense('B', 150, ExactSplitStrategy(), ['A'], [150])
        self.assertEqual(group.get_balances(), (Debt('A', 'B', 50),))

    def test_invalid_operations_leave_balances_and_history_unchanged(self):
        group = Group(['A', 'B'])
        group.add_expense('A', 100, ExactSplitStrategy(), ['B'], [100])
        before = (group.get_balances(), group.get_history())
        operations = [lambda : group.add_expense('X', 100, ExactSplitStrategy(), ['B'], [100]), lambda : group.add_expense('A', 100, ExactSplitStrategy(), ['X'], [100]), lambda : group.add_expense('A', 100, ExactSplitStrategy(), ['A', 'B'], [40, 50]), lambda : group.add_expense('A', 100, ExactSplitStrategy(), ['A', 'B'], [-1, 101]), lambda : group.add_expense('A', 100, PercentageSplitStrategy(), ['B'], [9999]), lambda : group.add_expense('A', 100, ExactSplitStrategy(), [], []), lambda : group.add_expense('A', 0, EqualSplitStrategy(), ['A']), lambda : group.add_expense('A', True, EqualSplitStrategy(), ['A']), lambda : group.record_settlement('B', 'A', 101), lambda : group.record_settlement('A', 'B', 1), lambda : group.record_settlement('A', 'A', 1), lambda : group.record_settlement('B', 'A', 0)]
        for operation in operations:
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual((group.get_balances(), group.get_history()), before)

    def test_invalid_strategy_output_is_rejected(self):

        class BrokenSplit:

            def allocate(self, total, participants, values=None):
                return {'B': total + 1}
        group = Group(['A', 'B'])
        with self.assertRaises(ValueError):
            group.add_expense('A', 100, BrokenSplit(), ['B'])
        self.assertEqual(group.get_history(), ())

    def test_duplicate_and_empty_participants(self):
        for users in ([], ['A', 'A'], ['']):
            with self.assertRaises(ValueError):
                Group(["A", "B"]).add_expense("A", 100, EqualSplitStrategy(), users)

    def test_defensive_copies_and_immutable_results(self):
        (participants, amounts) = (['B'], [100])
        strategy = ExactSplitStrategy()
        group = Group(['A', 'B'])
        expense = group.add_expense('A', 100, strategy, participants, amounts)
        participants.clear()
        amounts[0] = 900
        with self.assertRaises(FrozenInstanceError):
            expense.total = 0
        self.assertEqual(expense.shares, (('B', 100),))
        snapshot = group.get_balances()
        group.record_settlement('B', 'A', 100)
        self.assertEqual(snapshot, (Debt('B', 'A', 100),))

    def test_history_replay(self):
        group = Group(['A', 'B', 'C'])
        group.add_expense('A', 101, PercentageSplitStrategy(), ['A', 'B', 'C'], [3333, 3333, 3334])
        group.add_expense('B', 10000, EqualSplitStrategy(), ['C', 'B', 'A'])
        group.add_expense('C', 100, ExactSplitStrategy(), ['A'], [100])
        group.record_settlement('A', 'B', 1000)
        replay = {}

        def add(debtor, creditor, amount):
            if debtor == creditor:
                return
            pair = tuple(sorted((debtor, creditor)))
            signed = amount if debtor == pair[0] else -amount
            replay[pair] = replay.get(pair, 0) + signed
        for event in group.get_history():
            if isinstance(event, Expense):
                for (uid, amount) in event.shares:
                    add(uid, event.payer, amount)
            else:
                add(event.debtor, event.creditor, -event.amount)
        replay = {pair: value for (pair, value) in replay.items() if value}
        current = {}
        for debt in group.get_balances():
            pair = tuple(sorted((debt.debtor, debt.creditor)))
            current[pair] = debt.amount if debt.debtor == pair[0] else -debt.amount
        self.assertEqual(replay, current)

    def test_competing_settlements(self):
        group = Group(['A', 'B'])
        group.add_expense('A', 10000, ExactSplitStrategy(), ['B'], [10000])
        barrier = Barrier(2)

        def settle(_):
            barrier.wait()
            try:
                group.record_settlement('B', 'A', 8000)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(settle, range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(group.get_balances(), (Debt('B', 'A', 2000),))
        self.assertEqual(len(group.get_history()), 2)

    def test_concurrent_expenses_do_not_lose_updates(self):
        group = Group(['A', 'B'])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: group.add_expense('A', 1, ExactSplitStrategy(), ['B'], [1]), range(200)))
        self.assertEqual(group.get_balances(), (Debt('B', 'A', 200),))
        self.assertEqual(len(group.get_history()), 200)

    def test_service_split_types_and_rejection_atomicity(self):
        service = SplitwiseService({'trip': ['A', 'B', 'C']})
        for (mode, values, total, expected) in [('EQUAL', None, 100, {'A': 34, 'B': 33, 'C': 33}), ('EXACT', [0, 100, 0], 100, {'A': 0, 'B': 100, 'C': 0}), ('PERCENTAGE', [3333, 3333, 3334], 101, {'A': 34, 'B': 33, 'C': 34})]:
            expense = service.add_expense('trip', 'A', total, mode, ['A', 'B', 'C'], values)
            self.assertEqual(dict(expense.shares), expected)
        before = (service.get_balances('trip'), service.get_history('trip'))
        for (mode, users, values) in [('INVALID', ['B'], None), ('EQUAL', ['B', 'B'], None), ('EQUAL', ['B'], [100]), ('EXACT', ['B'], None), ('EXACT', ['B', 'C'], [100]), ('EXACT', ['B'], [99]), ('EXACT', ['X'], [100]), ('PERCENTAGE', ['B'], [9999]), ('EXACT', ['B'], [True]), ('EQUAL', [], None)]:
            with self.assertRaises(ValueError):
                service.add_expense('trip', 'A', 100, mode, users, values)
            self.assertEqual((service.get_balances('trip'), service.get_history('trip')), before)

    def test_service_copies_caller_data(self):
        service = SplitwiseService({'trip': ['A', 'B']})
        (users, values) = (['B'], [100])
        expense = service.add_expense('trip', 'A', 100, 'EXACT', users, values)
        users.clear()
        values.clear()
        self.assertEqual(dict(expense.shares), {'B': 100})
        self.assertEqual(service.get_balances('trip'), (Debt('B', 'A', 100),))

    def test_service_rejects_invalid_ids(self):
        service = SplitwiseService({'trip': ['A', 'B']})
        for invalid in [None, [], '', 'é']:
            for operation in [lambda : service.get_balances(invalid), lambda : service.get_history(invalid), lambda : service.record_settlement('trip', invalid, 'B', 1)]:
                with self.assertRaises(ValueError):
                    operation()

    def test_inline_checks_accept_string_ids_and_reject_bad_data(self):
        service = SplitwiseService({"voyagé": ["A", "É"]})
        expense = service.add_expense("voyagé", "A", 100, "EXACT", ["É"], [100])
        self.assertEqual(dict(expense.shares), {"É": 100})
        before = service.get_balances("voyagé"), service.get_history("voyagé")
        for users, values in [([None], [100]), ([[]], [100]), ([" "], [100]), (["É"], [-1]), (["É"], [True]), (["É"], "100"), (["É"], 100), (["É"], [100, 0])]:
            with self.assertRaises(ValueError):
                service.add_expense("voyagé", "A", 100, "EXACT", users, values)
            self.assertEqual((service.get_balances("voyagé"), service.get_history("voyagé")), before)
        for invalid in [None, "", " "]:
            with self.assertRaises(ValueError):
                SplitwiseService({invalid: ["A"]})

    def test_group_isolation_and_unknown_group(self):
        service = SplitwiseService({'trip': ['A', 'B'], 'home': ['A', 'B']})
        service.add_expense('trip', 'A', 100, 'EXACT', ['B'], [100])
        self.assertEqual(service.get_balances('home'), ())
        with self.assertRaises(ValueError):
            service.get_balances('missing')
class StrategyReuseTests(unittest.TestCase):
    def test_same_instances_with_different_inputs_and_concurrent_calls(self):
        strategies = [EqualSplitStrategy(), ExactSplitStrategy(), PercentageSplitStrategy()]
        def calculate(i):
            users = [f"A{i}", f"B{i}"]
            for strategy, values in zip(strategies, [None, [i, i], [5000, 5000]]):
                result = strategy.allocate(2 * i, users, values)
                self.assertEqual(result, {users[0]: i, users[1]: i})
                result.clear()
                self.assertEqual(strategy.allocate(2 * i, users, values), {users[0]: i, users[1]: i})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(calculate, range(1, 101)))
        for strategy, values in zip(strategies, [[10], [9], [9999]]):
            with self.assertRaises(ValueError):
                strategy.allocate(10, ["A"], values)
        calculate(7)

    def test_strategy_cannot_substitute_another_member(self):
        class WrongParticipants:
            def allocate(self, total, participants, values=None):
                return {"C": total}
        group = Group(["A", "B", "C"])
        with self.assertRaises(ValueError):
            group.add_expense("A", 100, WrongParticipants(), ["B"])
        self.assertEqual(group.get_history(), ())
        self.assertEqual(group.get_balances(), ())

if __name__ == '__main__':
    unittest.main()
