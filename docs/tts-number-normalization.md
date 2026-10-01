# Preserve ambiguous specialized number tokens

Clock, currency, percentage, ordinal and decimal normalization honor the existing conservative rule for identifiers, ranges and leading-zero codes.

## Contract

Tighten specialized token boundaries and apply the existing leading-zero rule to their callbacks. Clock values such as `03:04` retain their supported zero-padded hour form. Apply shared preservation to the native number verbalizer as well.

The original normalization test module imports torch for unrelated route tests; its literal cases were run separately without torch. Full route/ML tests and platform smoke tests await hosted CI.

## Regression coverage

The public helper regression is in `tests/test_voice_number_boundaries.py`.
Run it with `python -m pytest -q tests/test_voice_number_boundaries.py` from the repository root.
It uses local text, files or child processes; no model generation is required.
