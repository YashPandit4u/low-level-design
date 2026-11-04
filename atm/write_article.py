"""Build the article from prose and exact, tested source excerpts."""
from pathlib import Path
import ast
import textwrap
ROOT = Path(__file__).resolve().parent
python = (ROOT/'atm.py').read_text()
java = (ROOT/'ATM.java').read_text()
tree = ast.parse(python)

def py_class(name):
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    return '\n'.join(python.splitlines()[node.lineno-1:node.end_lineno])

def py_methods(names, class_name='ATM'):
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    nodes = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    return '\n\n'.join(textwrap.dedent('\n'.join(python.splitlines()[n.lineno-1:n.end_lineno])) for n in nodes)

def java_block(start):
    offset = java.index(start)
    opening = java.index('{', offset)
    depth = 1; end = opening+1
    while depth:
        depth += (java[end] == '{') - (java[end] == '}')
        end += 1
    return textwrap.dedent(java[java.rfind('\n',0,offset)+1:end])

def pair(p,j):
    return '\nPython:\n\n```python\n'+p+'\n```\n\nJava:\n\n```java\n'+j+'\n```\n'

article = '''# ATM Low Level Design

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

A State interface can make sense when each state handles many operations differently. It also allows states to be tested separately. Here it would spread a few short state checks across several classes without making withdrawal easier to follow.

#### Great Solution: Explicit state checks in ATM

For four states and a small set of operations, direct checks are easy to review. Card entry, PIN entry, balance inquiry, and withdrawal check the current state before doing work. Inspection methods remain available in every state. We'll use this approach. If the state behavior grows, we can introduce state classes later.

**Our choice**

Use strings for this walkthrough. The transitions are the important part, not an enum or a hierarchy. Only ATM methods change the state. Callers cannot set it directly.

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

ATM owns this object and allows only one operation to use it at a time. The constructor copies the initial stock. A snapshot returns a copy, so changing either map cannot change the machine's stock.

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

- **BankGateway and Hardware:** define their contracts. Real bank communication and device drivers stay outside this exercise.
- **CashInventory:** implement `plan` in detail because exact note selection is easy to get wrong. Its constructor and stock updates are short.
- **ATM:** implement card entry, PIN checks, balance inquiry, withdrawal, and cancellation.

We'll build the dependencies first, then use them in ATM. Each method shown under a class belongs to that class. The complete files below put the methods and imports together.

For important operations, we'll explain the **Core logic** and **Edge cases** before the code. Simple methods get a shorter explanation. The tests use a fake bank and dispenser so we can control their responses.

### BankGateway and Hardware

These interfaces define what ATM can ask the bank and hardware to do. Each call waits for a result or times out. The adapters must not call ATM methods while ATM is waiting for them, because it still holds the lock. A timeout does not prove that the external action stopped.

'''
article += pair(py_class('BankGateway')+'\n\n'+py_class('Hardware'), java_block('public interface BankGateway')+'\n\n'+java_block('public interface Hardware'))
article += '''
### CashInventory

Start with the stock we were given at startup. The constructor rejects nonpositive denominations and negative counts. Zero counts are valid: a cassette may be empty. Copy the map so later changes to the caller's configuration cannot change the ATM's stock.

'''
article += pair(py_methods(['__init__'], 'CashInventory'),
                'private final Map<Long, Integer> notes;\n\n' + java_block('CashInventory(Map'))
article += '''
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

'''
article += pair(py_methods(['plan'], 'CashInventory'),
                java_block('Map<Long, Integer> plan') + '\n\n' + java_block('private Map<Long, Integer> findBundle'))
article += '''
**Recording delivery and reading stock**

`record_dispensed` is the only method that reduces stock. ATM calls it after the dispenser confirms delivery, using the plan it just created while holding the same lock. For a plan of `{20000: 3}`, it subtracts three from the ₹200 count. Planning alone never calls this method.

`snapshot` returns a separate map of counts. Python returns a mutable copy and Java returns an unmodifiable copy. In both cases, the stored inventory stays private.

'''
article += pair(py_methods(['record_dispensed', 'snapshot'], 'CashInventory'),
                java_block('void recordDispensed') + '\n\n' + java_block('Map<Long, Integer> snapshot'))
