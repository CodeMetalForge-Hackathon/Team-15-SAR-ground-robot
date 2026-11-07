// drone_node.ino — runs on the ESP32 strapped to each drone (ESP32, S3, or C6).
//
// Talks ESP-NOW to the ESP32-S3 gateway on the Jetson. Sends telemetry and
// detections; receives waypoints. Works with no flight controller attached
// (bench mode), so the whole radio chain can be tested on a desk.
//
// Teammate hooks (search for "HOOK"):
//   Gavin    get_pose(), apply_waypoint(), battery_pct(), flight_state()
//   Mabelle  call t15_report(...) when the ID/watch sensor hears someone
//   Mohammed call t15_report(...) if CV runs on the drone (or send JSON to the Jetson instead)
//
// Board: any ESP32 in Arduino IDE (esp32 core 2.x or 3.x).
// Serial Monitor at 115200 for debug text; type 'd' (fake thermal hit) or
// 'v' (fake radar vitals) to test detections end to end.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Preferences.h>
#include <math.h>
#include "t15_protocol.h"

// ============================== settings ==============================
#define DRONE_ID      1          // 1, 2, 3 ... unique per drone, matches homebase
#define WIFI_CHANNEL  1          // must be the same on every board
#define SENSING_MASK  (T15_SENS_THERMAL | T15_SENS_MMWAVE)  // sensors this drone carries
// #define T15_KEY "team15-secret"   // military: uncomment, same text as homebase --key
#define USE_MR60BHA2  0          // 1 = read the Seeed 60 GHz radar (needs Seeed_Arduino_mmWave library)
#define BENCH_MODE    1          // 1 = no flight controller: pose follows waypoints at BENCH_SPEED
#define BENCH_SPEED   1.0f       // m/s used by the bench pose model
#define LINK_HOLD_MS  8000       // no homebase this long -> hover
#define LINK_RTB_MS   20000      // ... this long -> fly home to (0,0) on its own
#define DET_RETX_MS   1000       // resend unacknowledged detections this often
#define TX_POWER_QDBM 0          // 0 = default; e.g. 40 = 10 dBm to emit less (EMCON)
// ======================================================================

#ifdef T15_KEY
static const uint8_t *KEY = (const uint8_t *)T15_KEY;
static const size_t KLEN = sizeof(T15_KEY) - 1;
#else
static const uint8_t *KEY = NULL;
static const size_t KLEN = 0;
#endif

static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

typedef struct { uint8_t len; int8_t rssi; uint8_t data[T15_MAX_PKT]; } rx_item_t;
static QueueHandle_t rxq;

typedef struct { bool used; t15_det_t det; uint32_t last_tx; } det_slot_t;
static det_slot_t dq[16];                 // store-and-forward until the homebase acks
static uint16_t next_det_id = 1;

static Preferences prefs;
static uint32_t seq = 0, seq_ceiling = 0;  // survives reboots (replay protection)
static uint32_t last_home_seq = 0;

static t15_wp_t wp;                        // current waypoint from the homebase
static bool have_wp = false;
static uint32_t last_rx_ms = 0, last_tx_ms = 0, tx_period_ms = 500;
static uint8_t state = T15_DS_LANDED;
static uint8_t failsafe = 0;               // 0 none, 1 hold, 2 rtb
static float px = 0, py = 0, pz = 0, pyaw = 0, psig = 0;   // pose, metres from homebase

#if USE_MR60BHA2
#include "Seeed_Arduino_mmWave.h"
HardwareSerial mmSerial(0);                // XIAO ESP32C6 kit: radar is on UART0
SEEED_MR60BHA2 mmWave;
static uint32_t last_mm_report = 0;
#endif

// ======================== HOOK: flight controller ========================
// Pose in metres from the homebase AprilTag/UWB anchor: x east, y north, z up.
// sigma = your 1-sigma position error (VIO drift). Replace with the real source:
// Crazyflie flow deck, UWB ranging, or leave it to the homebase camera
// (CV can send {"type":"pose",...} JSON to the Jetson instead).
static void get_pose(float &x, float &y, float &z, float &yaw, float &sigma) {
#if BENCH_MODE
  static uint32_t last = millis();
  float dt = (millis() - last) / 1000.0f;
  last = millis();
  if (have_wp && failsafe != 1) {
    float tx = failsafe == 2 ? 0 : wp.x, ty = failsafe == 2 ? 0 : wp.y;
    float dx = tx - px, dy = ty - py, d = sqrtf(dx * dx + dy * dy), step = BENCH_SPEED * dt;
    if (d > 1e-3f) { float k = d < step ? 1.0f : step / d; px += dx * k; py += dy * k; }
    pz += (wp.z - pz) * fminf(1.0f, dt);
    psig = fminf(psig + 0.02f * step, 5.0f);
  }
#endif
  x = px; y = py; z = pz; yaw = pyaw; sigma = psig;
}

