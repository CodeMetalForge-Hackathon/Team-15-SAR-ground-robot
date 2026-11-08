"""Bluetooth (BLE) link for cflib: fly a Crazyflie from a laptop without a Crazyradio.

    import cflib.crtp
    cflib.crtp.init_drivers()
    from sar_sim import ble_link; ble_link.register()
    uri = "ble://Crazyflie"      # first drone whose Bluetooth name starts with "Crazyflie"
    uri = "ble://<address>"      # one specific drone (on a Mac this is a long UUID)
    python3 -m sar_sim.ble_link  # list the drones in Bluetooth range

It speaks the Crazyflie's Bluetooth CRTP bridge (crazyflie2-nrf-firmware,
docs/protocols/ble.md):
  service   00000201-1C7F-4F9E-947B-43B7C00A9A08
  crtp      ...0202  write a whole CRTP packet of up to 20 bytes
  crtpUp    ...0203  write a longer packet in two pieces
  crtpDown  ...0204  notifications from the drone, in one or two pieces
Like the Crazyradio, the drone answers one packet for every packet it gets,
so this link sends tiny "null" packets when idle to collect the answers.

On connect the link checks which radio firmware the drone has, with echo packets:
  * up to 2023.11, and 2024.10 or newer: everything works. Long packets
    (over 20 bytes, e.g. the high-level go_to) use whichever length rule
    the echo test shows.
  * 2024.2: this release has a Bluetooth bug. Its long answers (20 bytes or
    more) lose byte 20, so they can't be repaired. The link drops them
    instead of handing cflib damaged data; only the connect handshake is
    rebuilt (it is known text padded with zeros). Short answers are fine. So:
    connect once over USB first, so cflib caches the drone's variable lists,
    and keep log blocks to 14 bytes of data or less. Updating the drone's
    firmware fixes this for good.

Limits: slower than the Crazyradio (roughly 30-60 packets a second each way
on a Mac). The first connection reads the drone's variable lists and can
take about 30 s; later ones use the cache. Only one Bluetooth connection at
a time, so close the phone app first. If the drone hears a Crazyradio, its
firmware turns Bluetooth off until restarted. Needs: pip install bleak
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from collections import deque

log = logging.getLogger(__name__)

SERVICE = "00000201-1c7f-4f9e-947b-43b7c00a9a08"
CRTP = "00000202-1c7f-4f9e-947b-43b7c00a9a08"
CRTP_UP = "00000203-1c7f-4f9e-947b-43b7c00a9a08"
CRTP_DOWN = "00000204-1c7f-4f9e-947b-43b7c00a9a08"
NULL = b"\xff"                      # CRTP port 15, channel 3: ignored by the drone
ECHO_HEADER = 0xFC                  # CRTP port 15, channel 0 (link echo), legacy bits set
NAME_PREFIX = "Crazyflie"
SCAN_S = 4.0
POLL_S = 0.004                      # pause after an idle poll
COALESCE = {(3, 0)}                 # thrust setpoints: only the newest one matters...


def _thrust(raw):
    """Thrust of a legacy roll/pitch/yaw/thrust setpoint (struct '<fffH' after the header)."""
    return int.from_bytes(raw[13:15], "little") if len(raw) >= 15 else None
MAX_QUEUE = 500


def uplink_writes(pk: bytes, pid: int, mode: str | None):
    """(characteristic, bytes) writes that carry one CRTP packet to the drone."""
    if len(pk) <= 20:
        return [(CRTP, pk)]
    if mode not in ("full", "minus1") or len(pk) > 31:
        raise ValueError(f"cannot send a {len(pk)}-byte packet over this Bluetooth link")
    n = len(pk) if mode == "full" else len(pk) - 1
    first = bytes([0x80 | ((pid & 3) << 5) | (n & 0x1F)]) + pk[:19]
    second = bytes([(pid & 3) << 5]) + pk[19:]
    return [(CRTP_UP, first), (CRTP_UP, second)]


LEN1, FW2024_2 = "len1", "2024.2"


class Reassembler:
    """Joins the drone's one- or two-piece crtpDown notifications into CRTP packets.

    dialect LEN1: control byte = start | pid | (length - 1), as documented.
    dialect FW2024_2: control byte = start | length, both pieces carry it,
    and the second piece starts one byte late (the firmware skips byte 20)."""

    def __init__(self, dialect=LEN1):
        self.dialect = dialect
        self.first = None
        self.pid = None
        self.length = 0
        self.expect = None
        self.damaged = 0
        self.last_damaged = None            # header byte of the last packet that was dropped

    def feed(self, frag: bytes):
        if not frag:
            return None
        if self.dialect == FW2024_2:
            return self._feed_2024_2(bytes(frag))
        ctrl = frag[0]
        pid = (ctrl >> 5) & 3
        if ctrl & 0x80:
            length = (ctrl & 0x1F) + 1
            body = bytes(frag[1:])
            if length <= 19:
                self.first = None
                return body[:length]
            self.first, self.pid, self.length = body, pid, length
            return None
        if self.first is not None and pid == self.pid:
            pk = (self.first + bytes(frag[1:]))[:self.length]
            self.first = None
            return pk
        self.first = None                   # lost a piece: drop it, like the firmware does
        return None

    def _feed_2024_2(self, frag):
        ctrl = frag[0]
        if not ctrl & 0x80:
            return None
        length = ctrl & 0x1F
        if self.expect is not None and ctrl == self.expect:
            first, self.first, self.expect = self.first, None, None
            if first and (first[0] & 0xF3) == 0xF1:  # link "source": "Bitcraze Crazyflie" + zeros
                return first + bytes(max(0, length - len(first)))
            self.damaged += 1
            self.last_damaged = first[0] if first else None
            return None
        if length <= 19:
            return frag[1:1 + length]
        self.first, self.expect = frag[1:20], ctrl
        return None


async def _scan(timeout=SCAN_S):
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    out = []
    for address, (dev, adv) in found.items():
        name = getattr(adv, "local_name", None) or getattr(dev, "name", None) or ""
        if name.startswith(NAME_PREFIX):
            out.append((address, name, getattr(adv, "rssi", None)))
    return sorted(out, key=lambda r: -(r[2] or -999))


async def _find(target, tries=3):
    """A full scan, then pick by address or name (the same steps that work on macOS)."""
    from bleak import BleakScanner
    by_name = not target or target.startswith(NAME_PREFIX)
    for _ in range(tries):
        found = await BleakScanner.discover(timeout=SCAN_S, return_adv=True)
        for address, (dev, adv) in found.items():
            name = getattr(adv, "local_name", None) or getattr(dev, "name", None) or ""
            if by_name and name.startswith(target or NAME_PREFIX):
                return dev
            if not by_name and address.lower() == target.lower():
                return dev
    return None


def _wrong_uri(msg):
    try:
        from cflib.crtp.exceptions import WrongUriType
    except ImportError:                     # used without cflib (tests)
        return ValueError(msg)
    return WrongUriType(msg)


class BleDriver:
    """A cflib link driver (same methods as cflib's UsbDriver) for ble:// URIs."""

    def __init__(self):
        self.uri = None
        self.needs_resending = False        # Bluetooth writes are acknowledged, like USB
        self.in_queue = queue.Queue()
        self.out = deque()
        self.lock = threading.Lock()
        self.loop = self.thread = self.client = self.writer = None
        self.closing = False
        self.pid = 0
        self.long_mode = None
        self.rx = Reassembler()
        self.echo_waiter = None
        self.probe = None
        self.lossy = False
        self.link_error_callback = None
        self.packet_factory = None          # tests can replace cflib's CRTPPacket
        self.sent = 0
        self.received = 0

    # ---- cflib driver interface ----------------------------------------------
    def get_name(self):
        return "ble"

    def get_status(self):
        return "Bluetooth link (bleak)"

    def get_help(self):
        return "ble://Crazyflie or ble://<address>"

    def scan_interface(self, address=None):
        try:
            found = asyncio.run(_scan())
        except Exception as exc:            # no Bluetooth, no permission, no bleak
            log.warning("Bluetooth scan failed: %s", exc)
            return []
        return [[f"ble://{addr}", name] for addr, name, _ in found]

    def connect(self, uri, radio_link_statistics_callback, link_error_callback):
        if not uri.startswith("ble://"):
            raise _wrong_uri("Not a Bluetooth URI")
        self.uri, self.link_error_callback = uri, link_error_callback
        self.loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self.loop)        # like asyncio.run() does, for bleak on macOS
            self.loop.run_forever()

        self.thread = threading.Thread(target=run, name="t15-ble", daemon=True)
        self.thread.start()
        fut = asyncio.run_coroutine_threadsafe(self._connect(uri[len("ble://"):]), self.loop)
        try:
            fut.result(timeout=60)
        except Exception:
            self.close()
            raise

    def send_packet(self, pk):
        raw = bytes([pk.header]) + bytes(pk.data)
        if len(raw) > 20 and self.long_mode is None:
            self._error(f"Bluetooth link cannot send this {len(raw)}-byte packet (port {pk.port})")
            return
        self._push(raw, (pk.port, pk.channel) if (pk.port, pk.channel) in COALESCE else None)

    def receive_packet(self, time=0):
        try:
            if time == 0:
                return self.in_queue.get(False)
            if time < 0:
                return self.in_queue.get(True)
            return self.in_queue.get(True, time)
        except queue.Empty:
            return None

    def close(self):
        self.closing = True
        if self.loop is not None and self.loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._disconnect(), self.loop).result(timeout=6)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=3)
            if not self.thread.is_alive() and self.loop is not None:
                self.loop.close()
        self.client = None

    # ---- internals ------------------------------------------------------------
    def _push(self, raw, key):
        with self.lock:
            if key is not None:
                for i, (k, old) in enumerate(self.out):
                    # ...except that a zero-thrust setpoint is never dropped for a non-zero one,
                    # or the other way round: the drone needs a zero first to unlock its thrust.
                    if k == key and (_thrust(old) == 0) == (_thrust(raw) == 0):
                        self.out[i] = (key, raw)       # replace the older setpoint
                        return
            if len(self.out) >= MAX_QUEUE:
                self.out.popleft()
                log.warning("Bluetooth send queue full; dropped the oldest packet")
            self.out.append((key, raw))

    def _pop(self):
        with self.lock:
            return self.out.popleft()[1] if self.out else None

    def _error(self, msg):
        log.error(msg)
        if self.link_error_callback and not self.closing:
            self.link_error_callback(msg)

    def _on_disconnect(self, _client):
        if not self.closing:
            self._error("Bluetooth link lost")

    def _on_notify(self, _char, data):
        data = bytes(data)
        if self.probe is not None and len(data) > 1 and data[0] & 0x80 and data[1] == ECHO_HEADER:
            if not self.probe.done():
                self.probe.set_result(data)          # the raw first piece of our probe echo
            return
        before = self.rx.damaged
        pk = self.rx.feed(data)
        if pk:
            self._deliver(pk)
        elif self.rx.damaged != before:
            port, channel = (self.rx.last_damaged or 0) >> 4, (self.rx.last_damaged or 0) & 3
            if port in (2, 5) and channel == 0:
                self._error("This drone's radio firmware (2024.2) damages long Bluetooth answers, and "
                            "cflib needed one (the drone's variable list). Connect once over USB first "
                            "so the list is cached, then try Bluetooth again. A firmware update fixes it.")
            elif port == 4:
                self._error("This drone's radio firmware (2024.2) damages long Bluetooth answers, and "
                            "cflib needed one (a deck's memory). Update the drone's firmware, or use "
                            "USB or a Crazyradio.")

    def _deliver(self, raw):
        header, data = raw[0], raw[1:]
        port, channel = (header & 0xF0) >> 4, header & 0x03
        if port == 15 and channel == 0 and self.echo_waiter is not None:
            if not self.echo_waiter.done():
                self.echo_waiter.set_result(bytes(data))
            return
        if port == 15 and channel == 3:
            return                                   # null packet
        self.received += 1
        if self.packet_factory:
            self.in_queue.put(self.packet_factory(header, data))
        else:
            from cflib.crtp.crtpstack import CRTPPacket
            self.in_queue.put(CRTPPacket(header, list(data)))

    async def _connect(self, target):
        from bleak import BleakClient
        device = await _find(target)
        if device is None:
            raise ConnectionError(f"No Crazyflie found over Bluetooth for {target or NAME_PREFIX!r}. "
                                  "Is it on, in range, and disconnected from the phone app?")
        self.client = BleakClient(device, disconnected_callback=self._on_disconnect, timeout=20)
        await self.client.connect()
        await self.client.start_notify(CRTP_DOWN, self._on_notify)
        self.writer = asyncio.ensure_future(self._writer())
        await self._detect_firmware()
        while not self.in_queue.empty():             # startup log printed before we were ready
            self.in_queue.get_nowait()
        log.info("Bluetooth link up to %s (radio firmware %s, long packets %s)",
                 target, self.rx.dialect, self.long_mode)

    async def _detect_firmware(self):
        """Short echo: is the length byte 'length - 1' (most firmware) or 'length' (2024.2)?"""
        probe = bytes([ECHO_HEADER]) + b"t15ok"     # 6 bytes
        for _ in range(2):
            self.probe = asyncio.get_running_loop().create_future()
            self._push(probe, None)
            try:
                frag = await asyncio.wait_for(self.probe, 3.0)
            except asyncio.TimeoutError:
                continue
            finally:
                self.probe = None
            if frag[0] & 0x1F == len(probe):
                self.rx.dialect, self.long_mode, self.lossy = FW2024_2, "full", True
                log.warning("Drone radio firmware 2024.2: long Bluetooth answers are damaged by the "
                            "firmware and will be dropped. Short ones work. A firmware update fixes it.")
                return
            break
        self.long_mode = await self._detect_long_mode()

    async def _write_raw(self, raw):
        writes = uplink_writes(raw, self.pid, self.long_mode)
        if len(writes) > 1:
            self.pid = (self.pid + 1) & 3
        for char, data in writes:
            await self.client.write_gatt_char(char, data, response=True)
        self.sent += 1

    async def _writer(self):
        while not self.closing:
            raw = self._pop()
            try:
                await self._write_raw(raw if raw is not None else NULL)
            except Exception as exc:
                if not self.closing:
                    self._error(f"Bluetooth write failed: {exc}")
                return
            if raw is None:
                await asyncio.sleep(POLL_S)

    async def _detect_long_mode(self):
        payload = bytes(range(1, 24))                # 24-byte echo packet: needs two pieces
        for mode in ("full", "minus1"):
            self.long_mode = mode
            self.echo_waiter = asyncio.get_running_loop().create_future()
            self._push(bytes([ECHO_HEADER]) + payload, None)
            try:
                if await asyncio.wait_for(self.echo_waiter, 2.0) == payload:
                    return mode
            except asyncio.TimeoutError:
                pass
            finally:
                self.echo_waiter = None
        log.warning("This drone's Bluetooth did not echo a long packet; packets over 20 bytes "
                    "(e.g. high-level go_to) are turned off on this link")
        return None

    async def _disconnect(self):
        if self.writer is not None:
            self.writer.cancel()
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass


def register():
    """Let cflib open ble:// URIs. Call after cflib.crtp.init_drivers()."""
    import cflib.crtp as crtp
    if BleDriver not in crtp.CLASSES:
        crtp.CLASSES.append(BleDriver)


def main():
    found = asyncio.run(_scan(6.0))
    if not found:
        print("No Crazyflie found over Bluetooth. Is it on, and disconnected from the phone app?")
        return
    for address, name, rssi in found:
        print(f"ble://{address}   {name}   signal {rssi} dBm")


if __name__ == "__main__":
    main()
