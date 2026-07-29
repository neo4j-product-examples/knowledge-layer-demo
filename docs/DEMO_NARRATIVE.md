# The Knowledge Layer Demo — Story Arc & Talk Track

### "Show me how you decided."

---

## The premise everyone in the room has lived

You apply for a loan. Weeks go by. You get a yes or a no — and no real reason. Somewhere inside the bank, a person quietly pulled data from half a dozen systems, stitched it together by hand, and formed a judgment nobody can fully reconstruct later. That is how most lending decisions still get made.

This demo is about changing the second half of that sentence: not *what* the bank decides, but **how the decision gets made — and whether anyone can explain it.**

**The applicant:** Rosa's Bakery, a small business applying to Meridian Bank for a $400K loan to open a second location. Relatable enough that everyone roots for Rosa; rich enough that the bank has to actually think.

**The protagonist:** Meridian's loan-processing agent.

**The question — and the point of the whole demo:**

> "Here's the recommendation on Rosa's loan. Now show me exactly how you got there — every fact, every source, every step."

We are deliberately NOT making this about approve vs. decline. The audience will argue with a verdict. Nobody argues with a clearly-shown reasoning path. **The hero of this demo is the explanation, not the answer.**

---

## The five systems behind Rosa's application

Every system maps to something a normal person understands — no risk jargon.

| System | In plain terms | Backend |
| :---- | :---- | :---- |
| Core banking | Rosa's existing accounts & history with the bank | Snowflake (system of record, must not move) |
| Loan / credit | Her current facilities \+ this new application | Snowflake |
| Compliance | Her KYC status \+ the bank's actual lending policies (PDFs) | Snowflake \+ documents |
| Ownership / hierarchy | Who owns Rosa's Bakery, and what *else* those owners are tied to | Neo4j (natively a graph) |
| CRM | Whether anyone at the bank already covers this relationship | Neo4j (natively a graph) |

Above all five: the **Knowledge Layer** — the ontology plus descriptions and pointers into each source. It copies none of their data. It is a map, not a vault.

---

## The spine of the story: three properties, three outcomes

The Knowledge Layer makes enterprise AI **accurate, explainable, and governable.** Those are properties — and nobody buys properties. So each one has to visibly cash out into an outcome that the bank pays for. The demo shows the property AND the payoff.

| Property | Shown by | Business outcome |
| :---- | :---- | :---- |
| **Accurate** | The agent sees a fact that lives only in the *connections* between systems | Better decisions — right calls, fewer surprises |
| **Explainable** | The reasoning path IS the customer's explanation, produced instantly | Faster decisions, lower complaint/appeal cost, compliance by default |
| **Governable** | A human approves from the provenance graph in seconds | Weeks → minutes; audit-ready; cost-to-serve down |

The throughline to say out loud:

> "The same Knowledge Layer that makes this agent accurate, explainable, and governable is what turns a three-week, opaque, expensive loan decision into a same-day one you can stand behind."

---

## BEAT 1 — The old way (the problem everyone recognizes)

**On screen:** The conventional agent — all the bank's data dumped into a vector store. Ask it about Rosa's loan. It produces a fluent recommendation and a paragraph of reasoning that *sounds* thorough. Then reveal what it couldn't see.

**Talk track:**

> "This is the agent most banks are building today — all their data in a vector database, standard RAG. Ask it about Rosa's loan and it gives you an answer with confident-sounding reasoning. The problem isn't that it's rude or slow. The problem is you can't tell what it actually looked at, and — as we're about to see — it missed something that changes everything. It retrieved documents that mention Rosa. It never followed the connections between them."

**Why it lands:** Everyone recognizes "a confident answer you can't check." You've set up explainability as the thing that's missing, before naming it.

Action Items

- [Mike Worthington](mailto:michael.worthington@neo4j.com) can you build out a story beat where an algorithm behaves like a black box around loan decisions

---

## BEAT 2 — Discovery (the layer shows its work before it works)

**On screen:** Turn on the Knowledge Layer. The agent's first move is to ask the KL *what exists* — five data products appear, each described, each a pointer to a source. 

Emphasize: Due to Virtual Graph, Rosa's account data never left core banking. And with Document Intelligence, Rosa’s business plan and the banks lending policies can be queried as a knowledge graph. 

**Talk track:**

> "With the Knowledge Layer on, watch the first thing the agent does. It doesn't guess — it discovers what data exists, what each system means, and how to reach it. And nothing moved. The layer holds descriptions and pointers. Rosa's records stay in the systems that own them. For a bank, that's the difference between a project that ships and one that dies in the security review."

**Why it lands:** The governance beat. "Data doesn't move" answers the first objection every regulated buyer has. And you've shown the agent's process is inspectable from step one.

Action Items

- Virtual Graph & DocIntel (Corydon)  
  - Load in dummy banking data into Snowflake and create virtual graph from said data. This data represents the bank’s current data layer and **we must demonstrate that they do not need to disrupt** this current layer to create a working knowledge layer  
  - Create lending policy documents and Rosa’s business plan, and create knowedge graphs from them using DocIntel  
