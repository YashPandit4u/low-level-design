# Splitwise Low Level Design

## Understanding the problem

💸 An expense-sharing system records money people spend on behalf of a group and tracks who owes whom. If Asha pays ₹900 for dinner shared equally with Ben and Chen, Ben owes Asha ₹300 and Chen owes Asha ₹300. Asha's own ₹300 share creates no debt.

The interesting part starts when Ben pays for breakfast the next morning, someone chooses an unequal split, and two friends record settlements at the same time. We need to calculate each share correctly and keep the balances accurate after every operation.

We'll build an expense-sharing service that stores its data in memory.

## Requirements

Imagine the interviewer opens with:

> Design a system like Splitwise. Users should be able to add shared expenses, see balances, and settle up.

That's enough to recognize the product, but it leaves several important decisions open. Does an expense have one payer or several? Does settlement move money? Can users owe different amounts for the same expense? Before drawing classes, we need answers.

### Clarifying questions

> **You:** Are expenses associated with groups? Do we need to create users and manage group membership?
>
> **Interviewer:** Support multiple groups. Users and group membership are provided at startup. User profiles and membership changes are out of scope.

We need to identify users, but we don’t need to manage their accounts. A user ID is enough for this design. The same person can belong to several groups, and balances stay separate between groups.

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

The caller tells us that a payment has already happened. We record it without connecting to a bank or payment gateway.

> **You:** Do we need history, editing, or deletion? And should concurrent updates be safe?
>
> **Interviewer:** Keep expense and settlement history. No editing or deletion for now. Concurrent updates must be safe, and failed operations must not partially change balances.

Concurrency is part of correctness here. Two simultaneous settlements must not both spend the same outstanding debt.

### Final requirements

1. Support multiple groups with fixed membership configured at startup.
2. Add an expense with one payer and one or more group participants.
3. Support equal, exact-amount, and percentage splits.
4. Store money as integer paise. The shares must add up to the expense total.
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

**User.** Accounts already exist. We only need user IDs and group membership. There is no need for a User class containing email addresses, passwords, or payment details. User IDs stay strings.

**Group.** A group owns membership, expense history, and balances. It checks who can participate and updates debts when expenses or settlements are added.

**Expense.** An expense records who paid, the total, and each participant's final share. Even without business methods, those fields belong together. We also need to retain them after balances have changed. Expense is an immutable record.

**Settlement.** A settlement records a directed payment between two members. It reduces a debt but does not erase the original expense. Keeping it separate makes the history understandable: dinner happened, then Ben paid Asha back.

**Split.** This word can mean either the rule used to divide an expense or one person's resulting share. We need both concepts, but that doesn't mean both need class hierarchies. A share can be a user ID and an amount. We'll decide how to organize the calculation when we get to class design.

**Balance.** A balance is a changing relationship between two users. We need to store that amount, but a separate Balance class may not be necessary. We'll decide on the data structure during class design. A returned Debt record will keep the public API readable.

**SplitwiseService.** Callers submit expense data and a group ID. The service selects a split strategy and calls the requested group. It doesn't calculate individual shares or hold every group's lock.

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

Group passes the expense inputs into a reusable strategy. The resulting Expense stores the final amounts, so its history stays stable even if the allocation rules change later.

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
| EQUAL | Omit in Python. Pass `null` in Java. |
| EXACT | Each participant's amount in paise, e.g. `[4000, 6000]`. |
| PERCENTAGE | Each participant's percentage in basis points, e.g. `[4000, 6000]` means 40% and 60%. |

Reject duplicate participants and unknown split types. Exact and percentage splits need one value per participant. Equal splits take no values.

The service chooses the strategy. The strategy calculates and checks the shares. Group checks membership and updates debts. Copy the input lists before using them.

### Group

A group needs its members, history, current balances, and a lock. Before writing those fields down, let's decide what a balance means.

#### Bad Solution: Store each person's net position

Suppose we store:

```text
Asha: +₹300
Ben:  -₹300
```

A positive amount means the person should receive money. A negative amount means they owe money. This is compact and useful for debt simplification.

But it loses who owes whom. Consider two histories:

```text
History 1: A owes B ₹300; B owes C ₹300
History 2: A owes C ₹300
```

Both have the same totals: A owes ₹300, B’s total is zero, and C should receive ₹300. But the people who owe each other are different. Those totals alone cannot tell us whom A should pay.

This representation works if we only need each person’s overall total. Our requirements also need to preserve who owes whom.

#### Good Solution: Store both directions

We could store `balances[A][B] = 300` and `balances[B][A] = -300`. That makes lookup convenient, but every update must preserve the relationship between two entries.

This is a reasonable design if most queries ask for all debts involving one user: their row already contains the answer. With one group lock, we can update both entries safely. The cost is maintaining two copies of every relationship, including deleting both when a debt reaches zero.

Our API asks for the whole group's balances, so that lookup advantage doesn't help us yet. We can keep one copy instead.

#### Great Solution: Store one signed balance per unordered pair

Sort the two immutable user IDs and use the ordered pair as a key. For key `(A, B)`:

```text
 +30000 means A owes B ₹300
 -30000 means B owes A ₹300
       0 means neither owes the other; remove the entry
```

The ordering uses IDs, not display names. Renaming “Asha” must not change the direction of an existing balance. Use one consistent ID ordering throughout the implementation.

Now opposite obligations become ordinary addition. If A owes B ₹300 and a later expense makes B owe A ₹100, the same entry changes from `30000` to `20000`.

We'll use this representation. It gives us one value to update for either direction of a debt. The downside is that negative amounts are easy to misread. We’ll use one helper to convert a debt into the correct sign. Finding all debts for one person also requires scanning the pair map unless we add an index later.

The sign convention is internal. Callers receive `Debt(debtor, creditor, positiveAmount)` so UI code doesn't have to understand it.

**History and current balances.**

Why keep both history and current balances?

We could store only the history. To find current balances, we would apply every expense and settlement again in order. Adding records would be simple, but every balance query and settlement check would need to read the whole history.

We’ll keep history and a map of current balances. History explains how the debts arose. The map lets us look up what is owed now. Every accepted expense or settlement updates both under the same group lock. They must always agree:

```text
current balances == replay of accepted history
```

