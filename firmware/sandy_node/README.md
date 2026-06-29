# Sandy Node — generic extension firmware (ESP32)

One firmware for every sellable node. Flash once with the node's printed `CODE`;
the customer pairs it in the app and adds/controls devices with no flashing.

## Flash
1. Arduino IDE → install ESP32 board support.
2. Library Manager: **PubSubClient**, **ArduinoJson**, **IRremoteESP8266**, **ESP32Servo**.
3. Edit the `EDIT THESE PER NODE` block in [sandy_node.ino](sandy_node.ino):
   WiFi, MQTT (`SANDY_MQTT_*`, same broker the backend uses), IR pins, and the
   `OUTPUTS[]` map (id + kind + pin; angles for servo). Leave `NODE_CODE_OVERRIDE`
   empty — the **same firmware** flashes to every node.
4. Upload to the ESP32.

## Pairing code
With `NODE_CODE_OVERRIDE` empty, each node auto-derives a **unique** code from its
chip MAC: `sandy-xxxxxx`. It prints on the Serial monitor at first boot — read it
and put it on the unit's sticker; the customer types it in the app to pair. The
node derives its MQTT id from this code exactly like the backend
(`node_store.code_to_node_id`: lowercase, keep `a-z0-9`), so pairing needs no
handshake.

## MQTT contract
- subscribe: `sandy/node/<node_id>/+`  (last segment = output id)
- status (retained heartbeat, every 30s): `sandy/node/<node_id>/status`
- IR learned code: `sandy/node/<node_id>/ir/learned`

Payloads (the backend validates before publishing): see the header in the `.ino`.

## What works end to end
- **App/Sandy → node control**: the backend publishes the validated command to the
  output topic; the node acts (relay/dimmer/servo/cover/buzzer, IR send of a code).
- **Node → backend ingest** (`integrations/mqtt_ingest.py`): a background subscriber
  consumes `sandy/node/+/status` (heartbeat → online/capabilities) and
  `sandy/node/+/ir/learned` (captured code → stored as the node's last IR).
- **IR learn flow**: app calls `POST /api/nodes/<id>/ir/learn` → node captures the
  next remote press → ingest stores it → app polls `GET /api/nodes/<id>/ir/last`
  → app saves it to a device button via `POST /api/devices/<name>/ir-learn`.
  (Wired in the iOS Control surface: an IR device shows "علّم زر جديد" which runs
  this trigger→poll→save flow.)

## Servo-presses-a-switch
Wire the servo arm over the wall switch. In `OUTPUTS[]` set `kind:"servo"` with
`onAngle`/`offAngle`. Bind a `switch` device in the app to this output → "ضوّي" →
`on` → servo moves to `onAngle`. Calibrate by sending an explicit angle (`0..180`).
