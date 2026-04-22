from __future__ import annotations

from essay_writer.validation.checks import run_deterministic_checks


def test_em_dash_detected():
    text = "This is important — and so is this — clearly."
    result = run_deterministic_checks(text)
    assert result.em_dash_count == 2


def test_em_dash_clean():
    result = run_deterministic_checks("No em dashes here at all.")
    assert result.em_dash_count == 0


def test_tier1_vocab_detected():
    text = "We should delve into the tapestry of evidence and leverage our tools to foster growth."
    result = run_deterministic_checks(text)
    hits = {h.word: h.count for h in result.tier1_vocab_hits}
    assert hits.get("delve") == 1
    assert hits.get("tapestry") == 1
    assert hits.get("leverage") == 1
    assert hits.get("foster") == 1


def test_tier1_vocab_case_insensitive():
    result = run_deterministic_checks("This DELVE into Robust solutions.")
    hits = {h.word for h in result.tier1_vocab_hits}
    assert "delve" in hits
    assert "robust" in hits


def test_tier1_vocab_clean():
    result = run_deterministic_checks("The analysis shows a clear relationship between income and health outcomes.")
    assert result.tier1_vocab_hits == []


def test_tier1_vocab_counts_multiple_occurrences():
    result = run_deterministic_checks("We utilize this and utilize that.")
    hits = {h.word: h.count for h in result.tier1_vocab_hits}
    assert hits.get("utilize") == 2


def test_bad_conclusion_opener_in_conclusion():
    text = "Some body text.\n\nIn conclusion, this essay has shown that climate change is real."
    result = run_deterministic_checks(text)
    assert result.bad_conclusion_opener is True


def test_bad_conclusion_opener_overall():
    text = "Some body text.\n\nOverall, the evidence supports the thesis."
    result = run_deterministic_checks(text)
    assert result.bad_conclusion_opener is True


def test_bad_conclusion_opener_in_summary():
    text = "Some body text.\n\nIn summary, these findings demonstrate the point."
    result = run_deterministic_checks(text)
    assert result.bad_conclusion_opener is True


def test_bad_conclusion_opener_clean():
    text = "Some body text.\n\nThe evidence suggests that further research is needed."
    result = run_deterministic_checks(text)
    assert result.bad_conclusion_opener is False


def test_consecutive_similar_sentences_triggers():
    # Four sentences, all 7 words — should trigger a run of 4
    text = (
        "The cat sat on the mat quietly. "
        "The dog ran through the park quickly. "
        "The bird flew over the hill slowly. "
        "The fish swam under the water deeply."
    )
    result = run_deterministic_checks(text)
    assert len(result.consecutive_similar_sentence_runs) > 0
    assert result.consecutive_similar_sentence_runs[0].sentence_count >= 3


def test_consecutive_similar_sentences_clean():
    # Deliberately varied: short, long, short, long
    text = (
        "Stop. "
        "The industrial revolution fundamentally transformed the relationship between labor and capital across Europe. "
        "Consider this. "
        "Economic historians have argued for decades that these changes were both inevitable and deeply contingent on local conditions."
    )
    result = run_deterministic_checks(text)
    assert len(result.consecutive_similar_sentence_runs) == 0


def test_participial_phrase_rate_high():
    # 4 participial phrases in ~60 words = rate well above 1 per 300 words
    text = (
        "She walked to the store, buying milk on the way. "
        "He sat at his desk, writing code for hours. "
        "They went to the park, playing games until dark. "
        "We met at noon, discussing plans for the project."
    )
    result = run_deterministic_checks(text)
    assert result.participial_phrase_count == 4
    assert result.participial_phrase_rate > 1.0


def test_participial_phrase_rate_low():
    # One participial phrase in 400+ words keeps rate below 1 per 300 words
    text = "She walked to the store, buying milk. " + ("The analysis showed a clear and consistent relationship between the variables. " * 40)
    result = run_deterministic_checks(text)
    assert result.participial_phrase_rate <= 1.0


def test_contrastive_negation_detected():
    text = "It's not about the money, it's about the mission. Not just fast, but reliable."
    result = run_deterministic_checks(text)
    assert result.contrastive_negation_count >= 2


def test_contrastive_negation_clean():
    result = run_deterministic_checks("The evidence supports this claim directly.")
    assert result.contrastive_negation_count == 0


def test_signposting_detected():
    text = "Having examined the evidence, we can now consider the implications."
    result = run_deterministic_checks(text)
    assert len(result.signposting_hits) > 0


def test_signposting_clean():
    result = run_deterministic_checks("The results point in a different direction.")
    assert result.signposting_hits == []


def test_word_count():
    result = run_deterministic_checks("The quick brown fox jumps over the lazy dog.")
    assert result.word_count == 9


def test_has_issues_true_when_em_dash_present():
    result = run_deterministic_checks("This is important — noted.")
    assert result.has_issues is True


def test_has_issues_false_for_clean_text():
    # Varied sentence lengths, no flagged vocab, no participial phrases, no em dashes, no signposting
    text = (
        "Stop.\n\n"
        "Arctic temperatures have risen four times faster than the global average over the last fifty years. "
        "This acceleration is not uniform: some regions have warmed at twice that rate. "
        "The permafrost holds an estimated 1.5 trillion tons of carbon.\n\n"
        "That number should give us pause.\n\n"
        "If even a fraction of that carbon is released into the atmosphere, "
        "the feedback effects will outpace any mitigation effort currently on the table. "
        "Policy has not kept pace with what the science requires."
    )
    result = run_deterministic_checks(text)
    assert result.has_issues is False


def test_triplet_contrastive_combo_detected():
    text = "It is not about speed, scale, or polish. It is about source-specific work."
    result = run_deterministic_checks(text)
    assert result.triplet_contrastive_combo_count == 1
    assert result.has_issues is True


def test_clustered_triplets_detected():
    text = (
        "The policy affects renters, landlords, and inspectors. "
        "The response needs shade, repairs, and enforcement."
    )
    result = run_deterministic_checks(text)
    assert result.clustered_triplet_count == 1


def test_paragraph_length_variance_warning_detected():
    text = (
        "First paragraph has exactly five words.\n\n"
        "Second paragraph also has five.\n\n"
        "Third paragraph also has five."
    )
    result = run_deterministic_checks(text)
    assert result.paragraph_length_variance_warning is True
    assert result.paragraph_length_profile is not None
    assert result.paragraph_length_profile.paragraph_count == 3


def test_mechanical_burstiness_detected():
    text = (
        "This sentence has enough words to count as a deliberately long sentence for the detector heuristic. "
        "This matters. "
        "This sentence also has enough words to make the short sentence feel mechanically inserted."
    )
    result = run_deterministic_checks(text)
    assert result.mechanical_burstiness_count == 1


def test_concrete_engagement_detected():
    text = 'The source says "renters face higher heat exposure" on page 12.'
    result = run_deterministic_checks(text)
    assert result.concrete_engagement_present is True
