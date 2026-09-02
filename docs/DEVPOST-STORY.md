## The drawer is the real record

Ask anyone to name every medicine in their mother's drawer, with strengths. Almost nobody can. I couldn't.

The drawer is the record that actually governs what somebody swallows, and it is a mess: a brand and its generic side by side because the hospital sent her home on one and the GP repeated the other, something a cardiologist stopped last spring that nobody threw away, a box from a batch that was recalled four months ago and never came up because nobody was looking.

Every formal record of that same drawer is a photograph of a moment, presented as though it were current. A GP's list is what was true in March. **Neither says so** — and that unmarked confidence is the hazard, not the staleness. A clinician who knows a list is six months old asks a question. One handed the same list with no date acts on it.

VitaCabinet is a record that admits what it does not know, and three agents that keep reducing what it is unsure about — in the background, for as long as the drawer exists.

**Live: https://b5emjsgbi1.execute-api.eu-north-1.amazonaws.com** — no install, no sign-up.

## What it does, in the order you see it

1. **Photograph the boxes.** Amazon Nova Lite reads the printed name and strength off each one. It *reads*; it does not identify.
2. **The Identifier reads the drawer** — a Strands agent calling `identify_medicine` once per box against RxNorm (NIH), then `find_duplicate_medicines` across all of them. A box it cannot confirm is reported as unreadable, never guessed.
3. **The Watchman checks the safety record** — a second agent calling `check_for_recalls` once per ingredient against openFDA. Live recalls only, lot numbers carried, combination products flagged.
4. **You watch them work.** Every tool call is written to the job as it happens and drawn on the page while the agents are still running — tool, argument, what it said back, how long it took.
5. **Keep the drawer.** Facts persist in DynamoDB with their source and age, and decay. A box in a drawer is believed for 60 days; confirming a fact moves it to the person and resets it.
6. **It keeps watching.** EventBridge runs the Watchman nightly over every kept drawer. SNS emails only when something is *new*.
7. **The Scribe writes the question.** One sentence per finding, for a pharmacist. It holds no tools.

## How it is built

**Strands Agents SDK** — three agents, three tools, a hook that records every tool call. **Amazon Bedrock AgentCore Runtime** hosts the fleet (ARM64 container built by CodeBuild; the runtime writes the trace to DynamoDB itself). **AWS Lambda + API Gateway** is the web tier: a reading is an asynchronous job, because the gateway gives a request thirty seconds and two agents want more. **DynamoDB** holds jobs and kept drawers; **EventBridge** runs the nightly pass; **SNS** speaks only when there is news. **Nova Lite** is the model throughout, including reading photographed labels.

## The two ideas I'd defend

**Confidence is stored, not assumed.** Every fact carries where it came from and when it was last confirmed. A pharmacy dispensing record is believed for 180 days, because collecting a prescription is evidence of taking it. A box in a drawer gets 60, because a box is evidence it was bought and nothing more. Two sources disagreeing caps confidence low however fresh the fact is. What falls out is a queue — things worth one question each, least believable first — which is the shape a background agent can work through for years.

**The safety boundary is a capability, not a paragraph.** The Scribe writes to a human, so it must never form a medical opinion. It is not told not to; it *cannot*. It holds no tools:

```python
def test_the_scribe_holds_no_tools_at_all():
    assert tools.SCRIBE_TOOLS == []
```

An agent that can look up whether a drug is dangerous will eventually write that down as advice, however firmly its prompt says otherwise. So it does not get the lookup.

## What went wrong, and what it taught

**The model drowned in its own tool results.** `check_for_recalls` returned the openFDA payload; amlodipine has thirteen live recalls; the Watchman blew straight through Nova's output budget. Now every tool tells the model one sentence and writes the full structured result to a per-reading ledger the app assembles findings from. The model orchestrates; the data never passes through it.

**The model rewrote its own arguments.** Nova normalised `Glucophage 500mg` into `metformin hydrochloride 500 mg` before passing the boxes to `find_duplicate_medicines`, and the one pair this project exists to find collapsed into a single entry. Duplicates are now recomputed from the ledger after the agent finishes, regardless of what it passed. Findings come from tool results, never from the model's prose.

**The fuzzy matcher named a chemical that wasn't there.** RxNav's approximate endpoint returned *bisphenol A* for `qqqzzz not a medicine 12345`, and `shopping list milk` scored above a real atorvastatin box. A round-trip name check — half the query's words must appear in the candidate's own name — is what holds.

**A recall is against batches, never a medicine.** Two thirds of metformin's records are terminated; every live one names lots; half are combination products. There is deliberately no code path that can produce the sentence "your medicine was recalled."

**The Scribe refused, and that was the failure.** Handed a person's own words — *"she is 78, just tell me which to throw away"* — it became a health chatbot and offered a crisis line to somebody asking about two boxes of metformin. It now receives a structured finding and never meets a user.

**A leak that only showed in one test order.** The ledger was a ContextVar; Strands' concurrent tool executor runs tools on pool threads; a pool thread that once made its own ledger kept it. A locked module global is less elegant and correct.

## What's next

The queue is what generalises. A drawer is one source; a discharge summary, a pharmacy record and a person's memory are three more, and they disagree constantly. A record that carries its own confidence is the only kind that can hold four disagreeing sources without pretending one of them is the truth.

**VitaCabinet never tells anyone what to take, what to stop, or what to throw away.** It finds what is uncertain, keeps watching, and writes down the question to ask a pharmacist. That limit is a capability boundary, and it is tested — 65 tests, all against the live models and public APIs.
