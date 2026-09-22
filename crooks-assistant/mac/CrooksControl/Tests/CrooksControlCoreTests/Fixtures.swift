import Foundation

// Documents produced by the REAL scripts/control.py, not written by hand.
//
// Some were captured by running `crooks-control status` and `actions` on the machine this
// was developed on. The rest were produced by calling control.py's own status_document(),
// plan_document() and apply_document() with read_health() and tablet_route() stubbed —
// which is how tests/test_control.py drives them, because a document invented by the person
// writing the test is a test of his memory rather than of the script.
//
// The generator is kept with the workstream notes; regenerating is a matter of running
// control.py again. The ONLY edit made to any of these is the absolute path prefix in
// `actions`, rewritten from the development checkout to /Users/george/crooks-assistant so that
// reading the fixture does not require knowing where it was captured — and the branch name,
// which was this workstream's own worktree branch, rewritten to main. No field that any
// test asserts on was touched.

enum Fixture {

    /// `crooks-control status` on a Mac where nothing is answering. Captured verbatim.
    static let offlineStatus = Data(#"""
{
  "contract": 1,
  "command": "status",
  "ok": false,
  "at": 1789256251.542,
  "state": "RED",
  "headline": "CROOKS \u2014 Offline",
  "why": "nothing is answering on 127.0.0.1:8000. `make up`, or `make install` to have it start at login.",
  "issues": [
    "the assistant is not answering"
  ],
  "degraded": [],
  "rows": [
    {
      "key": "online",
      "label": "Online",
      "state": "bad",
      "value": "nothing answering on 127.0.0.1:8000",
      "detail": "`make up` to run it in a window, or `make install` to have it start at login"
    },
    {
      "key": "build",
      "label": "Build",
      "state": "off",
      "value": "?",
      "detail": "version ?"
    },
    {
      "key": "backend",
      "label": "Assistant",
      "state": "bad",
      "value": "not running",
      "detail": ""
    },
    {
      "key": "speech",
      "label": "Voice/STT",
      "state": "off",
      "value": "unknown",
      "detail": "this build does not report it"
    },
    {
      "key": "speaks",
      "label": "Speaks",
      "state": "off",
      "value": "unknown",
      "detail": "this build does not report it"
    },
    {
      "key": "claude",
      "label": "Claude",
      "state": "off",
      "value": "unknown",
      "detail": "this build does not report it"
    },
    {
      "key": "shopify",
      "label": "Shopify",
      "state": "off",
      "value": "unknown",
      "detail": "this build does not report it"
    },
    {
      "key": "gmail",
      "label": "Gmail",
      "state": "off",
      "value": "unknown",
      "detail": "this build does not report it"
    },
    {
      "key": "orders",
      "label": "Order cache",
      "state": "off",
      "value": "cold",
      "detail": "the first question about orders will read the store"
    },
    {
      "key": "tablet",
      "label": "Tablet",
      "state": "off",
      "value": "no route",
      "detail": "Tailscale is not installed (or its CLI is not on PATH)."
    },
    {
      "key": "mutation",
      "label": "Changes",
      "state": "off",
      "value": "unknown",
      "detail": "no capability table on this build"
    },
    {
      "key": "session",
      "label": "Test session",
      "state": "off",
      "value": "none",
      "detail": ""
    },
    {
      "key": "branch",
      "label": "Branch",
      "state": "ok",
      "value": "main \u00b7 2b25230a5a",
      "detail": "Phase 6: what this machine can and cannot verify, written before the code"
    },
    {
      "key": "known_good",
      "label": "Known good",
      "state": "off",
      "value": "none recorded",
      "detail": "crooks-control mark-good records the running build as the one to come back to"
    }
  ],
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6: what this machine can and cannot verify, written before the code",
      "committed_at": "2026-09-12T21:51:56+00:00",
      "build": "",
      "version": ""
    },
    "candidate": null,
    "last_known_good": null,
    "note": "the candidate build is read by `plan`, which fetches; status never touches the network"
  },
  "tablet": {
    "host": "",
    "url": "",
    "note": "Tailscale is not installed (or its CLI is not on PATH).",
    "local": "http://127.0.0.1:8000/"
  },
  "test_session": {
    "active": false,
    "id": "",
    "name": ""
  },
  "mutation": {
    "state": "unknown",
    "detail": "no capability table on this build",
    "source": "writes",
    "ready": [],
    "read_only": [],
    "missing_scope": [],
    "unavailable": []
  },
  "local_work": {
    "dirty": [],
    "blocking": [],
    "stops": false
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "port": 8000
}
"""#.utf8)

    /// GREEN: everything answering, changes ready, the tablet routed.
    static let onlineStatus = Data(#"""
{
  "contract": 1,
  "command": "status",
  "ok": true,
  "at": 1789256979.848,
  "state": "GREEN",
  "headline": "CROOKS — Online",
  "why": "everything answering, changes ready, tablet routed",
  "issues": [],
  "degraded": [],
  "rows": [
    {
      "key": "online",
      "label": "Online",
      "state": "ok",
      "value": "answering on 127.0.0.1:8000",
      "detail": "ok · up 2.1h · 2 session(s)"
    },
    {
      "key": "build",
      "label": "Build",
      "state": "ok",
      "value": "2026.09.12+2b25230",
      "detail": "version 5.4.0"
    },
    {
      "key": "backend",
      "label": "Assistant",
      "state": "ok",
      "value": "running",
      "detail": ""
    },
    {
      "key": "speech",
      "label": "Voice/STT",
      "state": "ok",
      "value": "whisper.cpp · whisper-server on 8081, small.en",
      "detail": ""
    },
    {
      "key": "speaks",
      "label": "Speaks",
      "state": "ok",
      "value": "ElevenLabs, Derek",
      "detail": ""
    },
    {
      "key": "claude",
      "label": "Claude",
      "state": "ok",
      "value": "claude-opus-5, 214ms",
      "detail": ""
    },
    {
      "key": "shopify",
      "label": "Shopify",
      "state": "ok",
      "value": "crooks-clothing.myshopify.com",
      "detail": ""
    },
    {
      "key": "gmail",
      "label": "Gmail",
      "state": "ok",
      "value": "george@crooksclothing.co.uk",
      "detail": ""
    },
    {
      "key": "orders",
      "label": "Order cache",
      "state": "ok",
      "value": "41 held, read 62s ago",
      "detail": "30 day(s)"
    },
    {
      "key": "tablet",
      "label": "Tablet",
      "state": "ok",
      "value": "https://crooks-mini.tail1234.ts.net/",
      "detail": "serving on 443"
    },
    {
      "key": "mutation",
      "label": "Changes",
      "state": "ok",
      "value": "ready",
      "detail": "all 3 changes ready"
    },
    {
      "key": "session",
      "label": "Test session",
      "state": "off",
      "value": "none",
      "detail": ""
    },
    {
      "key": "branch",
      "label": "Branch",
      "state": "ok",
      "value": "main · 2b25230a5a",
      "detail": "Phase 6: what this machine can and cannot verify, written before the code"
    },
    {
      "key": "known_good",
      "label": "Known good",
      "state": "off",
      "value": "none recorded",
      "detail": "crooks-control mark-good records the running build as the one to come back to"
    }
  ],
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6: what this machine can and cannot verify, written before the code",
      "committed_at": "2026-09-12T21:51:56+00:00",
      "build": "2026.09.12+2b25230",
      "version": "5.4.0"
    },
    "candidate": null,
    "last_known_good": null,
    "note": "the candidate build is read by `plan`, which fetches; status never touches the network"
  },
  "tablet": {
    "host": "crooks-mini.tail1234.ts.net",
    "url": "https://crooks-mini.tail1234.ts.net/",
    "note": "serving on 443",
    "local": "http://127.0.0.1:8000/"
  },
  "test_session": {
    "active": false,
    "id": "",
    "name": ""
  },
  "mutation": {
    "state": "ready",
    "detail": "all 3 changes ready",
    "source": "families",
    "ready": [
      "Order edit",
      "Refund",
      "Email"
    ],
    "read_only": [],
    "missing_scope": [],
    "unavailable": []
  },
  "local_work": {
    "dirty": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "blocking": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "stops": true
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "port": 8000
}
"""#.utf8)

    /// AMBER: Gmail's token has expired and one capability family is read-only.
    static let degradedStatus = Data(#"""
{
  "contract": 1,
  "command": "status",
  "ok": true,
  "at": 1789256979.863,
  "state": "AMBER",
  "headline": "CROOKS — Degraded",
  "why": "gmail: the Gmail token needs renewing · 1 of 3 read-only — live writes are off",
  "issues": [],
  "degraded": [
    "gmail",
    "changes"
  ],
  "rows": [
    {
      "key": "online",
      "label": "Online",
      "state": "ok",
      "value": "answering on 127.0.0.1:8000",
      "detail": "ok · up 2.1h · 2 session(s)"
    },
    {
      "key": "build",
      "label": "Build",
      "state": "ok",
      "value": "2026.09.12+2b25230",
      "detail": "version 5.4.0"
    },
    {
      "key": "backend",
      "label": "Assistant",
      "state": "ok",
      "value": "running",
      "detail": ""
    },
    {
      "key": "speech",
      "label": "Voice/STT",
      "state": "ok",
      "value": "whisper.cpp · whisper-server on 8081, small.en",
      "detail": ""
    },
    {
      "key": "speaks",
      "label": "Speaks",
      "state": "ok",
      "value": "ElevenLabs, Derek",
      "detail": ""
    },
    {
      "key": "claude",
      "label": "Claude",
      "state": "ok",
      "value": "claude-opus-5, 214ms",
      "detail": ""
    },
    {
      "key": "shopify",
      "label": "Shopify",
      "state": "ok",
      "value": "crooks-clothing.myshopify.com",
      "detail": ""
    },
    {
      "key": "gmail",
      "label": "Gmail",
      "state": "bad",
      "value": "the Gmail token needs renewing",
      "detail": ""
    },
    {
      "key": "orders",
      "label": "Order cache",
      "state": "ok",
      "value": "41 held, read 62s ago",
      "detail": "30 day(s)"
    },
    {
      "key": "tablet",
      "label": "Tablet",
      "state": "ok",
      "value": "https://crooks-mini.tail1234.ts.net/",
      "detail": "serving on 443"
    },
    {
      "key": "mutation",
      "label": "Changes",
      "state": "off",
      "value": "read only",
      "detail": "1 of 3 read-only — live writes are off"
    },
    {
      "key": "session",
      "label": "Test session",
      "state": "off",
      "value": "none",
      "detail": ""
    },
    {
      "key": "branch",
      "label": "Branch",
      "state": "ok",
      "value": "main · 2b25230a5a",
      "detail": "Phase 6: what this machine can and cannot verify, written before the code"
    },
    {
      "key": "known_good",
      "label": "Known good",
      "state": "off",
      "value": "none recorded",
      "detail": "crooks-control mark-good records the running build as the one to come back to"
    }
  ],
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6: what this machine can and cannot verify, written before the code",
      "committed_at": "2026-09-12T21:51:56+00:00",
      "build": "2026.09.12+2b25230",
      "version": "5.4.0"
    },
    "candidate": null,
    "last_known_good": null,
    "note": "the candidate build is read by `plan`, which fetches; status never touches the network"
  },
  "tablet": {
    "host": "crooks-mini.tail1234.ts.net",
    "url": "https://crooks-mini.tail1234.ts.net/",
    "note": "serving on 443",
    "local": "http://127.0.0.1:8000/"
  },
  "test_session": {
    "active": false,
    "id": "",
    "name": ""
  },
  "mutation": {
    "state": "read_only",
    "detail": "1 of 3 read-only — live writes are off",
    "source": "families",
    "ready": [
      "Order edit",
      "Email"
    ],
    "read_only": [
      {
        "label": "Refund",
        "scope": "write_orders",
        "detail": "live writes are off"
      }
    ],
    "missing_scope": [],
    "unavailable": []
  },
  "local_work": {
    "dirty": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "blocking": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "stops": true
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "port": 8000
}
"""#.utf8)

    /// BLUE: a test session is recording.
    static let recordingStatus = Data(#"""
{
  "contract": 1,
  "command": "status",
  "ok": true,
  "at": 1789256979.878,
  "state": "BLUE",
  "headline": "CROOKS — Testing",
  "why": "recording 2026-09-12-shopfloor — crooks-watch follows it",
  "issues": [],
  "degraded": [],
  "rows": [
    {
      "key": "online",
      "label": "Online",
      "state": "ok",
      "value": "answering on 127.0.0.1:8000",
      "detail": "ok · up 2.1h · 2 session(s)"
    },
    {
      "key": "build",
      "label": "Build",
      "state": "ok",
      "value": "2026.09.12+2b25230",
      "detail": "version 5.4.0"
    },
    {
      "key": "backend",
      "label": "Assistant",
      "state": "ok",
      "value": "running",
      "detail": ""
    },
    {
      "key": "speech",
      "label": "Voice/STT",
      "state": "ok",
      "value": "whisper.cpp · whisper-server on 8081, small.en",
      "detail": ""
    },
    {
      "key": "speaks",
      "label": "Speaks",
      "state": "ok",
      "value": "ElevenLabs, Derek",
      "detail": ""
    },
    {
      "key": "claude",
      "label": "Claude",
      "state": "ok",
      "value": "claude-opus-5, 214ms",
      "detail": ""
    },
    {
      "key": "shopify",
      "label": "Shopify",
      "state": "ok",
      "value": "crooks-clothing.myshopify.com",
      "detail": ""
    },
    {
      "key": "gmail",
      "label": "Gmail",
      "state": "ok",
      "value": "george@crooksclothing.co.uk",
      "detail": ""
    },
    {
      "key": "orders",
      "label": "Order cache",
      "state": "ok",
      "value": "41 held, read 62s ago",
      "detail": "30 day(s)"
    },
    {
      "key": "tablet",
      "label": "Tablet",
      "state": "ok",
      "value": "https://crooks-mini.tail1234.ts.net/",
      "detail": "serving on 443"
    },
    {
      "key": "mutation",
      "label": "Changes",
      "state": "ok",
      "value": "ready",
      "detail": "all 3 changes ready"
    },
    {
      "key": "session",
      "label": "Test session",
      "state": "ok",
      "value": "2026-09-12-shopfloor",
      "detail": "Saturday shop floor"
    },
    {
      "key": "branch",
      "label": "Branch",
      "state": "ok",
      "value": "main · 2b25230a5a",
      "detail": "Phase 6: what this machine can and cannot verify, written before the code"
    },
    {
      "key": "known_good",
      "label": "Known good",
      "state": "off",
      "value": "none recorded",
      "detail": "crooks-control mark-good records the running build as the one to come back to"
    }
  ],
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6: what this machine can and cannot verify, written before the code",
      "committed_at": "2026-09-12T21:51:56+00:00",
      "build": "2026.09.12+2b25230",
      "version": "5.4.0"
    },
    "candidate": null,
    "last_known_good": null,
    "note": "the candidate build is read by `plan`, which fetches; status never touches the network"
  },
  "tablet": {
    "host": "crooks-mini.tail1234.ts.net",
    "url": "https://crooks-mini.tail1234.ts.net/",
    "note": "serving on 443",
    "local": "http://127.0.0.1:8000/"
  },
  "test_session": {
    "active": true,
    "id": "2026-09-12-shopfloor",
    "name": "Saturday shop floor"
  },
  "mutation": {
    "state": "ready",
    "detail": "all 3 changes ready",
    "source": "families",
    "ready": [
      "Order edit",
      "Refund",
      "Email"
    ],
    "read_only": [],
    "missing_scope": [],
    "unavailable": []
  },
  "local_work": {
    "dirty": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "blocking": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "stops": true
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "port": 8000
}
"""#.utf8)

    /// RED while still answering: Claude is down, which is one of the three the assistant cannot work without.
    static let essentialDownStatus = Data(#"""
{
  "contract": 1,
  "command": "status",
  "ok": false,
  "at": 1789256979.893,
  "state": "RED",
  "headline": "CROOKS — Issue",
  "why": "claude: no answer from the Claude API in 30s",
  "issues": [
    "claude"
  ],
  "degraded": [],
  "rows": [
    {
      "key": "online",
      "label": "Online",
      "state": "ok",
      "value": "answering on 127.0.0.1:8000",
      "detail": "ok · up 2.1h · 2 session(s)"
    },
    {
      "key": "build",
      "label": "Build",
      "state": "ok",
      "value": "2026.09.12+2b25230",
      "detail": "version 5.4.0"
    },
    {
      "key": "backend",
      "label": "Assistant",
      "state": "ok",
      "value": "running",
      "detail": ""
    },
    {
      "key": "speech",
      "label": "Voice/STT",
      "state": "ok",
      "value": "whisper.cpp · whisper-server on 8081, small.en",
      "detail": ""
    },
    {
      "key": "speaks",
      "label": "Speaks",
      "state": "ok",
      "value": "ElevenLabs, Derek",
      "detail": ""
    },
    {
      "key": "claude",
      "label": "Claude",
      "state": "bad",
      "value": "no answer from the Claude API in 30s",
      "detail": ""
    },
    {
      "key": "shopify",
      "label": "Shopify",
      "state": "ok",
      "value": "crooks-clothing.myshopify.com",
      "detail": ""
    },
    {
      "key": "gmail",
      "label": "Gmail",
      "state": "ok",
      "value": "george@crooksclothing.co.uk",
      "detail": ""
    },
    {
      "key": "orders",
      "label": "Order cache",
      "state": "ok",
      "value": "41 held, read 62s ago",
      "detail": "30 day(s)"
    },
    {
      "key": "tablet",
      "label": "Tablet",
      "state": "ok",
      "value": "https://crooks-mini.tail1234.ts.net/",
      "detail": "serving on 443"
    },
    {
      "key": "mutation",
      "label": "Changes",
      "state": "ok",
      "value": "ready",
      "detail": "all 3 changes ready"
    },
    {
      "key": "session",
      "label": "Test session",
      "state": "off",
      "value": "none",
      "detail": ""
    },
    {
      "key": "branch",
      "label": "Branch",
      "state": "ok",
      "value": "main · 2b25230a5a",
      "detail": "Phase 6: what this machine can and cannot verify, written before the code"
    },
    {
      "key": "known_good",
      "label": "Known good",
      "state": "off",
      "value": "none recorded",
      "detail": "crooks-control mark-good records the running build as the one to come back to"
    }
  ],
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6: what this machine can and cannot verify, written before the code",
      "committed_at": "2026-09-12T21:51:56+00:00",
      "build": "2026.09.12+2b25230",
      "version": "5.4.0"
    },
    "candidate": null,
    "last_known_good": null,
    "note": "the candidate build is read by `plan`, which fetches; status never touches the network"
  },
  "tablet": {
    "host": "crooks-mini.tail1234.ts.net",
    "url": "https://crooks-mini.tail1234.ts.net/",
    "note": "serving on 443",
    "local": "http://127.0.0.1:8000/"
  },
  "test_session": {
    "active": false,
    "id": "",
    "name": ""
  },
  "mutation": {
    "state": "ready",
    "detail": "all 3 changes ready",
    "source": "families",
    "ready": [
      "Order edit",
      "Refund",
      "Email"
    ],
    "read_only": [],
    "missing_scope": [],
    "unavailable": []
  },
  "local_work": {
    "dirty": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "blocking": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "stops": true
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "port": 8000
}
"""#.utf8)

    /// Healthy, but Tailscale is serving nothing — so the pad has no way in.
    static let noRouteStatus = Data(#"""
{
  "contract": 1,
  "command": "status",
  "ok": true,
  "at": 1789256979.908,
  "state": "AMBER",
  "headline": "CROOKS — Degraded",
  "why": "Tailscale is not serving the tablet's address",
  "issues": [],
  "degraded": [
    "tablet route"
  ],
  "rows": [
    {
      "key": "online",
      "label": "Online",
      "state": "ok",
      "value": "answering on 127.0.0.1:8000",
      "detail": "ok · up 2.1h · 2 session(s)"
    },
    {
      "key": "build",
      "label": "Build",
      "state": "ok",
      "value": "2026.09.12+2b25230",
      "detail": "version 5.4.0"
    },
    {
      "key": "backend",
      "label": "Assistant",
      "state": "ok",
      "value": "running",
      "detail": ""
    },
    {
      "key": "speech",
      "label": "Voice/STT",
      "state": "ok",
      "value": "whisper.cpp · whisper-server on 8081, small.en",
      "detail": ""
    },
    {
      "key": "speaks",
      "label": "Speaks",
      "state": "ok",
      "value": "ElevenLabs, Derek",
      "detail": ""
    },
    {
      "key": "claude",
      "label": "Claude",
      "state": "ok",
      "value": "claude-opus-5, 214ms",
      "detail": ""
    },
    {
      "key": "shopify",
      "label": "Shopify",
      "state": "ok",
      "value": "crooks-clothing.myshopify.com",
      "detail": ""
    },
    {
      "key": "gmail",
      "label": "Gmail",
      "state": "ok",
      "value": "george@crooksclothing.co.uk",
      "detail": ""
    },
    {
      "key": "orders",
      "label": "Order cache",
      "state": "ok",
      "value": "41 held, read 62s ago",
      "detail": "30 day(s)"
    },
    {
      "key": "tablet",
      "label": "Tablet",
      "state": "off",
      "value": "no route",
      "detail": "Tailscale is not serving this port."
    },
    {
      "key": "mutation",
      "label": "Changes",
      "state": "ok",
      "value": "ready",
      "detail": "all 3 changes ready"
    },
    {
      "key": "session",
      "label": "Test session",
      "state": "off",
      "value": "none",
      "detail": ""
    },
    {
      "key": "branch",
      "label": "Branch",
      "state": "ok",
      "value": "main · 2b25230a5a",
      "detail": "Phase 6: what this machine can and cannot verify, written before the code"
    },
    {
      "key": "known_good",
      "label": "Known good",
      "state": "off",
      "value": "none recorded",
      "detail": "crooks-control mark-good records the running build as the one to come back to"
    }
  ],
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6: what this machine can and cannot verify, written before the code",
      "committed_at": "2026-09-12T21:51:56+00:00",
      "build": "2026.09.12+2b25230",
      "version": "5.4.0"
    },
    "candidate": null,
    "last_known_good": null,
    "note": "the candidate build is read by `plan`, which fetches; status never touches the network"
  },
  "tablet": {
    "host": "",
    "url": "",
    "note": "Tailscale is not serving this port.",
    "local": "http://127.0.0.1:8000/"
  },
  "test_session": {
    "active": false,
    "id": "",
    "name": ""
  },
  "mutation": {
    "state": "ready",
    "detail": "all 3 changes ready",
    "source": "families",
    "ready": [
      "Order edit",
      "Refund",
      "Email"
    ],
    "read_only": [],
    "missing_scope": [],
    "unavailable": []
  },
  "local_work": {
    "dirty": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "blocking": [
      "crooks-assistant/mac/CrooksControl/Package.swift",
      "crooks-assistant/mac/CrooksControl/.build/",
      "crooks-assistant/mac/CrooksControl/Sources/CrooksControlCore/"
    ],
    "stops": true
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "port": 8000
}
"""#.utf8)

    /// `crooks-control actions`. This is the Phase 5 list, which has NO start and NO stop in it.
    static let actions = Data(#"""
{
  "contract": 1,
  "command": "actions",
  "ok": true,
  "at": 1789256251.762,
  "actions": [
    {
      "id": "open",
      "label": "Open CROOKS OS",
      "kind": "open_url",
      "group": "use",
      "url": "http://127.0.0.1:8000/",
      "confirm": false,
      "why": "the tablet's own page, on this Mac's browser"
    },
    {
      "id": "restart",
      "label": "Restart",
      "kind": "shell",
      "group": "use",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/python",
        "/Users/george/crooks-assistant/scripts/install_launchd.py",
        "--restart"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": true,
      "confirm_text": "Restart the assistant and whisper-server? Anything mid-sentence on the tablet will stop.",
      "why": "the launchd agents, kicked \u2014 the same as `make restart`"
    },
    {
      "id": "check",
      "label": "Check for update",
      "kind": "control",
      "group": "update",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/python",
        "/Users/george/crooks-assistant/scripts/control.py",
        "plan"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": false,
      "why": "fetches, shows both SHAs, changes nothing"
    },
    {
      "id": "update",
      "label": "Update",
      "kind": "control",
      "group": "update",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/python",
        "/Users/george/crooks-assistant/scripts/control.py",
        "apply",
        "--yes"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": true,
      "confirm_text": "Fast-forward to the candidate build, run the offline suite, restart and verify?",
      "why": "the whole update; it stops rather than move a dirty tree",
      "needs_plan": true
    },
    {
      "id": "rollback",
      "label": "Roll back",
      "kind": "control",
      "group": "update",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/python",
        "/Users/george/crooks-assistant/scripts/control.py",
        "rollback",
        "--yes"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": true,
      "confirm_text": "Go back to the last known-good build and restart?",
      "why": "only offered when a known-good build is recorded and the tree is clean"
    },
    {
      "id": "tests",
      "label": "Run tests",
      "kind": "shell",
      "group": "test",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/pytest",
        "-q",
        "-m",
        "not live"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": false,
      "why": "the offline suite \u2014 the same as `make test`"
    },
    {
      "id": "tests_ui",
      "label": "Run UI tests",
      "kind": "shell",
      "group": "test",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/python",
        "/Users/george/crooks-assistant/scripts/experience.py",
        "--ui"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": false,
      "why": "the golden scenarios, and the page driven in Chromium \u2014 the same as crooks-test-ui"
    },
    {
      "id": "session_start",
      "label": "Start live recording",
      "kind": "shell",
      "group": "test",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/python",
        "/Users/george/crooks-assistant/scripts/test_session.py",
        "start",
        "--name",
        "from the Control app"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": false,
      "why": "begins a test session; nothing restarts and the tablet joins within a poll"
    },
    {
      "id": "session_stop",
      "label": "Stop recording",
      "kind": "shell",
      "group": "test",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/python",
        "/Users/george/crooks-assistant/scripts/test_session.py",
        "stop"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": false,
      "why": "ends it"
    },
    {
      "id": "report",
      "label": "Generate report",
      "kind": "shell",
      "group": "test",
      "command": [
        "/Users/george/crooks-assistant/.venv/bin/python",
        "/Users/george/crooks-assistant/scripts/test_session.py",
        "report"
      ],
      "cwd": "/Users/george/crooks-assistant",
      "confirm": false,
      "why": "writes reports/<session>.md from the timeline"
    },
    {
      "id": "report_open",
      "label": "Open latest report",
      "kind": "open_path",
      "group": "test",
      "path": "/Users/george/crooks-assistant/reports",
      "confirm": false,
      "why": "the newest file in reports/ \u2014 the app opens it, or the folder when there is none"
    },
    {
      "id": "logs",
      "label": "Open logs",
      "kind": "open_path",
      "group": "look",
      "path": "/Users/george/crooks-assistant/logs",
      "confirm": false,
      "why": "assistant.out.log and its neighbours"
    },
    {
      "id": "folder",
      "label": "Open project folder",
      "kind": "open_path",
      "group": "look",
      "path": "/Users/george/crooks-assistant",
      "confirm": false,
      "why": "the checkout itself"
    }
  ]
}
"""#.utf8)

    /// A check that found three commits to take.
    static let planAvailable = Data(#"""
{
  "contract": 1,
  "command": "plan",
  "ok": true,
  "at": 1789259505.275,
  "update": {
    "contract": 1,
    "command": "crooks-update",
    "ok": true,
    "check": true,
    "repo": "",
    "branch": "main",
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "behind": 3,
    "ahead": 0,
    "fast_forward": true,
    "local_work": {
      "dirty": [],
      "blocking": [],
      "stops": false
    },
    "deps": [
      "requirements.txt"
    ],
    "changed_files": 17,
    "moved": false,
    "tested": false,
    "restarted": false,
    "verified": false,
    "stages": [],
    "stop": null,
    "next": "click_to_apply"
  },
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6 D: start polling when the app starts, not when a window appears",
      "committed_at": "2026-09-13T00:31:06+00:00",
      "build": "2026.09.12+9f31c22",
      "version": "5.4.1"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "last_known_good": null
  },
  "local_work": {
    "dirty": [],
    "blocking": [],
    "stops": false
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "next": "click_to_apply",
  "click": {
    "label": "Update now",
    "command": [
      "crooks-control",
      "apply",
      "--yes"
    ],
    "enabled": true
  }
}
"""#.utf8)

    /// A check that found nothing.
    static let planUpToDate = Data(#"""
{
  "contract": 1,
  "command": "plan",
  "ok": true,
  "at": 1789259505.285,
  "update": {
    "contract": 1,
    "command": "crooks-update",
    "ok": true,
    "check": true,
    "repo": "",
    "branch": "main",
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "candidate": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "behind": 0,
    "ahead": 0,
    "fast_forward": true,
    "local_work": {
      "dirty": [],
      "blocking": [],
      "stops": false
    },
    "deps": [],
    "changed_files": 0,
    "moved": false,
    "tested": false,
    "restarted": false,
    "verified": false,
    "stages": [],
    "stop": null,
    "next": "up_to_date"
  },
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6 D: start polling when the app starts, not when a window appears",
      "committed_at": "2026-09-13T00:31:06+00:00",
      "build": "2026.09.12+9f31c22",
      "version": "5.4.1"
    },
    "candidate": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "last_known_good": null
  },
  "local_work": {
    "dirty": [],
    "blocking": [],
    "stops": false
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "next": "up_to_date",
  "click": {
    "label": "Update now",
    "command": [
      "crooks-control",
      "apply",
      "--yes"
    ],
    "enabled": false
  }
}
"""#.utf8)

    /// A check stopped by unsaved work. Nothing moved, so this is a refusal, not a failure.
    static let planBlockedDirty = Data(#"""
{
  "contract": 1,
  "command": "plan",
  "ok": false,
  "at": 1789259505.294,
  "update": {
    "contract": 1,
    "command": "crooks-update",
    "ok": false,
    "check": true,
    "repo": "",
    "branch": "main",
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "behind": 3,
    "ahead": 0,
    "fast_forward": true,
    "local_work": {
      "dirty": [
        "app/turn.py"
      ],
      "blocking": [
        "app/turn.py"
      ],
      "stops": true
    },
    "deps": [],
    "changed_files": 0,
    "moved": false,
    "tested": false,
    "restarted": false,
    "verified": false,
    "stages": [],
    "stop": {
      "stage": "branch",
      "reason": "There are local changes here (app/turn.py). Commit or stash them first. Nothing has been thrown away."
    },
    "next": "blocked"
  },
  "build": {
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a",
      "branch": "main",
      "detached": false,
      "subject": "Phase 6 D: start polling when the app starts, not when a window appears",
      "committed_at": "2026-09-13T00:31:06+00:00",
      "build": "2026.09.12+9f31c22",
      "version": "5.4.1"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "last_known_good": null
  },
  "local_work": {
    "dirty": [
      "app/turn.py"
    ],
    "blocking": [
      "app/turn.py"
    ],
    "stops": true
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "next": "blocked",
  "click": {
    "label": "Update now",
    "command": [
      "crooks-control",
      "apply",
      "--yes"
    ],
    "enabled": false
  }
}
"""#.utf8)

    /// THE IMPORTANT ONE. ok:true, the build moved, and /health never came back.
/// `next` is "verify_by_hand" and `marked_good` is null. A control panel that reads
/// `ok` and draws a tick has told the owner his shop is running a dead build.
    static let applyMovedButUnhealthy = Data(#"""
{
  "contract": 1,
  "command": "apply",
  "ok": true,
  "at": 1789259505.295,
  "update": {
    "contract": 1,
    "command": "crooks-update",
    "ok": true,
    "check": false,
    "repo": "",
    "branch": "main",
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "behind": 3,
    "ahead": 0,
    "fast_forward": true,
    "local_work": {
      "dirty": [],
      "blocking": [],
      "stops": false
    },
    "deps": [],
    "changed_files": 17,
    "moved": true,
    "tested": true,
    "restarted": true,
    "verified": false,
    "stages": [],
    "stop": null,
    "next": "verify_the_tablet"
  },
  "stages": [
    {
      "stage": "tablet",
      "state": "ok",
      "detail": "https://crooks-mini.tail1234.ts.net/"
    },
    {
      "stage": "mark",
      "state": "skip",
      "detail": "the backend did not read back healthy, so nothing was marked"
    }
  ],
  "tablet": {
    "host": "crooks-mini.tail1234.ts.net",
    "url": "https://crooks-mini.tail1234.ts.net/",
    "note": "serving on 443"
  },
  "marked_good": null,
  "build": {
    "current": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17",
      "branch": "main",
      "detached": false,
      "subject": "the candidate",
      "build": "",
      "version": ""
    },
    "was": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "last_known_good": null
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "next": "verify_by_hand"
}
"""#.utf8)

    /// The same run, but the new build answered and was recorded as known-good.
    static let applySucceeded = Data(#"""
{
  "contract": 1,
  "command": "apply",
  "ok": true,
  "at": 1789259505.296,
  "update": {
    "contract": 1,
    "command": "crooks-update",
    "ok": true,
    "check": false,
    "repo": "",
    "branch": "main",
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "behind": 3,
    "ahead": 0,
    "fast_forward": true,
    "local_work": {
      "dirty": [],
      "blocking": [],
      "stops": false
    },
    "deps": [],
    "changed_files": 17,
    "moved": true,
    "tested": true,
    "restarted": true,
    "verified": true,
    "stages": [],
    "stop": null,
    "next": "verify_the_tablet"
  },
  "stages": [
    {
      "stage": "tablet",
      "state": "ok",
      "detail": "https://crooks-mini.tail1234.ts.net/"
    },
    {
      "stage": "mark",
      "state": "ok",
      "detail": "9f31c22b17 recorded as known good"
    }
  ],
  "tablet": {
    "host": "crooks-mini.tail1234.ts.net",
    "url": "https://crooks-mini.tail1234.ts.net/",
    "note": "serving on 443"
  },
  "marked_good": {
    "version": 1,
    "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
    "short": "9f31c22b17",
    "branch": "main",
    "subject": "the candidate",
    "build": "2026.09.12+9f31c22",
    "status": "ok",
    "recorded_at": 1789259505.296,
    "recorded_by": "crooks-control apply"
  },
  "build": {
    "current": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17",
      "branch": "main",
      "detached": false,
      "subject": "the candidate",
      "build": "2026.09.12+9f31c22",
      "version": "5.4.1"
    },
    "was": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "last_known_good": {
      "version": 1,
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17",
      "branch": "main",
      "subject": "the candidate",
      "build": "2026.09.12+9f31c22",
      "status": "ok",
      "recorded_at": 1789259505.296,
      "recorded_by": "crooks-control apply"
    }
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
    "short": "9f31c22b17",
    "recorded_at": 1789259505.296,
    "build": "2026.09.12+9f31c22",
    "reason": "The build running here IS the last known-good one. There is nothing to go back to.",
    "commands": [],
    "note": ""
  },
  "next": "done"
}
"""#.utf8)

    /// Stopped at the fetch: this Mac has commits the branch does not. Nothing moved.
    static let applyBlocked = Data(#"""
{
  "contract": 1,
  "command": "apply",
  "ok": false,
  "at": 1789259505.296,
  "update": {
    "contract": 1,
    "command": "crooks-update",
    "ok": false,
    "check": false,
    "repo": "",
    "branch": "main",
    "current": {
      "sha": "2b25230a5ae4df73c23c839ce5441058a54e26bb",
      "short": "2b25230a5a"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "behind": 3,
    "ahead": 2,
    "fast_forward": false,
    "local_work": {
      "dirty": [],
      "blocking": [],
      "stops": false
    },
    "deps": [],
    "changed_files": 0,
    "moved": false,
    "tested": false,
    "restarted": false,
    "verified": false,
    "stages": [],
    "stop": {
      "stage": "fetch",
      "reason": "This Mac has 2 commits the branch does not, so the update cannot be a fast-forward. Nothing was changed."
    },
    "next": "blocked"
  },
  "stages": [],
  "tablet": null,
  "marked_good": null,
  "build": {
    "current": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17",
      "branch": "main",
      "detached": false,
      "subject": "the candidate",
      "build": "2026.09.12+9f31c22",
      "version": "5.4.1"
    },
    "candidate": {
      "sha": "9f31c22b17ad04b8c0e0d7f9b1d4a2c6e8f10a33",
      "short": "9f31c22b17"
    },
    "last_known_good": null
  },
  "rollback": {
    "available": false,
    "safe": false,
    "sha": "",
    "short": "",
    "recorded_at": null,
    "build": "",
    "reason": "No known-good build has been recorded on this Mac yet, so there is nothing to go back to. `crooks-control mark-good` records the build that is running now.",
    "commands": [],
    "note": ""
  },
  "next": "blocked",
  "stop": {
    "stage": "fetch",
    "reason": "This Mac has 2 commits the branch does not, so the update cannot be a fast-forward. Nothing was changed."
  }
}
"""#.utf8)
}
