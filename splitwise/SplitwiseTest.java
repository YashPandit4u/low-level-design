import java.util.*;
import java.util.concurrent.*;

public final class SplitwiseTest {
    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
    public static void main(String[] args) throws Exception {
        check(new Splitwise.EqualSplitStrategy().allocate(10000, List.of("C", "A", "B"), null)
                .equals(Map.of("A", 3334L, "B", 3333L, "C", 3333L)));
        check(new Splitwise.PercentageSplitStrategy().allocate(101, List.of("A", "B", "C"), List.of(3333L, 3333L, 3334L))
                .equals(Map.of("A", 34L, "B", 33L, "C", 34L)));
        for (long total = 1; total <= 300; total++) {
            var shares = new Splitwise.PercentageSplitStrategy().allocate(total, List.of("A", "B", "C"), List.of(3333L, 3333L, 3334L));
            check(shares.values().stream().mapToLong(Long::longValue).sum() == total);
        }
        List<Splitwise.SplitStrategy> algorithms = List.of(
            new Splitwise.EqualSplitStrategy(), new Splitwise.ExactSplitStrategy(), new Splitwise.PercentageSplitStrategy());
        var allocationPool = Executors.newFixedThreadPool(8);
        try {
            List<Callable<Boolean>> tasks = new ArrayList<>();
            for (long i = 1; i <= 100; i++) {
                final long amount = i;
                tasks.add(() -> {
                    var ids = List.of("A" + amount, "B" + amount);
                    for (int j = 0; j < algorithms.size(); j++) {
                        List<Long> input = j == 0 ? null : j == 1
                            ? List.of(amount, amount) : List.of(5000L, 5000L);
                        check(algorithms.get(j).allocate(2 * amount, ids, input)
                            .equals(Map.of(ids.get(0), amount, ids.get(1), amount)));
                    }
                    return true;
                });
            }
            for (var result : allocationPool.invokeAll(tasks)) check(result.get());
        } finally { allocationPool.shutdownNow(); }
        var service = new Splitwise(Map.of("trip", List.of("A", "B", "C")));
        var users = new ArrayList<>(List.of("A", "B", "C"));
        check(service.addExpense("trip", "A", 100, "EQUAL", users, null)
                .shares().equals(Map.of("A", 34L, "B", 33L, "C", 33L)));
        var values = new ArrayList<>(List.of(0L, 100L, 0L));
        var exact = service.addExpense("trip", "A", 100, "EXACT", users, values);
        values.clear();
        check(exact.shares().equals(Map.of("A", 0L, "B", 100L, "C", 0L)));
        check(service.addExpense("trip", "A", 101, "PERCENTAGE", users,
                List.of(3333L, 3333L, 3334L)).shares().equals(Map.of("A", 34L, "B", 33L, "C", 34L)));
        var snapshot = service.getHistory("trip");
        var debts = service.getBalances("trip");
        List<Runnable> invalid = List.of(
            () -> service.addExpense("trip", "A", 100, null, users, null),
            () -> service.addExpense("trip", "A", 100, "EQUAL", List.of("B", "B"), null),
            () -> service.addExpense("trip", "A", 100, "EQUAL", users, List.of(100L)),
            () -> service.addExpense("trip", "A", 100, "EXACT", users, null),
            () -> service.addExpense("trip", "A", 100, "EXACT", users, List.of(100L)),
            () -> service.addExpense("trip", "A", 100, "EXACT", List.of("B"), List.of(99L)),
            () -> service.addExpense("trip", "A", 100, "PERCENTAGE", List.of("B"), List.of(9999L)),
            () -> service.addExpense("missing", "A", 100, "EQUAL", users, null));
        for (var action : invalid) {
            try { action.run(); throw new AssertionError("Invalid input accepted"); }
            catch (IllegalArgumentException expected) {
                check(service.getHistory("trip").equals(snapshot));
                check(service.getBalances("trip").equals(debts));
            }
        }
        var group = new Splitwise.Group(List.of("A", "B", "C"));
        group.addExpense("A", 90000, new Splitwise.EqualSplitStrategy(), List.of("A", "B", "C"), null);
        group.addExpense("B", 30000, new Splitwise.EqualSplitStrategy(), List.of("A", "B"), null);
        group.recordSettlement("B", "A", 10000);
        check(group.getBalances().equals(List.of(new Splitwise.Debt("B", "A", 5000), new Splitwise.Debt("C", "A", 30000))));
        var before = group.getHistory();
        try {
            group.recordSettlement("B", "A", 6000);
            throw new AssertionError("Overpayment accepted");
        } catch (IllegalArgumentException expected) { check(group.getHistory().equals(before)); }
        group.recordSettlement("B", "A", 5000);
        check(group.getBalances().size() == 1);

        var overflow = new Splitwise.Group(List.of("A", "B"));
        overflow.addExpense("B", Long.MAX_VALUE, new Splitwise.ExactSplitStrategy(), List.of("A"), List.of(Long.MAX_VALUE));
        try {
            overflow.addExpense("B", 1, new Splitwise.ExactSplitStrategy(), List.of("A"), List.of(1L));
            throw new AssertionError("Overflow accepted");
        } catch (ArithmeticException expected) {
            check(overflow.getHistory().size() == 1);
            check(overflow.getBalances().get(0).amount() == Long.MAX_VALUE);
        }
        var concurrent = new Splitwise.Group(List.of("A", "B"));
        concurrent.addExpense("A", 10000, new Splitwise.ExactSplitStrategy(), List.of("B"), List.of(10000L));
        var barrier = new CyclicBarrier(2);
        var pool = Executors.newFixedThreadPool(2);
        Callable<Boolean> settle = () -> {
            barrier.await();
            try { concurrent.recordSettlement("B", "A", 8000); return true; }
            catch (IllegalArgumentException expected) { return false; }
        };
        try {
            var first = pool.submit(settle);
            var second = pool.submit(settle);
            check(first.get() != second.get());
            check(concurrent.getBalances().equals(List.of(new Splitwise.Debt("B", "A", 2000))));
            check(concurrent.getHistory().size() == 2);
        } finally { pool.shutdownNow(); }
        System.out.println("Java checks passed: rounding, conservation, netting, settlement, overflow, concurrency.");
    }
}
