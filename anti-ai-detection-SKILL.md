---
name: anti-ai-detection
description: "Use this skill when the user is writing academic or submitted work (essays, papers, application materials, reports) that needs to reduce AI-detection risk from tools like Turnitin, GPTZero, Copyleaks, or Originality.ai while remaining readable and submittable. Trigger phrases include 'make it sound human,' 'avoid AI detection,' 'pass Turnitin,' 'not get flagged by GPTZero,' 'rewrite to not sound like ChatGPT,' 'remove AI voice,' or any indication that the text will be submitted somewhere it would be penalized if flagged as AI-generated. The calibration is tightest for academic-submission detector-risk reduction, but it also applies to other contexts where AI-written text would be a problem, including cover letters, client deliverables, and published writing."
---

# Anti-AI Detection: Writing Text That Reads as Human

## Who This Skill Is For

This skill reduces detector-risk signals while preserving readable, submittable academic prose. It is calibrated for cases where the user is worried about AI-detection tools such as Turnitin, GPTZero, Copyleaks, or Originality.ai.

## Detector Reality Check

AI-detection tools are unreliable and can produce false positives, especially on heavily polished, formulaic, or non-native English writing. Grammarly-heavy human text can also get flagged.

AI prose regresses to the mean: it is correct, balanced, and predictable. Detection tools exploit this by measuring perplexity (word predictability) and burstiness (sentence length variation). The goal is to break the patterns that make text statistically machine-like, not to introduce errors. The deeper goal is to sound like a specific person thinking through a specific source, not a machine producing balanced coverage.

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

The em dash is the single most cited indicator of AI text. En dashes and colon-heavy explanation patterns have also become common model habits. Colons are especially suspicious when they create a neat "claim: explanation" rhythm, introduce tidy lists, or turn a sentence into a labeled summary.

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

**Anti-mechanical guard:** Short sentences must earn their brevity: end on a point, not a filler. "This matters." earns it. "It was good." doesn't. If you can't find a real reason for a short sentence, rewrite a long one to be longer instead of padding with a short filler. Burstiness from forced filler reads as a different AI tell ("chopped" prose) and some detectors now flag it. Similarly, do not manufacture burstiness by splitting long compound sentences into fragments. If the user's natural writing style favors long sentences with conjunctions and parenthetical asides, preserve that rhythm. Artificial shortening is as detectable as artificial uniformity.

**No fake emphasis chains:** Do not stack clipped mini-sentences to simulate human rhythm. "The board's role is advisory. It can recommend. It cannot compel." sounds synthetic, not natural. If two or three ultra-short declarative sentences appear in a row, combine them into normal prose unless you are quoting speech or source language.

### Over-Chopping (Splitting Natural Clauses)

LLMs often compensate for uniform sentence length by splitting one continuous observation into two short sentences. This creates its own AI tell. If two clauses share a subject, continue the same observation, or would sound natural when spoken together, keep them together. Use a conjunction, semicolon, parenthetical aside, or another normal sentence shape rather than chopping the thought apart just to create variation.

**Rule:** Before splitting a sentence in two, check whether the clauses belong to the same line of thought. If they do, keep them together. Short sentences should exist because the thought is genuinely short, not because a longer sentence was mechanically broken apart.

### Stacked Mini-Sentence Endings

LLMs often end paragraphs with two or three clipped declarative sentences meant to land with rhetorical force. "They do not face the street. They ignore it." and "This was not a plan. It was an erasure." both read as manufactured emphasis. If the final observation is worth making, fold it into the preceding sentence or cut it.

**Rule:** Do not end a paragraph with two or more consecutive sentences under 8 words unless quoting source language. One short closing sentence is fine. Two in a row is a tell.

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

### Preserve Informal Academic Tics

Human academic writers often have small habits that polished LLM prose removes: trailing qualifications, casual sentence openers, slight shorthand, parenthetical "etc," and other low-stakes irregularities. These can be useful human signals when they are genuinely part of the writer's voice.

**Rule:** If the user's writing samples contain these tics, preserve them. Do not clean them out just to make the prose sound smoother. Do not invent them if they are absent from the user's normal writing or inappropriate for the assignment.

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

## Additional High-Risk Patterns

Apply these in order: first calibrate to the user's actual voice, then remove inflated wording, then fix sentence-pattern tells, then force source specificity, then check the ending.

### Voice Calibration

Detection tools measure how much your text resembles the average output of an LLM. The best defense is text that resembles you specifically, not "human writing in general." Generic "human-sounding" output produced by following anti-AI rules still comes from the same underlying probability distribution as the AI text it is replacing, and detectors can pick that up.

**Rule:** Before rewriting any submitted academic work, the user should provide 2 to 3 paragraphs of their own writing from another context (a different class, a personal email, a journal entry). The rewrite should match the user's actual sentence rhythm, word choices, hedging habits, and structural quirks rather than producing generic clean prose. If the user's samples show long, conjunction-heavy sentences with embedded parenthetical asides, the rewrite must preserve that habit even when other rules in this document push toward shorter sentences. The user's voice wins over statistical targets. If no sample is provided, ask for one before doing a heavy rewrite.

