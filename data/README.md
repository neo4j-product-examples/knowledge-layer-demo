# Demo data — Rosa's Bakery / Meridian Bank

Synthetic dataset supporting Beats 2 and 3 of the Knowledge Layer demo (see `../docs/DEMO_NARRATIVE.md`). Modeled as a small but structurally realistic slice of what a bank's core banking + loan/credit warehouse looks like in Snowflake, plus the ownership data that's natively a graph in Neo4j.

## Where each table goes

**`snowflake/`** — loads into Snowflake as-is (system of record for core banking and loan/credit). Neo4j's Virtual Graph maps nodes and relationships over these tables without copying data.

| File | Rows | Represents | Suggested Virtual Graph mapping |
| :---- | :---- | :---- | :---- |
| `customers.csv` | 80 | Business customer master | `(:Customer {customer_id})` |
| `accounts.csv` | 104 | Deposit accounts (checking/savings/money market) | `(:Account)-[:HELD_BY]->(:Customer)` |
| `account_transactions.csv` | 5,911 | Trailing ~24 months of deposit/withdrawal/card/fee activity | `(:Transaction)-[:POSTED_TO]->(:Account)` |
| `kyc_status.csv` | 80 | Compliance/KYC status per customer | properties on `:Customer`, or `(:Customer)-[:HAS_KYC]->(:KYCRecord)` |
| `loan_facilities.csv` | 52 | Existing loan/credit facilities | `(:Facility)-[:ISSUED_TO]->(:Customer)` |
| `payment_history.csv` | 1,070 | Monthly scheduled vs. actual payments per facility | `(:Payment)-[:APPLIED_TO]->(:Facility)` |
| `credit_score_history.csv` | 960 | Quarterly credit score per customer, trailing 3 years | `(:CreditScore)-[:SCORED]->(:Customer)` |
| `loan_applications.csv` | 15 | Rosa's new $400K application + other filler applications | `(:Application)-[:SUBMITTED_BY]->(:Customer)` |
| `branches.csv` | 5 | Branch reference data | `(:Branch {branch_id})` |
| `employees.csv` | 10 | Relationship managers / loan officers / branch managers | `(:Employee)-[:WORKS_AT]->(:Branch)` |
| `industry_codes.csv` | 16 | Industry lookup | `(:Industry {industry_code})` |
| `product_types.csv` | 8 | Deposit & loan product lookup | `(:ProductType {product_type_code})` |

`customers.csv` also carries a self-referencing `parent_customer_id` column (see "Corporate hierarchy" below), which Virtual Graph maps as `(:Customer)-[:REPORTS_TO]->(:Customer)`, plus a `customer_seq_id` numeric surrogate key required for GDS support (see below).

**`ownership-seed/`** — per the narrative, ownership/hierarchy is natively a graph in Neo4j, not Snowflake. These CSVs are the raw facts to load directly into Neo4j (not via Virtual Graph), using `customer_id` and `owner_id` values that match the Snowflake tables above so the two graphs join cleanly.

| File | Rows | Represents | Native Neo4j shape |
| :---- | :---- | :---- | :---- |
| `owners.csv` | 84 | Individual owners | `(:Person {owner_id})` |
| `ownership.csv` | 90 | Who owns what, and how much | `(:Person)-[:OWNS {pct, role}]->(:Customer)` |

## The story encoded in the data

Rosa's Bakery (`C001`) is owned 70% by Rosa Alvarez (`O001`) and 30% by Marcus Alvarez (`O002`). Marcus Alvarez also owns 100% of Alvarez Distribution Co (`C002`), which is currently delinquent on `LOC-2002` (62 days past due, last 2 payment cycles missed — see `payment_history.csv`). Alvarez Distribution's credit score has also been trending down in `credit_score_history.csv`, consistent with the delinquency.

That delinquency is invisible to any single system:
- Core banking (`customers.csv`, `accounts.csv`, `account_transactions.csv`) only shows Rosa's Bakery looks healthy — 6 years of relationship history, solid balances.
- The loan system (`loan_facilities.csv`, `payment_history.csv`) shows a facility called `LOC-2002` is delinquent, but has no idea that account belongs to someone connected to Rosa's Bakery.
- Only traversing `Rosa's Bakery -> Marcus Alvarez -> Alvarez Distribution Co -> LOC-2002` (crossing from the ownership graph into the loan system) surfaces the connected risk. That traversal is Beat 3.

Two other, unrelated delinquencies exist in the dataset (`C006`, `C033`), so "find the delinquent facility" isn't a giveaway — the agent has to follow the specific ownership path to find the one that's actually connected to Rosa's application.

## Corporate hierarchy: a reason to use Virtual Graph over plain SQL on Snowflake

