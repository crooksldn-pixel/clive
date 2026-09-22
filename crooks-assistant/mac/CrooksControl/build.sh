#!/bin/sh
# Build CROOKS Control and assemble it into an app the Mac will open from the Dock or at
# login. Run it on the Mac, in this folder, or by `make control-app` from the project.
#
#   ./build.sh              build, and leave CROOKS Control.app here
#   ./build.sh --install    the same, then move it to /Applications
#   ./build.sh --login      the same, then have it open at login (System Settings shows it)
#
# It needs the Xcode command line tools (`xcode-select --install`) and macOS 13 or later.
# There is no code signing here beyond ad-hoc: the app runs local commands from a folder you
# chose, and it is built on the Mac it runs on. Gatekeeper does not ask about an app you built
# yourself.
#
# The core's tests run first, every time. They are the ones that decide what this app believes
# about whether CROOKS OS is up, whether the tablet is connected and whether an update worked,
# and shipping a build with any of those broken is not worth the thirty seconds it saves.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
APP_NAME="CROOKS Control"
BINARY="CrooksControl"
BUNDLE="$HERE/$APP_NAME.app"
INSTALL=0
LOGIN=0
SKIP_TESTS=0

for argument in "$@"; do
  case "$argument" in
    --install) INSTALL=1 ;;
    --login) INSTALL=1; LOGIN=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "I do not know the option $argument. --install, --login or --skip-tests." >&2; exit 2 ;;
  esac
done

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This builds a Mac app, so it has to run on the Mac." >&2
  echo "Everything that CAN be checked elsewhere is in ./verify.sh — run that instead." >&2
  exit 1
fi

if ! command -v swift >/dev/null 2>&1; then
  echo "There is no swift here. Install the command line tools once:  xcode-select --install" >&2
  exit 1
fi

cd "$HERE"

if [ "$SKIP_TESTS" -eq 0 ]; then
  echo "Testing the core…"
  swift test
  echo
fi

echo "Building $APP_NAME (release)…"
swift build -c release --disable-sandbox --product "$BINARY"

BUILT=$(swift build -c release --show-bin-path)/$BINARY
if [ ! -x "$BUILT" ]; then
  echo "The build finished but $BUILT is not there." >&2
  exit 1
fi

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cp "$BUILT" "$BUNDLE/Contents/MacOS/$BINARY"
cp "$HERE/Info.plist" "$BUNDLE/Contents/Info.plist"
printf 'APPL????' > "$BUNDLE/Contents/PkgInfo"
# Sign with the ad-hoc identity so the app keeps one identity across rebuilds; without this
# every rebuild is a new app to the system and any permission you granted is asked for again.
codesign --force --sign - "$BUNDLE" >/dev/null 2>&1 || echo "  (not signed; that is fine for a local build)"
echo "  built $BUNDLE"

if [ "$INSTALL" -eq 1 ]; then
  DESTINATION="/Applications/$APP_NAME.app"
  rm -rf "$DESTINATION"
  cp -R "$BUNDLE" "$DESTINATION"
  echo "  installed $DESTINATION"
  BUNDLE="$DESTINATION"
fi

if [ "$LOGIN" -eq 1 ]; then
  osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$BUNDLE\", hidden:false}" >/dev/null
  echo "  it will open at login (System Settings › General › Login Items to undo)"
fi

echo
echo "Open it:  open \"$BUNDLE\""
echo "The first run asks for the CROOKS OS folder if it is not in one of the usual places."
