# ATM Low Level Design

## Understanding the problem

An ATM lets a customer use a bank account without visiting a teller. The customer inserts a card, enters a PIN, and asks for cash. Our job is to coordinate that session, the bank, and the cash dispenser without losing track of the money.

The screen makes this look simple. The difficult moment comes after the bank approves a withdrawal. What if the machine cannot dispense the notes? What if it dispenses them but the reply is lost? We'll build the normal flow first, then make those outcomes explicit.

## Requirements

An interviewer might start with:

> Design an ATM that authenticates a customer and lets them check their balance or withdraw cash.

That leaves a few decisions open. Which operations belong to our code? Who owns the money? What should the machine do when cash delivery fails? Clarify those before choosing classes.

### Clarifying questions

> **You:** Which operations should we support? Do we need deposits and transfers?
>
> **Interviewer:** Support PIN authentication, balance inquiry, cash withdrawal, and cancellation. Leave deposits and transfers out.

This gives us a small customer flow: insert a card, authenticate, then read the balance or withdraw cash.

> **You:** Does the ATM own account balances and PIN verification?
>
> **Interviewer:** No. The bank authenticates the card and owns the account balance. Assume one account per card for this exercise.

We need a bank interface, not an account-management system. The ATM remembers the account returned by authentication. It does not store PINs or maintain a second account balance.

> **You:** Can the bank reserve the withdrawal amount before we dispense cash?
>
> **Interviewer:** Yes. It checks available funds and creates a hold in one operation. We can turn that hold into a debit after delivery or release it when no cash was delivered.

A hold makes those funds unavailable to other withdrawals. Reading the balance alone would not reserve them. We'll call the final debit operation `capture`.

> **You:** Which currency and notes should we support? Is there a withdrawal limit?
>
> **Interviewer:** Use INR with denomination counts configured at startup. Each request must be within a configured withdrawal limit and payable exactly with the available notes. We do not need to minimize the number of notes.

Use integer paise throughout. For example, ₹600 is `60000`, and three ₹200 notes are `{20000: 3}`. Enough total cash does not guarantee that an exact bundle is available.

> **You:** What happens after a wrong PIN or a completed withdrawal? When do we eject the card?
>
> **Interviewer:** Allow three rejected PIN attempts per inserted-card session, then eject. After a completed or definitely declined withdrawal, keep the authenticated session open. The customer can do another operation or cancel to end the session and eject.

The attempt count belongs to this session. Bank-wide card lockout is separate. Ending the session must also clear the authenticated account so the next customer starts fresh.

> **You:** Are we designing one machine or a fleet? Can requests overlap?
>
> **Interviewer:** One ATM with one active card session. Calls may arrive from different threads, so serialize them. Cancellation waits for a running withdrawal to finish. The bank handles account activity from other machines.

This lets us use one lock for local session and cash state. It does not replace the bank's protection of shared account funds.

> **You:** How much hardware failure handling do we need? What about a process crash?
>
> **Interviewer:** Use a hardware interface that reports full delivery, no delivery, or an uncertain result. Stop the ATM on uncertainty or failed card ejection. Leave persistent crash recovery and operator reconciliation for follow-ups.

The distinction matters: a lost reply does not prove that no cash was delivered. We'll keep the unresolved operation ID and stop instead of guessing whether to refund.

### Final requirements

1. Serve one ATM with one active card session and one bank account per card. Authenticate through the bank.
2. Allow available-balance inquiry and withdrawal only after authentication. Keep the session open after a completed or definitely declined withdrawal.
3. Eject the card after three rejected PIN attempts or when the customer cancels.
4. Withdraw a positive amount within the configured per-withdrawal limit. Find an exact bundle from the configured note counts.
5. Reserve bank funds before dispensing. Capture after confirmed delivery and release only after confirmed non-delivery.
6. Stop serving customers after an uncertain withdrawal or failed card ejection. Retain the operation ID for an unresolved withdrawal.
7. Serialize operations, including cancellation. Use INR and integer paise for all money values.

Out of scope:

- Deposits
- Transfers
- Multiple accounts per card
- Currency conversion
- Cash refilling during a session
- Receipt printing and screen rendering
- Persistent storage and crash recovery
- Automatic retries and reconciliation
- Bank-wide PIN lockout policy
- Automatic session expiry

These requirements define the behavior we will implement. Card ejection remains a hardware operation: clearing session memory cannot physically return a stuck card.

