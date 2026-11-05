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

Clearing session memory cannot return a stuck card. We still need the hardware to confirm ejection.

## Core entities and relationships

Start with the nouns in the requirements: ATM, session, card, account, bank, notes, and dispenser. Keep a class when it owns changing state, enforces a rule, or represents an external dependency.

The **ATM** needs to remember the active card and allowed operations. **CashInventory** needs to track note counts and find valid bundles. **BankGateway** and **Hardware** define the operations we need from systems outside that local state.

For one ATM, the session can stay as fields on ATM. A separate Session class becomes useful if we later need to store and manage sessions independently.

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
  - state: ATMState                    // IDLE, PIN_REQUIRED, READY, OUT_OF_SERVICE
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
  - endSession(outOfService: boolean) -> void
```

Python uses `int` for money. Java uses `long` and `Map<Long, Integer>` for note counts.

`enterPin` returns true when authentication succeeds and false when the bank rejects the card or PIN. Invalid input or an operation in the wrong state raises an error. `withdraw` returns a short result string for an attempted withdrawal:

| Result | Meaning for the caller |
| --- | --- |
| SUCCESS | The full bundle was delivered and the bank confirmed the debit. |
| CASH_UNAVAILABLE | No exact bundle is available. The bank was not asked to reserve funds. |
| DECLINED | The bank rejected the hold. No dispensing was attempted. |
| NOT_DISPENSED | No cash was delivered and the bank confirmed release of the hold. |
| PENDING_REVIEW | The outcome needs review. Do not treat it as success or retry as a new withdrawal. |

`cancel` ends the session and attempts ejection. It does not promise that a stuck card was physically returned.

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

A State interface can make sense when each state handles many operations differently. It also allows states to be tested separately. Here it would spread a few short state checks across several classes without making withdrawal easier to follow.

#### Great Solution: Explicit state checks in ATM

For four states and a small set of operations, direct checks are easy to review. Card entry, PIN entry, balance inquiry, and withdrawal check the current state before doing work. We'll use this approach. If the state behavior grows, we can introduce state classes later.

**Our choice**

Use an `ATMState` enum with four values: `IDLE`, `PIN_REQUIRED`, `READY`, and `OUT_OF_SERVICE`. It gives us named states and catches misspelled values. The enum defines the allowed values. ATM still checks which transitions are allowed.

An enum and the State pattern solve different problems. We can use an enum with these direct checks. A class per state becomes useful when each state needs substantial behavior of its own.

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
```

ATM owns this object and allows only one operation to use it at a time. The constructor copies the initial stock so later changes to the caller's map cannot change the machine's stock.

`plan` returns a separate map, such as `{20000: 3}` for three ₹200 notes. A missing plan means the amount cannot be made. Only ATM passes a successful plan to `recordDispensed`, while still holding its lock. Neither the customer nor the hardware adapter can edit the stored inventory.

### Hardware

```text
interface Hardware
  + dispense(notes: Map<long, int>) -> string
  + ejectCard() -> void
```

The dispenser reports `ALL` only when the exact bundle reached the customer. `NONE` means no cash was delivered. `UNKNOWN` covers uncertainty and partial delivery. A timeout is also uncertain. Those meanings must come from the hardware adapter, not from guessing based on an exception message.

## Implementation

We now have the pieces for one withdrawal. ATM asks CashInventory for a bundle, BankGateway for a hold, and Hardware to deliver the notes. Once delivery is confirmed, ATM updates CashInventory and asks BankGateway to capture the hold. Neither the inventory nor the dispenser decides whether the customer is authenticated. That check stays in ATM.

The two methods worth spending most of our interview time on are `CashInventory.plan` and `ATM.withdraw`. The first chooses notes without changing stock. The second coordinates the bank and dispenser, including failures. We will also show the complete session methods so the flow from inserting a card to ejecting it is clear.

Here is what we will implement:

