# Vending Machine Low Level Design

## Understanding the problem

A customer inserts coins, chooses an item, and collects the item and any change. The machine also lets the customer cancel and get back the coins they inserted.

The tricky part is what the machine can actually give back. Suppose a snack costs ₹4 and the customer inserts ₹10. The machine owes ₹6. It might have ₹11 in change but still fail to make ₹6 with the coins it has. A balance alone cannot answer that question.

## Requirements

> Design a vending machine that accepts coins, sells products by slot code, and returns change.

### Clarifying questions

> **You:** Can a customer buy several items in one transaction?
>
> **Interviewer:** One item per purchase. A customer can insert coins, attempt a purchase, or cancel. If the purchase completes, the next customer starts with zero credit.

We need one active credit balance. We can leave carts and item reservations out of the core design.

> **You:** Which coins do we accept? Can the machine use a customer's inserted coins as change?
>
> **Interviewer:** Accept ₹1, ₹2, ₹5, and ₹10 coins, with at most ₹1,000 of credit. Keep inserted coins in escrow until the sale completes. Make change from a separate set of coin tubes.

Escrow is where the machine holds this customer's coins. Cancellation returns those same coins. Change comes from the tubes, so inserting a coin increases credit without increasing the change supply.

> **You:** What if the selected slot is empty or the machine cannot give exact change?
>
> **Interviewer:** Leave credit available. The customer can select a different slot, insert more coins, or cancel.

Check stock and plan exact change before asking the dispenser to move anything.

> **You:** What if the product drops and then the change mechanism jams?
>
> **Interviewer:** Handle confirmed delivery and uncertain outcomes separately. If we cannot complete the sale after the product drops, take the machine out of service and keep enough information for review.

The machine must distinguish a failed product drop from a failed payout after the customer already received the product.

> **You:** Can commands overlap? Can a technician refill the machine during a purchase?
>
> **Interviewer:** Customer commands can arrive concurrently within a session. Process them one at a time. Load stock, prices, and the initial change float at startup. Refilling is a follow-up.

One lock is enough for one machine. The controller keeps commands scoped to the active customer, and hardware calls finish or time out without calling back into the machine while it holds the lock.

### Final requirements

1. Serve one customer at a time. Sell one item per purchase from a slot with a configured price and quantity.
2. Accept ₹1, ₹2, ₹5, and ₹10 coins. Store money in whole rupees and limit credit to ₹1,000. Reject unsupported coins and deposits above the limit without changing credit.
3. Before dispensing, check slot stock and credit, then find exact change from the available change tubes. Leave credit available when any of those checks fails.
4. Dispense the product before paying change. Update stock and change counts after their respective confirmed deliveries. Collect the escrowed coins and clear credit once the sale completes.
5. Cancel by returning the inserted coins from escrow. Clear credit after confirmed return.
6. If the device confirms that the product did not drop, keep the stock and credit available. If delivery is uncertain or a payout fails, stop serving customers and preserve the information needed for review.
7. Serialize customer commands, including cancellation.

Out of scope:

- Cards, UPI, and notes
- Shopping carts
- Restocking and live price updates
- Durable crash recovery and automatic retries
- Coin sensing and motor control
- Screen rendering

## Core entities and relationships

Start with the responsibilities that differ. The machine knows whether the customer can buy. The coin bank knows which combinations of coins are possible. Hardware knows what actually came out.

| Type | Responsibility |
| --- | --- |
| VendingMachine | Own credit, serialize commands, and coordinate the sale. |
| Slot | Hold a price and the number of units in one physical slot. |
| CoinBank | Plan exact change within the tube counts and deduct confirmed payouts. |
| Hardware | Report delivery from product dispensing, change payout, and escrow return. |
| PendingPurchase | Retain the chosen slot, planned change, and whether the product was confirmed delivered. |

A slot code identifies a physical position. If the same chips are in A1 and B1, buying A1 reduces A1's quantity. We can add product names to the catalog later without changing the purchase flow.

The machine owns its own slot copies and one CoinBank. The constructor receives a hardware adapter for that machine. The coin acceptor presents a verified coin to `insertCoin` and returns it if rejected. On acceptance, the machine directs the coin into escrow before adding credit. When the sale completes, the machine moves escrow into a separate collection box. This exercise treats both of those routing operations as reliable. Product delivery, change payout, and escrow return can fail.