## Core entities and relationships

Start with the nouns in the requirements: ATM, session, card, account, bank, notes, and dispenser. Keep a class when it owns changing state, enforces a rule, or represents an external dependency.

The **ATM** needs to remember the active card and allowed operations. **CashInventory** needs to track note counts and find valid bundles. **BankGateway** and **Hardware** define the operations we need from systems outside that local state.

A session is just a few fields on this one ATM. It does not need its own class yet. We would reconsider that if sessions had a separate lifecycle or were stored independently.

| Entity | Responsibility |
| --- | --- |
| ATM | Own the current session and coordinate operations. |
| BankGateway | Authenticate a card, read available balance, and manage holds. |
| CashInventory | Find an exact note bundle and track confirmed dispensing. |
| Hardware | Dispense notes and eject the card. |

A card ID and an account ID are strings. We do not need a Customer or Account class because their data belongs to the bank. A map from denomination to count represents the cash stock. There is no useful behavior to put on an individual Banknote object here.

The ATM creates and owns one CashInventory. Startup code supplies the bank adapter and a hardware adapter for this machine. The screen controller calls ATM with a card ID, PIN, or amount. It never calls the bank or changes inventory directly.

For example, the controller calls `insertCard("card-A")`, then `enterPin("1234")`. Only after a successful PIN check can it call `withdraw(60000)` for ₹600. It does not supply an account ID for withdrawal. ATM uses the account returned by the bank for this session.

## Class design

We will start with the entry point, ATM, then define its dependencies. In these sketches, `-` marks private state or a private helper. `+` marks an operation available to the class’s caller. CashInventory’s caller is ATM, not the screen controller.

### ATM

The ATM owns the session. Let's connect the requirements to the state it needs:

| Requirement | State ATM needs |
| --- | --- |
| Accept one card and require authentication | Card ID, account ID, and current state |
| End the session after three rejected PINs | Attempt count |
| Respect the withdrawal limit and available notes | Limit and owned CashInventory |
| Stop after an uncertain withdrawal | Pending operation ID and OUT_OF_SERVICE state |
| Serialize requests on this machine | One lock shared by its operations |

The card ID identifies what was inserted. The account ID comes from successful authentication and is cleared when the session ends. Keeping both private prevents the caller from choosing a different account for a withdrawal.

```text
ATM
  - bank: BankGateway
  - hardware: Hardware
  - cash: CashInventory
  - withdrawalLimit: long              // paise
  - state: string                      // IDLE, PIN_REQUIRED, READY, OUT_OF_SERVICE
  - card: string | null
  - account: string | null
  - attempts: int
  - pending: string | null             // unresolved withdrawal operation ID
  - lock: Lock                         // Java uses this object's monitor

  + ATM(bank: BankGateway, hardware: Hardware,
        notes: Map<long, int>, withdrawalLimit: long)
  + insertCard(cardId: string) -> void
  + enterPin(pin: string) -> boolean
  + balance() -> long                   // available balance in paise
  + withdraw(amount: long) -> string    // amount in paise
  + cancel() -> void
  + state() -> string
  + pendingOperation() -> string | null
  + cashSnapshot() -> Map<long, int>
  - endSession(outOfService: boolean) -> void
```

Python uses `int` for money. Java uses `long` and `Map<Long, Integer>` for note counts. Python's `status()` returns the state and pending ID together. These inspection methods are for tests and maintenance, not account operations.

`enterPin` returns true when authentication succeeds and false when the bank rejects the card or PIN. Invalid input or an operation in the wrong state raises an error. `withdraw` returns a short result string for an attempted withdrawal:

| Result | Meaning for the caller |
| --- | --- |
| SUCCESS | The full bundle was delivered and the bank confirmed the debit. |
| CASH_UNAVAILABLE | No exact bundle is available. The bank was not asked to reserve funds. |
| DECLINED | The bank rejected the hold. No dispensing was attempted. |
| NOT_DISPENSED | No cash was delivered and the bank confirmed release of the hold. |
| PENDING_REVIEW | The outcome needs review. Do not treat it as success or retry as a new withdrawal. |

`cancel` ends the session and attempts ejection. It does not promise that a stuck card was physically returned. The controller can read the state to see whether the ATM was taken out of service.

