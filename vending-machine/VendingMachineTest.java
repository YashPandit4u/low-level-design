import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;

public final class VendingMachineTest {
    private static final class Device implements VendingMachine.Hardware {
        final List<String> calls = new ArrayList<>();
        final List<Integer> escrow = new ArrayList<>();
        VendingMachine.Delivery product = VendingMachine.Delivery.ALL;
        VendingMachine.Delivery change = VendingMachine.Delivery.ALL;
        VendingMachine.Delivery refund = VendingMachine.Delivery.ALL;
        boolean changeTimeout;

        public void acceptCoin(int coin) {
            escrow.add(coin);
        }

        public void collectEscrow() {
            calls.add("collect " + escrow);
            escrow.clear();
        }

        public VendingMachine.Delivery dispenseProduct(String slotCode) {
            calls.add("product " + slotCode);
            return product;
        }

        public VendingMachine.Delivery dispenseChange(Map<Integer, Integer> coins) {
            calls.add("change " + coins);
            if (changeTimeout) throw new IllegalStateException("Lost reply");
            return change;
        }

        public VendingMachine.Delivery returnEscrow() {
            calls.add("refund " + escrow);
            if (refund == VendingMachine.Delivery.ALL) escrow.clear();
            return refund;
        }
    }

    private static VendingMachine machine(Device device, int quantity, Map<Integer, Integer> stock) {
        return new VendingMachine(Map.of("A1", new VendingMachine.Slot(4, quantity)), stock, device);
    }

    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("Vending machine check failed");
    }

    private static void blocked(Runnable action) {
        try {
            action.run();
            throw new AssertionError("Expected machine to reject the operation");
        } catch (IllegalStateException expected) {
            check(expected.getMessage().equals("Machine is out of service"));
        }
    }

    private static void successAndRefundReturnToIdle() {
        var device = new Device();
        var vm = machine(device, 2, Map.of());
        check(vm.cancel());
        check(vm.buy("A1") == VendingMachine.PurchaseResult.INSUFFICIENT_CREDIT);
        check(device.calls.isEmpty());

        check(vm.insertCoin(2));
        check(vm.cancel());
        check(vm.cancel());
        check(device.calls.equals(List.of("refund [2]")));

        check(vm.insertCoin(2));
        check(vm.insertCoin(2));
        check(vm.buy("A1") == VendingMachine.PurchaseResult.SUCCESS);
        check(vm.buy("A1") == VendingMachine.PurchaseResult.INSUFFICIENT_CREDIT);
        check(vm.cancel());
        check(device.calls.equals(List.of("refund [2]", "product A1", "collect [2, 2]")));
    }

    private static void changeAndCancellation() {
        var device = new Device();
        var vm = machine(device, 2, Map.of(5, 1, 2, 3));
        check(vm.insertCoin(10));
        check(vm.buy("A1") == VendingMachine.PurchaseResult.SUCCESS);
        check(device.calls.equals(List.of("product A1", "change {2=3}", "collect [10]")));
        check(vm.insertCoin(10));
        check(vm.buy("A1") == VendingMachine.PurchaseResult.EXACT_CHANGE_UNAVAILABLE);
        check(vm.cancel());
        check(device.calls.get(3).equals("refund [10]"));
        check(vm.cancel() && device.calls.size() == 4);
    }

    private static void prechecksAndExactPayment() {
        var device = new Device();
        var vm = machine(device, 1, Map.of());
        check(!vm.insertCoin(3));
        check(vm.insertCoin(2));
        try {
            vm.buy("missing");
            throw new AssertionError("Expected an unknown slot error");
        } catch (IllegalArgumentException expected) {
            check(device.calls.isEmpty());
        }
        check(vm.buy("A1") == VendingMachine.PurchaseResult.INSUFFICIENT_CREDIT);
        check(vm.insertCoin(2));
        check(vm.buy("A1") == VendingMachine.PurchaseResult.SUCCESS);
        check(vm.buy("A1") == VendingMachine.PurchaseResult.SOLD_OUT);
        check(device.calls.equals(List.of("product A1", "collect [2, 2]")));

        for (int i = 0; i < 100; i++) check(vm.insertCoin(10));
        check(!vm.insertCoin(1));
        check(device.escrow.size() == 100);
    }

    private static void deviceFailures() {
        var device = new Device();
        var vm = machine(device, 1, Map.of(2, 3));
        vm.insertCoin(10);
        device.product = VendingMachine.Delivery.NONE;
        check(vm.buy("A1") == VendingMachine.PurchaseResult.NOT_DISPENSED);
        check(device.calls.equals(List.of("product A1")));
        check(device.escrow.equals(List.of(10)));
        device.product = VendingMachine.Delivery.ALL;
        check(vm.buy("A1") == VendingMachine.PurchaseResult.SUCCESS);

        var uncertainDevice = new Device();
        var uncertain = machine(uncertainDevice, 1, Map.of(2, 3));
        uncertain.insertCoin(10);
        uncertainDevice.product = VendingMachine.Delivery.UNKNOWN;
        check(uncertain.buy("A1") == VendingMachine.PurchaseResult.PENDING_REVIEW);
        blocked(uncertain::cancel);
        check(uncertainDevice.calls.equals(List.of("product A1")));

        var changeDevice = new Device();
        var payout = machine(changeDevice, 1, Map.of(2, 3));
        payout.insertCoin(10);
        changeDevice.changeTimeout = true;
        check(payout.buy("A1") == VendingMachine.PurchaseResult.PENDING_REVIEW);
        blocked(payout::cancel);
        blocked(() -> payout.buy("A1"));
        blocked(() -> payout.insertCoin(1));
        check(changeDevice.calls.equals(List.of("product A1", "change {2=3}")));
        check(changeDevice.escrow.equals(List.of(10)));

        var refundDevice = new Device();
        var refund = machine(refundDevice, 1, Map.of());
        refund.insertCoin(5);
        refundDevice.refund = VendingMachine.Delivery.UNKNOWN;
        check(!refund.cancel());
        blocked(refund::cancel);
        check(refundDevice.calls.equals(List.of("refund [5]")));
    }

    private static void lastItemRace() throws Exception {
        var device = new Device();
        var vm = machine(device, 1, Map.of());
        vm.insertCoin(2);
        vm.insertCoin(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> vm.buy("A1"));
            var b = pool.submit(() -> vm.buy("A1"));
            var outcomes = new HashSet<>(List.of(a.get(), b.get()));
            check(outcomes.equals(java.util.Set.of(VendingMachine.PurchaseResult.SUCCESS,
                    VendingMachine.PurchaseResult.SOLD_OUT)));
        }
        check(device.calls.equals(List.of("product A1", "collect [2, 2]")));
    }

    private static void exhaustiveChange() {
        for (int ones = 0; ones <= 2; ones++) {
            for (int twos = 0; twos <= 2; twos++) {
                for (int fives = 0; fives <= 2; fives++) {
                    for (int tens = 0; tens <= 2; tens++) {
                        var stock = Map.of(1, ones, 2, twos, 5, fives, 10, tens);
                        var bank = new VendingMachine.CoinBank(stock);
                        var possible = new HashSet<Integer>();
                        for (int a = 0; a <= ones; a++) {
                            for (int b = 0; b <= twos; b++) {
                                for (int c = 0; c <= fives; c++) {
                                    for (int d = 0; d <= tens; d++) {
                                        possible.add(a + 2 * b + 5 * c + 10 * d);
                                    }
                                }
                            }
                        }
                        for (int amount = 0; amount <= 20; amount++) {
                            var plan = bank.plan(amount);
                            check((plan != null) == possible.contains(amount));
                            if (plan == null) continue;
                            int total = 0;
                            for (var coin : plan.entrySet()) {
                                check(coin.getValue() > 0 && coin.getValue() <= stock.get(coin.getKey()));
                                total += coin.getKey() * coin.getValue();
                            }
                            check(total == amount);
                        }
                    }
                }
            }
        }
    }

    public static void main(String[] args) throws Exception {
        successAndRefundReturnToIdle();
        changeAndCancellation();
        prechecksAndExactPayment();
        deviceFailures();
        lastItemRace();
        exhaustiveChange();
        System.out.println("Vending Machine Java scenarios passed, including 1,701 change cases.");
    }
}