## Class design

### VendingMachine

The machine needs a slot lookup, one customer's credit, and a way to stop new operations if something goes wrong.

| Requirement | State needed |
| --- | --- |
| Buy from a slot code | Map from code to Slot |
| Accept and refund a customer's payment | Credit backed by the coins in escrow |
| Make exact change | One CoinBank for the tube counts |
| Keep an uncertain sale available for review | PendingPurchase and an out-of-service state |
| Prevent overlapping commands | One lock for the machine |

```text
VendingMachine
  - slots: Map<string, Slot>
  - coins: CoinBank
  - hardware: Hardware
  - credit: int
  - state: MachineState
  - pending: PendingPurchase or null
  - lock: Lock

  + VendingMachine(slots: Map<string, Slot>, change: Map<int, int>, hardware: Hardware)
  + insertCoin(coin: int) -> boolean
  + buy(slotCode: string) -> PurchaseResult
  + cancel() -> boolean
```

The controller passes the selected slot code. The machine looks up the price and stock, so the caller cannot supply a cheaper price. For coin insertion, false means the coin should be returned. For cancellation, true means no customer credit remains. False means the refund needs review and the machine has stopped.

Two states are enough. READY allows customer commands. OUT_OF_SERVICE rejects them. Credit distinguishes a session with payment from one without payment. The lock prevents another command from entering while a sale is running.

#### Good Solution: Put each mode in its own class

A State pattern can help when every mode has its own substantial behavior. Here, the out-of-service behavior is one rule shared by three methods. A class per mode would spread those methods out without removing any purchase logic.

#### Great Solution: Keep an enum and check it at each entry point

Use READY and OUT_OF_SERVICE. A failed payout can change the state before releasing the lock, so a cancellation waiting on the lock cannot issue a second payout. This keeps the rule close to each customer command.

### Slot

```text
Slot
  price: int
  quantity: int
```

The slot holds the selling price and count. The machine decrements the count after confirmed product delivery. A product may already be gone even if change has not been paid.

### CoinBank

```text
CoinBank
  - counts: Map<int, int>                 // denomination -> available count
  + plan(amount: int) -> Map<int, int> or null
  + recordPaid(plan: Map<int, int>)
```

`plan` returns a bundle or null when no bundle exists. An empty bundle means the customer paid exactly. These are different outcomes. `recordPaid` applies the change payout once the hardware confirms it.

The customer cannot call CoinBank directly. VendingMachine keeps the same lock from planning through payout, so no other command can spend those coins in between.

### Hardware

```text
interface Hardware
  + acceptCoin(coin: int)
  + collectEscrow()
  + dispenseProduct(slotCode: string) -> Delivery
  + dispenseChange(coins: Map<int, int>) -> Delivery
  + returnEscrow() -> Delivery
```

Product delivery concerns one item. For coin delivery, ALL means the complete requested bundle reached the customer. NONE means nothing reached them. UNKNOWN covers both uncertain and partial delivery. A timeout leaves the outcome uncertain too.

`returnEscrow` returns the customer's original coins from a different compartment. It does not draw from the change tubes.

### PendingPurchase

```text
PendingPurchase
  slotCode: string
  change: Map<int, int>
  productDelivered: boolean
```

Save this record before asking the product dispenser to move. If the product is confirmed delivered, set `productDelivered` before starting the change payout. With that flag set, review starts from “item delivered, change unresolved.” Without it, product delivery is uncertain and the payout has not started.

Credit and the record stay in memory when a purchase needs review. A failed cancellation has no purchase record. The remaining credit identifies the unresolved escrow refund. These are diagnostic facts, and the machine stays closed to customer operations until a recovery procedure is added.

### PurchaseResult

| Result | Meaning |
| --- | --- |
| SUCCESS | Product and any required change were delivered. |
| SOLD_OUT | The slot is empty. |
| INSUFFICIENT_CREDIT | The customer needs to insert more money or choose a cheaper item. |
| EXACT_CHANGE_UNAVAILABLE | The change tubes cannot make the amount owed. |
| NOT_DISPENSED | Hardware confirmed that the product did not reach the customer. Credit remains available. |
| PENDING_REVIEW | The machine stopped because delivery or payout needs review. |