| Current state | Event | Next state |
| --- | --- | --- |
| IDLE | Insert a card | PIN_REQUIRED |
| PIN_REQUIRED | Correct PIN | READY |
| PIN_REQUIRED | First or second rejected PIN | PIN_REQUIRED |
| PIN_REQUIRED | Third rejected PIN | IDLE if ejection succeeds |
| PIN_REQUIRED or READY | Cancel | IDLE if ejection succeeds |
| READY | Completed or definitely declined withdrawal | READY |
| Active session | Uncertain money operation or failed card ejection | OUT_OF_SERVICE |

Operations that are not allowed in the current state fail before changing the session. Cancelling while IDLE or OUT_OF_SERVICE does nothing. There is no customer operation that brings an OUT_OF_SERVICE machine back online.

An authentication outage also ends the session and disables this teaching ATM. A failed balance read changes no money or session state, so the error can be shown while leaving the customer authenticated.

Do we need the State pattern?

#### Good Solution: One class per state

A State interface can make sense when each state handles many operations differently. It also allows states to be tested separately. Here it would spread four short guards over several classes without making the withdrawal flow easier to follow.

#### Great Solution: Explicit state checks in ATM

For four states and a small set of operations, direct checks are easy to review. Every public operation checks whether it is allowed before doing work. We'll use this approach. If the state behavior grows, we can introduce state classes later.

**Our choice**

Use strings for this walkthrough. The transitions are the important part, not an enum or a hierarchy. Public methods change the state, callers cannot set it directly.

### BankGateway

The bank owns money. In particular, a balance check followed by an unrelated debit is not enough: another ATM could spend the same funds between those calls.

```text
interface BankGateway
  + authenticate(cardId: string, pin: string) -> string | null
  + availableBalance(accountId: string) -> long
  + hold(accountId: string, amount: long, operationId: string) -> boolean
  + capture(operationId: string) -> void
  + release(operationId: string) -> void
```

`hold` checks available funds and reserves them atomically at the bank. `false` means the bank definitely declined and created no hold. An exception means we do not know the result. `capture` converts the reservation into a debit. `release` removes the reservation. Available balance excludes active holds.

These are requirements of our bank adapter, not a claim that every bank exposes this exact API. The exercise assumes a hold stays valid until capture or release. Real expiry and recovery rules need an agreement with the bank.

### CashInventory

The inventory answers two different questions: “Can we make this amount?” and “Which notes definitely left the machine?” Planning must not remove notes.

```text
CashInventory                         // internal to ATM
  - notes: Map<long, int>                // denomination in paise -> count
  + CashInventory(notes: Map<long, int>)
  + plan(amount: long) -> Map<long, int> | null
  + recordDispensed(plan: Map<long, int>) -> void
  + snapshot() -> Map<long, int>
```

The ATM owns this object and serializes access to it. The constructor copies the initial stock. A snapshot returns a copy, so changing either map cannot change the machine's stock.

`plan` returns a separate map, such as `{20000: 3}` for three ₹200 notes. A missing plan means the amount cannot be made. Only ATM passes a successful plan to `recordDispensed`, while still holding its lock. Neither the customer nor the hardware adapter can edit the stored inventory.

### Hardware

```text
interface Hardware
  + dispense(notes: Map<long, int>) -> string
  + ejectCard() -> void
```

The dispenser reports `ALL` only when the exact bundle reached the customer. `NONE` means no cash was delivered. `UNKNOWN` covers uncertainty and partial delivery. A timeout is also uncertain. Those meanings must come from the hardware adapter, not from guessing based on an exception message.

## Implementation

We have four classes, but they do not all need the same amount of implementation work:

- **BankGateway and Hardware:** define their contracts. Real bank communication and device drivers stay outside this exercise.
- **CashInventory:** implement `plan` in detail because exact note selection is easy to get wrong. Its constructor and stock updates are short.
- **ATM:** implement the session methods, then spend most of our time on `withdraw`. This is where bank funds and physical cash must agree.

We'll build the dependencies first, then use them in ATM. Each method shown under a class belongs to that class. The complete files below put the methods and imports together.

For the important operations, we'll explain the **Core logic** and **Edge cases** before the code. Simple methods get a shorter explanation. The bank and hardware are interfaces because their real implementations are outside this exercise. The tests provide working fakes for both.

### BankGateway and Hardware

Define the contracts first. Authentication returns an account ID or a rejected result. The remaining bank methods use that account ID or the withdrawal's operation ID. The ATM never stores a PIN. The hardware adapter must report uncertainty honestly.


