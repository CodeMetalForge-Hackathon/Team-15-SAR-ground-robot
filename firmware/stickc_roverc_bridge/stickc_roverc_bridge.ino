// Team-15 M5StickC -> RoverC-Pro USB-serial motor bridge.  COMPILES (m5stack:esp32 3.3.10, M5Unified 0.3.0) for
// StickC / StickC Plus / StickC Plus2. NOT FLASHED, NOT RUN on hardware.
// Protocol and rules: docs/rover/BRIDGE_PROTOCOL.md. Executable model (keep in lockstep, same parsing):
// rover/tests/bridge_model.py. Flashing needs separate written approval, with the RoverC power switch OFF.
//
// Safety rules implemented here:
//  - setup() writes ZERO to the motors FIRST, before M5.begin() (which can take hundreds of ms), and
//    again after it. Starts DISARMED, or I2CERR if the zero can't be confirmed.
//  - Non-zero speeds are refused (N frame) unless ARMED by an "A" frame naming an operator AND a session id.
//    M frames must carry the session that ARMED; any other session's M zeroes the motors and DISARMS.
//  - ARM succeeds only if the zero write is confirmed on the I2C bus. ARM is refused in ESTOP.
//  - Watchdog (independent of the Pi, on this MCU's millis()): no ACCEPTED Z/M frame (or ARM) for
//    WATCHDOG_MS (250 ms) while ARMED -> ZERO + WDSTOP. Pings, refused, unknown, bad-CRC, malformed and
//    oversized frames never feed it.
//  - Any failed I2C write makes the output UNKNOWN (bytes may have landed); ZERO is retried every 20 ms
//    until the bus confirms it.
//  - Button A = local e-stop: ZERO + ESTOP. Only a local long press (>= 1 s) on button B clears ESTOP,
//    and only to DISARMED; the Pi can never clear it.
//  - Task watchdog: a hung loop() resets the chip, and setup() zeroes first.
//  - Only the 4 motor registers 0x00-0x03 are ever written. Servo registers are never touched.
//  - |speed| > 100, non-numeric speeds and empty fields are refused (and zero the motors).
//
// RESIDUAL HARDWARE RISKS (not fixable in firmware; bench-test, see BRIDGE_PROTOCOL.md):
//  - The RoverC STM32 holds the last speeds. Between a reset and the first zero write in setup(), and in
//    ESP32 download mode (G0 held LOW at reset: G0 is both SDA and a strapping pin, and on StickC boards the
//    USB-UART auto-program circuit drives it), NOTHING stops the wheels except the RoverC power switch.
//    The Pi opens the port with DTR/RTS deasserted to avoid auto-reset.
//  - Board model (StickC / Plus / Plus2), hat pin map (RoverC docs: SDA = G0, SCL = G26), whether Arduino
//    Wire (I2C port 0) conflicts with M5Unified's Ex_I2C on this board, and the task-watchdog API version.

#include <M5Unified.h>
#include <Wire.h>
#include <esp_task_wdt.h>

static const uint8_t ROVER_ADDR = 0x38;
static const uint8_t REG_MOTOR0 = 0x00;
static const int SDA_PIN = 0;    // RoverC-Pro docs; verify on the identified StickC model
static const int SCL_PIN = 26;
static const uint32_t I2C_HZ = 100000;
static const uint16_t I2C_TIMEOUT_MS = 20;  // a stuck bus must not stall loop() past the watchdog
static const uint32_t WATCHDOG_MS = 250;    // must stay <= 300 (bench requirement)
static const uint32_t ZERO_RETRY_MS = 20;
static const uint32_t TASK_WDT_MS = 1000;   // hung loop() -> chip reset -> setup() zeroes first
static const uint32_t ESTOP_CLEAR_HOLD_MS = 1000;
static const int MAX_SPEED = 100;
static const int MAX_BYTES_PER_LOOP = 256;  // the watchdog check always runs, even under a serial flood
static const size_t LINE_MAX_BYTES = 95;

enum State { BOOT, DISARMED, ARMED, WDSTOP, ESTOP, I2CERR };
static const char *STATE_NAMES[] = {"BOOT", "DISARMED", "ARMED", "WDSTOP", "ESTOP", "I2CERR"};