### Copula Avoidance

LLMs systematically avoid plain "is," "are," "was," and "has." They reach for inflated substitutes that gesture at function or role: "serves as," "functions as," "acts as," "stands as," "represents," "constitutes," "embodies," "operates as." Detectors notice this because human writers default to plain copulas and only reach for the inflated version when the meaning genuinely requires it.

**Rule:** Default to "is," "are," "was," "has." Use "serves as," "functions as," "acts as," "represents," and similar only when the inflated verb carries meaning the plain copula would lose. If "is" works, use "is."
Examples:

"The board acts as an arbiter" → "The board is an arbiter"
"The resolution functions as a counter-plan" → "The resolution is a counter-plan"
"Village Preservation served as an advocate" → "Village Preservation was the advocate"

### Filler Phrases

LLMs use multi-word phrases where a single word works. "In order to" instead of "to." "Due to the fact that" instead of "because." "At this point in time" instead of "now." "In the event that" instead of "if." "For the purpose of" instead of "for." "With regard to" instead of "about."

**Rule:** Replace multi-word filler with the shortest equivalent. "To," "because," "now," "if," "for," "about." This single substitution tightens prose more than almost any other edit.

### Significance Inflation

LLMs frame their own observations as important rather than letting the content demonstrate importance. Tells include: "the most important," "the key issue," "deserves attention," "worth noting," "the crucial point," "matters here," "the heart of the matter," "what is striking," "what is notable."

**Rule:** Cut self-importance framing. State the observation directly without telling the reader it is significant. If the point is significant, the prose will show it. If the prose does not show it, adding "this is important" will not fix the prose.
Examples:

"The most important policy finding is that the project produces fewer units" → "The project produces fewer units"
"What deserves attention here is the two-building design" → "The two-building design splits..."

### Synonym Cycling

LLMs avoid repeating the same noun and reach for variants: protagonist becomes "main character" becomes "central figure" becomes "hero." This is taught as good style in school but is actually a strong AI tell, because real writers repeat the clearest word. The variants often introduce small meaning shifts the writer didn't intend.

**Rule:** Repeat the clearest noun rather than cycling through synonyms. "Building" stays "building." "Developer" stays "developer." "Board" stays "board." Vary only when the alternate word carries meaningfully different information (e.g., "the building" vs. "the proposal" vs. "the project" if those genuinely refer to different things).

### False Ranges

LLMs love "from X to Y" constructions to suggest comprehensive coverage. "From bustling cities to serene landscapes," "from solo developers to enterprise teams," "from a member of Congress to city council members." The pattern signals comprehensiveness without actually establishing it, and detectors flag it.

**Rule:** Use "from X to Y" only when describing a literal range with a clear axis (years, distances, dollar amounts, temperatures). For lists of items, just list the items. "Representatives from a congressional office and several council offices" is better than "spanning every level from a member of Congress to council members."

### Superficial -ing Analyses

LLMs string together present participles to fake analytical depth: "showcasing," "highlighting," "reflecting," "symbolizing," "underscoring," "demonstrating," "illustrating," "embodying." These verbs claim that something means something without doing the work of showing how.

**Rule:** Cut "showcasing," "highlighting," "reflecting," "symbolizing," "underscoring," "demonstrating," "illustrating," "embodying" when used as present participles attached to a main clause. Either delete the participle phrase entirely or rewrite as a separate sentence that actually argues for the connection.
Example:

"The two-building design splits the project, reflecting the developer's wage strategy" → "The two-building design splits the project. The reason is wages."

### Vague Attributions

LLMs cite generic authorities to add weight without committing to a source. "Experts believe," "studies show," "industry observers note," "scholars argue," "many have suggested," "it is widely understood." Real academic writing names the specific source.

**Rule:** Either name the specific source ("Arnstein argues," "the board's resolution states," "Davidoff writes in his 1965 article") or remove the attribution and state the claim directly. Never use "experts," "scholars," "observers," or "many" as the subject of a sentence.

### Generic Conclusions

LLMs end with vague forward-looking statements: "The future looks bright," "exciting times lie ahead," "much remains to be seen," "only time will tell," "the implications will continue to unfold." These are filler that sounds like a conclusion without making any actual claim.

**Rule:** End on a specific claim or a specific question, never on a forward-looking generality. If the essay has nothing specific to say at the end, the essay is not done. "Whether the LPC acts on the recommendation remains to be seen" is borderline acceptable only because the LPC is named and the action is concrete. "Time will tell whether community participation matters" would not be acceptable.

---

## Paragraph-Level Before/After Gallery

Rules in the abstract are easy to ignore. The samples below show the exact rewrites this skill expects. Pattern-match against them when revising.

### Example 1: Uniform topic-sentence paragraph shape

**Before (AI-flagged at high confidence):**