We can check that they agree by rebuilding balances from history and comparing the result with the map. We don’t need extra maps for per-user totals or creditor lists unless a requirement calls for them.

```text
class Group:
    - members: Set<UserId>                  // immutable
    - balances: Map<Pair<UserId>, signed amount>
    - history: List<Expense | Settlement>
    - lock: Lock

    + addExpense(payer, total, strategy, participants, values) -> Expense
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

This works for three fixed split types. A string and a helper would be enough. Notice that the first part calculates each person’s share. The second part updates debts from those shares. That second part is the same for every split type.

If someone stays twice as long, they might pay twice as much. A new strategy handles that calculation. The code for balances, history, and settlements stays the same.

That gives us a small Strategy interface:

```text
interface SplitStrategy:
    allocate(total, participants, values) -> Map<UserId, amount>

EqualSplitStrategy()
ExactSplitStrategy()
PercentageSplitStrategy()
```

The strategies have no expense-specific fields. Each call receives the total, participants, and values. Exact values are amounts in paise. Percentage values are basis points: `2500` means 25.00%, and `10000` means 100%. Values follow participant order. Equal splits use no values.

This lets the same strategy instance calculate different expenses. A strategy could also hold configuration without violating the pattern or single responsibility. Here, passing expense data into the method makes the separation easier to follow.

We'll use separate strategies because allocation is a meaningful behavior to test independently. The cost is three small classes and a service-side lookup. A map from split type to strategy is enough to select among the three modes. Group accepts the resulting strategy internally, while clients only submit split data.

Group still validates the returned allocation. Group knows who its members are. The strategy only knows the participants passed to it. It also verifies that shares are nonnegative integers and sum to the total. A new strategy must not be able to create money by returning invalid shares.

### Expense, Settlement, and Debt

```text
Expense
  id: String                       // unique expense ID
  payer: String                    // user ID of the person who paid
  total: long                      // positive amount in paise
  sharesByUser: Map<String, long>   // participant user ID → share in paise

Settlement
  id: String                       // unique settlement ID
  debtor: String                   // user ID of the person paying back
  creditor: String                 // user ID of the person receiving payment
  amount: long                     // positive amount repaid, in paise

Debt
  debtor: String                   // user ID of the person who owes money
  creditor: String                 // user ID of the person owed money
  amount: long                     // positive outstanding amount, in paise
```

All three records are immutable. Expense copies the final shares so later rounding changes cannot alter history. Group handles settlement because a person’s current debt can come from several expenses.

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
  addExpense(payer, total, strategy, participants, values) -> Expense
  recordSettlement(debtor, creditor, amount) -> Settlement
  getBalances() -> List<Debt>
  getHistory() -> List<Event>

SplitStrategy.allocate(total, participants, values) -> Map<UserId, paise>
  EqualSplitStrategy()
  ExactSplitStrategy()
  PercentageSplitStrategy()

Event = Expense | Settlement
Expense(id: String, payer: String, total: long,
        sharesByUser: immutable Map<String, long>)
Settlement(id: String, debtor: String, creditor: String, amount: long)
Debt(debtor: String, creditor: String, amount: long)
// All monetary values are integer paise; totals and settlement/debt amounts are positive.
```

Before implementing, let’s list the rules that must always hold:

1. An expense's shares sum exactly to its positive total.
2. Every referenced user belongs to the group.
3. Nobody owes themselves.
4. Each pair has at most one nonzero signed balance.
5. A settlement only reduces an existing debt in the specified direction.
6. History and the balance index change together.

Those statements give us a concrete standard for deciding whether the code is correct.

## Implementation

We don't need to spend equal time implementing every class. The important methods are the ones that calculate shares or change debts:

- **SplitStrategy.allocate:** implement equal, exact, and percentage splits. Getting the total right, especially after rounding, is the interesting part.
- **Group.addExpense:** validate the expense, calculate shares, and update balances and history together.
- **Group.recordSettlement:** check the current debt before reducing it. A rejected payment must leave the group unchanged.
- **SplitwiseService:** show how the service chooses a strategy and calls Group.

We’ll also implement the constructors and read methods used by these operations. Each method checks its own inputs. The result records are short, so we’ll show their definitions after Group.

We’ll show the service entry point, implement the allocation algorithms, then connect them to Group.

For `Group.addExpense` and `Group.recordSettlement`, we’ll separate the explanation into:

1. **Core logic:** the steps for completing a valid operation.
2. **Edge cases:** inputs to reject and boundary conditions to handle.

Small helpers only need a brief explanation.

For the walkthrough below, we'll group the three allocation algorithms together so you can compare them. Keep this example in mind:

```text
Asha pays ₹900 for Asha, Ben, and Chen
        ↓ splitType=EQUAL, participants=[A, B, C]
Service selects its reusable EqualSplitStrategy instance
        ↓ Group calls allocate(90000, [A, B, C], no values)
shares: Asha ₹300, Ben ₹300, Chen ₹300
        ↓ Group ignores the payer's own share
Ben owes Asha ₹300; Chen owes Asha ₹300
        ↓ Group stores the expense and updates both pairs together
one history record, two current debts
```

The strategy never needs to know who paid. It answers how the cost is shared. The group turns those shares into obligations to the payer.

The snippets below use the methods from the runnable Python and Java implementations. Methods shown separately belong to the class named by their section. Python uses `Lock`, `Protocol`, `dataclass`, and `uuid4`. Java uses `java.util.*` and `BigInteger`. The complete files below include the imports and class wrappers. Invalid requests must be rejected before changing balances or history. This in-memory version does not handle process crashes or memory allocation failures.

### SplitwiseService

The service receives a group ID and plain expense data. It finds the group and chooses a strategy. Group performs the balance changes.

**Constructor.**

Create the groups once at startup and keep one instance of each strategy. Reject blank group IDs before storing them. Each public method looks up its group directly and rejects an unknown ID.

Python:

```python
class SplitwiseService:
    def __init__(self, group_members):
        self._strategies = {"EQUAL": EqualSplitStrategy(), "EXACT": ExactSplitStrategy(),
                            "PERCENTAGE": PercentageSplitStrategy()}
        if any(not isinstance(gid, str) or not gid.strip() for gid in group_members):
            raise ValueError("Invalid group ID")
        self._groups = {gid: Group(members) for gid, members in group_members.items()}
```

