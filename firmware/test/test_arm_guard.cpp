#include <unity.h>
#include "arm_guard.h"

static const char* FIRST  = "0123456789abcdef0123456789abcdef";
static const char* SECOND = "fedcba9876543210fedcba9876543210";

void setUp(void) {}
void tearDown(void) {}

void test_empty_token_rejected(void) {
  ArmGuard guard;
  TEST_ASSERT_FALSE(guard.allows(""));
}

void test_short_token_rejected(void) {
  ArmGuard guard;
  TEST_ASSERT_FALSE(guard.allows("invalid"));
}

void test_fresh_token_allowed(void) {
  ArmGuard guard;
  TEST_ASSERT_TRUE(guard.allows(FIRST));
}

void test_inhibited_token_blocked(void) {
  ArmGuard guard;
  guard.inhibit(FIRST);
  for (int i = 0; i < 100; i++) {
    TEST_ASSERT_FALSE(guard.allows(FIRST));
  }
}

void test_new_token_allowed_after_inhibit(void) {
  ArmGuard guard;
  guard.inhibit(FIRST);
  TEST_ASSERT_TRUE(guard.allows(SECOND));
}

void test_second_token_inhibitable(void) {
  ArmGuard guard;
  guard.inhibit(FIRST);
  guard.inhibit(SECOND);
  TEST_ASSERT_FALSE(guard.allows(SECOND));
}

int main(int argc, char **argv) {
  UNITY_BEGIN();
  RUN_TEST(test_empty_token_rejected);
  RUN_TEST(test_short_token_rejected);
  RUN_TEST(test_fresh_token_allowed);
  RUN_TEST(test_inhibited_token_blocked);
  RUN_TEST(test_new_token_allowed_after_inhibit);
  RUN_TEST(test_second_token_inhibitable);
  return UNITY_END();
}
