---
name: anti-ai-detection
description: "Use this skill when the user is writing academic or submitted work (essays, papers, application materials, reports) that needs to reduce AI-detection risk from tools like Turnitin, GPTZero, Copyleaks, or Originality.ai while remaining readable and submittable. Trigger phrases include 'make it sound human,' 'avoid AI detection,' 'pass Turnitin,' 'not get flagged by GPTZero,' 'rewrite to not sound like ChatGPT,' 'remove AI voice,' or any indication that the text will be submitted somewhere it would be penalized if flagged as AI-generated. The calibration is tightest for academic-submission detector-risk reduction, but it also applies to other contexts where AI-written text would be a problem, including cover letters, client deliverables, and published writing."
---

# Anti-AI Detection: Writing Text That Reads as Human

## Reality Check

AI prose regresses to the mean: correct, balanced, predictable. Detection tools exploit this by measuring perplexity (word predictability) and burstiness (sentence-length variation). The goal is to break these patterns and sound like a specific human thinking through a specific source, not a machine producing balanced coverage.

## Core Prose Standard

Write in plain, specific prose. Say a point once, in one normal sentence, and let concrete source detail carry it rather than rhetorical rhythm. Every sentence should add meaning, not cadence. If a sentence sounds odd read aloud, rewrite it as normal prose.

## How to use these rules

Each rule below has a stable ID (`R1`, `R2`, …) and is a single, self-contained unit: one directive, and where useful one before/after example. The rules are the audit surface. Apply the whole set while drafting, then run the ordered Self-Check at the end and stop at the first failure. When two rules conflict, precedence is: the user's own writing sample > factual accuracy > explicit assignment instructions > these rules. `R21` (voice calibration) overrides every statistical rule here.

Vocabulary and phrase lists are calibrated to detector patterns observed through early 2026. Treat them as illustrative of the *kind* of word or phrase to avoid, not a closed set; when in doubt, apply the governing principle in the rule.

---

## Mechanical bans

**R1 — No em dashes or en dashes.** Never use em dashes (U+2014) or en dashes (U+2013), and do not use decorative hyphen breaks as a pause. Use a hyphen only when it is part of a standard spelling, source title, file name, citation detail, URL, or required technical term.

**R2 — No decorative colons.** Do not use a colon as a default explanation or organization tool ("label: explanation"). A colon is allowed only when a citation style, source title, URL, timestamp, ratio, or quoted source requires it. For an aside use commas or parentheses; for an explanation use a full sentence; for a dramatic pause use a period.

## Vocabulary and phrasing

**R3 — Prefer plain words over inflated substitutes.** Prefer concrete verbs and plain nouns over Latinate abstractions. "Use" not "utilize," "show" not "showcase," "help" not "facilitate." If a word would feel stiff said aloud, replace it. High-risk words (early 2026): *delve, tapestry, landscape (metaphorical), realm, embark, multifaceted, pivotal, underscores, showcasing, highlighting, emphasizing, foster, leverage, utilize, facilitate, enhance, streamline, elevate, robust, seamless, quietly, silently.* Risky in clusters: *crucial, vital, essential, nuanced, comprehensive, intricate, noteworthy, bustling, enigmatic, captivating, enduring, cornerstone, game-changer, treasure trove, testament to.*

**R4 — Cut canned opener and framing phrases.** Avoid: "In today's [adjective] world…," "It's worth noting that…," "It bears mentioning…," "Here's why this matters," "Let's unpack this," "At its core…," "This raises an important question," "[Subject] is a testament to…," "In an era of…," "The question isn't X, it's Y," "Despite its [positives], [subject] faces challenges…," "I hope this email finds you well."

**R5 — Replace multi-word filler with one word.** "In order to" → "to." "Due to the fact that" → "because." "At this point in time" → "now." "In the event that" → "if." "For the purpose of" → "for." "With regard to" → "about." This single pass tightens prose more than almost any other edit.

## Sentence-level constructions

**R6 — No contrastive negation.** Avoid "not just X but Y," "X goes beyond Y," "X is more than just Y," "it's not about X, it's about Y." Prefer a direct affirmative. *"It's not about working harder, it's about working smarter"* → *"Working smarter matters more than working harder."*

