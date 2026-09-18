# Running the iOS app

The Xcode project lives on the owner's Mac (it is not in this repository); this
folder holds the Swift sources (`SandyApp/`) and tests (`SandyAppTests/`).

## Build

1. Open the Sandy Xcode project and make sure every file under `ios/SandyApp/`
   is in the app target (Copy items if needed is **not** required when the
   project references this folder directly).
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
