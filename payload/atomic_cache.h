/* Exact atomic cache writer shared by legacy installer and Spotless watcher. */
static int same_file(const char *a, const char *b) {
  int x = open(a, O_RDONLY | O_NOFOLLOW), y = open(b, O_RDONLY | O_NOFOLLOW);
  struct stat sx, sy;
  int result = 1;
  if (x < 0 || y < 0 || fstat(x, &sx) || fstat(y, &sy) ||
      !S_ISREG(sx.st_mode) || !S_ISREG(sy.st_mode) ||
      sx.st_size != sy.st_size || sx.st_size < 1 ||
      sx.st_size > 32 * 1024 * 1024)
    goto done;
  unsigned char bx[8192], by[8192];
  for (off_t off = 0; off < sx.st_size;) {
    size_t n = sx.st_size - off > 8192 ? 8192 : (size_t)(sx.st_size - off);
    if (read(x, bx, n) != (ssize_t)n || read(y, by, n) != (ssize_t)n ||
        memcmp(bx, by, n))
      goto done;
    off += (off_t)n;
  }
  result = 0;
done:
  if (x >= 0)
    close(x);
  if (y >= 0)
    close(y);
  return result;
}

static int replace_cache(int restore) {
  const char *expected =
      restore ? HOME "/patched.record" : HOME "/original.record";
  const char *replacement =
      restore ? HOME "/original.record" : HOME "/patched.record";
  if (!same_file(record_path, replacement))
    return 0; /* Idempotent retry. */
  struct stat before, current, input;
  if (lstat(record_path, &before) || !S_ISREG(before.st_mode) ||
      same_file(record_path, expected))
    return 1;
  int source = open(replacement, O_RDONLY | O_NOFOLLOW), dest = -1;
  int result = 1, created = 0;
  if (source < 0 || fstat(source, &input) || !S_ISREG(input.st_mode) ||
      input.st_size < 1 || input.st_size > 32 * 1024 * 1024)
    goto done;
  snprintf(temporary_path, sizeof(temporary_path), "%s.spotless.tmp",
           record_path);
  dest = open(temporary_path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
  if (dest < 0)
    goto done;
  created = 1;
  unsigned char buffer[8192];
  for (off_t off = 0; off < input.st_size;) {
    size_t n =
        input.st_size - off > 8192 ? 8192 : (size_t)(input.st_size - off);
    if (read(source, buffer, n) != (ssize_t)n)
      goto done;
    for (size_t written = 0; written < n;) {
      ssize_t w = write(dest, buffer + written, n - written);
      if (w < 0 && errno == EINTR)
        continue;
      if (w <= 0)
        goto done;
      written += (size_t)w;
    }
    off += (off_t)n;
  }
  if (fchown(dest, before.st_uid, before.st_gid) ||
      fchmod(dest, before.st_mode & 0777) || fsync(dest))
    goto done;
  if (close(dest)) {
    dest = -1;
    goto done;
  }
  dest = -1;
  if (same_file(temporary_path, replacement) ||
      same_file(record_path, expected) || lstat(record_path, &current) ||
      current.st_dev != before.st_dev || current.st_ino != before.st_ino ||
      current.st_mode != before.st_mode || current.st_uid != before.st_uid ||
      current.st_gid != before.st_gid)
    goto done;
  if (rename(temporary_path, record_path))
    goto done;
  created = 0;
  result = same_file(record_path, replacement);
done:
  if (source >= 0)
    close(source);
  if (dest >= 0)
    close(dest);
  if (created)
    unlink(temporary_path);
  return result;
}
