/* The autopilot: one script, two pages, one clock.
 *
 * The director page shows the words. The stage page is the app, and drives
 * itself. You narrate and never touch the keyboard, which is the only way a
 * four-minute unedited take is repeatable.
 *
 * Three things here are scar tissue from doing this once before:
 *
 *   Addressing.  A BroadcastChannel reaches EVERY tab on the origin. The first
 *                version of this fired one click into six open tabs and created
 *                six of everything. So the director does a roll-call, claims
 *                exactly one stage by id, and every message after that carries
 *                that id. Unclaimed stages ignore the traffic.
 *
 *   The clock.   setInterval in a background tab is throttled to about once a
 *                second, so a countdown drifts the moment the director loses
 *                focus. The tick comes from a Web Worker instead, which is not
 *                throttled.
 *
 *   Waiting.     Beats that trigger real network work do not advance on a
 *                guessed duration. They advance when the stage says it finished,
 *                or when a ceiling is reached — whichever is later, so the words
 *                never run ahead of the screen.
 */

const CHANNEL = 'vitacabinet-autopilot';

/* --- timing ------------------------------------------------------------- *
 * Hold times are derived from the words rather than typed in by hand, so
 * editing a line re-times the take automatically. 2.4 words/second is an
 * unhurried speaking pace; the +1.4s is the breath before the next line.
 */
function holdFor(text, floor) {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(floor || 4, Math.round((words / 2.4 + 1.4) * 10) / 10);
}

/* --- the script --------------------------------------------------------- *
 * say     the line to read, verbatim
 * cue     what is happening on screen, for the director's eye only
 * act     {action, args} sent to the stage as the beat opens
 * until   the stage event that must arrive before advancing
 * ceiling hard cap in seconds for `until`, so a dead network cannot hang the take
 * floor   minimum seconds to hold, regardless of word count
 */
