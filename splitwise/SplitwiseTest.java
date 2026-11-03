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
        var service = new Splitwise(Map.of("trip", List.of("A", "B", "C"), "home", List.of("A", "B")));
        var participants = new ArrayList<>(List.of("A", "B", "C"));
        var input = new Splitwise.EqualSplitInput(participants);
        participants.clear();
        check(service.addExpense(new Splitwise.AddExpenseRequest("trip", "A", 100, input))
                .shares().equals(Map.of("A", 34L, "B", 33L, "C", 33L)));
        check(service.addExpense(new Splitwise.AddExpenseRequest("trip", "A", 100,
                new Splitwise.ExactSplitInput(Map.of("B", 100L)))).shares().equals(Map.of("B", 100L)));
        check(service.addExpense(new Splitwise.AddExpenseRequest("trip", "A", 101,
                new Splitwise.PercentageSplitInput(Map.of("A", 3333, "B", 3333, "C", 3334))))
                .shares().equals(Map.of("A", 34L, "B", 33L, "C", 34L)));
        check(service.getBalances("home").isEmpty());
        var sourceAmounts = new HashMap<>(Map.of("B", 100L));
        var sourceWeights = new HashMap<>(Map.of("B", 10000));
        var exactInput = new Splitwise.ExactSplitInput(sourceAmounts);
        var percentInput = new Splitwise.PercentageSplitInput(sourceWeights);
        sourceAmounts.clear(); sourceWeights.clear();
        check(exactInput.amountsByUser().equals(Map.of("B", 100L)));
        check(percentInput.basisPointsByUser().equals(Map.of("B", 10000)));
        try { exactInput.amountsByUser().put("B", 0L); throw new AssertionError("Mutable input"); }
        catch (UnsupportedOperationException expected) {}
        for (String invalid : Arrays.asList(null, "", "é")) {
            try { service.getBalances(invalid); throw new AssertionError("Invalid group ID"); }
            catch (IllegalArgumentException expected) {}
            try { service.getHistory(invalid); throw new AssertionError("Invalid group ID"); }
            catch (IllegalArgumentException expected) {}
            try { service.recordSettlement("trip", invalid, "B", 1); throw new AssertionError("Invalid debtor ID"); }
            catch (IllegalArgumentException expected) {}
        }
        var snapshot = service.getHistory("trip");
        var debts = service.getBalances("trip");
        for (var request : List.of(
                new Splitwise.AddExpenseRequest("trip", "A", 100, null),
                new Splitwise.AddExpenseRequest("missing", "A", 100, input),
                new Splitwise.AddExpenseRequest("trip", "A", 100, new Splitwise.EqualSplitInput(List.of("B", "B"))),
                new Splitwise.AddExpenseRequest("trip", "A", 100, new Splitwise.ExactSplitInput(Map.of("X", 100L))),
                new Splitwise.AddExpenseRequest("trip", "A", 100, new Splitwise.ExactSplitInput(Map.of("B", 99L))),
                new Splitwise.AddExpenseRequest("trip", "A", 100, new Splitwise.PercentageSplitInput(Map.of("B", 9999))))) {
            try { service.addExpense(request); throw new AssertionError("Invalid request accepted"); }
            catch (IllegalArgumentException expected) {
                check(service.getHistory("trip").equals(snapshot));
                check(service.getBalances("trip").equals(debts));
            }
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
