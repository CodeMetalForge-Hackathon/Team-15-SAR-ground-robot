// t15_protocol.h — Team-15 radio packets. Same bytes as link/protocol.py.
//
//   drone ESP32 --ESP-NOW--> ESP32-S3 gateway --USB serial--> Jetson homebase
//
// Packet (little-endian):
//   header 14 B | payload N B | [auth tag 8 B if flags&T15_FLAG_AUTH] | crc16 2 B
// Serial framing (gateway <-> Jetson only): COBS(...) + 0x00
//
// Header-only and self-contained (own SHA-256/HMAC, no mbedtls), so it builds
// the same on ESP32, ESP32-S3, ESP32-C6 and a laptop (tests/xcheck.c).
// Change this file and link/protocol.py together, then run tests/test_link.py.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define T15_MAGIC      0xA5
#define T15_VERSION    1
#define T15_HOME_ID    0
#define T15_BROADCAST  0xFF

#define T15_TELEMETRY  1
#define T15_DETECTION  2
#define T15_WAYPOINT   3

#define T15_FLAG_AUTH  0x01
#define T15_TAG_LEN    8
#define T15_HDR_LEN    14
#define T15_TELEM_LEN  27
#define T15_DET_LEN    20
#define T15_WP_LEN     24
#define T15_MAX_PKT    64          // biggest packet is 14+27+8+2 = 51
#define T15_MAX_FRAME  (T15_MAX_PKT + 4)

// sensor ids (detection.sensor); capability bit = 1 << (id - 1)
#define T15_SENS_ID_THERMAL  1
#define T15_SENS_ID_CV       2
#define T15_SENS_ID_MMWAVE   3
#define T15_SENS_ID_BLE      4
#define T15_SENS_ID_ACOUSTIC 5
#define T15_SENS_THERMAL  (1u << 0)
#define T15_SENS_CV       (1u << 1)
#define T15_SENS_MMWAVE   (1u << 2)
#define T15_SENS_BLE      (1u << 3)
#define T15_SENS_ACOUSTIC (1u << 4)

// person status
#define T15_ST_UNKNOWN  0
#define T15_ST_OK       1
#define T15_ST_INJURED  2
#define T15_ST_CRITICAL 3

// drone state
#define T15_DS_LANDED    0
#define T15_DS_FLYING    1
#define T15_DS_HOLDING   2
#define T15_DS_RTB       3
#define T15_DS_LINK_LOST 4

// waypoint commands
#define T15_CMD_GOTO 0
#define T15_CMD_HOLD 1
#define T15_CMD_RTB  2
#define T15_CMD_LAND 3

// errors from t15_check
#define T15_ERR_SHORT  -1
#define T15_ERR_CRC    -2
#define T15_ERR_MAGIC  -3
#define T15_ERR_TYPE   -4
#define T15_ERR_LEN    -5
#define T15_ERR_AUTH   -6
#define T15_ERR_NOAUTH -7

typedef struct { uint8_t type, flags, src, dst; uint32_t seq, t_ms; } t15_hdr_t;
typedef struct { float x, y, z, yaw, sigma; uint8_t battery, state, sensing; uint32_t wp_ack; } t15_telem_t;
typedef struct { float x, y; uint8_t sensor, conf, status, hr, br, range_dm; uint16_t det_id; uint32_t tag_id; } t15_det_t;
typedef struct { float x, y, z, yaw; uint8_t cmd, tx_period_ds; uint16_t det_ack; uint32_t wp_seq; } t15_wp_t;

// ------------------------------------------------------------------ crc16
static inline uint16_t t15_crc16(const uint8_t *d, size_t n) {
  uint16_t crc = 0xFFFF;                        // CRC-16/CCITT-FALSE
  for (size_t i = 0; i < n; i++) {
    crc ^= (uint16_t)d[i] << 8;
    for (int b = 0; b < 8; b++) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
  }
  return crc;
}

// ---------------------------------------------------------- SHA-256 / HMAC
typedef struct { uint32_t h[8]; uint8_t buf[64]; size_t blen; uint64_t total; } t15_sha256_t;

static const uint32_t T15_K256[64] = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};

