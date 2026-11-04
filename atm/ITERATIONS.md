# ATM article: ten separate iterations

Repository: /Users/yashpandit/studies/switch/low-level-design
Publish: https://yashpandit4u.github.io/low-level-design/atm/
Each iteration is a separate scheduled prompt. Read this document and prior results before editing. Run exactly your assigned iteration, not a loop of revisions. Commit and push each completed iteration. Never overwrite another run's uncommitted work. If a preceding iteration is incomplete, recover that prerequisite before your assigned review and explain this in the log.

## Yash's requirements carried forward from Splitwise

- Follow the actual Hello Interview reading structure and UI. Read its reference articles in the user's authenticated browser where necessary. Do not claim to have read inaccessible content. Inventory Management is especially useful for the implementation delivery; Connect Four and Parking Lot provide other comparisons.
- Write an original ATM article. Use plain, conversational teaching language. Avoid clever phrasing, compressed semicolon sentences, unexplained jargon, and claims of being an official Hello Interview article.
- Start with the problem, clarification dialogue, final requirements, entities, class design, implementation, verification, follow-ups, and interview expectations. Explain why choices meet requirements.
- Requirements belong in the existing code-block-style UI. List out-of-scope items on separate lines.
- Main class design/implementation headings and right-side navigation use class names, not every small method or issue. Verification is nested inside Implementation, and individual tests do not clutter the right menu.
- Begin implementation by identifying important classes/methods and why they deserve attention. Explain important methods BEFORE code. Use explicit Core logic numbered steps and Edge cases bullets selectively for complex operations. Small helpers need brief explanations, not repeated templates.
- Provide complete methods and constructors in both Python and Java. Avoid fragments like 'after looking up the group', undefined helper calls, or hiding the lesson exclusively in a final source dump. Keep explanations clear and concise, with typed fields and money units in code.
- Do not add layers merely to demonstrate a pattern. Public callers supply strings/IDs/simple values, not constructed strategy objects. Use stateless algorithms where expense/request data belongs to each call. Name strategy implementations consistently with a Strategy suffix if strategies are justified.
- Validate common input once at the owning boundary. Keep small checks inline and retain only meaningful domain helpers. Avoid lengthy defensive validation repeated in each algorithm, irrelevant ASCII rules, gratuitous HTTP/security digressions, DTO hierarchies, or enum/factory proliferation.
- Explain alternatives with logically justified Bad/Good/Great labels. Multiple options can share a rating; choose based on the requirements. Reuse existing collapsed comparison UI, without inventing recommendation badges.
- Use Python/Java tabs, smooth section scrolling, polished existing search/theme controls, a layout that works on wide screens and mobile, and no unnecessary left sidebar. No ATM simulation or game. No complexity table/section.
- Detailed edition is the default. Preserve the existing Splitwise endpoint and its contents. Reuse its page shell locally for ATM, adapting titles, links and controls. An ATM simplified edition is optional, not a reason to dilute the main walkthrough.
- Attribute authorship to Yash Pandit with a short friendly footer. Use an ATM-appropriate learning line rather than pretending Hello Interview wrote it.
- Verify article snippets and runnable implementations agree. Test meaningful success/failure paths, no partial mutation, and concurrency where in scope. Rebuild HTML and verify links, tabs, and navigation. Push to main and check Pages deployment before saying 'live'.

## ATM design concerns

Choose a concrete interview scope: card/session/PIN flow, balance inquiry, withdrawal, cancel/eject, bank interface, cash inventory and dispenser. Clarify deposits and external bank ownership. Model money as integer minor units. Explain state transitions and invalid operations. Separate bank debit authorization from cash dispensing, acknowledge uncertain/partial hardware outcomes, avoid unsafe automatic refunds after unknown dispensing outcomes. Discuss idempotency and reconciliation in follow-ups rather than overloading the main walkthrough. Cash denomination allocation must respect counts; explain greedy limitations if noncanonical denominations are allowed. Use fake bank/hardware in tests, no real banking integrations or credentials.

## Scheduled iteration focus

