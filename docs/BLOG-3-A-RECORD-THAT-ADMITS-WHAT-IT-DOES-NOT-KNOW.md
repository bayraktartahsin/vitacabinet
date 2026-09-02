# Agents for Humans: a medical record that admits what it does not know

*Third post on building VitaCabinet on the Strands Agents SDK and Amazon Bedrock. The first was about [the agent that holds no tools](https://builder.aws.com/content/3IgYR6LSK8Egmfr1jFBDELaleu3/agents-for-humans-i-gave-one-of-my-agents-no-tools-at-all); the second about making the other two do real work. This one is about the data model underneath, and why a background agent needs one.*

Every medical record is a photograph of a moment, presented as though it were current.

A GP's list is what was true in March. A hospital discharge summary is from the night of an admission. A pharmacy's dispensing history says what was *collected*, which is not what was *swallowed*. Each is accurate about a moment and silent about which moment. And that silence — not the staleness itself — is the hazard. A clinician who knows a list is six months old asks a question. One handed the same list with no date acts on it.

VitaCabinet is live at **https://b5emjsgbi1.execute-api.eu-north-1.amazonaws.com**. Photograph the boxes in a drawer, and three agents read it, keep watching it, and write down what to ask a pharmacist. This post is about the part that is not an agent: the record they work on.

---

## Nothing is stored as a bare fact

The core type is tiny, and every field earns its place:

```python
@dataclass
class Fact:
    subject: str                 # the drug, as we understand it
    source: Source               # where this claim came from
    confirmed_at: datetime       # when it was last known to be true
    contested: str = ""          # set when two sources disagree, says how
```

`Source` is an enum, and each member carries a **horizon** — how many days before a claim from that source should be believed no more:

| Source | Believed for | Why |
| --- | --- | --- |
| a pharmacy dispensing record | 180 days | collecting a prescription is evidence of taking it |
| a clinician's list | 120 days | authoritative, and out of date the day it was written |
| the person themselves | 90 days | people forget, and people are polite to doctors |
| a box photographed in the drawer | 60 days | a box in a drawer is evidence it was *bought*, and nothing more |
| inferred from other facts | 30 days | inference compounds error |

Confidence is a straight line from one to zero across that horizon. Deliberately crude. I tried a nicer curve and threw it away: precision here would be a lie. The honest claim is *"this is probably stale,"* not *"this is 41% true."*

Two sources disagreeing caps confidence at 0.4 no matter how fresh the fact is. A conflict discovered this morning is not a strong fact — it is a strong *question*.

## What falls out is a queue, not a form

Once every fact can say how much it should be believed, the interesting query is not "what is in the drawer" but **"what is least believable right now."**

```python
@property
def stale_facts(self) -> list[Fact]:
    return sorted((f for f in self.facts if f.stale), key=lambda f: f.confidence)
```

That is a work queue. Least believable first. Each entry is worth exactly one question — *"Are you still taking the ramipril? The last time anyone confirmed it was 130 days ago"* — and the Scribe agent turns each into a sentence a person can read aloud at a pharmacy counter.

This is the shape a background agent needs. Not a dashboard somebody has to open, but a queue something can work through, slowly, for years.

## Keeping a drawer

In the first build the record was in memory and every reading was stateless. That was fine for a demo and useless for the product, so drawers now persist in DynamoDB — one table, one key:

```
drawer#<id>   boxes, facts[], findings[], seen_keys[], history[], subscribers[]
job#<id>      status, trace[], said{}, result   (TTL: one hour)
```

When the person confirms a fact — *"yes, she is taking that"* — it moves from `BOX` to `PERSON`, its clock resets, and its bar on the page refills. Confidence is *stored*, not assumed; and it is stored per fact, because the pharmacy is sure about one drug and nobody is sure about another.

## The Watchman only speaks when something is new

An EventBridge rule runs the Watchman agent every night over every kept drawer. It calls `check_for_recalls` for every ingredient, and the findings are diffed against what it found last time — **by finding key, not by count**:

```python
def set_findings(drawer_id, findings, trace_len):
    seen = set(row["seen_keys"])
    new = [f for f in findings if f["key"] not in seen]
    ...
    return {"new": new, "total": len(findings)}
```

Only if `new` is non-empty does SNS send an email. The same recall showing up again tomorrow is not news. A message every night is how people stop reading the one that matters — which is the single most important product decision in the whole thing, and it is four lines.

The page shows it plainly: *Watchman last checked: 03:12 today · 0 new · 13 findings · 5 tool calls · runs nightly via EventBridge.* Zero new is the normal, good outcome. The design has to make silence look like success.

## A recall is against batches, never against a medicine

The Watchman's findings are the most dangerous output in the system, so they are the most constrained. Three traps in the openFDA record shaped the wording:

- Two thirds of metformin's records are `Terminated`. Presenting a closed 2013 recall as news teaches the reader to ignore the next one. **Live only.**
- Every live record names specific lots. The actionable thing is the lot number on the box in your hand, not the drug name. **Lots carried on the type.**
- Search `metformin` and you get *Synjardy XR* — empagliflozin *and* metformin. Somebody on plain metformin has not been affected. **Combination products flagged.**

There is deliberately no code path anywhere in the project that can produce the sentence *"your medicine was recalled."* The wording is tested:

```python
assert "a batch of" in text
assert "check the box" in text
assert "your medicine" not in text
```

Somebody frightened off a drug they need is a worse outcome than the recall you were reporting.

## Photographs, and why the vision model does not identify

The drawer is photographed. Amazon Nova Lite — the same model the agents run on — reads the printed product name and strength off each box, one line per box, nothing else.

It *reads*. It does not *identify*. The identity still comes from RxNorm afterwards, exactly as it does for typed text. A vision model that also decided what the drug *was* would be a second, unaccountable source of identity — and the entire point of this record is that every fact can say where it came from.

---

## What I'd want you to take

- **Store the provenance, not just the value.** A record that shows only the drug name is making the same mistake as every record it is trying to improve on.
- **Make staleness a first-class query.** Then a background agent has something to do.
- **Diff by identity, not by count, and stay silent when nothing changed.** That is the difference between an assistant and an alarm.
- **Keep the vision model out of identity.** Reading and identifying are different jobs with different accountability.

Code, Apache 2.0, with the test suite that runs against the live NIH and FDA APIs: **https://github.com/bayraktartahsin/vitacabinet**

VitaCabinet does not tell anyone what to take, what to stop, or what to throw away. It finds what is uncertain in a drawer, keeps watching it, and writes down the question to ask a pharmacist. That limit is enforced by which agent holds which tool, and it is tested.
