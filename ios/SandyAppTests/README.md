# SandyAppTests

Unit tests for the iOS app. They live **outside** `ios/SandyApp/` on purpose: the
app target uses an Xcode 16 file-system-synchronized group rooted at the app
source folder, so anything under it is compiled into the **app** target. XCTest
files must not land there (the app target doesn't link XCTest), so the tests sit
in this sibling folder and map to a separate test target.

## Running

`ios/SandyApp.xcodeproj` already has the `SandyAppTests` target, mapped to this
folder as a synchronized group. Open the project and press `⌘U`.

## What's covered today

- [APIClientTests.swift](APIClientTests.swift) — the network-free JWT payload
  decode behind `APIClient.currentUserId` (valid id, missing token, malformed
  token, no `user_id`, unpadded base64URL).

## Growing it

The store layer currently depends on the concrete `APIClient`. As stores move to
depend on `APIClientProtocol` (already defined for this purpose), inject a mock
conforming to it and add tests for the optimistic toggle/delete/rollback paths in
`TasksStore` and the session flow in `AppState`.