// Hand the waypoint to the flight controller (MSP/CRSF/cflib...). Bench: just print.
static void apply_waypoint(const t15_wp_t &w) {
  static const char *names[] = {"GOTO", "HOLD", "RTB", "LAND"};
  Serial.printf("[wp %lu] %s x=%.1f y=%.1f z=%.1f\n", (unsigned long)w.wp_seq,
                w.cmd < 4 ? names[w.cmd] : "?", w.x, w.y, w.z);
}

static uint8_t battery_pct() { return 255; }   // 255 = unknown; homebase then uses airtime

// Bench mode reports "flying" 3 s after boot so the homebase starts planning.
// On a real drone return the flight controller's armed/landed state.
static uint8_t flight_state() {
#if BENCH_MODE
  if (millis() < 3000) return T15_DS_LANDED;
#endif
  if (failsafe) return T15_DS_LINK_LOST;
  if (!have_wp) return T15_DS_FLYING;
  if (wp.cmd == T15_CMD_HOLD) return T15_DS_HOLDING;
  if (wp.cmd == T15_CMD_RTB || wp.cmd == T15_CMD_LAND) return T15_DS_RTB;
  return T15_DS_FLYING;
}

// ============================== radio ==============================
static uint32_t next_seq() {
  if (++seq >= seq_ceiling) { seq_ceiling = seq + 1000; prefs.putUInt("seq", seq_ceiling); }
  return seq;
}

static void radio_send(const uint8_t *buf, size_t n) { esp_now_send(BCAST, buf, n); }

#if ESP_ARDUINO_VERSION_MAJOR >= 3
static void on_recv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  rx_item_t it;
  it.rssi = info->rx_ctrl ? info->rx_ctrl->rssi : 0;
#else
static void on_recv(const uint8_t *mac, const uint8_t *data, int len) {
  rx_item_t it;
  it.rssi = 0;
#endif
  if (len <= 0 || len > T15_MAX_PKT) return;
  it.len = (uint8_t)len;
  memcpy(it.data, data, len);
  xQueueSend(rxq, &it, 0);           // never block the WiFi task
}

static void handle_packet(const uint8_t *buf, size_t len) {
  t15_hdr_t h;
  if (t15_check(buf, len, &h, KEY, KLEN, KEY != NULL) != 0) return;   // bad crc / bad signature
  if (h.type != T15_WAYPOINT || h.src != T15_HOME_ID) return;
  if (h.dst != DRONE_ID && h.dst != T15_BROADCAST) return;
  if (KEY) {                          // signed mode: reject replays
    if (h.seq <= last_home_seq) return;
    last_home_seq = h.seq;
  }
  t15_wp_t w;
  t15_get_wp(buf, &w);
  last_rx_ms = millis();
  if (failsafe) { failsafe = 0; Serial.println("[link] homebase back"); }
  tx_period_ms = w.tx_period_ds ? (uint32_t)w.tx_period_ds * 100 : 500;
  for (auto &s : dq)                  // homebase has these: stop resending
    if (s.used && (int16_t)(s.det.det_id - w.det_ack) <= 0) s.used = false;
  if (!have_wp || w.wp_seq != wp.wp_seq) {
    wp = w;
    have_wp = true;
    apply_waypoint(wp);
  }
}

static void send_telemetry() {
  t15_telem_t t;
  get_pose(t.x, t.y, t.z, t.yaw, t.sigma);
  t.battery = battery_pct();
  t.state = state;
  t.sensing = state == T15_DS_LANDED ? 0 : SENSING_MASK;
  t.wp_ack = have_wp ? wp.wp_seq : 0;
  uint8_t buf[T15_MAX_PKT];
  radio_send(buf, t15_encode_telem(buf, DRONE_ID, next_seq(), millis(), &t, KEY, KLEN));
}

