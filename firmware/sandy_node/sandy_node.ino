// ─────────────────────────────────────────────────────────────────────────
// Sandy Node — generic plug-and-play extension firmware (ESP32, Arduino)
//
// One firmware for every sellable node. Flash it once with the node's printed
// CODE; the customer powers it, pairs it in the app (enters the same code), adds
// a device, and controls it — no flashing, no per-device code.
//
// It derives its MQTT id from the code the SAME way the backend does
// (node_store.code_to_node_id: lowercase, keep [a-z0-9]) so its topics are known
// before pairing — no provisioning handshake.
//
// MQTT contract (broker = SANDY_MQTT_* , TLS):
//   subscribe : sandy/node/<NODE_ID>/+          last segment = output id
//   status    : sandy/node/<NODE_ID>/status     retained JSON heartbeat
//   ir learned: sandy/node/<NODE_ID>/ir/learned raw code captured in learn mode
//
// Outputs are declared in OUTPUTS[] below. The "output id" you give an output is
// what you pick in the app when you bind a device's transport to this node.
//
// Payloads (validated by the backend before publish):
//   relay   : "on" | "off"
//   dimmer  : "on" | "off" | "0".."100"     (PWM duty)
//   servo   : "on" | "off"                  (uses onAngle/offAngle)
//           | "0".."180"                    (move to an explicit angle — calibration)
//   cover   : "open" | "close" | "stop"     (servo/continuous; mapped to angles)
//   ir      : "learn"                        (capture next remote press -> publish)
//           | "<hex code>"                  (blast a previously learned code)
//   buzzer  : "beep" | "[[freq,ms],[freq,ms],...]"  (a melody, as data)
//
// Required libraries (Library Manager): PubSubClient, ArduinoJson,
//   IRremoteESP8266, ESP32Servo.
// ─────────────────────────────────────────────────────────────────────────

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <IRsend.h>
#include <IRrecv.h>
#include <IRutils.h>

// ── EDIT THESE PER NODE ────────────────────────────────────────────────────
const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

const char* MQTT_HOST = "YOUR_BROKER.hivemq.cloud";  // SANDY_MQTT_HOST
const int   MQTT_PORT = 8883;                          // SANDY_MQTT_PORT (TLS)
const char* MQTT_USER = "YOUR_MQTT_USER";
const char* MQTT_PASS = "YOUR_MQTT_PASS";

// Pairing code. Leave EMPTY to auto-derive a unique code from the chip's MAC —
// then the SAME firmware flashes to every node and each gets its own code. Read it
// from the Serial monitor on first boot and print it on the box's sticker; the
// customer types it in the app to pair. Set a value here only to force a code.
const char* NODE_CODE_OVERRIDE = "";

// IR pins (set when you wire the transmitter/receiver).
const int IR_SEND_PIN = 4;
const int IR_RECV_PIN = 15;

// Output map: {id, kind, pin, onAngle, offAngle}
//   kind: "relay" | "dimmer" | "servo" | "cover" | "ir" | "buzzer"
//   onAngle/offAngle used by servo/cover only.
struct Output {
  const char* id;
  const char* kind;
  int pin;
  int onAngle;
  int offAngle;
};

Output OUTPUTS[] = {
  {"relay1", "relay",  26, 0,   0},
  {"light",  "servo",  13, 30,  150},   // a servo arm that presses a wall switch
  {"buzzer", "buzzer", 27, 0,   0},
  {"ir",     "ir",     0,  0,   0},     // pin unused; uses IR_SEND_PIN/IR_RECV_PIN
};
const int OUTPUT_COUNT = sizeof(OUTPUTS) / sizeof(OUTPUTS[0]);
// ────────────────────────────────────────────────────────────────────────────

const char* FW_VERSION = "1.0.0";

WiFiClientSecure netClient;
PubSubClient mqtt(netClient);
IRsend irSend(IR_SEND_PIN);
IRrecv irRecv(IR_RECV_PIN, 1024, 50, true);

