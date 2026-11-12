import java.util.HashMap;
import java.util.Map;

/** Single-session vending machine. All amounts are whole rupees. */
public final class VendingMachine {
    private static final int MAX_CREDIT = 1000;

    private enum MachineState { READY, OUT_OF_SERVICE }

    public enum Delivery { ALL, NONE, UNKNOWN }

    public enum PurchaseResult {
        SUCCESS, SOLD_OUT, INSUFFICIENT_CREDIT, EXACT_CHANGE_UNAVAILABLE,
        NOT_DISPENSED, PENDING_REVIEW
    }

    public static final class Slot {
        private final int price;
        private int quantity;

        public Slot(int price, int quantity) {
            if (price <= 0 || price > MAX_CREDIT || quantity < 0) {
                throw new IllegalArgumentException("Invalid slot");
            }
            this.price = price;
            this.quantity = quantity;
        }
    }

    private static final class PendingPurchase {
        final String slotCode;
        final Map<Integer, Integer> change;
        boolean productDelivered;

        PendingPurchase(String slotCode, Map<Integer, Integer> change) {
            this.slotCode = slotCode;
            this.change = change;
        }
    }

    public interface Hardware {
        void acceptCoin(int coin);
        void collectEscrow();
        Delivery dispenseProduct(String slotCode);
        Delivery dispenseChange(Map<Integer, Integer> coins);
        Delivery returnEscrow();
    }

    static final class CoinBank {
        private static final int[] DENOMINATIONS = {10, 5, 2, 1};
        private final Map<Integer, Integer> counts;

        CoinBank(Map<Integer, Integer> counts) {
            for (var entry : counts.entrySet()) {
                if (entry.getKey() == null || !accepts(entry.getKey())
                        || entry.getValue() == null || entry.getValue() < 0) {
                    throw new IllegalArgumentException("Invalid change stock");
                }
            }
            this.counts = new HashMap<>(counts);
        }

        static boolean accepts(int coin) {
            for (int denomination : DENOMINATIONS) {
                if (coin == denomination) return true;
            }
            return false;
        }

        Map<Integer, Integer> plan(int amount) {
            Map<Integer, Map<Integer, Integer>> reachable = Map.of(0, Map.of());
            for (int coin : DENOMINATIONS) {
                var nextRow = new HashMap<>(reachable);
                for (var entry : reachable.entrySet()) {
                    int subtotal = entry.getKey();
                    int limit = Math.min(counts.getOrDefault(coin, 0), (amount - subtotal) / coin);
                    for (int count = 1; count <= limit; count++) {
                        int total = subtotal + count * coin;
                        if (!nextRow.containsKey(total)) {
                            var bundle = new HashMap<>(entry.getValue());
                            bundle.put(coin, count);
                            nextRow.put(total, bundle);
                        }
                    }
                }
                reachable = nextRow;
            }
            return reachable.get(amount);
        }

        void recordPaid(Map<Integer, Integer> plan) {
            for (var entry : plan.entrySet()) {
                int coin = entry.getKey();
                counts.put(coin, counts.get(coin) - entry.getValue());
            }
        }
    }

    private final Map<String, Slot> slots = new HashMap<>();
    private final CoinBank coins;
    private final Hardware hardware;
    private MachineState state = MachineState.READY;
    private int credit;
    private PendingPurchase pending;

    public VendingMachine(Map<String, Slot> slots, Map<Integer, Integer> change, Hardware hardware) {
        for (var entry : slots.entrySet()) {
            String code = entry.getKey();
            Slot slot = entry.getValue();
            if (code == null || code.isEmpty() || slot == null) {
                throw new IllegalArgumentException("Invalid slot");
            }
            this.slots.put(code, new Slot(slot.price, slot.quantity));
        }
        this.coins = new CoinBank(change);
        this.hardware = hardware;
    }

    public synchronized boolean insertCoin(int coin) {
        if (state != MachineState.READY) throw new IllegalStateException("Machine is out of service");
        if (!CoinBank.accepts(coin) || credit + coin > MAX_CREDIT) return false;
        hardware.acceptCoin(coin);
        credit += coin;
        return true;
    }

    public synchronized PurchaseResult buy(String slotCode) {
        if (state != MachineState.READY) throw new IllegalStateException("Machine is out of service");
        Slot slot = slots.get(slotCode);
        if (slot == null) throw new IllegalArgumentException("Unknown slot");
        if (slot.quantity == 0) return PurchaseResult.SOLD_OUT;
        if (credit < slot.price) return PurchaseResult.INSUFFICIENT_CREDIT;

        Map<Integer, Integer> change = coins.plan(credit - slot.price);
        if (change == null) return PurchaseResult.EXACT_CHANGE_UNAVAILABLE;

        pending = new PendingPurchase(slotCode, change);
        try {
            Delivery delivery = hardware.dispenseProduct(slotCode);
            if (delivery == Delivery.NONE) {
                pending = null;
                return PurchaseResult.NOT_DISPENSED;
            }
            if (delivery == Delivery.ALL) {
                slot.quantity--;
                pending.productDelivered = true;
                if (change.isEmpty() || hardware.dispenseChange(Map.copyOf(change)) == Delivery.ALL) {
                    coins.recordPaid(change);
                    hardware.collectEscrow();
                    credit = 0;
                    pending = null;
                    return PurchaseResult.SUCCESS;
                }
            }
        } catch (RuntimeException failure) {
            state = MachineState.OUT_OF_SERVICE;
            return PurchaseResult.PENDING_REVIEW;
        }
        state = MachineState.OUT_OF_SERVICE;
        return PurchaseResult.PENDING_REVIEW;
    }

    public synchronized boolean cancel() {
        if (state != MachineState.READY) throw new IllegalStateException("Machine is out of service");
        if (credit == 0) return true;
        try {
            if (hardware.returnEscrow() == Delivery.ALL) {
                credit = 0;
                return true;
            }
        } catch (RuntimeException failure) {
            state = MachineState.OUT_OF_SERVICE;
            return false;
        }
        state = MachineState.OUT_OF_SERVICE;
        return false;
    }
}
