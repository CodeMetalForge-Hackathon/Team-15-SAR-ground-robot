// C1: foreground CoreBluetooth advertiser. Advertises exactly one 128-bit
// service UUID and no local name. No manufacturer or service data.
import CoreBluetooth
import Foundation

final class Advertiser: NSObject, ObservableObject, CBPeripheralManagerDelegate {
    enum Mode: String, CaseIterable, Identifiable {
        case staticA1 = "Static A1"
        case rotating = "Rotating"
        case status = "SOS status"
        var id: String { rawValue }
    }

    @Published var mode: Mode = .status
    @Published var btState = "unknown"
    @Published var running = false
    @Published var advertisingOK = false
    @Published var currentUUID = "-"
    @Published var currentCounter: UInt32?
    @Published private(set) var sos = false
    @Published private(set) var statusReady = false
    @Published var statusMessage = ""
    @Published var log: [String] = []

    private var pm: CBPeripheralManager!
    private var timer: Timer?
    private var statusState: SOSState?
    var statusOrder: String {
        guard let record = statusState?.record else { return "none" }
        return "\(record.counter):\(record.revision)"
    }
    private let fmt: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    override init() {
        super.init()
        do {
            statusState = try SOSState()
            sos = statusState?.record?.sos ?? false
            statusReady = true
        } catch { statusMessage = error.localizedDescription }
        pm = CBPeripheralManager(delegate: self, queue: nil)
        add("self-check vector A1: \(OLFToken.selfCheckA1() ? "PASS" : "FAIL")")
        add("self-check status v2: \(OLFToken.selfCheckStatus() ? "PASS" : "FAIL")")
    }

    func start() {
        guard OLFToken.selfCheckA1(), OLFToken.selfCheckStatus() else { add("reference vector FAILED"); return }
        guard mode != .status || statusReady else { add("SOS state unavailable"); return }
        guard !running else { return }
        guard pm.state == .poweredOn else { add("cannot start: bluetooth \(btState)"); return }
        statusMessage = ""
        running = true
        add("START mode=\(mode.rawValue)")
        tick(force: true)
        guard running else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            self?.tick(force: false)
        }
    }

    func setSOS(_ value: Bool) {
        guard mode == .status, statusReady, value != sos else { return }
        guard let counter = OLFToken.counter(at: Date()) else { return }
        do {
            guard let next = try statusState?.allocate(counter: counter, sos: value) else { return }
            sos = value
            statusMessage = ""
            if running { advertiseStatus(next) }
        } catch { statusMessage = error.localizedDescription; add(statusMessage) }
    }

    private func advertiseStatus(_ record: SOSState.Record) {
        let uuid = OLFToken.uuidString(OLFToken.statusPayload(alias: OLFToken.syntheticAlias,
            counter: record.counter, revision: record.revision, sos: record.sos, key: OLFToken.syntheticKey))
        currentUUID = uuid; currentCounter = record.counter; advertisingOK = false
        pm.stopAdvertising()
        pm.startAdvertising([CBAdvertisementDataServiceUUIDsKey: [CBUUID(string: uuid)]])
        add("status=\(record.sos ? "SOS" : "NORMAL") counter=\(record.counter) revision=\(record.revision)")
    }

    func stop() {
        timer?.invalidate(); timer = nil
        pm.stopAdvertising()
        running = false; advertisingOK = false
        currentUUID = "-"; currentCounter = nil
        add("STOP")
    }

    private func tick(force: Bool) {
        guard running else { return }
        if mode == .status {
            guard let counter = OLFToken.counter(at: Date()) else { stop(); return }
            if !force && currentCounter == counter { return }
            do {
                guard let next = try statusState?.allocate(counter: counter, sos: sos) else { stop(); return }
                advertiseStatus(next)
            } catch { statusMessage = error.localizedDescription; add(statusMessage); stop() }
            return
        }
        var uuid = OLFToken.vectorA1UUID
        var ctr: UInt32? = OLFToken.vectorA1Counter
        if mode == .rotating {
            guard let c = OLFToken.counter(at: Date()) else { add("counter overflow: stopping"); stop(); return }
            ctr = c
            uuid = OLFToken.uuidString(OLFToken.payload(alias: OLFToken.syntheticAlias, counter: c,
                                                        key: OLFToken.syntheticKey))
        }
        if !force && uuid == currentUUID { return }
        currentUUID = uuid; currentCounter = ctr
        pm.stopAdvertising()
        pm.startAdvertising([CBAdvertisementDataServiceUUIDsKey: [CBUUID(string: uuid)]])
        add("advertise uuid=\(uuid) counter=\(ctr.map { String($0) } ?? "-")")
    }

    func peripheralManagerDidUpdateState(_ p: CBPeripheralManager) {
        switch p.state {
        case .poweredOn: btState = "poweredOn"
        case .poweredOff: btState = "poweredOff"
        case .unauthorized: btState = "unauthorized"
        case .unsupported: btState = "unsupported"
        case .resetting: btState = "resetting"
        default: btState = "unknown"
        }
        add("bluetooth \(btState)")
        if p.state != .poweredOn && running { stop() }
    }

    func peripheralManagerDidStartAdvertising(_ p: CBPeripheralManager, error: Error?) {
        if let error { statusMessage = "Beacon could not start. Stop and try again."; advertisingOK = false; add("startAdvertising ERROR: \(error.localizedDescription)") }
        else { advertisingOK = true; add("startAdvertising callback OK (not proof of reception)") }
    }

    func add(_ s: String) {
        log.insert("\(fmt.string(from: Date())) \(s)", at: 0)
        if log.count > 40 { log.removeLast() }
    }
}