Python:

```python
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
```

Java:

```java
public interface BankGateway {
    String authenticate(String cardId, String pin); // null means rejected
    long availableBalance(String accountId);
    boolean hold(String accountId, long amount, String operationId);
    void capture(String operationId);
    void release(String operationId);
}

public interface Hardware {
    // ALL: exact bundle delivered. NONE: nothing delivered.
    // UNKNOWN: uncertain or partial delivery.
    String dispense(Map<Long, Integer> notes);
    void ejectCard();
}
```

### CashInventory

Start with the stock we were given at startup. The constructor rejects nonpositive denominations and negative counts. Zero counts are valid: a cassette may be empty. Copy the map so later changes to the caller's configuration cannot change the ATM's stock.


Python:

```python
def __init__(self, notes: dict[int, int]):
    if any(type(d) is not int or d <= 0 or type(n) is not int or n < 0
           for d, n in notes.items()):
        raise ValueError("Invalid denomination or note count")
    self._notes = dict(notes)
```

Java:

```java
private final Map<Long, Integer> notes;

CashInventory(Map<Long, Integer> notes) {
    for (var entry : notes.entrySet()) {
        if (entry.getKey() == null || entry.getKey() <= 0
                || entry.getValue() == null || entry.getValue() < 0) {
            throw new IllegalArgumentException("Invalid denomination or note count");
        }
    }
    this.notes = new HashMap<>(notes);
}
```

**Planning the bundle**

Let's decide how to choose notes. Suppose the ATM has one ₹500 note and three ₹200 notes. A customer asks for ₹600. Taking ₹500 first gets stuck, but three ₹200 notes work.

#### Bad Solution: Take the largest note and never reconsider

Greedy selection is short, but it rejects that valid ₹600 withdrawal. Checking total cash first does not fix the problem. We need a combination that respects both denominations and counts.

#### Great Solution: Try bounded combinations

Try the largest useful count of a denomination, then smaller counts if the remaining amount cannot be made. Each denomination has a fixed stock limit. Remember failed subproblems so we do not solve the same remainder repeatedly. This is a clear fit for a small, configured set of cassettes and a capped withdrawal amount.

#### Good Solution: Build a dynamic programming table

A table can record which amounts are reachable and reconstruct a bundle. It is useful when we want predictable bounds over a modest amount range. It also introduces more bookkeeping, particularly when note counts are limited. We do not need it for this walkthrough.

**Implementing `plan`**

ATM has already checked that the amount is positive and within the withdrawal limit. The planner only needs to solve the note-selection problem.

**Core logic:**

1. Visit denominations from largest to smallest.
2. Try a count no larger than the stock or the remaining amount allows.
3. Ask whether the smaller denominations can make the remainder.
4. Return the first complete bundle. Return no plan if every choice fails.

**Edge cases:**

- Enough total money but no exact bundle: return no plan.
- A denomination is exhausted: try zero notes of that denomination.
- A larger-note choice gets stuck: try fewer of those notes.
- Planning fails: leave every count unchanged.

`plan` sorts the denominations and starts the search. Its helper, `find_bundle`, receives the next denomination's index and the amount still needed. Reaching zero returns an empty map: we have successfully made the amount and need no more notes. Running out of denominations with money still needed returns `None` in Python or `null` in Java.

As a successful search returns, each level adds its chosen notes to that map. The code checks `is not None`, rather than whether the map is nonempty, because an empty map is a valid success at the end of the search.

The `failed` set remembers combinations of index and remaining amount that could not work. For example, after proving that the smaller notes cannot make ₹100, another path does not need to repeat that search. This cache belongs to one planning call because stock may change before the next withdrawal.

This finds a valid bundle with a preference for larger notes. It does not promise the fewest notes for every denomination set.


Python:

```python
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
```

Java:

```java
Map<Long, Integer> plan(long amount) {
    var denominations = new ArrayList<>(notes.keySet());
    denominations.sort(Comparator.reverseOrder());
    var failed = new HashMap<Integer, Set<Long>>();
    return findBundle(denominations, 0, amount, failed);
}

private Map<Long, Integer> findBundle(List<Long> denominations, int index,
        long remaining, Map<Integer, Set<Long>> failed) {
    if (remaining == 0) return new HashMap<>();
    if (index == denominations.size()
            || failed.getOrDefault(index, Set.of()).contains(remaining)) return null;
    long denomination = denominations.get(index);
    int limit = (int) Math.min(notes.get(denomination), remaining / denomination);
    for (int count = limit; count >= 0; count--) {
        var rest = findBundle(denominations, index + 1,
                remaining - count * denomination, failed);
        if (rest != null) {
            if (count > 0) rest.put(denomination, count);
            return rest;
        }
    }
    failed.computeIfAbsent(index, unused -> new HashSet<>()).add(remaining);
    return null;
}
```

