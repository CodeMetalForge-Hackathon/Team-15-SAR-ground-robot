// M5StickC Plus SE + RoverC Pro: USB and Wi-Fi pulse control.
#include <M5Unified.h>
#include <M5_RoverC.h>
#include "wifi_control.h"

M5_RoverC rover;
RoverNetwork network;
char wifiLine[48];
size_t wifiUsed = 0;
bool wifiOverflowed = false;
bool wifiOwned = false;
bool wifiAuthenticated = false;
uint32_t wifiConnectedAt = 0;
String lastStationIP;
bool ready = false;
bool moving = false;
bool locked = false;
uint32_t lastMove = 0;
constexpr uint32_t PULSE_MS = 250;
char line[384];
size_t used = 0;
bool overflowed = false;
uint32_t moveCount = 0;
char lastDirection = '-';
int lastPower = 0;
uint32_t lastBaseProbe = 0;

bool readMotors(int8_t* motors) {
  Wire.beginTransmission(0x38);
  Wire.write(0x00);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(uint8_t(0x38), uint8_t(4)) != 4) return false;
  for (int i = 0; i < 4; ++i) motors[i] = int8_t(Wire.read());
  return true;
}

void drawStatus(const char* state) {
  M5.Display.fillScreen(locked ? TFT_RED : TFT_BLACK);
  M5.Display.setCursor(0, 0);
  M5.Display.setTextSize(2);
  M5.Display.println("Rover USB + WiFi");
  M5.Display.println(state);
  M5.Display.printf("Last: %c power %d\n", lastDirection, lastPower);
  M5.Display.printf("Moves RX: %lu\n", (unsigned long)moveCount);
  M5.Display.setTextSize(1);
  M5.Display.printf("WiFi: %s\n", network.ssid.c_str());
  M5.Display.printf("Key: %s\n", network.password.c_str());
  M5.Display.printf("AP: %s:5000\n", WiFi.softAPIP().toString().c_str());
  M5.Display.printf("LAN: %s %s\n", network.state(), WiFi.localIP().toString().c_str());
  M5.Display.println("Front button locks motors");
}

void stopMotors() {
  if (ready) rover.setSpeed(0, 0, 0);
  moving = false;
}

// Retry while stopped: a base that powers up after the M5 must not remain READY=0.
void refreshBase() {
  if (moving) return;
  int8_t values[4] = {};
  bool detected = readMotors(values);
  if (detected && (values[0] || values[1] || values[2] || values[3])) {
    rover.setSpeed(0, 0, 0);
    detected = readMotors(values) && !values[0] && !values[1] && !values[2] && !values[3];
  }
  if (ready != detected) {
    ready = detected;
    drawStatus(locked ? "LOCKED: reset" : ready ? "READY / stopped" : "NO BASE / power");
    Serial.printf("BASE_DETECTED=%d\n", ready);
  }
}

void execute(const char* text, Print& reply, bool usb = true) {
  if (!strcmp(text, "WIFI_STATUS")) { network.status(reply); return; }
  if (!strcmp(text, "WIFI_CREDENTIALS")) {
    if (usb) network.status(reply, true);
    else reply.println("ERR USB_ONLY");
    return;
  }
  if (!strncmp(text, "WIFI_JOIN ", 10) || !strcmp(text, "WIFI_FORGET")) {
    if (!usb) { reply.println("ERR USB_ONLY"); return; }
    stopMotors();
    network.client.stop();
    wifiOwned = false;
    wifiAuthenticated = false;
    wifiUsed = 0;
    if (!strcmp(text, "WIFI_FORGET")) network.forget(reply);
    else network.configure(text + 10, reply);
    drawStatus("STOP / WiFi setup");
    return;
  }
  if (!strcmp(text, "HELLO")) {
    refreshBase();
    reply.printf("ROVERC_USB_V1 READY=%d LOCKED=%d\n", ready, locked);
    int8_t motors[4] = {};
    bool motorBus = readMotors(motors);
    reply.printf("MOTOR_STATUS I2C=%d VALUES=%d,%d,%d,%d MOVES_RX=%lu\n",
                  motorBus, motors[0], motors[1], motors[2], motors[3],
                  (unsigned long)moveCount);
    return;
  }
  if (!strcmp(text, "STOP")) {
    stopMotors();
    drawStatus(locked ? "LOCKED: reset" : "STOP / USB");
    reply.println("OK STOP");
    return;
  }
  if (usb && wifiOwned && wifiAuthenticated) {
    reply.println("ERR WIFI_CONTROLLER_ACTIVE");
    return;
  }
  refreshBase();
  char direction = 0, extra = 0;
  int speed = 0;
  if (sscanf(text, "MOVE %c %d %c", &direction, &speed, &extra) != 2 ||
      speed < 5 || speed > 50 || !strchr("wasdzc", direction) || !ready || locked) {
    stopMotors();
    reply.println("ERR COMMAND_OR_NOT_READY");
    return;
  }
  int x = 0, y = 0, z = 0;
  if (direction == 'w') y = speed;
  if (direction == 's') y = -speed;
  if (direction == 'a') x = -speed;
  if (direction == 'd') x = speed;
  if (direction == 'z') z = -speed;
  if (direction == 'c') z = speed;
  rover.setSpeed(x, y, z);
  ++moveCount;
  lastDirection = direction;
  lastPower = speed;
  int8_t actual[4] = {};
  int8_t expected[4] = {int8_t(y + x - z), int8_t(y - x + z),
                        int8_t(y - x - z), int8_t(y + x + z)};
  if (!readMotors(actual) || memcmp(actual, expected, 4) != 0) {
    stopMotors();
    drawStatus("MOTOR I2C ERROR");
    reply.println("ERR MOTOR_REGISTER_VERIFY");
    return;
  }
  moving = true;
  lastMove = millis();
  drawStatus("MOVE / 250ms");
  reply.println("OK MOVE");
}

