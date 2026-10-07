# SandyAppTests

Unit tests for the iOS app. They live **outside** `ios/SandyApp/` on purpose: the
app target uses an Xcode 16 file-system-synchronized group rooted at the app
source folder, so anything under it is compiled into the **app** target. XCTest
files must not land there (the app target doesn't link XCTest), so the tests sit
in this sibling folder and map to a separate test target.

## Running

`ios/SandyApp.xcodeproj` already has the `SandyAppTests` target, mapped to this
folder as a synchronized group. Open the project and press `⌘U`.

From the terminal, run `scripts/run_ios_tests.sh` (pass `-only-testing:SandyAppTests/<Suite>`
for less). Every run, pass or fail, is kept in `ios/test-results/<date-time>/` (`latest`
points at the newest): the whole log, the result bundle, and `failures.txt` naming each
failed test with its message, so a failure that comes and goes is known the first time.

## What's covered today

- [APIClientTests.swift](APIClientTests.swift) — the network-free JWT payload
  decode behind `APIClient.currentUserId` (valid id, missing token, malformed
  token, no `user_id`, unpadded base64URL).

## The network in tests

`StubNetwork.install { request in (status, body) }` swaps `APIClient.session` for one
that answers through `StubURLProtocol`, and records what was sent
(`StubNetwork.requests`, bodies read whole). Call `StubNetwork.uninstall()` in
`tearDown`. Build clients with `TestClient.make()`: its token lives in memory and the
address is not mirrored for the extensions, so a test never signs the app out.

## Growing it

The store layer currently depends on the concrete `APIClient`. As stores move to
depend on `APIClientProtocol` (already defined for this purpose), inject a mock
conforming to it and add tests for the optimistic toggle/delete/rollback paths in
`TasksStore` and the session flow in `AppState`.
