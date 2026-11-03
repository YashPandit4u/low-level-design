"""ATM teaching implementation. All amounts are integer paise."""
from __future__ import annotations
from threading import Lock
from typing import Protocol
from uuid import uuid4


class BankGateway(Protocol):
    def authenticate(self, card_id: str, pin: str) -> str | None:
        """Return an account ID, or None for a rejected card/PIN."""
        ...

    def available_balance(self, account_id: str) -> int: ...

    def hold(self, account_id: str, amount: int, operation_id: str) -> bool:
        """Atomically reserve funds. False means definitely declined, no hold."""
        ...

    def capture(self, operation_id: str) -> None:
        """Turn this hold into a posted debit."""
        ...

    def release(self, operation_id: str) -> None:
        """Cancel this hold without debiting the account."""
        ...


class Hardware(Protocol):
    def dispense(self, notes: dict[int, int]) -> str:
        """ALL: exact bundle delivered. NONE: no cash left the machine.
        UNKNOWN: delivery is uncertain, including partial delivery.
        """
        ...

    def eject_card(self) -> None: ...


class CashInventory:
    def __init__(self, notes: dict[int, int]):
        if any(type(d) is not int or d <= 0 or type(n) is not int or n < 0
               for d, n in notes.items()):
            raise ValueError("Invalid denomination or note count")
        self._notes = dict(notes)

    def plan(self, amount: int) -> dict[int, int] | None:
        # The ATM has already validated the amount. Planning changes no stock.
        denominations = sorted(self._notes, reverse=True)
        failed = set()

        def find_bundle(index, remaining):
            if remaining == 0:
                return {}
            if index == len(denominations) or (index, remaining) in failed:
                return None
            denomination = denominations[index]
            limit = min(self._notes[denomination], remaining // denomination)
            for count in range(limit, -1, -1):
                rest = find_bundle(index + 1, remaining - count * denomination)
                if rest is not None:
                    if count:
                        rest[denomination] = count
                    return rest
            failed.add((index, remaining))
            return None

        return find_bundle(0, amount)

    def record_dispensed(self, plan: dict[int, int]) -> None:
        # Only the owning ATM calls this, with its unchanged, successful plan.
        for denomination, count in plan.items():
            self._notes[denomination] -= count

    def snapshot(self) -> dict[int, int]:
        return dict(self._notes)


class ATM:
    def __init__(self, bank: BankGateway, hardware: Hardware,
                 notes: dict[int, int], withdrawal_limit: int = 2000000):
        if type(withdrawal_limit) is not int or withdrawal_limit <= 0:
            raise ValueError("Invalid withdrawal limit")
        self._bank = bank
        self._hardware = hardware
        self._cash = CashInventory(notes)
        self._limit = withdrawal_limit
        self._lock = Lock()
        self._state = "IDLE"
        self._card = None
        self._account = None
        self._attempts = 0
        self._pending = None

    def insert_card(self, card_id: str) -> None:
        with self._lock:
            if self._state != "IDLE":
                raise ValueError("ATM is not available")
            if not isinstance(card_id, str) or not card_id.strip():
                raise ValueError("Card ID required")
            self._card = card_id
            self._attempts = 0
            self._state = "PIN_REQUIRED"

    def enter_pin(self, pin: str) -> bool:
        with self._lock:
            if self._state != "PIN_REQUIRED":
                raise ValueError("Insert a card first")
            if not isinstance(pin, str) or not pin:
                raise ValueError("PIN required")
            try:
                account = self._bank.authenticate(self._card, pin)
            except Exception:
                self._end_session(out_of_service=True)
                raise RuntimeError("Bank unavailable") from None
            if account is None:
                self._attempts += 1
                if self._attempts == 3:
                    self._end_session()
                return False
            self._account = account
            self._state = "READY"
            return True

    def balance(self) -> int:
        with self._lock:
            if self._state != "READY":
                raise ValueError("Authenticate first")
            return self._bank.available_balance(self._account)

    def withdraw(self, amount: int) -> str:
        with self._lock:
            if self._state != "READY":
                raise ValueError("Authenticate first")
            if type(amount) is not int or not 0 < amount <= self._limit:
                raise ValueError("Amount must be positive and within the limit")
            plan = self._cash.plan(amount)
            if plan is None:
                return "CASH_UNAVAILABLE"
            operation_id = str(uuid4())
            self._pending = operation_id
            try:
                if not self._bank.hold(self._account, amount, operation_id):
                    self._pending = None
                    return "DECLINED"
                outcome = self._hardware.dispense(dict(plan))
                if outcome == "NONE":
                    self._bank.release(operation_id)
                    self._pending = None
                    return "NOT_DISPENSED"
                if outcome != "ALL":
                    self._end_session(out_of_service=True)
                    return "PENDING_REVIEW"
                self._cash.record_dispensed(plan)
                self._bank.capture(operation_id)
                self._pending = None
                return "SUCCESS"
            except Exception:
                # A timeout does not prove that the last operation failed.
                self._end_session(out_of_service=True)
                return "PENDING_REVIEW"

    def cancel(self) -> None:
        with self._lock:
            if self._state in ("PIN_REQUIRED", "READY"):
                self._end_session()

    def _end_session(self, out_of_service: bool = False) -> None:
        self._state = "OUT_OF_SERVICE" if out_of_service else "IDLE"
        self._card = None
        self._account = None
        self._attempts = 0
        try:
            self._hardware.eject_card()
        except Exception:
            self._state = "OUT_OF_SERVICE"

    def status(self) -> tuple[str, str | None]:
        with self._lock:
            return self._state, self._pending

    def cash_snapshot(self) -> dict[int, int]:
        with self._lock:
            return self._cash.snapshot()
