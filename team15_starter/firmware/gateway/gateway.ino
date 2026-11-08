// gateway.ino — the ESP32-S3 plugged into the Jetson by USB.
//
// A dumb, fast pipe:  ESP-NOW from drones  ->  USB serial to the Jetson
//                     USB serial from Jetson ->  ESP-NOW broadcast to drones
// It does not check signatures; the homebase and the drones do that.
//
// Serial format (binary!):  up   = COBS(rssi_byte + packet) + 0x00
//                           down = COBS(packet) + 0x00
// Never print debug text on Serial here: it would corrupt the binary stream.
// Watch the LED instead (blinks on traffic, if your board has one on LED_BUILTIN).
//
// Arduino IDE: board "ESP32S3 Dev Module". Plugged into the native USB port:
// set "USB CDC On Boot: Enabled" (Jetson sees /dev/ttyACM0). Plugged into the
// UART port: leave it Disabled (Jetson sees /dev/ttyUSB0 or /dev/ttyACM0).
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include "t15_protocol.h"

#define WIFI_CHANNEL 1             // same on every board
#define BAUD 921600                // matches homebase.py --baud (ignored over native USB)

static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
typedef struct { uint8_t len; int8_t rssi; uint8_t data[T15_MAX_PKT]; } rx_item_t;
static QueueHandle_t rxq;
static uint8_t inbuf[2 * T15_MAX_FRAME];
static size_t inlen = 0;
static uint32_t led_off_at = 0;

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
  xQueueSend(rxq, &it, 0);
}

static void blink() {
#ifdef LED_BUILTIN
  digitalWrite(LED_BUILTIN, HIGH);
  led_off_at = millis() + 20;
#endif
}

void setup() {
  Serial.begin(BAUD);
#ifdef LED_BUILTIN
  pinMode(LED_BUILTIN, OUTPUT);
#endif
  rxq = xQueueCreate(32, sizeof(rx_item_t));
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) { delay(1000); ESP.restart(); }
  esp_now_peer_info_t peer;
  memset(&peer, 0, sizeof peer);
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = WIFI_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  esp_now_register_recv_cb(on_recv);
}

void loop() {
  rx_item_t it;
  while (xQueueReceive(rxq, &it, 0) == pdTRUE) {            // drones -> Jetson
    uint8_t raw[T15_MAX_PKT + 1], enc[T15_MAX_FRAME];
    raw[0] = (uint8_t)it.rssi;
    memcpy(raw + 1, it.data, it.len);
    size_t n = t15_cobs_encode(raw, it.len + 1, enc);
    enc[n++] = 0x00;
    Serial.write(enc, n);
    blink();
  }
  while (Serial.available()) {                              // Jetson -> drones
    int b = Serial.read();
    if (b < 0) break;
    if (b == 0) {
      uint8_t pkt[T15_MAX_PKT];
      size_t n = inlen ? t15_cobs_decode(inbuf, inlen, pkt, sizeof pkt) : 0;
      if (n >= T15_HDR_LEN + 2) { esp_now_send(BCAST, pkt, n); blink(); }
      inlen = 0;
    } else if (inlen < sizeof inbuf) {
      inbuf[inlen++] = (uint8_t)b;
    } else {
      inlen = 0;                                            // runaway frame: drop it
    }
  }
#ifdef LED_BUILTIN
  if (led_off_at && millis() > led_off_at) { digitalWrite(LED_BUILTIN, LOW); led_off_at = 0; }
#endif
}
