## The drawer is the real record

Ask anyone to name every medicine in their mother's drawer, with strengths. Almost nobody can. I couldn't.

The drawer is the record that actually governs what somebody swallows, and it is a mess: a brand and its generic sitting side by side because the hospital sent her home on one and the GP repeated the other, something a cardiologist stopped last spring that nobody threw away, a box from a batch that was recalled four months ago and never came up because nobody was looking.

Every formal record of that same drawer is a photograph of a moment, presented as though it were current. A GP's list is what was true in March. A hospital's is from the night of an admission. **Neither of them says so** — and that unmarked confidence is the hazard, not the staleness itself. A clinician who knows a list is six months old asks a question. One handed the same list with no date acts on it.

VitaCabinet is a record that admits what it does not know.

## What it does

Photograph the boxes. VitaCabinet resolves each one to a real drug identity against RxNorm (NIH), finds the boxes that are the same medicine under two different names, checks the FDA enforcement record for live recalls naming those ingredients, and writes one plain question per finding that somebody can read aloud at a pharmacy counter.

Then it keeps doing it. The recall check is not a button — it runs on a schedule, because recalls arrive when they arrive and nothing about them is triggered by somebody remembering to open an app. That background half is the actual product. The screen is just where you go to see what it found.

## Two ideas I'd defend

**1. Confidence is stored, not assumed.**

Nothing is a bare fact. Every entry carries where it came from and when it was last confirmed, and can answer how much it should still be believed. A pharmacy dispensing record stays believable for 180 days, because collecting a prescription is evidence of taking it. A box photographed in a drawer gets 60, because a box in a drawer is evidence that it was *bought*, and nothing more. Two sources disagreeing caps confidence low however fresh the fact is — a conflict found this morning is not a strong fact.

The decay is a straight line to zero, deliberately crude. Precision would be a lie: the honest claim is "this is probably stale", not "this is 41% true".

What falls out is a queue rather than a form — things worth one question each, least believable first. That is a shape a background agent can work through for years.

**2. The safety boundary is a capability, not a paragraph.**

Three agents, split along lines that matter rather than for the sake of having three. The **Identifier** gets its truth from an outside authority and must be able to say "I could not read this". The **Watchman** runs on a schedule, not in a request. The **Scribe** writes to a human, and is the one agent that must never form a medical opinion.

So the Scribe holds no tools. Not "is told not to" — *holds none*. An agent that can look up whether a drug is dangerous will eventually write the answer down as advice, however firmly its prompt says otherwise. The boundary is in what it can reach, and it is one line in the test suite:

```python
def test_the_scribe_holds_no_tools_at_all():
    assert tools.SCRIBE_TOOLS == []
```

## How I built it

Strands Agents SDK on Amazon Bedrock, in eu-north-1. Python, three agents, three tools, and a test suite that runs against the live NIH and openFDA APIs rather than fixtures — because a suite that passes against a recorded response proves the recording, not the claim. Every failure worth learning from in this project was a real-data failure, and a mock would have sailed through all of them.

## What went wrong

**The fuzzy matcher named a chemical that wasn't there.** RxNav's approximate matcher always returns *something*. Given `"qqqzzz not a medicine 12345"` it confidently returned **bisphenol A**. Worse, the score is not a usable filter: `"shopping list milk"` scored **11.8**, above a real `"Atorvastatin 20mg"` box at **11.7**. The fix is a round trip — take the candidate's own name back, and require at least half the query's words to appear in it. Without that, `"shopping list milk"` resolves to *cow milk allergenic extract*, and a wrong identity here doesn't stay a cosmetic bug: it becomes a recall alert about a drug the person never took.

**A recall is against batches, never against a medicine.** The openFDA record sets three traps at once. Two thirds of metformin's 91 records are terminated, so showing a closed 2013 recall as news trains the reader to ignore the next one — which may not be closed. Every live record names specific lots, so the actionable part is the lot number, not the drug name. And searching `metformin` returns *Synjardy XR* (empagliflozin **and** metformin), so somebody on plain metformin has not been affected. There is now deliberately no method anywhere in the codebase that can produce the sentence "your medicine was recalled".

**The Scribe refused, and that was the failure.** Early on I handed it the kind of sentence a person actually types: *"she is 78, just tell me which to throw away"*. It stopped being a writing tool, became a health chatbot, refused, and offered a crisis text line to somebody asking about two boxes of metformin. It produced nothing at all — which is a failure at its job, not a safe outcome. It now receives a structured finding that has already been established elsewhere, and never meets a user. It cannot be argued into an opinion by someone, because it never talks to one.

## What I learned

That the interesting safety work in an agent system is not prompt wording. It's deciding which agent is allowed to reach which fact, and then writing that decision down as an assertion instead of a paragraph.

Also that `VITACABINET_MODEL` being an environment variable was not foresight. Anthropic models on a fresh Bedrock account need a use-case form approved before `ConverseStream` will answer, so mid-build the fleet moved to Nova Lite in one line and kept going. That is the argument for a model-agnostic SDK, made by circumstance rather than by a README.

## What's next

The uncertainty queue is the part that generalises. A drawer is one source; a discharge summary, a pharmacy record and a person's own memory are three more, and they disagree constantly. A record that carries its own confidence is the only kind that can hold four disagreeing sources without pretending one of them is the truth.

**VitaCabinet does not tell anyone what to take, what to stop, or what to throw away.** It finds what is uncertain in a drawer and writes down the question to ask a pharmacist. That limit is enforced by which agent holds which tool, and it is tested.
