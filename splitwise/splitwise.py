"""Executable Python reference for the accompanying Splitwise LLD article."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol
from uuid import uuid4


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"Expected an integer >= {minimum}")


def user_id(value):
    if not isinstance(value, str) or not value.strip() or not value.isascii():
        raise ValueError("ID must be a nonempty ASCII string")


class SplitStrategy(Protocol):
    def allocate(self, total: int) -> dict[str, int]: ...


class EqualSplit:
    def __init__(self, participants):
        self._participants = tuple(participants)
        if not self._participants:
            raise ValueError("At least one participant is required")
        for uid in self._participants:
            user_id(uid)
        if len(set(self._participants)) != len(self._participants):
            raise ValueError("Duplicate participant")

    def allocate(self, total):
        integer(total, 1)
        users = sorted(self._participants)
        base, remainder = divmod(total, len(users))
        return {uid: base + (i < remainder) for i, uid in enumerate(users)}


class ExactSplit:
    def __init__(self, amounts):
        self._amounts = dict(amounts)

    def allocate(self, total):
        integer(total, 1)
        if not self._amounts:
            raise ValueError("At least one participant is required")
        for uid, amount in self._amounts.items():
            user_id(uid)
            integer(amount)
        if sum(self._amounts.values()) != total:
            raise ValueError("Shares must sum to the expense total")
        return dict(self._amounts)


class PercentageSplit:
    """Integer basis points: 10000 means 100 percent."""
    def __init__(self, basis_points):
        self._basis_points = dict(basis_points)

    def allocate(self, total):
        integer(total, 1)
        if not self._basis_points:
            raise ValueError("At least one participant is required")
        for uid, weight in self._basis_points.items():
            user_id(uid)
            integer(weight)
        if sum(self._basis_points.values()) != 10000:
            raise ValueError("Percentages must sum to 10000 basis points")

        shares, fractions = {}, {}
        for uid, weight in self._basis_points.items():
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
        members = tuple(members)
        if not members:
            raise ValueError("Group must have members")
        for uid in members:
            user_id(uid)
        if len(set(members)) != len(members):
            raise ValueError("Duplicate group member")
        self._members = frozenset(members)
        self._balances = {}  # (lower ID, higher ID) -> signed minor units
        self._history = []
        self._lock = Lock()

    def _require_members(self, *users):
        for uid in users:
            user_id(uid)
            if uid not in self._members:
                raise ValueError(f"Unknown group member: {uid}")

    @staticmethod
    def _delta(debtor, creditor, amount):
        if debtor < creditor:
            return (debtor, creditor), amount
        return (creditor, debtor), -amount

    def add_expense(self, payer, total, strategy: SplitStrategy):
        integer(total, 1)
        self._require_members(payer)
        # Strategies are trusted pure application components; no shared mutation.
        shares = dict(strategy.allocate(total))
        if not shares:
            raise ValueError("At least one participant is required")
        self._require_members(*shares)
        for amount in shares.values():
            integer(amount)
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
        integer(amount, 1)
        self._require_members(debtor, creditor)
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
        for gid in group_members:
            user_id(gid)
        self._groups = {gid: Group(members) for gid, members in group_members.items()}

    def _group(self, group_id):
        user_id(group_id)
        if group_id not in self._groups:
            raise ValueError("Unknown group")
        return self._groups[group_id]

    def add_expense(self, group_id, payer, total, split_type, participants, values=None):
        group = self._group(group_id)
        user_id(payer)
        integer(total, 1)
        if split_type not in ("EQUAL", "EXACT", "PERCENTAGE"):
            raise ValueError("Unknown split type")
        if participants is None or isinstance(participants, (str, bytes)):
            raise ValueError("Participant list required")
        participants = tuple(participants)
        equal = EqualSplit(participants)  # validates nonempty, unique IDs
        if split_type == "EQUAL":
            if values is not None:
                raise ValueError("Equal splits do not take values")
            strategy = equal
        else:
            if values is None:
                raise ValueError("One value per participant required")
            values = tuple(values)
            if len(values) != len(participants):
                raise ValueError("One value per participant required")
            details = dict(zip(participants, values))
            strategy = (ExactSplit(details) if split_type == "EXACT"
                        else PercentageSplit(details))
        return group.add_expense(payer, total, strategy)

    def record_settlement(self, group_id, debtor, creditor, amount):
        return self._group(group_id).record_settlement(debtor, creditor, amount)

    def get_balances(self, group_id):
        return self._group(group_id).get_balances()

    def get_history(self, group_id):
        return self._group(group_id).get_history()