**R7 — No participial / -ing tack-ons.** Avoid the main-clause-plus-comma-plus-"-ing" construction and the "showcasing / highlighting / reflecting / underscoring / demonstrating / embodying" participle. Delete the participle phrase or rewrite it as a sentence that actually argues the connection. *"The two-building design splits the project, reflecting the developer's wage strategy"* → *"The two-building design splits the project. The reason is wages."*

**R8 — Ration correlative conjunctions.** "Not only…but also," "whether…or," "either…or" are fine once; a tell when repeated. Max one pair per 500 words.

**R9 — Default to the plain copula.** Use "is," "are," "was," "has." Avoid "serves as," "functions as," "acts as," "represents" unless the inflated verb carries meaning "is" would lose. *"The board acts as an arbiter"* → *"The board is an arbiter."*

**R10 — No false ranges.** Use "from X to Y" only for a literal range with a clear axis (years, distances, dollar amounts, temperatures). For a list of items, list the items. *"spanning every level from a member of Congress to council members"* → *"representatives from a congressional office and several council offices."*

**R11 — Break the rule of three.** Do not default to triplets. Check whether a list genuinely has three parts or is rounded to three for rhythm; if several triplets cluster within a few paragraphs, break at least half. The triplet-plus-contrastive-negation combo ("not X, Y, or Z, it is about W") is one of the strongest tells and should appear zero times.

## Length and rhythm

**R12 — Vary sentence length; never cluster.** Never write three or more consecutive sentences of similar length. Alternate long and short so the rhythm feels uneven. Do not enforce this with per-page quotas or by counting words to a target; vary because the meaning calls for it.

**R13 — Short sentences must earn their brevity.** A short sentence should land a real point, not fill a slot. Do not stack clipped mini-sentences to fake human rhythm (*"The board's role is advisory. It can recommend. It cannot compel."* reads synthetic) and do not end paragraphs with two or three clipped declaratives for rhetorical force. Fold the observation into the preceding sentence or cut it. Equally, do not over-chop: if two clauses belong to the same line of thought, keep them in one sentence.

**R14 — Vary paragraph length; never cluster.** Never write four or more consecutive paragraphs of similar length. Let some run two sentences and some run seven or eight, driven by how much the point deserves.

## Paragraph structure

**R15 — Every sentence and paragraph must advance the argument.** Do not restate the same idea in new words (*"This improves clarity" → "It makes communication clearer" → "The result is easier understanding"* is one point three times). If you can delete a sentence without losing meaning, delete it. If the first and last paragraph read as complete and nothing feels missed, the middle paragraphs are restating the thesis, not developing it.

**R16 — Break the AI paragraph template.** Not every paragraph should run topic sentence → detail → detail → wrap-up. Open some paragraphs with evidence, a quotation, a detail, or a question; let some build toward the claim; let some continue mid-thought from the previous paragraph. Fewer than half of your paragraphs should open with a direct topic-sentence claim.

**R17 — Vary paragraph endings.** Not every paragraph needs a concluding sentence. Avoid grand generalizations ("This shows that…," "Thus, it is clear that…") unless the argument requires them, and do not end consecutive paragraphs with the same structural move.

**R18 — Keep some drafting friction.** Do not smooth everything out. A sentence that trails into qualification, or a paragraph that ends on unresolved tension, reads more human than one that wraps up neatly.

**R19 — No standalone "Challenges" formula.** Avoid "Despite its [positive qualities], [subject] faces challenges…" followed by vague optimism, especially as its own section near the end. If challenges matter, integrate them throughout the argument.

## Transitions

**R20 — Stop signposting.** Cut "Let's now turn to…," "Having examined X, we can now consider Y," "This brings us to an important point," "With this in mind…," "As we have seen…," "Another key aspect is…," "Building on this idea…." Just start the next point; a paragraph break is itself a transition. When a transition is needed, make it carry a claim: *"The colonial grid replaced this order."*

## Tone and voice

