/* Host-test stand-ins for the Crazyflie firmware headers t15_scanner.c uses. */
#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef uint32_t TickType_t;
#define pdTRUE 1
#define M2T(X) ((unsigned int)(X))
#define T2M(X) ((unsigned int)(X))
TickType_t xTaskGetTickCount(void);