// ======================== HOOK: report a person ========================
// Call from any sensor code. conf 0..1. status T15_ST_*. hr/br 0 if unknown.
// dx, dy = where the person is relative to the drone in metres (0, 0 if unknown).
void t15_report(uint8_t sensor_id, float conf, uint8_t status, float hr, float br,
                float range_m, uint32_t tag_id, float dx, float dy) {
  det_slot_t *slot = NULL;
  for (auto &s : dq) if (!s.used) { slot = &s; break; }
  if (!slot) {                         // full: overwrite the oldest
    slot = &dq[0];
    for (auto &s : dq) if ((int16_t)(s.det.det_id - slot->det.det_id) < 0) slot = &s;
  }
  float x, y, z, yaw, sig;
  get_pose(x, y, z, yaw, sig);
  t15_det_t d;
  d.x = x + dx; d.y = y + dy;
  d.sensor = sensor_id;
  d.conf = (uint8_t)fminf(255.0f, fmaxf(0.0f, conf * 255.0f));
  d.status = status;
  d.hr = (uint8_t)fminf(255.0f, fmaxf(0.0f, hr));
  d.br = (uint8_t)fminf(255.0f, fmaxf(0.0f, br));
  d.range_dm = (uint8_t)fminf(255.0f, fmaxf(0.0f, range_m * 10.0f));
  d.det_id = next_det_id++;
  if (next_det_id == 0) next_det_id = 1;
  d.tag_id = tag_id;
  slot->used = true;
  slot->det = d;
  slot->last_tx = 0;                   // goes out on the next loop
  Serial.printf("[det %u] sensor %u conf %.2f hr %.0f br %.0f\n", d.det_id, sensor_id, conf, hr, br);
}

static void send_detections(uint32_t now) {
  int sent = 0;
  for (auto &s : dq) {
    if (!s.used || (s.last_tx && now - s.last_tx < DET_RETX_MS)) continue;
    uint8_t buf[T15_MAX_PKT];
    radio_send(buf, t15_encode_det(buf, DRONE_ID, next_seq(), now, &s.det, KEY, KLEN));
    s.last_tx = now ? now : 1;
    if (++sent >= 2) break;            // don't flood the channel
  }
}

static void check_failsafe(uint32_t now) {
  if (state == T15_DS_LANDED || !have_wp) return;
  uint32_t silent = now - last_rx_ms;
  if (silent > LINK_RTB_MS && failsafe != 2) {
    failsafe = 2;
    t15_wp_t home = wp;
    home.x = 0; home.y = 0; home.cmd = T15_CMD_RTB;
    Serial.println("[link] lost for too long: flying home");
    apply_waypoint(home);
  } else if (silent > LINK_HOLD_MS && failsafe == 0) {
    failsafe = 1;
    t15_wp_t hold = wp;
    float z, yaw, sig;
    get_pose(hold.x, hold.y, z, yaw, sig);
    hold.cmd = T15_CMD_HOLD;
    Serial.println("[link] lost: holding position");
    apply_waypoint(hold);
  }
}

static void poll_sensors(uint32_t now) {
#if USE_MR60BHA2
  if (mmWave.update(100)) {            // blocks up to 100 ms
    float hr = 0, br = 0, dist = 0;
    mmWave.getHeartRate(hr);
    mmWave.getBreathRate(br);
    mmWave.getDistance(dist);
    if ((hr > 0 || br > 0) && now - last_mm_report > 3000) {
      t15_report(T15_SENS_ID_MMWAVE, 0.95f, T15_ST_UNKNOWN, hr, br, dist, 0, 0, 0);
      last_mm_report = now;
    }
  }
#endif
  while (Serial.available()) {         // bench test commands
    char c = Serial.read();
    if (c == 'd') t15_report(T15_SENS_ID_THERMAL, 0.8f, T15_ST_UNKNOWN, 0, 0, 5.0f, 0, 3.0f, 2.0f);
    if (c == 'v') t15_report(T15_SENS_ID_MMWAVE, 0.95f, T15_ST_UNKNOWN, 82, 16, 1.0f, 0, 0, 0);
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  prefs.begin("t15", false);
  seq = prefs.getUInt("seq", 0);       // start above anything sent before the reboot
  seq_ceiling = seq + 1000;
  prefs.putUInt("seq", seq_ceiling);

  rxq = xQueueCreate(16, sizeof(rx_item_t));
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (TX_POWER_QDBM > 0) esp_wifi_set_max_tx_power(TX_POWER_QDBM);
  if (esp_now_init() != ESP_OK) { Serial.println("ESP-NOW init failed"); delay(1000); ESP.restart(); }
  esp_now_peer_info_t peer;
  memset(&peer, 0, sizeof peer);
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = WIFI_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;                // integrity comes from T15_KEY signatures instead
  esp_now_add_peer(&peer);
  esp_now_register_recv_cb(on_recv);
#if USE_MR60BHA2
  mmWave.begin(&mmSerial);
#endif
  Serial.printf("drone %d up: channel %d, %s, MAC %s\n", DRONE_ID, WIFI_CHANNEL,
                KEY ? "SIGNED" : "unsigned", WiFi.macAddress().c_str());
}

void loop() {
  uint32_t now = millis();
  rx_item_t it;
  while (xQueueReceive(rxq, &it, 0) == pdTRUE) handle_packet(it.data, it.len);
  state = flight_state();
  check_failsafe(now);
  if (now - last_tx_ms >= tx_period_ms) { last_tx_ms = now; send_telemetry(); }
  send_detections(now);
  poll_sensors(now);
  delay(5);
}
