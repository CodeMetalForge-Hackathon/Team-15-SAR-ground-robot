// Team-15 M5StickC -> RoverC-Pro USB-serial motor bridge.  DRAFT: NOT COMPILED, NOT FLASHED, NOT RUN.
// Protocol and rules: docs/rover/BRIDGE_PROTOCOL.md. Executable model (keep in lockstep):
// rover/tests/bridge_model.py. Flashing needs separate written approval, with the RoverC power switch OFF.
//
// Safety rules implemented here:
//  - Motors are written to ZERO in setup() before the serial port is even opened.
//  - Starts DISARMED. Non-zero speeds are refused (N frame) unless ARMED by an "A" frame naming an operator.
//  - Watchdog: no VALID frame for WATCHDOG_MS (250 ms) while armed or moving -> motors ZERO, state WDSTOP.
//    Leaving WDSTOP needs a new ARM. Invalid / bad-CRC frames never feed the watchdog.
//  - Button A on the StickC = local e-stop: ZERO + state ESTOP (needs re-ARM).
//  - I2C write failure -> ZERO attempt + state I2CERR (needs re-ARM after the fault is fixed).
//  - Only the 4 motor registers 0x00-0x03 are ever written. Servo registers are never touched.
//  - |speed| > 100 is refused (library clamp).
//
// Unverified until the controller is identified: board model (M5Unified covers StickC / Plus / Plus2),
// the hat pin map (RoverC docs: SDA = G0, SCL = G26), and the RoverC firmware revision.

#include <M5Unified.h>
#include <Wire.h>

static const uint8_t ROVER_ADDR = 0x38;
static const uint8_t REG_MOTOR0 = 0x00;
static const int SDA_PIN = 0;    // RoverC-Pro docs; verify on the identified StickC model
static const int SCL_PIN = 26;
static const uint32_t I2C_HZ = 100000;
static const uint32_t WATCHDOG_MS = 250;   // must stay <= 300 (bench requirement)
static const int MAX_SPEED = 100;

enum State { BOOT, DISARMED, ARMED, WDSTOP, ESTOP, I2CERR };
static const char *STATE_NAMES[] = {"BOOT", "DISARMED", "ARMED", "WDSTOP", "ESTOP", "I2CERR"};

static State state = BOOT;
static uint32_t lastValidMs = 0;
static uint32_t wdTrips = 0, i2cErrs = 0;
static int8_t regs[4] = {0, 0, 0, 0};
static char line[96];
static size_t lineLen = 0;
static bool lineOverflow = false;

static uint8_t crc8(const char *s, size_t n) {
  uint8_t c = 0;
  for (size_t i = 0; i < n; i++) {
    c ^= (uint8_t)s[i];
    for (int b = 0; b < 8; b++) c = (c & 0x80) ? (uint8_t)((c << 1) ^ 0x07) : (uint8_t)(c << 1);
  }
  return c;
}

static bool writeMotors(const int8_t s[4]) {
  Wire.beginTransmission(ROVER_ADDR);
  Wire.write(REG_MOTOR0);
  for (int i = 0; i < 4; i++) Wire.write((uint8_t)s[i]);
  if (Wire.endTransmission() != 0) return false;
  for (int i = 0; i < 4; i++) regs[i] = s[i];
  return true;
}

static void allZero() {
  static const int8_t z[4] = {0, 0, 0, 0};
  if (!writeMotors(z)) {
    i2cErrs++;
    state = I2CERR;
  }
}

static bool anyNonZero() { return regs[0] || regs[1] || regs[2] || regs[3]; }

static void sendFrame(const char *payload) {
  char out[112];
  uint8_t c = crc8(payload, strlen(payload));
  snprintf(out, sizeof out, "%s*%02X\n", payload, c);
  Serial.print(out);
}

static void ack(const char *seq) {
  char p[80];
  snprintf(p, sizeof p, "K,%s,%s,%lu,%lu", seq, STATE_NAMES[state], (unsigned long)wdTrips, (unsigned long)i2cErrs);
  sendFrame(p);
}

static void nak(const char *seq, const char *why) {
  char p[80];
  snprintf(p, sizeof p, "N,%s,%s", seq, why);
  sendFrame(p);
}

