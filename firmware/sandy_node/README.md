# Sandy Node — generic extension firmware (ESP32)

One firmware for every sellable node. Flash once with the node's printed `CODE`;
the customer pairs it in the app and adds/controls devices with no flashing.

## Flash
1. Arduino IDE → install ESP32 board support.
2. Library Manager: **PubSubClient**, **ArduinoJson**, **IRremoteESP8266**, **ESP32Servo**.
3. Edit the `EDIT THESE PER NODE` block in [sandy_node.ino](sandy_node.ino):
   WiFi, MQTT (`SANDY_MQTT_*`, same broker the backend uses), `NODE_CODE`, IR pins,
   and the `OUTPUTS[]` map (id + kind + pin; angles for servo).
4. Upload to the ESP32.

The node derives its MQTT id from `NODE_CODE` exactly like the backend
(`node_store.code_to_node_id`: lowercase, keep `a-z0-9`). So pairing needs no
handshake — enter the same code in the app.

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
  (The iOS learn UI still needs to be wired to this poll — small follow-up.)

## Servo-presses-a-switch
Wire the servo arm over the wall switch. In `OUTPUTS[]` set `kind:"servo"` with
`onAngle`/`offAngle`. Bind a `switch` device in the app to this output → "ضوّي" →
`on` → servo moves to `onAngle`. Calibrate by sending an explicit angle (`0..180`).