> The algorithm itself operates on two static objects before the dynamic-programming pass begins. The first is the local cost matrix C, where each entry stores a pairwise distance. The matrix is, in effect, a heatmap of similarity, and the alignment task amounts to finding a route through its low-cost valleys. The second is the warping path, a sequence of cells through C that must satisfy three conditions: boundary, monotonicity, and step size.

What flags it: opens with the topic sentence, every subsequent sentence supports it, ends on a tidy parallel-structure summary. Locally coherent, globally flat.

**After (real-writer rhythm):**

> Two objects matter before the dynamic-programming pass begins. The local cost matrix C stores every pairwise distance between the two sequences, so cell (i, j) reports how unlike x_i and y_j are. Think of C as a similarity heatmap whose low-cost valleys mark candidate alignments. On top of C the algorithm carves a warping path, which is a list of cells the alignment will actually use. That path is not free; it has to start at one corner, end at the other, never move backward, and never jump.

What changed: opener leads with the noun count, not a topic claim. The middle adds a worked-example reading ("Think of C as..."). The close lands on a concrete constraint list, not a parallel-structure paraphrase of the opener.

### Example 2: Paragraph-length variance

**Before (uniform 100-150 word paragraphs throughout):**

> [Paragraph 1, 130 words.] [Paragraph 2, 140 words.] [Paragraph 3, 125 words.] [Paragraph 4, 135 words.] ...

What flags it: even paragraph rhythm reads as machine output regardless of content.

**After (real-writer variance):**

> [Paragraph 1, 130 words, sets up the problem.]
>
> Then a beat. One sentence.
>
> [Paragraph 3, 220 words, the deep dive.] [Paragraph 4, 60 words, a short pivot.] [Paragraph 5, 150 words, the close.]

What changed: at least one paragraph is two sentences. One paragraph runs much longer than the others because the writer cared more about it.

### Example 3: Filler removal

**Before:** "In order to make the algorithm tractable, the designers introduced global constraints. In essence, these constraints define a feasible region around the diagonal. Essentially, only paths inside this region are evaluated."

**After:** "To make the algorithm tractable, the designers introduced global constraints. These constraints define a feasible region around the diagonal. Only paths inside the region are evaluated."

What changed: "in order to" → "to". Deleted "In essence,". Deleted "Essentially,". Three filler hits go away without changing the meaning.

### Example 4: Significance inflation

**Before:** "The most important consequence is that the recurrence runs in O(NM) time. What is striking here is that this matches the cost of the matrix fill itself, which deserves attention because it bounds the algorithm's scaling."

**After:** "The recurrence runs in O(NM) time, which matches the matrix-fill cost and bounds how the algorithm scales."

What changed: deleted "The most important consequence is", deleted "What is striking here is that", deleted "which deserves attention because". The point survives and the sentence is faster.

### Example 5: Vague attribution → named source

**Before:** "Experts believe that DTW is poorly suited to indexing because it does not obey the triangle inequality. Studies show that this limits its use in time-series databases."

**After:** "Senin notes that DTW does not obey the triangle inequality, which is what limits its use in indexing schemes for time-series databases (p. 19)."

What changed: "Experts believe" → "Senin notes". Removed "Studies show that". Added a page reference as a concrete handle.

### Example 6: Generic forward-looking closing

**Before:** "Only time will tell how the field will continue to develop, but the implications for time-series analysis will only continue to unfold."

**After:** "The successor algorithm the report names (CSDTW) bolts a hidden-Markov-model layer onto DTW, which is the review's tacit admission that the basic recurrence is a starting point and not an endpoint."

What changed: vague futurology replaced with a specific named successor and a specific judgment about what its existence implies.

---

## How to Use This Skill in a Schema-Constrained Stage

If your output JSON has an `anti_ai_self_check` field, populating that object IS how you run this skill. The expected workflow at generation time:

1. Write the draft.
2. Re-read it once.
3. List the first sentence of every paragraph in `paragraph_first_sentences`. Read the list alone. If it summarizes the essay, your middle paragraphs are restating, not advancing. Rewrite at least one middle paragraph before you finalize.
4. Count `paragraph_count` and `paragraphs_under_50_words`. If the essay is >1000 words and `paragraphs_under_50_words == 0`, add a short paragraph.
5. Search your text for every entry in the filler-phrases list. Put any you used in `filler_phrases_used`. If the list is non-empty, rewrite to remove them.
6. Search for every entry in the significance-inflation list. Same drill into `significance_inflation_phrases`.
7. Search for vague-authority subjects ("experts believe", "studies show"). Same drill into `vague_attributions_used`.
8. List every concrete source handle the prose actually contains (page numbers, named-source-plus-date parentheticals, quoted phrases of 8+ characters) in `concrete_source_handles`. If empty, add at least one.
9. For each bullet in `<style_guidance_checklist>`, fill one `style_guidance_grades` row. `followed: true` requires a `where` quote or paragraph reference.
10. If you removed any phrases during this pass, note them briefly in `self_check_notes` so the validator can confirm you actually ran the check.

A response with everything at zero / empty / true-without-evidence is treated as a failed audit.