An unknown slot is an invalid request. A valid slot with zero items is a normal purchase outcome.

## Implementation

Spend most of the interview on `buy` and `CoinBank.plan`. The first shows when we commit each part of the sale. The second shows how stock limits affect exact change. We'll start at the customer-facing machine and work down to its dependencies.

### VendingMachine

**Creating the machine**

Validate and copy the configured slots, load the change tubes, and start ready with zero credit. The copy lets us change a slot quantity without editing the caller's configuration.

```text
VendingMachine(slots, change, hardware)
    this.slots = {}
    for code, slot in slots
        if code == null or code is empty or slot == null
            throw Error("Invalid slot")
        this.slots[code] = Slot(slot.price, slot.quantity)
    coins = CoinBank(change)
    this.hardware = hardware
    state = READY
    credit = 0
    pending = null
    lock = Lock()
```

**Inserting a coin**

Check the machine state, denomination, and credit limit before accepting the coin. Place the accepted coin in escrow while holding the same lock that protects credit. A purchase cannot use that credit before the coin is in escrow.

```text
insertCoin(coin)
    synchronized(this)
        if state != READY
            throw Error("Machine is out of service")
        if coin is unsupported or credit + coin > 1000
            return false
        hardware.acceptCoin(coin)
        credit += coin
        return true
```

**Buying an item**

Say A1 costs ₹4 and the customer inserts ₹10. Before telling the motor to move, find a plan for ₹6. If that fails, the customer can still cancel and get the original ₹10 coin back.

**Core logic**

1. Find the slot and check its stock and the customer's credit.
2. Plan the exact change from the tubes.
3. Save the pending purchase and ask hardware to dispense the item.
4. After confirmed product delivery, reduce stock and ask hardware to pay any change.
5. After confirmed payout, update tube counts, collect escrow, and clear the credit and pending purchase.

**Edge cases**

- Unknown slot, sold out, insufficient credit, or no exact change: reject before dispensing.
- Product definitely did not drop: keep the item count and the customer's credit.
- Product delivery is uncertain: stop the machine before paying change.
- Change fails after the product drops: keep the stock decrement, retain the pending record, and stop. Returning all escrow would give the customer both the product and the full payment.

#### Bad Solution: Pay change before dispensing the product

Suppose we pay ₹6 first and the motor then jams. We cannot return the original ₹10 as well, because ₹6 has already gone out. We now owe a partial refund and need another payout to resolve a sale in which the customer got no product.

#### Great Solution: Plan change first, then dispense the item before paying out

Planning rules out avoidable change failures before anything moves. Paying only after confirmed product delivery leaves the original escrow intact if the product definitely did not drop. A payout can still fail, so we record which part of the sale happened and stop if we cannot finish.

**The purchase flow**

The same lock covers the stock check, change plan, and physical commands. A waiting cancel call can run only after this sale reaches a known result or stops the machine.

```text
buy(slotCode)
    synchronized(this)
        if state != READY
            throw Error("Machine is out of service")
        slot = slots[slotCode]
        if slot == null
            throw Error("Unknown slot")
        if slot.quantity == 0
            return SOLD_OUT
        if credit < slot.price
            return INSUFFICIENT_CREDIT

        change = coins.plan(credit - slot.price)
        if change == null
            return EXACT_CHANGE_UNAVAILABLE

        pending = PendingPurchase(slotCode, change)
        try
            delivery = hardware.dispenseProduct(slotCode)
            if delivery == NONE
                pending = null
                return NOT_DISPENSED

            if delivery == ALL
                slot.quantity -= 1
                pending.productDelivered = true
                if change is empty or hardware.dispenseChange(copy(change)) == ALL
                    coins.recordPaid(change)
                    hardware.collectEscrow()
                    credit = 0
                    pending = null
                    return SUCCESS
        catch error
            state = OUT_OF_SERVICE
            return PENDING_REVIEW

        state = OUT_OF_SERVICE
        return PENDING_REVIEW
```

If change is empty, skip the payout. If we lose the payout reply, the customer might have received some or all of the coins. The saved tube counts then represent the last confirmed counts. The machine cannot safely reuse them until it has checked the hardware.

