import Combine
import Foundation
import WatchConnectivity
import WatchKit

final class WatchLink: NSObject, ObservableObject, WCSessionDelegate {
    @Published private(set) var sos: Bool?
    @Published private(set) var broadcasting = false
    @Published private(set) var ready = false
    @Published private(set) var reachable = false
    @Published private(set) var pending = false
    @Published private(set) var feedback = "Open OLF C1 on your phone."
    private var order: String?
    private var latestSnapshot = -Double.infinity
    private var requestID: UUID?
    override init() {
        super.init()
        if WCSession.isSupported() { WCSession.default.delegate = self; WCSession.default.activate() }
    }
    private func accept(_ data: [String: Any]) {
        guard data["version"] as? Int == 1, let issued = data["issued"] as? Double,
              issued.isFinite, issued >= latestSnapshot,
              let sos = data["sos"] as? Bool, let order = data["order"] as? String,
              let ready = data["ready"] as? Bool, let live = data["broadcasting"] as? Bool else { return }
        if self.order != nil && self.order != order { feedback = "" }
        latestSnapshot = issued; self.sos = sos; self.order = order
        self.ready = ready; broadcasting = live
    }
    func refresh() {
        let session = WCSession.default
        reachable = session.activationState == .activated && session.isReachable
        guard reachable, !pending else { return }
        send(["kind": "snapshot"], mutation: false)
    }
    func setSOS(_ value: Bool) {
        guard reachable, ready, !pending, let order else { feedback = "Phone unavailable. Open OLF C1."; return }
        send(["kind": "sos", "version": 1, "id": UUID().uuidString,
              "issued": Date().timeIntervalSince1970, "order": order, "sos": value], mutation: true)
    }
    private func send(_ message: [String: Any], mutation: Bool) {
        let id = UUID(); requestID = id; pending = true
        if mutation { feedback = "Sending…" }
        WCSession.default.sendMessage(message, replyHandler: { reply in
            DispatchQueue.main.async {
                guard self.requestID == id else { return }
                self.requestID = nil; self.pending = false; self.accept(reply)
                if let error = reply["error"] as? String { self.feedback = error }
                else if mutation && reply["accepted"] as? Bool == true {
                    self.feedback = "Phone received"
                    WKInterfaceDevice.current().play(.notification)
                } else { self.feedback = "" }
            }
        }, errorHandler: { _ in DispatchQueue.main.async { self.failed(id) } })
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { self.failed(id) }
    }
    private func failed(_ id: UUID) {
        guard requestID == id else { return }
        requestID = nil; pending = false
        reachable = WCSession.default.isReachable
        feedback = "Not confirmed"
    }
    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        DispatchQueue.main.async { self.accept(session.receivedApplicationContext); self.refresh() }
    }
    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async {
            self.reachable = session.isReachable
            if !self.reachable && !self.pending { self.feedback = "" }
            self.refresh()
        }
    }
    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async { self.accept(applicationContext) }
    }
}
