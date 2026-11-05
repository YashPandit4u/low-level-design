import java.util.*;
import java.util.concurrent.*;

public final class ATMTest {
    static class Bank implements ATM.BankGateway {
        long funds = 100000;
        Map<String, Long> holds = new HashMap<>();
        String fail = "";
        public String authenticate(String card, String pin) {
            if (fail.equals("authenticate")) throw new RuntimeException();
            return card.equals("card-A") && pin.equals("1234") ? "account-A" : null;
        }
        public long availableBalance(String account) {
            if (fail.equals("balance")) throw new RuntimeException();
            return funds - holds.values().stream().mapToLong(Long::longValue).sum();
        }
        public boolean hold(String account, long amount, String id) {
            if (amount > availableBalance(account)) return false;
            holds.put(id, amount);
            if (fail.equals("hold")) throw new RuntimeException();
            return true;
        }
        public void capture(String id) {
            if (fail.equals("capture")) throw new RuntimeException();
            funds -= holds.remove(id);
            if (fail.equals("capture_after")) throw new RuntimeException();
        }
        public void release(String id) {
            if (fail.equals("release")) throw new RuntimeException();
            holds.remove(id);
            if (fail.equals("release_after")) throw new RuntimeException();
        }
    }
    static class Device implements ATM.Hardware {
        String outcome = "ALL";
        int calls, ejections;
        boolean ejectFails;
        public String dispense(Map<Long, Integer> notes) {
            calls++;
            if (outcome.equals("TIMEOUT")) throw new RuntimeException();
            return outcome;
        }
        public void ejectCard() {
            ejections++;
            if (ejectFails) throw new RuntimeException();
        }
    }
    static void check(boolean condition) {
        if (!condition) throw new AssertionError();
    }
    static ATM ready(Bank bank, Device device) {
        ATM atm = new ATM(bank, device, Map.of(50000L, 1, 20000L, 3), 100000);
        atm.insertCard("card-A");
        check(atm.enterPin("1234"));
        return atm;
    }
    static void sessionTransitions() {
        Bank bank = new Bank(); Device device = new Device();
        ATM atm = new ATM(bank, device, Map.of(20000L, 3), 100000);
        atm.insertCard("card-A");
        check(!atm.enterPin("bad"));
        try { atm.insertCard("card-B"); throw new AssertionError(); }
        catch (IllegalStateException expected) { }
        try { atm.enterPin(""); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { }
        check(atm.enterPin("1234"));
        try { atm.enterPin("bad"); throw new AssertionError(); }
        catch (IllegalStateException expected) { }
        check(atm.state().equals(ATM.ATMState.READY));
        atm.cancel();
        atm.insertCard("card-A");
        check(!atm.enterPin("bad"));
        atm.cancel();
        atm.insertCard("card-A");
        for (int i = 0; i < 2; i++) {
            check(!atm.enterPin("bad"));
            check(atm.state().equals(ATM.ATMState.PIN_REQUIRED));
        }
        check(!atm.enterPin("bad"));
        check(atm.state().equals(ATM.ATMState.IDLE) && device.ejections == 3);
        try { atm.balance(); throw new AssertionError(); }
        catch (IllegalStateException expected) { }
        atm.insertCard("card-A");
        device.ejectFails = true;
        for (int i = 0; i < 3; i++) check(!atm.enterPin("bad"));
        check(atm.state().equals(ATM.ATMState.OUT_OF_SERVICE));
        atm.cancel();
        try { atm.insertCard("card-A"); throw new AssertionError(); }
        catch (IllegalStateException expected) { }
        check(device.ejections == 4);

        bank = new Bank(); device = new Device();
        atm = new ATM(bank, device, Map.of(20000L, 1), 100000);
        atm.insertCard("card-A");
        bank.fail = "authenticate";
        try { atm.enterPin("1234"); throw new AssertionError(); }
        catch (RuntimeException expected) { }
        check(atm.state().equals(ATM.ATMState.OUT_OF_SERVICE) && device.ejections == 1);
        check(atm.pendingOperation() == null);
    }

    static void shortageThenSuccess() {
        Bank bank = new Bank(); Device device = new Device();
        ATM atm = new ATM(bank, device, Map.of(50000L, 1, 20000L, 3), 200000);
        atm.insertCard("card-A"); check(atm.enterPin("1234"));
        check(atm.withdraw(10000).equals("CASH_UNAVAILABLE"));
        check(atm.withdraw(120000).equals("CASH_UNAVAILABLE"));
        check(bank.holds.isEmpty() && device.calls == 0);
        bank.funds = 10000;
        check(atm.withdraw(60000).equals("DECLINED"));
        check(atm.cashSnapshot().equals(Map.of(50000L, 1, 20000L, 3)));
        check(atm.state().equals(ATM.ATMState.READY) && atm.pendingOperation() == null);
        check(device.calls == 0);
        bank.funds = 100000;
        check(atm.withdraw(60000).equals("SUCCESS"));
        check(atm.withdraw(60000).equals("CASH_UNAVAILABLE"));
        check(bank.funds == 40000 && bank.holds.isEmpty() && device.calls == 1);
        check(atm.cashSnapshot().equals(Map.of(50000L, 1, 20000L, 0)));
        check(atm.state().equals(ATM.ATMState.READY) && atm.pendingOperation() == null);
    }

    static void cancellationDuringDispensing() throws Exception {
        for (String deliveryResult : List.of("ALL", "UNKNOWN")) {
            CountDownLatch entered = new CountDownLatch(1);
            CountDownLatch finish = new CountDownLatch(1);
            CountDownLatch cancelling = new CountDownLatch(1);
            Bank bank = new Bank();
            Device device = new Device() {
                public String dispense(Map<Long, Integer> notes) {
                    entered.countDown();
                    try {
                        if (!finish.await(2, TimeUnit.SECONDS)) throw new AssertionError();
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        throw new RuntimeException(e);
                    }
                    return deliveryResult;
                }
            };
            ATM atm = ready(bank, device);
            try (var pool = Executors.newFixedThreadPool(2)) {
                var withdrawal = pool.submit(() -> atm.withdraw(20000));
                Future<?> cancellation;
                try {
                    check(entered.await(2, TimeUnit.SECONDS));
                    cancellation = pool.submit(() -> { cancelling.countDown(); atm.cancel(); });
                    check(cancelling.await(2, TimeUnit.SECONDS));
                    try { cancellation.get(50, TimeUnit.MILLISECONDS); throw new AssertionError(); }
                    catch (TimeoutException expected) { }
                    check(device.ejections == 0);
                } finally { finish.countDown(); }
                check(withdrawal.get(2, TimeUnit.SECONDS).equals(deliveryResult.equals("ALL") ? "SUCCESS" : "PENDING_REVIEW"));
                cancellation.get(2, TimeUnit.SECONDS);
            }
            check(device.ejections == 1);
            check(atm.state().equals(deliveryResult.equals("ALL") ? ATM.ATMState.IDLE : ATM.ATMState.OUT_OF_SERVICE));
            check((atm.pendingOperation() == null) == deliveryResult.equals("ALL"));
            check(bank.funds == (deliveryResult.equals("ALL") ? 80000 : 100000));
            check(bank.holds.isEmpty() == deliveryResult.equals("ALL"));
        }
    }

    static void accountAndStockBoundaries() {
        List<String> seen = new ArrayList<>();
        Bank bank = new Bank() {
            public String authenticate(String card, String pin) {
                return pin.equals("1234") ? "account-" + card : null;
            }
            public long availableBalance(String account) {
                seen.add("balance:" + account);
                return super.availableBalance(account);
            }
            public boolean hold(String account, long amount, String id) {
                seen.add("hold:" + account);
                return super.hold(account, amount, id);
            }
        };
        Device device = new Device();
        ATM atm = new ATM(bank, device, Map.of(20000L, 2), 20000);
        for (String card : List.of("A", "B")) {
            atm.insertCard(card); check(atm.enterPin("1234"));
            seen.clear();
            atm.balance();
            check(atm.withdraw(20000).equals("SUCCESS"));
            check(seen.equals(List.of("balance:account-" + card,
                    "hold:account-" + card, "balance:account-" + card)));
            atm.cancel();
        }
        bank = new Bank(); device = new Device();
        Map<Long, Integer> stock = new HashMap<>(Map.of(20000L, 1));
        atm = new ATM(bank, device, stock, 20000);
        stock.put(20000L, 99);
        atm.insertCard("card-A"); check(atm.enterPin("1234"));
        var snapshot = atm.cashSnapshot();
        try { snapshot.put(20000L, 88); throw new AssertionError(); }
        catch (UnsupportedOperationException expected) { }
        check(atm.withdraw(20000).equals("SUCCESS"));
        check(snapshot.get(20000L) == 1);
        check(atm.cashSnapshot().equals(Map.of(20000L, 0)));
        check(atm.withdraw(20000).equals("CASH_UNAVAILABLE"));
        check(bank.funds == 80000 && device.calls == 1);
    }

    static void uncertainWithdrawalWithStuckCard() {
        Bank bank = new Bank(); Device device = new Device();
        ATM atm = ready(bank, device);
        device.outcome = "UNKNOWN";
        device.ejectFails = true;
        check(atm.withdraw(20000).equals("PENDING_REVIEW"));
        String pending = atm.pendingOperation();
        check(atm.state().equals(ATM.ATMState.OUT_OF_SERVICE) && bank.holds.containsKey(pending));
        atm.cancel();
        for (Runnable action : List.<Runnable>of(
                () -> atm.insertCard("card-B"), () -> atm.enterPin("1234"),
                () -> atm.balance(), () -> atm.withdraw(20000))) {
            try { action.run(); throw new AssertionError(); }
            catch (IllegalStateException expected) { }
        }
        check(atm.state().equals(ATM.ATMState.OUT_OF_SERVICE) && atm.pendingOperation().equals(pending));
        check(device.ejections == 1 && device.calls == 1);
        check(bank.funds == 100000 && bank.holds.get(pending) == 20000);
        check(atm.cashSnapshot().equals(Map.of(50000L, 1, 20000L, 3)));
    }

    public static void main(String[] args) throws Exception {
        uncertainWithdrawalWithStuckCard();
        accountAndStockBoundaries();
        cancellationDuringDispensing();
        shortageThenSuccess();
        sessionTransitions();
        Bank bank = new Bank(); Device device = new Device();
        ATM atm = ready(bank, device);
        check(atm.withdraw(60000).equals("SUCCESS"));
        check(atm.balance() == 40000 && atm.cashSnapshot().get(20000L) == 0);
        atm.cancel();
        check(atm.state().equals(ATM.ATMState.IDLE) && device.ejections == 1);
        atm.insertCard("card-A");
        for (int i = 0; i < 3; i++) check(!atm.enterPin("bad"));
        check(atm.state().equals(ATM.ATMState.IDLE));

        for (String outcome : List.of("NONE", "UNKNOWN", "TIMEOUT")) {
            bank = new Bank(); device = new Device(); atm = ready(bank, device);
            device.outcome = outcome;
            String result = atm.withdraw(20000);
            if (outcome.equals("NONE")) {
                check(result.equals("NOT_DISPENSED") && bank.holds.isEmpty());
            } else {
                check(result.equals("PENDING_REVIEW") && !bank.holds.isEmpty());
                check(atm.state().equals(ATM.ATMState.OUT_OF_SERVICE));
                atm.cancel();
                check(atm.state().equals(ATM.ATMState.OUT_OF_SERVICE));
            }
            check(atm.cashSnapshot().get(20000L) == 3);
        }
        for (String stage : List.of("hold", "capture", "release")) {
            bank = new Bank(); device = new Device(); atm = ready(bank, device);
            bank.fail = stage;
            if (stage.equals("release")) device.outcome = "NONE";
            check(atm.withdraw(20000).equals("PENDING_REVIEW"));
            check(atm.pendingOperation() != null && atm.state().equals(ATM.ATMState.OUT_OF_SERVICE));
            check(atm.cashSnapshot().get(20000L) == (stage.equals("capture") ? 2 : 3));
        }
        bank = new Bank(); device = new Device(); atm = ready(bank, device);
        check(atm.withdraw(10000).equals("CASH_UNAVAILABLE") && bank.holds.isEmpty());
        bank.funds = 10000;
        check(atm.withdraw(20000).equals("DECLINED") && device.calls == 0);
        for (long amount : new long[]{0, -1, 100001}) {
            try { atm.withdraw(amount); throw new AssertionError(); }
            catch (IllegalArgumentException expected) { }
        }
        device.ejectFails = true; atm.cancel();
        check(atm.state().equals(ATM.ATMState.OUT_OF_SERVICE));

        for (String stage : List.of("capture_after", "release_after")) {
            bank = new Bank(); device = new Device(); atm = ready(bank, device);
            bank.fail = stage;
            boolean delivered = stage.equals("capture_after");
            device.outcome = delivered ? "ALL" : "NONE";
            check(atm.withdraw(20000).equals("PENDING_REVIEW"));
            check(atm.state().equals(ATM.ATMState.OUT_OF_SERVICE) && atm.pendingOperation() != null);
            check(bank.holds.isEmpty() && bank.funds == (delivered ? 80000 : 100000));
            check(atm.cashSnapshot().get(20000L) == (delivered ? 2 : 3));
            check(device.calls == 1);
            try { atm.withdraw(20000); throw new AssertionError(); }
            catch (IllegalStateException expected) { }
        }
        bank = new Bank(); device = new Device(); atm = ready(bank, device);
        bank.fail = "balance";
        try { atm.balance(); throw new AssertionError(); }
        catch (RuntimeException expected) { }
        check(atm.state().equals(ATM.ATMState.READY) && device.ejections == 0);
        bank.fail = "";
        check(atm.balance() == 100000);

        Bank concurrentBank = new Bank(); Device concurrentDevice = new Device();
        ATM shared = new ATM(concurrentBank, concurrentDevice, Map.of(20000L, 1), 100000);
        shared.insertCard("card-A"); shared.enterPin("1234");
        try (var pool = Executors.newFixedThreadPool(2)) {
            var first = pool.submit(() -> shared.withdraw(20000));
            var second = pool.submit(() -> shared.withdraw(20000));
            check(Set.of(first.get(), second.get()).equals(Set.of("SUCCESS", "CASH_UNAVAILABLE")));
        }
        check(concurrentBank.funds == 80000);
        for (int a=0; a<3; a++) for (int b=0; b<3; b++) for (int c=0; c<3; c++) {
            var inventory = Map.of(5L, a, 3L, b, 2L, c);
            var cash = new ATM.CashInventory(inventory);
            Set<Long> possible = new HashSet<>();
            for (int x=0; x<=a; x++) for (int y=0; y<=b; y++) for (int z=0; z<=c; z++)
                possible.add(5L*x + 3L*y + 2L*z);
            for (long amount=1; amount<=20; amount++) {
                var plan = cash.plan(amount);
                check((plan != null) == possible.contains(amount));
                if (plan != null) {
                    check(plan.entrySet().stream().mapToLong(e -> e.getKey()*e.getValue()).sum() == amount);
                    plan.forEach((d,n) -> check(n > 0 && n <= inventory.get(d)));
                }
            }
            check(cash.snapshot().equals(inventory));
        }
        System.out.println("ATM Java scenarios passed, including 540 allocation checks.");
    }
}
