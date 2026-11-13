# Vending Machine Low Level Design

## Understanding the problem

A customer puts in coins, picks an item, and takes the item and any change. They can also cancel and get their coins back.

Think about the Cancel button. Before you've paid, pressing it does nothing. After you've put in ₹10, it returns your coins. If the machine asks for a refund and gets no reply from the hardware, pressing Cancel again could pay you twice.

Same button, three different behaviors. We'll use the **State pattern** so each phase of the purchase has its own rules.

Now think about change. You put in ₹10 for a ₹4 snack, so the machine owes you ₹6. If the tubes have a ₹10 coin and a ₹1 coin, that's ₹11 in total, but there's no way to make ₹6. To make change, we need to know which coins are available.

## Requirements

> Design a vending machine that accepts coins, sells products by slot code, and returns change.

### Clarifying questions

> **You:** Can a customer buy several items in one transaction?
>
> **Interviewer:** One item per purchase. A customer can insert coins, attempt a purchase, or cancel. If the purchase completes, the next customer starts with zero credit.

One balance is enough. It tracks how much the current customer has put in. We'll leave carts and item reservations for later.

> **You:** Which coins do we accept? Can the machine use a customer's inserted coins as change?
>
> **Interviewer:** Accept ₹1, ₹2, ₹5, and ₹10 coins, with at most ₹1,000 of credit. Keep inserted coins in escrow until the sale completes. Make change from a separate set of coin tubes.

**Escrow** is the compartment that holds the customer's coins until the sale finishes. If the customer cancels, they get those same coins back. The machine pays change from separate coin tubes. Putting in a coin increases the customer's credit and leaves the tubes as they were.

> **You:** What if the selected slot is empty or the machine cannot give exact change?
>
> **Interviewer:** Leave credit available. The customer can select a different slot, insert more coins, or cancel.

Check stock and plan exact change before asking the dispenser to move anything.

> **You:** What if the product drops and then the change mechanism jams?
>
> **Interviewer:** Handle confirmed delivery and uncertain outcomes separately. If we cannot complete the sale after the product drops, take the machine out of service and keep enough information for review.

If the machine knows the item stayed in the slot, the customer can try again or cancel. If the item came out and the change got stuck, returning the full payment would give away the item.

> **You:** Can commands overlap? Can a technician refill the machine during a purchase?
>
> **Interviewer:** Two commands from the same customer can arrive at nearly the same time. Run them one at a time. Load the stock, prices, and change coins when the machine starts. We'll discuss refills later.

One lock makes the commands wait their turn. The controller sends commands for the current customer only. While the machine holds the lock, the hardware either replies or times out. It never calls back into the machine during that wait.

### Final requirements

1. Serve one customer at a time. Sell one item per purchase from a slot with a configured price and quantity.
2. Accept ₹1, ₹2, ₹5, and ₹10 coins. Store money in whole rupees and limit credit to ₹1,000. Reject unsupported coins and deposits above the limit without changing credit.
3. Before dispensing, check slot stock and credit, then find exact change from the available change tubes. Leave credit available when any of those checks fails.
4. Dispense the item first. Lower the slot count when hardware confirms delivery. Lower the tube counts when hardware confirms the change reached the customer. Then collect the coins from escrow and clear credit.
5. Cancel by returning the inserted coins from escrow. Clear credit after confirmed return.
6. If the device confirms that the product did not drop, keep the stock and credit available. If delivery is uncertain or a payout fails, stop serving customers and preserve the information needed for review.
7. Run customer commands one at a time, including cancellation.

Out of scope:

- Cards, UPI, and notes
- Shopping carts
- Restocking and live price updates
- Durable crash recovery and automatic retries
- Coin sensing and motor control
- Screen rendering

## Core entities and relationships

Think of a purchase as three questions. Can the customer buy this item right now? Which coins make up the change? What actually came out of the machine? The current state, the coin bank, and the hardware adapter each answer one of those questions.

