"""``python -m tools.analysis.legislative_data_map`` entry point; delegates to the CLI."""

from tools.analysis.legislative_data_map.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