- **ATMState:** define the allowed states.
- **BankGateway:** define authentication, balance inquiry, and hold operations.
- **Hardware:** define cash delivery and card ejection.
- **CashInventory:** implement `plan` in detail because exact note selection is easy to get wrong. Its constructor and stock updates are short.
- **ATM:** implement card entry, PIN checks, balance inquiry, withdrawal, and cancellation.

We'll build the dependencies first, then use them in ATM. Each method shown under a class belongs to that class. The complete files below put the methods and imports together.

For important operations, we'll explain the **Core logic** and **Edge cases** before the code. Simple methods get a shorter explanation. The tests use a fake bank and dispenser so we can control their responses.

### ATMState

Define the four states used by ATM. Python imports `Enum` from the standard library. The ATM methods will use these values when checking and changing state.


Python:

```python
class ATMState(Enum):
    IDLE = "IDLE"
    PIN_REQUIRED = "PIN_REQUIRED"
    READY = "READY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
```

Java:

```java
public enum ATMState {
    IDLE, PIN_REQUIRED, READY, OUT_OF_SERVICE
}
```

### BankGateway

The bank interface provides authentication, available-balance inquiry, and hold operations. Authentication returns an account ID or a rejected result. A rejected hold returns false, while an exception leaves its outcome uncertain.

Each adapter call waits for a result or times out. The bank adapter must not call ATM methods while ATM is waiting for it, because ATM still holds the lock.


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
```

### Hardware

The hardware interface handles dispensing and card ejection. `dispense` reports ALL, NONE, or UNKNOWN according to the delivery guarantees defined above. A timeout does not prove that the external action stopped. Failed ejection raises an error so ATM can take the machine out of service.

The hardware adapter must also avoid calling ATM methods while ATM holds its lock.


Python:

```python
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

Try the largest useful count of a denomination, then smaller counts if the remaining amount cannot be made. Each denomination has a fixed stock limit. Remember failed searches so we do not repeat them. This works well for a small set of note denominations and a limited withdrawal amount.

#### Good Solution: Build a dynamic programming table

A table can record which amounts are reachable and reconstruct a bundle. This can work well when the range of possible amounts is small. We also need to track how many notes of each denomination are available. We do not need it for this walkthrough.

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

Why is the cache key just `(index, remaining)`? Earlier choices used only larger denominations. They did not change the stock of any denomination still ahead of us. The same index and remainder therefore describe the same remaining problem within this call.

Walk through our ₹600 example before reading the code:

```text
Available: one ₹500 note, three ₹200 notes
Need: ₹600

Try one ₹500 note -> ₹100 remains
  ₹200 cannot fit -> no bundle
Try zero ₹500 notes -> ₹600 remains
  Try three ₹200 notes -> ₹0 remains -> success
Return {20000: 3} in paise. Stock is still unchanged.
```

Trying zero is essential. Without that choice, the search would never discover a bundle made entirely from smaller notes.

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

**Recording delivery**

`record_dispensed` is the only method that reduces stock. ATM calls it after the dispenser confirms delivery, using the plan it just created while holding the same lock. For a plan of `{20000: 3}`, it subtracts three from the ₹200 count. Planning alone never calls this method.


Python:

```python
def record_dispensed(self, plan: dict[int, int]) -> None:
    # Only the owning ATM calls this, with its unchanged, successful plan.
    for denomination, count in plan.items():
        self._notes[denomination] -= count
```

Java:

```java
void recordDispensed(Map<Long, Integer> plan) {
    plan.forEach((denomination, count) ->
            notes.put(denomination, notes.get(denomination) - count));
}
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
    self._state = ATMState.IDLE
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
private ATMState state = ATMState.IDLE;
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

Reinserting a card starts a new attempt count. Blocking that card across all ATMs belongs to the bank.


Python:

```python
def insert_card(self, card_id: str) -> None:
    with self._lock:
        if self._state != ATMState.IDLE:
            raise ValueError("ATM is not available")
        if not isinstance(card_id, str) or not card_id.strip():
            raise ValueError("Card ID required")
        self._card = card_id
        self._attempts = 0
        self._state = ATMState.PIN_REQUIRED

