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


def participant_ids(participants):
    if participants is None or isinstance(participants, (str, bytes)):
        raise ValueError("Participant list required")
    users = tuple(participants)
    if not users:
        raise ValueError("At least one participant is required")
    for uid in users:
        user_id(uid)
    if len(set(users)) != len(users):
        raise ValueError("Duplicate participant")
    return users


def split_values(users, values):
    if values is None or isinstance(values, (str, bytes)):
        raise ValueError("One value per participant required")
    values = tuple(values)
    if len(values) != len(users):
        raise ValueError("One value per participant required")
    for value in values:
        integer(value)
    return dict(zip(users, values))


class SplitStrategy(Protocol):
    def allocate(self, total: int, participants, values=None) -> dict[str, int]: ...


class EqualSplit:
    def allocate(self, total, participants, values=None):
        integer(total, 1)
        users = sorted(participant_ids(participants))
        if values is not None:
            raise ValueError("Equal splits do not take values")
        base, remainder = divmod(total, len(users))
        return {uid: base + (i < remainder) for i, uid in enumerate(users)}


class ExactSplit:
    def allocate(self, total, participants, values=None):
        integer(total, 1)
        amounts = split_values(participant_ids(participants), values)
        if sum(amounts.values()) != total:
            raise ValueError("Shares must sum to the expense total")
        return amounts


class PercentageSplit:
    """Integer basis points: 10000 means 100 percent."""
    def allocate(self, total, participants, values=None):
        integer(total, 1)
        basis_points = split_values(participant_ids(participants), values)
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

    def add_expense(self, payer, total, strategy: SplitStrategy, participants, values=None):
        integer(total, 1)
        self._require_members(payer)
        participants = participant_ids(participants)
        self._require_members(*participants)
        values = tuple(values) if values is not None else None
        # Expense inputs are local snapshots; strategies retain no per-call state.
        shares = dict(strategy.allocate(total, participants, values))
        if set(shares) != set(participants):
            raise ValueError("Allocation must contain exactly the participants")
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
        self._strategies = {"EQUAL": EqualSplit(), "EXACT": ExactSplit(),
                            "PERCENTAGE": PercentageSplit()}
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
        if not isinstance(split_type, str) or split_type not in self._strategies:
            raise ValueError("Unknown split type")
        strategy = self._strategies[split_type]
        return group.add_expense(payer, total, strategy, participants, values)

    def record_settlement(self, group_id, debtor, creditor, amount):
        return self._group(group_id).record_settlement(debtor, creditor, amount)

    def get_balances(self, group_id):
        return self._group(group_id).get_balances()

    def get_history(self, group_id):
        return self._group(group_id).get_history()
