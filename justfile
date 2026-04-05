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
  git config core.hooksPath .githooks
  uv venv && uv pip install hatchling editables && uv pip install -e ".[test,dev]" --no-build-isolation
  pipx install -e . --force

# Release: bump version, commit, tag, build, publish, push, update local install
# Usage: just release patch  (or: minor, major)
release bump="patch":
  #!/usr/bin/env bash
  set -euo pipefail
  current=$(grep '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
  IFS='.' read -r major minor patch <<< "$current"
  case "{{bump}}" in
    patch) patch=$((patch + 1)) ;;
    minor) minor=$((minor + 1)); patch=0 ;;
    major) major=$((major + 1)); minor=0; patch=0 ;;
    *) echo "Usage: just release [patch|minor|major]"; exit 1 ;;
  esac
  new="${major}.${minor}.${patch}"
  echo "Releasing: ${current} → ${new}"
  sed -i '' "s/^version = \"${current}\"/version = \"${new}\"/" pyproject.toml
  git add pyproject.toml
  git commit -m "chore: bump version to ${new}"
  git tag "v${new}"
  rm -rf dist/
  uv run python -m build
  uv run python -m twine upload dist/*
  git push && git push --tags
  gh release create "v${new}" --title "v${new}" --generate-notes
  pipx install -e . --force
  echo "Published revspec ${new}"

# Record the demo GIF
record-demo:
  rm -f demo/spec.review.jsonl demo/spec.review.lock demo/spec.review.offset
  cp demo/spec.original.md demo/spec.md
  python3 demo/reply.py &
  vhs demo/demo.tape
  kill %1 2>/dev/null || true
