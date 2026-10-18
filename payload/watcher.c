/* Spotless: self-contained, one-time UI patch. No credentials or native login
 * hook. */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#ifndef SPOTLESS_HOST_TEST
#include <sys/param.h>
#include <sys/proc.h>
#include <sys/sysctl.h>
#include <sys/user.h>
int sceKernelSetProcessName(const char *);
typedef struct {
  char reserved[45];
  char message[3075];
} sp_notification;
int sceKernelSendNotificationRequest(int, sp_notification *, size_t, int);
#endif
#ifndef HOME
#define HOME "/data/spotless"
#endif
#ifndef CACHE
#define CACHE                                                                  \
  "/mnt/sandbox/PPSA05688_000/download0/webkit/diskcache/Version 16/"
#endif
static char record_path[1024], temporary_path[1060];
#include "atomic_cache.h"
#include "cache_format.h"
#include "ready_state.h"
#include "ui_patch.h"

static int read_regular(const char *path, unsigned char **out, size_t *size,
                        size_t limit) {
  int fd = open(path, O_RDONLY | O_NOFOLLOW);
  struct stat st;
  if (fd < 0)
    return 1;
  int rc = 1;
  unsigned char *p = NULL;
  if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size < 1 ||
      (uint64_t)st.st_size > limit)
    goto done;
  p = malloc((size_t)st.st_size);
  if (!p)
    goto done;
  for (size_t off = 0; off < (size_t)st.st_size;) {
    ssize_t n = read(fd, p + off, (size_t)st.st_size - off);
    if (n < 0 && errno == EINTR)
      continue;
    if (n <= 0)
      goto done;
    off += (size_t)n;
  }
  struct stat after;
  if (fstat(fd, &after) || after.st_size != st.st_size ||
      after.st_mtime != st.st_mtime)
    goto done;
  *out = p;
  *size = (size_t)st.st_size;
  p = NULL;
  rc = 0;
