# Preserve literal sentence markers in user text

Streaming TTS preserves literal `<prd>` and `<stop>` text, including marker variants, while keeping the existing sentence boundaries.

## Contract

Choose period and stop markers absent from the original buffer, then use those markers throughout splitting and restoration.

The known behaviors in the existing golden corpus remain unchanged. This does not add a new tokenizer or change chunking defaults.

## Regression coverage

The public helper regression is in `tests/test_voice_chunk_markers.py`.
Run it with `python -m pytest -q tests/test_voice_chunk_markers.py` from the repository root.
It uses local text, files or child processes; no model generation is required.
