---
name: anti-ai-detection
description: "Use this skill when the user is writing academic or submitted work (essays, papers, application materials, reports) that needs to reduce AI-detection risk from tools like Turnitin, GPTZero, Copyleaks, or Originality.ai while remaining readable and submittable. Trigger phrases include 'make it sound human,' 'avoid AI detection,' 'pass Turnitin,' 'not get flagged by GPTZero,' 'rewrite to not sound like ChatGPT,' 'remove AI voice,' or any indication that the text will be submitted somewhere it would be penalized if flagged as AI-generated. The calibration is tightest for academic-submission detector-risk reduction, but it also applies to other contexts where AI-written text would be a problem, including cover letters, client deliverables, and published writing."
---

# Anti-AI Detection: Writing Text That Reads as Human

## Who This Skill Is For

This skill reduces detector-risk signals while preserving readable, submittable academic prose. It is calibrated for cases where the user is worried about AI-detection tools such as Turnitin, GPTZero, Copyleaks, or Originality.ai. If you want general "sound more human" writing advice without the detection pressure, many of these rules are overcalibrated.

## Detector Reality Check

AI-detection tools are unreliable and can produce false positives, especially on heavily polished, formulaic, or non-native English writing. Grammarly-heavy human text can also get flagged. This means two things: (1) you cannot reliably know whether your text will pass, only lower the risk; (2) over-cleaning can make text _more_ detectable, not less. If the user tells you the text has already been through Grammarly or similar polish tools, expect the detector risk to be higher, not lower.

<!-- Maintainer note: Save this file as UTF-8. It intentionally uses Unicode examples such as en dashes, arrows, and multiplication signs, but avoids literal em dash glyphs in instruction text. -->

Apply these rules during drafting, not as a post-processing step. AI prose regresses to the mean: it is correct, balanced, and predictable. Detection tools exploit this by measuring perplexity (word predictability) and burstiness (sentence length variation). The goal is to break the patterns that make text statistically machine-like, not to introduce errors. The deeper goal is to sound like a specific person thinking through a specific source, not a machine producing balanced coverage.

## Core Prose Standard

Write in plain, specific academic prose.
Do not simulate emphasis with stacked mini-sentences.
If a point can be said in one normal sentence, say it once.
Prefer concrete source detail over rhetorical rhythm.
Each sentence should add meaning, not just cadence.

What helps most:

- Prefer common verbs and nouns over inflated substitutes.
- Do not manufacture short sentences just to vary rhythm.
- Avoid staged rhetorical templates unless they are genuinely needed.
- If a sentence sounds odd when read aloud, rewrite it as normal prose.

---

## HARD BAN: DASH AND COLON HABITS

The em dash is the single most cited indicator of AI text. LLMs use it at 3 to 10 times the rate of human writers. En dashes and colon-heavy explanation patterns have also become common model habits. Colons are especially suspicious when they create a neat "claim: explanation" rhythm, introduce tidy lists, or turn a sentence into a labeled summary.

**Rule: Never use em dashes. Zero. Not one.**

Also avoid en dashes and decorative hyphen breaks in generated prose. Use hyphens only when they are part of a standard spelling, source title, file name, citation detail, URL, or required technical term. Do not use hyphens as a substitute for a pause.

Avoid colons as a default explanation tool. A colon is allowed only when the assignment, citation style, source title, URL, time stamp, ratio, or quoted source requires it. Do not use colon-led structures to sound organized.

- Parenthetical aside: use commas or parentheses
- Introducing an explanation: use a full sentence
- Dramatic pause: use a period and start a new sentence
- Setting off a list: restructure the sentence
- Label plus explanation pattern: rewrite as a normal sentence

---

## VOCABULARY: Words and Phrases to Avoid

### Flagged Vocabulary

**Governing principle:** Prefer concrete verbs and plain nouns over Latinate abstractions and register-inflated substitutes. "Use" not "utilize." "Show" not "showcase." "Help" not "facilitate." If a word would feel stiff said aloud in a normal conversation, it's a candidate for replacement.

The specific list below is calibrated to detection patterns observed through early 2026. Detectors update; models trained against these exact words have shifted to other words. Treat the list as illustrative of the _kind_ of word to avoid, not as the complete set. When in doubt, apply the governing principle.

**High-risk words (early 2026):**
delve, tapestry, landscape (metaphorical), realm, embark, multifaceted, pivotal, underscores, showcasing, highlighting, emphasizing, foster, leverage, utilize, facilitate, enhance, streamline, elevate, robust, seamless

**Contextually risky words (suspicious in clusters):**
crucial, vital, essential (when rotated interchangeably), nuanced, comprehensive, intricate, noteworthy, bustling, enigmatic, captivating, enduring, cornerstone, game-changer, treasure trove, testament to

### Flagged Phrases

