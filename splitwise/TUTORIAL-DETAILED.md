# Splitwise Low Level Design

## Understanding the problem

💸 An expense-sharing system records money people spend on behalf of a group and tracks who owes whom. If Asha pays ₹900 for dinner shared equally with Ben and Chen, Ben owes Asha ₹300 and Chen owes Asha ₹300. Asha's own ₹300 share creates no debt.

The interesting part starts when Ben pays for breakfast the next morning, someone chooses an unequal split, and two friends record settlements at the same time. We need the arithmetic and the state transitions to stay correct through all of that.

We're designing a scoped, in-memory expense-sharing backend inspired by Splitwise.

## Requirements

Imagine the interviewer opens with:

> Design a system like Splitwise. Users should be able to add shared expenses, see balances, and settle up.

That's enough to recognize the product, but it leaves several important decisions open. Does an expense have one payer or several? Does settlement move money? Can users owe different amounts for the same expense? Before drawing classes, we need answers.

### Clarifying questions

> **You:** Are expenses associated with groups? Do we need to create users and manage group membership?
>
> **Interviewer:** Support multiple groups. Users and group membership are provided at startup. User profiles and membership changes are out of scope.

Good. User identity matters, but we don't need an account-management subsystem. A user ID is enough for this design. The same person can belong to several groups, and balances stay separate between groups.

> **You:** Can multiple people pay for one expense, or should we assume one payer?
>
> **Interviewer:** One payer per expense. The payer must belong to the group. Participants can be any nonempty subset of group members, and the payer doesn't have to participate in the split.

That last detail matters. You can buy concert tickets for your friends without buying one for yourself. The payer's role and the participants' roles are different.

> **You:** Which split types should we support?
>
> **Interviewer:** Equal amounts, explicit amounts per participant, and percentages. Explicit amounts must add up to the expense total. Percentages must add up to 100 percent.

Now we have three actual behaviors, which gives us a reason to consider a splitting interface. We haven't decided where it belongs yet.

> **You:** What currency and precision are we using? How should we handle amounts that don't divide evenly?
>
> **Interviewer:** One currency throughout the system, INR. Store paise as integers. Percentage input supports two decimal places. Distribute leftover paise deterministically so the shares always sum exactly to the expense.

We've settled two separate questions: how money is represented and how rounding works. Saying “use a decimal type” would only answer the first. ₹100 still doesn't divide into three identical amounts at paise precision.

> **You:** Should opposite debts cancel? If Ben owes Asha ₹300 and Asha later owes Ben ₹100, should we show only ₹200?
>
> **Interviewer:** Yes. Net debts between the same two members within a group. Don't simplify debts through a third person yet.

That gives us pairwise netting. We aren't allowed to replace “A owes B, B owes C” with “A owes C” in the base design. Those are different behaviors.

> **You:** Does settling up initiate a bank payment, or record a payment that already happened? Are partial settlements allowed?
>
> **Interviewer:** Record an external payment. Partial settlements are allowed. Reject payments in the wrong direction or above the outstanding debt.

No payment gateway, bank confirmation, or payment-status workflow. The system records the caller's assertion that a payment happened. Authentication and authorization belong at the boundary and are outside this exercise.

> **You:** Do we need history, editing, or deletion? And should concurrent updates be safe?
>
> **Interviewer:** Keep expense and settlement history. No editing or deletion for now. Concurrent updates must be safe, and failed operations must not partially change balances.

Concurrency is part of correctness here. Two simultaneous settlements must not both spend the same outstanding debt.

### Final requirements

1. Support multiple groups with fixed membership configured at startup.
2. Add an expense with one payer and one or more group participants.
3. Support equal, exact-amount, and percentage splits.
4. Represent money in integer paise; every allocation must sum exactly to the total.
5. Net opposite debts between each pair of members within a group.
6. Return current debts as debtor, creditor, and positive amount.
7. Record partial or complete settlements against an existing directed debt.
8. Retain immutable expense and settlement records in group history.
9. Reject invalid operations before changing state and support concurrent access.

Out of scope:

- Payment processing
- Currency conversion
- Account management
- Changing membership
- Expense edits/deletion
- Cross-group netting
- Persistence
- Notifications
- Automatic debt simplification

A person's share can be zero: splitting 1 paise among three people gives 1, 0, and 0. Expenses and settlement payments must still be greater than zero.

## Core entities and relationships

Let's consider the nouns before turning them into classes.

**User.** The identity system is external, and this subsystem only needs membership and IDs. There is no need for a User class containing email addresses, passwords, or payment details. User IDs stay strings.

**Group.** A group owns membership, expense history, and balances. It enforces which users can participate and coordinates state changes. This clearly deserves a class.

**Expense.** An expense records who paid, the total, and each participant's final share. Even without business methods, those fields belong together. We also need to retain them after balances have changed. Expense is an immutable record.

**Settlement.** A settlement records a directed payment between two members. It reduces a debt but does not erase the original expense. Keeping it separate makes the history understandable: dinner happened, then Ben paid Asha back.

**Split.** This word can mean either the rule used to divide an expense or one person's resulting share. We need both concepts, but that doesn't mean both need class hierarchies. A share can be a user ID and an amount. We'll decide how to organize the calculation when we get to class design.

**Balance.** A balance is a changing relationship between two users. We need a representation, but we don't necessarily need a mutable Balance object with its own lifecycle. We'll decide on the data structure during class design. A returned Debt record will keep the public API readable.

**SplitwiseService.** Callers submit expense data and a group ID. This application-level entry point selects a split strategy and routes the operation to that group. It doesn't calculate individual shares or hold every group's lock.

