/* Builds firmware/crazyflie_scanner_app/src/t15_scanner.c on a PC so tests can
 * feed it scanner lines and read the packets it would send. */
#include "../../firmware/crazyflie_scanner_app/src/t15_scanner.c"

#define QN 4096
static uint32_t fakeMs;
static uint8_t q[QN][APPCHANNEL_MTU], ql[QN];
static int qh, qt, flying, nLandCalls, nStopCalls;

TickType_t xTaskGetTickCount(void) { return fakeMs; }
int appchannelSendDataPacket(void *d, size_t n) {
  if ((qt + 1) % QN == qh || n > APPCHANNEL_MTU) return 0;
  memcpy(q[qt], d, n);
  ql[qt] = (uint8_t)n;
  qt = (qt + 1) % QN;
  return pdTRUE;
}
size_t appchannelReceiveDataPacket(void *b, size_t m, int t) { (void)b; (void)m; (void)t; return 0; }
bool supervisorIsFlying(void) { return flying; }
int crtpCommanderHighLevelLand(const float h, const float d) { (void)h; (void)d; nLandCalls++; return 0; }
int crtpCommanderHighLevelStop(void) { nStopCalls++; return 0; }
void uart2Init(const uint32_t b) { (void)b; }
bool uart2GetCharWithTimeout(uint8_t *c, const uint32_t t) { (void)c; (void)t; return false; }

void relay_time(uint32_t ms) { fakeMs = ms; }
void relay_line(const char *s) { handleLine(s, (uint16_t)strlen(s)); }
int relay_take(uint8_t *out) {
  if (qh == qt) return 0;
  int n = ql[qh];
  memcpy(out, q[qh], n);
  qh = (qh + 1) % QN;
  return n;
}
void relay_params(int r, int hz, int cap, uint32_t fa, uint16_t fb, int wd) {
  minRssi = (int8_t)r; advHz = (uint8_t)hz; capPps = (uint8_t)cap;
  focusA = fa; focusB = fb; wdMs = (uint16_t)wd;
}
void relay_keepalive(void) { lastKeep = nowMs(); armed = true; }
void relay_flying(int f) { flying = f; }
int relay_watchdog(void) { watchdog(); return nLandCalls * 10 + nStopCalls; }
void relay_counts(uint16_t *out) {
  out[0] = nLines; out[1] = nSent; out[2] = nRate; out[3] = nWeak;
  out[4] = nBad; out[5] = nFull; out[6] = nLong; out[7] = nLand;
}
