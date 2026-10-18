/* Bounded, typed WebKit format-16 parser. No console-specific metadata
 * embedded. */
#ifndef SPOTLESS_CACHE_FORMAT_H
#define SPOTLESS_CACHE_FORMAT_H
#include "digest.h"
#include <stdlib.h>
#define SP_MAX_RECORD (32u * 1024u * 1024u)
#define SP_IDENTIFIER "https://tv.scdn.co/ps5/v2/f1b1b7e/js/spotifytv.js"
#define SP_VENDOR                                                              \
  "https://tv.scdn.co/ps5/v2/f1b1b7e/js/vendors.dabde9b04d44f0f634b7.js"
#define SP_CSS "https://tv.scdn.co/ps5/v2/f1b1b7e/css/spotifytv.css"
#define SP_SOURCE_SHA                                                          \
  "bccd77047ca9bcda924c1de15f0d9990ce9eb420a5ea0733f5f75f27a47d5ebb"
#define SP_PATCH_SHA                                                           \
  "a1657746d0b5d6df072fe95ee34d20fa6db9665578bc746eefc1d1aad05b52b4"
typedef struct {
  const unsigned char *p;
  size_t size, off;
  int bad;
  sp_hash hash;
} sp_decoder;
typedef struct {
  size_t header, body, header_hash, body_hash, body_size, checksum;
  uint64_t header_bytes, body_bytes;
  unsigned char typed[20];
  char identifier[1024];
} sp_record;
static const unsigned char *sp_take(sp_decoder *d, size_t n, uint32_t tag) {
  if (d->bad || n > d->size - d->off) {
    d->bad = 1;
    return NULL;
  }
  const unsigned char *p = d->p + d->off;
  d->off += n;
  unsigned char t[4] = {(unsigned char)tag, (unsigned char)(tag >> 8),
                        (unsigned char)(tag >> 16), (unsigned char)(tag >> 24)};
  sp_hash_update(&d->hash, t, 4);
  sp_hash_update(&d->hash, p, n);
  return p;
}
static uint64_t sp_number(sp_decoder *d, size_t n, uint32_t tag) {
  const unsigned char *p = sp_take(d, n, tag);
  uint64_t value = 0;
  if (p)
    for (size_t i = 0; i < n; i++)
      value |= (uint64_t)p[i] << (i * 8);
  return value;
}
static int sp_string(sp_decoder *d, char *out, size_t capacity) {
  uint64_t n = sp_number(d, 4, 11);
  if (out && capacity)
    out[0] = 0;
  if (n == 0xffffffffu)
    return 0;
  if (n > 1024 * 1024) {
    d->bad = 1;
    return 1;
  }
  uint64_t narrow = sp_number(d, 1, 3);
  if (narrow > 1) {
    d->bad = 1;
    return 1;
  }
  const unsigned char *p = sp_take(d, (size_t)n * (narrow ? 1 : 2), 101);
  if (!p)
    return 1;
  if (out) {
    if (n >= capacity) {
      d->bad = 1;
      return 1;
    }
    for (size_t i = 0; i < n; i++) {
      if (!p[i * (narrow ? 1 : 2)] || (!narrow && p[i * 2 + 1])) {
        d->bad = 1;
        return 1;
      }
      out[i] = (char)p[i * (narrow ? 1 : 2)];
    }
    out[n] = 0;
  }
  return d->bad;
}
static int sp_decode(const unsigned char *data, size_t size, sp_record *r,
                     int verify) {
  if (size > SP_MAX_RECORD)
    return 1;
  memset(r, 0, sizeof(*r));
  sp_decoder d = {.p = data, .size = size};
  sp_hash_init(&d.hash, 160);
  if (sp_number(&d, 4, 11) != 16)
    return 1;
  char type[32], range[4];
  sp_string(&d, NULL, 0);
  sp_string(&d, type, sizeof(type));
  sp_string(&d, r->identifier, sizeof(r->identifier));
  sp_string(&d, range, sizeof(range));
  if (d.bad || strcmp(type, "Resource") || range[0])
    return 1;
  sp_take(&d, 20, 101);
  sp_take(&d, 20, 101);
  uint64_t ts = sp_number(&d, 8, 29);
  if (((ts >> 52) & 0x7ffu) == 0x7ffu)
    return 1; /* IEEE-754 NaN/infinity. */
  r->header_hash = d.off;
  sp_take(&d, 20, 101);
  r->header_bytes = sp_number(&d, 8, 13);
  r->body_hash = d.off;
  sp_take(&d, 20, 101);
  r->body_size = d.off;
  r->body_bytes = sp_number(&d, 8, 13);
  if (sp_number(&d, 1, 3) != 1)
    return 1;
  r->checksum = d.off;
  sp_hash_final(d.hash, r->typed);
  const unsigned char *checksum = sp_take(&d, 20, 101);
  if (d.bad || !checksum || (verify && memcmp(checksum, r->typed, 20)))
    return 1;
  r->header = d.off;
  if (r->header_bytes > SP_MAX_RECORD || r->body_bytes > SP_MAX_RECORD ||
      r->header_bytes > SP_MAX_RECORD - r->header)
    return 1;
  r->body = r->header + (size_t)r->header_bytes;
  return 0;
}
static void sp_salted(const unsigned char *data, size_t size,
                      const unsigned char salt[8], unsigned char out[20]) {
  sp_hash s;
  sp_hash_init(&s, 160);
  sp_hash_update(&s, salt, 8);
  sp_hash_update(&s, data, size);
  sp_hash_final(s, out);
}
static int sp_validate(const unsigned char *data, size_t size,
                       const unsigned char salt[8], sp_record *r) {
  if (sp_decode(data, size, r, 1) || r->body > size ||
      r->body_bytes != size - r->body)
    return 1;
  unsigned char hash[20];
  sp_salted(data + r->header, (size_t)r->header_bytes, salt, hash);
  if (memcmp(hash, data + r->header_hash, 20))
    return 1;
  sp_salted(data + r->body, (size_t)r->body_bytes, salt, hash);
  return memcmp(hash, data + r->body_hash, 20) != 0;
}
static unsigned char *sp_rebuild(const unsigned char *data, size_t size,
                                 const unsigned char salt[8],
                                 const unsigned char *js, size_t js_size,
                                 size_t *out_size) {
  sp_record r;
  if (sp_validate(data, size, salt, &r) ||
      strcmp(r.identifier, SP_IDENTIFIER) ||
      !sp_sha256_matches(data + r.body, (size_t)r.body_bytes, SP_SOURCE_SHA) ||
      !sp_sha256_matches(js, js_size, SP_PATCH_SHA) ||
      js_size > SP_MAX_RECORD - r.body)
    return NULL;
  size_t n = r.body + js_size;
  unsigned char *out = malloc(n);
  if (!out)
    return NULL;
  memcpy(out, data, r.body);
  memcpy(out + r.body, js, js_size);
  unsigned char hash[20];
  sp_salted(js, js_size, salt, hash);
  memcpy(out + r.body_hash, hash, 20);
  for (unsigned i = 0; i < 8; i++)
    out[r.body_size + i] = (unsigned char)((uint64_t)js_size >> (i * 8));
  sp_record updated;
  if (sp_decode(out, n, &updated, 0)) {
    free(out);
    return NULL;
  }
  memcpy(out + updated.checksum, updated.typed, 20);
  if (sp_validate(out, n, salt, &updated)) {
    free(out);
    return NULL;
  }
  *out_size = n;
  return out;
}
#endif
