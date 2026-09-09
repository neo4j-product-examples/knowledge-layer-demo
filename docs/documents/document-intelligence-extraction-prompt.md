# Document Intelligence extraction prompt — Rosa's Bakery business plan

Purpose: ingest `docs/documents/rosas-bakery-business-plan.md` into a knowledge graph with the specific node/relationship properties the entity-resolution step (see `HANDOFF.md` section 7) needs — not just default generic NER. Use this with whatever Document Intelligence / LLM Knowledge Graph Builder tool is doing the extraction.

## Schema (nodes, properties, relationships)

Give this schema to the tool if it accepts a structured schema definition separately from free-text instructions:

**Node: `Person`**
- `name` (string)
- `role` (string) — e.g. "Founder & CEO", "Co-owner"
- `ownership_pct` (float) — only if an ownership percentage is explicitly stated for this person

**Node: `Organization`**
- `name` (string)
- `address` (string)
- `ein` (string)
- `industry` (string)
- `foundedDate` (string, `YYYY-MM`) — only if a founding date is explicitly stated
- `bankingRelationshipSince` (string, `YYYY-MM`) — only if the document states how long the business has banked with the lender
- `bankingBranch` (string) — only if a specific branch is named

**Relationship: `(Person)-[:OWNS {pct, role}]->(Organization)`**
- `pct` (float)
- `role` (string)

This mirrors the native Neo4j shape already used for the canonical ownership data (`(:Person)-[:OWNS {pct, role}]->(:Customer)` — see `data/README.md`), so resolution can eventually compare whole `Person-OWNS->Organization` patterns against the canonical `Person-OWNS->Customer` patterns, not just isolated node properties.

**Node: `LoanRequest`** — the business's own stated ask, separate from (but expected to be checked against) the bank's own formal loan-application record.
- `requestedAmount` (float)
- `termYears` (integer)
- `rateType` (string) — e.g. "Fixed", "Variable"
- `applicationId` (string) — only if the document references a specific application/facility id
- `purpose` (string) — a concise statement of what the loan is for
- `useOfProceeds` (string) — a plain-text summary of how the funds break down by category; capture the categories and amounts stated, don't invent a breakdown that isn't in the document
- `marketRationale` (string) — the business's own stated case for why this financing makes sense now (demand evidence, capacity constraints, growth opportunity)
- `repaymentRationale` (string) — the business's own stated case for why it can repay (projected breakeven, existing track record, cash flow stability)

**Relationship: `(Organization)-[:REQUESTS]->(LoanRequest)`**

This is loan-decision context, not identity data — it doesn't feed entity resolution (§5.1) the way Person/Organization/OWNS does. It exists so the lending agent can weigh the business's own account of the loan against the bank's own systems (the formal application, transaction history, credit score) rather than deciding from banking data alone.

## Extraction instructions (paste as the free-text prompt)

```
Extract every Person, Organization, and LoanRequest explicitly mentioned
in this document.

For each Person:
- Capture their full name exactly as written in the document. Do not
  normalize, reorder, abbreviate, or correct it in any way.
- Capture their stated role or title exactly as written.
- If an ownership percentage is stated for them, capture it as a numeric
  ownership_pct property (e.g. 70, not "70%" or "70 percent"). If no
  percentage is stated for a person, leave ownership_pct unset.

For each Organization:
- Capture its name exactly as written.
- Capture its full address as a single string, exactly as written in the
  document. Do not reformat, abbreviate, or standardize it.
- Capture its EIN exactly as written (format XX-XXXXXXX) if present.
- Capture its industry only if explicitly described in the text — do not
  infer an industry from the business name or activities.
- Capture foundedDate, bankingRelationshipSince, and bankingBranch only if
  explicitly stated (e.g. "banked with [Lender] since July 2020" ->
  bankingRelationshipSince "2020-07").

For each Person who is described as owning or co-owning an Organization,
create an OWNS relationship from that Person to that Organization, with
pct and role properties matching what is stated in the text.

If the document states a loan request or facility the Organization is
seeking (an amount, term, purpose, use of proceeds, or repayment
rationale), extract one LoanRequest node capturing:
- requestedAmount, termYears, rateType, and applicationId, if stated.
- purpose: a concise statement of what the financing is for.
- useOfProceeds: a plain-text summary of the funding breakdown as stated
  (categories and amounts) -- do not invent a breakdown not in the text.
- marketRationale: the business's own stated case for why this financing
  makes sense now.
- repaymentRationale: the business's own stated case for its ability to
  repay.
Create a REQUESTS relationship from the Organization to the LoanRequest.

Do not infer, guess, or add any property value that is not explicitly
stated in the document. Leave a property unset rather than estimating it.
Do not create relationships between entities based on assumed connections
outside this document — only what the text directly states.
```

## Why the "exact, don't normalize" instructions matter

The entity-resolution step scores signals like address match and EIN match against the structured banking data in `data/snowflake/customers.csv`. If the extraction step "cleans up" an address or reformats a name during ingestion, the string-similarity score against the canonical record drops for no real reason — the fuzzy match should fail or succeed based on genuine ambiguity, not on inconsistent normalization introduced by the extraction step itself.