**Recording delivery and reading stock**

`record_dispensed` is the only method that reduces stock. ATM calls it after the dispenser confirms delivery, using the plan it just created while holding the same lock. For a plan of `{20000: 3}`, it subtracts three from the ₹200 count. Planning alone never calls this method.

`snapshot` returns a separate map of counts. Python returns a mutable copy and Java returns an unmodifiable copy. In both cases, the stored inventory stays private.


Python:

```python
def record_dispensed(self, plan: dict[int, int]) -> None:
    # Only the owning ATM calls this, with its unchanged, successful plan.
    for denomination, count in plan.items():
        self._notes[denomination] -= count

def snapshot(self) -> dict[int, int]:
    return dict(self._notes)
```

Java:

```java
void recordDispensed(Map<Long, Integer> plan) {
    plan.forEach((denomination, count) ->
            notes.put(denomination, notes.get(denomination) - count));
}

Map<Long, Integer> snapshot() { return Map.copyOf(notes); }
```

### ATM

Start with the constructor. It receives the two adapters, the initial cash stock, and a withdrawal limit. It creates its own inventory and begins without a card or account. The default Python limit is ₹20,000, written as `2000000` paise.

All public operations use the same lock. One physical ATM serves one session at a time, so serial execution is a reasonable starting point. This lock protects local session and cash state. The bank must still protect the account across other ATMs.


Python:

```python
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
    self._card: str | None = None
    self._account: str | None = None
    self._attempts = 0
    self._pending: str | None = None
```

Java:

```java
private final BankGateway bank;
private final Hardware hardware;
private final CashInventory cash;
private final long withdrawalLimit;
private String state = "IDLE";
private String card;
private String account;
private int attempts;
private String pending;

public ATM(BankGateway bank, Hardware hardware, Map<Long, Integer> notes,
           long withdrawalLimit) {
    if (withdrawalLimit <= 0) throw new IllegalArgumentException("Invalid withdrawal limit");
    this.bank = bank;
    this.hardware = hardware;
    this.cash = new CashInventory(notes);
    this.withdrawalLimit = withdrawalLimit;
}
```

**Inserting a card and entering the PIN**

`insert_card` accepts a card only while idle. It stores the card ID and starts a fresh attempt count. `enter_pin` asks the bank to authenticate that card. It never compares PINs locally or saves the PIN for later.

**Core logic:**

1. Require a card waiting for authentication.
2. Send the card ID and PIN to the bank.
3. On success, keep the returned account ID and move to READY.
4. On rejection, count the attempt. After the third rejection, end the session and eject.

**Edge cases:**

- A second card arrives during a session: reject it without replacing the first card.
- Empty input: reject it before calling the bank. It does not count as a rejected PIN attempt.
- Bank authentication fails with an exception: end the session and take the ATM out of service.
- Repeated PIN submissions after success: reject them because the ATM is already READY.

The three-attempt counter is local to one session. It does not prevent someone from trying another ATM or reinserting a card. Bank-wide lockout is a separate bank responsibility.


Python:

```python
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
```

Java:

```java
public synchronized void insertCard(String cardId) {
    if (!state.equals("IDLE")) throw new IllegalStateException("ATM is not available");
    if (cardId == null || cardId.isBlank()) throw new IllegalArgumentException("Card ID required");
    card = cardId;
    attempts = 0;
    state = "PIN_REQUIRED";
}

public synchronized boolean enterPin(String pin) {
    if (!state.equals("PIN_REQUIRED")) throw new IllegalStateException("Insert a card first");
    if (pin == null || pin.isEmpty()) throw new IllegalArgumentException("PIN required");
    String authenticated;
    try {
        authenticated = bank.authenticate(card, pin);
    } catch (RuntimeException failure) {
        endSession(true);
        throw new IllegalStateException("Bank unavailable");
    }
    if (authenticated == null) {
        attempts++;
        if (attempts == 3) endSession(false);
        return false;
    }
    account = authenticated;
    state = "READY";
    return true;
}
```

