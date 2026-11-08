/*
 * Team-15 scanner relay: an out-of-tree app for the Crazyflie 2.1+.
 *
 * Mabelle's passive BLE scanner rides on the drone and prints text lines on a
 * wire into the Crazyflie's UART2 (expansion pin RX2, 115200 8N1). This app
 * keeps what the Jetson needs, packs each line into one app-channel packet
 * (<= 30 bytes) and sends it over the Crazyflie's own radio. The scanner
 * board itself never transmits RF.
 *
 * Packets to the Jetson (first byte = type), decoded by sar_sim/scanner_codec.py:
 *   'H' heartbeat  flags, scanner millis u32, dropped u16, lines u16
 *   'E' scan event "#SCAN_END,..." / "#SCAN_ERROR,..." text (<= 29 bytes)
 *   'U' token row  rssi, 16-byte UUID, name length|flags, name (<= 11 bytes)
 *   'B' advert     rssi, 6-byte address, address type, flags, name length, name (<= 19)
 * "#RAW", "#CONFIG" and other diagnostics stay on the drone.
 *
 * Adverts ("#BLE" lines) are filtered: weaker than t15scan.minRssi, more than
 * t15scan.advHz per address, or over t15scan.capPps in total are dropped.
 * One "focus" address (t15scan.focusA/focusB) skips all three filters.
 * Token rows are kept (max 4 per second per beacon); they carry identity.
 *
 * Packets from the Jetson: 'K' keep-alive, about twice a second. After the
 * first one arrives, if the drone is flying and keep-alives stop for
 * t15scan.wdMs, this app lands the drone. Set wdMs to 0 to turn that off.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "FreeRTOS.h"
#include "task.h"

#include "app.h"
#include "app_channel.h"
#include "crtp_commander_high_level.h"
#include "debug.h"
#include "log.h"
#include "param.h"
#include "supervisor.h"
#include "uart2.h"

#define DEBUG_MODULE "T15SCAN"

#define T15_BAUD 115200
#define LINE_MAX 600          /* longest scanner line kept (a 255-byte advert is ~540) */
#define SLOTS 48              /* addresses tracked for rate limiting */
#define TOKEN_GAP_MS 250      /* max 4 token rows per second per beacon */
#define LAND_S 2.5f

/* Tunable from the Jetson through Crazyflie params, group t15scan. */
static int8_t minRssi = -100;
static uint8_t advHz = 5;
static uint8_t capPps = 60;
static uint32_t focusA = 0;   /* focus address bytes 0..3, big-endian; 0 + 0 = no focus */
static uint16_t focusB = 0;   /* focus address bytes 4..5 */
static uint16_t wdMs = 3000;

/* Counters, readable as log variables. */
static uint16_t nLines, nSent, nRate, nWeak, nBad, nFull, nLong, nLand;

typedef struct { uint8_t key[7]; uint32_t last; } Slot;   /* key[0] = kind, then 6 id bytes */
static Slot slots[SLOTS];
static char line[LINE_MAX + 1];
static uint8_t pkt[APPCHANNEL_MTU];

static uint32_t lastKeep, landAt, tokens, tokenTick;
static bool armed, landing;

static uint32_t nowMs(void) { return T2M(xTaskGetTickCount()); }

