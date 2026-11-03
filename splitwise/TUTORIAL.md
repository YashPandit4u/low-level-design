# Splitwise Low Level Design

## Understanding the problem

💸 An expense-sharing system records what people spend for a group and tracks who owes whom. If Asha pays ₹900 for dinner shared equally with Ben and Chen, Ben owes Asha ₹300 and Chen owes Asha ₹300. Asha's own share creates no debt.

Now Ben pays for breakfast. Some of his spending should cancel what he owes Asha. Later, he pays her back. Our design needs to handle that small sequence correctly.

We'll build that flow first. Unequal splits, concurrent requests, and expense history come afterward as follow-ups. This is an interview exercise inspired by Splitwise, not a description of its internal implementation.

## Requirements

Imagine the interviewer starts with:

> Design an expense-sharing system like Splitwise. Users should be able to add expenses, see who owes whom, and settle up.

Before drawing classes, narrow the scope. A working expense-and-settlement flow is a useful starting point; we don't need to design the entire product at once.

### Clarifying questions

> **You:** Are we managing user accounts and creating groups?
>
> **Interviewer:** No. Support one group with a fixed set of member IDs. Assume accounts already exist.

That gives us a natural owner for the state: Group. We can add a service that routes between groups later.

> **You:** Can several people pay for one expense? Which splitting rules do we need?
>
> **Interviewer:** Start with one payer and an equal split among selected members. The payer doesn't have to be one of the participants. We'll discuss unequal splits afterward.

Someone can buy concert tickets for their friends without buying a ticket for themselves. Keep “who paid” separate from “who shares the cost.”

> **You:** How should we represent amounts that don't divide evenly?
>
> **Interviewer:** Use INR and store integer paise. Distribute leftover paise deterministically so the shares add up to the total.

₹100 divided among three people must become ₹33.34, ₹33.33, and ₹33.33 in some defined order. We cannot drop the extra paise.

> **You:** Should debts in opposite directions cancel? And does settlement actually transfer money?
>
> **Interviewer:** Cancel opposite debts between the same two people. Settlement records a payment made outside the system. Allow partial payments, but reject overpayment or payment in the wrong direction.

We need current debts, not a payment gateway. We also won't redirect debts through a third person in the initial version.

> **You:** Do we need history, edits, or concurrent access?
>
> **Interviewer:** Not initially. Handle one operation at a time and keep current balances. We can extend the design once that works.

These exclusions matter. The main implementation won't need event history, locks, or retry tracking. They become meaningful additions when the interviewer asks for them.

### Final requirements

1. Manage one group with fixed membership.
2. Add an expense with one payer and a nonempty set of participants.
3. Split the total equally in integer paise, preserving the exact total.
4. Net opposite debts between each pair of members.
5. Return current debts with a debtor, creditor, and positive amount.
6. Record partial or complete settlements; reject invalid operations before changing balances.

Out of scope initially:

- User accounts
- Payment processing
- Unequal splits
- History
- Editing
- Concurrency
- Persistence
- Currencies other than INR
- Debt simplification through third parties

## Core entities and relationships

The obvious nouns are users, groups, expenses, and balances. They don't all need classes with business logic.

**User** can remain an ID. We only need to check membership, so names, email addresses, and bank details add nothing here.

**Group** owns membership and current debts. It handles adding expenses and recording settlements because those operations change the same state.

**Expense** is a result describing an accepted expense: payer, total, and each participant's share. Returning it lets the caller show exactly how the cost was divided. We don't retain expense history yet.

**Debt** is a result containing debtor, creditor, and amount. It makes balance queries readable without exposing the group's mutable map.

| Entity | Responsibility |
| --- | --- |
| Group | Validate members, split expenses, update debts, and record settlements. |
| Expense | Return the payer, total, and final allocation. |
| Debt | Return one current obligation between two members. |

There's only one splitting rule so far. A private equal-split helper is enough; we haven't earned a strategy hierarchy yet.

## Class design

### Group and balance representation

Start with the questions the API needs to answer. If Ben wants to settle with Asha, we need to know how much **Ben owes Asha**, not just Ben's total debt across the group.

#### Option 1: store only each person's net total [Bad fit]

A map such as `Ben: -300, Asha: +300` looks convenient. But consider A owing B ₹300 while B owes C ₹300. B's net position is zero even though two direct debts still exist.