Java:

```java
private final Map<String, SplitStrategy> strategies = Map.of(
    "EQUAL", new EqualSplitStrategy(),
    "EXACT", new ExactSplitStrategy(),
    "PERCENTAGE", new PercentageSplitStrategy());
private final Map<String, Group> groups;

public Splitwise(Map<String, List<String>> groupMembers) {
    Map<String, Group> built = new HashMap<>();
    groupMembers.forEach((id, members) -> {
        if (id == null || id.isBlank()) throw new IllegalArgumentException("Invalid group ID");
        built.put(id, new Group(members));
    });
    groups = Map.copyOf(built);
}
```

The Java service class is named `Splitwise` in the runnable file. The methods below belong to that class. In Python, add them to `SplitwiseService`.

**Adding an expense.**

Look up the group and select the strategy. Reject an unknown group or split type. Then pass the expense data to Group, which checks the payer, total, and participants before changing balances.

Python:

```python
def add_expense(self, group_id, payer, total, split_type, participants, values=None):
    if not isinstance(group_id, str) or group_id not in self._groups:
        raise ValueError("Unknown group")
    group = self._groups[group_id]
    if not isinstance(split_type, str) or split_type not in self._strategies:
        raise ValueError("Unknown split type")
    strategy = self._strategies[split_type]
    return group.add_expense(payer, total, strategy, participants, values)
```

Java:

```java
public Expense addExpense(String groupId, String payer, long total, String splitType,
                          List<String> participants, List<Long> values) {
    Group group = groupId == null ? null : groups.get(groupId);
    if (group == null) throw new IllegalArgumentException("Unknown group");
    if (splitType == null || !strategies.containsKey(splitType)) throw new IllegalArgumentException("Unknown split type");
    return group.addExpense(payer, total, strategies.get(splitType), participants, values);
}
```

The caller still passes a string such as `"EQUAL"`. They never construct a strategy object.

**Settlements and reads.**

These methods find the requested group and return its result. Settlement validation belongs to Group because it needs the current debt. Group also creates safe copies for balance and history reads.

Python:

```python
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
```

Java:

```java
public Settlement recordSettlement(String groupId, String debtor, String creditor, long amount) {
    Group group = groupId == null ? null : groups.get(groupId);
    if (group == null) throw new IllegalArgumentException("Unknown group");
    return group.recordSettlement(debtor, creditor, amount);
}

public List<Debt> getBalances(String groupId) {
    Group group = groupId == null ? null : groups.get(groupId);
    if (group == null) throw new IllegalArgumentException("Unknown group");
    return group.getBalances();
}

public List<Event> getHistory(String groupId) {
    Group group = groupId == null ? null : groups.get(groupId);
    if (group == null) throw new IllegalArgumentException("Unknown group");
    return group.getHistory();
}
```

### SplitStrategy

All three strategies implement `allocate(total, participants, values)` and return each participant's share in paise. Each class below implements that interface and keeps no expense data between calls. Input checks are written directly in each method, followed by the calculation.

The interface gives every strategy the same inputs and output:

Python:

```python
class SplitStrategy(Protocol):
    def allocate(self, total: int, participants, values=None) -> dict[str, int]: ...
```

Java:

```java
interface SplitStrategy {
    Map<String, Long> allocate(long total, List<String> participants, List<Long> values);
}
```

**EqualSplitStrategy and the missing paise.**

The first version most people write is `total / numberOfPeople`. That works until the division has a remainder.

For ₹100 among three people, the input is 10,000 paise:

```text
base share = 10000 // 3 = 3333
remainder  = 10000 % 3  = 1

A: 3334, B: 3333, C: 3333
Total: 10000
```

Sort the participant IDs and give one extra paise to each of the first `remainder` participants. The same participants get the same shares even if the input order changes. Lower IDs will receive the extra paise whenever there is a tie. Rotating who gets it would require us to remember whose turn is next.

Python:

```python
class EqualSplitStrategy:
    def allocate(self, total, participants, values=None):
        if type(total) is not int or total < 1:
            raise ValueError("Invalid amount")
        if not isinstance(participants, (list, tuple)) or not participants:
            raise ValueError("Participants required")
        participants = tuple(participants)
        if any(not isinstance(uid, str) or not uid.strip() for uid in participants):
            raise ValueError("Invalid participant ID")
        if len(set(participants)) != len(participants):
            raise ValueError("Duplicate participant")
        users = sorted(participants)
        if values is not None:
            raise ValueError("Equal splits do not take values")
        base, remainder = divmod(total, len(users))
        return {uid: base + (i < remainder) for i, uid in enumerate(users)}
```

Java:

```java
static final class EqualSplitStrategy implements SplitStrategy {
    public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
        if (total <= 0) throw new IllegalArgumentException("Positive total required");
        if (participants == null || participants.isEmpty())
            throw new IllegalArgumentException("Participants required");
        if (participants.stream().anyMatch(id -> id == null || id.isBlank()))
            throw new IllegalArgumentException("Invalid participant ID");
        participants = List.copyOf(participants);
        if (new HashSet<>(participants).size() != participants.size())
            throw new IllegalArgumentException("Duplicate participant");
        var sorted = new ArrayList<>(participants);
        if (values != null) throw new IllegalArgumentException("Equal splits do not take values");
        Collections.sort(sorted);
        long base = total / sorted.size(), remainder = total % sorted.size();
        Map<String, Long> result = new HashMap<>();
        for (int i = 0; i < sorted.size(); i++)
            result.put(sorted.get(i), base + (i < remainder ? 1 : 0));
        return result;
    }
}
```

Do not silently turn a duplicated participant list into a set. If the input contains A twice, that could be a caller bug or an attempted weighting scheme. Our equal-split contract requires unique participants, so reject it.

**ExactSplitStrategy.**

For an exact split, the caller supplies each person’s amount. Check that participants are unique and each has one nonnegative amount. Build the user-to-amount map, add the amounts, and reject the request if the sum differs from the total. Return the map if it passes.

For a 10,000-paise expense, `[4000, 6000]` is valid. `[4000, 5000]` is not. Zero shares are allowed, but negative shares are rejected. Java uses checked addition so an overflowing sum also fails.

