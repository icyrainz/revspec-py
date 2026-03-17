test:
  revspec tests/fixtures/test-spec.md

reset:
  rm -f tests/fixtures/test-spec.md.*

build:
  uv run python -m build

publish: build
  uv run python -m twine upload dist/*