| Type | Responsibility |
| --- | --- |
| VendingMachine | Keep the credit, slots, hardware adapter, and current state. Run one customer command at a time. |
| MachineState | Define how customer commands behave in the current phase. |
| Slot | Hold a price and the number of units in one physical slot. |
| CoinBank | Find a way to make exact change with the coins on hand. Subtract coins once they have been paid out. |
| Hardware | Tell the machine what happened when it tried to deliver an item, pay change, or return the customer's coins. |
| PendingPurchase | Save the slot, the planned change, and whether hardware confirmed the item came out. |

A slot code identifies a physical position. If the same chips are in A1 and B1, buying A1 reduces A1's quantity. We can add product names to the catalog later without changing the purchase flow.

The machine keeps its own copy of each slot and one `CoinBank`. It receives a hardware adapter when it's created. The coin acceptor checks that a coin is genuine and calls `insertCoin`. If the machine rejects the coin, the acceptor gives it back. If it accepts the coin, it moves it into escrow before adding credit.

After a sale, the machine moves the coins from escrow to a collection box. For this exercise, moving coins into escrow or into the collection box always works. Delivering the item, paying change, and returning the coins to the customer can fail.

## Class design

### VendingMachine

The machine needs a slot lookup, one customer's credit, and a way to stop new operations if something goes wrong.

| What the machine needs to do | What it keeps |
| --- | --- |
| Buy from a slot code | Map from code to Slot |
| Accept and refund a customer's payment | Credit backed by the coins in escrow |
| Make exact change | One CoinBank for the tube counts |
| Route commands by phase | Current MachineState object |
| Keep an uncertain sale available for review | PendingPurchase |
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

The caller passes a slot code like A1. The machine looks up the price and stock itself. When `insertCoin` returns `false`, the acceptor gives the coin back. When `cancel` returns `true`, the customer has no credit left. If `cancel` returns `false`, the machine stops and the refund needs review.

### MachineState

Start with `cancel()`. Every state handles that call. `IdleState` returns right away. `HasCreditState` asks the hardware to return the coins in escrow. `OutOfServiceState` rejects the request because the previous refund may already have gone through.

```text
interface MachineState
  + insertCoin(machine: VendingMachine, coin: int) -> boolean
  + buy(machine: VendingMachine, slotCode: string) -> PurchaseResult
  + cancel(machine: VendingMachine) -> boolean
```

#### Good Solution: Keep an enum and branch on it

An enum can name the phases `IDLE`, `HAS_CREDIT`, and `OUT_OF_SERVICE`. With this design, each public method checks the enum and decides what to do. That's manageable with three commands. To add a maintenance phase, we'd check each method to see how it handles the new phase.

#### Great Solution: Give each state its own behavior

In the State pattern, the **context** is the object the caller talks to. Here that's `VendingMachine`. When the caller presses Cancel, the machine passes the call to whichever `MachineState` object it holds. That object decides what to do and whether to switch to another state. The caller keeps using the same machine, which still owns the credit, slots, and hardware.

| Current state | Command or outcome | Next state |
| --- | --- | --- |
| IdleState | Accept the first coin into escrow | HasCreditState |
| IdleState | Reject a coin, attempt to buy, or cancel | IdleState |
| HasCreditState | Insert more coins or fail a purchase check | HasCreditState |
| HasCreditState | Hardware confirms the product did not drop | HasCreditState |
| HasCreditState | Complete the sale or confirm the refund | IdleState |
| HasCreditState | Product delivery is uncertain, change payout fails, or escrow return fails | OutOfServiceState |
| OutOfServiceState | Any customer command | OutOfServiceState |

In `IdleState`, credit is zero. In `HasCreditState`, the customer has put in money and can try to buy something. In `OutOfServiceState`, the machine keeps the details of the problem and blocks customer commands. Three classes take more code. The benefit is that you can open one class and see what every button does in that phase.

The machine holds the lock until hardware replies or times out. If the customer presses Cancel while an item is dropping, Cancel waits and then uses the state the purchase ended in. If hardware reported the result later and the machine could handle new commands while waiting, a `DispensingState` could define what those commands do.

### Slot

```text
Slot
  price: int
  quantity: int
```