Net totals are useful for simplifying payments, but they lose the relationships our settlement rule needs.

#### Option 2: store directed debts [Recommended]

Use a map keyed by `(debtor, creditor)`, containing only positive amounts:

```text
(Ben, Asha) → 30000    Ben owes Asha ₹300
(Chen, Asha) → 30000   Chen owes Asha ₹300
```

For any two people, keep at most one direction. If Asha later owes Ben ₹100, reduce `(Ben, Asha)` to 20000. If she owes him ₹400 instead, remove the old entry and store `(Asha, Ben) → 10000`.

This takes a little cancellation logic, but the stored state reads just like the requirement. Zero means the entry disappears. We never store self-debts.

We could instead sort the IDs and encode direction using a positive or negative number. That's a valid alternative, but it introduces a sign convention that callers and helpers must interpret consistently. We'll keep direction explicit in this walkthrough.

### Expense and Debt

```text
Expense(payer, total, sharesByUser)
Debt(debtor, creditor, amount)
```

Treat these as immutable results. Copy the allocation when constructing Expense, and return fresh Debt records when listing balances. Callers should not be able to change group state by editing a returned collection.

Expense doesn't need a `settle()` method. Ben's current debt might combine dinner, breakfast, and several payments. The group knows that combined amount; one expense does not.

### Final class design

```text
class Group:
    members: Set<UserId>
    debts: Map<(debtor, creditor), positive paise>

    addExpense(payer, total, participants) -> Expense
    recordSettlement(debtor, creditor, amount)
    getBalances() -> List<Debt>

    private splitEqually(total, participants) -> Map<UserId, paise>
    private addDebt(debtor, creditor, amount)
```

The constructor copies the supplied members and starts with an empty debt map. All public mutations go through Group. The two helpers isolate the only calculations we need: dividing an expense and netting obligations.

## Implementation

The interesting methods are `addExpense` and `recordSettlement`. We'll implement their helpers along the way, then trace dinner, breakfast, and repayment through the whole design.

The Python and Java snippets are pseudocode. `require` rejects invalid input; result constructors make defensive copies. Assume amounts fit the chosen integer representation for this first pass. Overflow and concurrent updates are covered in the follow-ups.

### Group

#### Split an expense equally

Start with ₹100, represented as 10,000 paise, shared by A, B, and C. Integer division gives each person 3333 paise and leaves one paise. Give that extra paise to the first participant after sorting IDs.

Python:

```python
def split_equally(total, participants):
    users = sorted(participants)
    base, remainder = divmod(total, len(users))
    return {
        uid: base + (1 if i < remainder else 0)
        for i, uid in enumerate(users)
    }
```

Java:

```java
Map<String, Long> splitEqually(long total, List<String> participants) {
    var users = new ArrayList<>(participants);
    Collections.sort(users);
    long base = total / users.size();
    long remainder = total % users.size();
    Map<String, Long> shares = new HashMap<>();
    for (int i = 0; i < users.size(); i++) {
        shares.put(users.get(i), base + (i < remainder ? 1 : 0));
    }
    return shares;
}
```

The public method will validate the inputs before calling this helper. Sorting makes the result independent of request order. It favors lower IDs in repeated ties, which is a simple, explicit rounding policy. Rotating that priority would require extra state.

A one-paise expense shared by three people produces shares of 1, 0, and 0. Individual shares may be zero even though an expense total must be positive.

#### Net a new obligation

Suppose Ben already owes Asha ₹300. An expense now makes Asha owe Ben ₹100. Before adding a new entry, cancel as much as possible against the reverse debt.

Python:

```python
def add_debt(self, debtor, creditor, amount):
    forward = (debtor, creditor)
    reverse = (creditor, debtor)
    opposite = self.debts.get(reverse, 0)
    cancelled = min(amount, opposite)

    if opposite > cancelled:
        self.debts[reverse] = opposite - cancelled
    else:
        self.debts.pop(reverse, None)

    remaining = amount - cancelled
    if remaining > 0:
        self.debts[forward] = self.debts.get(forward, 0) + remaining
```

Java:

```java
void addDebt(String debtor, String creditor, long amount) {
    var forward = new Pair(debtor, creditor);
    var reverse = new Pair(creditor, debtor);
    long opposite = debts.getOrDefault(reverse, 0L);
    long cancelled = Math.min(amount, opposite);

    if (opposite > cancelled) debts.put(reverse, opposite - cancelled);
    else debts.remove(reverse);

    long remaining = amount - cancelled;
    if (remaining > 0) {
        debts.put(forward, debts.getOrDefault(forward, 0L) + remaining);
    }
}
```

For the example, `cancelled` is ₹100, leaving Ben owing Asha ₹200. If the new obligation is ₹400, cancellation uses up Ben's entire ₹300 debt, then records Asha owing Ben the remaining ₹100.

This helper is private. Its callers supply distinct members and nonnegative amounts, and the map already satisfies the one-direction-per-pair rule. Keeping cancellation here means every expense follows the same rule.

#### Add the expense

Now the public operation has a short flow: validate, calculate shares, and add each nonpayer's obligation to the payer.

Python:

```python
def add_expense(self, payer, total, participants):
    require(payer in self.members)
    require(type(total) is int and total > 0)
    require(len(participants) > 0)
    require(len(set(participants)) == len(participants))
    require(all(uid in self.members for uid in participants))

    shares = split_equally(total, participants)
    expense = Expense(payer, total, shares)
    for participant, amount in shares.items():
        if participant != payer and amount > 0:
            self.add_debt(participant, payer, amount)
    return expense
```

Java:

```java
Expense addExpense(String payer, long total, List<String> participants) {
    require(members.contains(payer));
    require(total > 0 && !participants.isEmpty());
    require(new HashSet<>(participants).size() == participants.size());
    require(members.containsAll(participants));

    var shares = splitEqually(total, participants);
    var expense = new Expense(payer, total, shares);
    for (var entry : shares.entrySet()) {
        if (!entry.getKey().equals(payer) && entry.getValue() > 0) {
            addDebt(entry.getKey(), payer, entry.getValue());
        }
    }
    return expense;
}
```

Notice the two separate decisions. Everyone in the participant list gets a share, including the payer when present. Only nonpayers create debts. Excluding the payer from the split calculation would incorrectly charge their share to everybody else.

All input validation happens before the first balance change. Don't validate participants as you update their debts: finding an unknown member halfway through would leave a partially applied expense. Duplicate participants are rejected rather than silently removed.

#### Record a settlement

A settlement reduces an existing debt. It must not create a new obligation or flip its direction.

Python:

```python
def record_settlement(self, debtor, creditor, amount):
    require(debtor in self.members and creditor in self.members)
    require(debtor != creditor)
    require(type(amount) is int and amount > 0)
    pair = (debtor, creditor)
    outstanding = self.debts.get(pair, 0)
    require(amount <= outstanding)

    remaining = outstanding - amount
    if remaining == 0:
        self.debts.pop(pair)
    else:
        self.debts[pair] = remaining
```

Java:

```java
void recordSettlement(String debtor, String creditor, long amount) {
    require(members.contains(debtor) && members.contains(creditor));
    require(!debtor.equals(creditor) && amount > 0);
    var pair = new Pair(debtor, creditor);
    long outstanding = debts.getOrDefault(pair, 0L);
    require(amount <= outstanding);

    long remaining = outstanding - amount;
    if (remaining == 0) debts.remove(pair);
    else debts.put(pair, remaining);
}
```

If B owes A ₹150, paying ₹100 leaves ₹50. Paying ₹150 removes the entry. Paying ₹160 fails without mutation. A payment in the reverse direction also fails because that directed entry has no outstanding debt.

We deliberately don't call `addDebt(creditor, debtor, amount)` here. That helper permits a direction reversal; settlement expressly forbids one.

#### Read the balances

`getBalances` returns one fresh `Debt(debtor, creditor, amount)` for every map entry. No signs need interpreting, and no zero entries need filtering. The caller receives a snapshot rather than the mutable map.

For `k` participants, adding an expense takes O(k log k) for sorting and O(k) expected time for map updates. A settlement takes O(1) expected time. Returning all `b` debts takes O(b), or O(b log b) if the display requires sorted results.

## Verification

A useful interview check follows the same group through several operations. Let A, B, and C represent Asha, Ben, and Chen.

### Dinner, breakfast, and repayment

