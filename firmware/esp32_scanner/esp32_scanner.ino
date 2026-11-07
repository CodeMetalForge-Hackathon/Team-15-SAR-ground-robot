// C1 passive BLE scanner (SENSOR_ID_SPEC.md). Requires NimBLE-Arduino 2.x.
// Receive only: passive scan (no scan requests), never advertises, never
// connects, and never initializes Wi-Fi. No keys or verification on the board.
//
// Output on USB serial (115200):
//   rssi,name,uuid          one CSV row per advertised 128-bit service UUID
//   #RAW,<adv hex>,<uuid>   diagnostic: raw advertisement bytes for that row
//   #...                    other diagnostics
//   #BLE,rssi,address,address_type,payload_hex  all BLE advertisements (discovery)
#include <NimBLEDevice.h>

static const uint16_t SCAN_INTERVAL_MS = 100;
static const uint16_t SCAN_WINDOW_MS = 100;   // 100% duty cycle

static void printClean(const std::string& s) {
  for (char ch : s) {
    if (ch == ',' || ch == '\n' || ch == '\r' || ch < 0x20 || ch > 0x7e) Serial.print('?');
    else Serial.print(ch);
  }
}

class ScanCB : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* d) override {
    // Separate comment-prefixed channel: existing C1/verifier CSV stays unchanged.
    Serial.print("#BLE,");
    Serial.print(d->getRSSI());
    Serial.print(',');
    Serial.print(d->getAddress().toString().c_str());
    Serial.print(',');
    Serial.print(d->getAddress().getType());
    Serial.print(',');
    for (uint8_t b : d->getPayload()) {
      if (b < 0x10) Serial.print('0');
      Serial.print(b, HEX);
    }
    Serial.println();
    int n = d->getServiceUUIDCount();
    for (int i = 0; i < n; i++) {
      NimBLEUUID u = d->getServiceUUID(i);
      if (u.bitSize() != 128) continue;
      std::string us = u.toString();
      Serial.print(d->getRSSI());
      Serial.print(',');
      printClean(d->getName());
      Serial.print(',');
      Serial.println(us.c_str());
      const std::vector<uint8_t>& p = d->getPayload();
      Serial.print("#RAW,");
      for (uint8_t b : p) { if (b < 0x10) Serial.print('0'); Serial.print(b, HEX); }
      Serial.print(',');
      Serial.println(us.c_str());
    }
  }
  void onScanEnd(const NimBLEScanResults& r, int reason) override {
    Serial.print("#SCAN_END,");
    Serial.println(reason);
    NimBLEDevice::getScan()->start(0, false, true);
  }
};

static ScanCB scanCB;

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) { delay(10); }
  NimBLEDevice::init("");                 // no advertising is configured or started
  NimBLEScan* s = NimBLEDevice::getScan();
  s->setScanCallbacks(&scanCB, true);     // report every advertisement (duplicates wanted)
  s->setActiveScan(false);                // PASSIVE: no scan requests
  s->setInterval(SCAN_INTERVAL_MS);
  s->setWindow(SCAN_WINDOW_MS);
  s->setDuplicateFilter(false);           // controller duplicate filter off
  s->setMaxResults(0);                    // do not store results
  Serial.println("#CONFIG,passive=1,interval_ms=100,window_ms=100,dup_filter=0,"
                 "want_duplicates=1,advertising=0,connections=0,wifi=never_initialized");
  if (s->start(0, false, true)) Serial.println("#SCAN_START");
  else Serial.println("#SCAN_ERROR,start_failed");
}

void loop() {
  Serial.print("#HEARTBEAT,scanning=");
  Serial.print(NimBLEDevice::getScan()->isScanning() ? 1 : 0);
  Serial.print(",millis=");
    Serial.print(millis());
    Serial.println(",passive=1,discovery=1");
  delay(1000);
}