A slot holds the price and how many items are left. Once hardware confirms the item came out, subtract one. The item is already gone even if the machine still owes change.

### CoinBank

```text
CoinBank
  - counts: Map<int, int>                 // denomination -> available count
  + plan(amount: int) -> Map<int, int> or null
  + recordPaid(plan: Map<int, int>)
```

`plan` gives us a coin bundle such as `{2: 3}`, which means three ₹2 coins. An empty bundle means the customer paid the exact price. `null` means the machine owes change and can't make it. Once hardware confirms the coins came out, `recordPaid` subtracts them from the tube counts.

The customer goes through `VendingMachine`. It keeps the lock from the moment we plan the change until the coins are paid, so another command can't use those same coins in between.

### Hardware

```text
interface Hardware
  + acceptCoin(coin: int)
  + collectEscrow()
  + dispenseProduct(slotCode: string) -> Delivery
  + dispenseChange(coins: Map<int, int>) -> Delivery
  + returnEscrow() -> Delivery
```

For the product, hardware checks whether one item came out. For coins, `ALL` means the customer received every coin we asked for. `NONE` means they got none. `UNKNOWN` covers cases where only some coins came out or where we can't tell what happened. If the hardware times out, we also treat the result as uncertain.

`returnEscrow` returns the customer's original coins from a different compartment. It does not draw from the change tubes.

### PendingPurchase

```text
PendingPurchase
  slotCode: string
  change: Map<int, int>
  productDelivered: boolean
```

Save this record before asking hardware to drop the item. Once the item comes out, set `productDelivered` to `true` before trying to pay change. If the sale stops there, we know the customer got the item and the change still needs checking. If the flag is still `false` on a sale that needs review, the item may or may not have come out, and we haven't tried to pay change.

If a purchase needs review, the machine keeps the credit and the record in memory. If a cancellation fails, there's no purchase record to keep. The remaining credit tells us how much was in escrow before the refund attempt. The machine stays out of service until the problem can be resolved.

### PurchaseResult

| Result | Meaning |
| --- | --- |
| SUCCESS | Product and any required change were delivered. |
| SOLD_OUT | The slot is empty. |
| INSUFFICIENT_CREDIT | The customer needs to insert more money or choose a cheaper item. |
| EXACT_CHANGE_UNAVAILABLE | The change tubes cannot make the amount owed. |
| NOT_DISPENSED | Hardware confirmed that the product did not reach the customer. Credit remains available. |
| PENDING_REVIEW | The machine stopped because delivery or payout needs review. |

A code that doesn't exist raises an error. An existing slot with zero items returns `SOLD_OUT`.

## Implementation

Start with the three commands a customer can trigger. Follow those calls into the state classes. `HasCreditState.buy` handles the sale and asks `CoinBank` to work out the change.

### VendingMachine

**Creating the machine**

Copy the configured slots and load the change tubes. Start in `IdleState` with zero credit and no pending purchase.

```text
VendingMachine(slots, change, hardware)
    this.slots = {}
    for code, slot in slots
        if code == null or code is empty or slot == null
            throw Error("Invalid slot")
        this.slots[code] = Slot(slot.price, slot.quantity)
    coins = CoinBank(change)
    this.hardware = hardware
    state = IdleState()
    credit = 0
    pending = null
    lock = Lock()
```

**Delegating customer commands**

Take the lock before looking up the current state. Say a Cancel request arrives while a purchase is paying change. If the payout fails, Cancel will run after the switch to `OutOfServiceState` and be rejected.

```text
insertCoin(coin)
    synchronized(this)
        return state.insertCoin(this, coin)

buy(slotCode)
    synchronized(this)
        return state.buy(this, slotCode)

cancel()
    synchronized(this)
        return state.cancel(this)
```

**Accepting a coin**

Both states that take coins call this method. Check the coin value and the credit limit first. Then move the coin to escrow and add its value to credit. The state that called this method decides what happens next.

```text
acceptCoin(coin)
    if coin is unsupported or credit + coin > 1000
        return false
    hardware.acceptCoin(coin)
    credit += coin
    return true
```