| Entity | Responsibility |
| --- | --- |
| SplitwiseService | Accept request data, select a split strategy, and route operations to the group. |
| Group | Own membership, history, current debt state, and synchronization. |
| SplitStrategy | Calculate a valid allocation without changing group state. |
| Expense | Preserve payer, total, and the final per-person allocation. |
| Settlement | Preserve who paid whom and how much. |
| Debt | Return a positive amount with explicit debtor and creditor. |

The ownership structure is straightforward:

```text
SplitwiseService
  └── groups: group ID → Group
                          ├── member IDs
                          ├── current pair balances
                          └── history: Expense or Settlement

Client sends split type, participants, and optional values
  └── SplitwiseService selects an internal SplitStrategy
        └── Group uses it to produce participant ID → share in paise
```

The strategy is used for one calculation. The resulting Expense stores the amounts, not a mutable strategy that might produce different amounts later.

## Class design

We'll start at the public API, then work down to the object that actually owns the state.

### SplitwiseService

| Requirement | State or operation |
| --- | --- |
| Multiple configured groups | A map from group ID to Group. |
| Add expenses | `addExpense(groupId, payer, total, splitType, participants, values)`. |
| Record settlements | `recordSettlement(groupId, debtor, creditor, amount)`. |
| View balances and history | `getBalances(groupId)` and `getHistory(groupId)`. |

```text
class SplitwiseService:
    - groups: Map<GroupId, Group>       // fixed after construction

    + addExpense(groupId, payer, total, splitType, participants, values) -> Expense
    + recordSettlement(groupId, debtor, creditor, amount) -> Settlement
    + getBalances(groupId) -> List<Debt>
    + getHistory(groupId) -> List<Expense | Settlement>
```

The caller passes a split type and plain data. No request class or strategy object is needed:

```text
splitType: "EQUAL", "EXACT", or "PERCENTAGE"
addExpense(groupId, payer, total, splitType, participants, values)
```

`participants` lists the users sharing the cost. `values` follows the same order:

| Split type | Values |
| --- | --- |
| EQUAL | Omit in Python; pass `null` in Java. |
| EXACT | Each participant's amount in paise, e.g. `[4000, 6000]`. |
| PERCENTAGE | Each participant's percentage in basis points, e.g. `[4000, 6000]` means 40% and 60%. |

Reject duplicate participants, unknown split types, and missing or mismatched values. Equal splits reject extra values. The service selects the strategy; the strategy checks the allocation; Group checks membership and updates debts. Collections are copied before use.

If exposed over HTTP, parse the split type from text and authenticate the caller before invoking this service. Membership checks alone don't authorize access. Return result data, not internal Group or strategy objects. HTTP handling remains outside this exercise.

### Group and balance representation

A group needs its members, history, current balances, and a lock. Before writing those fields down, let's decide what a balance means.

#### Option 1: store each person's net position [Bad fit]

Suppose we store:

```text
Asha: +₹300
Ben:  -₹300
```

Positive means the person should receive money; negative means they owe money. This is compact and useful for debt simplification.

But it loses who owes whom. Consider two histories:

```text
History 1: A owes B ₹300; B owes C ₹300
History 2: A owes C ₹300
```

Both have the same net positions: A owes ₹300, B is net zero, and C should receive ₹300. Our requirements distinguish those histories because we preserve direct pair relationships. Net positions alone cannot answer which settlement is valid.

This representation would be reasonable if the interviewer explicitly wanted only simplified net balances. It isn't enough for our current contract.

#### Option 2: store both directions [Good approach]

We could store `balances[A][B] = 300` and `balances[B][A] = -300`. That makes lookup convenient, but every update must preserve the relationship between two entries.

This is a reasonable design if most queries ask for all debts involving one user: their row already contains the answer. With one group lock, we can update both entries safely. The cost is maintaining two copies of every relationship, including deleting both when a debt reaches zero.

Our API asks for the whole group's balances, so that lookup advantage doesn't help us yet. We can keep one copy instead.

#### Option 3: store one signed balance per unordered pair [Recommended]

Sort the two immutable user IDs and use the ordered pair as a key. For key `(A, B)`:

```text
 +30000 means A owes B ₹300
 -30000 means B owes A ₹300
       0 means neither owes the other; remove the entry
```

The ordering uses IDs, not display names. Renaming “Asha” must not change the direction of an existing balance. Assume normalized ASCII IDs so Python and Java use the same ordering.

Now opposite obligations become ordinary addition. If A owes B ₹300 and a later expense makes B owe A ₹100, the same entry changes from `30000` to `20000`.

We'll use this representation. It gives us one value to update for either direction of a debt. The tradeoff is less obvious arithmetic: a negative number is easy to misread, so we'll centralize the sign conversion in one helper. Finding all debts for one person also requires scanning the pair map unless we add an index later.

The sign convention is internal. Callers receive `Debt(debtor, creditor, positiveAmount)` so UI code doesn't have to understand it.

### History versus current balances

We have two representations of related information. Is that a mistake?

One option is to keep only expense and settlement history and replay it whenever someone asks for balances. This gives one authoritative record of events and makes writes simple. The cost is reading the entire history for every balance query and settlement validation.

We'll keep history plus a balance index. History preserves the facts; the index answers current-debt questions quickly. Every successful mutation updates both under the same group lock. The invariant is:

```text
current balances == replay of accepted history
```

This is controlled duplication. It needs discipline, and replay is a useful way to verify it. We aren't going to add a second map for per-user totals, a third map for creditor lists, and a fourth map for debtor lists without a demonstrated need.

```text
class Group:
    - members: Set<UserId>                  // immutable
    - balances: Map<Pair<UserId>, signed amount>
    - history: List<Expense | Settlement>
    - lock: Lock

    + addExpense(payer, total, strategy) -> Expense
    + recordSettlement(debtor, creditor, amount) -> Settlement
    + getBalances() -> List<Debt>
    + getHistory() -> List<Expense | Settlement>
```

