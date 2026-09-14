Set-Location $PSScriptRoot
uv sync
uv run python -m english_tutor.main