article += '''
### ATM

Start with the constructor. It receives the two adapters, the initial cash stock, and a withdrawal limit. It creates its own inventory and begins without a card or account. The default Python limit is ₹20,000, written as `2000000` paise.

All public operations use the same lock. One physical ATM serves one session at a time, so serial execution is a reasonable starting point. This lock protects local session and cash state. The bank must still protect the account across other ATMs.

'''
fields = java[java.index('    private final BankGateway bank;'):java.index('    public ATM(')]
article += pair(py_methods(['__init__']), textwrap.dedent(fields)+java_block('public ATM('))
article += '''
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

'''
article += pair(py_methods(['insert_card','enter_pin']),java_block('public synchronized void insertCard')+'\n\n'+java_block('public synchronized boolean enterPin'))
article += '''
**Reading the balance**

After authentication, ask the bank for the current available balance. We do not cache it in the ATM because other account activity can change it. If the bank read fails, the error reaches the caller without changing cash or ending the session.

'''
article += pair(py_methods(['balance']), java_block('public synchronized long balance'))
article += '''
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

'''
article += pair(py_methods(['withdraw']),java_block('public synchronized String withdraw'))
article += '''
There is no automatic retry here. Calling `withdraw` again starts a new operation. In production, a retry needs a stable request ID and a stored outcome. We'll cover that extension below.

**Cancellation and ending the session**

Cancellation ends a session waiting for a PIN or ready for operations. It does nothing while idle, and it cannot reopen an out-of-service ATM. Because operations are serialized, cancellation waits for a running withdrawal to finish. It cannot interrupt physical dispensing halfway through.

`end_session` is shared by cancellation, the third rejected PIN, authentication outages, and uncertain withdrawals. It removes the card and account from session memory and attempts ejection. It deliberately preserves a pending operation ID. Failed ejection leaves the machine out of service.

'''
article += pair(py_methods(['cancel','_end_session']),java_block('public synchronized void cancel')+'\n\n'+java_block('private void endSession'))
article += '''
**Inspecting the ATM**

`status` returns the current state and pending operation ID together in Python. Java exposes them through `state` and `pendingOperation`. These are reads, so none of them clears the pending ID.

`cash_snapshot` delegates to the inventory's copying method. All these reads take the same lock as writes. The pending ID identifies the withdrawal to investigate. It does not tell us whether a refund is safe.

'''
article += pair(py_methods(['status','cash_snapshot']),java_block('public synchronized String state')+'\n\n'+java_block('public synchronized String pendingOperation')+'\n\n'+java_block('public synchronized Map<Long, Integer> cashSnapshot'))
article += '''
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

A failed balance read should leave the authenticated session open because it changes no money. With only one ₹200 note, two concurrent ₹200 withdrawals should produce one success and one cash shortage. They must never both dispense the same note.

For cancellation during withdrawal, pause the fake dispenser and start cancellation on another thread. Cancellation must wait without ejecting. After ALL, finish capture and then eject. After UNKNOWN, end out of service and retain the pending ID. The waiting cancellation must not clear it or eject a second time.

Check ownership across the public API too. Authenticate card A, cancel, then authenticate card B. Balance and withdrawal calls must use B's account. The caller never supplies that account ID. Also change the startup stock map and a returned snapshot: neither should change stored stock. Python allows editing its snapshot copy. Java rejects edits to its unmodifiable snapshot.

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

**What happens if the process crashes after cash is delivered?**

Our pending ID is only in memory, so a crash loses it. Save a withdrawal record to persistent storage before creating the hold. Save each confirmed outcome and the ID of the dispenser's stored transaction record. After restarting, compare the bank and dispenser records before accepting more withdrawals. A database rollback cannot take cash back from a customer.

**How would you support retries?**

Give the withdrawal a stable request ID before the first attempt. Store its amount, account, and result. Repeating that ID must return or resume the same operation, not dispense again. The bank and hardware must recognize repeated IDs or let us check an earlier result. That is what makes a retry safe. Giving every retry a new ID would make it look like another withdrawal.

**What if only some notes were delivered?**

Treat that as UNKNOWN in the current interface. A richer adapter can report the exact delivered bundle when the hardware can prove it. After checking those records, settle only the amount delivered and correct the note counts. Do not release the whole hold merely because the requested bundle was incomplete.

**Can we avoid holding a lock during bank calls?**

Yes, but we need an explicit in-progress operation and rules for what other requests can do during it. Holding one lock is easy to reason about for one physical customer session. The trade-off is that balance, cancellation, and status calls wait behind a slow operation. A production controller would keep the screen responsive while refusing conflicting money operations.

**How would cash refilling work?**

Only allow it in a maintenance state with no unresolved withdrawal. Check the physical note counts, then update the inventory under the ATM lock. An operator should not simply switch OUT_OF_SERVICE to IDLE while an uncertain hold or dispensing result remains.

**What would change without bank holds?**

The bank adapter might instead offer a debit with a reversal reference. The same uncertainty rule still applies: a reversal is appropriate only when the system has evidence that cash was not delivered. The protocol must define status queries, retries, and reconciliation. Do not quietly replace a hold with a local balance check.

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
'''
(ROOT/'TUTORIAL-DETAILED.md').write_text(article)
print('Wrote', len(article.split()), 'words including code')