Python:

```python
class ExactSplitStrategy:
    def allocate(self, total, participants, values=None):
        if type(total) is not int or total < 1:
            raise ValueError("Invalid amount")
        if not isinstance(participants, (list, tuple)) or not participants:
            raise ValueError("Participants required")
        participants = tuple(participants)
        if any(not isinstance(uid, str) or not uid.strip() for uid in participants):
            raise ValueError("Invalid participant ID")
        if len(set(participants)) != len(participants):
            raise ValueError("Duplicate participant")
        if not isinstance(values, (list, tuple)) or len(values) != len(participants):
            raise ValueError("One value per participant required")
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Shares must be nonnegative integers")
        amounts = dict(zip(participants, values))
        if sum(amounts.values()) != total:
            raise ValueError("Shares must sum to the expense total")
        return amounts
```

Java:

```java
static final class ExactSplitStrategy implements SplitStrategy {
    public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
        if (total <= 0) throw new IllegalArgumentException("Positive total required");
        if (participants == null || participants.isEmpty())
            throw new IllegalArgumentException("Participants required");
        if (participants.stream().anyMatch(id -> id == null || id.isBlank()))
            throw new IllegalArgumentException("Invalid participant ID");
        participants = List.copyOf(participants);
        if (new HashSet<>(participants).size() != participants.size())
            throw new IllegalArgumentException("Duplicate participant");
        if (values == null || values.size() != participants.size())
            throw new IllegalArgumentException("One value per participant required");
        if (values.stream().anyMatch(value -> value == null || value < 0))
            throw new IllegalArgumentException("Invalid split value");
        Map<String, Long> amounts = new HashMap<>();
        for (int i = 0; i < participants.size(); i++)
            amounts.put(participants.get(i), values.get(i));
        long sum = 0;
        for (long amount : amounts.values()) sum = Math.addExact(sum, amount);
        if (sum != total) throw new IllegalArgumentException("Shares must sum to total");
        return amounts;
    }
}
```

**PercentageSplitStrategy and rounding fairly.**

For percentages, independently rounding each result is unsafe. Take 101 paise split 33.33%, 33.33%, and 33.34%. The exact shares are 33.6633, 33.6633, and 33.6734 paise. Rounding each to the nearest paise gives 34 + 34 + 34 = 102. We've charged the group an extra paise.

We’ll use the largest-remainder method. First, calculate each share and round it down to whole paise. Then give the leftover paise to the people whose shares had the largest fractional parts. If two fractional parts are equal, use user ID to break the tie. We can do all of this with integer arithmetic.

For 101 paise split 33.33%, 33.33%, and 33.34%:

| User | Basis points | Exact quota in paise | Floor | Fractional remainder numerator |
| --- | ---: | ---: | ---: | ---: |
| A | 3333 | 33.6633 | 33 | 6633 |
| B | 3333 | 33.6633 | 33 | 6633 |
| C | 3334 | 33.6734 | 33 | 6734 |

The floors sum to 99. Two paise remain. C gets the first. A wins the tie for the second. Final shares are A=34, B=33, C=34.

Before calculating, require a positive total and nonnegative weights that sum to 10000 basis points. Check for missing values and duplicate participants before building the map. A 0% share is valid. Java uses `BigInteger` for `total * weight` so that multiplication cannot overflow before we divide by 10000.

Python:

```python
class PercentageSplitStrategy:
    """Integer basis points: 10000 means 100 percent."""
    def allocate(self, total, participants, values=None):
        if type(total) is not int or total < 1:
            raise ValueError("Invalid amount")
        if not isinstance(participants, (list, tuple)) or not participants:
            raise ValueError("Participants required")
        participants = tuple(participants)
        if any(not isinstance(uid, str) or not uid.strip() for uid in participants):
            raise ValueError("Invalid participant ID")
        if len(set(participants)) != len(participants):
            raise ValueError("Duplicate participant")
        if not isinstance(values, (list, tuple)) or len(values) != len(participants):
            raise ValueError("One value per participant required")
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Shares must be nonnegative integers")
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
```

Java:

```java
static final class PercentageSplitStrategy implements SplitStrategy {
    public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
        if (total <= 0) throw new IllegalArgumentException("Positive total required");
        if (participants == null || participants.isEmpty())
            throw new IllegalArgumentException("Participants required");
        if (participants.stream().anyMatch(id -> id == null || id.isBlank()))
            throw new IllegalArgumentException("Invalid participant ID");
        participants = List.copyOf(participants);
        if (new HashSet<>(participants).size() != participants.size())
            throw new IllegalArgumentException("Duplicate participant");
        if (values == null || values.size() != participants.size())
            throw new IllegalArgumentException("One value per participant required");
        if (values.stream().anyMatch(value -> value == null || value < 0))
            throw new IllegalArgumentException("Invalid split value");
        Map<String, Long> bps = new HashMap<>();
        for (int i = 0; i < participants.size(); i++)
            bps.put(participants.get(i), values.get(i));
        long sum = 0;
        for (long weight : bps.values()) {
            if (weight > 10000) throw new IllegalArgumentException("Invalid percentage");
            sum += weight;
        }
        if (sum != 10000) throw new IllegalArgumentException("Percentages must sum to 10000 basis points");
        Map<String, Long> shares = new HashMap<>();
        Map<String, Long> fractions = new HashMap<>();
        long allocated = 0;
        for (var entry : bps.entrySet()) {
            var qr = BigInteger.valueOf(total).multiply(BigInteger.valueOf(entry.getValue()))
                    .divideAndRemainder(BigInteger.valueOf(10000));
            long share = qr[0].longValueExact();
            shares.put(entry.getKey(), share);
            fractions.put(entry.getKey(), qr[1].longValueExact());
            allocated = Math.addExact(allocated, share);
        }
        var order = new ArrayList<>(bps.keySet());
        order.sort(Comparator.<String>comparingLong(fractions::get).reversed()
                .thenComparing(Comparator.naturalOrder()));
        long leftover = total - allocated;
        for (int i = 0; i < leftover; i++)
            shares.put(order.get(i), shares.get(order.get(i)) + 1);
        return shares;
    }
}
```