**Cancelling**

Return the actual coins in escrow. This works even when the change tubes are empty. If the return fails, keep the credit and stop the machine so a second cancellation cannot repeat an uncertain refund.

```text
cancel()
    synchronized(this)
        if state != READY
            throw Error("Machine is out of service")
        if credit == 0
            return true

        try
            if hardware.returnEscrow() == ALL
                credit = 0
                return true
        catch error
            state = OUT_OF_SERVICE
            return false

        state = OUT_OF_SERVICE
        return false
```

### Slot

A slot starts with a positive price within the credit limit and a nonnegative count. Zero means sold out. The machine owns the copy and updates it under the machine lock.

```text
Slot(price, quantity)
    if price <= 0 or price > 1000 or quantity < 0
        throw Error("Invalid slot")
    this.price = price
    this.quantity = quantity
```

### CoinBank

**Loading the tubes**

Copy the initial counts. Each key must be a supported denomination and each count must be nonnegative. A missing denomination has no available coins.

```text
CoinBank(initialCounts)
    for coin, count in initialCounts
        if coin is unsupported or count < 0
            throw Error("Invalid change stock")
    counts = copy(initialCounts)
```

**Planning change**

Use a concrete example. We owe ₹6 and have one ₹5 coin, three ₹2 coins, and no ₹1 coins.

#### Bad Solution: Take the largest coin and never reconsider

Greedy selection takes the ₹5 coin and leaves ₹1 to pay. There is no ₹1 coin, so it rejects the purchase. Three ₹2 coins would work. The machine has ₹11 in total, but that sum does not tell us which amounts are possible.

#### Great Solution: Try different counts and backtrack

First try the ₹5 coin. When ₹1 is impossible, go back and try zero ₹5 coins. Now try three ₹2 coins and find the exact bundle. At each denomination, try counts up to what fits and what is actually in stock. A failed branch never touches the physical inventory.

This fits a small set of denominations. If several branches reach the same denomination with the same remainder, remember the failed search and skip it next time within that plan.

#### Great Solution: Build reachable amounts one denomination at a time

Start with amount zero and an empty bundle. For each denomination, extend the amounts from the previous row with zero through the available count of that coin. Keep one bundle per amount and stop considering totals above the target.

| Coins processed | Reachable amounts up to ₹6 |
| --- | --- |
| None | 0 |
| One ₹5 coin | 0, 5 |
| Three ₹2 coins | 0, 2, 4, 5, 6 |

The ₹6 entry comes from the previous row's zero plus three ₹2 coins. Keeping a separate row matters. If we reuse entries added in the current row, one available ₹2 coin could be counted as ₹2, then ₹4, then ₹6.

A table uses more memory to keep intermediate amounts and bundles. With a small credit limit and just four denominations, it gives us a direct way to see how the count limit applies. We'll use this approach here.

**The change planner**

Each row holds only one bundle per amount. That is enough because future rows use different denominations. Two bundles for the same subtotal have the same options once we move on to the next denomination.

**Core logic**

1. Start with zero reachable using an empty bundle.
2. For each denomination, keep the old amounts and try adding available coins to each old bundle.
3. Return the saved bundle for the requested amount, or null if it is missing.

**Edge cases**

- Zero owed: the empty bundle succeeds.
- A denomination is empty: carry the previous row forward.
- The target is unreachable: return null and leave the counts alone.

```text
plan(amount)
    reachable = {0: {}}

    for coin in [10, 5, 2, 1]
        nextRow = copy(reachable)
        for subtotal, bundle in reachable
            limit = min(counts.get(coin, 0), floor((amount - subtotal) / coin))
            for count from 1 to limit
                total = subtotal + count * coin
                if total not in nextRow
                    candidate = copy(bundle)
                    candidate[coin] = count
                    nextRow[total] = candidate
        reachable = nextRow

    return reachable.get(amount)         // null if unreachable
```

**Recording confirmed payout**

The plan gives a count for each denomination. Subtract those counts only after confirmed payout. The same lock protects this update and the earlier plan.

```text
recordPaid(plan)
    for coin, count in plan
        counts[coin] -= count
```

