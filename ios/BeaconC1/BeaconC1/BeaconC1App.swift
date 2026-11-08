import SwiftUI

@main
struct BeaconC1App: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

struct ContentView: View {
    @StateObject private var adv = Advertiser()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("C1 FEASIBILITY · FOREGROUND ONLY").font(.headline)
            Text("SYNTHETIC TEST KEY · LABELLED EXPERIMENT").font(.caption.bold())
                .padding(4).background(Color.orange.opacity(0.3))
            Picker("Mode", selection: $adv.mode) {
                ForEach(Advertiser.Mode.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented).disabled(adv.running)

            Button(adv.running ? "Stop" : "Start") { adv.running ? adv.stop() : adv.start() }
                .buttonStyle(.borderedProminent).font(.title2)

            TimelineView(.periodic(from: .now, by: 0.1)) { ctx in
                let t = ctx.date.timeIntervalSince1970
                Text(String(format: "Unix %.1f · counter ", t) + "\(Int(t / 30))"
                     + String(format: " · %.1f s into window", t.truncatingRemainder(dividingBy: 30)))
                    .font(.system(.footnote, design: .monospaced))
            }
            Text("Bluetooth: \(adv.btState) · advertising: \(adv.advertisingOK ? "yes" : "no")")
                .font(.footnote)
            Text(adv.currentUUID).font(.system(.body, design: .monospaced)).bold()
                .minimumScaleFactor(0.5).lineLimit(1)
            Text("counter: \(adv.currentCounter.map { String($0) } ?? "-")")
                .font(.system(.footnote, design: .monospaced))
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(adv.log.enumerated()), id: \.offset) { _, line in
                        Text(line).font(.system(size: 10, design: .monospaced))
                    }
                }
            }
        }
        .padding()
        .onChange(of: adv.running) { _, running in
            UIApplication.shared.isIdleTimerDisabled = running
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { adv.stop() }
        }
    }
}
