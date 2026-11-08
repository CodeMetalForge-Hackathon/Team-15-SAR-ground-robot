"""Test stand-in for bleak: a simulated Bluetooth Crazyflie, no radio.

FakeDrone follows the drone radio firmware (crazyflie2-nrf-firmware):
  mode "old"    = up to 2023.11 (uplink length byte = length - 1)
  mode "2024.2" = release 2024.2: uplink length byte = length; its answers use
                  0x80|length in both pieces and skip byte 20 (the bug it shipped with)
  mode "new"    = 2024.10 and later (uplink length byte = length, answers fixed)
It answers one packet per packet received, echoes link-echo packets, and
splits its answers into crtpDown pieces like ble_crazyflies.c.
"""
import asyncio
from collections import deque

CRTP = "00000202-1c7f-4f9e-947b-43b7c00a9a08"
CRTP_UP = "00000203-1c7f-4f9e-947b-43b7c00a9a08"
DRONES = []


class FakeDrone:
    def __init__(self, mode="old", name="Crazyflie", address="F0-0D-00-00-00-01"):
        self.mode, self.name, self.address = mode, name, address
        self.downlink = deque()          # CRTP packets the drone wants to send
        self.received = []               # CRTP packets it got (not null, not echo)
        self.notify = None
        self.client = None
        self.pid = 0
        self.up_buf, self.up_len, self.up_pid = None, 0, None
        self.writes = 0

    def fragments(self, pk):
        if self.mode == "2024.2":                      # ble_crazyflies.c in release 2024.2
            ctrl = 0x80 | len(pk)
            if len(pk) > 19:
                return [bytes([ctrl]) + pk[:19], bytes([ctrl]) + (pk + b"\x7a")[20:len(pk) + 1]]
            return [bytes([ctrl]) + pk]
        ctrl = 0x80 | ((self.pid << 5) & 0x60) | ((len(pk) - 1) & 0x1F)
        out = [bytes([ctrl]) + pk[:19]]
        if len(pk) > 19:
            out.append(bytes([(self.pid << 5) & 0x60]) + pk[19:])
        self.pid = (self.pid + 1) & 3
        return out

    def _got(self, pk):
        port, ch = pk[0] >> 4, pk[0] & 3
        if port == 15 and ch == 0:
            self.downlink.appendleft(pk)              # link echo
        elif port == 15 and ch == 1:                  # link source: the connect handshake
            self.downlink.appendleft(bytes([0xF1]) + b"Bitcraze Crazyflie" + bytes(12))
        elif not (port == 15 and ch == 3):
            self.received.append(pk)
        if self.downlink and self.notify:             # one answer per packet received
            for frag in self.fragments(self.downlink.popleft()):
                self.notify(None, bytearray(frag))

    def write(self, char, data):
        self.writes += 1
        data = bytes(data)
        if char == CRTP:
            return self._got(data)
        if char != CRTP_UP or not data:
            return
        c = data[0]
        if self.mode == "old":
            if c & 0x80:
                self.up_pid, self.up_len = c & 0x60, (c & 0x1F) + 1
                if self.up_len > 19:
                    self.up_buf = bytearray(data[1:20])
                else:
                    self._got(data[1:1 + self.up_len])
            elif (c & 0x60) == self.up_pid and self.up_buf is not None:
                pk = (self.up_buf + data[1:] + bytes(32))[:self.up_len]
                self.up_buf = None
                self._got(bytes(pk))
        else:
            if c & 0x80:
                self.up_len, self.up_buf = c & 0x1F, bytearray(data[1:])
            elif self.up_buf is not None:
                pk = (self.up_buf + data[1:] + bytes(32))[:self.up_len]
                self.up_buf = None
                self._got(bytes(pk))


class BLEDevice:
    def __init__(self, address, name):
        self.address, self.name = address, name


class AdvertisementData:
    def __init__(self, local_name, rssi=-50):
        self.local_name, self.rssi = local_name, rssi


def _entries():
    return [(BLEDevice(d.address, d.name), AdvertisementData(d.name)) for d in DRONES]


class BleakScanner:
    @staticmethod
    async def discover(timeout=5.0, return_adv=False, **_):
        await asyncio.sleep(0)
        return {dev.address: (dev, adv) for dev, adv in _entries()}

    @staticmethod
    async def find_device_by_filter(filterfunc, timeout=10.0, **_):
        await asyncio.sleep(0)
        return next((dev for dev, adv in _entries() if filterfunc(dev, adv)), None)

    @staticmethod
    async def find_device_by_address(address, timeout=10.0, **_):
        await asyncio.sleep(0)
        return next((dev for dev, _ in _entries() if dev.address == address), None)


class BleakClient:
    def __init__(self, device, disconnected_callback=None, timeout=20, **_):
        self.drone = next(d for d in DRONES if d.address == device.address)
        self.disconnected_callback = disconnected_callback
        self.is_connected = False

    async def connect(self):
        self.is_connected = True
        self.drone.client = self

    async def start_notify(self, char, callback, **_):
        self.drone.notify = callback

    async def write_gatt_char(self, char, data, response=None):
        await asyncio.sleep(0.002)                     # a short Bluetooth connection interval
        if not self.is_connected:
            raise ConnectionError("not connected")
        self.drone.write(char, data)

    async def disconnect(self):
        self.is_connected = False

    def drop(self):
        """Test helper: the drone goes out of range."""
        self.is_connected = False
        if self.disconnected_callback:
            self.disconnected_callback(self)