### Hardware

The adapter defines what counts as delivery. The machine treats a lost reply as uncertain because the motor may have completed the action before the reply was lost.

```text
interface Hardware
    acceptCoin(coin)
    collectEscrow()
    dispenseProduct(slotCode) -> Delivery
    dispenseChange(coins) -> Delivery
    returnEscrow() -> Delivery
```

### PendingPurchase

Save the intent before the product command. Start with `productDelivered` false and set it only after the device confirms the item reached the customer.

```text
PendingPurchase(slotCode, change)
    this.slotCode = slotCode
    this.change = change
    productDelivered = false
```

### MachineState

```text
enum MachineState
    READY
    OUT_OF_SERVICE
```

### Delivery

```text
enum Delivery
    ALL
    NONE
    UNKNOWN
```

### PurchaseResult

```text
enum PurchaseResult
    SUCCESS
    SOLD_OUT
    INSUFFICIENT_CREDIT
    EXACT_CHANGE_UNAVAILABLE
    NOT_DISPENSED
    PENDING_REVIEW
```

### Verification

Walk through one sale using the example above. Start with one unit in A1 at ₹4 and a float of one ₹5 coin and three ₹2 coins.

```text
insertCoin(10)             -> credit = 10
buy("A1")
  plan(6)                  -> {2: 3}, counts still unchanged
  dispenseProduct("A1")    -> ALL, A1 quantity becomes 0
  dispenseChange({2: 3})   -> ALL, 2-coin count becomes 0
  collect escrow and clear credit -> SUCCESS
```

Now change only one condition at a time.

| Change | Expected behavior |
| --- | --- |
| Only two ₹2 coins are available | EXACT_CHANGE_UNAVAILABLE. No product command. Cancel can still return the ₹10 coin. |
| Product returns NONE | NOT_DISPENSED. Keep credit and stock. A later purchase or cancel can proceed. |
| Product outcome is UNKNOWN | PENDING_REVIEW. Do not issue change or accept another customer command. |
| Product returns ALL and change times out | PENDING_REVIEW. Record the item as delivered. Do not attempt a full escrow refund. |
| Escrow return is uncertain | Cancel returns false. Keep credit for review and reject another refund attempt. |
| Two purchase calls race for the last item | One succeeds. The other sees SOLD_OUT. Only one product command is issued. |

The tests also compare the planner against every bundle for several small inventories. That checks both directions: we never return an impossible plan, and we do not miss a valid one. Run the Java tests with JDK 21 or newer.

```sh
cd vending-machine
python3 -m unittest test_vending_machine.py
javac -d /tmp/vending-java VendingMachine.java VendingMachineTest.java
java -cp /tmp/vending-java VendingMachineTest
```

[Python tests](test_vending_machine.py) · [Java tests](VendingMachineTest.java)

### Complete reference implementations

The full implementations follow the same design and include the details needed to run the tests.

Download [vending_machine.py](vending_machine.py) or [VendingMachine.java](VendingMachine.java).

## Follow-ups

### 1. How would you restock and change prices?

Suppose a technician opens A1 just as a customer buys its last snack. If the technician replaces the count while `buy` is waiting for the motor, the software count could describe neither the old stock nor the newly loaded stock.

Add an operator maintenance flow and a MAINTENANCE state. Enter it under the machine lock only when there is no active credit or unresolved operation. Customer commands check the state before doing any work. While the machine is in maintenance, the operator can set A1's verified quantity and price, then return to READY after the door closes and the hardware checks pass.

```text
beginMaintenance()
    synchronized(this)
        if state != READY or credit != 0
            throw Error("Finish the current session or resolve the fault first")
        state = MAINTENANCE
```

Use verified totals for stock updates. If a technician loads twelve snacks, submitting “A1 has twelve” twice leaves twelve. Adding twelve twice would double count. A faulted machine needs reconciliation before this refill flow can reopen it.

### 2. What if inserted coins can also be used as change?

The main design tracks credit and keeps inserted coins separate from the change tubes. Two sessions can both have ₹10 credit but hold different coins. One could contain a ₹10 coin, while the other contains five ₹2 coins. A balance alone cannot tell us what we can recycle.