- "In today's [adjective] world..."
- "It's worth noting that..." / "It bears mentioning..."
- "Here's why this matters" / "Let's unpack this"
- "At its core..." / "This raises an important question"
- "[Subject] is a testament to..."
- "In an era of..." / "The question isn't X, it's Y"
- "Despite its [positive words], [subject] faces challenges..."
- "I hope this email finds you well"

**Rule:** Use plain, specific language. If you mean "use," write "use." Prefer the word a normal person would say aloud.

---

## SENTENCE STRUCTURE

### Contrastive Negation ("It's Not X, It's Y")

Patterns to avoid: "not just X, but Y," "X goes beyond Y," "X is more than just Y," "it's not about X, it's about Y."

**Rule:** Max one instance per 1,000 words. Prefer direct, affirmative statements. Instead of "It's not about working harder, it's about working smarter," write "Working smarter matters more than working harder."

### Participial Phrase Overuse ("X, doing Y")

Instruction-tuned models use present participial constructions (main clause + comma + -ing phrase) at 2–5× the human rate.

Examples to avoid: "The system processes the data, revealing key patterns" / "She walked through the market, noting the changes."

**Rule:** Max one participial phrase per 300 words. Rewrite as two sentences, or restructure so the -ing clause comes first.

### Correlative Conjunctions

"Not only...but also," "whether...or," "either...or": fine once or twice, a tell when repeated.

**Rule:** Max one correlative conjunction pair per 500 words.

### "From X to Y" Constructions

"From bustling cities to serene landscapes" is a strong tell when repeated.

**Rule:** Avoid unless describing a genuine, concrete range (e.g., "from 1800 to 1850").

### Uniform Sentence Length

AI sentences cluster around 15–20 words. Detection tools measure this as "burstiness."

**Rules:**

- Never write three or more consecutive sentences of similar length
- At least two sentences per page should be under 8 words
- At least one sentence per page should exceed 30 words
- Alternate long and short. The rhythm should feel uneven.

**Anti-mechanical guard:** Short sentences must earn their brevity: end on a point, not a filler. "This matters." earns it. "It was good." doesn't. If you can't find a real reason for a short sentence, rewrite a long one to be longer instead of padding with a short filler. Burstiness from forced filler reads as a different AI tell ("chopped" prose) and some detectors now flag it.

**No fake emphasis chains:** Do not stack clipped mini-sentences to simulate human rhythm. "The board's role is advisory. It can recommend. It cannot compel." sounds synthetic, not natural. If two or three ultra-short declarative sentences appear in a row, combine them into normal prose unless you are quoting speech or source language.

### Semantic Repetition

AI restates the same idea in consecutive sentences using different words, creating an illusion of development where none exists.

Example: "This improves clarity." → "It makes communication clearer." → "The result is easier understanding.": three sentences, one point.

**Rule:** Each sentence must advance the idea, not restate it. If you can delete a sentence without losing any meaning, delete it.

---

## PARAGRAPH PATTERNS

### Argument Development

AI paragraphs often have good sentence-to-sentence flow but weak whole-argument development. Paragraphs circle the same point rather than advancing it; locally coherent, globally flat. This is the hardest tell to fake because fixing it requires actual thinking, not rewriting.

**Rule:** Each paragraph should move the argument forward, not restate the thesis in new clothes. If you can read the first and last paragraph and feel nothing was missed, the middle isn't doing real work.

### Drafting Friction

Human writing contains small irregularities that signal real thinking: an idea qualified mid-sentence, a point that takes longer than expected, an aside that doesn't resolve cleanly. AI text feels "too complete": every thread tied off, no loose ends, no sign of a mind working through difficulty.

**Rule:** Don't smooth everything out. A sentence that trails into qualification, or a paragraph that ends on an unresolved tension, reads more human than one that wraps up neatly.

### The AI Paragraph Template

Almost every AI paragraph follows: (1) topic sentence → (2) supporting detail → (3) more detail → (4) wrap-up or transition. This is a dead giveaway when every paragraph does it.

### Uniform Paragraph Length

AI paragraphs cluster at 3–5 sentences and 60–100 words each.

**Rules:**

- Vary length deliberately. Some paragraphs: 2 sentences. Some: 7 or 8.
- At least one paragraph per page should be one or two sentences.
- Never write four or more consecutive paragraphs of similar length.

### Paragraph Openings

**Rules:**

- Do not begin more than half your paragraphs with a direct topic-sentence claim
- Some should open with evidence, a quotation, a detail, or a question
- Some should build toward the claim rather than stating it first
- Some can open mid-thought, continuing from the previous paragraph

### Paragraph Endings

AI wraps nearly every paragraph with a neat summary or transition. Human writers often just stop.

**Rules:**

- Not every paragraph needs a concluding sentence
- Avoid grand generalizations ("This shows that..." / "Thus, it is clear that...") unless the argument requires them
- Do not end consecutive paragraphs with the same structural move

### The "Challenges" Paragraph

AI frequently produces: "Despite its [positive qualities], [subject] faces challenges..." followed by vague optimism, often as a standalone section near the end.

