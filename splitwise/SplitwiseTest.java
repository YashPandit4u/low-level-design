import java.util.*;
import java.util.concurrent.*;

public final class SplitwiseTest {
    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
    public static void main(String[] args) throws Exception {
        check(new Splitwise.EqualSplit(List.of("C", "A", "B")).allocate(10000)
                .equals(Map.of("A", 3334L, "B", 3333L, "C", 3333L)));
        check(new Splitwise.PercentageSplit(Map.of("A", 3333, "B", 3333, "C", 3334)).allocate(101)
                .equals(Map.of("A", 34L, "B", 33L, "C", 34L)));
        for (long total = 1; total <= 300; total++) {
            var shares = new Splitwise.PercentageSplit(Map.of("A", 3333, "B", 3333, "C", 3334)).allocate(total);
            check(shares.values().stream().mapToLong(Long::longValue).sum() == total);
        }
        var group = new Splitwise.Group(List.of("A", "B", "C"));
        group.addExpense("A", 90000, new Splitwise.EqualSplit(List.of("A", "B", "C")));
        group.addExpense("B", 30000, new Splitwise.EqualSplit(List.of("A", "B")));
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
        overflow.addExpense("B", Long.MAX_VALUE, new Splitwise.ExactSplit(Map.of("A", Long.MAX_VALUE)));
        try {
            overflow.addExpense("B", 1, new Splitwise.ExactSplit(Map.of("A", 1L)));
            throw new AssertionError("Overflow accepted");
        } catch (ArithmeticException expected) {
            check(overflow.getHistory().size() == 1);
            check(overflow.getBalances().get(0).amount() == Long.MAX_VALUE);
        }
        var concurrent = new Splitwise.Group(List.of("A", "B"));
        concurrent.addExpense("A", 10000, new Splitwise.ExactSplit(Map.of("B", 10000L)));
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
