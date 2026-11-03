"""Executable Python reference for the accompanying Splitwise LLD article."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol
from uuid import uuid4


class SplitStrategy(Protocol):
    """Internal algorithms. Group validates and copies common inputs before calling."""
    def allocate(self, total: int, participants, values=None) -> dict[str, int]: ...


class EqualSplitStrategy:
    def allocate(self, total, participants, values=None):
        users = sorted(participants)
        if values is not None:
            raise ValueError("Equal splits do not take values")
        base, remainder = divmod(total, len(users))
        return {uid: base + (i < remainder) for i, uid in enumerate(users)}


class ExactSplitStrategy:
    def allocate(self, total, participants, values=None):
        if values is None:
            raise ValueError("Split values required")
        amounts = dict(zip(participants, values))
        if sum(amounts.values()) != total:
            raise ValueError("Shares must sum to the expense total")
        return amounts


class PercentageSplitStrategy:
    """Integer basis points: 10000 means 100 percent."""
    def allocate(self, total, participants, values=None):
        if values is None:
            raise ValueError("Split values required")
        basis_points = dict(zip(participants, values))
        if sum(basis_points.values()) != 10000:
            raise ValueError("Percentages must sum to 10000 basis points")

        shares, fractions = {}, {}
        for uid, weight in basis_points.items():
            shares[uid], fractions[uid] = divmod(total * weight, 10000)

        leftover = total - sum(shares.values())
        order = sorted(shares, key=lambda uid: (-fractions[uid], uid))
        for uid in order[:leftover]:
            shares[uid] += 1
        return shares


@dataclass(frozen=True)
class Expense:
    id: str
    payer: str
    total: int
    shares: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Settlement:
    id: str
    debtor: str
    creditor: str
    amount: int


@dataclass(frozen=True)
class Debt:
    debtor: str
    creditor: str
    amount: int


class Group:
    def __init__(self, members):
        if not isinstance(members, (list, tuple)) or not members:
            raise ValueError("Group must have members")
        if any(not isinstance(uid, str) or not uid.strip() for uid in members):
            raise ValueError("Invalid member ID")
        if len(set(members)) != len(members):
            raise ValueError("Duplicate group member")
        self._members = frozenset(members)
        self._balances = {}  # (lower ID, higher ID) -> signed minor units
        self._history = []
        self._lock = Lock()

    @staticmethod
    def _delta(debtor, creditor, amount):
        if debtor < creditor:
            return (debtor, creditor), amount
        return (creditor, debtor), -amount

    def add_expense(self, payer, total, strategy: SplitStrategy, participants, values=None):
        if type(total) is not int or total < 1:
            raise ValueError("Invalid amount")
        if not isinstance(payer, str) or payer not in self._members:
            raise ValueError("Unknown payer")
        if not isinstance(participants, (list, tuple)) or not participants:
            raise ValueError("Participants required")
        participants = tuple(participants)
        if any(not isinstance(uid, str) or not uid.strip() for uid in participants):
            raise ValueError("Invalid participant ID")
        if len(set(participants)) != len(participants):
            raise ValueError("Duplicate participant")
        if not self._members.issuperset(participants):
            raise ValueError("Unknown group participant")
        if values is not None:
            if not isinstance(values, (list, tuple)) or len(values) != len(participants):
                raise ValueError("One value per participant required")
            if any(type(value) is not int or value < 0 for value in values):
                raise ValueError("Split values must be nonnegative integers")
            values = tuple(values)

        # The strategy only needs to check its split-specific rules.
        shares = dict(strategy.allocate(total, participants, values))
        if set(shares) != set(participants):
            raise ValueError("Allocation must contain exactly the participants")
        for amount in shares.values():
            if type(amount) is not int or amount < 0:
                raise ValueError("Invalid amount")
        if sum(shares.values()) != total:
            raise ValueError("Invalid strategy result")

        expense = Expense(str(uuid4()), payer, total, tuple(sorted(shares.items())))
        with self._lock:
            pending = {}
            for participant, amount in shares.items():
                if participant == payer or amount == 0:
                    continue
                pair, delta = self._delta(participant, payer, amount)
                pending[pair] = self._balances.get(pair, 0) + delta
            self._commit(pending, expense)
        return expense

    def record_settlement(self, debtor, creditor, amount):
        if type(amount) is not int or amount < 1:
            raise ValueError("Invalid amount")
        if any(not isinstance(uid, str) or uid not in self._members for uid in (debtor, creditor)):
            raise ValueError("Unknown group member")
        if debtor == creditor:
            raise ValueError("Cannot settle with yourself")
        pair, direction = self._delta(debtor, creditor, 1)
        settlement = Settlement(str(uuid4()), debtor, creditor, amount)

        with self._lock:
            balance = self._balances.get(pair, 0)
            outstanding = direction * balance
            if amount > outstanding:
                raise ValueError("Settlement exceeds debt in this direction")
            self._commit({pair: balance - direction * amount}, settlement)
        return settlement

    def _commit(self, pending, event):
        # Caller holds the group lock; all domain validation precedes this point.
        for pair, balance in pending.items():
            if balance == 0:
                self._balances.pop(pair, None)
            else:
                self._balances[pair] = balance
        self._history.append(event)

    def get_balances(self):
        with self._lock:
            return tuple(
                Debt(a, b, value) if value > 0 else Debt(b, a, -value)
                for (a, b), value in sorted(self._balances.items())
            )

    def get_history(self):
        with self._lock:
            return tuple(self._history)


class SplitwiseService:
    def __init__(self, group_members):
        self._strategies = {"EQUAL": EqualSplitStrategy(), "EXACT": ExactSplitStrategy(),
                            "PERCENTAGE": PercentageSplitStrategy()}
        if any(not isinstance(gid, str) or not gid.strip() for gid in group_members):
            raise ValueError("Invalid group ID")
        self._groups = {gid: Group(members) for gid, members in group_members.items()}

    def add_expense(self, group_id, payer, total, split_type, participants, values=None):
        if not isinstance(group_id, str) or group_id not in self._groups:
            raise ValueError("Unknown group")
        group = self._groups[group_id]
        if not isinstance(split_type, str) or split_type not in self._strategies:
            raise ValueError("Unknown split type")
        strategy = self._strategies[split_type]
        return group.add_expense(payer, total, strategy, participants, values)

    def record_settlement(self, group_id, debtor, creditor, amount):
        if not isinstance(group_id, str) or group_id not in self._groups:
            raise ValueError("Unknown group")
        group = self._groups[group_id]
        return group.record_settlement(debtor, creditor, amount)

    def get_balances(self, group_id):
        if not isinstance(group_id, str) or group_id not in self._groups:
            raise ValueError("Unknown group")
        group = self._groups[group_id]
        return group.get_balances()

    def get_history(self, group_id):
        if not isinstance(group_id, str) or group_id not in self._groups:
            raise ValueError("Unknown group")
        group = self._groups[group_id]
        return group.get_history()
