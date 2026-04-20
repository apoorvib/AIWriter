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
