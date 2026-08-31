# Agents for Humans: I gave one of my agents no tools at all

*Building VitaCabinet with the Strands Agents SDK on Amazon Bedrock*

Ask someone to name every medicine in their mother's drawer, with strengths. Almost nobody can. I couldn't, and that is the whole reason this project exists.

The drawer is the record that actually governs what gets swallowed, and it is a mess — a brand and its generic side by side because the hospital sent her home on one and the GP repeated the other, something a cardiologist stopped last spring that nobody threw away, a box from a batch recalled four months ago that never came up because nobody was looking.

Meanwhile every *formal* record of the same drawer is a photograph of a moment presented as though it were current. A GP's list is what was true in March. A hospital's is from the night of an admission. Neither of them says so — and that unmarked confidence is the hazard, not the staleness itself. A clinician who knows a list is six months old asks a question. One handed the same list with no date acts on it.

So I built **VitaCabinet**: a record that admits what it does not know, and a small fleet of agents that work through what it is unsure about.

It is live, if you want to poke at it before reading any further — no install, no sign-up:
**https://b5emjsgbi1.execute-api.eu-north-1.amazonaws.com**

This post is about the four things that went wrong while building it, because those turned out to be the design.

---

## The agent that holds no tools

I started with the obvious split: one agent to read the drawer, one to check for recalls, one to write down what to ask the pharmacist. Three agents, three sets of `@tool` functions, all straightforward in Strands:

```python
from strands import Agent
from strands.models import BedrockModel

def watchman() -> Agent:
    return Agent(model=BedrockModel(model_id=MODEL, region_name="eu-north-1"),
                 tools=[check_for_recalls],
                 system_prompt=WATCHMAN_PROMPT)
```

The third agent — the one I call the Scribe — writes to a human. Its prompt said, firmly and at length, that it must never give medical advice.

That prompt was worthless, and I can show you why.

Early on I handed the Scribe the kind of sentence a person actually types:

> *"she is 78, should she stop one, just tell me which to throw away"*

It stopped being a writing tool. It became a health chatbot: it refused, apologised, and offered a crisis text line to somebody asking about two boxes of metformin. It produced no question at all.

That is not a safe outcome. That is a **failure at the job**, dressed as caution.

Two things were wrong. First, the Scribe should never have met a user's raw text — it should receive a finding that has already been established by the parts of the system that are allowed to establish things. Second, and more importantly: *any* agent that can look up whether a drug is dangerous will eventually write that lookup down as advice, however firmly you word its prompt. The prompt is a request. The tool list is a fact.

So the Scribe holds nothing:

```python
CLERICAL_TOOLS = [identify_medicine, find_duplicate_medicines]
SAFETY_TOOLS   = [check_for_recalls]
SCRIBE_TOOLS: list = []          # deliberately empty
```

And the safety model is one line in the test suite rather than a paragraph of policy:

```python
def test_the_scribe_holds_no_tools_at_all():
    assert tools.SCRIBE_TOOLS == []
```

That is the thing I'd most want another builder to take from this. The interesting safety work in an agent system is not prompt wording. It is deciding which agent is allowed to *reach* which fact, and then writing that decision down as an assertion.

---

## The lookup that names a chemical that isn't there

Drug identity comes from RxNorm, via the NIH's RxNav API. The exact lookup is easy. Real box text is not:

```
Metformin 500 mg      -> resolves instantly
Glucophage 500mg      -> nothing
```

A strength glued to a brand name defeats the exact endpoint while sailing straight through on generics — exactly backwards for a medicine cabinet, where the *branded* box is the one most likely to be hiding a duplicate. So I added RxNav's `approximateTerm` fallback, and that is where it got interesting.

The approximate matcher always returns something. Given

```
qqqzzz not a medicine 12345
```

it confidently came back with **bisphenol A**.

My first instinct was to filter on the score. That does not work either:

| query | score |
| --- | --- |
| `shopping list milk` | **11.8** |
| `Atorvastatin 20mg` (a real box) | **11.7** |

Nonsense outscored a real medicine. There is no threshold that keeps one and drops the other.

What works is a round trip: take the candidate's own name back from RxNav and check that the thing it named has something to do with what was asked.

```python
def _confirms(text: str, rxcui: str) -> bool:
    asked = _words(text)
    return bool(asked) and len(asked & _words(name_of(rxcui))) / len(asked) >= 0.5
```

I first tried "at least one word in common". `shopping list milk` sailed through that as *cow milk allergenic extract*. Requiring half the query's words is what finally holds.

This is not a cosmetic bug. A wrong identity here does not stay a wrong row on a screen: it becomes a duplicate warning about a drug the person does not take, or a recall alert for a medicine they have never held.

---

## A recall is against batches, never against a medicine

The recall feature is the one most able to do harm, so it is the one I spent longest making timid.

openFDA's drug enforcement endpoint sets three traps at once.

**Most of it is history.** Metformin has 91 records; roughly two thirds are `Terminated`. Presenting a closed 2013 recall as news trains someone to ignore the next one — which may not be closed. So live recalls only, by default, at the type level rather than at the call site.

**Every live record is against named lots.** The actionable part is `code_info` — the lot numbers — not the drug name. The only sentence the data supports is *"a batch of this product was recalled, here are the lots, go and check the box in front of you."*

