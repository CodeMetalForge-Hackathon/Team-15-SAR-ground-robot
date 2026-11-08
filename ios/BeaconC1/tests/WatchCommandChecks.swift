import Foundation

@main
struct WatchCommandChecks {
    static func main() throws {
        let now = Date(timeIntervalSince1970: 1_794_077_187)
        let request: [String: Any] = ["kind": "sos", "version": 1, "id": UUID().uuidString,
            "issued": now.timeIntervalSince1970, "order": "59802572:1", "sos": true]
        func reject(_ message: [String: Any], order: String = "59802572:1", at: Date? = nil) {
            do { _ = try WatchCommand.desired(message, currentOrder: order, now: at ?? now); fatalError("Invalid command accepted") }
            catch is WatchCommand.Rejection {} catch { fatalError("Unexpected error") }
        }
        let set = try WatchCommand.desired(request, currentOrder: "59802572:1", now: now)
        precondition(set)
        var clear = request; clear["sos"] = false
        let cleared = try WatchCommand.desired(clear, currentOrder: "59802572:1", now: now)
        precondition(!cleared)
        // An older set OR clear cannot overwrite newer phone state, including
        // phone UI changes, another command, or a fresh radio rotation.
        reject(request, order: "59802572:2"); reject(clear, order: "59802572:2")
        reject(request, order: "59802573:0")
        reject(request, at: now.addingTimeInterval(16))
        reject(request, at: now.addingTimeInterval(-6))
        for key in ["kind", "version", "id", "issued", "order", "sos"] {
            var missing = request; missing.removeValue(forKey: key); reject(missing)
        }
        var invalid = request; invalid["issued"] = Double.nan; reject(invalid)
        invalid = request; invalid["id"] = "invalid"; reject(invalid)
        invalid = request; invalid["version"] = 2; reject(invalid)
        invalid = request; invalid["sos"] = "true"; reject(invalid)
        print("PASS: Watch SOS/clear validation, stale revisions, expiry, clock skew, malformed commands")
    }
}