Both states that let the customer choose an item look up the slot here. If the code is missing, raise the same error in either state.

```text
slotFor(slotCode)
    slot = slots.get(slotCode)
    if slot == null
        throw Error("Unknown slot")
    return slot
```

### MachineState

The interface has the same three operations as the machine. Each one takes the machine as an argument so the state can read its credit and inventory or switch to another state. The caller only talks to `VendingMachine`.

```text
interface MachineState
    insertCoin(machine, coin) -> boolean
    buy(machine, slotCode) -> PurchaseResult
    cancel(machine) -> boolean
```

### IdleState

**Inserting the first coin**

Stay idle if the coin is rejected. After the first coin reaches escrow and credit is recorded, move to `HasCreditState`.

```text
insertCoin(machine, coin)
    if machine.acceptCoin(coin) == false
        return false
    machine.state = HasCreditState()
    return true
```

**Buying without credit**

Look up the slot first. If it's empty, tell the customer it's sold out. If there's an item in it, tell them they need to pay. In either case, the dispenser stays still.

```text
buy(machine, slotCode)
    slot = machine.slotFor(slotCode)
    if slot.quantity == 0
        return SOLD_OUT
    return INSUFFICIENT_CREDIT
```

**Cancelling without credit**

No coins are in escrow, so cancellation succeeds without a refund command.

```text
cancel(machine)
    return true
```

### HasCreditState

**Adding credit**

Use the same coin acceptance rule. The customer already has credit, so accepting or rejecting another coin leaves the state in place.

```text
insertCoin(machine, coin)
    return machine.acceptCoin(coin)
```

**Buying an item**

Back to the ₹4 snack in A1. The customer put in ₹10, so we need to find ₹6 in change before running the motor. If we can't make ₹6, stay in `HasCreditState`. The customer can pick another item or cancel.

**Core logic**

1. Find the slot and check its stock and the customer's credit.
2. Plan exact change from the tubes.
3. Save the purchase details before asking hardware to drop the item.
4. Once hardware confirms the item came out, subtract one from the slot and pay any change.
5. Once the change is paid, update the tube counts. Move the customer's coins from escrow to the collection box, clear credit, and return to `IdleState`.

**Edge cases**

- If a slot, stock, credit, or change check fails, stop before running the dispenser.
- If hardware confirms the item stayed in the slot, keep the stock and credit as they were. The customer can try again or cancel.
- If we can't tell whether the item came out, switch to `OutOfServiceState` before paying change.
- If the item came out but paying change failed, the lower stock count is still correct. Keep the purchase record and switch to `OutOfServiceState`.

#### Bad Solution: Pay change before dispensing the product

Suppose we pay ₹6 first and the motor then jams. Returning the original ₹10 would give the customer ₹16 in total. We would owe a separate ₹4 payout to resolve a sale in which the customer got no product.

#### Great Solution: Plan change first, then dispense the item before paying out

Planning checks the tubes before anything moves. Paying change after the item drops leaves the original escrow available if the product definitely did not drop. If the product drops but change fails, the pending record shows that the customer already received the item.

```text
buy(machine, slotCode)
    slot = machine.slotFor(slotCode)
    if slot.quantity == 0
        return SOLD_OUT
    if machine.credit < slot.price
        return INSUFFICIENT_CREDIT

    change = machine.coins.plan(machine.credit - slot.price)
    if change == null
        return EXACT_CHANGE_UNAVAILABLE

    machine.pending = PendingPurchase(slotCode, change)
    try
        delivery = machine.hardware.dispenseProduct(slotCode)
        if delivery == NONE
            machine.pending = null
            return NOT_DISPENSED

        if delivery == ALL
            slot.quantity -= 1
            machine.pending.productDelivered = true
            if change is empty or machine.hardware.dispenseChange(copy(change)) == ALL
                machine.coins.recordPaid(change)
                machine.hardware.collectEscrow()
                machine.credit = 0
                machine.pending = null
                machine.state = IdleState()
                return SUCCESS
    catch error
        machine.state = OutOfServiceState()
        return PENDING_REVIEW

    machine.state = OutOfServiceState()
    return PENDING_REVIEW
```