done:
  free(p);
  close(fd);
  return rc;
}
static int save_exclusive(const char *path, const unsigned char *data,
                          size_t size) {
  int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
  if (fd < 0) {
    if (errno != EEXIST)
      return 1;
    unsigned char *old = NULL;
    size_t bytes = 0;
    int rc = read_regular(path, &old, &bytes, SP_MAX_RECORD) || bytes != size ||
             (old && memcmp(old, data, size));
    free(old);
    return rc;
  }
  int rc = 1;
  for (size_t off = 0; off < size;) {
    ssize_t n = write(fd, data + off, size - off);
    if (n < 0 && errno == EINTR)
      continue;
    if (n <= 0)
      goto done;
    off += (size_t)n;
  }
  if (fsync(fd))
    goto done;
  rc = 0;
done:
  if (close(fd))
    rc = 1;
  /* Preserve an interrupted backup for inspection; never silently adopt it. */
  return rc;
}
static int read_salt(unsigned char salt[8]) {
  struct stat st;
  if (lstat(CACHE "salt", &st) || !S_ISREG(st.st_mode) || st.st_size != 8)
    return 1;
#ifdef SPOTLESS_HOST_TEST
  unsigned char *p = NULL;
  size_t size = 0;
  if (read_regular(CACHE "salt", &p, &size, 8))
    return 1;
  memcpy(salt, p, 8);
  free(p);
  return 0;
#else
  int pipefd[2];
  if (pipe(pipefd))
    return 1;
  pid_t child = fork();
  if (child < 0) {
    close(pipefd[0]);
    close(pipefd[1]);
    return 1;
  }
  if (!child) {
    close(pipefd[0]);
    unsigned char *p = NULL;
    size_t size = 0;
    int rc = setegid(st.st_gid) || seteuid(st.st_uid) ||
             read_regular(CACHE "salt", &p, &size, 8);
    if (!rc)
      rc = write(pipefd[1], p, 8) != 8;
    free(p);
    close(pipefd[1]);
    _exit(rc ? 1 : 0);
  }
  close(pipefd[1]);
  fd_set fds;
  FD_ZERO(&fds);
  FD_SET(pipefd[0], &fds);
  struct timeval timeout = {3, 0};
  int rc = 1, status = 0;
  if (select(pipefd[0] + 1, &fds, NULL, NULL, &timeout) > 0) {
    unsigned char b[9];
    ssize_t n = read(pipefd[0], b, sizeof(b));
    if (n == 8) {
      memcpy(salt, b, 8);
      rc = 0;
    }
  } else
    kill(child, SIGKILL);
  close(pipefd[0]);
  if (waitpid(child, &status, 0) != child || !WIFEXITED(status) ||
      WEXITSTATUS(status))
    rc = 1;
  return rc;
#endif
}
typedef struct {
  int js, vendor, css, matches;
  uint64_t stamp;
  char path[1024];
} sp_scan;
static int hex_name(const char *s) {
  if (strlen(s) != 40)
    return 0;
  for (unsigned i = 0; i < 40; i++)
    if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'A' && s[i] <= 'F')))
      return 0;
  return 1;
}
static int scan_cache(const unsigned char salt[8], sp_scan *out) {
  memset(out, 0, sizeof(*out));
  DIR *partitions = opendir(CACHE "Records");
  if (!partitions)
    return 1;
  struct dirent *partition;
  unsigned pcount = 0, total = 0;
  int rc = 0;
  while ((partition = readdir(partitions))) {
    if (!hex_name(partition->d_name))
      continue;
    if (++pcount > 128) {
      rc = 1;
      break;
    }
    char directory[1024];
    snprintf(directory, sizeof(directory), CACHE "Records/%s/Resource",
             partition->d_name);
    struct stat st;
    if (lstat(directory, &st) || !S_ISDIR(st.st_mode))
      continue;
    DIR *resources = opendir(directory);
    if (!resources)
      continue;
    struct dirent *entry;
    while ((entry = readdir(resources))) {
      if (!hex_name(entry->d_name))
        continue;
      if (++total > 4096) {
        rc = 1;
        break;
      }
      char path[1024];
      int len = snprintf(path, sizeof(path), "%s/%s", directory, entry->d_name);
      if (len < 0 || (size_t)len >= sizeof(path))
        continue;
      int fd = open(path, O_RDONLY | O_NOFOLLOW);
      if (fd < 0)
        continue;
      unsigned char prefix[4096];
      ssize_t n = read(fd, prefix, sizeof(prefix));
      close(fd);
      sp_record m;
      if (n < 1 || sp_decode(prefix, (size_t)n, &m, 1))
        continue;
      int kind = !strcmp(m.identifier, SP_IDENTIFIER) ? 1
                 : !strcmp(m.identifier, SP_VENDOR)   ? 2
                 : !strcmp(m.identifier, SP_CSS)      ? 3
                                                      : 0;
      if (!kind)
        continue;
      unsigned char *data = NULL;
      size_t bytes = 0;
      if (read_regular(path, &data, &bytes, SP_MAX_RECORD))
        continue;
      if (sp_validate(data, bytes, salt, &m)) {
        free(data);
        continue;
      }
      if (kind == 1) {
        out->matches++;
        if (sp_sha256_matches(data + m.body, (size_t)m.body_bytes,
                              SP_SOURCE_SHA))
          out->js = 1;
        else if (sp_sha256_matches(data + m.body, (size_t)m.body_bytes,
                                   SP_PATCH_SHA))
          out->js = 2;
        else
          out->js = -1;
        snprintf(out->path, sizeof(out->path), "%s", path);
        if (!lstat(path, &st))
          out->stamp = (uint64_t)st.st_ino ^ (uint64_t)st.st_mtime << 32 ^
                       (uint64_t)st.st_size;
      } else if (kind == 2 && m.body_bytes)
        out->vendor = 1;
      else if (kind == 3 && m.body_bytes)
        out->css = 1;
      free(data);
    }
    closedir(resources);
    if (rc)
      break;
  }
  closedir(partitions);
  return rc;
}
/* Rebuild the patched record from this console's own cached frontend. The
 * payload carries only the edits, never Spotify's code. */