```text
1. A pays ₹900 for A, B, C.
   Shares: A ₹300, B ₹300, C ₹300.
   A's share creates no debt.
   Balances: B → A ₹300; C → A ₹300.

2. B pays ₹300 for A and B.
   Shares: A ₹150, B ₹150.
   New obligation A → B ₹150 cancels part of B → A ₹300.
   Balances: B → A ₹150; C → A ₹300.

3. B records a ₹100 payment to A.
   Outstanding is ₹150, so accept.
   Balances: B → A ₹50; C → A ₹300.

4. B tries to pay A ₹60.
   Reject: only ₹50 remains. Both balances stay unchanged.

5. B pays A exactly ₹50.
   Remove that pair. Only C → A ₹300 remains.
```

This checks that expenses net together while settlements reduce only the debt that exists. Chen's balance stays untouched during Ben's repayments.

### Boundaries worth checking

- **Rounding:** 10,000 paise among A, B, C yields 3334, 3333, 3333. Reordering the input gives the same shares.
- **Payer excluded:** A pays ₹200 for B and C. Both owe A ₹100; A doesn't receive an invented share.
- **Direction reversal:** B owes A ₹300; A incurs a ₹400 obligation to B. Only A owes B ₹100 afterward.
- **Invalid input:** an unknown member, duplicate participant, empty list, or nonpositive total must leave all balances unchanged.
- **Wrong-direction settlement:** if B owes A, a payment from A to B is rejected.

That's a complete first pass: clear ownership, a working expense flow, cancellation, settlement, and verification. The rest of the article extends this design when the interviewer adds requirements.

## Extensibility

These are follow-up discussions, not features you need to implement before demonstrating the basic flow. Start with the new requirement, identify what changes, and leave unrelated code alone.

### How would you support exact and percentage splits?

An exact split supplies amounts directly. A percentage split supplies weights and requires another rounding calculation. Neither changes what happens after we have the final shares.

> I'd extract allocation behind `SplitStrategy.allocate(total)`. Group would ask for shares, validate them against membership and the total, then use the same debt-update helper.

```text
SplitStrategy.allocate(total) -> Map<UserId, paise>
    EqualSplit(participants)
    ExactSplit(amountsByUser)
    PercentageSplit(basisPointsByUser)

Group.addExpense(payer, total, strategy):
    shares = strategy.allocate(total)
    validate all shares before changing balances
    apply each nonpayer share using addDebt
```

The service accepts `addExpense(groupId, payer, total, splitType, participants, values)`. `splitType` is a string: `"EQUAL"`, `"EXACT"`, or `"PERCENTAGE"`. Exact values are paise; percentage values are basis points, in participant order. Equal splits need no values. Reject duplicate participants and mismatched lengths, then select the internal strategy. No request classes are needed.

Now Strategy has a purpose: several calculations share one output contract. A switch in an allocation helper would also work for a fixed set of modes. Separate strategies become useful when we want to test and extend each rule independently.

For **exact amounts**, require a nonempty allocation, nonnegative integer shares, and a sum equal to the total. Copy the accepted allocation. Group checks that every participant belongs to it.

For **percentages**, represent 25.00% as 2500 basis points and require weights to sum to 10000. Avoid independently rounding each share. For 101 paise split 33.33%, 33.33%, and 33.34%, rounding all three quotas to the nearest paise gives 34 + 34 + 34 = 102.

Instead, allocate each quota's floor and distribute remaining paise to the largest fractional remainders, breaking ties by user ID:

| User | Exact quota in paise | Floor | Final share |
| --- | ---: | ---: | ---: |
| A | 33.6633 | 33 | 34 |
| B | 33.6633 | 33 | 33 |
| C | 33.6734 | 33 | 34 |

The floors allocate 99 paise. C gets the first leftover paise, and A wins the tie for the second. Final shares sum to 101.

Python:

```python
def percentage_shares(total, weights):
    require(total > 0 and weights)
    require(all(type(w) is int and w >= 0 for w in weights.values()))
    require(sum(weights.values()) == 10000)
    shares, fractions = {}, {}
    for uid, weight in weights.items():
        shares[uid], fractions[uid] = divmod(total * weight, 10000)
    leftover = total - sum(shares.values())
    order = sorted(shares, key=lambda uid: (-fractions[uid], uid))
    for uid in order[:leftover]:
        shares[uid] += 1
    return shares
```

Java:

