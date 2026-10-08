"""Keep the log readable: a line per question, tool and fault, not a line per poll."""

from __future__ import annotations

import logging

# What the tablet asks for on a timer. Success is the expected case and says nothing.
POLLED_PREFIXES = ("/state/", "/health", "/ping", "/static/", "/sw.js", "/manifest.webmanifest", "/favicon.ico")
QUIET_STATUSES = (200, 304)


# Routes whose query must never reach the log: Instagram's sign-in comes back to the first with a
# one-time code and state in its address (app/routes/connections.py); [messaging] the public door
# for messages, whose query carries WeCom's signature, nonce and (on its URL check) the sealed echo
# (app/routes/hooks.py).
UNLOGGED_QUERIES = ("/connections/", "/hooks/")


class QuietPollsFilter(logging.Filter):
    """Drops uvicorn's access line for a poll that succeeded. During a turn the tablet asks
    /state every 400 ms and /health every 30 s; logged, they bury the lines that matter. A
    failure (any other status) is still logged, as is every request that is not a poll.

    It also takes the query off a Connections route's line, so a sign-in's code never lands in
    the journal."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            path, status = args[2], args[4]
            if status in QUIET_STATUSES and isinstance(path, str) and path.startswith(POLLED_PREFIXES):
                return False
            if isinstance(path, str) and "?" in path and path.startswith(UNLOGGED_QUERIES):
                record.args = (args[0], args[1], path.split("?", 1)[0] + "?[not logged]", args[3], args[4])
        return True


_FILTER = QuietPollsFilter()   # one instance, so repeated configuration does not stack copies


def quieten() -> None:
    """Silence what is only noise: successful polls, and httpx's line per outbound request
    (four of them per health check, one per voice line, all saying 200 OK)."""
    logging.getLogger("uvicorn.access").addFilter(_FILTER)
    logging.getLogger("httpx").setLevel(logging.WARNING)