static unsigned char *patch_record(const unsigned char *original, size_t size,
                                   const unsigned char salt[8],
                                   size_t *out_size) {
  sp_record m;
  if (sp_validate(original, size, salt, &m) ||
      !sp_sha256_matches(original + m.body, (size_t)m.body_bytes,
                         SP_SOURCE_SHA))
    return NULL;
  const unsigned char *src = original + m.body;
  size_t src_size = (size_t)m.body_bytes, cursor = 0, used = 0;
  unsigned char *js = malloc(SP_PATCHED_SIZE);
  if (!js)
    return NULL;
  for (size_t i = 0; i < sizeof(sp_edits) / sizeof(sp_edits[0]); i++) {
    size_t keep = sp_edits[i].offset - cursor,
           add = sp_edits[i].insert_length;
    if (sp_edits[i].offset < cursor ||
        sp_edits[i].length > src_size - sp_edits[i].offset ||
        keep + add > SP_PATCHED_SIZE - used)
      goto fail;
    memcpy(js + used, src + cursor, keep);
    memcpy(js + used + keep, sp_edits[i].insert, add);
    used += keep + add;
    cursor = sp_edits[i].offset + sp_edits[i].length;
  }
  if (src_size - cursor != SP_PATCHED_SIZE - used)
    goto fail;
  memcpy(js + used, src + cursor, src_size - cursor);
  /* sp_rebuild checks the result against SP_PATCH_SHA. */
  unsigned char *record =
      sp_rebuild(original, size, salt, js, SP_PATCHED_SIZE, out_size);
  free(js);
  return record;
fail:
  free(js);
  return NULL;
}
static int apply_ui(const sp_scan *scan, const unsigned char salt[8]) {
  unsigned char *original = NULL;
  size_t bytes = 0, new_size = 0;
  if (read_regular(scan->path, &original, &bytes, SP_MAX_RECORD))
    return 1;
  unsigned char *patched = patch_record(original, bytes, salt, &new_size);
  if (!patched) {
    free(original);
    return 1;
  }
  snprintf(record_path, sizeof(record_path), "%s", scan->path);
  int rc =
      save_exclusive(HOME "/original.record", original, bytes) ||
      save_exclusive(HOME "/patched.record", patched, new_size) ||
      save_exclusive(HOME "/record-path", (const unsigned char *)record_path,
                     strlen(record_path));
  if (!rc)
    rc = replace_cache(0);
  free(original);
  free(patched);
  return rc;
}
#ifdef SPOTLESS_RESTORE
static int restore_ui(void) {
  unsigned char *path = NULL, *original = NULL, *patched = NULL,
                *expected = NULL;
  size_t path_size = 0, original_size = 0, patched_size = 0, expected_size = 0;
  int rc = 1;
  unsigned char salt[8];
  sp_record m;
  if (read_regular(HOME "/record-path", &path, &path_size,
                   sizeof(record_path) - 1))
    goto done;
  if (memchr(path, 0, path_size))
    goto done;
  memcpy(record_path, path, path_size);
  record_path[path_size] = 0;
  const char *prefix = CACHE "Records/";
  size_t length = strlen(prefix);
  if (strncmp(record_path, prefix, length) ||
      strlen(record_path) != length + 40 + 10 + 40)
    goto done;
  char first[41];
  memcpy(first, record_path + length, 40);
  first[40] = 0;
  if (!hex_name(first) ||
      strncmp(record_path + length + 40, "/Resource/", 10) ||
      !hex_name(record_path + length + 50))
    goto done;
  if (read_salt(salt) ||
      read_regular(HOME "/original.record", &original, &original_size,
                   SP_MAX_RECORD) ||
      read_regular(HOME "/patched.record", &patched, &patched_size,
                   SP_MAX_RECORD))
    goto done;
  if (sp_validate(patched, patched_size, salt, &m) ||
      !sp_sha256_matches(patched + m.body, (size_t)m.body_bytes, SP_PATCH_SHA))
    goto done;
  expected = patch_record(original, original_size, salt, &expected_size);
  if (!expected || expected_size != patched_size ||
      memcmp(expected, patched, patched_size))
    goto done;
  rc = replace_cache(1);
done:
  free(path);
  free(original);
  free(patched);
  free(expected);
  return rc;
}
#endif
#ifndef SPOTLESS_HOST_TEST
static FILE *sp_log;
static void notice(const char *message) {
  if (sp_log) {
    fprintf(sp_log, "Spotless: %s\n", message);
    fflush(sp_log);
  }
  sp_notification n;
  memset(&n, 0, sizeof(n));
  snprintf(n.message, sizeof(n.message), "Spotless: %s", message);
  int rc = sceKernelSendNotificationRequest(0, &n, sizeof(n), 0);
  if (rc && sp_log) {
    fprintf(sp_log, "notification result=%#x\n", (unsigned)rc);
    fflush(sp_log);
  }
}
static int backend_pid(void) {
  _Static_assert(offsetof(struct kinfo_proc, ki_pid) == 72, "process PID ABI");
  _Static_assert(offsetof(struct kinfo_proc, ki_comm) == 447,
                 "process name ABI");
  struct stat app;
  if (lstat("/mnt/sandbox/NPXS40201_000/app0/eboot2.bin", &app) ||
      !S_ISREG(app.st_mode))
    return 0;
  int mib[] = {CTL_KERN, KERN_PROC, KERN_PROC_PROC, 0};
  size_t size = 0;
  if (sysctl(mib, 4, NULL, &size, NULL, 0) || size > 4 * 1024 * 1024)
    return 0;
  size += 64 * sizeof(struct kinfo_proc);
  unsigned char *buffer = calloc(1, size);
  if (!buffer)
    return 0;
  if (sysctl(mib, 4, buffer, &size, NULL, 0)) {
    free(buffer);
    return 0;
  }
  int result = 0, matches = 0;
  for (size_t off = 0; off + 4 <= size;) {
    int bytes = 0;
    memcpy(&bytes, buffer + off, 4);
    if (bytes < 467 || (size_t)bytes > size - off)
      break;
    struct kinfo_proc *p = (void *)(buffer + off);
    off += (size_t)bytes;
    if (!strncmp(p->ki_comm, "CustomMusicCore", 19) && p->ki_stat != SSTOP) {
      result = p->ki_pid;
      matches++;
    }
  }
  free(buffer);
  return matches == 1 ? result : 0;
}
static int guarded_apply(const sp_scan *scan, const unsigned char salt[8]) {
  pid_t parent = getpid(), watchdog = fork();
  if (watchdog < 0)
    return 1;
  if (!watchdog) {
    sleep(25);
    notice("Cache operation timed out. Installation unconfirmed; recovery "
           "backups kept.");
    kill(parent, SIGKILL);
    _exit(1);
  }
  int rc = apply_ui(scan, salt);
  kill(watchdog, SIGKILL);
  waitpid(watchdog, NULL, 0);
  return rc;
}
int main(void) {
  int name_result = sceKernelSetProcessName("Spotless");
  if (mkdir(HOME, 0700) && errno != EEXIST)
    return 1;
  int lock = open(HOME "/watcher.lock", O_RDWR | O_CREAT | O_NOFOLLOW, 0600);
  if (lock < 0)
    return 1;
  if (flock(lock, LOCK_EX | LOCK_NB)) {
    notice("Already waiting for Spotify. No second copy started.");
    close(lock);
    return 0;
  }
  sp_log = fopen(HOME "/watcher.log", "a");
  if (sp_log) {
    fprintf(sp_log,
            "process name result=%#x; UI-only build; no account credentials\n",
            (unsigned)name_result);
    fflush(sp_log);
  }
#ifdef SPOTLESS_RESTORE
  notice("Restoring original Spotify UI. Keep Spotify open.");
  int result = restore_ui();
  notice(result ? "Restore refused or failed. Keep recovery backups and check "
                  "watcher.log."
                : "Original UI restored. Fully close and reopen Spotify.");
#else
  notice("Ready. Open Spotify and leave its login page open.");
  sp_ready_state ready = {0};
  int result = 1, saw_assets = 0;
  struct timespec started;
  if (clock_gettime(CLOCK_MONOTONIC, &started)) {
    notice("Startup timer failed. No patch applied.");
    if (sp_log)
      fclose(sp_log);
    close(lock);
    return 1;
  }
  for (unsigned second = 0; second < 600; second++) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) ||
        now.tv_sec - started.tv_sec >= 600)
      break;
    unsigned char salt[8];
    sp_scan scan;
    int valid = !read_salt(salt) && !scan_cache(salt, &scan);
    if (valid && scan.matches == 1 && scan.js == 2) {
      notice("UI patch already installed. No changes needed. Use Spotify "
             "sign-in or Connect.");
      result = 0;
      break;
    }
    if (valid && scan.matches > 1) {
      notice("Multiple Spotify bundles found. No patch applied; check "
             "compatibility.");
      break;
    }
    if (valid && scan.js < 0) {
      notice("Unsupported Spotify frontend. No patch applied.");
      break;
    }
    int assets =
        valid && scan.matches == 1 && scan.js == 1 && scan.vendor && scan.css;
    int pid = assets ? backend_pid() : 0;
    if (assets && pid && !saw_assets) {
      notice("Spotify assets and backend loaded. Waiting five seconds for "
             "startup to settle.");
      saw_assets = 1;
    }
    if (sp_ready_step(&ready, pid, assets ? scan.stamp : 0, assets)) {
      notice("Installing UI patch. Please keep Spotify open.");
      if (guarded_apply(&scan, salt)) {
        notice("Patch failed or cache changed. Recovery backups kept; see "
               "watcher.log.");
        break;
      }
      notice("UI patch installed. Fully close and reopen Spotify once. Sign in "
             "using Spotify code or Connect.");
      result = 0;
      break;
    }
    if (second == 59)
      notice("Still waiting for Spotify assets and backend. Keep login page "
             "open; check DNS/internet if loading fails.");
    sleep(1);
  }
  if (result)
    notice("Stopped without a confirmed installation. Check watcher.log, then "
           "load Spotless again when Spotify is ready.");
#endif
  if (sp_log)
    fclose(sp_log);
  close(lock);
  return result;
}
#endif