Servo servos[8];                 // one Servo per servo/cover output (lazy attach)
bool irLearnMode = false;
unsigned long lastHeartbeat = 0;
String nodeCode;                 // the pairing code (override or MAC-derived)
String nodeId;                   // derived from nodeCode (matches the backend)

// PWM (LEDC) channel allocation for dimmer outputs.
int nextLedcChannel = 0;

// ── id derivation — MUST match backend node_store.code_to_node_id ────────────
String deriveNodeId(const char* code) {
  String out;
  for (const char* p = code; *p; ++p) {
    char c = *p;
    if (c >= 'A' && c <= 'Z') c = c - 'A' + 'a';
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) out += c;
  }
  return out;
}

Output* findOutput(const String& id) {
  for (int i = 0; i < OUTPUT_COUNT; ++i) {
    if (id == OUTPUTS[i].id) return &OUTPUTS[i];
  }
  return nullptr;
}

// ── Output setup ────────────────────────────────────────────────────────────
void setupOutputs() {
  for (int i = 0; i < OUTPUT_COUNT; ++i) {
    Output& o = OUTPUTS[i];
    if (strcmp(o.kind, "relay") == 0) {
      pinMode(o.pin, OUTPUT);
      digitalWrite(o.pin, LOW);
    } else if (strcmp(o.kind, "dimmer") == 0) {
      ledcSetup(nextLedcChannel, 5000, 8);
      ledcAttachPin(o.pin, nextLedcChannel);
      ledcWrite(nextLedcChannel, 0);
      o.offAngle = nextLedcChannel;   // reuse offAngle slot to remember the channel
      nextLedcChannel++;
    } else if (strcmp(o.kind, "servo") == 0 || strcmp(o.kind, "cover") == 0) {
      servos[i].setPeriodHertz(50);
      servos[i].attach(o.pin, 500, 2400);
      servos[i].write(o.offAngle);
    } else if (strcmp(o.kind, "buzzer") == 0) {
      pinMode(o.pin, OUTPUT);
    }
  }
}

// ── Command handlers ────────────────────────────────────────────────────────
void handleRelay(Output& o, const String& p) {
  digitalWrite(o.pin, (p == "on") ? HIGH : LOW);
}

void handleDimmer(Output& o, const String& p) {
  int channel = o.offAngle;  // stored channel
  int duty = 0;
  if (p == "on") duty = 255;
  else if (p == "off") duty = 0;
  else duty = map(constrain(p.toInt(), 0, 100), 0, 100, 0, 255);
  ledcWrite(channel, duty);
}

void handleServo(int idx, Output& o, const String& p) {
  int angle;
  if (p == "on" || p == "open") angle = o.onAngle;
  else if (p == "off" || p == "close") angle = o.offAngle;
  else angle = constrain(p.toInt(), 0, 180);   // explicit angle (calibration)
  servos[idx].write(angle);
}

void handleBuzzer(Output& o, const String& p) {
  if (p.startsWith("[")) {                      // a melody, as data: [[freq,ms],...]
    StaticJsonDocument<512> doc;
    if (deserializeJson(doc, p) == DeserializationError::Ok) {
      for (JsonArray note : doc.as<JsonArray>()) {
        int freq = note[0] | 0;
        int ms = note[1] | 0;
        if (freq > 0) tone(o.pin, freq, ms);
        delay(ms);
      }
      noTone(o.pin);
      return;
    }
  }
  tone(o.pin, 2000, 120);                       // default beep
  delay(120);
  noTone(o.pin);
}

void handleIr(const String& p) {
  if (p == "learn") {
    irLearnMode = true;
    irRecv.enableIRIn();
    return;
  }
  uint64_t code = strtoull(p.c_str(), nullptr, 16);
  if (code != 0) irSend.sendNEC(code);          // NEC is the common AC/TV protocol
}