**Reading the balance**

After authentication, ask the bank for the current available balance. We do not cache it in the ATM because other account activity can change it. If the bank read fails, the error reaches the caller without changing cash or ending the session.


Python:

```python
def balance(self) -> int:
    with self._lock:
        if self._state != "READY":
            raise ValueError("Authenticate first")
        return self._bank.available_balance(self._account)
```

Java:

```java
public synchronized long balance() {
    if (!state.equals("READY")) throw new IllegalStateException("Authenticate first");
    return bank.availableBalance(account);
}
```

**Withdrawing cash**

This is the core operation. We need both a valid cash bundle and reserved bank funds before asking the dispenser to move money.

**Core logic:**

1. Check the session and amount.
2. Find an exact bundle using the current stock.
3. Create an operation ID and ask the bank to hold the amount.
4. Send the planned notes to the dispenser.
5. After confirmed delivery, reduce inventory and capture the hold.
6. Clear the pending ID and report success.

**Edge cases:**

- Invalid amount or unauthenticated session: reject before any side effect.
- No exact bundle: return CASH_UNAVAILABLE without contacting the bank.
- Bank declines: return DECLINED without dispensing.
- Dispenser confirms no delivery: release the hold and keep inventory unchanged.
- Dispensing is partial or uncertain: keep the operation pending and stop the ATM.
- Hold, capture, or release throws: stop and retain the operation ID for review.

Why not simply debit first and refund on error?

#### Bad Solution: Refund after every dispenser exception

A timeout may happen after cash was delivered. Refunding in that case gives the customer both the cash and the money in their account. An exception tells us that communication failed, not necessarily that dispensing failed.

#### Great Solution: Resolve known outcomes and stop on uncertainty

Capture after confirmed delivery. Release after confirmed non-delivery. For everything else, keep the bank operation unresolved and stop accepting new sessions until it can be reconciled. This avoids guessing whether physical cash moved.

**The withdrawal method**

Before calling the bank, save the new operation ID in `pending`. If the hold request times out, that ID is how we identify the request whose outcome is unknown. Clear it only after a definite decline, a confirmed release, or a confirmed capture.

The `try` block starts at the first operation that can affect money. Invalid input and an unavailable cash bundle are handled before it. An exception inside the block leaves the operation pending and ends the session. The code does not attempt a refund from the exception handler.

Notice that inventory is reduced before capture. Once delivery is confirmed, those notes are gone even if the capture response later times out. For UNKNOWN, the stored counts are only the last confirmed stock. They must not be treated as current stock until maintenance reconciles the machine.


Python:

```python
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
```

Java:

```java
public synchronized String withdraw(long amount) {
    if (!state.equals("READY")) throw new IllegalStateException("Authenticate first");
    if (amount <= 0 || amount > withdrawalLimit)
        throw new IllegalArgumentException("Amount must be positive and within the limit");
    var plan = cash.plan(amount);
    if (plan == null) return "CASH_UNAVAILABLE";
    String operationId = UUID.randomUUID().toString();
    pending = operationId;
    try {
        if (!bank.hold(account, amount, operationId)) {
            pending = null;
            return "DECLINED";
        }
        String outcome = hardware.dispense(Map.copyOf(plan));
        if ("NONE".equals(outcome)) {
            bank.release(operationId);
            pending = null;
            return "NOT_DISPENSED";
        }
        if (!"ALL".equals(outcome)) {
            endSession(true);
            return "PENDING_REVIEW";
        }
        cash.recordDispensed(plan);
        bank.capture(operationId);
        pending = null;
        return "SUCCESS";
    } catch (RuntimeException failure) {
        endSession(true);
        return "PENDING_REVIEW";
    }
}
```

There is no automatic retry here. Calling `withdraw` again starts a new operation. In production, a retry needs a stable request ID and a stored outcome. We'll cover that extension below.

**Cancellation and ending the session**

Cancellation ends a session waiting for a PIN or ready for operations. It does nothing while idle, and it cannot reopen an out-of-service ATM. Because operations are serialized, cancellation waits for a running withdrawal to finish. It cannot interrupt physical dispensing halfway through.

`end_session` is shared by cancellation, the third rejected PIN, authentication outages, and uncertain withdrawals. It removes the card and account from session memory and attempts ejection. It deliberately preserves a pending operation ID. Failed ejection leaves the machine out of service.


