#!/usr/bin/env bash
# Sync the canonical iOS source tree into the Xcode build copy.
#
# Replaces the old `cp *.swift` mirror, which only ever copied a flat directory
# and silently dropped anything in a subfolder. The app source now lives in a
# real folder structure (App/, Core/, Features/…), so the mirror has to be a
# tree sync. Xcode 16 synchronized groups pick the tree up automatically.
#
# What this does:
#   - copies every *.swift, preserving its folder,
#   - deletes *.swift in the build copy that no longer exist in canonical
#     (so moves/renames propagate; no stale duplicate type definitions),
#   - never touches non-Swift build files (Info.plist, Assets.xcassets,
#     *.xcodeproj, the widget target, entitlements) — they are excluded from
#     both the transfer and the deletion pass.
#
# Usage:  scripts/sync_ios.sh            # default build copy path below
#         SANDY_IOS_BUILD=/path scripts/sync_ios.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/ios/SandyApp/"
DST="${SANDY_IOS_BUILD:-$HOME/Desktop/SandyApp/SandyApp}/"

if [ ! -d "$DST" ]; then
  echo "Build copy not found: $DST" >&2
  echo "Set SANDY_IOS_BUILD to the Xcode target's SandyApp/ source folder." >&2
  exit 1
fi

# 1) copy every *.swift, creating its folder; touch nothing else (additive).
rsync -av --include='*/' --include='*.swift' --exclude='*' "$SRC" "$DST"

# 2) prune ONLY *.swift that no longer exist in canonical (propagates moves and
#    renames). Scoped strictly to .swift, so non-Swift build files can't be hit.
( cd "$DST" && find . -name '*.swift' -print ) | while IFS= read -r rel; do
  rel="${rel#./}"
  if [ ! -f "$SRC$rel" ]; then
    rm -f "$DST$rel"
    echo "pruned stale swift: $rel"
  fi
done

echo "iOS source synced -> $DST"

# 3) unit-test target source (optional): the tests live OUTSIDE ios/SandyApp/ so
#    the app target's synchronized group never tries to compile XCTest files into
#    the app. Mirror them into a sibling SandyAppTests/ next to the app source.
#    One-time: create a "Unit Testing Bundle" target in Xcode whose folder is that
#    SandyAppTests/ (host app = SandyApp); its synchronized group then picks these
#    files up automatically on every later sync. See ios/SandyAppTests/README.md.
TEST_SRC="$REPO_ROOT/ios/SandyAppTests/"
if [ -d "$TEST_SRC" ]; then
  TEST_DST="$(dirname "${DST%/}")/SandyAppTests/"
  mkdir -p "$TEST_DST"
  rsync -av --include='*/' --include='*.swift' --exclude='*' "$TEST_SRC" "$TEST_DST"
  ( cd "$TEST_DST" && find . -name '*.swift' -print ) | while IFS= read -r rel; do
    rel="${rel#./}"
    if [ ! -f "$TEST_SRC$rel" ]; then
      rm -f "$TEST_DST$rel"
      echo "pruned stale test swift: $rel"
    fi
  done
  echo "iOS tests synced -> $TEST_DST"
fi