void setup() {
  auto cfg = M5.config();
  cfg.internal_imu = false;  // CPlus SE has no onboard IMU.
  cfg.internal_mic = false;  // GPIO0 is needed for the RoverC SDA line.
  cfg.internal_spk = false;
  M5.begin(cfg);
  Serial.begin(115200);
  ready = rover.begin();
  Wire.setTimeOut(20);
  stopMotors();
  network.begin();
  M5.Display.setRotation(1);
  M5.Display.setTextSize(2);
  drawStatus(ready ? "READY / stopped" : "NO ROVER");
  Serial.printf("ROVERC_USB_V1 READY=%d LOCKED=0\n", ready);
}

void loop() {
  M5.update();
  network.tick();
  if (!moving && uint32_t(millis() - lastBaseProbe) >= 1000) {
    lastBaseProbe = millis();
    refreshBase();
  }
  String stationIP = WiFi.localIP().toString();
  if (stationIP != lastStationIP) {
    lastStationIP = stationIP;
    drawStatus(moving ? "MOVE / 250ms" : "STOP / network");
  }
  if (wifiOwned && (!network.client.connected() ||
      (!wifiAuthenticated && uint32_t(millis() - wifiConnectedAt) > 3000))) {
    if (wifiAuthenticated) stopMotors();
    network.client.stop();
    wifiOwned = false;
    wifiAuthenticated = false;
    wifiUsed = 0;
    wifiOverflowed = false;
    drawStatus("STOP / disconnected");
  }
  if (network.server.hasClient()) {
    WiFiClient incoming = network.server.accept();
    if (wifiOwned) incoming.stop();
    else {
      network.client = incoming;
      network.client.setNoDelay(true);
      wifiOwned = true;
      wifiAuthenticated = false;
      wifiConnectedAt = millis();
      wifiUsed = 0;
      wifiOverflowed = false;
      // Movement ownership transfers only after pairing succeeds.
    }
  }
  if (M5.BtnA.wasPressed()) {
    locked = true;  // Latched until reset; queued commands cannot restart motors.
    stopMotors();
    drawStatus("LOCKED: reset");
    Serial.println("ERR LOCKED");
  }
  if (moving && uint32_t(millis() - lastMove) >= PULSE_MS) {
    stopMotors();
    drawStatus("STOP / timeout");
  }
  // Bound work per loop so malformed/continuous serial traffic cannot starve stop checks.
  for (int budget = 0; budget < 64 && Serial.available(); ++budget) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (overflowed) {
        stopMotors();
        Serial.println("ERR OVERFLOW");
      } else {
        line[used] = '\0';
        execute(line, Serial);
      }
      used = 0;
      overflowed = false;
    } else if (used < sizeof(line) - 1 && !overflowed) {
      line[used++] = c;
    } else {
      overflowed = true;
      stopMotors();
    }
  }
  // One TCP client owns movement; USB STOP remains available.
  for (int budget = 0; budget < 64 && wifiOwned && network.client.available(); ++budget) {
    char c = network.client.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (wifiOverflowed) {
        if (wifiAuthenticated) stopMotors();
        network.client.println("ERR OVERFLOW");
      } else {
        wifiLine[wifiUsed] = '\0';
        if (!wifiAuthenticated) {
          String expected = String("AUTH ") + network.password;
          if (expected == wifiLine) {
            stopMotors();
            wifiAuthenticated = true;
            network.client.println("OK AUTH");
            drawStatus("STOP / WiFi client");
          } else {
            network.client.println("ERR AUTH");
            network.client.stop();
          }
        } else execute(wifiLine, network.client, false);
      }
      wifiUsed = 0;
      wifiOverflowed = false;
    } else if (wifiUsed < sizeof(wifiLine) - 1 && !wifiOverflowed) wifiLine[wifiUsed++] = c;
    else { wifiOverflowed = true; if (wifiAuthenticated) stopMotors(); }
  }
  delay(1);
}
