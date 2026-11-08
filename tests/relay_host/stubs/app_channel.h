#pragma once
#include <stddef.h>
#define APPCHANNEL_MTU (30)
int appchannelSendDataPacket(void* data, size_t length);
size_t appchannelReceiveDataPacket(void* buffer, size_t max_length, int timeout_ms);
