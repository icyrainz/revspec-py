# Run the TUI on the test fixture
test:
  revspec tests/fixtures/test-spec.md

# Remove review state files for the test fixture
reset:
  rm -f tests/fixtures/test-spec.md.*

# Run the test suite
pytest *args:
  uv run pytest {{args}}

# Run tests and watch for changes
pytest-watch:
  uv run pytest-watch

# Install in editable mode for local dev (local venv + global command)
dev:
  uv venv && uv pip install hatchling editables && uv pip install -e ".[test,dev]" --no-build-isolation
  pipx install -e . --force

# Build dist packages
build:
  rm -rf dist/
  uv run python -m build

# Publish to PyPI (builds first), then update global editable install
publish: build
  uv run python -m twine upload dist/*
  pipx install -e . --force

# Show what would be published
check:
  uv run python -m twine check dist/*

# Record the demo GIF
record-demo:
  rm -f demo/spec.review.jsonl demo/spec.review.lock demo/spec.review.offset
  cp demo/spec.original.md demo/spec.md
  python3 demo/reply.py &
  vhs demo/demo.tape
  kill %1 2>/dev/null || true