Replace the credit field with counts by denomination for the escrow coins, and derive credit from those counts. To make change, search the combined available counts only if the hardware can route escrow coins into the payout. The resulting plan must say which coins come from escrow and which come from tubes.

For the ₹4 snack paid with five ₹2 coins, the device can return three ₹2 coins from escrow and retain two. If it cannot access escrow during payout, combining the counts would advertise change the machine cannot actually produce. With recycling, commit the source-specific count updates only after the device confirms what moved. The extra bookkeeping belongs to the cash handling code, while the machine still coordinates the purchase.

### 3. What happens if the machine crashes after the product drops?

A1's motor may finish just before the process dies. The in-memory pending record and stock update disappear. Reloading the initial stock and accepting a new payment would ignore a sale that might already have happened.

Persist an operation ID, slot code, price, credit, and planned change before sending the product command. Record each confirmed device outcome. Pass the same ID to the device so recovery can look up what happened even if the application missed the reply.

| Evidence after restart | Recovery decision |
| --- | --- |
| Device confirms no item delivered and the command cannot run later | Resolve the escrow refund using the original operation record. |
| Item delivered, change not started | Pay the planned change if the hardware can prove there was no prior payout command. |
| Item delivered and change paid | Mark the sale complete without dispensing again. |
| Evidence missing or partial | Stay out of service and reconcile the physical counts and customer amount owed. |

A record saying “payout requested” does not prove payout succeeded or failed. The adapter needs a durable status lookup or safe repetition by operation ID. Apply stock and tube updates at most once per operation, or rebuild them from a reconciled device journal and physical count. A second motor command is unsafe when we cannot tell what the first one did.

### 4. How would you add card payments?

Suppose a customer pays ₹4 by card. There are no inserted coins to refund and no change to plan. Forcing the card payment into the coin credit balance would blur what cancellation actually means.

Keep the stock check and the device delivery decision in VendingMachine. Add a card payment path with a small adapter that can authorize, capture, and release a payment. Authorize the exact item price before dispensing. Capture after confirmed delivery, release after confirmed non-delivery, and keep the operation pending when the outcome is uncertain.

```text
interface CardPayments
    authorize(amount, operationId) -> approved or declined
    capture(operationId)
    release(operationId)
```

A timeout after capture may mean the payment already posted. Recovery checks the original operation ID rather than charging again. CoinBank remains responsible for physical coins. If more payment methods arrive, separate payment behavior behind a common contract only after deciding which operations they actually share.

### 5. How would you sell several items in one purchase?

A customer wants one ₹4 snack and one ₹6 drink. They insert ₹10. The machine can validate both items before starting, but the snack can drop and the drink can jam. A cart introduces a partial sale, even if the initial stock checks were correct.

Keep a list of slot codes and quantities. Under the lock, check every slot and plan the change before moving any product. Record each confirmed delivery separately. If the drink definitely fails, the customer has received ₹4 of goods and is owed ₹6. If the machine only planned change for the full ₹10 cart, it might have no way to pay that ₹6.

One conservative option is to accept a cart only if the machine can make the refund amounts for every possible confirmed delivery prefix. For zero delivered items, return escrow. For one or two delivered items, check the amount owed from tubes before starting, using the chosen dispensing order. That adds planning and may reject otherwise sellable carts. Another option is to accept the cart and stop for review if a partial sale cannot be settled. Pick the policy with the interviewer before writing the cart logic.

## What is expected at each level?

For an early-career interview, show clear slot and credit ownership, a correct purchase and cancel flow, and a change planner that respects available counts.

For a mid-level interview, trace the ₹6 counterexample, explain why change is planned before dispensing, and separate confirmed device failures from uncertainty. Show how one lock protects the inventory plan and the customer session.

For a senior interview, walk through a product delivery followed by an uncertain payout. Explain what evidence recovery needs and which changes would let the machine resume safely. For follow-ups, identify the new requirement before adding state or interfaces.

## Test your understanding

- Why can the tubes contain more than ₹6 and still fail to pay exactly ₹6?
- Why does each dynamic programming row read only from the previous row?
- Why does cancelling work even if the change tubes are empty?
- If the item dropped and change timed out, which facts can the machine safely record?
- Why can buying two items require more than checking stock and totaling prices?
