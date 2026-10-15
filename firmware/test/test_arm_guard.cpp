#include <cassert>
#include "arm_guard.h"

int main() {
  ArmGuard guard;
  const char* first="0123456789abcdef0123456789abcdef";
  const char* second="fedcba9876543210fedcba9876543210";
  assert(!guard.allows(""));
  assert(!guard.allows("invalid"));
  assert(guard.allows(first));
  guard.inhibit(first); // Watchdog or connection failure.
  for(int i=0;i<100;i++)assert(!guard.allows(first));
  assert(guard.allows(second)); // A fresh operator arm action.
  guard.inhibit(second);
  assert(!guard.allows(second));
}