static State state = BOOT;
static char session[9] = "-";
static uint32_t lastValidMs = 0, lastZeroTryMs = 0;
static uint32_t wdTrips = 0, i2cErrs = 0;
static int8_t regs[4] = {0, 0, 0, 0};       // last output CONFIRMED by the bus
static bool outputUnknown = true;           // until the first zero is confirmed, assume the worst
static char line[LINE_MAX_BYTES + 1];
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
  if (Wire.endTransmission() != 0) {
    i2cErrs++;
    outputUnknown = true;                   // some bytes may have landed: real output is unknown
    return false;
  }
  for (int i = 0; i < 4; i++) regs[i] = s[i];
  outputUnknown = false;
  return true;
}

static void disarm(State s) {
  state = s;
  strcpy(session, "-");
}

static bool allZero() {
  static const int8_t z[4] = {0, 0, 0, 0};
  if (writeMotors(z)) return true;
  disarm(I2CERR);
  return false;
}

static bool maybeMoving() { return outputUnknown || regs[0] || regs[1] || regs[2] || regs[3]; }

static bool isSession(const char *s) {
  if (strlen(s) != 8) return false;
  for (; *s; s++) if (!((*s >= '0' && *s <= '9') || (*s >= 'a' && *s <= 'f'))) return false;
  return true;
}

static bool isSeq(const char *s) {                 // 1-9 digits
  size_t n = strlen(s);
  if (n < 1 || n > 9) return false;
  for (; *s; s++) if (*s < '0' || *s > '9') return false;
  return true;
}

static bool parseSpeed(const char *s, int *out) {  // optional '-', then 1-4 digits; nothing else
  const char *p = s;
  if (*p == '-') p++;
  size_t n = strlen(p);
  if (n < 1 || n > 4) return false;
  for (const char *q = p; *q; q++) if (*q < '0' || *q > '9') return false;
  *out = atoi(s);
  return true;
}

static bool isHex2(const char *s) {
  return strlen(s) == 2 && isxdigit((unsigned char)s[0]) && isxdigit((unsigned char)s[1]);
}

static void sendFrame(const char *payload) {
  char out[128];
  uint8_t c = crc8(payload, strlen(payload));
  snprintf(out, sizeof out, "%s*%02X\n", payload, c);
  Serial.print(out);
}

static void ack(const char *seq) {
  char p[112];
  snprintf(p, sizeof p, "K,%s,%s,%s,%lu,%lu", seq, STATE_NAMES[state], session, (unsigned long)wdTrips,
           (unsigned long)i2cErrs);
  sendFrame(p);
}

static void nak(const char *seq, const char *why) {
  char p[112];
  snprintf(p, sizeof p, "N,%s,%s", seq, why);
  sendFrame(p);
}

// Handles one complete line (without '\n' and '\r'). Invalid frames are dropped silently and never feed
// the watchdog. Fields are split by hand so EMPTY fields are preserved (strtok would collapse them).
static void handleLine(char *s) {
  char *star = strrchr(s, '*');
  if (!star || !isHex2(star + 1)) return;
  unsigned int cc = (unsigned int)strtoul(star + 1, NULL, 16);
  if (crc8(s, star - s) != (uint8_t)cc) return;
  *star = '\0';

  char *f[9];
  int n = 0;
  f[n++] = s;
  for (char *p = s; *p; p++) {
    if (*p == ',') {
      *p = '\0';
      if (n == 9) return;                          // too many fields
      f[n++] = p + 1;
    }
  }
  if (n < 2 || !isSeq(f[1])) return;
  const char *seq = f[1];

  if (!strcmp(f[0], "Z") && n == 2) {
    lastValidMs = millis();
    allZero();
    ack(seq);
  } else if (!strcmp(f[0], "P") && n == 2) {
    ack(seq);                                      // status only: does NOT feed the watchdog
  } else if (!strcmp(f[0], "A") && n == 4 && f[2][0] && isSession(f[3])) {
    if (state == ESTOP) { nak(seq, "estop-local-reset"); return; }
    if (allZero()) {                               // ARM only with zero confirmed (also clears I2CERR)
      state = ARMED;
      strcpy(session, f[3]);
      lastValidMs = millis();
    }
    ack(seq);
  } else if (!strcmp(f[0], "M") && n == 7) {
    if (!isSession(f[2]) || state != ARMED || strcmp(f[2], session) != 0) {
      char why[24];
      bool wasArmed = (state == ARMED);
      if (wasArmed) strcpy(why, "session");
      else snprintf(why, sizeof why, "not-armed-%s", STATE_NAMES[state]);
      allZero();
      if (wasArmed && state == ARMED) disarm(DISARMED);  // a foreign session's frame disarms
      nak(seq, why);
      return;
    }
    int v[4];
    for (int i = 0; i < 4; i++) {
      if (!parseSpeed(f[3 + i], &v[i])) { allZero(); nak(seq, "bad-speed"); return; }
    }
    for (int i = 0; i < 4; i++) {
      if (v[i] > MAX_SPEED || v[i] < -MAX_SPEED) { allZero(); nak(seq, "range"); return; }
    }
    int8_t sp[4] = {(int8_t)v[0], (int8_t)v[1], (int8_t)v[2], (int8_t)v[3]};
    if (!writeMotors(sp)) {
      allZero();
      disarm(I2CERR);
      nak(seq, "i2c");
      return;
    }
    lastValidMs = millis();                        // only an ACCEPTED motion frame feeds the watchdog
    ack(seq);
  } else {
    nak(seq, "unknown");
  }
}

