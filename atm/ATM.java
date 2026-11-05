import java.util.*;

/** All money values are integer paise. */
public final class ATM {
    public enum ATMState {
        IDLE, PIN_REQUIRED, READY, OUT_OF_SERVICE
    }

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

    static final class CashInventory {
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

        void recordDispensed(Map<Long, Integer> plan) {
            plan.forEach((denomination, count) ->
                    notes.put(denomination, notes.get(denomination) - count));
        }
    }

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

    public synchronized long balance() {
        if (state != ATMState.READY) throw new IllegalStateException("Authenticate first");
        return bank.availableBalance(account);
    }

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
}
