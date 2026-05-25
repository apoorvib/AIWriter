from __future__ import annotations

TIER1_FLAGGED_VOCAB: tuple[str, ...] = (
    "delve",
    "tapestry",
    "landscape",
    "realm",
    "embark",
    "multifaceted",
    "pivotal",
    "underscores",
    "showcasing",
    "highlighting",
    "emphasizing",
    "foster",
    "leverage",
    "utilize",
    "facilitate",
    "enhance",
    "streamline",
    "elevate",
    "robust",
    "seamless",
)

TIER2_FLAGGED_VOCAB: tuple[str, ...] = (
    "crucial",
    "vital",
    "essential",
    "nuanced",
    "comprehensive",
    "intricate",
    "noteworthy",
    "bustling",
    "enigmatic",
    "captivating",
    "enduring",
    "cornerstone",
    "game-changer",
    "treasure trove",
    "testament to",
)

FLAGGED_PHRASES: tuple[str, ...] = (
    "in today's",
    "it's worth noting",
    "it bears mentioning",
    "here's why this matters",
    "let's unpack this",
    "at its core",
    "this raises an important question",
    "is a testament to",
    "in an era of",
    "the question isn't",
    "i hope this email finds you well",
)

SIGNPOSTING_PHRASES: tuple[str, ...] = (
    "let's now turn to",
    "let us now turn to",
    "having examined",
    "having explored",
    "this brings us to",
    "as we have seen",
    "it is also worth considering",
    "another key aspect is",
    "building on this idea",
    "with this in mind",
    "turning now to",
    "let's now consider",
    "let us now consider",
)

BAD_CONCLUSION_OPENERS: tuple[str, ...] = (
    "in conclusion",
    "in summary",
    "to summarize",
    "to conclude",
    "overall,",
)

# Multi-word phrases that AI models reach for in place of the shortest equivalent.
# Detected case-insensitively as substrings. See anti-AI skill, "Filler Phrases" section.
FILLER_PHRASES: tuple[str, ...] = (
    "in order to",
    "due to the fact that",
    "at this point in time",
    "in the event that",
    "for the purpose of",
    "with regard to",
    "in light of the fact that",
    "in spite of the fact that",
    "a number of",
    "the fact that",
    "in essence",
    "in effect",
    "essentially,",
    "fundamentally,",
    "ultimately,",
    "as a matter of fact",
)

# Phrases that frame the model's own observation as important rather than letting the
# content demonstrate importance. See anti-AI skill, "Significance Inflation" section.
SIGNIFICANCE_INFLATION_PHRASES: tuple[str, ...] = (
    "the most important",
    "the key issue",
    "deserves attention",
    "worth noting",
    "the crucial point",
    "matters here",
    "the heart of the matter",
    "what is striking",
    "what is notable",
    "it is important to",
    "it is essential to",
    "what is interesting",
    "the binding constraint",
    "tacit acknowledgment",
    "deceptively flat",
    "it is worth",
    "it bears",
)

# Generic-authority subjects the model uses to add weight without naming a source.
# See anti-AI skill, "Vague Attributions" section.
VAGUE_ATTRIBUTION_SUBJECTS: tuple[str, ...] = (
    "experts believe",
    "experts argue",
    "experts say",
    "studies show",
    "studies suggest",
    "research shows",
    "research suggests",
    "scholars argue",
    "scholars believe",
    "scholars have suggested",
    "observers note",
    "industry observers",
    "many have suggested",
    "many believe",
    "many argue",
    "it is widely",
    "it is generally",
)

# Forward-looking generalities AI models use to close pieces. See anti-AI skill,
# "Generic Conclusions" section.
GENERIC_CLOSING_PHRASES: tuple[str, ...] = (
    "the future looks bright",
    "exciting times lie ahead",
    "much remains to be seen",
    "only time will tell",
    "implications will continue to unfold",
    "implications will only continue",
    "remains to be seen whether",
    "the road ahead",
    "time will tell",
    "lies ahead",
)

# Common AI paragraph-opener words. We do not ban them, but we count paragraphs
# whose opening token falls into this set to flag a uniform-shape pattern.
TOPIC_SENTENCE_OPENERS: tuple[str, ...] = (
    "the",
    "this",
    "we",
    "a",
    "an",
    "these",
    "those",
)
