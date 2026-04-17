from pdf_pipeline.outline.prefilter import looks_like_toc


def test_detects_contents_heading():
    text = "Contents\n\nChapter 1 ....... 1\nChapter 2 ....... 15"
    assert looks_like_toc(text) is True


def test_detects_table_of_contents_heading():
    assert looks_like_toc("TABLE OF CONTENTS\n\nIntroduction ... 1") is True


def test_detects_dot_leader_lines():
    text = "\n".join(
        [
            "Preface ..................... 3",
            "Introduction ............... 7",
            "Chapter 1: Origins ......... 12",
            "Chapter 2: Methods ......... 45",
        ]
    )
    assert looks_like_toc(text) is True


def test_detects_many_short_lines_ending_in_numbers():
    lines = [f"Section {i}    {i * 3}" for i in range(1, 12)]
    text = "\n".join(lines)
    assert looks_like_toc(text) is True


def test_rejects_narrative_text():
    text = (
        "This chapter explores the nature of algorithms. We begin by "
        "considering the question of what it means for a computation to "
        "terminate and how we might measure its complexity."
    )
    assert looks_like_toc(text) is False


def test_rejects_empty_text():
    assert looks_like_toc("") is False