```java
Map<String, Long> percentageShares(long total, Map<String, Integer> weights) {
    validateWeights(total, weights); // positive total; nonempty; weights >= 0; sum 10000
    Map<String, Long> shares = new HashMap<>();
    Map<String, Long> fractions = new HashMap<>();
    long allocated = 0;
    for (var e : weights.entrySet()) {
        var numerator = BigInteger.valueOf(total)
            .multiply(BigInteger.valueOf(e.getValue()));
        var qr = numerator.divideAndRemainder(BigInteger.valueOf(10000));
        long share = qr[0].longValueExact();
        shares.put(e.getKey(), share);
        fractions.put(e.getKey(), qr[1].longValueExact());
        allocated += share;
    }
    var order = new ArrayList<>(weights.keySet());
    order.sort(Comparator.<String>comparingLong(fractions::get)
        .reversed().thenComparing(Comparator.naturalOrder()));
    for (int i = 0; i < total - allocated; i++) {
        String uid = order.get(i);
        shares.put(uid, shares.get(uid) + 1);
    }
    return shares;
}
```

Because every fractional part is less than one, fewer than `k` paise remain for `k` participants. Each selected participant gets at most one extra paise. Zero-percent participants receive zero.

### What changes when requests arrive concurrently?

Our base implementation assumes one operation at a time. Two threads can otherwise approve payments against the same debt:

```text
B owes A ₹100.
Thread 1 reads ₹100 and approves an ₹80 payment.
Thread 2 reads ₹100 and approves an ₹80 payment.
Both record success against the same original debt.
```

> I'd add one lock to Group. Settlement validation and deduction must happen under that same lock. Adding an expense must hold it across all affected pairs, and balance reads must use it too.

```text
recordSettlement(debtor, creditor, amount):
    validate fixed input rules
    lock group:
        read current debt
        reject if amount exceeds debt
        reduce or remove the debt
```

Now the first payment leaves ₹20. The second thread acquires the lock afterward, sees ₹20, and rejects ₹80. A thread-safe map alone doesn't combine the check and update into one operation.

For multiple groups, add a `SplitwiseService` containing `groupId → Group`. It routes calls; each group retains its own lock. Unrelated groups can proceed independently. Per-pair locks offer more concurrency within a group, but expenses involving several pairs then need coordinated locking and consistent read snapshots. Start with the group lock.

Equal-split calculation can happen before acquiring it because it depends only on the request. Reading and changing current debts must happen inside.

### How would you add history and verify it stays consistent?

Current balances answer “what is owed now?” They don't explain how we got there. Once history is requested, retain accepted Expense records and introduce a Settlement record containing debtor, creditor, and amount.

> I'd append accepted records in order and update history and balances within the same group lock. Expense would retain the final allocation, so later rounding changes can't rewrite the past.

Keep records immutable, including their contained collections. A read should return a snapshot. Storing a caller-owned mutable allocation would let an unrelated later edit alter the apparent history.

There are two reasonable storage choices. History alone is enough if we replay it for every balance query. Keeping a current-balance map makes reads and settlement validation cheaper, but then every mutation must keep both representations consistent.

A useful verification is:

```text
replay accepted expenses and settlements into an empty map
compare reconstructed debts with current debts
```

An expense adds each nonpayer share. A settlement subtracts its directed amount. Compare both history and balances before and after rejected operations. An exception alone doesn't prove the method left state intact.

### What about overflow, retries, and durable writes?

These concerns strengthen the acceptance boundary; they don't require changing how an equal split works.

**Overflow.** Integer paise avoid floating-point rounding, but Java's `long` can still overflow. Use checked arithmetic for accumulated debts and widen intermediate percentage multiplication, as the Java snippet does with `BigInteger`. Python integers grow, though the input boundary must still reject fractional amounts and booleans.

Checked addition can fail halfway through a multi-person expense. Prepare every affected balance before writing any of them. Only after all arithmetic succeeds should the operation commit the new balances and history record. A simple implementation can calculate on a temporary map; a more efficient one can stage only affected pairs. The first trades O(b) copying for simpler rollback behavior.

**Retries.** An automatically generated expense ID doesn't prevent duplicate submissions. If the response is lost, repeating the request currently charges everyone again. Accept a caller-generated operation ID and store its request fingerprint and result. Under the group lock, return the previous result for an identical retry; reject reuse with different input. Check for a successful retry before validating a settlement against its now-reduced balance.