The ownership mechanic above lives outside Snowflake entirely, in native Neo4j — so by itself it's not a reason to put a Virtual Graph *over Snowflake*, only a reason Neo4j exists at all. `customers.csv` adds a second, independent hidden connection that sits entirely inside Snowflake, to make that case directly.

Three holding-company rows were added: `C081` (Cedarville Investment Group, top of the structure), `C082` (Alvarez Family Holdings LLC, parent `C081`), and `C083` (Alvarez Logistics Holdings LLC, parent `C081`). Rosa's Bakery (`C001`) and Alvarez Distribution Co (`C002`) were each given a `parent_customer_id` pointing at one of the two subsidiaries:

```
C001 (Rosa's Bakery) --> C082 --> C081 <-- C083 <-- C002 (Alvarez Distribution Co)
```

They share a common ultimate parent three hops up — a self-referencing foreign key inside a single Snowflake table.

**Correction from an earlier version of this doc:** the first draft of this section claimed a variable-length Cypher pattern (`-[:REPORTS_TO*1..5]->`) could resolve this hierarchy in one line while SQL needed a purpose-built recursive CTE, and pitched that gap as the reason to use Virtual Graph. That's wrong — Neo4j's own docs state variable-length paths are **not currently supported** in Virtual Graph's Cypher coverage (https://neo4j.com/docs/virtual-graph/aura/cypher-coverage/). A fixed-depth Cypher pattern and a fixed-depth SQL join (or a recursive CTE) are equally capable here — neither is a genuine capability gap. `patch_live_snowflake.sql` still demonstrates this fixed-depth chain (a 1/2-hop self-join returns 0 rows, a recursive CTE finds the shared parent `C081` at depth 2) as a useful illustration, but not as proof of a SQL-can't-do-this claim.

**The real, docs-confirmed capability gap is Graph Data Science (GDS).** Virtual Graph supports running GDS algorithms — PageRank, Louvain community detection, Weakly Connected Components, betweenness centrality, and 60+ others — directly against Snowflake data via a Cypher graph projection, with no data copy (https://neo4j.com/docs/virtual-graph/aura/gds/). These are iterative/heuristic graph computations (eigenvector-style power iteration for PageRank, modularity-optimizing local moves for Louvain), not joins or bounded recursion — there is no practical plain-SQL equivalent, recursive CTE or otherwise.

This is why `customers.csv` also has a `customer_seq_id` column: GDS requires a single, non-composite, unique unsigned-integer ID on every node table it projects, and `customer_id` (`"C001"`) doesn't qualify.

Demo framing that fits the corporate-hierarchy data already in place — a connected-borrower concentration check, which is a real banking/regulatory concern (aggregate credit exposure across related legal entities, akin to FinCEN beneficial-ownership aggregation):

```cypher
MATCH (a:Customer)-[r:REPORTS_TO]->(b:Customer)
WITH gds.graph.project('corpFamily', a, b) AS g
CALL gds.wcc.stream('corpFamily')
YIELD nodeId, componentId
RETURN gds.util.asNode(nodeId).customer_id AS customer_id, componentId
```

Weakly Connected Components groups every customer by corporate family in one call — Rosa's Bakery and Alvarez Distribution Co land in the same component — which a bank could then join back to `loan_facilities.current_balance` to sum exposure per family and check it against a concentration limit. (Exact GDS-session Cypher syntax should be verified against a live Virtual Graph instance before using in a live demo — this is illustrative of the documented mechanism, not a tested query.)

## Realism / scale notes

- 83 customers total: 2 fixed story customers (Rosa's Bakery, Alvarez Distribution Co) + 78 generated filler businesses across 15 industries, 5 branches, and 10 employees, + 3 holding-company entities (`C081`-`C083`) that carry the corporate-hierarchy mechanic above.
- Deposit accounts carry ~24 months of transaction history (5,911 rows) rather than just a balance.
- Loan facilities (52, spread across ~65% of customers) carry monthly payment history (1,070 rows) showing the payment pattern behind each `payment_status`, not just a flag.
- Credit scores are tracked quarterly for 3 years per customer (960 rows), with Alvarez Distribution's score trending down and Rosa's Bakery's trending up.
- Ownership isn't 1:1 either: a handful of "serial owners" hold stakes in two unrelated filler businesses each, and some businesses have two co-owners — so a shared owner across businesses isn't by itself a red flag; only the specific Marcus Alvarez path resolves to a real, connected risk.
- All identifiers (`customer_id`, `owner_id`, `facility_id`, etc.) are consistent across every file for clean joins/graph mapping.
- Dates are anchored to a July 2026 demo date. Generated with a fixed random seed (`generate_data.py`, not included in this folder) so the dataset is reproducible.

Lending policy PDFs and Rosa's business plan (for Document Intelligence / compliance) are a separate deliverable, not included here.