1. Read references, create complete ATM article and implementations, reuse UI, test and publish first version.
2. Compare problem framing, clarification dialogue, requirements and scope with reference. Fix gaps.
3. Compare entity selection, ownership, typed class design and public boundaries. Fix gaps.
4. Compare implementation teaching order, complete methods, explanations before code, selective core/edge sections. Fix gaps.
5. Audit session/state transitions, PIN failures, cancellation and card ejection. Review reference delivery and fix both correctness and teaching gaps.
6. Audit withdrawal flow, denomination allocation and cash shortages. Compare how reference explains hard algorithms. Fix gaps.
7. Audit bank failures, hardware uncertainty, concurrent requests and recovery scope. Improve trade-offs and explanations.
8. Compare UI and navigation against reference, inspect mobile/wide layouts and both language tabs. Fix gaps without adding novel UI.
9. Audit prose throughout, remove dense phrasing, duplicated validation and needless abstractions. Recheck complete code and article consistency.
10. Final independent end-to-end comparison, fix remaining justified gaps, run meaningful verification, publish and confirm live endpoint.

## Iteration results

Results are recorded below in execution order. Each entry identifies its assigned iteration number.

### Iteration 1 — first complete article (2026-11-04)

- Prerequisite: no earlier ATM article or completed iteration existed. Created the first full version rather than revising Splitwise.
- Reference actually read in Chrome: [Inventory Management](https://www.hellointerview.com/learn/low-level-design/problem-breakdowns/inventory-management#implementation). Read the class-design transition, InventoryManager constructor and operational methods, transfer Core logic/Edge cases and comparison choices, Warehouse ownership/concurrency/alert explanations, query methods, and interface sections. Inspected its actual implementation screenshot and right-side navigation. No claim of reading other articles during this pass.
- Applied reference structure: requirements dialogue and specification panel, selected entities, class-based design and implementation sections, method selection before implementation, selective Core logic/Edge cases, comparisons inside the relevant class, and verification nested within Implementation. Reused the existing Splitwise shell, styles, tabs, search, theme control, and smooth navigation without changing Splitwise.
- Concrete gaps prevented or fixed: greedy note selection falsely rejects valid bundles; automatic refunds after uncertain dispensing can give away money; balance checks alone do not reserve funds; cancellation must not reopen an uncertain ATM; snippets must include constructors and complete methods. Corrected Python 3.9 annotation compatibility after the initial test failed. Corrected tab accessibility labels that inherited the preceding comparison title.
- Delivered original article, complete Python and Java implementations, fake bank/hardware tests, an excerpt generator, HTML builder, and page/snippet checks. Pending operation IDs remain in memory only. Crash recovery, retries, partial-delivery reconciliation, and maintenance are explicitly follow-ups, not production guarantees.
- Validation: 14 Python tests passed. Java scenario tests passed. Each language checked 540 small inventory/amount combinations against exhaustive possibilities. Covered successful withdrawal, shortages, bank decline, invalid states/amounts, PIN retries, cancel/ejection, uncertain dispensing, hold/capture/release failures, and concurrent note use. Reassembled both languages from rendered HTML and ran their behavior tests successfully. Checked all local links, unique IDs, nine language-tab pairs, and verification nesting. Chrome confirmed Java tab switching and desktop layout. Detailed mobile/wide-screen comparison remains scheduled for iteration 8.
- Publication: commit for this iteration is the commit containing this entry, followed by a deployment-verification log entry. Target: /atm/. No Splitwise files changed.
- Deployment verified: article commit `d54c59adde7bbe2356b58ff82dd94b78714b77a8`, GitHub Pages [run 41717574219](https://github.com/YashPandit4u/low-level-design/actions/runs/41717574219) build and deploy jobs succeeded. The live /atm/ returned HTML byte-for-byte identical to the tested local page (SHA-256 `075810a51e9e3be225db71a8592c28d482d1337584b0a865ceeda1a31a02e6b5`). Iteration 1 complete. Remaining iterations are separate scheduled prompts.

### Iteration 3 — entities, types, and API boundaries (2026-11-04)

- Preceding results: reviewed iteration 1, including its verified deployment. Iteration 2 has no completed log entry. Recovered the necessary scope prerequisite by checking the existing clarification and requirements against the reference and explicitly stating one machine, one session, and concurrent callers. This does not mark iteration 2's separate review complete.
- Reference actually inspected in Chrome: Inventory Management, Requirements through Final Requirements, entity-candidate filtering, InventoryManager and Warehouse class design, AlertConfig/AlertListener ownership, and Final Class Design. Read the actual article text and inspected its class-design screenshot and right navigation.
- Concrete gaps: ATM fields appeared without requirement-to-state reasoning; constructors and the meaningful session-ending helper were absent from sketches; private state versus caller operations was unclear; `withdraw -> string` left result semantics implicit; startup adapter injection was insufficiently distinguished from customer operations.
- Changes: derive ATM state from requirements, explain the session-as-fields decision, identify the screen controller's simple inputs and authenticated account ownership, add typed constructors and visibility notation, document result strings and cancellation's physical-ejection limitation, and clarify inventory plan/snapshot ownership. Added nullable Python field annotations to match the documented types. No new classes, wrappers, patterns, UI components, or money-operation behavior.
- Validation: rebuilt Markdown and both HTML aliases. Page checks passed for links, unique IDs, all nine tab pairs, and class-based navigation. Both rendered language walkthroughs were reassembled and passed their behavioral suites: 14 Python tests and Java scenarios, including 540 exact-allocation checks per language and concurrent withdrawal. Splitwise unchanged.
- Publication: article commit is the commit containing this entry. Live deployment verification follows below.
- Deployment verified: commit `eef9656bdbfbaea50a5b351eef0d53f5874711bc`, [Pages run 41736117093](https://github.com/YashPandit4u/low-level-design/actions/runs/41736117093) completed successfully. Live /atm/ matches tested HTML byte-for-byte, SHA-256 `614331bc9552a10efd70d030b5cf635715ce8ace034f2c9951416572f7caf79e`. Iteration 3 complete.

### Iteration 4 — implementation teaching and method completeness (2026-11-04)

- Reviewed iteration 3's ownership/contracts changes and verified-deployment log. The required article and scope are present. Iteration 2 remains unlogged and is not counted as completed by this pass.
- Reference actually inspected in Chrome: Inventory Management's implementation introduction, InventoryManager constructor and short delegated methods, transfer Core logic/Edge cases, Warehouse constructor and individual stock/query methods, meaningful alert helper, and interface implementation guidance. Inspected the actual page and navigation around the implementation transition. Used its method-by-method explanation rhythm, not its prose or implementation.
- Concrete gaps: CashInventory's constructor, planning, delivery update, and snapshot were bundled into one long class block after combined prose. The recursive helper's empty-map success, failed-search cache, and lifetime were not explained. Withdrawal's pending-ID timing and exception boundary appeared in code without enough setup. Inspection methods had a generic explanation rather than identifying what each returns.
- Changes: explicit implementation priorities and dependency order; separate complete constructor, planner/helper, and delivery/snapshot panels under the same CashInventory heading; explain recursion and result semantics before code; explain pending-ID lifecycle and the money-operation exception boundary before withdraw; name the inspection methods and their behavior. Clarified that session cleanup follows the third rejected PIN, not every rejection. No new classes, helpers, UI widgets, state transitions, or business logic.
- Validation: regenerated Markdown and both HTML aliases. All 11 Python/Java tab pairs, local links, unique IDs, and verification nesting pass. The page checker now groups excerpts by owning class and checks exact Python AST equality with source, replacing its weaker method-count check. Reconstructed Python passed 14 tests. Reconstructed Java compiled and passed its scenario suite. Both include 540 allocation cases per language and concurrent withdrawals. Splitwise unchanged.
- Publication: the article commit is the commit containing this entry. Live deployment verification follows below.
- Deployment verified: commit `e30126bea777194886256ca4dead372711e5b6c9`, [Pages run 41774568881](https://github.com/YashPandit4u/low-level-design/actions/runs/41774568881) succeeded. Live /atm/ matches the tested HTML byte-for-byte, SHA-256 `bb3c915d764d584ff3301c3f2148bac1d4282332e8e9e5a06da21107c030a699`. Iteration 4 complete.
