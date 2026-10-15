#pragma once
#include <cstring>

// Call under the control-state mutex. A watchdog stop invalidates the current
// operator arm token; refreshing velocity commands cannot authorize a restart.
class ArmGuard {
  char blocked_[33] = "";
public:
  void inhibit(const char* token) {
    std::strncpy(blocked_, token, sizeof(blocked_)-1);
    blocked_[sizeof(blocked_)-1]='\0';
  }
  bool allows(const char* token) const {
    return token && std::strlen(token)==32 && std::strcmp(token,blocked_)!=0;
  }
};
