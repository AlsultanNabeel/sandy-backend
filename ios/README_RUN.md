# Running the iOS app

The Xcode project lives on the owner's Mac (it is not in this repository); this
folder holds the Swift sources (`SandyApp/`) and tests (`SandyAppTests/`).

## Build

1. Run `scripts/sync_ios.sh` to mirror every `*.swift` under `ios/SandyApp/`
   into the Xcode build copy (default `~/Desktop/SandyApp/SandyApp`, override
   with `SANDY_IOS_BUILD`). The app target uses synchronized groups, so the
   files are picked up with no `.xcodeproj` edits; the script exits non-zero if
   the build copy does not match the repo. Then open that Xcode project.
2. Signing & Capabilities: your team, plus **Sign in with Apple** and **Push
   Notifications**.
3. Run on a simulator or a device.

## Backend

The app talks to the production backend by default
(`Core/Networking/Backend.swift`, `defaultURL`). Sign-in is Apple, Google or
email; there is no developer/owner password login any more.

## Local network

Only the local camera stream uses plain `http://<device-ip>`. Allow that with
`NSAppTransportSecurity › NSAllowsLocalNetworking = YES` — do **not** enable
`NSAllowsArbitraryLoads`, which turns off TLS checks for every host.