def enter_pin(self, pin: str) -> bool:
    with self._lock:
        if self._state != ATMState.PIN_REQUIRED:
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
        self._state = ATMState.READY
        return True
```

Java:

```java
public synchronized void insertCard(String cardId) {
    if (state != ATMState.IDLE) throw new IllegalStateException("ATM is not available");
    if (cardId == null || cardId.isBlank()) throw new IllegalArgumentException("Card ID required");
    card = cardId;
    attempts = 0;
    state = ATMState.PIN_REQUIRED;
}

public synchronized boolean enterPin(String pin) {
    if (state != ATMState.PIN_REQUIRED) throw new IllegalStateException("Insert a card first");
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
    state = ATMState.READY;
    return true;
}
```

**Reading the balance**

After authentication, ask the bank for the current available balance. We do not cache it in the ATM because other account activity can change it. If the bank read fails, the error reaches the caller without changing cash or ending the session.


Python:

```python
def balance(self) -> int:
    with self._lock:
        if self._state != ATMState.READY:
            raise ValueError("Authenticate first")
        return self._bank.available_balance(self._account)
```

Java:

```java
public synchronized long balance() {
    if (state != ATMState.READY) throw new IllegalStateException("Authenticate first");
    return bank.availableBalance(account);
}
```

**Withdrawing cash**

This is the core operation. We need both a valid cash bundle and reserved bank funds before asking the dispenser to move money.

Plan the notes first. If the machine cannot make the amount, there is no reason to reserve the customer's funds. Keep the same ATM lock until withdrawal finishes so another call cannot use those notes between planning and delivery. We do not reserve notes in a second data structure because no other operation can change this inventory while the lock is held.

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

Capture after confirmed delivery. Release after confirmed non-delivery. If the outcome is unknown, stop accepting customers until the bank and dispenser records have been checked.

**The withdrawal method**

Before calling the bank, save the new operation ID in `pending`. If the hold request times out, that ID is how we identify the request whose outcome is unknown. Clear it only after a definite decline, a confirmed release, or a confirmed capture.

The `try` block starts at the first operation that can affect money. Invalid input and an unavailable cash bundle are handled before it. An exception inside the block leaves the operation pending and ends the session. The code does not attempt a refund from the exception handler.

Keep track of what is known at each failure point:

| Where the reply is lost | What we know | What we do |
| --- | --- | --- |
| Holding funds | No dispense call was made. The bank may have reserved funds. | Keep the operation ID and stop. |
| Dispensing | Some, all, or none of the notes may have left. | Keep the hold unresolved and stop. Do not guess a refund. |
| Capturing funds | All notes were delivered. The debit may already be posted. | Keep the reduced stock and operation ID, then stop. |
| Releasing funds after NONE | No notes were delivered. The bank may already have released the hold. | Keep stock unchanged and the operation ID, then stop. |

The lock prevents two local operations from overlapping. It cannot undo cash delivery or make the bank and dispenser commit together. That is why we still need PENDING_REVIEW even though every ATM method is synchronized.

Notice that inventory is reduced before capture. Once delivery is confirmed, those notes are gone even if the capture response later times out. For UNKNOWN, the stored counts are only the last confirmed stock. They must not be treated as current stock until maintenance reconciles the machine.


Python:

```python
def withdraw(self, amount: int) -> str:
    with self._lock:
        if self._state != ATMState.READY:
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
    if (state != ATMState.READY) throw new IllegalStateException("Authenticate first");
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

Each accepted withdrawal creates a new operation ID. After PENDING_REVIEW, the ATM rejects further withdrawals. In production, retrying an earlier operation needs a stable request ID and a stored outcome. We'll cover that extension below.

**Cancellation and ending the session**

Cancellation ends a session waiting for a PIN or ready for operations. It does nothing while idle, and it cannot reopen an out-of-service ATM. Because operations are serialized, cancellation waits for a running withdrawal to finish. It cannot interrupt physical dispensing halfway through.

