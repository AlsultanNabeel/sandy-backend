#!/bin/zsh
# Runs the app's unit tests on a simulator and always keeps what happened, pass or fail:
#   ios/test-results/<date-time>/log.txt          the whole xcodebuild output
#   ios/test-results/<date-time>/result.xcresult  the result bundle (open it in Xcode)
#   ios/test-results/<date-time>/failures.txt     each failed test by name, with its message
# ios/test-results/latest points at the newest run.
#
#   scripts/run_ios_tests.sh                                      every SandyAppTests test
#   scripts/run_ios_tests.sh -only-testing:SandyAppTests/OutboxTests   just some
# SANDY_SIM picks the simulator (default: iPhone 16 Pro).
set -u
root=${0:A:h:h}
results=$root/ios/test-results
out=$results/$(date +%Y-%m-%d_%H-%M-%S)
mkdir -p $out

(( $# )) || set -- -only-testing:SandyAppTests
xcodebuild test -project $root/ios/SandyApp.xcodeproj -scheme SandyApp \
  -destination "platform=iOS Simulator,name=${SANDY_SIM:-iPhone 16 Pro}" \
  -resultBundlePath $out/result.xcresult "$@" > $out/log.txt 2>&1
code=$?
ln -sfn $out $results/latest

# Failures by name from the result bundle: it also names a failure outside a test case's own
# lines (a suite's set-up, a crash), which the log alone may not.
if [[ -d $out/result.xcresult ]]; then
  xcrun xcresulttool get test-results summary --path $out/result.xcresult > $out/summary.json 2>/dev/null
  python3 - $out/summary.json > $out/failures.txt <<'EOF'
import json, sys
try:
    summary = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    sys.exit()
print(f"result: {summary.get('result')}  passed: {summary.get('passedTests')}  "
      f"failed: {summary.get('failedTests')}  expected failures: {summary.get('expectedFailures')}")
for f in summary.get("testFailures", []):
    print(f"FAILED {f.get('testIdentifierString') or f.get('testName')}: {f.get('failureText', '').strip()}")
EOF
fi
grep -E "Test Case .* failed|error: -\[|BUILD FAILED|\.swift:[0-9]+:[0-9]+: error" $out/log.txt >> $out/failures.txt

grep -E "TEST (SUCCEEDED|FAILED)|BUILD FAILED" $out/log.txt | tail -1
cat $out/failures.txt
echo "kept in $out"
exit $code