const SCRIPT = [
  { say: "Ask anyone to name every medicine in their mother's drawer, with the strengths. Almost nobody can. I couldn't.",
    cue: "Straight in. No title card." },

  { say: "That drawer decides what she actually swallows, and it is a mess. A brand and its generic side by side, because the hospital sent her home on one and the GP repeated the other.",
    cue: "The problem. Slow down." },

  { say: "This is for whoever manages somebody else's medicines. An adult child, a spouse, a carer.",
    cue: "WHO IT'S FOR." },

  { say: "And why it matters: every list they are handed is a photograph of a moment, presented as current. A GP's list is what was true in March, and it does not say so. That unmarked confidence is the hazard.",
    cue: "WHY IT MATTERS — the thesis." },

  { say: "So: VitaCabinet. Live on Lambda, API Gateway, DynamoDB and Bedrock. I photograph the drawer.",
    cue: "SCREEN: the photo drops in and Nova Lite reads the labels.",
    act: { action: 'reset' }, floor: 5 },

  { say: "Nova Lite reads the printed names and strengths off the boxes. It reads; it does not identify. Identity comes from RxNorm next, so every fact can say where it came from.",
    cue: "SCREEN: six lines appear in the drawer. Wait for it.",
    act: { action: 'photo' }, until: 'photo', ceiling: 40, floor: 10 },

  { say: "I add one line that is not a medicine at all, and read the drawer. Now watch the agents work.",
    cue: "SCREEN: the trace starts streaming. Point at it.",
    act: { action: 'scan' }, until: 'scan', ceiling: 90, floor: 12 },

  { say: "This is the Identifier, on the Strands Agents SDK, calling its tools: one call per box to RxNorm at the NIH, then one to compare them all. Every call you see is real and timed.",
    cue: "SCREEN: the Identifier's rows. Keep talking; it is still running.",
    act: { action: 'focus', args: { kind: 'trace' } }, floor: 9 },

  { say: "Then the Watchman takes over — one call per ingredient to the FDA enforcement record. Two agents, seven tool calls, about fifteen seconds.",
    cue: "SCREEN: Watchman rows and the count chips.",
    act: { action: 'focus', args: { kind: 'counts' } }, floor: 8 },

  { say: "The duplicate is what this exists for. Glucophage and Metformin — a brand and its generic, the same ingredient twice. Read only the fronts of the boxes and you would never see it. That is a double dose.",
    cue: "SCREEN: the red card.",
    act: { action: 'focus', args: { kind: 'duplicate' } } },

  { say: "Now the part I would defend hardest. I ask it to write the question.",
    cue: "SCREEN: the Scribe writes.",
    act: { action: 'question', args: { kind: 'duplicate' } }, until: 'question', ceiling: 45, floor: 8 },

  { say: "A question for a pharmacist, not advice. The agent that wrote it holds no tools at all — not told not to advise, unable to. An agent that can look up whether a drug is dangerous will eventually write that down as advice. So it does not get the lookup.",
    cue: "The capability-boundary argument. Technical high point." },

  { say: "A live FDA recall, with the lot number. It says a batch was recalled — check the box. It never says your medicine was recalled; no code path in this project can produce that sentence.",
    cue: "SCREEN: the amber card, the lot line.",
    act: { action: 'focus', args: { kind: 'recall' } }, floor: 9 },

  { say: "And the line that was not a medicine: shopping list milk. Reported unreadable, never named. The NIH fuzzy matcher would call it cow milk allergenic extract. A wrong name here becomes a recall alert for a drug nobody takes.",
    cue: "SCREEN: the 'not identified' note.",
    act: { action: 'focus', args: { kind: 'unreadable' } }, floor: 10 },

  { say: "Now I keep the drawer. Every fact carries its source and its age, and decays. A box in a drawer is believed for sixty days, because a box is evidence it was bought, and nothing more.",
    cue: "SCREEN: the cabinet panel appears with confidence bars.",
    act: { action: 'save' }, until: 'save', ceiling: 20, floor: 11 },

  { say: "When Mum confirms she is actually taking one, the fact moves to her and resets. Confidence is stored, not assumed.",
    cue: "SCREEN: one bar refills, source changes to 'the person themselves'.",
    act: { action: 'confirm', args: { subject: 'Norvasc 5mg' } }, floor: 7 },

  { say: "And the Watchman keeps watching. EventBridge runs it nightly over every kept drawer, and it emails only when something is new — a message every night is how people stop reading the one that matters. Here it is, running now.",
    cue: "SCREEN: 'Run the Watchman now' — trace streams again, then the watch line updates.",
    act: { action: 'check' }, until: 'check', ceiling: 90, floor: 12 },

  { say: "Zero new since last check. Nothing to say, so it says nothing. That is the whole point of a background agent.",
    cue: "SCREEN: the watch line — 0 new.",
    act: { action: 'focus', args: { kind: 'watch' } }, floor: 7 },

  { say: "Three agents on Strands. The Identifier reads. The Watchman runs on a schedule. The Scribe writes, and holds nothing. Under them, one table where every fact ages.",
    cue: "SCREEN: the architecture diagram.",
    act: { action: 'architecture' }, floor: 12 },

  { say: "VitaCabinet never tells anyone what to take, what to stop, or what to throw away. It finds what is uncertain, keeps watching, and writes the question to ask a pharmacist. That limit is a capability boundary, not a paragraph in a prompt — and it is tested.",
    cue: "CLOSE. Land it, then stop.",
    act: { action: 'closing' }, floor: 11 },
];

/* --- plumbing ----------------------------------------------------------- */

function newId() {
  return Math.random().toString(36).slice(2, 10);
}

/* An unthrottled 100ms tick. A background tab clamps setInterval to ~1s, which
 * is enough to make a countdown visibly wrong halfway through a take. */
function makeTicker(onTick) {
  const src = "let h=null;onmessage=e=>{if(e.data==='start'){clearInterval(h);" +
              "h=setInterval(()=>postMessage(0),100)}else{clearInterval(h);h=null}}";
  const w = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
  w.onmessage = onTick;
  w.postMessage('start');
  return w;
}

export { CHANNEL, SCRIPT, holdFor, newId, makeTicker };
