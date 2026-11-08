// Durable sequence allocation for status v2. Never reuse or reset a sequence
// after an SOS/clear update; allocation is persisted before advertising.
import Darwin
import Foundation

final class SOSState {
    struct Record: Codable {
        let version: Int
        let counter: UInt32
        let revision: UInt8
        let sos: Bool
    }
    enum Failure: LocalizedError {
        case corrupt, clockRollback, rateLimit, sync
        var errorDescription: String? {
            switch self {
            case .corrupt: return "SOS state invalid. Status advertising is disabled."
            case .clockRollback: return "Clock moved backward. Wait for the previous window."
            case .rateLimit: return "Status update limit reached. Wait for the next 30-second window."
            case .sync: return "Could not save status sequence. Update withheld."
            }
        }
    }
    private let url: URL
    private(set) var record: Record?
    private var writeFailed = false

    init(url: URL? = nil) throws {
        self.url = url ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OLF-C1/status-v2.json")
        if FileManager.default.fileExists(atPath: self.url.path) {
            let data = try Data(contentsOf: self.url)
            guard data.count <= 4096,
                  let saved = try? JSONDecoder().decode(Record.self, from: data),
                  saved.version == 2, saved.counter < (1 << 27), saved.revision < 16 else {
                throw Failure.corrupt
            }
            record = saved
        }
    }

    func allocate(counter: UInt32, sos: Bool) throws -> Record {
        guard !writeFailed else { throw Failure.sync }
        guard counter < (1 << 27) else { throw Failure.clockRollback }
        if let old = record, counter < old.counter { throw Failure.clockRollback }
        let revision = record?.counter == counter ? Int(record!.revision) + 1 : 0
        guard revision < 16 else { throw Failure.rateLimit }
        let next = Record(version: 2, counter: counter, revision: UInt8(revision), sos: sos)
        let directory = url.deletingLastPathComponent()
        do {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try JSONEncoder().encode(next).write(to: url, options: .atomic)
        let file = try FileHandle(forWritingTo: url)
        defer { try? file.close() }
        try file.synchronize()
        let fd = open(directory.path, O_RDONLY)
        guard fd >= 0 else { throw Failure.sync }
        defer { close(fd) }
        guard fsync(fd) == 0 else { throw Failure.sync }
        } catch { writeFailed = true; throw error }
        record = next
        return next
    }
}