**R21 — The user's voice wins.** When the user provides writing samples, match their actual rhythm, word choices, and quirks, and preserve their informal tics (trailing qualifications, casual openers, parenthetical "etc.") rather than smoothing them out. Do not invent tics that are absent from their normal writing. With no sample, ask for two or three short paragraphs before a heavy rewrite. This rule overrides every statistical rule above.

**R22 — Cut significance inflation.** State the observation directly instead of announcing that it matters. *"The most important policy finding is that the project produces fewer units"* → *"The project produces fewer units."* *"What deserves attention here is the two-building design"* → *"The two-building design splits…"* If the prose does not show the point is significant, "this is important" will not fix it.

**R23 — Do not over-hedge.** State claims directly. Avoid "it could be argued that," "one might suggest," "not without its challenges." If genuinely uncertain, say so plainly once, not in every sentence.

**R24 — No performative enthusiasm.** Not everything is "fascinating," "remarkable," or "striking." If something is interesting, let the content show it.

**R25 — No synonym cycling.** Repeat the clearest noun rather than rotating synonyms. "Building" stays "building," "board" stays "board." Vary only when the alternate word carries genuinely different information (the building vs. the proposal vs. the project, when those refer to different things).

**R26 — No vague attributions.** Name the specific source ("Arnstein argues," "the board's resolution states," "Davidoff writes in his 1965 article") or state the claim directly. Never use "experts," "scholars," "observers," or "many" as the subject of a sentence.

**R27 — Take a position; do not treat everything equally.** Do not cover every angle evenly and wrap every point cleanly. Spend more words on the most interesting point and fewer on the obvious one, skip the counterargument to every claim, and allow the register to shift naturally (more casual in an aside, more precise in a technical passage). Leave some threads loose.

**R28 — End on something specific.** Close on a specific claim or question, never a forward-looking generality. *"Whether the LPC acts on the recommendation remains to be seen"* is borderline acceptable only because the LPC is named and the action is concrete. *"Time will tell whether community participation matters"* is not.

## Format-specific rules

**R29 — Academic essays.** Continuous prose, no section headers unless requested. Do not open with a sweeping historical claim; start with the specific argument. Avoid the five-paragraph structure for longer or complex assignments. The conclusion should add an implication, qualification, or connection and must not begin with "In conclusion," "Overall," or "In summary." Vary citation integration (quote mid-sentence, paraphrase, or lead with the evidence and attribute after), and include at least one concrete handle — a page number, an exact phrase, a named counterargument — that requires real reading. One concrete handle beats three vague gestures.

**R30 — Emails and messages.** Keep it short; AI emails run two to three times longer than human ones. Do not open with "I hope this message finds you well." Match the register of the recipient.

**R31 — Blog posts and articles.** Open with a specific anecdote, example, or detail, not a generalization. Vary paragraph length more than feels comfortable. Do not end with an inspirational call to action, and do not pair a "Challenges" section with a "Future Prospects" section.

---

## Self-Check Before Delivering

Run in order. Stop at the first failure, fix it, then continue.

1. **Dashes and colons (R1, R2).** Search for em dash U+2014, en dash U+2013, decorative hyphen pauses, and "label: explanation" colons. Remove all non-required hits.
2. **High-risk vocabulary (R3, R5).** Search for the high-risk word list and the filler phrases. Replace every hit.
3. **Contrastive-negation + triplet combo (R6, R11).** Search for "not just," "not only," "it's not about," "isn't about." If any appears within two sentences of a three-item list, rewrite.
4. **Length variance (R12, R14).** If the longest and shortest paragraphs are within 30% of each other, add a very short paragraph and expand one that deserves more room. Confirm no run of three similar-length sentences or four similar-length paragraphs.
5. **Argument advancement (R15).** Read only the first sentence of each paragraph in order. If nothing feels missed, the middle paragraphs are restating, not advancing; fix them.
6. **Concrete engagement (R29).** Confirm at least one specific piece of evidence (named source, exact phrase, page number, concrete example) that would require real reading. If absent, add one.
7. **Read aloud.** Read three random paragraphs aloud. If any sentence sounds like corporate prose or a textbook summary, rewrite it.