`end_session` is shared by cancellation, the third rejected PIN, authentication outages, and uncertain withdrawals. It removes the card and account from session memory and attempts ejection. It deliberately preserves a pending operation ID. Failed ejection leaves the machine out of service.


Python:

```python
def cancel(self) -> None:
    with self._lock:
        if self._state in (ATMState.PIN_REQUIRED, ATMState.READY):
            self._end_session()

def _end_session(self, out_of_service: bool = False) -> None:
    self._state = ATMState.OUT_OF_SERVICE if out_of_service else ATMState.IDLE
    self._card = None
    self._account = None
    self._attempts = 0
    try:
        self._hardware.eject_card()
    except Exception:
        self._state = ATMState.OUT_OF_SERVICE
```

Java:

```java
public synchronized void cancel() {
    if (state == ATMState.PIN_REQUIRED || state == ATMState.READY) endSession(false);
}

private void endSession(boolean outOfService) {
    state = outOfService ? ATMState.OUT_OF_SERVICE : ATMState.IDLE;
    card = null;
    account = null;
    attempts = 0;
    try {
        hardware.ejectCard();
    } catch (RuntimeException failure) {
        state = ATMState.OUT_OF_SERVICE;
    }
}
```

### Verification

Walk through the outcomes before adding more features. Use a fake bank with an account balance and a map of active holds. Use a fake dispenser whose result can be set to ALL, NONE, UNKNOWN, or a timeout. This makes failure paths reproducible without real banking or hardware. The tests check internal state after operations finish. Python reads the private-by-convention fields, and Java uses reflection in the test file.

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

Also combine failures: let dispensing return UNKNOWN and then make card ejection fail. The pending ID must survive both failures. Another card, PIN, balance inquiry, or withdrawal must be rejected without another bank or dispense call. Cancellation must not retry ejection or clear the pending ID.

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

A failed balance read should leave the authenticated session open because it changes no money. With only one ₹200 note, two concurrent ₹200 withdrawals should produce one success and one cash shortage. They must never both dispense the same note.

For cancellation during withdrawal, pause the fake dispenser and start cancellation on another thread. Cancellation must wait without ejecting. After ALL, finish capture and then eject. After UNKNOWN, end out of service and retain the pending ID. The waiting cancellation must not clear it or eject a second time.

Check ownership across the public API too. Authenticate card A, cancel, then authenticate card B. Balance and withdrawal calls must use B's account. The caller never supplies that account ID. Also change the startup stock map after constructing ATM. Stored stock must keep its original counts.

Test a withdrawal exactly at the configured limit. It should succeed when funds and notes are available. A second request for the same note must report CASH_UNAVAILABLE after the first request uses it.

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

An interviewer may now change one of our assumptions. Start by explaining where the current design falls short, then name the fields or methods you would change. A short answer is often enough. The examples below go further so you can work through the details if asked.

### 1. What happens if the process crashes after cash is delivered?

Suppose a customer withdraws ₹600. The bank creates the hold, the dispenser hands over three ₹200 notes, and the process crashes before calling `capture`. Our in-memory `pending` field disappears. On restart, the constructor loads its initial note counts and starts in IDLE. Both choices are unsafe after this crash. We could reuse notes that have left the machine or leave the customer's hold unresolved.

The missing piece is a withdrawal record that survives the process. ATM already coordinates every step, so it is the place to record progress. CashInventory continues to choose notes, and the bank continues to own account funds.

> I would save the withdrawal before contacting the bank and record each confirmed outcome. On restart, I would keep the machine unavailable while comparing unfinished withdrawals with the bank and dispenser records. I would use the original operation ID to finish the existing withdrawal.

The record needs enough information to investigate after the card and account fields have been cleared.