**Rule:** Avoid this formula entirely. If challenges need discussing, integrate them throughout the argument.

---

## TRANSITIONS: Stop Signposting

AI tells the reader what it is about to do, does it, then tells the reader what it did.

### Avoid:

- "Let's now turn to..." / "Having examined X, we can now consider Y"
- "This brings us to an important point" / "With this in mind..."
- "As we have seen..." / "It is also worth considering..."
- "Another key aspect is..." / "Building on this idea..."

**Rule:** Just start the next point. A paragraph break is itself a transition. When a transition is needed, make it do real work: "The colonial grid replaced this order" is a transition that also makes a claim.

---

## TONE AND VOICE

### Avoid Excessive Hedging

"It could be argued that," "one might suggest," "not without its challenges": these dilute prose. State claims directly. If uncertain, say so plainly once, not in every sentence.

### Avoid Performative Enthusiasm

Not everything is "fascinating," "remarkable," or "striking." If something is interesting, the content should show it.

### Avoid Uniform Tone

AI holds the same register for an entire piece. Allow natural minor shifts: a bit more casual in an aside, more precise in a technical passage, more direct in a strong claim.

### Avoid Balanced Treatment

AI covers every angle equally and wraps every point cleanly. Human writers take positions and spend more time on what interests them.

- Spend more words on the most interesting point, fewer on the obvious one
- You do not need to acknowledge the counterargument to every claim
- Leave some threads loose

### Read It Out Loud

If a sentence sounds like something a person would actually say, it is fine. If it sounds like a press release written by committee, rewrite it.

### Register Bleed-Through

Academic AI output tends to hit one register and hold it, usually "polished undergraduate." Real student writing shifts register as the writer tires or gets interested. Early paragraphs tend to be more careful; later paragraphs get looser, more direct, occasionally sharper. If the essay is long (>1000 words), the last third should read slightly differently from the first third: a bit more direct, a bit less hedged, sentences landing harder. Don't keep the same tight register end-to-end.

---

## THE RULE OF THREE

AI defaults to grouping things in threes because it has learned this is "good writing." It is now a structural tell when overused, but humans use triplets constantly in real prose. The problem is density, not the triplet itself.

**Rules:**

- Do not default to three as the automatic list length. Check whether each list actually has three parts or whether you're rounding to three for rhythm.
- If the essay has multiple triplets within a few paragraphs, break at least half of them. A single triplet is fine; clustered triplets are a tell.
- Be especially alert to the triplet + contrastive negation combo ("not X, Y, or Z, it is about W"). This combo is one of the strongest tells and should appear zero times.

---

## FORMAT-SPECIFIC RULES

### Academic Essays

- No section headers or subheadings unless explicitly requested; essays are continuous prose
- Do not open with a grand sweeping historical claim; start with the specific argument
- Avoid the five-paragraph structure for longer or more complex assignments
- The conclusion should add something (an implication, a qualification, a new connection), not restate the introduction
- Do not begin the conclusion with "In conclusion," "Overall," or "In summary"
- Vary citation integration: sometimes quote mid-sentence, sometimes paraphrase, sometimes lead with the evidence and attribute after
- Include one specific example, piece of evidence, or quotation that requires the kind of engagement a student would actually do (a page-number citation, a specific phrase from a source, a named counterargument). AI-generated essays are unusually abstract: they gesture at evidence rather than work with it. One concrete handle beats three vague ones.

### Emails and Messages

- Keep it short; AI emails are typically 2–3× longer than human ones
- Do not open with "I hope this message finds you well"
- Match the register of the person you are writing to

### Blog Posts and Articles

- Open with a specific anecdote, example, or detail, not a generalization
- Vary paragraph length more than feels comfortable
- Do not end with an inspirational call to action
- Do not include a "Challenges" section followed by a "Future Prospects" section

---

## SELF-CHECK BEFORE DELIVERING

Run these in order. Stop at the first one you fail and fix before continuing.

1. **Dash and colon habits.** Search for em dash U+2014, en dash U+2013, decorative hyphen pauses, and colon-heavy "label: explanation" patterns. Remove all non-required hits.
2. **High-risk vocabulary.** Search for the high-risk word list. Replace every hit.
3. **Contrastive-negation + triplet combo.** Search for "not just," "not only," "it's not about," "isn't about." If any of these appears within two sentences of a three-item list, rewrite.
4. **Paragraph length variance.** If the longest and shortest paragraphs are within 30% of each other, add a very short paragraph (2 sentences) and expand one that deserves more room.
5. **Argument advancement.** Read only the first sentence of each paragraph in order. If the essay still makes sense and nothing feels missed, the paragraphs aren't advancing the argument; they're restating it. Fix the middle paragraphs.
6. **Concrete engagement.** Is there at least one specific piece of evidence (named source, exact phrase, page number, concrete example) that would require real reading? If not, add one.
7. **Read three random paragraphs aloud.** If any sentence sounds like corporate prose or a textbook summary, rewrite it.