Because the percentages sum to 100%, the floors cannot exceed the total. The sum of the fractional parts is the integer number of remaining paise, and it is smaller than the participant count. Each selected participant therefore needs at most one additional paise.

Notice that a 0% participant gets no fractional remainder and no allocation. The method doesn't need a separate special case for them.

### Group

Group turns shares into debts and records repayments. Both operations change balances and history. Before implementing them, let’s choose how to protect those changes when requests arrive together.

**Concurrency tradeoffs.**

##### Bad Solution: Rely on a thread-safe map

A concurrent map can protect individual operations. It doesn't make an entire expense atomic, and it doesn't combine a settlement's validation with its deduction.

```text
Ben owes Asha ₹100.
Thread 1 checks: ₹100 outstanding, payment of ₹80 is valid.
Thread 2 checks: ₹100 outstanding, payment of ₹80 is valid.
Both record success.
```

We have recorded ₹160 against a ₹100 debt. Depending on the update code, the balance may become negative or one deduction may overwrite the other. Neither result satisfies the contract.

##### Good Solution: One service-wide lock

This allows only one group operation at a time across the entire service. It is easy to implement, but adding dinner in one group blocks a completely unrelated group's settlement. There is no shared debt state between them, so that coordination is unnecessary.

##### Great Solution: One lock per group

An expense may change several pairs and history together. A group lock keeps those changes together. Other operations on that group wait until the update finishes. Operations on different groups can continue.

We could use a lock for each pair of users. But one expense might then need several locks, acquired in a fixed order to avoid deadlocks. We would also need to coordinate history updates and reads. Start with one group lock. Consider smaller locks only if measurements show that waiting on the group lock is a problem.

**Constructor.**

A group starts with fixed members, no debts, and an empty history. Reject an empty member list, invalid IDs, and duplicate members. Copy the IDs so later changes to the caller’s list cannot change membership. Each group owns its lock.

Expense creation and settlement check membership directly before changing any balances.

Python:

```python
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
```

Java:

```java
private final Set<String> members;
private final Map<Pair, Long> balances = new HashMap<>();
private final List<Event> history = new ArrayList<>();
private final Object lock = new Object();

public Group(List<String> users) {
    if (users == null || users.isEmpty())
        throw new IllegalArgumentException("Group members required");
    if (users.stream().anyMatch(id -> id == null || id.isBlank()))
        throw new IllegalArgumentException("Invalid member ID");
    members = Set.copyOf(users);
    if (members.size() != users.size()) throw new IllegalArgumentException("Duplicate member");
}
```

The remaining methods belong to Group.

**Translating a share into debt.**

Every participant owes their allocated share to the payer, except when the participant is the payer. A helper will sort the two user IDs and choose the sign that represents who owes whom. It returns both the pair and the signed amount. For example, B owing A 30000 paise becomes `(A, B), -30000`. Callers skip self-debts before using it.

Python:

```python
@staticmethod
def _delta(debtor, creditor, amount):
    if debtor < creditor:
        return (debtor, creditor), amount
    return (creditor, debtor), -amount
```

Java:

```java
private record Pair(String lower, String higher) {}
private record Delta(Pair pair, long value) {}

private static Delta delta(String debtor, String creditor, long amount) {
    return debtor.compareTo(creditor) < 0
            ? new Delta(new Pair(debtor, creditor), amount)
            : new Delta(new Pair(creditor, debtor), -amount);
}
```

Callers exclude self-debts before using this helper. Keeping the sign conversion in one place prevents expenses and settlements from developing subtly different conventions.

**Group.addExpense.**

We now know how to calculate shares. Next, we need to apply the whole expense without leaving some balances updated and others unchanged.

**Core logic:**

1. Validate the positive total, payer, and participant list.
2. Ask the strategy to calculate shares. Check that the returned participants and total match the expense.
3. Create an immutable Expense record.
4. Under the group lock, calculate the new balances for each participant who owes the payer. Skip the payer’s own share and any zero shares.
5. Store all new balances, append the expense to history, and return it.

For example, A paying ₹900 for A, B, and C creates B → A ₹300 and C → A ₹300. A’s own ₹300 share creates no debt.

**Edge cases:**

- Zero, negative, or non-integer total: reject.
- Payer or participant outside the group, an empty participant list, or duplicate participants: reject.
- Missing split values, mismatched counts, or invalid amounts or percentages: the strategy rejects them.
- Strategy output with missing or extra users, negative shares, or a sum different from the total: reject.
- Balance arithmetic exceeds Java’s `long` range: reject before storing any changes.
- The payer is the only participant, or some shares are zero: record the expense without creating debts for those shares.

Every rejection must leave balances and history unchanged. For example, shares of ₹300, ₹300, and ₹200 cannot cover a ₹900 expense. We reject that request before writing anything.

Why calculate `pending` first? In Java, checked arithmetic can fail. If we update Ben's balance and then discover overflow while updating Chen's, we have a partial expense. Preparing every new value before writing prevents that. Each participant produces at most one pair because there is exactly one payer and participants are unique.

The strategy retains no inputs or results, so concurrent calls can safely share its instance. Allocation happens outside the lock because it is a pure calculation and membership never changes in this version. Balance updates depend on current state and belong inside. That lets other operations use the group while shares are being calculated.

Python:

```python
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
    values = tuple(values) if values is not None else None
    # Expense inputs are local snapshots; strategies retain no per-call state.
    shares = dict(strategy.allocate(total, participants, values))
    if set(shares) != set(participants):
        raise ValueError("Allocation must contain exactly the participants")
    if not shares:
        raise ValueError("At least one participant is required")
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
```

Java:

```java
public Expense addExpense(String payer, long total, SplitStrategy strategy,
                          List<String> participants, List<Long> values) {
    if (total <= 0) throw new IllegalArgumentException("Positive total required");
    if (payer == null || !members.contains(payer))
        throw new IllegalArgumentException("Unknown payer");
    if (participants == null || participants.isEmpty())
        throw new IllegalArgumentException("Participants required");
    if (participants.stream().anyMatch(id -> id == null || id.isBlank()))
        throw new IllegalArgumentException("Invalid participant ID");
    participants = List.copyOf(participants);
    if (new HashSet<>(participants).size() != participants.size())
        throw new IllegalArgumentException("Duplicate participant");
    if (!members.containsAll(participants))
        throw new IllegalArgumentException("Unknown group participant");
    values = values == null ? null : new ArrayList<>(values);
    var shares = Map.copyOf(strategy.allocate(total, participants, values));
    if (!shares.keySet().equals(new HashSet<>(participants))) throw new IllegalArgumentException("Allocation must contain exactly the participants");
    if (shares.isEmpty()) throw new IllegalArgumentException("Participants required");
    long sum = 0;
    for (var entry : shares.entrySet()) {
        if (entry.getValue() < 0) throw new IllegalArgumentException("Negative share");
        sum = Math.addExact(sum, entry.getValue());
    }
    if (sum != total) throw new IllegalArgumentException("Invalid strategy result");
    var expense = new Expense(UUID.randomUUID().toString(), payer, total, shares);
    synchronized (lock) {
        Map<Pair, Long> pending = new HashMap<>();
        for (var entry : shares.entrySet()) {
            if (entry.getKey().equals(payer) || entry.getValue() == 0) continue;
            var d = delta(entry.getKey(), payer, entry.getValue());
            long next = Math.addExact(balances.getOrDefault(d.pair(), 0L), d.value());
            if (next == Long.MIN_VALUE) throw new IllegalArgumentException("Balance magnitude exceeds supported range");
            pending.put(d.pair(), next);
        }
        commit(pending, expense);
    }
    return expense;
}
```

The checks after `allocate` verify the returned user IDs, membership, nonnegative shares, and exact total. Group enforces these rules even if a strategy contains a bug.

**Committing balances and history together.**

Both expenses and settlements use this helper. The caller already holds the group lock and has finished all validation and arithmetic.

The `pending` map contains the new balance for each affected pair. Remove entries whose new balance is zero. Store the other balances, then append the event to history. The helper does not acquire the lock again:

Python:

```python
def _commit(self, pending, event):
    # Caller holds the group lock; all domain validation precedes this point.
    for pair, balance in pending.items():
        if balance == 0:
            self._balances.pop(pair, None)
        else:
            self._balances[pair] = balance
    self._history.append(event)
```

Java:

```java
private void commit(Map<Pair, Long> pending, Event event) {
    // Caller holds lock; domain validation and checked arithmetic are complete.
    pending.forEach((pair, value) -> {
        if (value == 0) balances.remove(pair);
        else balances.put(pair, value);
    });
    history.add(event);
}
```

All validation must finish before this method runs. Rejecting an expense after the first write could leave some balances changed. Reads use the same lock, so they wait until both balances and history are updated.

The lock does not protect us from a process crash. Saving these changes safely to a database requires a transaction, which we’ll discuss in the follow-ups.

**Group.recordSettlement.**

A settlement is not a negative expense. It has its own rule: there must already be enough debt in the requested direction.

**Core logic:**

1. Validate that the amount is positive and the two users are distinct group members.
2. Under the group lock, read the current debt in the requested payment direction.
3. Check that the payment does not exceed the debt.
4. Reduce the debt and append a settlement record. Remove the balance entry if the debt reaches zero.

If B owes A ₹150 and pays ₹100, B now owes A ₹50. History gains one settlement record.

**Edge cases:**

- Zero, negative, or non-integer payment amount: reject.
- Unknown member or payment to oneself: reject.
- No debt in the requested direction, including a payment in the reverse direction: reject.
- Payment greater than the outstanding debt: reject without changing balances or history.
- Payment exactly equals the debt: remove the balance entry and keep the settlement in history.
- Two settlements arrive together: check and reduce the debt under the same lock so both cannot spend the same outstanding amount.

For example, a ₹200 payment against a ₹150 debt is rejected. The debt stays ₹150 and no settlement is recorded.

We convert the direction into `+1` or `-1`, then interpret the stored balance through it. If `(A, B)` stores `-15000`, B owes A ₹150. For B paying A, the direction is `-1`, so the outstanding amount is `(-1) × (-15000) = 15000`.

Python:

```python
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
```

Java:

```java
public Settlement recordSettlement(String debtor, String creditor, long amount) {
    if (amount <= 0) throw new IllegalArgumentException("Positive settlement required");
    if (debtor == null || creditor == null || !members.contains(debtor) || !members.contains(creditor))
        throw new IllegalArgumentException("Unknown group member");
    if (debtor.equals(creditor)) throw new IllegalArgumentException("Cannot settle with yourself");
    var d = delta(debtor, creditor, 1);
    var event = new Settlement(UUID.randomUUID().toString(), debtor, creditor, amount);
    synchronized (lock) {
        long balance = balances.getOrDefault(d.pair(), 0L);
        long outstanding = d.value() * balance;
        if (amount > outstanding) throw new IllegalArgumentException("Settlement exceeds debt in this direction");
        commit(Map.of(d.pair(), balance - d.value() * amount), event);
    }
    return event;
}
```

The positive-amount check and `amount <= outstanding` reject absent debts and payments in the wrong direction. An exact settlement produces zero, so `commit` removes the pair. A partial settlement leaves a smaller debt in the same direction.

Creating the event before acquiring the lock doesn't record anything. It's just a local object. If validation fails inside the lock, that object is discarded and history remains unchanged.

**Reading balances and history.**

Reads use the same group lock. Otherwise a balance query could see Ben's updated share but Chen's old one halfway through an expense.

For a positive balance, the lower ID is the debtor. For a negative balance, the higher ID is the debtor. In either case, return a Debt record with a positive amount.

`getBalances` converts each stored pair into a Debt record and returns the records in a stable order. An empty balance map produces an empty result.

`getHistory` copies the history in the order events were accepted. Both methods hold the group lock while copying. The returned records are immutable, so callers cannot change group data through them.


Python:

```python
def get_balances(self):
    with self._lock:
        return tuple(
            Debt(a, b, value) if value > 0 else Debt(b, a, -value)
            for (a, b), value in sorted(self._balances.items())
        )

def get_history(self):
    with self._lock:
        return tuple(self._history)
```

Java:

```java
public List<Debt> getBalances() {
    synchronized (lock) {
        List<Debt> result = new ArrayList<>();
        balances.forEach((pair, value) -> result.add(value > 0
            ? new Debt(pair.lower(), pair.higher(), value)
            : new Debt(pair.higher(), pair.lower(), -value)));
        result.sort(Comparator.comparing(Debt::debtor).thenComparing(Debt::creditor));
        return List.copyOf(result);
    }
}

public List<Event> getHistory() {
    synchronized (lock) { return List.copyOf(history); }
}
```

The caller can keep or display a snapshot after the lock is released. It may become stale as new expenses arrive, which is normal. It cannot corrupt the group's internal state. A change can happen between calls to `getBalances` and `getHistory`. If a caller needs both from the same moment, return them together under one lock.

**Complexity.**

Let `k` be expense participants, `b` the group's nonzero debt pairs, and `h` its history length.

| Operation | Time | Additional observation |
| --- | --- | --- |
| Equal split | O(k log k) | Sorting makes remainder allocation deterministic. |
| Exact split | O(k) | Validate and copy shares. |
| Percentage split | O(k log k) | Sort by fractional remainder and ID. |
| Apply allocation | O(k) average | Prepare and update k pairs. Appending history takes amortized O(1). |
| Record settlement | O(1) average | One pair update and one history append. |
| Sorted balance snapshot | O(b log b) | O(b) output space. |
| History snapshot | O(h) | Copies references to immutable records. |

These time estimates treat arithmetic as constant time. With arbitrarily large Python integers, arithmetic also depends on the number of digits. History storage grows with all retained events and their allocations, not just the number of members. Pagination and archival are natural production additions.

### Expense, Settlement, and Debt

These records hold the results returned by Group. Python stores shares as a tuple of pairs. Java copies the shares into an unmodifiable map. Both prevent a caller from changing a saved expense.

Python:

```python
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
```

Java:

```java
public sealed interface Event permits Expense, Settlement {}
public record Expense(String id, String payer, long total, Map<String, Long> shares) implements Event {
    public Expense { shares = Map.copyOf(shares); }
}
public record Settlement(String id, String debtor, String creditor, long amount) implements Event {}
public record Debt(String debtor, String creditor, long amount) {}
```

### Complete reference implementations

- [Python implementation](splitwise.py): standard library only, including all strategies, records, Group, and service routing.
- [Java implementation](Splitwise.java): Java 17+, with immutable records, checked arithmetic, and equivalent operations. `Splitwise` is the service class name in this file.
- [Python verification suite](test_splitwise.py): rounding, ledger replay, settlement validation, isolation, and concurrent updates.
- [Java verification suite](SplitwiseTest.java): rounding, conservation, netting, settlements, overflow rejection, and competing settlements.

The implementations are deliberately small enough to read together with the article. They implement the base requirements. The extensions below are discussion topics.

Run the checks from this article's directory:

```sh
python3 -m unittest -v

# JDK 17 or newer
javac --release 17 -d /tmp/splitwise-classes Splitwise.java SplitwiseTest.java
java -cp /tmp/splitwise-classes SplitwiseTest
```

### Verification

Let’s check the balances and history after a sequence of operations. Use IDs A, B, and C for Asha, Ben, and Chen.

Before tracing the ledger, call the service with each split type and verify the shares. Reject unknown types, duplicate participants, mismatched value counts, invalid totals, and nonmembers without changing balances or history. Changing the caller's lists after a call must not alter the stored expense.

#### Test case 1: equal expense followed by an opposite debt

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

#### Test case 2: partial settlement and overpayment rejection

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

#### Test case 3: rounding and payer exclusion

An equal 10,000-paise split among A, B, C produces 3334, 3333, 3333. Reordering the input participants produces the same allocation.

The percentage example produces 34, 33, 34 from 101 paise and weights 3333, 3333, 3334. In both cases, summing the stored shares exactly reproduces the expense total.

For a separate expense where A pays ₹200 entirely for B and C, pass `EQUAL` with participants `[B, C]`. Both owe A ₹100. We do not force A into the participant set or invent an A share.

#### Test case 4: malformed allocations do nothing

Start with B owing A ₹50 and three existing history records. Try an exact ₹100 expense with A=₹40 and B=₹50:

```text
Service validates the inputs, finds the group, and selects ExactSplitStrategy.
Group validates payer A and total 10000.
ExactSplitStrategy adds the supplied shares: 4000 + 5000 = 9000.
9000 != 10000 → reject.
Group never reaches commit.

Afterward: B still owes A ₹50; history still contains three records.
```

Now try a different failure: an exact allocation totaling ₹100, but containing user D, who isn't a member. The strategy can calculate that allocation successfully. Group must reject it during membership validation, before changing any pair. This checks the boundary between allocation rules and group rules.

Also reject a negative share, an empty split, and percentages summing to 99.99%.

Compare both balances and history before and after each failure. Checking only for an exception is not enough. A method could change a balance and then throw.

#### Test case 5: competing settlements

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

#### Test case 6: reconstruct the balance index

Replay each expense by adding every nonpayer share to the corresponding pair. Replay each settlement by subtracting its directed amount. Remove zero entries. Compare that reconstructed map with the live balance snapshot.

This checks the relationship between history and balances across a sequence of operations. It is stronger than testing a single helper in isolation. Also verify that operations in one group do not change another group containing the same user IDs.

#### Test case 7: reuse a strategy across expenses

Use the same EqualSplitStrategy instance for 100 paise among A and B, then 90 paise among B, C, and D. Expect 50 each in the first result and 30 each in the second. Repeat with exact and percentage inputs, including concurrent calls with different participant lists. Each result must depend only on that call's inputs. An invalid call must not affect the next valid one.

## Extensibility

If there is time after the main implementation, discuss how the design would change for these new requirements.

### How would you simplify debts to reduce payments?

Suppose A owes B ₹300 and B owes C ₹300. Rather than making two payments, A could pay C directly. Everyone's net financial position would be the same.

> I'd derive each person's net position from the pair balances, then match debtors with creditors. I would first expose this as a proposed payment plan. Before applying the plan, we need to decide how settlements will work when the people paying each other have changed.

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

In our example, B's net position is zero, so B disappears from both lists. The only match is A paying C ₹300. With more people, each pass through the loop clears at least one person’s remaining amount. Building the positions takes O(b), sorting takes O(m log m), and matching takes O(m), where `b` is the number of current debt pairs and `m` the number of nonzero positions.