static bool isDigits(const char *s) {
  if (!*s) return false;
  for (; *s; s++) if (*s < '0' || *s > '9') return false;
  return true;
}

static bool parseSpeed(const char *s, int *out) {
  char *end;
  long v = strtol(s, &end, 10);
  if (end == s || *end) return false;
  *out = (int)v;
  return v >= -32768 && v <= 32767;
}

// Handles one complete line (without '\n'). Invalid frames are dropped silently and do not feed the watchdog.
static void handleLine(char *s) {
  char *star = strrchr(s, '*');
  if (!star || strlen(star + 1) != 2) return;
  unsigned int cc;
  if (sscanf(star + 1, "%2X", &cc) != 1) return;
  if (crc8(s, star - s) != (uint8_t)cc) return;
  *star = '\0';

  char *f[7];
  int n = 0;
  for (char *tok = strtok(s, ","); tok && n < 7; tok = strtok(NULL, ",")) f[n++] = tok;
  if (n < 2 || !isDigits(f[1])) return;
  const char *seq = f[1];
  lastValidMs = millis();

  if (!strcmp(f[0], "Z") && n == 2) {
    allZero();
    ack(seq);
  } else if (!strcmp(f[0], "P") && n == 2) {
    ack(seq);
  } else if (!strcmp(f[0], "A") && n == 3 && f[2][0]) {
    allZero();
    if (state != I2CERR) state = ARMED;
    ack(seq);
  } else if (!strcmp(f[0], "M") && n == 6) {
    int v[4];
    for (int i = 0; i < 4; i++) {
      if (!parseSpeed(f[2 + i], &v[i])) { nak(seq, "bad-speed"); return; }
    }
    for (int i = 0; i < 4; i++) {
      if (v[i] > MAX_SPEED || v[i] < -MAX_SPEED) { allZero(); nak(seq, "range"); return; }
    }
    if (state != ARMED) {
      char why[24];
      snprintf(why, sizeof why, "not-armed-%s", STATE_NAMES[state]);
      allZero();
      nak(seq, why);
      return;
    }
    int8_t sp[4] = {(int8_t)v[0], (int8_t)v[1], (int8_t)v[2], (int8_t)v[3]};
    if (!writeMotors(sp)) {
      i2cErrs++;
      state = I2CERR;
      allZero();
      nak(seq, "i2c");
      return;
    }
    ack(seq);
  } else {
    nak(seq, "unknown");
  }
}

static void drawStatus() {
  M5.Display.fillScreen(state == ARMED ? TFT_DARKGREEN : TFT_MAROON);
  M5.Display.setCursor(2, 2);
  M5.Display.printf("%s\nwd:%lu i2c:%lu\n%d %d %d %d", STATE_NAMES[state], (unsigned long)wdTrips,
                    (unsigned long)i2cErrs, regs[0], regs[1], regs[2], regs[3]);
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  Wire.begin(SDA_PIN, SCL_PIN, I2C_HZ);
  allZero();                           // motors zero BEFORE the host can say anything
  if (state != I2CERR) state = DISARMED;
  Serial.begin(115200);
  lastValidMs = millis();
  M5.Display.setRotation(1);
  M5.Display.setTextSize(2);
  drawStatus();
}

void loop() {
  M5.update();
  if (M5.BtnA.wasPressed()) {          // local e-stop
    allZero();
    state = ESTOP;
  }
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (!lineOverflow) { line[lineLen] = '\0'; handleLine(line); }
      lineLen = 0;
      lineOverflow = false;
    } else if (c != '\r') {
      if (lineLen < sizeof(line) - 1) line[lineLen++] = c;
      else lineOverflow = true;        // oversize line: drop the whole line
    }
  }
  if (millis() - lastValidMs > WATCHDOG_MS && state != WDSTOP && (state == ARMED || anyNonZero())) {
    allZero();
    wdTrips++;
    state = WDSTOP;
  }
  static State shown = BOOT;
  static uint32_t lastDraw = 0;
  if (state != shown || millis() - lastDraw > 500) { drawStatus(); shown = state; lastDraw = millis(); }
  delay(1);
}
