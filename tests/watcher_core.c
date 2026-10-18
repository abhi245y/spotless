#define SPOTLESS_HOST_TEST
#define SPOTLESS_RESTORE
#include "../payload/watcher.c"
int main(int argc, char **argv) {
  if (argc < 2)
    return 2;
  if (!strcmp(argv[1], "ready")) {
    sp_ready_state s = {0};
    if (sp_ready_step(&s, 11, 22, 1))
      return 1;
    for (int i = 0; i < 4; i++)
      if (sp_ready_step(&s, 11, 22, 1))
        return 1;
    if (!sp_ready_step(&s, 11, 22, 1) || sp_ready_step(&s, 12, 22, 1) ||
        sp_ready_step(&s, 12, 23, 1) || sp_ready_step(&s, 12, 23, 0))
      return 1;
    return 0;
  }
  if (!strcmp(argv[1], "sha1") || !strcmp(argv[1], "sha256")) {
    if (argc != 3)
      return 2;
    unsigned char *data = NULL;
    size_t bytes = 0;
    if (read_regular(argv[2], &data, &bytes, SP_MAX_RECORD))
      return 1;
    unsigned char hash[32];
    unsigned bits = !strcmp(argv[1], "sha1") ? 160 : 256;
    sp_digest(bits, data, bytes, hash);
    free(data);
    for (unsigned i = 0; i < bits / 8; i++)
      printf("%02x", hash[i]);
    puts("");
    return 0;
  }
  unsigned char salt[8];
  if (read_salt(salt))
    return 1;
  if (!strcmp(argv[1], "restore"))
    return restore_ui();
  sp_scan scan;
  int rc = scan_cache(salt, &scan);
  if (!strcmp(argv[1], "scan")) {
    printf("%d %d %d %d %d\n", rc, scan.js, scan.vendor, scan.css,
           scan.matches);
    return rc;
  }
  if (strcmp(argv[1], "apply") || rc || scan.matches != 1 || scan.js < 1 ||
      !scan.vendor || !scan.css)
    return 1;
  if (scan.js == 2)
    return 0;
  return apply_ui(&scan, salt);
}
