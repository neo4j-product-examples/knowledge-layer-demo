# Meridian Lending Intelligence

This is a script for you to read before you run the demo, then keep open on a second screen while you drive.

One rule holds the whole thing together: **hold off on the word "graph" until the room already trusts the answer.**  So the demo earns trust with a business answer first, and only shows the machinery once someone actually wants to know how it got there. 

Everything below maps to an actual screen in the app. Bold lines are what you say. Indented lines are what you click.

---

## Open with their world

Don't open on the app. Open on a story this room already recognizes. Show the business plan on the screen:

![Screenshot 2026-09-10 at 2.34.22 PM](/Users/corydonbaylor/Documents/github/knowledge-layer-demo/docs/walkthrough_images/1- businessplan.png)

**"Rosa's Bakery wants $400,000 to open a second location. Somewhere in your bank right now, someone is pulling her credit file, her account history, maybe an old paper application, and trying to hold all of it in their head at once. That's often how a loan decision gets made: good people, scattered systems, and a decision that's hard to reconstruct a week later."**

**"I'm going to show you Rosa's actual loan decision, made live, and exactly why it came out the way it did. Whether you agree with the recommendation or not, you'll be able to argue with it, fact by fact."**

---

## Step 1: Load the file

> Click **Upload Business Plan**.

![2 - KG](/Users/corydonbaylor/Documents/github/knowledge-layer-demo/docs/walkthrough_images/2 - KG.png)

A small cluster of circles and lines appears on the right. 

**"Earlier you saw Rosa's business plan as it was given to the bank. Now you are seeing it as a knowledge graph: the people who own the business, the company itself, the loan she's asking for. We'll come back to why it looks like that. For now, watch what happens when I ask the question you'd actually ask."**

---

## Step 2: Ask the question a loan officer would actually ask

> Click the suggested question: **"Should we approve the $400,000 term loan for Rosa's Bakery? Check it against Meridian's lending policy."**

Below the graph, in the tool call trace, a running list appears: *Finding matching Meridian customer... Pulling credit score... Checking lending policy... Checking decision history for precedent... Finding parent companies.* Each line lands as it actually finishes. None of it is a canned replay.

**"Every one of these is a real lookup happening right now, against real systems. And more pieces populate the graph as more decision points are being considered. I will walk through it in detail when we get our final answer but different data points come from different systems"**

Let it run. It takes maybe 20 seconds. Silence is fine here. People watch a live list build itself more closely than they listen to a pitch.

---

## Step 3: Let the answer make your case for you

The recommendation lands as plain text: strong credit and a clean payment history, but a decline or escalation, because a related company under the same ownership has a delinquent loan, and the requested amount doesn't hold up against Rosa's own cash flow.

**"Read the second paragraph. It names the exact policy section it checked her against, the exact number that failed, and the exact company connected to her that you'd never think to check by hand."**

**![4 - answer](/Users/corydonbaylor/Documents/github/knowledge-layer-demo/docs/walkthrough_images/4 - answer.png)**

You've just made a business point: the software caught something a manual review would likely miss, and it told you exactly how.

**If someone pushes back on the recommendation itself, good.** Let them argue with it. "You don't have to agree with the call. That's the point. You can see every fact that went into it, so you're arguing with a specific number instead of a black box."

---

## Step 4: Now, and only now, show them the picture

This is the reveal. Everything before this point built the trust to have this conversation.

**"Remember that picture from the start? Here's what it turned into while it was answering you."**

> Point to the graph pane. Every fact from the answer is now a labeled circle, connected to the ones it relates to.

**"Every circle is one fact: a credit score, a policy rule, that related company. Every line is a connection between two facts. This is the actual record of what the assistant looked at, in the order it looked at it, generated automatically while it worked. If a regulator, an auditor, or Rosa herself ever asks why you decided this, this is the honest answer."**

![](/Users/corydonbaylor/Documents/github/knowledge-layer-demo/docs/walkthrough_images/3 - waiting.png)

**"Notice the dark blue ones — that's the Banking Virtual Graph. Rosa's real transaction history still lives in the bank's own core system, exactly where it's always lived. It never moved here. See 'Transactions: 120'? That's not 120 rows copied into this graph — it's one fact standing in for a query the agent ran against the real system. Same with her credit score, her KYC status. Every one of these dark blue circles is a thin pointer, not a copy. The record of what mattered to this decision lives here; the data itself stays put."**

**"Think of it like a detective's evidence board. A spreadsheet is great at telling you what's true about one thing at a time, but terrible at telling you how two far-apart facts connect. That delinquent affiliate lived in the connection between two systems. No single system had it on its own. A spreadsheet would have needed someone to think to look there. This just looked."**

---

## Step 5: Show that it remembers

> Point to the purple nodes in the graph, labeled with a past recommendation.

**"It checked its own memory before deciding. See this? That's a similar decision Meridian made on a different loan, cited as precedent, the same way a loan committee would say 'we handled a case like this before, and here's what we did.' Every decision it makes becomes part of the record the next one gets checked against."**

**![5 - context](/Users/corydonbaylor/Documents/github/knowledge-layer-demo/docs/walkthrough_images/5 - context.png)**

This is a small moment, but it's the one that answers the unspoken question in the room: *does this thing learn, or does it just look smart once?* It compounds. Say that plainly and move on.

---

## Optional: for the person who wants to know how it actually works

Don't offer this. Wait for someone to ask "okay, but where does all this data actually live" or "did you have to copy everything into one place to do this." 

> Click **View Ontology** at the bottom of the screen.

**"Short answer: no, nothing moved. This is a map of the five places this information actually lives: the bank's own systems, the business plan, the lending policy manual, the decision history, and a small connector layer that links matches between the first two. Every one of those stays exactly where it already is, owned by whoever already owns it. It's a map, nothing more."![6 - ontology](/Users/corydonbaylor/Documents/github/knowledge-layer-demo/docs/walkthrough_images/6 - ontology.png)**

This line usually shifts IT and compliance from worry to useful questions. Say it, let them explore the map for thirty seconds, then move on. Don't turn this into a second demo.

---

## Land it

Close on the business point:

**"Rosa got an answer the same day instead of weeks later. The bank caught a risk a spreadsheet would have missed. Every person downstream of this decision, the loan officer, the auditor, Rosa herself, got the same honest answer to 'why.' The graph is how we kept that promise."**

Stop there. Don't add a slide. Let the room ask the next question.

