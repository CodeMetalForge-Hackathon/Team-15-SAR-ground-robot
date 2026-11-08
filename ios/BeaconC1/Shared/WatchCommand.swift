import Foundation

// Only live commands with a recent timestamp and the phone's current durable
// revision may change SOS. No queued mutation can later overwrite a newer state.
enum WatchCommand {
    enum Rejection: LocalizedError {
        case malformed, expired, changed
        var errorDescription: String? {
            switch self {
            case .malformed: return "Invalid request. Try again."
            case .expired: return "Request expired. Try again."
            case .changed: return "Phone status changed. Check and try again."
            }
        }
    }
    static func desired(_ message: [String: Any], currentOrder: String, now: Date) throws -> Bool {
        guard message["kind"] as? String == "sos", message["version"] as? Int == 1,
              let id = message["id"] as? String, UUID(uuidString: id) != nil,
              let issued = message["issued"] as? Double, issued.isFinite,
              let order = message["order"] as? String,
              let desired = message["sos"] as? Bool else { throw Rejection.malformed }
        let age = now.timeIntervalSince1970 - issued
        guard age >= -5, age <= 15 else { throw Rejection.expired }
        guard order == currentOrder else { throw Rejection.changed }
        return desired
    }
}
