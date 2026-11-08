# Team-15 scanner app for the Crazyflie 2.1+.
# Build:  make CRAZYFLIE_BASE=/path/to/crazyflie-firmware
# Flash:  python3 -m cfloader flash build/cf2.bin stm32-fw -w radio://0/80/2M/E7E7E7E7E7
#         (cfloader comes with: python3 -m pip install cfclient). See sar_sim/README.md.
CRAZYFLIE_BASE ?= ../../../crazyflie-firmware
OOT_CONFIG := $(PWD)/app-config
include $(CRAZYFLIE_BASE)/tools/make/oot.mk
