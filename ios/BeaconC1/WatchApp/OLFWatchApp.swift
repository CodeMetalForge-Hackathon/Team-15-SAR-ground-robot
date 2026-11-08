import SwiftUI

@main
struct OLFWatchApp: App {
    @StateObject private var link = WatchLink()
    @Environment(\.scenePhase) private var phase
    private let orange = Color(red: 224/255, green: 79/255, blue: 22/255)
    var body: some Scene {
        WindowGroup {
            ScrollView {
                VStack(spacing: 4) {
                    Text(link.sos.map { $0 ? "SOS ON" : "SOS OFF" } ?? "SOS —")
                        .font(.system(.title2, design: .serif).bold())
                        .foregroundStyle(link.sos == true ? orange : .primary)
                    Button(link.sos == true ? "Clear SOS" : "SOS") { link.setSOS(link.sos != true) }
                        .font(.headline).buttonStyle(.borderedProminent).tint(orange)
                        .disabled(!link.reachable || !link.ready || link.pending || link.sos == nil)
                    Text(link.feedback.isEmpty ? (link.reachable ? "Phone connected" : "Phone unavailable") : link.feedback)
                        .font(.caption2).multilineTextAlignment(.center)
                    Text(link.reachable && link.broadcasting ? "Phone broadcasting" : "Open phone · Start beacon")
                        .font(.caption2).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    if !link.reachable && link.sos != nil {
                        Text("Last known SOS status").font(.caption2).foregroundStyle(.secondary)
                    }
                    Button("Refresh") { link.refresh() }.font(.caption2)
                        .buttonStyle(.plain).disabled(link.pending)
                    Text("DEMO · No emergency call").font(.system(size: 10)).foregroundStyle(.secondary)
                }.padding(.horizontal, 4)
            }
            .onAppear { link.refresh() }
            .onChange(of: phase) { _, value in if value == .active { link.refresh() } }
        }
    }
}
