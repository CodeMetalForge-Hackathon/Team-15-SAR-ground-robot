# Apple Watch SOS remote

The OLF SOS watch app controls the paired iPhone's existing signed beacon:

`Watch → WatchConnectivity → iPhone OLF C1 → BLE status tag → ESP32 → dashboard`

## Use

1. Install the updated OLF C1 iPhone app and its embedded **OLF SOS** watch app.
   If automatic installation is off, use the iPhone's Watch app → Available Apps
   → OLF SOS → Install. Developer builds require Developer Mode on both devices.
2. On the phone, open OLF C1 and tap **Start beacon**. Keep it foregrounded.
3. Open OLF SOS on the watch. Tap **SOS**, or **Clear SOS** when it is on.
   A haptic and **Phone received** mean the phone accepted the change.
4. **Phone broadcasting** means its CoreBluetooth advertiser is running. Confirm
   actual radio detection on the local `/trace` dashboard. Neither label claims
   the receiver has detected the tag.

The watch displays **Phone unavailable** or **Last known status** when disconnected.
It never silently queues an SOS or clear for later. Use Refresh after reconnecting.
If the phone status changes while you are operating the watch, refresh/check it
and try again. On initial app launch the phone's SOS state is unknown to the
watch until its snapshot arrives.

SOS remains saved on the phone until explicitly cleared, including across phone
app restarts. The watch cannot remotely start advertising: a background phone
may save the request but still needs **Open phone · Start beacon**. The displayed
radio origin/blue dot continues to represent the phone, not the watch.
This is a local demo with public synthetic test keys and no emergency dispatch.

## Development

Open `BeaconC1.xcodeproj`. Shared schemes:

- **BeaconC1**: iPhone app, with OLFWatch embedded and automatically signed.
- **OLFWatch**: watch app, bundle ID `com.culubo.olf.beaconc1.watchkitapp`,
  companion `com.culubo.olf.beaconc1`. Minimum watchOS 10 / iOS 17.

Choose the same development team for both targets. Run on a paired watch and
phone. Xcode may need its watchOS platform downloaded before scheme builds.
No HealthKit, location, microphone, internet server or background workout mode
is used. watchOS cannot advertise this custom UUID; the phone remains the beacon.

## Request handling

Only live WatchConnectivity `sendMessage` calls mutate SOS. Application context
contains read-only phone snapshots. Commands contain a random request ID,
timestamp, requested SOS bit and the last observed durable phone status order.
The phone rejects malformed commands, commands older than 15 seconds or more
than 5 seconds ahead, and commands whose expected order differs from its current
persisted `(window, revision)`. This prevents an old clear from overwriting a
newer phone/watch change or radio rotation. The phone uses the same durable SOS
allocator and radio HMAC as its local UI; it acknowledges only the accepted
state. There is no automatic retry. The watch stops waiting after 8 seconds and
reports **Not confirmed**; late replies cannot mark another request successful.

## Checks

```sh
swiftc Shared/WatchCommand.swift tests/WatchCommandChecks.swift -o /tmp/olf-watch-command-check
/tmp/olf-watch-command-check
```

Run from this directory. These checks exercise both set and clear, expiry,
clock skew, stale orders after phone changes/rotation, and malformed messages.
Use the existing `SOSChecks.swift` harness for durable radio status allocation.
Physical WatchConnectivity delivery and haptics require paired real devices.

Apple references: [WatchConnectivity sessions](https://developer.apple.com/documentation/watchconnectivity/wcsession),
[watch companion bundle ID](https://developer.apple.com/documentation/bundleresources/information-property-list/wkcompanionappbundleidentifier),
[CoreBluetooth platform limitations](https://developer.apple.com/documentation/corebluetooth/cbperipheralmanager).