```text
WithdrawalRecord
  operationId: string
  accountId: string
  amount: long                          // paise
  plannedNotes: Map<long, int>
  phase: WithdrawalPhase
  result: string | null

WithdrawalPhase
  CREATED, HOLD_REQUESTED, HELD, DISPENSE_REQUESTED,
  DELIVERED, NOT_DELIVERED, COMPLETED, NEEDS_REVIEW
```

Save a request phase **before** making the corresponding external call. Save its confirmed outcome afterward. For example, persist DISPENSE_REQUESTED before asking Hardware to dispense, then DELIVERED only after confirmed delivery. If the process dies between those writes, the record tells us delivery may have happened.

That gap cannot be closed with a database transaction around `dispense`. The dispenser is a separate physical device. We need to pass the operation ID to an extended hardware adapter and ask it for a durable delivery result after restart. The bank needs a matching operation-status lookup.

| Recovery evidence | Next action |
| --- | --- |
| Bank hold exists and hardware proves full delivery | Finish capture using the original ID. |
| Bank hold exists and hardware proves the command delivered nothing and cannot deliver later | Release the hold. |
| Bank already captured the withdrawal | Record that result without another debit. |
| Hardware cannot establish the delivery outcome | Keep the ATM out of service and retain the record for review. |

A missing hardware record alone may be inconclusive. A command could still be in flight, or the journal could be unavailable. We need a device guarantee before treating that as non-delivery.

There is a second recovery problem. A crash can happen after inventory is reduced but before completion is saved. Replaying that update would subtract the same notes twice. Store inventory updates with the operation ID and apply each once, or rebuild counts from a reconciled hardware journal and physical count. The startup configuration is no longer the source of truth after the machine has served customers.

This adds storage writes and recovery coordination to the withdrawal path. In an interview, the main points are the durable record, the uncertain gap around each external call, and a clear rule for when the machine can serve customers again.

### 2. How would you support retries without dispensing twice?

Imagine the controller submits a withdrawal, cash is delivered, and the response to the controller is lost. It submits the same request again. Our current `withdraw(amount)` creates a fresh operation ID for every accepted call, so that second call would look like another withdrawal.

The controller must create an ID when the customer confirms the withdrawal and reuse it when retrying that submission. A deliberate second withdrawal gets a new ID. This changes the public method only when retry support becomes a requirement.

```text
ATM
  + withdraw(requestId: string, amount: long) -> string
```

> I would look up the request before starting any money operation. If it already completed, I would return the stored result. If it is still running or uncertain, I would return PENDING_REVIEW or an in-progress result. I would also check that the ID still refers to the same account and amount.

Use the durable withdrawal record from the previous follow-up. The lookup and creation must be atomic so two threads cannot both claim a new ID.

```text
At withdrawal admission, while holding the ATM lock
  require an authenticated session
  record = store.find(requestId)
  if record exists
    require record.accountId == currentAccount
    require record.amount == amount
    return record.result if completed, otherwise PENDING_REVIEW

  require the machine is ready for a new withdrawal
  validate amount and plan notes
  store.insertUnique(requestId, currentAccount, amount, plannedNotes)
  // Only the caller that created the record starts the withdrawal.
```

The stored account prevents another customer's session from reusing the ID to retrieve or execute that withdrawal. The pending record also keeps the machine unavailable to competing money operations.

Application deduplication solves only one part. If the bank captures successfully and its reply is lost, a retry must not post another debit. Give bank operations a documented repeat-by-ID contract. The hardware needs durable deduplication of `dispense(operationId, notes)`, or a status lookup that conclusively resolves the earlier command. If it offers neither, an uncertain dispense must stay pending for review.

For the ₹600 example, repeating request `W1` after SUCCESS returns W1's saved result. While delivery is uncertain, the current ATM ends the session and stays out of service. It rejects the retry until recovery resolves the withdrawal and the customer authenticates again. Reusing W1 for ₹800 is rejected.

Keep completed IDs long enough to cover the supported retry window. Deleting a record too early allows an old request to look new. That retention policy is part of the retry contract.

### 3. What if only some notes were delivered?

