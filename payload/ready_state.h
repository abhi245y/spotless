#ifndef SPOTLESS_READY_STATE_H
#define SPOTLESS_READY_STATE_H
#include <stdint.h>
/* Require the same backend and cache snapshot across a five-second settle
 * window. */
typedef struct {
  int pid;
  uint64_t stamp;
  unsigned stable;
  int ready;
} sp_ready_state;
static int sp_ready_step(sp_ready_state *s, int pid, uint64_t stamp,
                         int assets) {
  if (pid <= 0 || !assets) {
    s->pid = 0;
    s->stable = 0;
    s->ready = 0;
    return 0;
  }
  if (s->pid != pid || s->stamp != stamp) {
    s->pid = pid;
    s->stamp = stamp;
    s->stable = 0;
    s->ready = 0;
    return 0;
  }
  if (s->stable < 5)
    s->stable++;
  s->ready = s->stable >= 5;
  return s->ready;
}
#endif
