import java.math.BigInteger;
import java.util.*;

/** Java 17+ reference implementation for the accompanying article. */
public final class Splitwise {
    // Internal algorithms. Group validates and copies common inputs before calling.
    interface SplitStrategy {
        Map<String, Long> allocate(long total, List<String> participants, List<Long> values);
    }
    static final class EqualSplitStrategy implements SplitStrategy {
        public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
            var sorted = new ArrayList<>(participants);
            if (values != null) throw new IllegalArgumentException("Equal splits do not take values");
            Collections.sort(sorted);
            long base = total / sorted.size(), remainder = total % sorted.size();
            Map<String, Long> result = new HashMap<>();
            for (int i = 0; i < sorted.size(); i++)
                result.put(sorted.get(i), base + (i < remainder ? 1 : 0));
            return result;
        }
    }
    static final class ExactSplitStrategy implements SplitStrategy {
        public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
            if (values == null) throw new IllegalArgumentException("Split values required");
            Map<String, Long> amounts = new HashMap<>();
            for (int i = 0; i < participants.size(); i++)
                amounts.put(participants.get(i), values.get(i));
            long sum = 0;
            for (long amount : amounts.values()) sum = Math.addExact(sum, amount);
            if (sum != total) throw new IllegalArgumentException("Shares must sum to total");
            return amounts;
        }
    }
    static final class PercentageSplitStrategy implements SplitStrategy {
        public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
            if (values == null) throw new IllegalArgumentException("Split values required");
            Map<String, Long> bps = new HashMap<>();
            for (int i = 0; i < participants.size(); i++)
                bps.put(participants.get(i), values.get(i));
            long sum = 0;
            for (long weight : bps.values()) {
                if (weight > 10000) throw new IllegalArgumentException("Invalid percentage");
                sum += weight;
            }
            if (sum != 10000) throw new IllegalArgumentException("Percentages must sum to 10000 basis points");
            Map<String, Long> shares = new HashMap<>();
            Map<String, Long> fractions = new HashMap<>();
            long allocated = 0;
            for (var entry : bps.entrySet()) {
                var qr = BigInteger.valueOf(total).multiply(BigInteger.valueOf(entry.getValue()))
                        .divideAndRemainder(BigInteger.valueOf(10000));
                long share = qr[0].longValueExact();
                shares.put(entry.getKey(), share);
                fractions.put(entry.getKey(), qr[1].longValueExact());
                allocated = Math.addExact(allocated, share);
            }
            var order = new ArrayList<>(bps.keySet());
            order.sort(Comparator.<String>comparingLong(fractions::get).reversed()
                    .thenComparing(Comparator.naturalOrder()));
            long leftover = total - allocated;
            for (int i = 0; i < leftover; i++)
                shares.put(order.get(i), shares.get(order.get(i)) + 1);
            return shares;
        }
    }
    public sealed interface Event permits Expense, Settlement {}
    public record Expense(String id, String payer, long total, Map<String, Long> shares) implements Event {
        public Expense { shares = Map.copyOf(shares); }
    }
    public record Settlement(String id, String debtor, String creditor, long amount) implements Event {}
    public record Debt(String debtor, String creditor, long amount) {}
    private record Pair(String lower, String higher) {}
    private record Delta(Pair pair, long value) {}

    static final class Group {
        private final Set<String> members;
        private final Map<Pair, Long> balances = new HashMap<>();
        private final List<Event> history = new ArrayList<>();
        private final Object lock = new Object();
        public Group(List<String> users) {
            if (users == null || users.isEmpty())
                throw new IllegalArgumentException("Group members required");
            if (users.stream().anyMatch(id -> id == null || id.isBlank()))
                throw new IllegalArgumentException("Invalid member ID");
            members = Set.copyOf(users);
            if (members.size() != users.size()) throw new IllegalArgumentException("Duplicate member");
        }
        private static Delta delta(String debtor, String creditor, long amount) {
            return debtor.compareTo(creditor) < 0
                    ? new Delta(new Pair(debtor, creditor), amount)
                    : new Delta(new Pair(creditor, debtor), -amount);
        }
        public Expense addExpense(String payer, long total, SplitStrategy strategy,
                                  List<String> participants, List<Long> values) {
            if (total <= 0) throw new IllegalArgumentException("Positive total required");
            if (payer == null || !members.contains(payer))
                throw new IllegalArgumentException("Unknown payer");
            if (participants == null || participants.isEmpty())
                throw new IllegalArgumentException("Participants required");
            if (participants.stream().anyMatch(id -> id == null || id.isBlank()))
                throw new IllegalArgumentException("Invalid participant ID");
            participants = List.copyOf(participants);
            if (new HashSet<>(participants).size() != participants.size())
                throw new IllegalArgumentException("Duplicate participant");
            if (!members.containsAll(participants))
                throw new IllegalArgumentException("Unknown group participant");
            if (values != null) {
                if (values.size() != participants.size())
                    throw new IllegalArgumentException("One value per participant required");
                if (values.stream().anyMatch(value -> value == null || value < 0))
                    throw new IllegalArgumentException("Invalid split value");
                values = List.copyOf(values);
            }

            var shares = Map.copyOf(strategy.allocate(total, participants, values));
            if (!shares.keySet().equals(new HashSet<>(participants))) throw new IllegalArgumentException("Allocation must contain exactly the participants");
            long sum = 0;
            for (var entry : shares.entrySet()) {
                if (entry.getValue() < 0) throw new IllegalArgumentException("Negative share");
                sum = Math.addExact(sum, entry.getValue());
            }
            if (sum != total) throw new IllegalArgumentException("Invalid strategy result");
            var expense = new Expense(UUID.randomUUID().toString(), payer, total, shares);
            synchronized (lock) {
                Map<Pair, Long> pending = new HashMap<>();
                for (var entry : shares.entrySet()) {
                    if (entry.getKey().equals(payer) || entry.getValue() == 0) continue;
                    var d = delta(entry.getKey(), payer, entry.getValue());
                    long next = Math.addExact(balances.getOrDefault(d.pair(), 0L), d.value());
                    if (next == Long.MIN_VALUE) throw new IllegalArgumentException("Balance magnitude exceeds supported range");
                    pending.put(d.pair(), next);
                }
                commit(pending, expense);
            }
            return expense;
        }
        public Settlement recordSettlement(String debtor, String creditor, long amount) {
            if (amount <= 0) throw new IllegalArgumentException("Positive settlement required");
            if (debtor == null || creditor == null || !members.contains(debtor) || !members.contains(creditor))
                throw new IllegalArgumentException("Unknown group member");
            if (debtor.equals(creditor)) throw new IllegalArgumentException("Cannot settle with yourself");
            var d = delta(debtor, creditor, 1);
            var event = new Settlement(UUID.randomUUID().toString(), debtor, creditor, amount);
            synchronized (lock) {
                long balance = balances.getOrDefault(d.pair(), 0L);
                long outstanding = d.value() * balance;
                if (amount > outstanding) throw new IllegalArgumentException("Settlement exceeds debt in this direction");
                commit(Map.of(d.pair(), balance - d.value() * amount), event);
            }
            return event;
        }
        private void commit(Map<Pair, Long> pending, Event event) {
            // Caller holds lock; domain validation and checked arithmetic are complete.
            pending.forEach((pair, value) -> {
                if (value == 0) balances.remove(pair);
                else balances.put(pair, value);
            });
            history.add(event);
        }
        public List<Debt> getBalances() {
            synchronized (lock) {
                List<Debt> result = new ArrayList<>();
                balances.forEach((pair, value) -> result.add(value > 0
                    ? new Debt(pair.lower(), pair.higher(), value)
                    : new Debt(pair.higher(), pair.lower(), -value)));
                result.sort(Comparator.comparing(Debt::debtor).thenComparing(Debt::creditor));
                return List.copyOf(result);
            }
        }
        public List<Event> getHistory() {
            synchronized (lock) { return List.copyOf(history); }
        }
    }
    private final Map<String, SplitStrategy> strategies = Map.of(
        "EQUAL", new EqualSplitStrategy(), "EXACT", new ExactSplitStrategy(), "PERCENTAGE", new PercentageSplitStrategy());
    private final Map<String, Group> groups;
    public Splitwise(Map<String, List<String>> groupMembers) {
        Map<String, Group> built = new HashMap<>();
        groupMembers.forEach((id, members) -> {
            if (id == null || id.isBlank()) throw new IllegalArgumentException("Invalid group ID");
            built.put(id, new Group(members));
        });
        groups = Map.copyOf(built);
    }
    public Expense addExpense(String groupId, String payer, long total, String splitType,
                              List<String> participants, List<Long> values) {
        Group group = groupId == null ? null : groups.get(groupId);
        if (group == null) throw new IllegalArgumentException("Unknown group");
        if (splitType == null || !strategies.containsKey(splitType)) throw new IllegalArgumentException("Unknown split type");
        return group.addExpense(payer, total, strategies.get(splitType), participants, values);
    }

    public Settlement recordSettlement(String groupId, String debtor, String creditor, long amount) {
        Group group = groupId == null ? null : groups.get(groupId);
        if (group == null) throw new IllegalArgumentException("Unknown group");
        return group.recordSettlement(debtor, creditor, amount);
    }
    public List<Debt> getBalances(String groupId) {
        Group group = groupId == null ? null : groups.get(groupId);
        if (group == null) throw new IllegalArgumentException("Unknown group");
        return group.getBalances();
    }
    public List<Event> getHistory(String groupId) {
        Group group = groupId == null ? null : groups.get(groupId);
        if (group == null) throw new IllegalArgumentException("Unknown group");
        return group.getHistory();
    }
}
