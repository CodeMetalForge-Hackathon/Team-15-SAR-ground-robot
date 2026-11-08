import SwiftUI

struct BeaconDetails: View {
    @ObservedObject var adv: Advertiser
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Test configuration") {
                    Text("PUBLIC SYNTHETIC TEST KEY · LABELLED EXPERIMENT").font(.caption.bold())
                    Picker("Mode", selection: $adv.mode) {
                        ForEach(Advertiser.Mode.allCases) { Text($0.rawValue).tag($0) }
                    }.disabled(adv.running)
                    Text("Stop the beacon before changing test modes. SOS is sent only in SOS status mode.")
                        .font(.caption)
                }
                .listRowBackground(PhoneTheme.panel)
                Section("Radio") {
                    LabeledContent("Bluetooth", value: adv.btState)
                    LabeledContent("Advertising", value: adv.advertisingOK ? "Yes" : "No")
                    Text("Advertising is not confirmation of receiver detection.").font(.caption)
                    LabeledContent("Counter", value: adv.currentCounter.map { String($0) } ?? "—")
                    Text(adv.currentUUID).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                }
                .listRowBackground(PhoneTheme.panel)
                Section("Log") {
                    ForEach(Array(adv.log.enumerated()), id: \.offset) { _, line in
                        Text(line).font(.system(.caption2, design: .monospaced)).textSelection(.enabled)
                    }
                }
                .listRowBackground(PhoneTheme.panel)
            }
            .scrollContentBackground(.hidden)
            .background(PhoneTheme.canvas)
            .foregroundStyle(PhoneTheme.text)
            .navigationTitle("Technical details").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .tint(PhoneTheme.accent)
        .preferredColorScheme(.dark)
    }
}
