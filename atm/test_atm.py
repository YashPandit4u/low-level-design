import itertools
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Event
from atm import ATM, CashInventory


class FakeBank:
    def __init__(self, funds=100000):
        self.funds = funds
        self.holds = {}
        self.fail = None
        self.calls = []

    def authenticate(self, card, pin):
        if self.fail == 'authenticate': raise TimeoutError()
        return 'account-A' if card == 'card-A' and pin == '1234' else None

    def available_balance(self, account):
        if self.fail == 'balance': raise TimeoutError()
        return self.funds - sum(self.holds.values())

    def hold(self, account, amount, operation):
        self.calls.append('hold')
        if amount > self.available_balance(account): return False
        self.holds[operation] = amount
        if self.fail == 'hold': raise TimeoutError()
        return True

    def capture(self, operation):
        self.calls.append('capture')
        if self.fail == 'capture': raise TimeoutError()
        self.funds -= self.holds.pop(operation)
        if self.fail == 'capture_after': raise TimeoutError()

    def release(self, operation):
        self.calls.append('release')
        if self.fail == 'release': raise TimeoutError()
        del self.holds[operation]
        if self.fail == 'release_after': raise TimeoutError()


class FakeHardware:
    def __init__(self):
        self.outcome = 'ALL'
        self.dispensed = []
        self.ejections = 0
        self.eject_fails = False

    def dispense(self, notes):
        self.dispensed.append(dict(notes))
        if self.outcome == 'TIMEOUT': raise TimeoutError()
        return self.outcome

    def eject_card(self):
        self.ejections += 1
        if self.eject_fails: raise RuntimeError()