### SplitStrategy

Let's start with the straightforward version: put the split calculation inside `Group.addExpense`.

```text
if splitType == EQUAL:
    shares = divide total among participant IDs
else if splitType == EXACT:
    shares = validate supplied amounts
else if splitType == PERCENTAGE:
    shares = calculate and round percentage amounts

apply shares to balances
```

This works. For three fixed split types, an enum and a helper are defensible. But notice the boundary in that sketch: everything above the blank line decides how much each participant owes; everything below it updates the same ledger, regardless of how those amounts were obtained.

Suppose we add a weighted split for a holiday rental, where one person stayed twice as many nights. The allocation changes, but membership checks, pair netting, history, and settlement rules don't. Separating the calculation lets us add that behavior without editing the ledger code.

That gives us a small Strategy interface:

```text
interface SplitStrategy:
    allocate(total) -> Map<UserId, amount>

EqualSplit(participants)
ExactSplit(amountsByUser)
PercentageSplit(basisPointsByUser)
```

Each strategy copies its configuration when constructed and performs a pure calculation. EqualSplit holds participant IDs. ExactSplit holds proposed amounts. PercentageSplit holds percentages in basis points: `2500` means 25.00%, and `10000` means 100%.

We'll use separate strategies because allocation is a meaningful behavior to test independently. The cost is three small classes and a service-side selection branch. A small switch or type check is enough; a separate factory hierarchy would add little for three modes. Group accepts the resulting strategy internally, while clients only submit split data.

Group still validates the returned allocation. It knows membership; the strategy doesn't. It also verifies that shares are nonnegative integers and sum to the total. A new strategy must not be able to create money by returning invalid shares.

### Expense, Settlement, and Debt

```text
Expense(id, payer, total, sharesByUser)
Settlement(id, debtor, creditor, amount)
Debt(debtor, creditor, amount)
```

All three are immutable. Expense makes a defensive copy of its shares. Returning an immutable object that contains a mutable map would not be sufficient.

Why store final amounts instead of just percentages? Because the expense needs an exact, stable allocation. If our rounding policy changes next month, last month's dinner must not quietly shift a paise between friends.

Why no `settle()` method on Expense? A settlement applies to the current net debt between two people. That debt may come from several expenses in both directions. Group has that information; one Expense does not.

### Final class design

Here's the design assembled in one place. Follow an expense from the service down: the service validates the request and selects a strategy, the group asks that strategy for shares, and the group records the resulting debt changes.

```text
splitType: "EQUAL", "EXACT", or "PERCENTAGE"

SplitwiseService
  groups: Map<GroupId, Group>
  addExpense(groupId, payer, total, splitType, participants, values) -> Expense
  recordSettlement(groupId, debtor, creditor, amount) -> Settlement
  getBalances(groupId) -> List<Debt>
  getHistory(groupId) -> List<Event>

Group
  members: immutable Set<UserId>
  balances: Map<(lowerId, higherId), signed paise>
  history: List<Event>
  lock
  addExpense(payer, total, strategy) -> Expense
  recordSettlement(debtor, creditor, amount) -> Settlement
  getBalances() -> List<Debt>
  getHistory() -> List<Event>

SplitStrategy.allocate(total) -> Map<UserId, paise>
  EqualSplit(participants)
  ExactSplit(amountsByUser)
  PercentageSplit(basisPointsByUser)

Event = Expense | Settlement
Expense(id, payer, total, immutable sharesByUser)
Settlement(id, debtor, creditor, amount)
Debt(debtor, creditor, positive amount)
```

The key invariants are worth saying aloud before implementing:

1. An expense's shares sum exactly to its positive total.
2. Every referenced user belongs to the group.
3. Nobody owes themselves.
4. Each pair has at most one nonzero signed balance.
5. A settlement only reduces an existing debt in the specified direction.
6. History and the balance index change together.

Those statements give us a concrete standard for deciding whether the code is correct.

## Implementation

Start by getting one equal expense all the way through the system. Then add exact and percentage allocation, followed by settlement. That gives you a working flow before spending time on the trickiest rounding rule. Request records can be sketched; allocation and atomic debt updates deserve the implementation time.

For the walkthrough below, we'll group the three allocation algorithms together so you can compare them. Keep this example in mind:

```text
Asha pays ₹900 for Asha, Ben, and Chen
        ↓ splitType=EQUAL, participants=[A, B, C]
Service validates the request and constructs EqualSplit
        ↓ Group calls EqualSplit.allocate
shares: Asha ₹300, Ben ₹300, Chen ₹300
        ↓ Group ignores the payer's own share
Ben owes Asha ₹300; Chen owes Asha ₹300
        ↓ Group stores the expense and updates both pairs together
one history record, two current debts
```

The strategy never needs to know who paid. It answers how the cost is shared. The group turns those shares into obligations to the payer.

The snippets below use Python and Java-style pseudocode. They share the same semantics. Complete executable reference implementations are linked later. Expected validation failures happen before mutation; process crashes and allocation failures require persistence and transactional recovery, which are outside this in-memory exercise.

### SplitwiseService

The caller supplies data; the service chooses the calculation:

Python:

```python
service.add_expense("trip", "A", 90000, "EQUAL", ["A", "B", "C"])
```

Java:

```java
service.addExpense("trip", "A", 90000, "EQUAL", List.of("A", "B", "C"), null);
```

After validating the split type, participant IDs, and value count, the selection is small:

Python:

```python
if split_type == "EQUAL":
    strategy = EqualSplit(participants)
elif split_type == "EXACT":
    strategy = ExactSplit(dict(zip(participants, values)))
else:  # PERCENTAGE; unknown types were already rejected
    strategy = PercentageSplit(dict(zip(participants, values)))
return group.add_expense(payer, total, strategy)
```

