"""`python -m app.bench`, run from crooks-assistant/: see app/bench/cli.py and docs/BENCH.md."""

from app.bench.cli import main

if __name__ == "__main__":   # only when run as the command; importing it (a module scan) runs nothing
    raise SystemExit(main())
