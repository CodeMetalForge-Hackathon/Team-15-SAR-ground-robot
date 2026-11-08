// tests/xcheck.c — compiles firmware/t15_protocol.h on a laptop so
// tests/test_link.py can check C and Python produce identical bytes.
//   ./xcheck enc            -> sample packets as hex, one per line
//   ./xcheck dec KEY HEX    -> decode HEX (KEY "-" = none), print fields
//   ./xcheck sha N          -> sha256 of bytes 0..N-1 (i & 0xFF)
//   ./xcheck cobs HEX       -> COBS-encode HEX
#include <stdio.h>
#include <stdlib.h>
#include "../firmware/t15_protocol.h"

static void hex(const uint8_t *b, size_t n) { for (size_t i = 0; i < n; i++) printf("%02x", b[i]); printf("\n"); }
static size_t unhex(const char *s, uint8_t *out) {
  size_t n = 0; unsigned v;
  while (s[0] && s[1] && sscanf(s, "%2x", &v) == 1) { out[n++] = (uint8_t)v; s += 2; }
  return n;
}

int main(int argc, char **argv) {
  if (argc < 2) return 2;
  const uint8_t key[] = "team15-test-key";
  size_t klen = sizeof key - 1;
  uint8_t out[T15_MAX_PKT];
  if (!strcmp(argv[1], "enc")) {
    t15_telem_t t = {12.5f, -3.25f, 1.5f, 0.75f, 0.5f, 87, T15_DS_FLYING, T15_SENS_THERMAL | T15_SENS_MMWAVE, 41};
    t15_det_t d = {30.0f, 42.5f, T15_SENS_ID_MMWAVE, 240, T15_ST_INJURED, 118, 22, 12, 7, 0xDEADBEEF};
    t15_wp_t w = {20.0f, 40.0f, 1.25f, 0.0f, T15_CMD_GOTO, 5, 6, 99};
    hex(out, t15_encode_telem(out, 2, 1000, 123456, &t, NULL, 0));
    hex(out, t15_encode_telem(out, 2, 1001, 123457, &t, key, klen));
    hex(out, t15_encode_det(out, 3, 77, 5000, &d, NULL, 0));
    hex(out, t15_encode_det(out, 3, 78, 5001, &d, key, klen));
    hex(out, t15_encode_wp(out, 1, 4242, 9, &w, NULL, 0));
    hex(out, t15_encode_wp(out, 1, 4243, 10, &w, key, klen));
    return 0;
  }
  if (!strcmp(argv[1], "dec") && argc == 4) {
    uint8_t buf[256]; size_t n = unhex(argv[3], buf);
    int use_key = strcmp(argv[2], "-") != 0;
    t15_hdr_t h;
    int rc = t15_check(buf, n, &h, use_key ? (const uint8_t *)argv[2] : NULL, use_key ? strlen(argv[2]) : 0, use_key);
    if (rc) { printf("ERR %d\n", rc); return 0; }
    printf("HDR %u %u %u %u %u %u\n", h.type, h.flags, h.src, h.dst, h.seq, h.t_ms);
    if (h.type == T15_TELEMETRY) { t15_telem_t m; t15_get_telem(buf, &m);
      printf("TEL %.4f %.4f %.4f %.4f %.4f %u %u %u %u\n", m.x, m.y, m.z, m.yaw, m.sigma, m.battery, m.state, m.sensing, m.wp_ack); }
    if (h.type == T15_DETECTION) { t15_det_t m; t15_get_det(buf, &m);
      printf("DET %.4f %.4f %u %u %u %u %u %u %u %u\n", m.x, m.y, m.sensor, m.conf, m.status, m.hr, m.br, m.range_dm, m.det_id, m.tag_id); }
    if (h.type == T15_WAYPOINT) { t15_wp_t m; t15_get_wp(buf, &m);
      printf("WPT %.4f %.4f %.4f %.4f %u %u %u %u\n", m.x, m.y, m.z, m.yaw, m.cmd, m.tx_period_ds, m.det_ack, m.wp_seq); }
    return 0;
  }
  if (!strcmp(argv[1], "sha") && argc == 3) {
    size_t n = (size_t)atoi(argv[2]);
    uint8_t *b = malloc(n + 1), mac[32];
    for (size_t i = 0; i < n; i++) b[i] = (uint8_t)i;
    t15_sha256_t s; t15_sha256_init(&s); t15_sha256_update(&s, b, n); t15_sha256_final(&s, mac); hex(mac, 32);
    t15_hmac_sha256(key, klen, b, n, mac); hex(mac, 32);
    free(b);
    return 0;
  }
  if (!strcmp(argv[1], "cobs") && argc == 3) {
    static uint8_t in[2048], enc[2100], dec[2048];
    size_t n = unhex(argv[2], in);
    size_t m = t15_cobs_encode(in, n, enc);
    hex(enc, m);
    size_t k = t15_cobs_decode(enc, m, dec, sizeof dec);
    printf("%s\n", (k == n && !memcmp(in, dec, n)) ? "RT_OK" : "RT_FAIL");
    return 0;
  }
  return 2;
}