Each payment clears at least one remaining position. With `m` nonzero positions, this produces at most `m - 1` payments. It does not guarantee the fewest possible payments. Finding that minimum is a harder problem.

There is a subtle integration issue. In the original graph, A has no direct debt to C, so our base `recordSettlement(A, C, amount)` correctly rejects the suggested payment. Showing a simplified plan does not automatically make the ledger able to accept it.

One option is to replace the current debts with the proposed debts in a single operation. Record this change in history so we can still rebuild the balances. Check that each person’s overall amount stays the same. Also check that the group has not changed since we calculated the plan, for example by comparing a group version number.

Another option is to keep the original debts and reduce each debt along the agreed payment path when a payment happens. Either approach needs clear rules about whether members must agree to a change in whom they pay.

In an interview, explain both how to suggest fewer payments and how the system would record them.

### What if the client retries after a timeout?

Our generated event ID identifies an accepted record. It doesn't stop duplicate submissions. If an expense succeeded but the response was lost, retrying it currently adds the expense again.

> I'd require a caller-generated operation ID for mutations. Under the group lock, I'd look it up before applying the operation. An identical retry returns the original result. If the same ID comes with different input, reject it.

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

Check the operation ID, update balances and history, and save the result under the same lock. For settlements, check for a successful retry before rejecting it against the now-reduced debt.

Store a consistent representation of the request, or a fingerprint computed from it, so retries can be compared. Include the operation type, group, users, amount, split type, and split values. Two split types can produce the same shares but still represent different requests.

With a database, save the operation ID and result in the same transaction as the balance changes. A uniqueness constraint on group ID and operation ID prevents the same operation from being recorded twice.

Decide how long to keep these operation IDs. Once an ID is removed, a late retry could be treated as a new operation. Callers need to know how long retries are safe.

### How would you edit or delete an expense?

Updating the Expense object is the wrong starting point because it has already contributed to current balances. Removing it from history without undoing that contribution leaves the index inconsistent.

> I'd preserve the original record and append a correction. Under one group lock, reverse the original allocation, apply the replacement, and record the correction linking both versions. I'd prevent the same version from being reversed twice.

For deletion, there is no replacement allocation. For editing, validate the entire replacement before modifying any balances. A stable expense ID plus a revision number helps detect two people editing the same version concurrently.

Existing settlements make this interesting. Suppose Ben owed Asha ₹100, paid it, and the expense is later deleted. Reversing that expense now makes Asha owe Ben ₹100. Asha would now need to refund Ben. Confirm that this is the behavior the product wants.

```text
Original expense: (A,B) = -10000     B owes A ₹100
Settlement:      (A,B) += 10000     balance is zero
Delete expense:  (A,B) += 10000     A now owes B ₹100
```

The settlement remains in history because the payment really happened. The correction reverses the expense's contribution, not the entire pair balance. Resetting that pair to zero would erase the refund obligation and could also erase unrelated expenses.

We could forbid edits after an expense is settled. But our settlements reduce a combined debt, not a particular expense. To enforce that rule, we would need to track which expenses each repayment covers. Adding correction records fits our current design more easily.

### How would you support multiple payers?

Replace the single payer field with a map of `paidByUser`. Require its amounts to be nonnegative and sum to the expense total. The shares still sum to the same total.

For each user, compute:

```text
net contribution = amount paid - allocated share
```

A positive contribution means the user should receive money. A negative contribution means they owe money. Choose a consistent rule for matching people who owe money with people who should receive it.

When several people paid and several people owe, there may be more than one valid way to match them. For example, match users in ascending ID order. Store the resulting debts in the expense record. That lets us rebuild the same debts from history even if the matching rule changes later.

This matching only decides who owes whom for the new expense. Existing debts elsewhere in the group stay as they are.

### How would you add persistence or multiple currencies?

These are separate changes.

For persistence, store events and balance rows in one database transaction. A process-local group lock cannot coordinate multiple application instances. Use database concurrency control, such as locking a group row or checking a group version, with retries for conflicts. Keep idempotency records in that same transaction. Do not keep a database transaction open while waiting for someone to authorize a bank transfer. Payment processing needs a separate flow.

For currencies, never add INR and USD balances together. A Money value can hold the currency and an integer amount in its smallest unit, such as paise for INR. Include the currency in each debt’s key so balances stay separate. Currencies have different numbers of decimal places. Don’t assume that every currency uses two. If conversion is required, record the chosen exchange rate, conversion time, and rounding policy as part of the accepted operation. Conversion affects the amounts people owe, so agree on these rules before implementing it.

## What is expected at each level?

These are useful practice targets for this problem, rather than universal hiring rules.

### Junior

Aim for a working equal-split flow with a sensible service/group boundary. You should exclude the payer's own share from debt, record current balances, and support a valid settlement. Basic validation matters: reject unknown users, invalid amounts, and shares that don't add up. It's reasonable to need a hint about distributing leftover paise or netting opposite debts, but you should be able to trace the resulting arithmetic.

### Mid-level

Implement all three split types and make sure their shares add up exactly. Keep history separate from current balances, use signs consistently, and prevent callers from changing stored records. Reject settlements that exceed the debt.

Explain when separate strategies help and when a simple switch would be enough. Show why two simultaneous settlements need a lock around both the debt check and the update. Test that rejected operations leave balances and history unchanged.

### Senior

Clarify the requirements and the rules the system must always preserve. Explain why a person’s overall total cannot tell us whom they owe. Show why an expense must update the whole group together and why a thread-safe map alone does not ensure that.

Look for rounding errors, overflow, mutable input data, and duplicate retries without needing hints. For follow-ups, explain how to record simplified payments, correct expenses that have already been repaid, and handle concurrent updates in a database. Keep the main design small enough to implement and test.

## Test your understanding

1. Why doesn't a user's net position tell us whom they owe?
2. How do you split one paise equally among three people without creating or losing money?
3. Why must settlement validation happen inside the same lock as the balance update?
4. Why does an automatically generated Expense ID fail to prevent duplicate retries?
5. If a suggested simplified payment has no direct pair debt, what must change before recording it?

If you can answer those with concrete examples, you understand the parts of this design that matter most.