Python:

```python
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
```

Java:

```java
public synchronized void cancel() {
    if (state.equals("PIN_REQUIRED") || state.equals("READY")) endSession(false);
}

private void endSession(boolean outOfService) {
    state = outOfService ? "OUT_OF_SERVICE" : "IDLE";
    card = null;
    account = null;
    attempts = 0;
    try {
        hardware.ejectCard();
    } catch (RuntimeException failure) {
        state = "OUT_OF_SERVICE";
    }
}
```

**Inspecting the ATM**

`status` returns the current state and pending operation ID together in Python. Java exposes them through `state` and `pendingOperation`. These are reads, so none of them clears the pending ID.

`cash_snapshot` delegates to the inventory's copying method. All these reads take the same lock as writes. A pending ID is a clue for reconciliation, not permission to refund or restart the machine.


Python:

```python
def status(self) -> tuple[str, str | None]:
    with self._lock:
        return self._state, self._pending

def cash_snapshot(self) -> dict[int, int]:
    with self._lock:
        return self._cash.snapshot()
```

Java:

```java
public synchronized String state() { return state; }

public synchronized String pendingOperation() { return pending; }

public synchronized Map<Long, Integer> cashSnapshot() { return cash.snapshot(); }
```

### Verification

Walk through the outcomes before adding more features. Use a fake bank with an account balance and a map of active holds. Use a fake dispenser whose result can be set to ALL, NONE, UNKNOWN, or a timeout. This makes failure paths reproducible without real banking or hardware.

#### A successful withdrawal that greedy selection would miss

Start with ₹1,000 in the account and cash stock `{50000: 1, 20000: 3}`. Authenticate, then withdraw `60000` paise. Expect three ₹200 notes, ₹400 remaining in the account, and no active hold. The ₹500 note must remain in the machine.

```text
Initial: bank balance = 100000 paise, no holds
         notes = {50000: 1, 20000: 3}

plan(60000) -> {20000: 3}              // inventory unchanged
hold(account, 60000, operationId)     // available balance becomes 40000
hardware.dispense({20000: 3}) -> ALL
recordDispensed({20000: 3})           // notes become {50000: 1, 20000: 0}
capture(operationId)                 // posted balance becomes 40000, hold removed

Result: SUCCESS, ATM stays READY, pending ID cleared
```

#### Rejection must not move money

Try withdrawal before authentication, zero, a negative amount, and an amount above the limit. All must fail before a bank hold. Try ₹100 against the same stock: cash planning fails even though total cash is sufficient. Then lower bank funds below a valid bundle's amount: the bank declines and the dispenser is never called.

#### Delivery outcomes must have different effects

| Result | Bank funds | Inventory | ATM |
| --- | --- | --- | --- |
| ALL and successful capture | Debited | Remove delivered notes | READY |
| NONE and successful release | Unchanged, no hold | Unchanged | READY |
| UNKNOWN or dispenser timeout | Hold unresolved | Last confirmed counts only | OUT_OF_SERVICE |
| ALL but capture times out | Capture outcome unresolved | Remove delivered notes | OUT_OF_SERVICE |
| NONE but release times out | Release outcome unresolved | Unchanged | OUT_OF_SERVICE |

A fake can throw after creating a hold. That tests why an exception must not be interpreted as a definite decline. Also test capture and release both before and after the bank applies the change. The ATM sees the same timeout in either case.

For example, the customer receives ₹200 and the bank captures the hold, but its reply never arrives:

```text
Bank before withdrawal: 100000 paise
hold(20000) succeeds
Dispenser reports ALL
ATM removes one 20000-paise note from inventory
Bank captures the hold: balance = 80000, hold removed
Capture reply is lost: ATM receives a timeout

ATM result: PENDING_REVIEW
ATM state: OUT_OF_SERVICE, operation ID retained
No refund and no second dispensing attempt
```

The test knows the bank applied the debit because it controls the fake. The ATM does not know that yet. Retaining the ID allows later review to resolve the outcome without moving money again. Check that `cancel` cannot bring the machine back online.

#### Session boundaries and concurrent calls

Try a session trace as well. This checks that a rejected operation does not quietly change who is using the ATM.