If the customer paid exactly, skip the change payout. If the payout reply never comes back, some or all of the coins may already be gone. The software still has the old tube counts. Check what is physically in the tubes before reopening the machine.

**Cancelling with credit**

Give the customer back the coins they put in. This works even with empty change tubes because the coins are still in escrow. Once hardware confirms the refund, clear the credit and go back to `IdleState`. If the refund fails or the reply is missing, move to `OutOfServiceState` to block another attempt.

```text
cancel(machine)
    try
        if machine.hardware.returnEscrow() == ALL
            machine.credit = 0
            machine.state = IdleState()
            return true
    catch error
        machine.state = OutOfServiceState()
        return false

    machine.state = OutOfServiceState()
    return false
```

### OutOfServiceState

Each customer command fails before touching hardware or changing any data. An operator needs to resolve the fault before reopening the machine.

```text
insertCoin(machine, coin)
    throw Error("Machine is out of service")

buy(machine, slotCode)
    throw Error("Machine is out of service")

cancel(machine)
    throw Error("Machine is out of service")
```

### Slot

A slot price must be between ₹1 and ₹1,000. Its item count starts at zero or more. Zero means sold out. The machine keeps its own copy and holds the lock when updating it.

```text
Slot(price, quantity)
    if price <= 0 or price > 1000 or quantity < 0
        throw Error("Invalid slot")
    this.price = price
    this.quantity = quantity
```

### CoinBank

**Loading the tubes**

Copy the starting count for each coin value. Accept only supported coin values and counts of zero or more. If a coin value is missing from the map, treat it as zero.

```text
CoinBank(initialCounts)
    for coin, count in initialCounts
        if coin is unsupported or count < 0
            throw Error("Invalid change stock")
    counts = copy(initialCounts)
```

**Planning change**

We owe ₹6. The tubes hold one ₹5 coin and three ₹2 coins. How do we find the right bundle?

#### Bad Solution: Take the largest coin and never reconsider

A greedy rule takes the largest coin that fits. It takes ₹5 first and gets stuck because there's no ₹1 coin. The machine would reject the sale even though three ₹2 coins would work. The total of ₹11 tells us how much cash we have. We still need to check what we can make with it.

#### Great Solution: Try different counts and backtrack

Try one ₹5 coin. When you can't make the remaining ₹1, undo that choice and try using zero ₹5 coins. Now three ₹2 coins make exactly ₹6. This is **backtracking**. For each coin value, try only as many coins as the tube has and as many as fit the amount still owed. Every try happens in memory. The machine only pays once it has a plan.

This works well with a few coin values. Different choices can leave you at the same coin value with the same amount still owed. If that search already failed, remember the pair so you can skip it for the rest of this plan.

#### Great Solution: Build reachable amounts one denomination at a time

Use **dynamic programming** to build up the amounts we can pay. Start with ₹0 and no coins. Add one coin value at a time. For every amount in the previous row, try adding zero, one, or more of the new coin, up to the number we have. Save one way to make each total and skip anything above ₹6.

| Coins processed | Reachable amounts up to ₹6 |
| --- | --- |
| None | 0 |
| One ₹5 coin | 0, 5 |
| Three ₹2 coins | 0, 2, 4, 5, 6 |

To get ₹6, take ₹0 from the previous row and add three ₹2 coins. Read from the previous row so you don't count a coin twice. For example, with just one ₹2 coin, reading from the row you're writing could turn ₹0 into ₹2, then reuse the same coin to reach ₹4 and ₹6.

The table needs memory for the amounts and bundles we find along the way. Here the credit limit is small and we have only four coin values. We'll use the table because it makes it easy to see how the available coin counts limit each row.

**The change planner**

If two bundles make the same subtotal, keep either one. Every later row adds a new coin value, so it has the same choices whichever bundle we saved.

**Core logic**

1. Record that we can make ₹0 with no coins.
2. For each coin value, copy the old row. Add new totals by combining coins of that value with bundles from the old row.
3. Look up the amount we owe. Return its bundle, or `null` if there's no entry.

