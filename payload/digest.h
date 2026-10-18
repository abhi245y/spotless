/* SHA-1 for WebKit record checksums; SHA-256 for pinned application assets. */
#ifndef SPOTLESS_DIGEST_H
#define SPOTLESS_DIGEST_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct {
  uint32_t h[8];
  uint64_t bytes;
  unsigned used, bits;
  unsigned char block[64];
} sp_hash;
static uint32_t sp_rotl(uint32_t v, unsigned n) {
  return (v << n) | (v >> (32 - n));
}
static uint32_t sp_rotr(uint32_t v, unsigned n) {
  return (v >> n) | (v << (32 - n));
}
static const uint32_t sp_k256[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
static void sp_hash_block(sp_hash *s) {
  uint32_t w[80];
  for (unsigned i = 0; i < 16; i++)
    w[i] = (uint32_t)s->block[i * 4] << 24 |
           (uint32_t)s->block[i * 4 + 1] << 16 |
           (uint32_t)s->block[i * 4 + 2] << 8 | s->block[i * 4 + 3];
  uint32_t a = s->h[0], b = s->h[1], c = s->h[2], d = s->h[3], e = s->h[4],
           f = s->h[5], g = s->h[6], h = s->h[7];
  if (s->bits == 160) {
    for (unsigned i = 16; i < 80; i++)
      w[i] = sp_rotl(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    for (unsigned i = 0; i < 80; i++) {
      uint32_t k = i < 20   ? 0x5a827999
                   : i < 40 ? 0x6ed9eba1
                   : i < 60 ? 0x8f1bbcdc
                            : 0xca62c1d6;
      uint32_t v = i < 20   ? ((b & c) | (~b & d))
                   : i < 40 ? (b ^ c ^ d)
                   : i < 60 ? ((b & c) | (b & d) | (c & d))
                            : (b ^ c ^ d);
      uint32_t t = sp_rotl(a, 5) + v + e + k + w[i];
      e = d;
      d = c;
      c = sp_rotl(b, 30);
      b = a;
      a = t;
    }
  } else {
    for (unsigned i = 16; i < 64; i++) {
      uint32_t x = w[i - 15], y = w[i - 2];
      w[i] = w[i - 16] + (sp_rotr(x, 7) ^ sp_rotr(x, 18) ^ (x >> 3)) +
             w[i - 7] + (sp_rotr(y, 17) ^ sp_rotr(y, 19) ^ (y >> 10));
    }
    for (unsigned i = 0; i < 64; i++) {
      uint32_t t = h + (sp_rotr(e, 6) ^ sp_rotr(e, 11) ^ sp_rotr(e, 25)) +
                   ((e & f) ^ (~e & g)) + sp_k256[i] + w[i];
      uint32_t u = (sp_rotr(a, 2) ^ sp_rotr(a, 13) ^ sp_rotr(a, 22)) +
                   ((a & b) ^ (a & c) ^ (b & c));
      h = g;
      g = f;
      f = e;
      e = d + t;
      d = c;
      c = b;
      b = a;
      a = t + u;
    }
    s->h[5] += f;
    s->h[6] += g;
    s->h[7] += h;
  }
  s->h[0] += a;
  s->h[1] += b;
  s->h[2] += c;
  s->h[3] += d;
  s->h[4] += e;
}
static void sp_hash_init(sp_hash *s, unsigned bits) {
  memset(s, 0, sizeof(*s));
  s->bits = bits;
  const uint32_t sha1[] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476,
                           0xc3d2e1f0};
  const uint32_t sha256[] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                             0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  memcpy(s->h, bits == 160 ? sha1 : sha256,
         bits == 160 ? sizeof(sha1) : sizeof(sha256));
}
static void sp_hash_update(sp_hash *s, const void *data, size_t size) {
  const unsigned char *p = data;
  s->bytes += size;
  while (size) {
    size_t n = 64 - s->used;
    if (n > size)
      n = size;
    memcpy(s->block + s->used, p, n);
    s->used += (unsigned)n;
    p += n;
    size -= n;
    if (s->used == 64) {
      sp_hash_block(s);
      s->used = 0;
    }
  }
}
static void sp_hash_final(sp_hash s, unsigned char *out) {
  uint64_t bits = s.bytes * 8;
  s.block[s.used++] = 0x80;
  if (s.used > 56) {
    memset(s.block + s.used, 0, 64 - s.used);
    sp_hash_block(&s);
    s.used = 0;
  }
  memset(s.block + s.used, 0, 56 - s.used);
  for (unsigned i = 0; i < 8; i++)
    s.block[63 - i] = (unsigned char)(bits >> (i * 8));
  sp_hash_block(&s);
  for (unsigned i = 0; i < s.bits / 8; i++)
    out[i] = (unsigned char)(s.h[i / 4] >> (24 - 8 * (i % 4)));
}
static void sp_digest(unsigned bits, const void *data, size_t size,
                      unsigned char *out) {
  sp_hash s;
  sp_hash_init(&s, bits);
  sp_hash_update(&s, data, size);
  sp_hash_final(s, out);
}
static int sp_sha256_matches(const void *data, size_t size, const char *hex) {
  unsigned char out[32];
  sp_digest(256, data, size, out);
  static const char digits[] = "0123456789abcdef";
  for (unsigned i = 0; i < 32; i++)
    if (digits[out[i] >> 4] != hex[i * 2] ||
        digits[out[i] & 15] != hex[i * 2 + 1])
      return 0;
  return 1;
}
#endif