Our Hardware contract groups partial delivery into UNKNOWN. That keeps the basic ATM conservative, but it cannot tell a customer how much cash they actually received.

Suppose we requested three ₹200 notes and the device can prove that two reached the customer. We know ₹400 was delivered, while the hold is still for ₹600. The useful extension is a delivery report with evidence about both customer delivery and cassette movement.

```text
DeliveryReport
  outcome: string                       // COMPLETE, PARTIAL, NONE, UNKNOWN
  deliveredNotes: Map<long, int>         // notes confirmed received by customer
  removedFromCassettes: Map<long, int>   // includes notes moved to a reject bin
  journalId: string
```

Those two maps answer different questions. Delivered notes determine the amount to debit. Notes removed from cassettes determine which notes can still be dispensed. A note trapped inside the machine may be unavailable even though the customer never received it.

> I would extend Hardware to return the confirmed bundle. ATM would calculate the delivered amount and ask the bank to capture that amount from the hold. CashInventory would apply the confirmed cassette changes. If either amount is uncertain, I would keep the withdrawal pending.

This also requires a bank contract change. Our existing `capture(operationId)` captures the entire hold. For partial delivery, we need a settlement operation that captures the delivered amount and releases the unused portion of the reservation.

```text
BankGateway
  + settleHold(operationId: string, deliveredAmount: long) -> void
```

For this extension, `settleHold` must validate that the delivered amount is within the hold, support safe repetition by ID, and reject a conflicting amount for an already settled operation.

```text
Requested amount        60000 paise
Confirmed delivered     {20000: 2}
Amount to capture       40000 paise
Unused hold to release  20000 paise
```

The ATM should remain out of service after partial delivery until the device fault and stock are checked. Knowing the delivered amount resolves the money question, but the dispenser may still be jammed. If the report itself is uncertain, avoid calculating a refund from an estimate.

The added report is justified when the hardware can provide reliable evidence. A richer object cannot create certainty that the device does not have.

### 4. Can we avoid holding the ATM lock during bank calls?

In the current implementation, `withdraw` holds the lock from validation through completion. A slow bank call also blocks cancellation and balance inquiry. Releasing the lock around the network call sounds straightforward, but it creates a new race.

```text
Thread A plans a withdrawal and releases the lock
Thread B cancels the session and inserts another card
Thread A resumes and reads the new session's account
```

The withdrawal must keep the account and notes it was accepted with. It must also claim the machine before releasing the lock.

> I would add a WITHDRAWING state and retain one active operation. Under the lock, I would validate the session, copy the account and plan into that operation, and mark the machine busy. External calls would use that saved data. I would reacquire the lock to apply the result.

```text
ATM gains
  state: ATMState                       // add WITHDRAWING
  activeOperation: WithdrawalRecord | null
  endSessionAfterWithdrawal: boolean
```

The operation belongs to ATM and contains the account, amount, and note plan. Each external step uses that record rather than reading the current session again.

```text
1. Under lock
   Validate the session and amount
   Plan notes, create activeOperation, set WITHDRAWING

2. Outside lock
   Perform hold, dispense, and the appropriate bank settlement
   Use activeOperation's saved inputs and record each confirmed outcome

3. Under lock
   Verify the result belongs to the active operation
   Apply confirmed inventory changes exactly once
   Finish in READY or OUT_OF_SERVICE
   Honor a queued request to end the session
```

While WITHDRAWING, another withdrawal, card insertion, and maintenance request must fail. Cancellation can set `endSessionAfterWithdrawal` and return promptly. It cannot eject immediately or release a hold while dispensing may be underway. After a known outcome, finish the money operation and end the session. After uncertainty, stop the machine and retain the operation for review.

This version also needs an explicit rule for balance inquiry. The simplest choice is to reject it while a withdrawal is active. If the product needs live balance updates, define their account and timing semantics separately.

The trade-off is more coordination code and more transitions to test. For a single-customer ATM, the current lock is a reasonable interview choice. Split the lock scope when responsiveness is an explicit requirement.

### 5. How would cash refilling work?