Java:

```java
SplitStrategy strategy = switch (splitType) {
    case "EQUAL" -> new EqualSplit(participants);
    case "EXACT" -> new ExactSplit(amountsByUser(participants, values));
    case "PERCENTAGE" -> new PercentageSplit(basisPointsByUser(participants, values));
    default -> throw new IllegalArgumentException("Unknown split type");
};
return group.addExpense(payer, total, strategy);
```

The map helpers pair each participant with their value; percentage values must be between 0 and 10000 before conversion to Java integers. Reject duplicates and length mismatches before making a map, or entries could be overwritten or silently dropped. The complete implementations include these checks.

Group accepts a strategy internally. The public service accepts a split-type string and plain expense data. We don't need a factory class or a request-object hierarchy for this.

### SplitStrategy

All three strategies return the same result: each participant's share in paise. Let's implement their calculations before connecting them to the group ledger.

#### EqualSplit and the missing paise

The first version most people write is `total / numberOfPeople`. That works until the division has a remainder.

For ₹100 among three people, the input is 10,000 paise:

```text
base share = 10000 // 3 = 3333
remainder  = 10000 % 3  = 1

A: 3334, B: 3333, C: 3333
Total: 10000
```

Sort the participant IDs and give one extra paise to each of the first `remainder` participants. This is deterministic and independent of request-list order. It does favor lower IDs across repeated ties; rotating that priority would be a different business policy requiring additional state.

Python:

```python
def allocate(total, participants):
    require(total > 0)
    require(participants and no_duplicates(participants))
    users = sorted(participants)
    base, remainder = divmod(total, len(users))
    return {
        uid: base + (1 if i < remainder else 0)
        for i, uid in enumerate(users)
    }
```

Java:

```java
Map<String, Long> allocate(long total, List<String> participants) {
    require(total > 0 && !participants.isEmpty());
    require(noDuplicates(participants));
    var users = sortedCopy(participants);
    long base = total / users.size();
    long remainder = total % users.size();
    Map<String, Long> shares = new HashMap<>();
    for (int i = 0; i < users.size(); i++) {
        shares.put(users.get(i), base + (i < remainder ? 1 : 0));
    }
    return shares;
}
```

Do not silently turn a duplicated participant list into a set. If the input contains A twice, that could be a caller bug or an attempted weighting scheme. Our equal-split contract requires unique participants, so reject it.

#### ExactSplit

Exact splitting is validation, not an allocation algorithm. The caller already supplied the answer.

Python:

```python
def allocate(total, amounts):
    require(total > 0 and amounts)
    require(all(is_integer(x) and x >= 0 for x in amounts.values()))
    require(sum(amounts.values()) == total)
    return dict(amounts)  # defensive copy
```

Java:

```java
Map<String, Long> allocate(long total, Map<String, Long> amounts) {
    require(total > 0 && !amounts.isEmpty());
    long sum = 0;
    for (long amount : amounts.values()) {
        require(amount >= 0);
        sum = Math.addExact(sum, amount);
    }
    require(sum == total);
    return Map.copyOf(amounts);
}
```

The Java version uses checked addition. An overflow must reject the operation instead of wrapping into a plausible-looking total. Python's integers can grow beyond a fixed machine word, but the API must still reject fractional amounts and booleans masquerading as integers.

At the request boundary, reject duplicate user IDs before constructing a map. Once duplicates have overwritten each other in a map, the allocation layer can't recover the original input.

#### PercentageSplit and rounding fairly

For percentages, independently rounding each result is unsafe. Take 101 paise split 33.33%, 33.33%, and 33.34%. The exact shares are 33.6633, 33.6633, and 33.6734 paise. Rounding each to the nearest paise gives 34 + 34 + 34 = 102. We've charged the group an extra paise.

We'll use the largest-remainder method. Compute every exact quota using integer arithmetic, allocate its floor, then give leftover paise to the largest fractional remainders. Break ties using user ID.

For 101 paise split 33.33%, 33.33%, and 33.34%:

| User | Basis points | Exact quota in paise | Floor | Fractional remainder numerator |
| --- | ---: | ---: | ---: | ---: |
| A | 3333 | 33.6633 | 33 | 6633 |
| B | 3333 | 33.6633 | 33 | 6633 |
| C | 3334 | 33.6734 | 33 | 6734 |

The floors sum to 99. Two paise remain. C gets the first; A wins the tie for the second. Final shares are A=34, B=33, C=34.

Python:

```python
def allocate(total, basis_points):
    require(total > 0 and basis_points)
    require(all(is_integer(w) and w >= 0 for w in basis_points.values()))
    require(sum(basis_points.values()) == 10000)

    shares, fractions = {}, {}
    for uid, weight in basis_points.items():
        shares[uid], fractions[uid] = divmod(total * weight, 10000)

    leftover = total - sum(shares.values())
    order = sorted(shares, key=lambda uid: (-fractions[uid], uid))
    for uid in order[:leftover]:
        shares[uid] += 1
    return shares
```

Java:

```java
Map<String, Long> allocate(long total, Map<String, Integer> bps) {
    validatePositiveTotalAndPercentages(total, bps); // nonempty, sum = 10000
    Map<String, Long> shares = new HashMap<>();
    Map<String, Long> fractions = new HashMap<>();
    long allocated = 0;

    for (var entry : bps.entrySet()) {
        // Widen before multiplication so total * weight cannot overflow long.
        BigInteger numerator = BigInteger.valueOf(total)
            .multiply(BigInteger.valueOf(entry.getValue()));
        BigInteger[] qr = numerator.divideAndRemainder(BigInteger.valueOf(10000));
        long share = qr[0].longValueExact();
        shares.put(entry.getKey(), share);
        fractions.put(entry.getKey(), qr[1].longValueExact());
        allocated = Math.addExact(allocated, share);
    }

    var order = sortByRemainderDescendingThenIdAscending(fractions);
    long leftover = total - allocated;
    for (int i = 0; i < leftover; i++) {
        String uid = order.get(i);
        shares.put(uid, shares.get(uid) + 1);
    }
    return shares;
}
```