**Edge cases**

- If the customer paid exactly, return an empty bundle.
- If a tube is empty, copy the previous row as it is.
- If no bundle makes the amount, return `null` and leave the tube counts alone.

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

The plan says how many coins to take from each tube. Subtract them after hardware confirms they came out. The machine still holds the lock it took before planning.

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

Save the slot and change plan before telling the motor to move. Start with `productDelivered` set to `false`. Set it to `true` once hardware confirms the customer got the item.

```text
PendingPurchase(slotCode, change)
    this.slotCode = slotCode
    this.change = change
    productDelivered = false
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

Put one ₹4 snack in A1. Load one ₹5 coin and three ₹2 coins into the change tubes. Now follow a customer who puts in ₹10.

```text
IdleState.insertCoin(10)   -> credit = 10, switch to HasCreditState
HasCreditState.buy("A1")
  plan(6)                  -> {2: 3}, counts still unchanged
  dispenseProduct("A1")    -> ALL, A1 quantity becomes 0
  dispenseChange({2: 3})   -> ALL, 2-coin count becomes 0
  collect escrow and clear credit -> switch to IdleState, return SUCCESS
```

Now change only one condition at a time.

| Change | Expected behavior |
| --- | --- |
| Buy from a stocked slot before inserting a coin | IdleState returns INSUFFICIENT_CREDIT. Hardware is untouched. |
| Only two ₹2 coins are available | EXACT_CHANGE_UNAVAILABLE. Stay in HasCreditState. Cancel can still return the ₹10 coin. |
| Product returns NONE | NOT_DISPENSED. Keep credit and stock. A later purchase or cancel can proceed. |
| Product outcome is UNKNOWN | PENDING_REVIEW. Move to OutOfServiceState before paying change. |
| Product returns ALL and change times out | PENDING_REVIEW. Record the item as delivered. Do not attempt a full escrow refund. |
| Escrow return is uncertain | Cancel returns false. Keep credit for review and reject another refund attempt. |
| Two purchase calls race for the last item | One succeeds. The other sees SOLD_OUT. Only one product command is issued. |

The tests check that after a sale or refund, cancelling again issues no hardware command. They also compare the change planner against every possible bundle for several small inventories. Run the Java tests with JDK 21 or newer.

```sh
cd vending-machine
python3 -m unittest test_vending_machine.py
javac -d /tmp/vending-java VendingMachine.java VendingMachineTest.java
java -cp /tmp/vending-java VendingMachineTest
```

[Python tests](test_vending_machine.py) · [Java tests](VendingMachineTest.java)

### Complete reference implementations

Both versions implement the state classes and change planner above. Use the test commands to run the same purchase and refund scenarios in either language.

Download [vending_machine.py](vending_machine.py) or [VendingMachine.java](VendingMachine.java).

## Follow-ups

### 1. How would you restock and change prices?

Imagine a technician refills A1 while its motor is still dropping the last snack. If they enter a new count before the purchase subtracts one, the number in software can disagree with what's in the slot.

Add a `MaintenanceState` that rejects all three customer commands before they reach the hardware. The operator takes the machine lock and can enter maintenance only from `IdleState`. In maintenance, they can count the items in A1 and enter that count and its price. Once the door is closed and the hardware checks pass, go back to `IdleState`. The customer commands still go through the same `MachineState` interface.

Enter the count you can verify. Sending “A1 has twelve” twice leaves twelve in the system. Sending “add twelve” twice records twenty-four. If the machine stopped after a failed sale, check what happened to the item and money before putting it back into service.

### 2. What if inserted coins can also be used as change?

Right now, we keep the customer's coins in escrow and pay change from the tubes. Two customers can both have ₹10 of credit. One may have put in a ₹10 coin and the other five ₹2 coins. To reuse their coins, we need to know which coins are in escrow.

Track how many coins of each value are in escrow. Add up their values to get the credit. If the hardware can pay from both escrow and the tubes, plan change using both sets of coins. The plan has to say how many coins to take from each place.

For a ₹4 snack paid for with five ₹2 coins, the machine could return three of those coins and keep two. If the device can't pay from escrow, count only the coins in the tubes when planning change. When it can use both, update the count for each place after the device confirms which coins moved. The cash handling code tracks the counts. The machine still runs the sale.

### 3. What happens if the machine crashes after the product drops?

The motor may drop the item just before the program crashes. The purchase record and any stock update held in memory disappear. If the machine reloads its starting stock and takes another payment, it could sell an item that's already gone.

Before asking for the item, save an operation ID, the slot code, the price, the credit, and the change plan to storage that survives a restart. Record each result the device confirms. Send the same ID to the device so the machine can ask what happened after it restarts, even if it missed the first reply.

| Evidence after restart | Recovery decision |
| --- | --- |
| Device confirms no item delivered and the command cannot run later | Use the original record to work out and return what the customer paid. |
| Item delivered, change not started | Pay the planned change if the hardware can prove there was no prior payout command. |
| Item delivered and change paid | Mark the sale complete without dispensing again. |
| Evidence missing or partial | Stay out of service. Check the actual stock and coin counts, and work out what the customer is still owed. |

A record saying “payout requested” tells us that a command was sent. The device needs to remember the result across restarts, or let the machine resend the same operation ID without paying again. Apply each stock or tube update once. Another option is to rebuild the counts from the device's records after checking them against what's physically in the machine.

### 4. How would you add card payments?

Suppose a customer pays ₹4 by card. The machine has no coins to return and owes no change. Cancel now means releasing a card hold instead of opening the escrow compartment.

Keep the slot check and the decision about item delivery in the machine. Give card payments an adapter with three operations. Authorize to put a hold on the exact price before dropping the item. Capture to charge the card once hardware confirms the item came out. Release the hold if hardware confirms the item stayed in the slot. If we can't tell what happened, keep the operation open for review.

```text
interface CardPayments
    authorize(amount, operationId) -> approved or declined
    capture(operationId)
    release(operationId)