**Persistence.** A process-local lock doesn't protect multiple application instances or survive a crash. Store balance changes, history, and the idempotency record in one database transaction. Use database locking or version checks to coordinate competing updates. Define how long retry keys remain valid rather than discarding them as an arbitrary cache optimization.

### How would you simplify debts to reduce payments?

If A owes B ₹300 and B owes C ₹300, A could pay C directly. Everybody's net position would remain the same.

> I'd derive net positions from the current debts, then match people who owe money with people who should receive it. I'd return a proposed payment plan first, because applying it changes the settlement rules.

For each debt, subtract its amount from the debtor's net position and add it to the creditor's. Ignore zero positions. Match a debtor and creditor for the smaller remaining amount, then advance whichever position reaches zero.

```text
Current debts: A → B ₹300; B → C ₹300
Net positions: A -₹300; B ₹0; C +₹300
Proposed plan: A → C ₹300
```

For `m` nonzero positions, this produces at most `m - 1` payments when `m > 0`. It doesn't guarantee the globally smallest transaction count. Sorting by ID gives a deterministic plan; computing positions and sorting costs O(b + m log m).

There's an integration trap: our existing settlement method rejects A paying C because no such direct debt exists. To accept the plan, either explicitly restructure the debt map while preserving every user's net position, or define how the payment reduces the original obligations along a path. If history exists, record that change too. A suggestion alone must not silently replace the ledger.

### How would you edit expenses or support multiple payers?

Both changes build on the history extension.

For **editing**, append a correction that reverses the old allocation and applies the replacement. Validate the replacement first and prevent the same expense revision from being reversed twice. Don't simply overwrite the original record or reset its pairs to zero: those pairs may include other expenses.

Settlements stay recorded because the money really changed hands. If Ben paid back a ₹100 expense that is later deleted, reversing the expense creates a ₹100 refund obligation from Asha to Ben. That's a product policy to agree on, not an arithmetic bug.

For **multiple payers**, replace the single payer with `paidByUser`. Require both payments and shares to sum to the expense total. Each person's net contribution is `amount paid - share owed`. Match negative contributions with positive ones to create this expense's obligations. Several valid pairings may exist, so choose a deterministic rule and retain the resulting edges for stable replay.

Multiple currencies are a separate extension: partition obligations by currency and use its minor-unit precision. Never add INR and USD debts together without an explicit conversion policy.

### Complete reference implementations

The executable references below implement the **extended design**, not the minimal walkthrough. They include multiple groups, all three split strategies, immutable history, synchronized operations, and a signed canonical-pair balance map. That last representation stores one sorted pair with a sign for direction; it is an alternative to the positive directed map taught above.

- [Python implementation](splitwise.py) and [Python verification suite](test_splitwise.py).
- [Java implementation](Splitwise.java) and [Java verification suite](SplitwiseTest.java), requiring Java 17+.

They do not implement the proposed retry, editing, debt-simplification, multiple-payer, or persistence extensions. Treat them as optional further study after completing the main flow.

Run their checks from this article's directory:

```sh
python3 -m unittest -v
javac --release 17 -d /tmp/splitwise-classes Splitwise.java SplitwiseTest.java
java -cp /tmp/splitwise-classes SplitwiseTest
```

## What is expected at each level?

These are practice targets, not universal hiring rules.

### Junior

Build a working equal-expense and settlement flow. Keep responsibility in Group, exclude self-debts, and handle invalid members and amounts. You may need a hint about remainder allocation or cancelling opposite debts, but you should be able to trace the result correctly.

### Mid-level

Independently handle rounding, cancellation, direction reversal, and partial settlement. Explain why the balance representation fits the required queries. Verify rejected operations don't mutate state, and show how unequal splits could be added without rewriting debt updates.

### Senior

Keep the first solution small while proactively identifying its boundaries. When the interviewer adds concurrency, history, or retries, explain the required consistency guarantees and where they belong. Recognize that a simplified payment plan changes settlement semantics. Depth means defending these choices, not implementing every extension before the core works.

## Test your understanding

1. Why must the payer still receive a share when included among participants?
2. Why can't per-user net totals replace direct debts for our settlement rule?
3. What happens when a new obligation is larger than the debt in the opposite direction?
4. Why can expense netting reverse a debt while a settlement cannot?
5. Which check and update must share a lock once concurrency is introduced?