Because the percentages sum to 100%, the floors cannot exceed the total. The sum of the fractional parts is the integer number of remaining paise, and it is smaller than the participant count. Each selected participant therefore needs at most one additional paise.

Notice that a 0% participant gets no fractional remainder and no allocation. The method doesn't need a separate special case for them.

### Group

The group turns allocations into debts and records settlements. Its methods share one sign convention and one lock, so we'll establish those helpers before following the two mutation paths.

#### Translating a share into debt

Every participant owes their allocated share to the payer, except when the participant is the payer. We need one helper to translate that directed obligation into our canonical key and sign.

Python:

```python
def debt_delta(debtor, creditor, amount):
    if debtor < creditor:
        return (debtor, creditor), amount
    return (creditor, debtor), -amount
```

Java:

```java
record Pair(String lower, String higher) {}
record Delta(Pair pair, long value) {}

Delta debtDelta(String debtor, String creditor, long amount) {
    return debtor.compareTo(creditor) < 0
        ? new Delta(new Pair(debtor, creditor), amount)
        : new Delta(new Pair(creditor, debtor), -amount);
}
```

Callers exclude self-debts before using this helper. Keeping the sign conversion in one place prevents expenses and settlements from developing subtly different conventions.

#### Group.addExpense

We now know how to calculate shares. The next job is to accept all of an expense together. If Ben's debt changes but Chen's doesn't, we haven't recorded a smaller expense; we've recorded a broken one.

The normal flow is:

1. Validate the payer and total.
2. Ask the strategy for shares and validate its result.
3. Create an immutable Expense record.
4. Under the group lock, calculate new balances for affected pairs.
5. Commit those balances and append the record to history.

Important failures include an unknown payer, a nonmember participant, an empty allocation, a negative share, and a total mismatch. None should alter the group.

Python:

```python
def add_expense(self, payer, total, strategy):
    require_positive_integer(total)
    self.require_member(payer)
    shares = dict(strategy.allocate(total))
    self.validate_allocation(total, shares)
    expense = Expense(new_id(), payer, total, immutable_copy(shares))

    with self.lock:
        pending = {}
        for participant, amount in shares.items():
            if participant == payer or amount == 0:
                continue
            pair, delta = debt_delta(participant, payer, amount)
            pending[pair] = self.balances.get(pair, 0) + delta

        self.commit(pending, expense)
    return expense
```

Java:

```java
Expense addExpense(String payer, long total, SplitStrategy strategy) {
    require(total > 0);
    requireMember(payer);
    var shares = Map.copyOf(strategy.allocate(total));
    validateAllocation(total, shares);
    var expense = new Expense(newId(), payer, total, shares);

    synchronized (lock) {
        Map<Pair, Long> pending = new HashMap<>();
        for (var entry : shares.entrySet()) {
            if (entry.getKey().equals(payer) || entry.getValue() == 0) continue;
            var d = debtDelta(entry.getKey(), payer, entry.getValue());
            long next = Math.addExact(balances.getOrDefault(d.pair(), 0L), d.value());
            require(next != Long.MIN_VALUE); // magnitude must be representable
            pending.put(d.pair(), next);
        }
        commit(pending, expense);
    }
    return expense;
}
```

`validateAllocation` checks nonempty shares, membership, nonnegative integer amounts, and an exact sum. These are the rules the group must enforce even if a strategy contains a bug.

Why calculate `pending` first? In Java, checked arithmetic can fail. If we update Ben's balance and then discover overflow while updating Chen's, we have a partial expense. Preparing every new value before writing prevents that. Each participant produces at most one pair because there is exactly one payer and participants are unique.

Allocation happens outside the lock because it is a pure calculation and membership never changes in this version. Balance updates depend on current state and belong inside. This division keeps the critical section small without weakening correctness.

#### Committing balances and history together

The `pending` map contains replacement balances, not deltas. For each affected pair, we've already combined the old balance with the new obligation. The remaining work is deliberately mechanical:

Python:

```python
def commit(self, pending, event):  # private; caller holds the group lock
    for pair, balance in pending.items():
        if balance == 0:
            self.balances.pop(pair, None)
        else:
            self.balances[pair] = balance
    self.history.append(event)
```

Java:

```java
private void commit(Map<Pair, Long> pending, Event event) {
    // Caller holds the group lock; validation and arithmetic are complete.
    for (var entry : pending.entrySet()) {
        if (entry.getValue() == 0) balances.remove(entry.getKey());
        else balances.put(entry.getKey(), entry.getValue());
    }
    history.add(event);
}
```

No business validation belongs here: a rejection after the first write would leave a partial update. Readers take the same lock, so they cannot observe the interval between updating the pairs and appending history. This is atomic visibility within our process, not crash recovery. Durable all-or-nothing writes need a database transaction, which we'll discuss in the follow-ups.

#### Concurrency tradeoffs

##### Rely on a thread-safe map [Incorrect]

A concurrent map can protect individual operations. It doesn't make an entire expense atomic, and it doesn't combine a settlement's validation with its deduction.

```text
Ben owes Asha ₹100.
Thread 1 checks: ₹100 outstanding, payment of ₹80 is valid.
Thread 2 checks: ₹100 outstanding, payment of ₹80 is valid.
Both record success.
```