class ATMTest(unittest.TestCase):
    def setUp(self):
        self.bank, self.hardware = FakeBank(), FakeHardware()
        self.atm = ATM(self.bank, self.hardware, {50000: 1, 20000: 3}, 100000)

    def login(self):
        self.atm.insert_card('card-A')
        self.assertTrue(self.atm.enter_pin('1234'))

    def test_success_and_non_greedy_bundle(self):
        self.login()
        self.assertEqual(self.atm.withdraw(60000), 'SUCCESS')
        self.assertEqual(self.hardware.dispensed, [{20000: 3}])
        self.assertEqual(self.atm.balance(), 40000)
        self.assertEqual(self.atm.cash_snapshot(), {50000: 1, 20000: 0})
        self.assertEqual(self.atm.status(), ('READY', None))

    def test_invalid_operations(self):
        for action in [lambda: self.atm.balance(), lambda: self.atm.withdraw(20000),
                       lambda: self.atm.enter_pin('1234')]:
            with self.assertRaises(ValueError): action()
        self.login()
        with self.assertRaises(ValueError): self.atm.insert_card('other')
        for amount in [0, -1, 100001, True, 3.5]:
            with self.assertRaises(ValueError): self.atm.withdraw(amount)
        self.assertEqual(self.bank.calls, [])

    def test_three_pin_failures_end_session(self):
        self.atm.insert_card('card-A')
        for _ in range(3): self.assertFalse(self.atm.enter_pin('0000'))
        self.assertEqual(self.atm.status(), ('IDLE', None))
        self.assertEqual(self.hardware.ejections, 1)
        self.login()

    def test_cancel_clears_authenticated_session(self):
        self.login()
        self.atm.cancel()
        self.atm.cancel()
        self.assertEqual(self.hardware.ejections, 1)
        with self.assertRaises(ValueError): self.atm.balance()

    def test_pin_session_preserves_card_and_resets_attempts(self):
        self.atm.insert_card('card-A')
        self.assertFalse(self.atm.enter_pin('bad'))
        with self.assertRaises(ValueError): self.atm.insert_card('card-B')
        with self.assertRaises(ValueError): self.atm.enter_pin('')
        self.assertTrue(self.atm.enter_pin('1234'))
        with self.assertRaises(ValueError): self.atm.enter_pin('bad')
        self.assertEqual(self.atm.status(), ('READY', None))
        self.atm.cancel()
        self.atm.insert_card('card-A')
        self.assertFalse(self.atm.enter_pin('bad'))
        self.atm.cancel()  # Cancellation before authentication also resets attempts.
        self.atm.insert_card('card-A')
        for _ in range(2):
            self.assertFalse(self.atm.enter_pin('bad'))
            self.assertEqual(self.atm.status(), ('PIN_REQUIRED', None))
        self.assertFalse(self.atm.enter_pin('bad'))
        self.assertEqual(self.atm.status(), ('IDLE', None))
        self.assertEqual(self.hardware.ejections, 3)
        with self.assertRaises(ValueError): self.atm.balance()

    def test_ejection_failure_during_pin_lockout_is_terminal(self):
        self.atm.insert_card('card-A')
        self.hardware.eject_fails = True
        for _ in range(3): self.assertFalse(self.atm.enter_pin('bad'))
        self.assertEqual(self.atm.status(), ('OUT_OF_SERVICE', None))
        self.atm.cancel()
        with self.assertRaises(ValueError): self.atm.insert_card('card-A')
        with self.assertRaises(ValueError): self.atm.enter_pin('1234')
        self.assertEqual(self.hardware.ejections, 1)

    def test_cash_unavailable_has_no_bank_side_effect(self):
        self.login()
        self.assertEqual(self.atm.withdraw(10000), 'CASH_UNAVAILABLE')
        self.assertEqual(self.bank.calls, [])

    def test_bank_decline_has_no_hardware_side_effect(self):
        self.login()
        self.bank.funds = 10000
        self.assertEqual(self.atm.withdraw(20000), 'DECLINED')
        self.assertEqual(self.hardware.dispensed, [])
        self.assertEqual(self.atm.cash_snapshot()[20000], 3)

    def test_shortage_and_decline_leave_notes_for_later_withdrawal(self):
        self.atm = ATM(self.bank, self.hardware, {50000: 1, 20000: 3}, 200000)
        self.login()
        for amount in [10000, 120000]:  # No exact bundle; then insufficient total cash.
            self.assertEqual(self.atm.withdraw(amount), 'CASH_UNAVAILABLE')
        self.assertEqual(self.bank.calls, [])
        self.bank.funds = 10000
        self.assertEqual(self.atm.withdraw(60000), 'DECLINED')
        self.assertEqual(self.hardware.dispensed, [])
        self.assertEqual(self.atm.cash_snapshot(), {50000: 1, 20000: 3})
        self.assertEqual(self.atm.status(), ('READY', None))
        self.bank.funds = 100000
        self.assertEqual(self.atm.withdraw(60000), 'SUCCESS')
        self.assertEqual(self.atm.withdraw(60000), 'CASH_UNAVAILABLE')
        self.assertEqual(self.hardware.dispensed, [{20000: 3}])
        self.assertEqual(self.bank.calls, ['hold', 'hold', 'capture'])
        self.assertEqual(self.atm.cash_snapshot(), {50000: 1, 20000: 0})
        self.assertEqual(self.atm.status(), ('READY', None))

    def test_no_cash_releases_hold(self):
        self.login()
        self.hardware.outcome = 'NONE'
        self.assertEqual(self.atm.withdraw(20000), 'NOT_DISPENSED')
        self.assertEqual(self.bank.holds, {})
        self.assertEqual(self.bank.funds, 100000)
        self.assertEqual(self.atm.cash_snapshot()[20000], 3)

    def test_unknown_and_timeout_never_release_hold(self):
        for outcome in ['UNKNOWN', 'TIMEOUT', 'unexpected']:
            with self.subTest(outcome=outcome):
                self.setUp()
                self.login()
                self.hardware.outcome = outcome
                self.assertEqual(self.atm.withdraw(20000), 'PENDING_REVIEW')
                state, pending = self.atm.status()
                self.assertEqual(state, 'OUT_OF_SERVICE')
                self.assertIn(pending, self.bank.holds)
                self.assertNotIn('release', self.bank.calls)
                self.atm.cancel()
                self.assertEqual(self.atm.status()[0], 'OUT_OF_SERVICE')

    def test_bank_failure_at_each_money_step(self):
        for stage in ['hold', 'capture', 'release']:
            with self.subTest(stage=stage):
                self.setUp()
                self.login()
                self.bank.fail = stage
                self.hardware.outcome = 'NONE' if stage == 'release' else 'ALL'
                self.assertEqual(self.atm.withdraw(20000), 'PENDING_REVIEW')
                self.assertEqual(self.atm.status()[0], 'OUT_OF_SERVICE')
                self.assertIsNotNone(self.atm.status()[1])
                self.assertEqual(self.atm.cash_snapshot()[20000], 2 if stage == 'capture' else 3)

    def test_bank_reply_lost_after_success(self):
        for stage in ['capture_after', 'release_after']:
            with self.subTest(stage=stage):
                self.setUp()
                self.login()
                self.bank.fail = stage
                self.hardware.outcome = 'ALL' if stage == 'capture_after' else 'NONE'
                self.assertEqual(self.atm.withdraw(20000), 'PENDING_REVIEW')
                state, pending = self.atm.status()
                self.assertEqual(state, 'OUT_OF_SERVICE')
                self.assertIsNotNone(pending)
                self.assertEqual(self.bank.holds, {})
                delivered = stage == 'capture_after'
                self.assertEqual(self.bank.funds, 80000 if delivered else 100000)
                self.assertEqual(self.atm.cash_snapshot()[20000], 2 if delivered else 3)
                self.assertEqual(self.bank.calls, ['hold', 'capture' if delivered else 'release'])
                with self.assertRaises(ValueError): self.atm.withdraw(20000)

    def test_balance_outage_does_not_end_session(self):
        self.login()
        self.bank.fail = 'balance'
        with self.assertRaises(TimeoutError): self.atm.balance()
        self.assertEqual(self.atm.status(), ('READY', None))
        self.assertEqual(self.hardware.ejections, 0)
        self.bank.fail = None
        self.assertEqual(self.atm.balance(), 100000)

    def test_eject_failure_disables_machine(self):
        self.login()
        self.hardware.eject_fails = True
        self.atm.cancel()
        self.assertEqual(self.atm.status()[0], 'OUT_OF_SERVICE')

    def test_authentication_outage_ends_session(self):
        self.atm.insert_card('card-A')
        self.bank.fail = 'authenticate'
        with self.assertRaises(RuntimeError): self.atm.enter_pin('1234')
        self.assertEqual(self.atm.status()[0], 'OUT_OF_SERVICE')

    def test_snapshots_do_not_expose_inventory(self):
        snapshot = self.atm.cash_snapshot()
        snapshot[50000] = 99
        self.assertEqual(self.atm.cash_snapshot()[50000], 1)

    def test_parallel_withdrawals_cannot_spend_same_note(self):
        self.atm = ATM(self.bank, self.hardware, {20000: 1})
        self.login()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(self.atm.withdraw, [20000, 20000]))
        self.assertCountEqual(results, ['SUCCESS', 'CASH_UNAVAILABLE'])
        self.assertEqual(self.bank.funds, 80000)

    def test_cancel_waits_for_dispensing(self):
        for outcome in ['ALL', 'UNKNOWN']:
            with self.subTest(outcome=outcome):
                self.setUp()
                entered, finish, cancelling = Event(), Event(), Event()
                def dispense(notes):
                    entered.set()
                    if not finish.wait(2): raise AssertionError('Test did not release dispenser')
                    return outcome
                self.hardware.dispense = dispense
                self.login()
                def cancel():
                    cancelling.set()
                    self.atm.cancel()
                with ThreadPoolExecutor(2) as pool:
                    withdrawal = pool.submit(self.atm.withdraw, 20000)
                    try:
                        self.assertTrue(entered.wait(2))
                        cancellation = pool.submit(cancel)
                        self.assertTrue(cancelling.wait(2))
                        with self.assertRaises(FutureTimeout): cancellation.result(timeout=0.05)
                        self.assertEqual(self.hardware.ejections, 0)
                    finally:
                        finish.set()
                    self.assertEqual(withdrawal.result(2), 'SUCCESS' if outcome == 'ALL' else 'PENDING_REVIEW')
                    cancellation.result(2)
                self.assertEqual(self.hardware.ejections, 1)
                state, pending = self.atm.status()
                self.assertEqual(state, 'IDLE' if outcome == 'ALL' else 'OUT_OF_SERVICE')
                self.assertEqual(pending is None, outcome == 'ALL')
                self.assertEqual(self.bank.funds, 80000 if outcome == 'ALL' else 100000)
                self.assertEqual(bool(self.bank.holds), outcome == 'UNKNOWN')

    def test_new_session_uses_new_authenticated_account(self):
        seen = []
        class AccountBank(FakeBank):
            def authenticate(self, card, pin):
                return 'account-' + card if pin == '1234' else None
            def available_balance(self, account):
                seen.append(('balance', account))
                return super().available_balance(account)
            def hold(self, account, amount, operation):
                seen.append(('hold', account))
                return super().hold(account, amount, operation)
        self.atm = ATM(AccountBank(), self.hardware, {20000: 2})
        for card in ['A', 'B']:
            self.atm.insert_card(card)
            self.assertTrue(self.atm.enter_pin('1234'))
            seen.clear()
            self.atm.balance()
            self.assertEqual(self.atm.withdraw(20000), 'SUCCESS')
            self.assertEqual(seen, [('balance', 'account-' + card),
                                    ('hold', 'account-' + card),
                                    ('balance', 'account-' + card)])
            self.atm.cancel()

    def test_owned_stock_and_exact_limit(self):
        stock = {20000: 1}
        self.atm = ATM(self.bank, self.hardware, stock, 20000)
        stock[20000] = 99
        self.login()
        snapshot = self.atm.cash_snapshot()
        snapshot[20000] = 88
        self.assertEqual(self.atm.withdraw(20000), 'SUCCESS')
        self.assertEqual(self.atm.cash_snapshot(), {20000: 0})
        self.assertEqual(self.atm.withdraw(20000), 'CASH_UNAVAILABLE')
        self.assertEqual(self.bank.funds, 80000)
        self.assertEqual(self.hardware.dispensed, [{20000: 1}])

    def test_planner_against_exhaustive_small_inventories(self):
        for counts in itertools.product(range(3), repeat=3):
            inventory = dict(zip([5, 3, 2], counts))
            cash = CashInventory(inventory)
            possible = {sum(d * n for d, n in zip(inventory, combination))
                        for combination in itertools.product(*(range(c + 1) for c in counts))}
            for amount in range(1, 21):
                plan = cash.plan(amount)
                self.assertEqual(plan is not None, amount in possible)
                if plan is not None:
                    self.assertEqual(sum(d*n for d, n in plan.items()), amount)
                    self.assertTrue(all(0 < n <= inventory[d] for d, n in plan.items()))
            self.assertEqual(cash.snapshot(), inventory)


if __name__ == '__main__': unittest.main()
