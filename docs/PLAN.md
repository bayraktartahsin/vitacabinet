# VitaCabinet — the plan

## What it is, in one line

Photograph the medicine boxes in a kitchen drawer. VitaCabinet works out what
is actually in there, finds what nobody else can see, and then keeps watching
for years so that when something changes, somebody notices.

## The problem, stated so a judge feels it

Six boxes on a kitchen table. Ask her which ones she is still taking.

She cannot tell you. Neither can you, about your own father. Her GP has seen
one part of that drawer, the cardiologist another, the pharmacy a third. Nobody
has ever seen all six boxes at once — and nobody did anything wrong. The harm
lives in the gaps between people who were each doing their job correctly.

## What it finds

| Finding | Where the truth comes from |
|---|---|
| Two boxes are the same medicine under different names | RxNorm ingredient identity (NIH) |
| A medicine stopped months ago but still being taken | drift between the drawer and the last confirmed list |
| Two medicines that should not be taken together | openFDA adverse event reports |
| A medicine that has been **recalled** | openFDA enforcement records |
| A medicine last confirmed months ago — still taking it? | the record's own decay model |

Every one of these is checkable. The patient is synthetic; the pharmacology is
real, public, and citable by anyone who wants to argue with it.

## What it deliberately does not do

It never tells anyone to stop taking anything. It writes the one question to
ask a clinician and hands it over. The same boundary VitaHome drew: do the
clerical work, leave the medical decision to a person.

This is a capability boundary, not an instruction — the agent that assembles
questions is not given a tool that can write clinical advice.

## The agents, and why each one exists separately

Splitting work across agents is only worth doing when the pieces have different
failure modes or different authority. Five do here.

1. **Reader** — turns a photograph of boxes into candidate text. Fails by
   misreading; must never hand downstream a name it is not sure of.
2. **Identifier** — resolves text to a drug through RxNorm. Separate from the
   Reader because its source of truth is an external authority, and because a
   bad read must not silently become a confident identity.
3. **Watchman** — runs on a schedule, not in a request. Recalls, shortages and
   safety alerts arrive whenever they arrive; nothing about them is triggered
   by a user opening an app. This is the background half of the product.
4. **Investigator** — when two sources disagree, it does not merge them or pick
   the likelier. It works out what would settle the question and goes to get
   it, or marks the fact uncertain *in a specific way*.
5. **Scribe** — assembles what to ask a clinician. Deliberately has no tool
   capable of asserting a clinical fact.

## The record that admits what it does not know

Every medical record is a photograph of a moment presented as if it were
current. That confidence is the hazard, not the staleness.

So every fact carries its age and how it was established. "Metformin, last
confirmed 4 months ago, from a box photographed in March" is a different claim
from "Metformin, confirmed by the pharmacy yesterday", and the interface says
so. Reducing that uncertainty is what the agent does in the background — one
question a week, not a form.

## Demo, five minutes

| At | What happens |
|---|---|
| 0:00 | A photo of six boxes. "Ask her which of these she is still taking." Silence. |
| 0:40 | Photograph them. The picture assembles itself. |
| 1:30 | Two boxes, one molecule — with the RxNorm code that proves it. One stopped months ago. One interacts. |
| 2:15 | "None of her six doctors saw all six boxes. Nobody did anything wrong." |
| 3:00 | It does not say stop. It writes the question. |
| 3:30 | Weeks pass. The FDA publishes a recall. It already knows what is in the drawer. |
| 4:15 | "We last confirmed the metformin four months ago. Are you still taking it?" |

## Build order

Evidence and demo first — the sequencing mistake from the last build was
leaving both until the end.

| Days | Work |
|---|---|
| 1–2 | Repo, licence, Strands on Bedrock, drug identity **(done)** |
| 3–4 | Recalls and interactions from openFDA; the uncertainty model |
| 5–6 | The five agents, the capability boundary, sessions carrying state |
| 7–8 | AgentCore deploy, live link, the scheduled Watchman |
| 9–10 | Web app: the drawer, the findings, the questions |
| 11 | Run it against 12 real medicine names, record the numbers |
| 12 | Video |
| 13 | Three builder.aws posts (0.6 bonus) |
| 14 | Submit. Two days of buffer, deliberately unused. |

## What could sink it

- **Reading boxes from a photo is the hardest part.** If vision struggles with
  real packaging, the fallback is typing a name — the findings still stand, the
  demo loses its opening. Test this on day 3, not day 11.
- **Adjacency to prior work.** Reconciling medications is close to something
  already built. The defence is that this is about time and decay rather than
  comparison at a moment, and the framing has to carry it in the first minute.
- **Scope.** Five agents is the ceiling, not the floor. Any one of them can be
  a single tool call if the week runs short.
