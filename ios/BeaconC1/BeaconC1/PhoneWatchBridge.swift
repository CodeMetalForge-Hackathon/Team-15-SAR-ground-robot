import Combine
import Foundation
import WatchConnectivity

final class PhoneWatchBridge: NSObject, ObservableObject, WCSessionDelegate {
    let advertiser = Advertiser()
    private var changes: AnyCancellable?
    override init() {
        super.init()
        if WCSession.isSupported() { WCSession.default.delegate = self; WCSession.default.activate() }
        changes = advertiser.objectWillChange.receive(on: RunLoop.main).sink { [weak self] _ in self?.publish() }
    }
    private func snapshot() -> [String: Any] {
        ["version": 1, "sos": advertiser.sos, "order": advertiser.statusOrder,
         "ready": advertiser.statusReady && advertiser.mode == .status,
         "broadcasting": advertiser.running && advertiser.advertisingOK && advertiser.mode == .status,
         "issued": Date().timeIntervalSince1970]
    }
    private func publish() {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        guard session.activationState == .activated, session.isPaired, session.isWatchAppInstalled else { return }
        try? session.updateApplicationContext(snapshot())
    }
    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        DispatchQueue.main.async { self.publish() }
    }
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) { session.activate() }
    func sessionWatchStateDidChange(_ session: WCSession) { DispatchQueue.main.async { self.publish() } }
    func sessionReachabilityDidChange(_ session: WCSession) { DispatchQueue.main.async { self.publish() } }
    func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        DispatchQueue.main.async {
            var reply: [String: Any]
            do {
                if message["kind"] as? String == "snapshot" {
                    reply = self.snapshot()
                } else {
                    guard self.advertiser.statusReady, self.advertiser.mode == .status else {
                        reply = self.snapshot(); reply["error"] = "Open SOS status mode on the phone."
                        replyHandler(reply); return
                    }
                    let desired = try WatchCommand.desired(message, currentOrder: self.advertiser.statusOrder, now: Date())
                    self.advertiser.setSOS(desired)
                    reply = self.snapshot()
                    if self.advertiser.sos == desired {
                        reply["accepted"] = true
                    } else {
                        reply["error"] = self.advertiser.statusMessage.isEmpty ? "Phone could not save status." : self.advertiser.statusMessage
                    }
                }
            } catch { reply = self.snapshot(); reply["error"] = error.localizedDescription }
            replyHandler(reply)
            self.publish()
        }
    }
}
