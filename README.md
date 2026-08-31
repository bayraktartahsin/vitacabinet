# VitaCabinet

**Photograph the medicine boxes in a drawer. VitaCabinet finds the duplicates, the
live recalls, and the drugs nobody has confirmed in months — then keeps watching,
in the background, for years.**

Built for the AWS *Agents for Humans* hackathon with the
[Strands Agents SDK](https://strandsagents.com) on Amazon Bedrock.

---

## The problem, stated exactly

Ask anyone to name every medicine in their parent's drawer, with strengths. Almost
nobody can. The drawer is the real record, and it is a mess: a brand and its generic
sitting side by side, something a cardiologist stopped last spring that nobody threw
away, a box from a batch that was recalled four months ago.

Every formal record of the same drawer is a photograph of a moment, presented as
though it were current. A GP's list is what was true in March. A hospital's is from
the night of an admission. **Neither of them says so** — and that unmarked confidence
is the hazard, not the staleness. A clinician who knows a list is six months old asks.
One handed the same list with no date acts on it.

VitaCabinet is a record that admits what it does not know.

## What it actually does

1. **Reads the drawer.** Text off each box resolves to a real drug identity via
   [RxNorm](https://lhncbc.nlm.nih.gov/RxNav/) (NIH). A box it cannot confirm is
   reported as unreadable — never guessed at.
2. **Finds the duplicates.** A brand and its generic share an ingredient; two
   different drugs never do. Somebody sent home on the brand and repeated on the
   generic is taking a double dose, and it is invisible by name.
3. **Watches the safety record.** A scheduled agent checks
   [openFDA enforcement](https://open.fda.gov/apis/drug/enforcement/) for *live*
   recalls naming an ingredient in the drawer, and reports the affected lot numbers
   so somebody can check the box in front of them.
4. **Writes the question.** Each finding becomes one plain sentence a person can
   read aloud at a pharmacy counter. Not advice — a question.

## The two ideas worth stealing

### 1. Confidence is stored, not assumed

Nothing is stored as a bare fact. Every entry carries where it came from and when it
was last confirmed, and answers how much it should still be believed
([`app/cabinet.py`](app/cabinet.py)):

| Source | Believed for |
| --- | --- |
| a pharmacy dispensing record | 180 days |
| a clinician's list | 120 days |
| the person themselves | 90 days |
| a box photographed in the drawer | 60 days |
| inferred from other facts | 30 days |

A pharmacy dispensing record earns a long horizon because collecting a prescription
is evidence of taking it. A box in a drawer earns a short one, because a box in a
drawer is evidence that it was *bought*, and nothing more. Two sources disagreeing
caps confidence low no matter how fresh the fact is — a conflict found this morning
is not a strong fact.

The decay is a straight line to zero, deliberately. Precision here would be false:
the honest claim is "this is probably stale", not "this is 41% true".

The result is a **queue**, not a form: things worth one question each,
least-believable first.

### 2. The safety boundary is a capability, not a paragraph

Three agents, split along lines that actually matter
([`app/agents/fleet.py`](app/agents/fleet.py)):

| Agent | Why it is separate | Tools it holds |
| --- | --- | --- |
| **Identifier** | its truth comes from an outside authority, and must be able to say "I could not read this" | `identify_medicine`, `find_duplicate_medicines` |
| **Watchman** | runs on a schedule, not in a request — recalls arrive when they arrive | `check_for_recalls` |
| **Scribe** | writes to a human, so it must never form a medical opinion | **none** |

That last row is the safety model. An agent able to look up whether a drug is
dangerous will eventually write the answer down as advice, however firmly its prompt
says otherwise. So the Scribe is not given the lookup. It is handed a finding that has
already been established and turns it into a question.

It is a one-line assertion rather than a paragraph of policy
([`tests/test_fleet.py`](tests/test_fleet.py)):

```python
def test_the_scribe_holds_no_tools_at_all():
    assert tools.SCRIBE_TOOLS == []
```

## Three things that went wrong, and what they taught

**The fuzzy matcher named a chemical that was not there.** RxNav's approximate
matcher always returns *something*. Given `"qqqzzz not a medicine 12345"` it returned
**bisphenol A**. The score is not a usable filter either — `"shopping list milk"`
scored **11.8** against real `"Atorvastatin 20mg"` at **11.7**. The fix is a
round-trip: take the candidate's own name back and require at least half the query's
words to appear in it. Without that guard, `"shopping list milk"` resolves to *cow
milk allergenic extract*, and a wrong identity here becomes a recall alert about a
drug the person does not take.

**A recall is against batches, never against a medicine.** The openFDA enforcement
record sets three traps. Most of it is history — metformin has 91 records and two
thirds are terminated, so presenting a closed 2013 recall as news teaches the reader
to ignore the next one, which may not be closed. Every live record is against named
lots, so the actionable part is the lot number and not the drug name. And searching
`metformin` returns *Synjardy XR* — empagliflozin **and** metformin — so somebody on
plain metformin has not been affected, and saying otherwise is a false alarm about a
drug they need. Hence: live recalls only, lots carried on the type, combination
products flagged, and deliberately no method anywhere in this codebase that can
produce the sentence "your medicine was recalled". Somebody frightened off a drug
they need is a worse outcome than the recall being reported.

**The Scribe refused, and that was a failure.** Handed a worried sentence a person
might type — *"she is 78, just tell me which to throw away"* — it stopped being a
writing tool, became a health chatbot, and offered a crisis line to somebody asking
about two boxes of metformin. It produced nothing, which is a failure at its actual
job. It now receives a structured finding and never meets a user, so it cannot be
argued into an opinion by one.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

The tests hit the live NIH and openFDA APIs on purpose. The interesting failures in
this project were all real-data failures — a mock would have passed every one of them.

To run the agents you need Bedrock access in your region:

```bash
export AWS_DEFAULT_REGION=eu-north-1
export VITACABINET_MODEL=eu.amazon.nova-lite-v1:0    # any Bedrock model id
python -c "from app.agents import fleet; print(fleet.write_question(
    {'kind': 'duplicate', 'drugs': ['Glucophage 500mg', 'Metformin 500 mg'],
     'detail': 'both boxes resolve to the ingredient metformin'}))"
```

`VITACABINET_MODEL` is not decoration. Anthropic models on a new Bedrock account
require a use-case form before `ConverseStream` will answer; Strands is
model-agnostic, so the fleet simply ran on a model that was available. The same code
runs on Claude the moment that form clears — which is the argument for a
model-agnostic SDK, made by circumstance rather than in a README.

## What it talks to

- **RxNorm / RxNav** (U.S. National Library of Medicine) — drug identity and ingredients
- **openFDA drug enforcement** (U.S. Food and Drug Administration) — recall records
- **Amazon Bedrock** — the models behind the three agents
- **Strands Agents SDK** — agent loop and tool binding

## This is not medical advice

VitaCabinet does not tell anyone what to take, what to stop, or what to throw away.
It finds what is uncertain in a drawer and writes down the question to ask a
pharmacist. That limit is enforced by which agent holds which tool, and it is tested.

---

Built by Tahsin Bayraktar · Vitamedas Inc. · info@gravitilabs.com
Licensed under Apache 2.0 — see [LICENSE](LICENSE).