- Native Graph databases (steggy)

---

## BEAT 3 — The connected fact (ACCURATE → better decisions)

**On screen:** The agent traverses the ownership graph: Rosa's Bakery → its owners → what *else* those owners are connected to → and over into the loan system, where one of those connected entities is already behind on a facility with the bank. That fact exists in NO single system — only in the join between the ownership graph and the credit system. Show the traversal happening.

**Talk track:**

> "Now watch it follow the connections. Rosa's Bakery — who owns it — and what else those owners are tied to. One of those connected businesses is already behind on a loan with this same bank. No single system knew that. Core banking has Rosa's accounts. The loan system has the delinquency. Only by connecting them does the fact appear. This is what flat retrieval structurally cannot do — and it's exactly the kind of thing that turns a good-looking loan into a loss. Accuracy here isn't a nicer answer. It's the bad decision you didn't make."

**Why it lands:** The "accurate → better decision" payoff, made concrete and visual. The audience sees a real fact emerge from connections, not from a document.

---

## BEAT 4 — The explanation (EXPLAINABLE → faster, cheaper, compliant)

**On screen:** THE hero beat. The agent renders the full reasoning path as a decision-trace graph in Bloom — every fact, every source, every hop — and then turns that same graph into a plain-language explanation: "This decision rests on Rosa's strong 6-year history (core banking), her current facilities (loan system), her KYC status (compliance), and one connected entity's delinquency (ownership \+ loan systems)." Every clause links back to its source.

**Talk track:**

> "This is the heart of it. Everything the agent did — every fact, every source, every step — is captured as a graph. And that same graph becomes the explanation. Not 'computer says no.' A sourced, plain-language account of exactly how the decision was reached. Think about what that's worth. When you have to tell Rosa why — legally, you often must — it's already written, and it's true. When your auditor asks how the agent decided, you show them the path. When your loan officer reviews it, they're checking a trail, not redoing the work. One artifact: the customer's answer, the compliance record, and the audit trail. That's why the three-week decision becomes a same-day one."

**Why it lands:** This is where explainability stops being a virtue and becomes money — faster cycle time, lower complaint cost, adverse-action compliance for free. Because you framed the whole demo as "show me how you decided," this beat is the climax, not a footnote.

---

## BEAT 5 — The human in control (GOVERNABLE → weeks to minutes)

**On screen:** The loan officer reviews the provenance graph and approves the agent's recommendation — in seconds, because they can see and trust every step, instead of re-pulling all five systems by hand.

**Talk track:**

> "And here's what makes it real in production. The officer doesn't take the agent's word for it — and doesn't have to redo the analysis either. They read the trail, they see it holds, they approve. The work that used to take weeks of manual cross-system checking takes minutes, and it's defensible. Governance isn't the thing that slows the agent down. It's the thing that lets you actually use it."

**Why it lands:** Governability reframed as the *enabler* of cost savings, not a tax on them. An agent nobody trusts gets re-checked by hand and saves nothing; a governable one collapses the cycle time.

---

## BEAT 6 — Learning from use (optional / roadmap)

**On screen:** An analyst corrects one ownership mapping; the Knowledge Layer learns it once, for every future application.

**Talk track:**

> "And it compounds. Correct one mapping, once, and every future decision inherits it. Living infrastructure, not a catalog you re-import every quarter."

**Caution:** Least-built, easiest-to-fake beat. Show live only if it genuinely works; otherwise state it as roadmap. Don't let a shaky Beat 6 undercut a clean Beat 4\.

---

## The "so what" slide (in their language, not ours)

- **Rosa got a same-day answer** — and a real reason. (Customer experience)  
- **The bank avoided a bad loan** it literally could not see before. (Reduced risk)  
- **The officer's weeks of manual work became minutes.** (Reduced cost)  
- **Every decision is audit-ready by default.** (Compliance)  
- **Rosa's data never moved, and the bank owns the ontology.** (Governance \+ IP)

## On-screen checklist for whoever builds it

- [ ] Old-way answer vs. Knowledge-Layer answer, side by side  
- [ ] The five discovered data products (pointers, not copies)  
- [ ] The ownership-graph traversal surfacing the connected delinquency  
- [ ] The decision-trace / reasoning graph in Bloom  
- [ ] That same trace rendered as a plain-language, sourced explanation  
- [ ] The agent reaching sources over MCP — no bespoke integration on screen

## Two framing cautions (from internal strategy threads)

- **Don't oversell it as a product.** Internally the KL is still a *pattern on the platform*, not a shippable SKU. Show a working capability — infra \+ NeoCarta \+ a little services glue — not a finished box.  
- **Show how you'd buy it.** Keep the three-pillar packaging visible — infrastructure / NeoCarta software / expert services — because these are ELA-scale strategic engagements, not use-case sales.

## The one line to leave them with

> "Every bank can tell you *what* it decided. The Knowledge Layer lets you show *how* — for every customer, every time, in plain language you can stand behind."  