static int hexv(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static bool hexByte(const char *s, uint8_t *out) {
  int h = hexv(s[0]), l = hexv(s[1]);
  if (h < 0 || l < 0) return false;
  *out = (uint8_t)(h << 4 | l);
  return true;
}

/* Signed decimal followed by ','. Returns the text after the comma, or NULL. */
static const char *parseInt(const char *s, int *out, int maxDigits) {
  bool neg = (*s == '-');
  int v = 0, n = 0;
  if (neg) s++;
  while (*s >= '0' && *s <= '9') {
    v = v * 10 + (*s++ - '0');
    if (++n > maxDigits) return NULL;
  }
  if (n == 0 || *s != ',') return NULL;
  *out = neg ? -v : v;
  return s + 1;
}

static void send(uint8_t len) {
  if (appchannelSendDataPacket(pkt, len) == pdTRUE) nSent++;
  else nFull++;
}

static uint16_t dropped(void) {
  uint32_t d = (uint32_t)nRate + nWeak + nBad + nFull + nLong;
  return d > 0xFFFF ? 0xFFFF : (uint16_t)d;
}

/* True if this id may send now (at most once per minGapMs). */
static bool allow(uint8_t kind, const uint8_t *id, uint32_t minGapMs) {
  uint32_t now = nowMs();
  int freeSlot = -1, oldest = 0;
  for (int i = 0; i < SLOTS; i++) {
    if (slots[i].key[0] == kind && memcmp(slots[i].key + 1, id, 6) == 0) {
      if (now - slots[i].last < minGapMs) return false;
      slots[i].last = now;
      return true;
    }
    if (slots[i].key[0] == 0 && freeSlot < 0) freeSlot = i;
    if (now - slots[i].last > now - slots[oldest].last) oldest = i;
  }
  int i = freeSlot >= 0 ? freeSlot : oldest;
  slots[i].key[0] = kind;
  memcpy(slots[i].key + 1, id, 6);
  slots[i].last = now;
  return true;
}

/* Shared advert budget: capPps packets per second, up to one second of burst. */
static bool budget(void) {
  uint32_t now = nowMs(), dt = now - tokenTick, cap = (uint32_t)capPps * 1000u;
  tokenTick = now;
  if (dt > 1000) dt = 1000;
  tokens += dt * capPps;
  if (tokens > cap) tokens = cap;
  if (tokens < 1000) return false;
  tokens -= 1000;
  return true;
}

/* "#HEARTBEAT,scanning=1,millis=123,passive=1,discovery=1" */
static void onHeartbeat(const char *s) {
  uint8_t flags = 0;
  if (strstr(s, "scanning=1,")) flags |= 1;
  if (strstr(s, ",passive=1")) flags |= 2;
  if (strstr(s, ",discovery=1")) flags |= 4;
  const char *m = strstr(s, "millis=");
  uint32_t ms = m ? (uint32_t)strtoul(m + 7, NULL, 10) : 0;
  uint16_t d = dropped(), n = nLines;
  pkt[0] = 'H';
  pkt[1] = flags;
  memcpy(pkt + 2, &ms, 4);
  memcpy(pkt + 6, &d, 2);
  memcpy(pkt + 8, &n, 2);
  send(10);
}

static void onScanEvent(const char *s, uint16_t len) {
  if (len > APPCHANNEL_MTU - 1) len = APPCHANNEL_MTU - 1;
  pkt[0] = 'E';
  memcpy(pkt + 1, s, len);
  send((uint8_t)(len + 1));
}

/* "rssi,name,uuid" with uuid = 8-4-4-4-12 hex digits, nothing after it. */
static void onToken(const char *s) {
  int rssi;
  const char *p = parseInt(s, &rssi, 4);
  if (!p || rssi < -128 || rssi > 127) { nBad++; return; }
  const char *comma = strchr(p, ',');
  if (!comma || comma - p > 80) { nBad++; return; }
  uint16_t nameLen = (uint16_t)(comma - p);
  const char *u = comma + 1;
  if (strlen(u) != 36) { nBad++; return; }
  uint8_t uuid[16], flags = 0;
  for (int i = 0, b = 0; i < 36;) {
    if (i == 8 || i == 13 || i == 18 || i == 23) {
      if (u[i] != '-') { nBad++; return; }
      i++;
      continue;
    }
    if ((u[i] >= 'A' && u[i] <= 'F') || (u[i + 1] >= 'A' && u[i + 1] <= 'F')) flags |= 0x20;
    if (!hexByte(u + i, &uuid[b++])) { nBad++; return; }
    i += 2;
  }
  if (!allow('U', uuid, TOKEN_GAP_MS)) { nRate++; return; }
  uint16_t keep = nameLen > 11 ? 11 : nameLen;
  if (keep < nameLen) flags |= 0x80;
  pkt[0] = 'U';
  pkt[1] = (uint8_t)(int8_t)rssi;
  memcpy(pkt + 2, uuid, 16);
  pkt[18] = (uint8_t)(flags | keep);
  memcpy(pkt + 19, p, keep);
  send((uint8_t)(19 + keep));
}

/* "#BLE,rssi,aa:bb:cc:dd:ee:ff,type,payloadhex" */
static void onAdvert(const char *s) {
  int rssi, atype;
  const char *p = parseInt(s + 5, &rssi, 3);
  if (!p || rssi < -127 || rssi > 20) { nBad++; return; }
  uint8_t addr[6];
  for (int i = 0; i < 6; i++) {
    if (!hexByte(p + 3 * i, &addr[i]) || p[3 * i + 2] != (i < 5 ? ':' : ',')) { nBad++; return; }
  }
  p += 18;
  p = parseInt(p, &atype, 1);
  if (!p || atype < 0 || atype > 3) { nBad++; return; }
  size_t hexLen = strlen(p);
  if (hexLen % 2) { nBad++; return; }

  /* Walk the advertising data the same way discovery/server.py does. */
  size_t n = hexLen / 2, off = 0;
  size_t nameOff = 0, nameLen = 0;
  uint8_t flags = 0, b;
  while (off < n) {
    uint8_t size;
    if (!hexByte(p + 2 * off, &size)) { nBad++; return; }
    if (size == 0) break;
    size_t end = off + size + 1;
    if (end > n) { nBad++; return; }
    uint8_t kind;
    if (!hexByte(p + 2 * (off + 1), &kind)) { nBad++; return; }
    if (kind == 8 || kind == 9) {
      nameOff = off + 2;
      nameLen = size - 1;
      flags = (uint8_t)((flags & ~0x04) | (kind == 8 ? 0x04 : 0));
    }
    if (kind == 0xFF && size >= 3) {
      uint8_t lo, hi;
      if (hexByte(p + 2 * (off + 2), &lo) && hexByte(p + 2 * (off + 3), &hi) && lo == 0x4C && hi == 0x00)
        flags |= 0x01;
    }
    off = end;
  }
  for (size_t i = 0; i < n; i++) {
    if (!hexByte(p + 2 * i, &b)) { nBad++; return; }
  }

  uint32_t fa = (uint32_t)addr[0] << 24 | (uint32_t)addr[1] << 16 | (uint32_t)addr[2] << 8 | addr[3];
  uint16_t fb = (uint16_t)(addr[4] << 8 | addr[5]);
  bool focus = (focusA || focusB) && fa == focusA && fb == focusB;
  if (!focus && rssi < minRssi) { nWeak++; return; }
  uint32_t gap = focus ? 100 : 1000u / (advHz ? advHz : 1);
  if (!allow('B', addr, gap)) { nRate++; return; }
  if (!focus && !budget()) { nRate++; return; }

  size_t keep = nameLen > 19 ? 19 : nameLen;
  if (keep < nameLen) {
    flags |= 0x02;
    /* Do not cut a UTF-8 character in half. */
    while (keep > 0 && hexByte(p + 2 * (nameOff + keep), &b) && (b & 0xC0) == 0x80) keep--;
  }
  pkt[0] = 'B';
  pkt[1] = (uint8_t)(int8_t)rssi;
  memcpy(pkt + 2, addr, 6);
  pkt[8] = (uint8_t)atype;
  pkt[9] = flags;
  pkt[10] = (uint8_t)keep;
  for (size_t i = 0; i < keep; i++) hexByte(p + 2 * (nameOff + i), &pkt[11 + i]);
  send((uint8_t)(11 + keep));
}

static void handleLine(const char *s, uint16_t len) {
  nLines++;
  if (strncmp(s, "#BLE,", 5) == 0) onAdvert(s);
  else if (strncmp(s, "#HEARTBEAT,", 11) == 0) onHeartbeat(s);
  else if (strncmp(s, "#SCAN_END", 9) == 0 || strncmp(s, "#SCAN_ERROR", 11) == 0) onScanEvent(s, len);
  else if (s[0] != '#' && len > 0) onToken(s);
}

static void watchdog(void) {
  uint32_t now = nowMs();
  if (landing) {
    if (now - landAt > (uint32_t)(LAND_S * 1000) + 500) {
      crtpCommanderHighLevelStop();
      landing = false;
      armed = false;              /* re-armed by the next keep-alive */
    }
    return;
  }
  if (!armed || wdMs == 0) return;
  if (supervisorIsFlying() && now - lastKeep > wdMs) {
    DEBUG_PRINT("Jetson silent for %lu ms: landing\n", (unsigned long)(now - lastKeep));
    crtpCommanderHighLevelLand(0.0f, LAND_S);
    landing = true;
    landAt = now;
    nLand++;
  }
}

void appMain(void) {
  uart2Init(T15_BAUD);
  DEBUG_PRINT("Team-15 scanner relay on UART2 at %d baud\n", T15_BAUD);
  uint16_t len = 0;
  bool tooLong = false;
  uint8_t rx[APPCHANNEL_MTU];
  tokenTick = nowMs();

  while (1) {
    uint8_t c;
    if (uart2GetCharWithTimeout(&c, M2T(10))) {
      int budgetChars = 512;      /* keep the keep-alive and watchdog checks moving */
      do {
        if (c == '\n') {
          if (tooLong) nLong++;
          else {
            if (len && line[len - 1] == '\r') len--;
            line[len] = 0;
            handleLine(line, len);
          }
          len = 0;
          tooLong = false;
        } else if (len < LINE_MAX) {
          line[len++] = (char)c;
        } else {
          tooLong = true;
        }
      } while (--budgetChars > 0 && uart2GetCharWithTimeout(&c, 0));
    }
    if (appchannelReceiveDataPacket(rx, sizeof(rx), 0) > 0 && rx[0] == 'K') {
      lastKeep = nowMs();
      armed = true;
    }
    watchdog();
  }
}

PARAM_GROUP_START(t15scan)
PARAM_ADD(PARAM_INT8, minRssi, &minRssi)
PARAM_ADD(PARAM_UINT8, advHz, &advHz)
PARAM_ADD(PARAM_UINT8, capPps, &capPps)
PARAM_ADD(PARAM_UINT32, focusA, &focusA)
PARAM_ADD(PARAM_UINT16, focusB, &focusB)
PARAM_ADD(PARAM_UINT16, wdMs, &wdMs)
PARAM_GROUP_STOP(t15scan)

LOG_GROUP_START(t15scan)
LOG_ADD(LOG_UINT16, lines, &nLines)
LOG_ADD(LOG_UINT16, sent, &nSent)
LOG_ADD(LOG_UINT16, rate, &nRate)
LOG_ADD(LOG_UINT16, weak, &nWeak)
LOG_ADD(LOG_UINT16, bad, &nBad)
LOG_ADD(LOG_UINT16, full, &nFull)
LOG_ADD(LOG_UINT16, tooLong, &nLong)
LOG_ADD(LOG_UINT16, land, &nLand)
LOG_GROUP_STOP(t15scan)
