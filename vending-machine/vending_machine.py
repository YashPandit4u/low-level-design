"""Single-session vending machine. All amounts are whole rupees."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from threading import Lock
from typing import Protocol


class Delivery(Enum):
    ALL = auto()
    NONE = auto()
    UNKNOWN = auto()


class PurchaseResult(Enum):
    SUCCESS = auto()
    SOLD_OUT = auto()
    INSUFFICIENT_CREDIT = auto()
    EXACT_CHANGE_UNAVAILABLE = auto()
    NOT_DISPENSED = auto()
    PENDING_REVIEW = auto()


@dataclass
class Slot:
    price: int
    quantity: int


@dataclass
class PendingPurchase:
    slot_code: str
    change: dict[int, int]
    product_delivered: bool = False


class Hardware(Protocol):
    def accept_coin(self, coin: int) -> None: ...
    def collect_escrow(self) -> None: ...
    def dispense_product(self, slot_code: str) -> Delivery: ...
    def dispense_change(self, coins: dict[int, int]) -> Delivery: ...
    def return_escrow(self) -> Delivery: ...


class CoinBank:
    DENOMINATIONS = (10, 5, 2, 1)

    def __init__(self, counts: dict[int, int]):
        if any(type(coin) is not int or coin not in self.DENOMINATIONS
               or type(count) is not int or count < 0 for coin, count in counts.items()):
            raise ValueError("Invalid change stock")
        self._counts = dict(counts)

    def plan(self, amount: int) -> dict[int, int] | None:
        reachable = {0: {}}
        for coin in self.DENOMINATIONS:
            next_row = dict(reachable)
            for subtotal, bundle in reachable.items():
                limit = min(self._counts.get(coin, 0), (amount - subtotal) // coin)
                for count in range(1, limit + 1):
                    total = subtotal + count * coin
                    if total not in next_row:
                        next_row[total] = {**bundle, coin: count}
            reachable = next_row
        return reachable.get(amount)

    def record_paid(self, plan: dict[int, int]) -> None:
        for coin, count in plan.items():
            self._counts[coin] -= count


class VendingMachine:
    MAX_CREDIT = 1000

    def __init__(self, slots: dict[str, Slot], change: dict[int, int], hardware: Hardware):
        self._slots = {}
        for code, slot in slots.items():
            if (not code or type(slot.price) is not int or not 0 < slot.price <= self.MAX_CREDIT
                    or type(slot.quantity) is not int or slot.quantity < 0):
                raise ValueError("Invalid slot")
            self._slots[code] = Slot(slot.price, slot.quantity)
        self._coins = CoinBank(change)
        self._hardware = hardware
        self._state: MachineState = IdleState()
        self._credit = 0
        self._pending: PendingPurchase | None = None
        self._lock = Lock()

    def insert_coin(self, coin: int) -> bool:
        with self._lock:
            return self._state.insert_coin(self, coin)

    def buy(self, slot_code: str) -> PurchaseResult:
        with self._lock:
            return self._state.buy(self, slot_code)

    def cancel(self) -> bool:
        with self._lock:
            return self._state.cancel(self)

    def _accept_coin(self, coin: int) -> bool:
        if type(coin) is not int or coin not in CoinBank.DENOMINATIONS:
            return False
        if self._credit + coin > self.MAX_CREDIT:
            return False
        self._hardware.accept_coin(coin)
        self._credit += coin
        return True

    def _slot_for(self, slot_code: str) -> Slot:
        slot = self._slots.get(slot_code)
        if slot is None:
            raise ValueError("Unknown slot")
        return slot


class MachineState(Protocol):
    def insert_coin(self, machine: VendingMachine, coin: int) -> bool: ...
    def buy(self, machine: VendingMachine, slot_code: str) -> PurchaseResult: ...
    def cancel(self, machine: VendingMachine) -> bool: ...


class IdleState:
    def insert_coin(self, machine: VendingMachine, coin: int) -> bool:
        if not machine._accept_coin(coin):
            return False
        machine._state = HasCreditState()
        return True

    def buy(self, machine: VendingMachine, slot_code: str) -> PurchaseResult:
        slot = machine._slot_for(slot_code)
        if slot.quantity == 0:
            return PurchaseResult.SOLD_OUT
        return PurchaseResult.INSUFFICIENT_CREDIT

    def cancel(self, machine: VendingMachine) -> bool:
        return True


class HasCreditState:
    def insert_coin(self, machine: VendingMachine, coin: int) -> bool:
        return machine._accept_coin(coin)

    def buy(self, machine: VendingMachine, slot_code: str) -> PurchaseResult:
        slot = machine._slot_for(slot_code)
        if slot.quantity == 0:
            return PurchaseResult.SOLD_OUT
        if machine._credit < slot.price:
            return PurchaseResult.INSUFFICIENT_CREDIT

        change = machine._coins.plan(machine._credit - slot.price)
        if change is None:
            return PurchaseResult.EXACT_CHANGE_UNAVAILABLE

        pending = PendingPurchase(slot_code, change)
        machine._pending = pending
        try:
            delivery = machine._hardware.dispense_product(slot_code)
            if delivery == Delivery.NONE:
                machine._pending = None
                return PurchaseResult.NOT_DISPENSED
            if delivery == Delivery.ALL:
                slot.quantity -= 1
                pending.product_delivered = True
                if not change or machine._hardware.dispense_change(dict(change)) == Delivery.ALL:
                    machine._coins.record_paid(change)
                    machine._hardware.collect_escrow()
                    machine._credit = 0
                    machine._pending = None
                    machine._state = IdleState()
                    return PurchaseResult.SUCCESS
        except Exception:
            # A lost reply leaves the physical result uncertain.
            machine._state = OutOfServiceState()
            return PurchaseResult.PENDING_REVIEW
        machine._state = OutOfServiceState()
        return PurchaseResult.PENDING_REVIEW

    def cancel(self, machine: VendingMachine) -> bool:
        try:
            if machine._hardware.return_escrow() == Delivery.ALL:
                machine._credit = 0
                machine._state = IdleState()
                return True
        except Exception:
            # A second refund could repeat an uncertain first attempt.
            machine._state = OutOfServiceState()
            return False
        machine._state = OutOfServiceState()
        return False


class OutOfServiceState:
    def insert_coin(self, machine: VendingMachine, coin: int) -> bool:
        raise RuntimeError("Machine is out of service")

    def buy(self, machine: VendingMachine, slot_code: str) -> PurchaseResult:
        raise RuntimeError("Machine is out of service")

    def cancel(self, machine: VendingMachine) -> bool:
        raise RuntimeError("Machine is out of service")
