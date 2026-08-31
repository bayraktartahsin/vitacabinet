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
    cue: "Straight in. No title card, no throat-clearing." },

  { say: "That drawer decides what she actually swallows, and it is a mess. A brand and its generic side by side, because the hospital sent her home on one and the GP repeated the other.",
    cue: "The problem. Slow down here." },

  { say: "This is for whoever manages somebody else's medicines. An adult child, a spouse, a carer.",
    cue: "WHO IT'S FOR — judges are told to look for this." },

  { say: "And here is why it matters. Every list they are handed is a photograph of a moment, presented as though it were current. A GP's list is what was true in March, and it does not say so.",
    cue: "WHY IT MATTERS." },

  { say: "That unmarked confidence is the hazard, not the staleness. A clinician who knows a list is six months old asks. One handed the same list with no date acts on it.",
    cue: "The thesis of the whole project." },

  { say: "So: VitaCabinet. Live right now on Lambda, API Gateway and Bedrock. Seven boxes, and one line that is not a medicine at all.",
    cue: "SCREEN: the app, drawer already filled.",
    act: { action: 'reset' }, floor: 9 },

  { say: "Read the drawer. Every box goes to RxNorm at the National Institutes of Health for its true identity, then every ingredient to the FDA enforcement record. Live, now.",
    cue: "SCREEN: scanning, about five seconds. Keep talking.",
    act: { action: 'scan' }, until: 'scan', ceiling: 45, floor: 12 },

  { say: "Seven boxes read, one duplicate, and the ingredients checked against the FDA.",
    cue: "SCREEN: the count chips. Point at them.",
    act: { action: 'focus', args: { kind: 'counts' } }, floor: 6 },

  { say: "The duplicate is what this exists for. Glucophage and Metformin — a brand and its generic, the same ingredient twice. Read only the fronts of the boxes and you would never see it. That is a double dose.",
    cue: "SCREEN: the red duplicate card.",
    act: { action: 'focus', args: { kind: 'duplicate' } } },

  { say: "Now the part I would defend hardest. I ask it to write the question.",
    cue: "SCREEN: clicking 'Write the question to ask'.",
    act: { action: 'question', args: { kind: 'duplicate' } }, until: 'question', ceiling: 45, floor: 8 },

  { say: "A question for a pharmacist. Not advice. It told nobody to stop anything, because the agent that wrote it holds no tools at all.",
    cue: "SCREEN: the Scribe's question. Let them read it.", floor: 9 },

  { say: "It is not told not to advise. It cannot. Any agent that can look up whether a drug is dangerous will eventually write that down as advice, however you word the prompt. So it does not get the lookup.",
    cue: "The capability-boundary argument. Technical high point." },

  { say: "A live FDA recall, with the lot number to check against the box in your hand.",
    cue: "SCREEN: the amber recall card.",
    act: { action: 'focus', args: { kind: 'recall' } }, floor: 7 },

  { say: "Read it. A batch of this product was recalled — check the box. It never says your medicine was recalled. No code path in this project can produce that sentence. Somebody frightened off a drug they need is worse than the recall I was reporting.",
    cue: "Point at the lot number." },

  { say: "And this is the line I promised. Shopping list milk. Reported unreadable, and never named.",
    cue: "SCREEN: the 'not identified' note.",
    act: { action: 'focus', args: { kind: 'unreadable' } }, floor: 7 },

  { say: "Harder than it looks. The NIH fuzzy matcher answers that with cow milk allergenic extract, and scores it above a real atorvastatin box. A wrong name here becomes a recall alert for a drug nobody takes.",
    cue: "The failure that shaped the design." },

  { say: "Three agents on the Strands Agents SDK. The Identifier reads the drawer and may say I could not read this. The Watchman runs on a schedule, because recalls arrive when they arrive. The Scribe writes, and holds nothing.",
    cue: "SCREEN: the architecture diagram.",
    act: { action: 'architecture' }, floor: 14 },

  { say: "Underneath, every fact carries its source and its age. A pharmacy record stays believable for a hundred and eighty days. A box in a drawer gets sixty — a box is evidence it was bought, and nothing more.",
    cue: "SCREEN: the confidence row.",
    act: { action: 'focus', args: { kind: 'decay' } } },

  { say: "VitaCabinet never tells anyone what to take, what to stop, or what to throw away. It finds what is uncertain and writes the question to ask a pharmacist. That limit is a capability boundary, not a paragraph in a prompt, and it is tested.",
    cue: "CLOSE. Land it, then stop talking.",
    act: { action: 'closing' }, floor: 12 },
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