```

If capture times out, the card may already have been charged. Look up the original operation ID before doing anything else. `CoinBank` still handles physical coins. If we add more ways to pay, first check which operations they share. Those shared operations can form a common payment interface.

### 5. How would you sell several items in one purchase?

A customer pays ₹10 for a ₹4 snack and a ₹6 drink. Both are in stock. The snack drops, then the drink gets stuck. Now the machine has finished only part of the sale.

Store the slot codes and quantities in the cart. With the lock held, check stock and plan change before running any motor. Record each item as it comes out. If the machine confirms the drink stayed in the slot, the customer got ₹4 of goods and is owed ₹6. The change plan for the full ₹10 sale was empty, so it tells us nothing about whether we can pay that ₹6.

One option is to pick the order in which items will drop, then check what we'd owe if the machine stopped after each item. If nothing comes out, return the escrow. If just the snack comes out, the tubes need to make ₹6. If both come out, the customer paid exactly. This takes more planning and can reject a cart even when all its items could have come out. Another option is to accept the cart and stop for review if we can't settle a partial sale. Agree on the rule before writing the cart logic.

## What is expected at each level?

For an early-career interview, show what Cancel does in each state. Then trace how the first coin goes into escrow and how a completed sale or refund brings the machine back to idle.

For a mid-level interview, show why taking the ₹5 coin first fails when we owe ₹6. Explain why we plan change before the item drops, why a timeout is different from a confirmed failure, and what another command can do while the lock is held.

For a senior interview, walk through an item dropping just before the change payout times out. Explain which records you would check before reopening the machine. In follow-ups, explain what the new requirement changes before adding a state or interface.

## Test your understanding

- Where does the first coin change the current state? Why does a second coin leave the state in place?
- Which object handles `cancel()` after a refund times out? What would change if the machine could take new commands before hardware replied?
- Why can the tubes contain more than ₹6 and still fail to pay exactly ₹6?
- Why does the change planner read from the previous row of the dynamic programming table?
- Why does cancelling work even if the change tubes are empty?
- If the item dropped and change timed out, which facts can the machine safely record?
- Why can buying two items require more than checking stock and totaling prices?