We have recorded ₹160 against a ₹100 debt. Depending on the update code, the balance may become negative or one deduction may overwrite the other. Neither result satisfies the contract.

##### One service-wide lock [Good approach]

This serializes every group. It is easy to implement, but adding dinner in one group blocks a completely unrelated group's settlement. There is no shared debt state between them, so that coordination is unnecessary.

##### One lock per group [Recommended]

An expense may change several pairs and history together. A group lock covers that whole consistency boundary. Independent groups proceed concurrently, while related operations observe complete updates.

Per-pair locks are possible, but a multi-participant expense then needs multiple locks in a stable order, history needs coordinated updates, and readers need consistent snapshots. That's a substantial complexity increase. Start with a group lock; consider finer granularity only when a measured workload justifies it.

#### Group.recordSettlement

A settlement is not a negative expense. It has its own rule: there must already be enough debt in the requested direction.

We convert the direction into `+1` or `-1`, then interpret the stored balance through it. If `(A, B)` stores `-15000`, B owes A ₹150. For B paying A, the direction is `-1`, so the outstanding amount is `(-1) × (-15000) = 15000`.

Python:

```python
def record_settlement(self, debtor, creditor, amount):
    require_positive_integer(amount)
    self.require_members(debtor, creditor)
    require(debtor != creditor)
    pair, direction = debt_delta(debtor, creditor, 1)
    event = Settlement(new_id(), debtor, creditor, amount)

    with self.lock:
        balance = self.balances.get(pair, 0)
        outstanding = direction * balance
        require(amount <= outstanding)
        self.commit({pair: balance - direction * amount}, event)
    return event
```

Java:

```java
Settlement recordSettlement(String debtor, String creditor, long amount) {
    require(amount > 0);
    requireMembers(debtor, creditor);
    require(!debtor.equals(creditor));
    var d = debtDelta(debtor, creditor, 1);
    var event = new Settlement(newId(), debtor, creditor, amount);

    synchronized (lock) {
        long balance = balances.getOrDefault(d.pair(), 0L);
        long outstanding = d.value() * balance;
        require(amount <= outstanding);
        commit(Map.of(d.pair(), balance - d.value() * amount), event);
    }
    return event;
}
```

The positive-amount check and `amount <= outstanding` reject absent debts and payments in the wrong direction. An exact settlement produces zero, so `commit` removes the pair. A partial settlement leaves a smaller debt in the same direction.

Creating the event before acquiring the lock doesn't record anything. It's just a local object. If validation fails inside the lock, that object is discarded and history remains unchanged.

#### Reading balances and history

Reads use the same group lock. Otherwise a balance query could see Ben's updated share but Chen's old one halfway through an expense.

For each positive pair balance, return lower ID as debtor; for a negative balance, reverse the IDs and return the magnitude. Return a detached immutable collection of Debt records. History likewise returns a snapshot containing immutable records.

The caller can keep or display a snapshot after the lock is released. It may become stale as new expenses arrive, which is normal. It cannot corrupt the group's internal state. Separate calls to `getBalances` and `getHistory` are separate snapshots; if a client needs them from the same instant, expose one combined snapshot method.

#### Complexity

Let `k` be expense participants, `b` the group's nonzero debt pairs, and `h` its history length.

| Operation | Time | Additional observation |
| --- | --- | --- |
| Equal split | O(k log k) | Sorting makes remainder allocation deterministic. |
| Exact split | O(k) | Validate and copy shares. |
| Percentage split | O(k log k) | Sort by fractional remainder and ID. |
| Apply allocation | O(k) average | Hash lookups and pending updates; history append amortized O(1). |
| Record settlement | O(1) average | One pair update and one history append. |
| Sorted balance snapshot | O(b log b) | O(b) output space. |
| History snapshot | O(h) | Copies references to immutable records. |

The arithmetic bounds assume ordinary bounded monetary inputs; arbitrarily large integers have their own digit-dependent cost. History storage grows with all retained events and their allocations, not just the number of members. Pagination and archival are natural production additions.

### Complete reference implementations

- [Python implementation](splitwise.py): standard library only, including all strategies, records, Group, and service routing.
- [Java implementation](Splitwise.java): Java 17+, with immutable records, checked arithmetic, and equivalent operations. `Splitwise` is the service class name in this file.
- [Python verification suite](test_splitwise.py): rounding, ledger replay, settlement validation, isolation, and concurrent updates.
- [Java verification suite](SplitwiseTest.java): rounding, conservation, netting, settlements, overflow rejection, and competing settlements.

The implementations are deliberately small enough to read together with the article. They implement the base requirements; the following extensions are design discussions.

Run the checks from this article's directory:

```sh
python3 -m unittest -v

# JDK 17 or newer
javac --release 17 -d /tmp/splitwise-classes Splitwise.java SplitwiseTest.java
java -cp /tmp/splitwise-classes SplitwiseTest
```

## Verification

Let's follow complete state changes rather than just calling methods and hoping the output looks reasonable. Use IDs A, B, and C for Asha, Ben, and Chen.

Before tracing the ledger, call the service with each split type and verify the shares. Reject unknown types, duplicate participants, mismatched value counts, invalid totals, and nonmembers without changing balances or history. Changing the caller's lists after a call must not alter the stored expense.

### Test case 1: equal expense followed by an opposite debt

The group starts empty. A pays ₹900 for A, B, and C.

```text
service.addExpense(trip, A, 90000, "EQUAL", [A, B, C], null)

Allocation: A=30000, B=30000, C=30000
A's own share: no debt
B owes A 30000 → pair (A,B) gets -30000
C owes A 30000 → pair (A,C) gets -30000

Public balances:
  B owes A ₹300
  C owes A ₹300
History: one expense
```

Now B pays ₹300, split equally between A and B:

```text
Allocation: A=15000, B=15000
A owes B 15000 → add +15000 to (A,B)
Existing (A,B): -30000
New (A,B): -15000

Public balances:
  B owes A ₹150
  C owes A ₹300
History: two expenses
```

Both expenses remain in history. Only their current net effect is reduced.

### Test case 2: partial settlement and overpayment rejection

Continue from that state. B records a ₹100 payment to A:

```text
pair = (A,B), direction = -1
balance = -15000
outstanding = 15000
payment = 10000 → accepted
new balance = -15000 - (-1 × 10000) = -5000

B now owes A ₹50.
History: two expenses and one settlement.
```

If B next attempts ₹60, reject it. The balance stays at ₹50 and no history record is appended. If A tries paying B, reject that too: the debt points the other way. Paying exactly ₹50 removes the pair without deleting its history.

### Test case 3: rounding and payer exclusion

An equal 10,000-paise split among A, B, C produces 3334, 3333, 3333. Reordering the input participants produces the same allocation.

The percentage example produces 34, 33, 34 from 101 paise and weights 3333, 3333, 3334. In both cases, summing the stored shares exactly reproduces the expense total.

For a separate expense where A pays ₹200 entirely for B and C, pass `EQUAL` with participants `[B, C]`. Both owe A ₹100. We do not force A into the participant set or invent an A share.

### Test case 4: malformed allocations do nothing

Start with B owing A ₹50 and three existing history records. Try an exact ₹100 expense with A=₹40 and B=₹50:

```text
Service validates the inputs, finds the group, and selects ExactSplit.
Group validates payer A and total 10000.
ExactSplit adds the supplied shares: 4000 + 5000 = 9000.
9000 != 10000 → reject.
Group never reaches commit.

Afterward: B still owes A ₹50; history still contains three records.
```

Now try a different failure: an exact allocation totaling ₹100, but containing user D, who isn't a member. The strategy can calculate that allocation successfully. Group must reject it during membership validation, before changing any pair. This checks the boundary between allocation rules and group rules.

Also reject a negative share, an empty split, and percentages summing to 99.99%.

Compare both balances and history before and after each failure. Checking only the exception is insufficient; a method can throw after it has already damaged state.

### Test case 5: competing settlements

Reset the group so B owes A ₹100. Two threads each attempt to record ₹80.

```text
Thread 1 acquires the group lock.
Thread 2 waits.

Thread 1 reads outstanding = ₹100.
Thread 1 accepts ₹80 and records remaining debt = ₹20.
Thread 1 appends its settlement and releases the lock.

Thread 2 acquires the lock.
Thread 2 reads outstanding = ₹20.
Thread 2 rejects ₹80 without mutation.

Result: exactly one new settlement, ₹20 still owed.
```

Which thread wins is unspecified. The invariant holds either way.

### Test case 6: reconstruct the balance index

Replay each expense by adding every nonpayer share to the corresponding pair. Replay each settlement by subtracting its directed amount. Remove zero entries. Compare that reconstructed map with the live balance snapshot.

This checks the relationship between history and balances across a sequence of operations. It is stronger than testing a single helper in isolation. Also verify that operations in one group do not change another group containing the same user IDs.

## Extensibility

The basic design is enough for a substantial interview. If there is time, these follow-ups test different kinds of reasoning: graph transformations, retry semantics, reversibility, and richer payment inputs.

### How would you simplify debts to reduce payments?

Suppose A owes B ₹300 and B owes C ₹300. Rather than making two payments, A could pay C directly. Everyone's net financial position would be the same.

> I'd derive each person's net position from the pair balances, then match debtors with creditors. I would first expose this as a proposed payment plan. Applying that plan needs explicit semantics because it changes who is allowed to settle with whom.

For every debt from debtor D to creditor C of amount X, subtract X from D's net position and add X to C's. Positive balances represent money to receive. Negative balances represent money to pay.

```python
net = {uid: 0 for uid in members}
for debt in balance_snapshot:
    net[debt.debtor] -= debt.amount
    net[debt.creditor] += debt.amount

debtors = sorted((uid, -n) for uid, n in net.items() if n < 0)
creditors = sorted((uid, n) for uid, n in net.items() if n > 0)

# Mutable entries so we can consume each outstanding position.
debtors = [list(item) for item in debtors]
creditors = [list(item) for item in creditors]
payments = []
i = j = 0
while i < len(debtors) and j < len(creditors):
    amount = min(debtors[i][1], creditors[j][1])
    payments.append(Debt(debtors[i][0], creditors[j][0], amount))
    debtors[i][1] -= amount
    creditors[j][1] -= amount
    if debtors[i][1] == 0:
        i += 1
    if creditors[j][1] == 0:
        j += 1
```

In our example, B's net position is zero, so B disappears from both lists. The only match is A paying C ₹300. With more people, the same loop consumes one or both positions on each iteration. Building the positions takes O(b), sorting takes O(m log m), and matching takes O(m), where `b` is the number of current debt pairs and `m` the number of nonzero positions.

Each payment clears at least one remaining position. With `m` nonzero positions, this produces at most `m - 1` payments. It does not guarantee the globally smallest possible number of transactions. Don't advertise a minimum-transaction algorithm unless you've actually solved that harder optimization problem.

There is a subtle integration issue. In the original graph, A has no direct debt to C, so our base `recordSettlement(A, C, amount)` correctly rejects the suggested payment. Showing a simplified plan does not automatically make the ledger able to accept it.

One option is an explicit, audited debt-restructuring operation that atomically replaces pair balances with the proposed equivalent graph. That operation must appear in history so replay still works, preserve every user's net position, and verify the group hasn't changed since the plan was calculated, for example with a group version. Another option records the direct payment while applying reductions along the agreed original debt path. Either way, the product must define whether members consent to changing their counterparties.

