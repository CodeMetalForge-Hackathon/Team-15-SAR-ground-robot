#pragma once
#include <stdbool.h>
#include <stdint.h>
void uart2Init(const uint32_t baudrate);
bool uart2GetCharWithTimeout(uint8_t *c, const uint32_t timeoutTicks);
