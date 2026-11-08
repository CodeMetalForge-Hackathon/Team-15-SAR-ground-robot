import Foundation
func check(_ value: @autoclosure () -> Bool) { precondition(value()) }
@main
struct SOSChecks {
 static func main() throws {
check(OLFToken.selfCheckA1()); check(OLFToken.selfCheckStatus())
let clear = OLFToken.statusPayload(alias: 1, counter: OLFToken.vectorA1Counter, revision: 2, sos: false, key: OLFToken.syntheticKey)
check(OLFToken.uuidString(clear) == "02017210-7984-03AC-DD8C-F2D2CF388A19")
let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: directory) }
let url = directory.appendingPathComponent("status.json")
let state = try SOSState(url: url)
let normal = try state.allocate(counter: 100, sos: false)
check(normal.revision == 0)
let sos = try state.allocate(counter: 100, sos: true)
check(sos.revision == 1 && sos.sos)
let restored = try SOSState(url: url)
check(restored.record?.sos == true)
let cleared = try restored.allocate(counter: 100, sos: false)
check(cleared.revision == 2 && !cleared.sos)
do { _ = try restored.allocate(counter: 99, sos: false); fatalError("rollback allowed") }
catch SOSState.Failure.clockRollback {}
for i in 3...15 { let record = try restored.allocate(counter: 100, sos: true); check(Int(record.revision) == i) }
do { _ = try restored.allocate(counter: 100, sos: false); fatalError("sequence wrapped") }
catch SOSState.Failure.rateLimit {}
let nextWindow = try restored.allocate(counter: 101, sos: false)
check(nextWindow.revision == 0)
try Data("corrupt".utf8).write(to: url)
do { _ = try SOSState(url: url); fatalError("corrupt state allowed") }
catch SOSState.Failure.corrupt {}
// An uncertain disk write cannot allocate the same order for a different status.
let blockedURL = directory.appendingPathComponent("blocked/status.json")
let blocked = try SOSState(url: blockedURL)
try Data("file blocking directory".utf8).write(to: directory.appendingPathComponent("blocked"))
do { _ = try blocked.allocate(counter: 100, sos: false); fatalError("write unexpectedly succeeded") } catch {}
try FileManager.default.removeItem(at: directory.appendingPathComponent("blocked"))
do { _ = try blocked.allocate(counter: 100, sos: true); fatalError("failed allocator reused") }
catch SOSState.Failure.sync {}
print("PASS: Swift v1/v2 vectors, durable SOS/clear, restore, rollback, sequence cap, corrupt state, disk failure")
 }
}