For an interview, explain the proposal algorithm and this integration boundary. A greedy loop by itself is not a complete simplification feature.

### What if the client retries after a timeout?

Our generated event ID identifies an accepted record. It doesn't stop duplicate submissions. If an expense succeeded but the response was lost, retrying it currently adds the expense again.

> I'd require a caller-generated operation ID for mutations. Under the group lock, I'd look it up before applying the operation. An identical retry returns the original result; reuse with different input is rejected.

```text
Group:
    processedOperations: Map<OperationId, (requestFingerprint, result)>

mutate(operationId, request):
    validate and canonicalize request
    lock group
        if operationId exists:
            require stored fingerprint == request fingerprint
            return stored result
        validate against current state
        apply balances and append event
        remember operationId, fingerprint, result
        return result
```

The lookup, mutation, and operation record must share the same consistency boundary. For settlements, check for a successful retry before rejecting it against the now-reduced debt.

Fingerprint semantic request data, including operation type, group, users, amount, and normalized split configuration. An expense's split mode may matter even when two modes happen to produce the same allocation. In a persistent implementation, use a transaction and a uniqueness constraint scoped to the group and operation ID.

The idempotency map also needs a retention policy. Removing an old key means a sufficiently late retry may become a new operation. That is an API guarantee to define, not an arbitrary cache tuning detail.

### How would you edit or delete an expense?

Updating the Expense object is the wrong starting point because it has already contributed to current balances. Removing it from history without undoing that contribution leaves the index inconsistent.

> I'd preserve the original record and append a correction. Under one group lock, reverse the original allocation, apply the replacement, and record the correction linking both versions. I'd prevent the same version from being reversed twice.

For deletion, there is no replacement allocation. For editing, validate the entire replacement before modifying any balances. A stable expense ID plus a revision number helps detect two people editing the same version concurrently.

Existing settlements make this interesting. Suppose Ben owed Asha ₹100, paid it, and the expense is later deleted. Reversing that expense now makes Asha owe Ben ₹100. That's an intelligible refund obligation, but the product needs to accept that policy explicitly.

```text
Original expense: (A,B) = -10000     B owes A ₹100
Settlement:      (A,B) += 10000     balance is zero
Delete expense:  (A,B) += 10000     A now owes B ₹100
```

The settlement remains in history because the payment really happened. The correction reverses the expense's contribution, not the entire pair balance. Resetting that pair to zero would erase the refund obligation and could also erase unrelated expenses.

An alternative is to prohibit edits after settlement, but settlements net across expenses, so determining which expense has been “settled” would require a new allocation model. This is why append-only corrections often fit the existing design better.

### How would you support multiple payers?

Replace the single payer field with a map of `paidByUser`. Require its amounts to be nonnegative and sum to the expense total. The shares still sum to the same total.

For each user, compute:

```text
net contribution = amount paid - allocated share
```

A positive contribution means the user should receive money; a negative contribution means they owe money. Match debtors and creditors using a documented deterministic rule to create this expense's pair obligations.

The allocation is not unique when several people paid and several people owe. Choose a policy, such as ascending ID matching, and store the resulting obligation edges in the expense record. That preserves replay behavior even if the matching policy changes later.

This matching is within one new expense, where we must choose counterparties. It does not silently simplify existing debts across the whole group.

### How would you add persistence or multiple currencies?

These are separate changes.

For persistence, store events and balance rows in one database transaction. A process-local group lock cannot coordinate multiple application instances. Use database concurrency control, such as locking a group row or checking a group version, with retries for conflicts. Keep idempotency records in that same transaction. Avoid holding a database transaction open while a person authorizes a bank transfer; actual payment processing needs its own workflow.

For currencies, never add INR and USD balances together. Introduce a Money value containing currency and minor-unit amount, and partition debt keys by currency. Minor-unit precision is currency-specific; don't hardcode “two decimal places” globally. If conversion is required, record the chosen exchange rate, conversion time, and rounding policy as part of the accepted operation. Conversion changes the accounting semantics and deserves its own requirements discussion.

## What is expected at each level?

These are useful practice targets for this problem, rather than universal hiring rules.

### Junior

Aim for a working equal-split flow with a sensible service/group boundary. You should exclude the payer's own share from debt, record current balances, and support a valid settlement. Basic validation matters: reject unknown users, invalid amounts, and shares that don't add up. It's reasonable to need a hint about distributing leftover paise or netting opposite debts, but you should be able to trace the resulting arithmetic.

### Mid-level

You should independently distinguish expense history from current balances and implement all three splitting modes with exact totals. The pairwise sign convention should be consistent, records should be immutable, and partial settlements should reject overpayment. Explain the strategy-versus-switch tradeoff without treating a pattern as mandatory. Recognize the concurrent settlement race and protect the check and update together. Verification should include rejected operations leaving state unchanged.

### Senior

Drive the discussion around invariants and scope. Explain why pair balances and per-user net positions answer different questions, why a group is the atomic update boundary, and why a thread-safe map alone is insufficient. Catch rounding, overflow, defensive-copy, and retry issues without prompting. For extensions, discuss how simplified payments interact with the original ledger, how corrections affect settled expenses, and how persistence changes concurrency guarantees. The strongest answer connects these choices to explicit requirements while keeping the base design small enough to implement and verify.

## Test your understanding

1. Why doesn't a user's net position tell us whom they owe?
2. How do you split one paise equally among three people without creating or losing money?
3. Why must settlement validation happen inside the same lock as the balance update?
4. Why does an automatically generated Expense ID fail to prevent duplicate retries?
5. If a suggested simplified payment has no direct pair debt, what must change before recording it?

If you can answer those with concrete examples, you understand the parts of this design that matter most.
