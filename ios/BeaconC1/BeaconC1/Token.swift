// C1 feasibility only. Wire format v1 (SENSOR_ID_SPEC.md).
// LABELLED EXPERIMENT: uses the PUBLIC SYNTHETIC TEST KEY for alias 1 from
// evidence/c0-20261107T1914Z/protocol_vectors_v1.json. Never enroll it.
// Production key storage (Keychain) is out of scope for C1.
import CryptoKit
import Foundation

enum OLFToken {
    static let domain = Array("OLF/BLE-ID/v1".utf8)
    static let window: Double = 30
    static let syntheticAlias: UInt8 = 1
    static let syntheticKey = SymmetricKey(data: Data((0..<32).map { UInt8($0) }))

    // Vector A1 (alias 1, counter 59802572, synthetic key 1), used by the static stage.
    static let vectorA1Counter: UInt32 = 59_802_572
    static let vectorA1UUID = "01010390-83CC-C438-CFA7-043609B9D1C4"

    static func counter(at date: Date) -> UInt32? {
        let c = floor(date.timeIntervalSince1970 / window)
        guard c >= 0, c <= Double(UInt32.max) else { return nil }   // reject overflow
        return UInt32(c)
    }

    static func payload(alias: UInt8, counter: UInt32, key: SymmetricKey) -> [UInt8] {
        let header: [UInt8] = [0x01, alias] + withUnsafeBytes(of: counter.bigEndian) { Array($0) }
        let mac = HMAC<SHA256>.authenticationCode(for: domain + header, using: key)
        return header + Array(Array(mac).prefix(10))
    }

    /// Bytes 0..15 in order, formatted 8-4-4-4-12 (uppercase, as CBUUID prints it).
    static func uuidString(_ p: [UInt8]) -> String {
        precondition(p.count == 16)
        let h = p.map { String(format: "%02X", $0) }.joined()
        let c = Array(h)
        func s(_ a: Int, _ b: Int) -> String { String(c[a..<b]) }
        return "\(s(0, 8))-\(s(8, 12))-\(s(12, 16))-\(s(16, 20))-\(s(20, 32))"
    }

    /// Swift vs the independently generated C0 vector A1.
    static func selfCheckA1() -> Bool {
        uuidString(payload(alias: 1, counter: vectorA1Counter, key: syntheticKey)) == vectorA1UUID
    }
}
