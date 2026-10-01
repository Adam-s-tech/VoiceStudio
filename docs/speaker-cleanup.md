# Retain known speakers when cleaning short answers

Clean up segments retains a genuine short answer when its neighboring segments belong to other known speakers.

## Contract

Remove the unconditional cross-speaker fallback for non-ultra-short fragments. Preserve the same-speaker merge and documented ultra-short stray-token exception.

The documented ultra-short (<0.5 seconds or <4 characters) stray-token folding exception remains. This does not change diarization or its speaker assignments.

## Regression coverage

The public helper regression is in `tests/test_voice_speaker_cleanup.py`.
Run it with `python -m pytest -q tests/test_voice_speaker_cleanup.py` from the repository root.
It uses local text, files or child processes; no model generation is required.
