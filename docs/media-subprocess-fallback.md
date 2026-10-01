# Update fallback process exit status after wait

The Windows-compatible subprocess wrapper exposes the completed child exit code after `wait()`, matching its public asyncio process contract.

## Contract

Store the completed Popen wait result in the wrapper returncode before returning it.

The unsupported transport condition is reproduced with a selector loop on macOS; native Windows execution and the full application smoke matrix await hosted CI. No ffmpeg binary or model was needed for the process protocol regression.

## Regression coverage

The public helper regression is in `tests/test_voice_fallback_exit.py`.
Run it with `python -m pytest -q tests/test_voice_fallback_exit.py` from the repository root.
It uses local text, files or child processes; no model generation is required.