**Half the results are combination products.** Search `metformin` and you get *Synjardy XR* — empagliflozin **and** metformin. Somebody on plain metformin has not been affected, and telling them otherwise is a false alarm about a drug they need.

The result is that there is deliberately no method anywhere in this codebase that can produce the string "your medicine was recalled". The wording is tested:

```python
text = describe(recall).lower()
assert "a batch of" in text
assert "check the box" in text
assert "your medicine" not in text
assert "25140249" in text          # the lot number is the actionable part
```

Somebody frightened off a medicine they need is a worse outcome than the recall you were trying to report.

---

## Two things about building on AWS that I did not expect to matter

**Model-agnostic turned out to be load-bearing, not marketing.** Mid-build, Anthropic models on my fresh Bedrock account started returning `ResourceNotFoundException` on `ConverseStream` — a new account has to submit use-case details once before those models will answer. In a framework welded to one provider that is a day lost. In Strands it was one environment variable:

```python
DEFAULT_MODEL = os.getenv("VITACABINET_MODEL", "eu.amazon.nova-lite-v1:0")
```

The fleet moved to Amazon Nova Lite and kept going. Same agents, same tools, same tests. That is the argument for a model-agnostic SDK, made by circumstance rather than by a README — and it is why `VITACABINET_MODEL` is documented rather than hidden.

**Testing against live public APIs was worth the slowness.** Every test in this project calls RxNav and openFDA for real. The suite takes 52 seconds, needs a network, and would be considered bad practice in most codebases.

But look back at the three failures above: nonsense scoring higher than a real drug, a terminated recall looking exactly like a live one, a combination product hiding inside an ingredient search. **A mock would have passed every one of them**, because I would have written the mock from my own wrong assumptions. A suite that passes against a recorded response proves the recording, not the claim.

---

## What the record actually looks like

Underneath the agents is the part I think generalises. Nothing is stored as a bare fact. Every entry carries where it came from and when it was last confirmed, and can answer how much it should still be believed:

| Source | Believed for |
| --- | --- |
| a pharmacy dispensing record | 180 days |
| a clinician's list | 120 days |
| the person themselves | 90 days |
| a box photographed in the drawer | 60 days |
| inferred from other facts | 30 days |

A pharmacy dispensing record earns a long horizon because collecting a prescription is evidence of taking it. A box in a drawer earns a short one, because a box in a drawer is evidence that it was *bought*, and nothing more. Two sources disagreeing caps confidence low however fresh the fact is — a conflict found this morning is not a strong fact.

The decay is a straight line to zero. Deliberately crude: precision would be a lie. The honest claim is "this is probably stale", not "this is 41% true".

What falls out is a **queue** rather than a form — things worth one question each, least believable first. That is a shape a background agent can work through for years, which is the actual product. The screen is just where you go to see what it found.

---

## The public URL that would not go public

The last failure was pure infrastructure, and I am writing it down because I could not find it written down anywhere.

The app is FastAPI, so the deploy is a Lambda with a four-line Mangum adapter — no container, no second implementation, nothing about the deployed behaviour that the tests do not already exercise:

```python
from mangum import Mangum
from .api import app

handler = Mangum(app, lifespan="off")
```

A Lambda Function URL is the obvious front door. I created one with `AuthType: NONE` and attached exactly the resource policy AWS documents:

```json
{
  "Effect": "Allow",
  "Principal": "*",
  "Action": "lambda:InvokeFunctionUrl",
  "Resource": "arn:aws:lambda:eu-north-1:...:function:vitacabinet",
  "Condition": { "StringEquals": { "lambda:FunctionUrlAuthType": "NONE" } }
}
```

It returned `403 AccessDeniedException` to every anonymous request.

What I checked before giving up, in case it saves somebody an afternoon: the console renders the policy without complaint; `GetPolicy` and `GetResourcePolicy` both return it intact; the account belongs to no organization, so no SCP or RCP is in play; a direct `lambda:Invoke` of the same function returns `200` with the right body, so the code and the packaging are fine; and deleting and recreating the URL config changes nothing. The block sits above the policy layer and is not visible from the API or the console.

The fix was to stop arguing with it. An API Gateway HTTP API is public by default and needs no resource policy for anonymous callers, so the whole question disappears:

```python
api_id = api.create_api(
    Name="vitacabinet", ProtocolType="HTTP",
    Target=f"arn:aws:lambda:{REGION}:{account}:function:vitacabinet")["ApiId"]
```

Two things I would tell myself an hour earlier. **Separate the layers before you debug the policy** — one direct `Invoke` returning `200` proved the function was never the problem, and I should have run it first. And **when a managed service refuses in a way its own console cannot explain, take the other road**; API Gateway was the more ordinary way to front a Lambda anyway, and I had talked myself out of it because Function URLs looked simpler.

---

VitaCabinet does not tell anyone what to take, what to stop, or what to throw away. It finds what is uncertain in a drawer and writes down the question to ask a pharmacist. That limit is enforced by which agent holds which tool, and it is tested.

Try it: **https://b5emjsgbi1.execute-api.eu-north-1.amazonaws.com**

Code, with the Apache 2.0 licence and all 38 tests: **https://github.com/bayraktartahsin/vitacabinet**

Built for the Agents for Humans hackathon with the Strands Agents SDK on Amazon Bedrock.
