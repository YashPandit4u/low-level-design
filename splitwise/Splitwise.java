import java.math.BigInteger;
import java.util.*;

/** Java 17+ reference implementation for the accompanying article. */
public final class Splitwise {
    static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }
    static void validId(String id) {
        require(id != null && !id.isBlank() && id.chars().allMatch(c -> c < 128), "Invalid ASCII ID");
    }
    static List<String> participantIds(List<String> participants) {
        require(participants != null && !participants.isEmpty(), "Participants required");
        participants.forEach(Splitwise::validId);
        var users = List.copyOf(participants);
        require(new HashSet<>(users).size() == users.size(), "Duplicate participant");
        return users;
    }
    static Map<String, Long> splitValues(List<String> users, List<Long> values) {
        require(values != null && values.size() == users.size(), "One value per participant required");
        for (Long value : values) require(value != null && value >= 0, "Invalid split value");
        values = List.copyOf(values);
        Map<String, Long> result = new HashMap<>();
        for (int i = 0; i < users.size(); i++) result.put(users.get(i), values.get(i));
        return result;
    }
    // Internal stateless algorithms; expense inputs arrive on each call.
    interface SplitStrategy {
        Map<String, Long> allocate(long total, List<String> participants, List<Long> values);
    }
    static final class EqualSplit implements SplitStrategy {
        public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
            require(total > 0, "Positive total required");
            var sorted = new ArrayList<>(participantIds(participants));
            require(values == null, "Equal splits do not take values");
            Collections.sort(sorted);
            long base = total / sorted.size(), remainder = total % sorted.size();
            Map<String, Long> result = new HashMap<>();
            for (int i = 0; i < sorted.size(); i++)
                result.put(sorted.get(i), base + (i < remainder ? 1 : 0));
            return result;
        }
    }
    static final class ExactSplit implements SplitStrategy {
        public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
            require(total > 0, "Positive total required");
            var amounts = splitValues(participantIds(participants), values);
            long sum = 0;
            for (long amount : amounts.values()) sum = Math.addExact(sum, amount);
            require(sum == total, "Shares must sum to total");
            return amounts;
        }
    }
    static final class PercentageSplit implements SplitStrategy {
        public Map<String, Long> allocate(long total, List<String> participants, List<Long> values) {
            require(total > 0, "Positive total required");
            var bps = splitValues(participantIds(participants), values);
            long sum = 0;
            for (long weight : bps.values()) {
                require(weight <= 10000, "Invalid percentage");
                sum += weight;
            }
            require(sum == 10000, "Percentages must sum to 10000 basis points");
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
            require(!users.isEmpty(), "Group members required");
            users.forEach(Splitwise::validId);
            members = Set.copyOf(users);
            require(members.size() == users.size(), "Duplicate member");
        }
        private void member(String user) {
            validId(user);
            require(members.contains(user), "Unknown group member");
        }
        private static Delta delta(String debtor, String creditor, long amount) {
            return debtor.compareTo(creditor) < 0
                    ? new Delta(new Pair(debtor, creditor), amount)
                    : new Delta(new Pair(creditor, debtor), -amount);
        }
        public Expense addExpense(String payer, long total, SplitStrategy strategy,
                                  List<String> participants, List<Long> values) {
            require(total > 0, "Positive total required");
            member(payer);
            participants = participantIds(participants);
            participants.forEach(this::member);
            values = values == null ? null : new ArrayList<>(values);
            var shares = Map.copyOf(strategy.allocate(total, participants, values));
            require(shares.keySet().equals(new HashSet<>(participants)), "Allocation must contain exactly the participants");
            require(!shares.isEmpty(), "Participants required");
            long sum = 0;
            for (var entry : shares.entrySet()) {
                member(entry.getKey());
                require(entry.getValue() >= 0, "Negative share");
                sum = Math.addExact(sum, entry.getValue());
            }
            require(sum == total, "Invalid strategy result");
            var expense = new Expense(UUID.randomUUID().toString(), payer, total, shares);
            synchronized (lock) {
                Map<Pair, Long> pending = new HashMap<>();
                for (var entry : shares.entrySet()) {
                    if (entry.getKey().equals(payer) || entry.getValue() == 0) continue;
                    var d = delta(entry.getKey(), payer, entry.getValue());
                    long next = Math.addExact(balances.getOrDefault(d.pair(), 0L), d.value());
                    require(next != Long.MIN_VALUE, "Balance magnitude exceeds supported range");
                    pending.put(d.pair(), next);
                }
                commit(pending, expense);
            }
            return expense;
        }
        public Settlement recordSettlement(String debtor, String creditor, long amount) {
            require(amount > 0, "Positive settlement required");
            member(debtor); member(creditor);
            require(!debtor.equals(creditor), "Cannot settle with yourself");
            var d = delta(debtor, creditor, 1);
            var event = new Settlement(UUID.randomUUID().toString(), debtor, creditor, amount);
            synchronized (lock) {
                long balance = balances.getOrDefault(d.pair(), 0L);
                long outstanding = d.value() * balance;
                require(amount <= outstanding, "Settlement exceeds debt in this direction");
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
        "EQUAL", new EqualSplit(), "EXACT", new ExactSplit(), "PERCENTAGE", new PercentageSplit());
    private final Map<String, Group> groups;
    public Splitwise(Map<String, List<String>> groupMembers) {
        Map<String, Group> built = new HashMap<>();
        groupMembers.forEach((id, members) -> { validId(id); built.put(id, new Group(members)); });
        groups = Map.copyOf(built);
    }
    private Group group(String id) {
        validId(id);
        var group = groups.get(id);
        require(group != null, "Unknown group");
        return group;
    }
    public Expense addExpense(String groupId, String payer, long total, String splitType,
                              List<String> participants, List<Long> values) {
        var group = group(groupId);
        validId(payer);
        require(total > 0, "Positive total required");
        require(splitType != null && strategies.containsKey(splitType), "Unknown split type");
        return group.addExpense(payer, total, strategies.get(splitType), participants, values);
    }

    public Settlement recordSettlement(String groupId, String debtor, String creditor, long amount) {
        return group(groupId).recordSettlement(debtor, creditor, amount);
    }
    public List<Debt> getBalances(String groupId) { return group(groupId).getBalances(); }
    public List<Event> getHistory(String groupId) { return group(groupId).getHistory(); }
}