```text
Insert card-A                 -> PIN_REQUIRED, attempts = 0
Enter a wrong PIN            -> PIN_REQUIRED, attempts = 1
Try to insert card-B         -> error, card-A stays in the session
Enter the correct PIN        -> READY for card-A's account
Cancel                       -> IDLE, account cleared, card ejected
Try to read the balance      -> error, authentication required
Insert card-A again          -> PIN_REQUIRED, attempts = 0
Reject three PINs            -> IDLE, card ejected once more
```

Also cancel while waiting for a PIN. The next inserted card must get a fresh attempt count. If ejection fails instead, expect OUT_OF_SERVICE and reject the next card. Calling cancel again must not retry ejection or bring the ATM online.

Three wrong PINs should eject once and clear the session. Cancellation should remove access to balance and withdrawal. A failed ejection should disable the ATM. A failed balance read should leave the authenticated session open because it changes no money. With only one ₹200 note, two concurrent ₹200 withdrawals should produce one success and one cash shortage. They must never both dispense the same note.

The included tests also compare the planner against all combinations of several small inventories. That checks exact amounts, available counts, and planning without mutation instead of only checking one happy path.

Run the tests from the repository root:

```sh
python3 -m unittest discover -s atm -v
javac -d /tmp/atm-java atm/ATM.java atm/ATMTest.java
java -cp /tmp/atm-java ATMTest
```

The Java tests use Java 21 or later. The Python implementation works with Python 3.9 or later. Download [Python tests](test_atm.py) or [Java tests](ATMTest.java) to inspect the fakes and assertions.

### Complete reference implementations

The walkthrough excerpts come directly from these files. Python needs the imports at the top of the complete file. Java nests the two interfaces and CashInventory inside ATM to keep the example easy to compile. The design responsibilities are the same in both languages.

Download [atm.py](atm.py) or [ATM.java](ATM.java).

## Follow-ups

**What happens if the process crashes after cash is delivered?**

Our pending ID is only in memory, so this version cannot recover safely from that crash. Persist a withdrawal record before creating the hold. Record each known outcome and retain the hardware's durable journal reference. On restart, reconcile bank and dispenser records before accepting more withdrawals. A database transaction alone cannot roll back cash already handed to a customer.

**How would you support retries?**

Give the withdrawal a stable request ID before the first attempt. Store its amount, account, and result. Repeating that ID must return or resume the same operation, not dispense again. The bank and hardware adapters need compatible deduplication or status-query support. Generating a new UUID for each retry does not provide idempotency.

**What if only some notes were delivered?**

Treat that as UNKNOWN in the current interface. A richer adapter can report the exact delivered bundle when the hardware can prove it. Reconciliation then settles the delivered amount and corrects inventory. Do not release the whole hold merely because the requested bundle was incomplete.

**Can we avoid holding a lock during bank calls?**

Yes, but we need an explicit in-progress operation and rules for what other requests can do during it. Holding one lock is easy to reason about for one physical customer session. The trade-off is that balance, cancellation, and status calls wait behind a slow operation. A production controller would keep the screen responsive while refusing conflicting money operations.

**How would cash refilling work?**

Only allow it in a maintenance state with no unresolved withdrawal. Reconcile physical counts, then replace the configured inventory under the ATM lock. An operator should not simply switch OUT_OF_SERVICE to IDLE while an uncertain hold or dispensing result remains.

**What would change without bank holds?**

The bank adapter might instead offer a debit with a reversal reference. The same uncertainty rule still applies: a reversal is appropriate only when the system has evidence that cash was not delivered. The protocol must define status queries, retries, and reconciliation. Do not quietly replace a hold with a local balance check.

## What is expected at each level?

For an early-career interview, aim for clear ownership, valid session transitions, and a complete withdrawal that checks bank funds and note availability. Explain your assumptions about failures rather than skipping them.

For a mid-level interview, show the exact-bundle problem, separate planning from mutation, and explain why a bank reservation is different from reading a balance. Walk through definite failures and uncertainty with concrete examples.

For a senior interview, discuss crash recovery, duplicate requests, partial delivery, and the bank/hardware contract. Keep those extensions connected to specific failure scenarios. Adding more patterns or classes is not a substitute for knowing what happens to the customer's money.

## Test your understanding

- The ATM has ₹500 and three ₹200 notes. Why can a greedy ₹600 withdrawal fail?
- Cash was delivered, but capture timed out. Which local data can we update confidently?
- Why is a rejected hold different from a hold request that throws?
- Why does cancelling an uncertain withdrawal not release the funds?
- Which parts of this design must become durable before it can recover from a restart?