The constructor currently accepts note counts once. Adding a public `addNotes` method would let someone change inventory while a withdrawal is using a plan, or put a faulty machine back online before an unresolved withdrawal is checked.

Cash refilling needs a maintenance flow. Add MAINTENANCE to ATMState and expose maintenance operations to the operator-side component when that requirement is introduced.

```text
ATM
  + beginMaintenance() -> void
  + replaceCashCounts(counts: Map<long, int>) -> void
  + finishMaintenance() -> void
```

> I would allow maintenance only after the customer session has ended and all withdrawals have been resolved. While the machine is in MAINTENANCE, an operator can replace counts with physically verified totals. Returning to IDLE also requires a successful device check.

These operations use the same ATM lock as customer actions. `beginMaintenance` rejects an active card or withdrawal. An OUT_OF_SERVICE machine with an unresolved operation must complete reconciliation before entering this refill flow. A stuck card also needs to be handled before normal service resumes.

`replaceCashCounts` validates denominations and nonnegative counts, makes a defensive copy, and updates CashInventory. Use final verified counts rather than an increment that could be applied twice if the operator retries.

For example, if there are four usable ₹200 notes and the operator loads ten more, the verified count is fourteen. Submitting fourteen twice should still leave fourteen. A persistent version also records the operator action and the resulting counts before reopening.

Replacing counts makes the operator's physical count authoritative, so entry into maintenance and completion of device checks matter. Refilling alone does not prove that an earlier uncertain withdrawal was settled correctly.

### 6. What would change if the bank did not support holds?

Our current flow relies on a reservation that can later be captured or released. If the bank only supports a debit and a reversal, the sequence changes. Confirm the bank's guarantees before changing the adapter.

> I would debit before dispensing and keep the debit reference with the withdrawal. If the bank definitely declines, I would stop before touching the dispenser. If the debit succeeds and the dispenser proves that no cash was delivered, I would reverse that debit. An uncertain outcome would stay pending for review.

A reversal cancels a particular debit. It needs the original reference and its own safe retry rules.

| Outcome | Next action |
| --- | --- |
| Debit is definitely declined | Return DECLINED without dispensing. |
| Debit reply is lost | Query the debit by operation ID and resolve it before proceeding. |
| Debit confirmed, full cash delivery confirmed | Complete the withdrawal. |
| Debit confirmed, no delivery conclusively confirmed | Reverse the original debit. |
| Cash delivery or reversal outcome is uncertain | Retain the references and stop for review. |

Suppose a ₹600 debit succeeds, the dispenser confirms NONE, and the reversal times out. The customer may already have been refunded, or the debit may still stand. Keep the reversal pending and check its status using the same reference. Sending another untracked refund risks crediting twice.

The difference from holds is visible to the customer. Funds have been posted as a debit before cash is delivered, and a reversal may take time to appear. That is a product and bank-integration trade-off. ATM still coordinates the steps, but BankGateway's methods and the withdrawal's recorded phases must reflect the protocol the bank actually supports.


## What is expected at each level?

For an early-career interview, aim for clear ownership, valid session transitions, and a complete withdrawal that checks bank funds and note availability. Explain your assumptions about failures rather than skipping them.

For a mid-level interview, show the exact-bundle problem, separate choosing notes from reducing stock, and explain why a bank reservation is different from reading a balance. Walk through definite failures and uncertainty with concrete examples.

For a senior interview, discuss crash recovery, duplicate requests, partial delivery, and the bank/hardware contract. Keep those extensions connected to specific failure scenarios. Adding more patterns or classes is not a substitute for knowing what happens to the customer's money.

## Test your understanding

- The ATM has ₹500 and three ₹200 notes. Why can a greedy ₹600 withdrawal fail?
- Cash was delivered, but capture timed out. Which local data can we update confidently?
- Why is a rejected hold different from a hold request that throws?
- Why does cancelling an uncertain withdrawal not release the funds?
- Which records must survive a restart before this design can recover safely?
