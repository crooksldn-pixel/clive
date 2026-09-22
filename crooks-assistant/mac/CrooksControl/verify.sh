#!/bin/sh
# What can be checked about CROOKS Control on a machine that is not a Mac — and, just as
# importantly, what cannot.
#
# This is the gate the appliance's own CI runs. It is deliberately explicit about the third
# check being weaker than the first two: `swiftc -parse` proves the SwiftUI files are valid
# Swift and nothing else. It does not type-check them, it does not resolve SwiftUI or AppKit,
# and it will happily pass a view that calls a method that does not exist. A green run of this
# script is NOT evidence that the Mac app builds. Only `swift build` on a Mac is that.
#
#   ./verify.sh          run everything it can
#   SWIFT=/path/to/swift ./verify.sh    with a toolchain somewhere unusual

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SWIFT=${SWIFT:-$(command -v swift || echo /opt/swift/usr/bin/swift)}
SWIFTC=${SWIFTC:-$(dirname "$SWIFT")/swiftc}
FAILED=0

if [ ! -x "$SWIFT" ]; then
  echo "NOT RUN  no Swift toolchain at $SWIFT — nothing here was checked." >&2
  exit 2
fi

echo "== 1. The core builds (Foundation only, every decision the app makes)"
cd "$HERE"
if "$SWIFT" build --target CrooksControlCore; then
  echo "   ok"
else
  echo "   FAILED"; FAILED=1
fi

echo
echo "== 2. The core's tests"
if "$SWIFT" test; then
  echo "   ok"
else
  echo "   FAILED"; FAILED=1
fi

echo
echo "== 3. The Mac app's sources parse (SYNTAX ONLY — see the note at the top of this file)"
if [ "$(uname -s)" = "Darwin" ]; then
  echo "   skipped: this is a Mac, so check 4 below is the real one"
elif "$SWIFTC" -parse "$HERE"/Sources/CrooksControl/*.swift; then
  echo "   ok — the files are valid Swift. They are NOT known to compile."
else
  echo "   FAILED"; FAILED=1
fi

echo
echo "== 4. The Mac app builds"
if [ "$(uname -s)" = "Darwin" ]; then
  if "$SWIFT" build --target CrooksControl; then
    echo "   ok"
  else
    echo "   FAILED"; FAILED=1
  fi
else
  echo "   NOT RUN. This is $(uname -s), and SwiftUI and AppKit do not exist here."
  echo "   Nothing in this run says anything about whether the Mac app compiles, draws,"
  echo "   or launches. Run this script on the Mac to find out."
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "Everything this machine can check, it checked, and it passed."
else
  echo "Something failed above." >&2
fi
exit "$FAILED"
