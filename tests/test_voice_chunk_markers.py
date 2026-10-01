"""Literal marker text must survive the streaming TTS chunker."""
import pytest

@pytest.mark.parametrize("step", [1, 7, 1000])
def test_literal_internal_markers_survive_streaming(step):
    from services.sentence_chunker import SentenceChunker
    text = "The literal <stop> marker should survive this sentence. The literal <prd> marker should too."
    chunker = SentenceChunker(min_sentence_len=10)
    out = []
    for start in range(0, len(text), step):
        out.extend(chunker.push(text[start:start + step]))
    out.extend(chunker.flush())
    assert " ".join(out) == text

def test_colliding_marker_variants_and_abbreviations_survive_together():
    from services.sentence_chunker import SentenceChunker
    text = "Dr. Smith preserves <prd>, <prd_>, <stop>, and <stop_> in this example. Another sentence follows."
    chunker = SentenceChunker(min_sentence_len=10)
    assert " ".join(chunker.push(text) + chunker.flush()) == text
