import unittest
from concurrent.futures import ThreadPoolExecutor
from itertools import product

from vending_machine import CoinBank, Delivery, PurchaseResult, Slot, VendingMachine


class FakeHardware:
    def __init__(self):
        self.calls = []
        self.escrow = []
        self.product = Delivery.ALL
        self.change = Delivery.ALL
        self.refund = Delivery.ALL

    def accept_coin(self, coin):
        self.escrow.append(coin)

    def collect_escrow(self):
        self.calls.append(("collect", tuple(self.escrow)))
        self.escrow.clear()

    def dispense_product(self, slot_code):
        self.calls.append(("product", slot_code))
        return self.product

    def dispense_change(self, coins):
        self.calls.append(("change", coins))
        if isinstance(self.change, Exception):
            raise self.change
        return self.change

    def return_escrow(self):
        self.calls.append(("refund", tuple(self.escrow)))
        if self.refund == Delivery.ALL:
            self.escrow.clear()
        return self.refund


class VendingMachineTest(unittest.TestCase):
    def setUp(self):
        self.hw = FakeHardware()

    def machine(self, change=None, quantity=1):
        return VendingMachine({"A1": Slot(4, quantity)}, change or {}, self.hw)

    def test_non_greedy_change_is_paid_and_deducted(self):
        vm = self.machine({5: 1, 2: 3}, quantity=2)
        self.assertTrue(vm.insert_coin(10))
        self.assertEqual(vm.buy("A1"), PurchaseResult.SUCCESS)
        self.assertEqual(self.hw.calls, [
            ("product", "A1"), ("change", {2: 3}), ("collect", (10,))
        ])
        self.assertTrue(vm.insert_coin(10))
        self.assertEqual(vm.buy("A1"), PurchaseResult.EXACT_CHANGE_UNAVAILABLE)
        self.assertTrue(vm.cancel())
        self.assertEqual(self.hw.calls[-1], ("refund", (10,)))

    def test_no_change_preserves_original_payment(self):
        vm = self.machine({5: 1, 2: 2})
        vm.insert_coin(10)
        self.assertEqual(vm.buy("A1"), PurchaseResult.EXACT_CHANGE_UNAVAILABLE)
        self.assertEqual(self.hw.calls, [])
        self.assertTrue(vm.cancel())
        self.assertEqual(self.hw.calls, [("refund", (10,))])
        self.assertTrue(vm.cancel())
        self.assertEqual(len(self.hw.calls), 1)

    def test_invalid_selection_credit_and_sold_out_do_not_move_cash(self):
        vm = self.machine()
        self.assertFalse(vm.insert_coin(3))
        self.assertFalse(vm.insert_coin(True))
        vm.insert_coin(2)
        with self.assertRaises(ValueError):
            vm.buy("missing")
        self.assertEqual(vm.buy("A1"), PurchaseResult.INSUFFICIENT_CREDIT)
        self.assertEqual(self.hw.calls, [])
        vm.insert_coin(2)
        self.assertEqual(vm.buy("A1"), PurchaseResult.SUCCESS)
        self.assertEqual(vm.buy("A1"), PurchaseResult.SOLD_OUT)
        self.assertEqual(self.hw.calls, [("product", "A1"), ("collect", (2, 2))])

    def test_limit_rejects_the_extra_coin(self):
        vm = self.machine()
        for _ in range(100):
            self.assertTrue(vm.insert_coin(10))
        self.assertFalse(vm.insert_coin(1))
        vm.cancel()
        self.assertEqual(self.hw.calls, [("refund", (10,) * 100)])

    def test_confirmed_product_failure_keeps_stock_and_credit(self):
        vm = self.machine({2: 3})
        vm.insert_coin(10)
        self.hw.product = Delivery.NONE
        self.assertEqual(vm.buy("A1"), PurchaseResult.NOT_DISPENSED)
        self.assertEqual(self.hw.calls, [("product", "A1")])
        self.hw.product = Delivery.ALL
        self.assertEqual(vm.buy("A1"), PurchaseResult.SUCCESS)

    def test_unknown_product_stops_before_change(self):
        vm = self.machine({2: 3})
        vm.insert_coin(10)
        self.hw.product = Delivery.UNKNOWN
        self.assertEqual(vm.buy("A1"), PurchaseResult.PENDING_REVIEW)
        self.assertFalse(vm._pending.product_delivered)
        self.assertEqual(vm._slots["A1"].quantity, 1)
        with self.assertRaises(RuntimeError):
            vm.cancel()
        self.assertEqual(self.hw.calls, [("product", "A1")])

    def test_change_timeout_keeps_delivery_fact_and_blocks_refund(self):
        vm = self.machine({2: 3})
        vm.insert_coin(10)
        self.hw.change = TimeoutError()
        self.assertEqual(vm.buy("A1"), PurchaseResult.PENDING_REVIEW)
        self.assertTrue(vm._pending.product_delivered)
        self.assertEqual(vm._pending.change, {2: 3})
        self.assertEqual(vm._slots["A1"].quantity, 0)
        self.assertEqual(vm._credit, 10)
        for action in (vm.cancel, lambda: vm.buy("A1"), lambda: vm.insert_coin(1)):
            with self.assertRaises(RuntimeError):
                action()
        self.assertEqual(self.hw.calls, [("product", "A1"), ("change", {2: 3})])

    def test_failed_refund_is_not_repeated(self):
        vm = self.machine()
        vm.insert_coin(5)
        self.hw.refund = Delivery.UNKNOWN
        self.assertFalse(vm.cancel())
        self.assertEqual(vm._credit, 5)
        with self.assertRaises(RuntimeError):
            vm.cancel()
        self.assertEqual(self.hw.calls, [("refund", (5,))])

    def test_concurrent_buy_cannot_sell_last_item_twice(self):
        vm = self.machine()
        vm.insert_coin(2)
        vm.insert_coin(2)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(vm.buy, ["A1", "A1"]))
        self.assertCountEqual(results, [PurchaseResult.SUCCESS, PurchaseResult.SOLD_OUT])
        self.assertEqual(self.hw.calls.count(("product", "A1")), 1)

    def test_planner_against_exhaustive_bundles(self):
        denominations = (1, 2, 5, 10)
        for counts in product(range(3), repeat=4):
            stock = dict(zip(denominations, counts))
            bank = CoinBank(stock)
            possible = {
                sum(coin * count for coin, count in zip(denominations, bundle))
                for bundle in product(*(range(count + 1) for count in counts))
            }
            for amount in range(21):
                plan = bank.plan(amount)
                self.assertEqual(plan is not None, amount in possible)
                if plan is not None:
                    self.assertEqual(sum(coin * count for coin, count in plan.items()), amount)
                    self.assertTrue(all(0 < count <= stock[coin] for coin, count in plan.items()))
            self.assertEqual(bank._counts, stock)


if __name__ == "__main__":
    unittest.main()
