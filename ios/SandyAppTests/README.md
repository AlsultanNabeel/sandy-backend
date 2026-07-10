# SandyAppTests

Unit tests for the iOS app. They live **outside** `ios/SandyApp/` on purpose: the
app target uses an Xcode 16 file-system-synchronized group rooted at the app
source folder, so anything under it is compiled into the **app** target. XCTest
files must not land there (the app target doesn't link XCTest), so the tests sit
in this sibling folder and map to a separate test target.

## One-time setup (Xcode GUI, ~1 minute)

The `.xcodeproj` is not in this repo — it lives in the Xcode build copy — so the
test **target** has to be created once from Xcode (the same reason folder/target
changes aren't done from the CLI):

1. Run `scripts/sync_ios.sh` once so `SandyAppTests/` exists next to `SandyApp/`
   in the build copy.
2. In Xcode: **File ▸ New ▸ Target… ▸ Unit Testing Bundle**.
   - Product name: `SandyAppTests`
   - Host Application: `SandyApp`
3. Delete the boilerplate group Xcode adds, then drag the synced `SandyAppTests/`
   folder in as a **synchronized group** (matching how the app target is set up,
   `objectVersion 77`). From then on `scripts/sync_ios.sh` keeps it in sync — no
   more `.xcodeproj` edits.
4. `⌘U` to run.

## After that

`scripts/sync_ios.sh` mirrors every `*.swift` here into the build copy's
`SandyAppTests/` automatically (added in step 3 of that script), exactly like it
does for the app source.

## What's covered today

- [APIClientTests.swift](APIClientTests.swift) — the network-free JWT payload
  decode behind `APIClient.currentUserId` (valid id, missing token, malformed
  token, no `user_id`, unpadded base64URL).

## Growing it

The store layer currently depends on the concrete `APIClient`. As stores move to
depend on `APIClientProtocol` (already defined for this purpose), inject a mock
conforming to it and add tests for the optimistic toggle/delete/rollback paths in
`TasksStore` and the session flow in `AppState`.
