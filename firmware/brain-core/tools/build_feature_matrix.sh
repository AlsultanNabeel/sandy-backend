#!/bin/bash
# Builds the brain once per enabled feature, with that one feature switched off in
# config.h, and says which builds fail. A feature that cannot be switched off alone is a
# feature whose code leaks past its guard (the Wi-Fi switch once lived inside the display's).
# Run from firmware/brain-core with ESP-IDF exported. Restores config.h when done.
set -u
cfg=main/include/config.h
orig=$(mktemp)
cp "$cfg" "$orig"
trap 'cp "$orig" "$cfg"; rm -f "$orig"' EXIT
fail=0
for f in $(grep -E "^#define ENABLE_[A-Z_]+ +1" "$orig" | awk '{print $2}' | sort -u); do
  cp "$orig" "$cfg"
  sed -i.bak -E "s/^#define $f( +)1/#define $f\\10/" "$cfg" && rm -f "$cfg.bak"
  if idf.py -B build-matrix build > "build-matrix-$f.log" 2>&1; then
    echo "$f off: builds"
    rm -f "build-matrix-$f.log"
  else
    echo "$f off: FAILS (build-matrix-$f.log)"
    fail=1
  fi
done
exit $fail
