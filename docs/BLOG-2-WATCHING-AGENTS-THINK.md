# Agents for Humans: the model orchestrates, the data never passes through it

*Second post on building VitaCabinet with the Strands Agents SDK on Amazon Bedrock. The [first one](https://builder.aws.com/content/3IgYR6LSK8Egmfr1jFBDELaleu3/agents-for-humans-i-gave-one-of-my-agents-no-tools-at-all) was about the agent that holds no tools. This one is about what happened when I made the other two actually do the work.*

VitaCabinet reads a medicine drawer — photograph the boxes, and three agents resolve each one against RxNorm, check the FDA enforcement record for live recalls, and write down the question to ask a pharmacist. It is live: **https://b5emjsgbi1.execute-api.eu-north-1.amazonaws.com**

When I audited my own first build against the judging criteria, I found something uncomfortable. I had defined three Strands agents, tested them, drawn them on the architecture diagram — and the request path a judge would actually exercise ran two REST calls in plain Python and never touched two of them. The one agent that did run was the one with no tools. The SDK was, in the deployed product, a sentence generator.

So I rewired it. Here is what that took, in the order the problems arrived.

---

## Problem one: the model drowned in its own tool results

The first honest version was simple. `check_for_recalls(ingredient)` returned the openFDA payload as a dict; the Watchman agent called it once per ingredient; Strands handed each result back to the model.

Amlodipine has thirteen live recalls on the enforcement record. Each is a paragraph. The Watchman's second call blew straight through Nova Lite's output budget:

```
strands.types.exceptions.MaxTokensReachedException:
Model stopped generating due to maximum token limit.
```

The model was being asked to *carry* the data, and the data was never its job. Its job is deciding what to call next.

The fix is a split I now think every tool-using agent should have. A tool returns **one sentence** to the model — enough to decide the next step — and writes the **full structured result** to a ledger the application reads afterwards:

```python
@tool
def check_for_recalls(ingredient: str) -> str:
    live = fda.recalls(ingredient)
    ledger().recalls[ingredient] = live          # the app reads this
    if not live:
        return f"{ingredient}: no live recalls on the FDA enforcement record."
    newest = live[0]
    return (f"{ingredient}: {len(live)} live recall(s). Newest: a batch of "
            f"{newest.product.split(',')[0]} on {newest.date}, lots {newest.lots}. "
            f"Report batches and lots, never 'your medicine'.")   # the model reads this
```

Thirteen recalls became one line in the context window. The Watchman went from a crash to 5.5 seconds for five ingredients — and, because its context stayed small, its final report got *better*: it now says things like *"if you are taking only metformin and not the combination product, you may not be affected."* That sentence was written by a model that had read a summary, not a dump.

## Problem two: the model rewrote its own arguments

With the ledger in place, the Identifier agent worked beautifully — one `identify_medicine` call per box, then `find_duplicate_medicines` across all of them. Except the duplicate finding, the one thing the product exists for, vanished.

The trace explained it. Nova had "helpfully" normalised the box texts before passing them back:

```
find_duplicate_medicines(box_texts=["metformin hydrochloride 500 mg", ...])
```

`Glucophage 500mg` and `Metformin 500 mg` — a brand and its generic, the pair I needed — had been collapsed into one string before the tool ever saw them. The tool compared a list with no pair in it, and reported none.

You cannot prompt this away reliably. What you can do is stop depending on the model relaying inputs faithfully. `find_duplicate_medicines` now compares **whatever is already in the ledger** — every box the Identifier has read this session — and its argument only adds. And the orchestrator recomputes duplicates from the ledger after the agent finishes, unconditionally. Cheap, deterministic, and immune to the model's paraphrasing.

The principle generalises: **findings come from tool results, never from the model's prose or the model's arguments.** The model decides *when* to look. The tools decide *what was found*.

## Problem three: API Gateway gives you thirty seconds

Two agents reading seven boxes take 15–35 seconds, depending on cold starts. API Gateway HTTP APIs return `503` at thirty. No configuration changes that.

I resisted the obvious fix — a spinner over a synchronous call that sometimes works — because it would also have been the worse demo. A reading became a *job*:

1. `POST /scan` writes the boxes to DynamoDB, invokes the same Lambda **asynchronously** with `{"job": id}`, and answers in a few hundred milliseconds.
2. A Strands **hook** on `AfterToolCallEvent` writes each tool call — name, arguments, what the tool said, duration — to the job row *as it happens*.
3. The page polls `GET /jobs/{id}` every 600 ms and draws the trace as it grows.

```python
class Trace(HookProvider):
    def register_hooks(self, registry, **_):
        registry.add_callback(AfterToolCallEvent, self.after)

    def after(self, ev):
        step = {"agent": self.agent_name, "tool": ev.tool_use["name"],
                "input": ev.tool_use["input"], "said": tool_text(ev.result)[:240],
                "ms": elapsed_ms(ev)}
        store.job_step(self.job_id, step)     # DynamoDB list_append
```

The person watching sees `identify_medicine("Glucophage 500mg") → 2909 ms → metformin hydrochloride 500 MG Oral Tablet (RxCUI 861008)` appear line by line. It is the most persuasive thing on the screen, and it exists because of a timeout.

## Problem four: a leak that only showed up in one test order

The ledger was a `contextvars.ContextVar`. Clean, per-request, idiomatic. One test failed — only when the whole suite ran, never alone.

Strands' `ConcurrentToolExecutor` runs tools on a thread pool. If a pool thread ever lazily created its own ledger, it *kept* it, and the next reading's tool calls on that thread landed in a stale ledger. The duplicate vanished again, for a different reason, in a way that depended on which thread picked up which call.

The fix was less clever than the bug: a module-level ledger guarded by a lock. Each Lambda invocation is its own process; locally, readings serialise. I wrote down why in the code, because the ContextVar *looks* more correct and the next person will want to put it back.

## Then I moved the agents to AgentCore

With the agents doing real work, the last step was hosting them where AWS suggests: **Amazon Bedrock AgentCore Runtime**. The starter toolkit builds the ARM64 container in CodeBuild, so no Docker on the laptop — which mattered, because there is none.

```bash
agentcore configure -e agentcore_entry.py -n vitacabinet -rf requirements.txt
agentcore deploy --env VITACABINET_TABLE=vitacabinet
```

The entrypoint is twenty lines around the same `read_drawer()` the Lambda used. The one design point worth stating: when the payload carries a job id, **the runtime writes the trace to DynamoDB itself**, from inside AgentCore, so the page keeps drawing the agents thinking even though the reading no longer runs next to it. The Lambda's job handler became "invoke the runtime, wait, record the result." Same agents, same tools, same ledger, same trace — one code path, two places it runs.

Two things went wrong that will save you an hour: the container failed to start because `bedrock-agentcore` was not in `requirements.txt` (the toolkit installs *your* requirements, not its own), and the auto-created execution role needed an inline policy for the table before the trace could be written from inside the runtime.

---

## What I would tell you

- **Tools should tell the model one sentence and tell the app everything.** The model's context is for deciding, not for carrying.
- **Never derive findings from the model's prose or the model's arguments.** Recompute from what the tools actually returned.
- **A timeout can be a feature.** The async job with a streamed trace is a better product than the synchronous call would have been.
- **Order-dependent test failures in agent code are usually shared state on executor threads.** Look there first.

The code, Apache 2.0, with 60-odd tests that run against the live models and public APIs: **https://github.com/bayraktartahsin/vitacabinet**

VitaCabinet does not tell anyone what to take, what to stop, or what to throw away. It finds what is uncertain in a drawer, keeps watching it, and writes down the question to ask a pharmacist.
