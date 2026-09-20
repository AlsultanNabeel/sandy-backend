# Running the iOS app

Everything lives here: the Xcode project (`SandyApp.xcodeproj`), the app
sources (`SandyApp/`, including `Info.plist`, entitlements and assets), the
widget extension (`SandyWidget/`) and the tests (`SandyAppTests/`,
`SandyAppUITests/`). There is no second copy to sync.

## Build

1. Open `ios/SandyApp.xcodeproj`. The targets use synchronized groups, so a new
   file under `SandyApp/` is picked up with no `.xcodeproj` edits.
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
