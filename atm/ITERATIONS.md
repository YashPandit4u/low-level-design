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

No iterations completed yet. Append one entry per run with references actually inspected, concrete findings, changes, validation, commit and deployment status. If a comparison finds no justified change, record that honestly rather than inventing a flaw.

### Iteration 1 — first complete article (2026-11-04)

- Prerequisite: no earlier ATM article or completed iteration existed. Created the first full version rather than revising Splitwise.
- Reference actually read in Chrome: [Inventory Management](https://www.hellointerview.com/learn/low-level-design/problem-breakdowns/inventory-management#implementation). Read the class-design transition, InventoryManager constructor and operational methods, transfer Core logic/Edge cases and comparison choices, Warehouse ownership/concurrency/alert explanations, query methods, and interface sections. Inspected its actual implementation screenshot and right-side navigation. No claim of reading other articles during this pass.
- Applied reference structure: requirements dialogue and specification panel, selected entities, class-based design and implementation sections, method selection before implementation, selective Core logic/Edge cases, comparisons inside the relevant class, and verification nested within Implementation. Reused the existing Splitwise shell, styles, tabs, search, theme control, and smooth navigation without changing Splitwise.
- Concrete gaps prevented or fixed: greedy note selection falsely rejects valid bundles; automatic refunds after uncertain dispensing can give away money; balance checks alone do not reserve funds; cancellation must not reopen an uncertain ATM; snippets must include constructors and complete methods. Corrected Python 3.9 annotation compatibility after the initial test failed. Corrected tab accessibility labels that inherited the preceding comparison title.
- Delivered original article, complete Python and Java implementations, fake bank/hardware tests, an excerpt generator, HTML builder, and page/snippet checks. Pending operation IDs remain in memory only. Crash recovery, retries, partial-delivery reconciliation, and maintenance are explicitly follow-ups, not production guarantees.
- Validation: 14 Python tests passed. Java scenario tests passed. Each language checked 540 small inventory/amount combinations against exhaustive possibilities. Covered successful withdrawal, shortages, bank decline, invalid states/amounts, PIN retries, cancel/ejection, uncertain dispensing, hold/capture/release failures, and concurrent note use. Reassembled both languages from rendered HTML and ran their behavior tests successfully. Checked all local links, unique IDs, nine language-tab pairs, and verification nesting. Chrome confirmed Java tab switching and desktop layout. Detailed mobile/wide-screen comparison remains scheduled for iteration 8.
- Publication: commit for this iteration is the commit containing this entry, followed by a deployment-verification log entry. Target: /atm/. No Splitwise files changed.