static void drawStatus() {
  M5.Display.fillScreen(state == ARMED ? TFT_DARKGREEN : TFT_MAROON);
  M5.Display.setCursor(2, 2);
  M5.Display.printf("%s%s\nwd:%lu i2c:%lu\n%d %d %d %d", STATE_NAMES[state], outputUnknown ? " ?" : "",
                    (unsigned long)wdTrips, (unsigned long)i2cErrs, regs[0], regs[1], regs[2], regs[3]);
}

static void startTaskWatchdog() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t cfg = {.timeout_ms = TASK_WDT_MS, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&cfg);
#else
  esp_task_wdt_init((TASK_WDT_MS + 999) / 1000, true);
#endif
  esp_task_wdt_add(NULL);
}

void setup() {
  Wire.begin(SDA_PIN, SCL_PIN, I2C_HZ);   // zero FIRST: a reset while moving must stop the wheels ASAP
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  allZero();
  auto cfg = M5.config();
  cfg.external_display_value = 0;          // no Port A (I2C_NUM_0) display probing: Wire owns I2C_NUM_0 for the hat
  cfg.internal_mic = false;                // StickC/Plus PDM mic uses GPIO0 = RoverC SDA (M5StickC Plus SE: none)
  cfg.internal_imu = false;                // M5StickC Plus SE has no IMU
  M5.begin(cfg);                          // display / PMIC init: can take hundreds of ms
  // M5Unified sets GPIO0 to a plain output HIGH on StickC/Plus (CH552 countermeasure). That detaches SDA from
  // I2C, so re-attach the hat bus AFTER M5.begin (the working installed firmware also starts Wire after it).
  Wire.end();
  Wire.begin(SDA_PIN, SCL_PIN, I2C_HZ);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  if (allZero()) state = DISARMED;        // and again: confirmed on the re-attached bus, else I2CERR (no ARM)
  Serial.begin(115200);
  lastValidMs = millis();
  M5.Display.setRotation(1);
  M5.Display.setTextSize(2);
  drawStatus();
  startTaskWatchdog();
}

void loop() {
  esp_task_wdt_reset();
  M5.update();
  if (M5.BtnA.wasPressed()) {             // local e-stop
    allZero();
    disarm(ESTOP);
  }
  if (state == ESTOP && M5.BtnB.pressedFor(ESTOP_CLEAR_HOLD_MS)) {   // local, deliberate clear
    if (allZero()) disarm(DISARMED);
  }
  for (int i = 0; i < MAX_BYTES_PER_LOOP && Serial.available(); i++) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (!lineOverflow) { line[lineLen] = '\0'; handleLine(line); }
      lineLen = 0;
      lineOverflow = false;
    } else if (c != '\r') {
      if (lineLen < LINE_MAX_BYTES) line[lineLen++] = c;
      else lineOverflow = true;           // oversize line: drop the whole line
    }
  }
  uint32_t now = millis();
  if (now - lastValidMs > WATCHDOG_MS && state == ARMED) {
    allZero();
    wdTrips++;
    disarm(WDSTOP);
  }
  if (state != ARMED && maybeMoving() && now - lastZeroTryMs >= ZERO_RETRY_MS) {
    lastZeroTryMs = now;                  // output may be non-zero: keep retrying until confirmed
    allZero();
  }
  static State shown = BOOT;
  static uint32_t lastDraw = 0;
  if (state != shown || now - lastDraw > 500) { drawStatus(); shown = state; lastDraw = now; }
  delay(1);
}