// ── MQTT ────────────────────────────────────────────────────────────────────
void publishStatus() {
  StaticJsonDocument<512> doc;
  doc["online"] = true;
  doc["firmware_version"] = FW_VERSION;
  JsonArray caps = doc.createNestedArray("capabilities");
  bool hasRelay=false, hasPwm=false, hasServo=false, hasIr=false, hasBuzzer=false;
  JsonArray outs = doc.createNestedArray("outputs");
  for (int i = 0; i < OUTPUT_COUNT; ++i) {
    JsonObject jo = outs.createNestedObject();
    jo["id"] = OUTPUTS[i].id;
    jo["kind"] = OUTPUTS[i].kind;
    String k = OUTPUTS[i].kind;
    if (k == "relay") hasRelay = true;
    else if (k == "dimmer") hasPwm = true;
    else if (k == "servo" || k == "cover") hasServo = true;
    else if (k == "ir") hasIr = true;
    else if (k == "buzzer") hasBuzzer = true;
  }
  if (hasRelay) caps.add("relay");
  if (hasPwm) caps.add("pwm");
  if (hasServo) caps.add("servo");
  if (hasIr) caps.add("ir");
  if (hasBuzzer) caps.add("buzzer");

  char buf[512];
  size_t n = serializeJson(doc, buf);
  String topic = "sandy/node/" + nodeId + "/status";
  mqtt.publish(topic.c_str(), (const uint8_t*)buf, n, true);  // retained
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  String t(topic);
  int slash = t.lastIndexOf('/');
  if (slash < 0) return;
  String outId = t.substring(slash + 1);

  String p;
  p.reserve(len);
  for (unsigned int i = 0; i < len; ++i) p += (char)payload[i];
  p.trim();

  Output* o = findOutput(outId);
  if (o == nullptr) return;

  String k = o->kind;
  if (k == "relay") handleRelay(*o, p);
  else if (k == "dimmer") handleDimmer(*o, p);
  else if (k == "servo" || k == "cover") {
    int idx = (int)(o - OUTPUTS);
    handleServo(idx, *o, p);
  }
  else if (k == "buzzer") handleBuzzer(*o, p);
  else if (k == "ir") handleIr(p);
}

void connectMqtt() {
  while (!mqtt.connected()) {
    String clientId = "sandy-node-" + nodeId;
    if (mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS)) {
      String sub = "sandy/node/" + nodeId + "/+";
      mqtt.subscribe(sub.c_str());
      publishStatus();
    } else {
      delay(2000);
    }
  }
}

// ── Arduino lifecycle ───────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);
  // Pairing code: the override if set, else a unique "sandy-xxxxxx" from the MAC.
  if (strlen(NODE_CODE_OVERRIDE) > 0) {
    nodeCode = String(NODE_CODE_OVERRIDE);
  } else {
    String mac = WiFi.macAddress();         // AA:BB:CC:DD:EE:FF
    mac.replace(":", "");
    nodeCode = "sandy-" + mac.substring(6); // last 3 bytes -> 6 hex chars
  }
  nodeId = deriveNodeId(nodeCode.c_str());
  Serial.println("=====================================");
  Serial.println(" Sandy node pairing code: " + nodeCode);
  Serial.println(" (enter this in the app to pair)");
  Serial.println("=====================================");

  setupOutputs();
  irSend.begin();

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(300); }

  netClient.setInsecure();          // broker TLS without a pinned CA (HiveMQ Cloud)
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(1024);
  mqtt.setCallback(onMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) { WiFi.reconnect(); delay(500); return; }
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  // IR learn: capture one press, publish the raw code, leave learn mode.
  if (irLearnMode) {
    decode_results results;
    if (irRecv.decode(&results)) {
      String hexCode = uint64ToString(results.value, 16);
      String topic = "sandy/node/" + nodeId + "/ir/learned";
      mqtt.publish(topic.c_str(), hexCode.c_str());
      irRecv.disableIRIn();
      irLearnMode = false;
    }
  }

  // Heartbeat every 30s so the app shows the node online and its capabilities.
  if (millis() - lastHeartbeat > 30000) {
    lastHeartbeat = millis();
    publishStatus();
  }
}