#define T15_ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static inline void t15_sha256_block(uint32_t *h, const uint8_t *p) {
  uint32_t w[64];
  for (int i = 0; i < 16; i++)
    w[i] = (uint32_t)p[4*i] << 24 | (uint32_t)p[4*i+1] << 16 | (uint32_t)p[4*i+2] << 8 | (uint32_t)p[4*i+3];
  for (int i = 16; i < 64; i++) {
    uint32_t s0 = T15_ROR(w[i-15], 7) ^ T15_ROR(w[i-15], 18) ^ (w[i-15] >> 3);
    uint32_t s1 = T15_ROR(w[i-2], 17) ^ T15_ROR(w[i-2], 19) ^ (w[i-2] >> 10);
    w[i] = w[i-16] + s0 + w[i-7] + s1;
  }
  uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], k = h[7];
  for (int i = 0; i < 64; i++) {
    uint32_t t1 = k + (T15_ROR(e, 6) ^ T15_ROR(e, 11) ^ T15_ROR(e, 25)) + ((e & f) ^ (~e & g)) + T15_K256[i] + w[i];
    uint32_t t2 = (T15_ROR(a, 2) ^ T15_ROR(a, 13) ^ T15_ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
    k = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
  }
  h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += k;
}

static inline void t15_sha256_init(t15_sha256_t *s) {
  static const uint32_t iv[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  memcpy(s->h, iv, sizeof iv); s->blen = 0; s->total = 0;
}

static inline void t15_sha256_update(t15_sha256_t *s, const uint8_t *d, size_t n) {
  s->total += n;
  while (n--) {
    s->buf[s->blen++] = *d++;
    if (s->blen == 64) { t15_sha256_block(s->h, s->buf); s->blen = 0; }
  }
}

static inline void t15_sha256_final(t15_sha256_t *s, uint8_t out[32]) {
  uint64_t bits = s->total * 8;
  uint8_t one = 0x80, zero = 0;
  t15_sha256_update(s, &one, 1);
  while (s->blen != 56) t15_sha256_update(s, &zero, 1);
  uint8_t len[8];
  for (int i = 0; i < 8; i++) len[i] = (uint8_t)(bits >> (56 - 8 * i));
  t15_sha256_update(s, len, 8);
  for (int i = 0; i < 8; i++) {
    out[4*i] = (uint8_t)(s->h[i] >> 24); out[4*i+1] = (uint8_t)(s->h[i] >> 16);
    out[4*i+2] = (uint8_t)(s->h[i] >> 8); out[4*i+3] = (uint8_t)s->h[i];
  }
}

static inline void t15_hmac_sha256(const uint8_t *key, size_t klen, const uint8_t *msg, size_t n, uint8_t out[32]) {
  uint8_t k0[64] = {0}, pad[64], inner[32];
  t15_sha256_t s;
  if (klen > 64) { t15_sha256_init(&s); t15_sha256_update(&s, key, klen); t15_sha256_final(&s, k0); }
  else memcpy(k0, key, klen);
  for (int i = 0; i < 64; i++) pad[i] = k0[i] ^ 0x36;
  t15_sha256_init(&s); t15_sha256_update(&s, pad, 64); t15_sha256_update(&s, msg, n); t15_sha256_final(&s, inner);
  for (int i = 0; i < 64; i++) pad[i] = k0[i] ^ 0x5c;
  t15_sha256_init(&s); t15_sha256_update(&s, pad, 64); t15_sha256_update(&s, inner, 32); t15_sha256_final(&s, out);
}

// constant-time compare so a bad actor can't time the tag check
static inline int t15_tag_equal(const uint8_t *a, const uint8_t *b, size_t n) {
  uint8_t d = 0;
  for (size_t i = 0; i < n; i++) d |= a[i] ^ b[i];
  return d == 0;
}

// ------------------------------------------------------------ byte helpers
static inline void t15_put_u8(uint8_t **p, uint8_t v) { *(*p)++ = v; }
static inline void t15_put_u16(uint8_t **p, uint16_t v) { *(*p)++ = (uint8_t)v; *(*p)++ = (uint8_t)(v >> 8); }
static inline void t15_put_u32(uint8_t **p, uint32_t v) { for (int i = 0; i < 4; i++) *(*p)++ = (uint8_t)(v >> (8 * i)); }
static inline void t15_put_f32(uint8_t **p, float f) { uint32_t v; memcpy(&v, &f, 4); t15_put_u32(p, v); }
static inline uint8_t t15_get_u8(const uint8_t **p) { return *(*p)++; }
static inline uint16_t t15_get_u16(const uint8_t **p) { uint16_t v = (uint16_t)((*p)[0] | ((*p)[1] << 8)); *p += 2; return v; }
static inline uint32_t t15_get_u32(const uint8_t **p) {
  uint32_t v = (uint32_t)(*p)[0] | (uint32_t)(*p)[1] << 8 | (uint32_t)(*p)[2] << 16 | (uint32_t)(*p)[3] << 24;
  *p += 4; return v;
}
static inline float t15_get_f32(const uint8_t **p) { uint32_t v = t15_get_u32(p); float f; memcpy(&f, &v, 4); return f; }

// ------------------------------------------------------------------ encode
static inline uint8_t *t15_put_hdr(uint8_t *o, uint8_t type, const uint8_t *key, uint8_t src, uint8_t dst, uint32_t seq, uint32_t t_ms) {
  t15_put_u8(&o, T15_MAGIC); t15_put_u8(&o, T15_VERSION); t15_put_u8(&o, type);
  t15_put_u8(&o, key ? T15_FLAG_AUTH : 0); t15_put_u8(&o, src); t15_put_u8(&o, dst);
  t15_put_u32(&o, seq); t15_put_u32(&o, t_ms);
  return o;
}

static inline size_t t15_finish(uint8_t *start, uint8_t *o, const uint8_t *key, size_t klen) {
  size_t n = (size_t)(o - start);
  if (key) {
    uint8_t mac[32];
    t15_hmac_sha256(key, klen, start, n, mac);
    memcpy(o, mac, T15_TAG_LEN); o += T15_TAG_LEN; n += T15_TAG_LEN;
  }
  uint16_t c = t15_crc16(start, n);
  t15_put_u16(&o, c);
  return n + 2;
}

// key = NULL for unauthenticated (civilian) mode. out must hold T15_MAX_PKT.
static inline size_t t15_encode_telem(uint8_t *out, uint8_t src, uint32_t seq, uint32_t t_ms,
                                      const t15_telem_t *m, const uint8_t *key, size_t klen) {
  uint8_t *o = t15_put_hdr(out, T15_TELEMETRY, key, src, T15_HOME_ID, seq, t_ms);
  t15_put_f32(&o, m->x); t15_put_f32(&o, m->y); t15_put_f32(&o, m->z); t15_put_f32(&o, m->yaw); t15_put_f32(&o, m->sigma);
  t15_put_u8(&o, m->battery); t15_put_u8(&o, m->state); t15_put_u8(&o, m->sensing); t15_put_u32(&o, m->wp_ack);
  return t15_finish(out, o, key, klen);
}

static inline size_t t15_encode_det(uint8_t *out, uint8_t src, uint32_t seq, uint32_t t_ms,
                                    const t15_det_t *m, const uint8_t *key, size_t klen) {
  uint8_t *o = t15_put_hdr(out, T15_DETECTION, key, src, T15_HOME_ID, seq, t_ms);
  t15_put_f32(&o, m->x); t15_put_f32(&o, m->y);
  t15_put_u8(&o, m->sensor); t15_put_u8(&o, m->conf); t15_put_u8(&o, m->status);
  t15_put_u8(&o, m->hr); t15_put_u8(&o, m->br); t15_put_u8(&o, m->range_dm);
  t15_put_u16(&o, m->det_id); t15_put_u32(&o, m->tag_id);
  return t15_finish(out, o, key, klen);
}

static inline size_t t15_encode_wp(uint8_t *out, uint8_t dst, uint32_t seq, uint32_t t_ms,
                                   const t15_wp_t *m, const uint8_t *key, size_t klen) {
  uint8_t *o = t15_put_hdr(out, T15_WAYPOINT, key, T15_HOME_ID, dst, seq, t_ms);
  t15_put_f32(&o, m->x); t15_put_f32(&o, m->y); t15_put_f32(&o, m->z); t15_put_f32(&o, m->yaw);
  t15_put_u8(&o, m->cmd); t15_put_u8(&o, m->tx_period_ds); t15_put_u16(&o, m->det_ack); t15_put_u32(&o, m->wp_seq);
  return t15_finish(out, o, key, klen);
}

// ------------------------------------------------------------------ decode
// Checks crc, magic, length and (if key) the auth tag. Fills h.
// Returns 0 on success, or a T15_ERR_* code. Payload starts at buf + T15_HDR_LEN.
static inline int t15_check(const uint8_t *buf, size_t len, t15_hdr_t *h,
                            const uint8_t *key, size_t klen, int require_auth) {
  if (len < T15_HDR_LEN + 2) return T15_ERR_SHORT;
  uint16_t crc_rx = (uint16_t)(buf[len - 2] | (buf[len - 1] << 8));
  if (t15_crc16(buf, len - 2) != crc_rx) return T15_ERR_CRC;
  const uint8_t *p = buf;
  if (t15_get_u8(&p) != T15_MAGIC || t15_get_u8(&p) != T15_VERSION) return T15_ERR_MAGIC;
  h->type = t15_get_u8(&p); h->flags = t15_get_u8(&p); h->src = t15_get_u8(&p); h->dst = t15_get_u8(&p);
  h->seq = t15_get_u32(&p); h->t_ms = t15_get_u32(&p);
  size_t plen = h->type == T15_TELEMETRY ? T15_TELEM_LEN : h->type == T15_DETECTION ? T15_DET_LEN :
                h->type == T15_WAYPOINT ? T15_WP_LEN : 0;
  if (!plen) return T15_ERR_TYPE;
  size_t want = T15_HDR_LEN + plen + ((h->flags & T15_FLAG_AUTH) ? T15_TAG_LEN : 0) + 2;
  if (len != want) return T15_ERR_LEN;
  if (h->flags & T15_FLAG_AUTH) {
    if (key) {
      uint8_t mac[32];
      t15_hmac_sha256(key, klen, buf, T15_HDR_LEN + plen, mac);
      if (!t15_tag_equal(mac, buf + T15_HDR_LEN + plen, T15_TAG_LEN)) return T15_ERR_AUTH;
    } else if (require_auth) return T15_ERR_NOAUTH;
  } else if (require_auth) return T15_ERR_NOAUTH;
  return 0;
}

static inline void t15_get_telem(const uint8_t *buf, t15_telem_t *m) {
  const uint8_t *p = buf + T15_HDR_LEN;
  m->x = t15_get_f32(&p); m->y = t15_get_f32(&p); m->z = t15_get_f32(&p); m->yaw = t15_get_f32(&p); m->sigma = t15_get_f32(&p);
  m->battery = t15_get_u8(&p); m->state = t15_get_u8(&p); m->sensing = t15_get_u8(&p); m->wp_ack = t15_get_u32(&p);
}

static inline void t15_get_det(const uint8_t *buf, t15_det_t *m) {
  const uint8_t *p = buf + T15_HDR_LEN;
  m->x = t15_get_f32(&p); m->y = t15_get_f32(&p);
  m->sensor = t15_get_u8(&p); m->conf = t15_get_u8(&p); m->status = t15_get_u8(&p);
  m->hr = t15_get_u8(&p); m->br = t15_get_u8(&p); m->range_dm = t15_get_u8(&p);
  m->det_id = t15_get_u16(&p); m->tag_id = t15_get_u32(&p);
}

static inline void t15_get_wp(const uint8_t *buf, t15_wp_t *m) {
  const uint8_t *p = buf + T15_HDR_LEN;
  m->x = t15_get_f32(&p); m->y = t15_get_f32(&p); m->z = t15_get_f32(&p); m->yaw = t15_get_f32(&p);
  m->cmd = t15_get_u8(&p); m->tx_period_ds = t15_get_u8(&p); m->det_ack = t15_get_u16(&p); m->wp_seq = t15_get_u32(&p);
}

// -------------------------------------------------------------------- COBS
// out must hold n + n/254 + 2 bytes. Returns encoded length (no trailing 0x00).
static inline size_t t15_cobs_encode(const uint8_t *in, size_t n, uint8_t *out) {
  size_t o = 1, code_idx = 0;
  uint8_t code = 1;
  for (size_t i = 0; i < n; i++) {
    if (in[i] == 0) { out[code_idx] = code; code_idx = o++; code = 1; }
    else {
      out[o++] = in[i];
      if (++code == 0xFF) { out[code_idx] = code; code_idx = o++; code = 1; }
    }
  }
  out[code_idx] = code;
  return o;
}

// Returns decoded length, or 0 on a malformed frame.
static inline size_t t15_cobs_decode(const uint8_t *in, size_t n, uint8_t *out, size_t cap) {
  size_t i = 0, o = 0;
  while (i < n) {
    uint8_t code = in[i++];
    if (code == 0 || i + code - 1 > n) return 0;
    for (uint8_t k = 1; k < code; k++) { if (o >= cap) return 0; out[o++] = in[i++]; }
    if (code < 0xFF && i < n) { if (o >= cap) return 0; out[o++] = 0; }
  }
  return o;
}
