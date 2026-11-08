import SwiftUI

@main
struct BeaconC1App: App {
    @StateObject private var watch = PhoneWatchBridge()
    var body: some Scene {
        WindowGroup { ContentView(adv: watch.advertiser) }
    }
}

struct ContentView: View {
    @ObservedObject var adv: Advertiser
    @State private var showDetails = false
    @Environment(\.scenePhase) private var scenePhase
    private var statusMode: Bool { adv.mode == .status }
    private var canStart: Bool { adv.btState == "poweredOn" && (!statusMode || adv.statusReady) }
    private var transmission: String {
        if adv.running { return adv.advertisingOK ? "Sending signal" : "Starting…" }
        switch adv.btState {
        case "poweredOff": return "Bluetooth off"
        case "unauthorized": return "Bluetooth access needed"
        case "unsupported": return "Bluetooth unavailable"
        case "poweredOn": return "Signal paused"
        default: return "Waiting for Bluetooth"
        }
    }
    private var guidance: String {
        if !statusMode { return "Test mode is on. Change it in settings to use SOS." }
        if adv.sos && !adv.running { return "SOS is on. Tap Start signal to send it." }
        return "Keep this app open to send your signal."
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack(spacing: 10) {
                    Image("RescueLogo").resizable().scaledToFit()
                        .frame(width: 36, height: 36).accessibilityHidden(true)
                    Text("Team-15").font(.headline)
                    Text("/ Rescue").font(.subheadline).foregroundStyle(PhoneTheme.muted)
                    Spacer(minLength: 0)
                    Button { showDetails = true } label: {
                        Image(systemName: "gearshape").font(.body.weight(.semibold))
                            .frame(width: 44, height: 44)
                            .background(PhoneTheme.raised, in: RoundedRectangle(cornerRadius: 9))
                            .overlay(RoundedRectangle(cornerRadius: 9).stroke(PhoneTheme.border))
                    }.buttonStyle(.plain).accessibilityLabel("Technical details")
                }
                Divider().overlay(PhoneTheme.border)
                VStack(alignment: .leading, spacing: 8) {
                    Text("PHONE SIGNAL").font(.caption.weight(.bold)).tracking(1.2)
                        .foregroundStyle(PhoneTheme.accent)
                    Text("Rescue signal").font(.largeTitle.bold())
                    Text("Your signal to the search team.")
                        .font(.subheadline).foregroundStyle(PhoneTheme.muted)
                }
                VStack(alignment: .leading, spacing: 20) {
                    Text("YOUR STATUS").font(.caption.weight(.bold)).tracking(1)
                        .foregroundStyle(PhoneTheme.muted)
                    Label(transmission, systemImage: adv.running && adv.advertisingOK ? "antenna.radiowaves.left.and.right" : "antenna.radiowaves.left.and.right.slash")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(adv.running && adv.advertisingOK ? PhoneTheme.green : PhoneTheme.muted)
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(PhoneTheme.raised, in: Capsule())
                        .overlay(Capsule().stroke(PhoneTheme.border))
                        .accessibilityAddTraits(.updatesFrequently)
                    Divider().overlay(PhoneTheme.border)
                    VStack(alignment: .leading, spacing: 8) {
                        Text(statusMode ? (adv.sos ? "SOS is on" : "SOS is off") : "TEST MODE")
                            .font(.system(.largeTitle, weight: .bold))
                            .foregroundStyle(statusMode && adv.sos ? PhoneTheme.red : PhoneTheme.text)
                            .accessibilityAddTraits(.updatesFrequently)
                        Text(statusMode ? (adv.sos ? "Your signal includes a request for help." : "Your signal does not request help.") : "Synthetic beacon test")
                            .font(.subheadline).foregroundStyle(PhoneTheme.muted)
                    }
                    if statusMode {
                        Toggle("Request help (SOS)", isOn: Binding(get: { adv.sos }, set: { adv.setSOS($0) }))
                            .font(.headline).tint(PhoneTheme.red).disabled(!adv.statusReady)
                            .accessibilityHint("Changes the SOS status carried by your beacon tag")
                        Text("Stays on until you turn it off.")
                            .font(.subheadline).foregroundStyle(PhoneTheme.muted)
                    }
                }
                .padding(22).frame(maxWidth: .infinity, alignment: .leading)
                .background(PhoneTheme.panel, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(statusMode && adv.sos ? PhoneTheme.red.opacity(0.6) : PhoneTheme.border))
                VStack(alignment: .leading, spacing: 12) {
                    Button { adv.running ? adv.stop() : adv.start() } label: {
                        Label(adv.running ? "Stop signal" : "Start signal", systemImage: adv.running ? "stop.fill" : "antenna.radiowaves.left.and.right")
                            .font(.headline).frame(maxWidth: .infinity, minHeight: 56)
                            .foregroundStyle(adv.running ? PhoneTheme.red : .white)
                            .background(adv.running ? PhoneTheme.red.opacity(0.1) : PhoneTheme.accent, in: RoundedRectangle(cornerRadius: 9))
                            .overlay(RoundedRectangle(cornerRadius: 9).stroke(adv.running ? PhoneTheme.red.opacity(0.5) : PhoneTheme.accent))
                    }
                    .buttonStyle(.plain)
                    .disabled(!adv.running && !canStart).opacity(!adv.running && !canStart ? 0.5 : 1)
                    Text(guidance).font(.subheadline).foregroundStyle(PhoneTheme.muted)
                    if !adv.statusMessage.isEmpty {
                        Label(adv.statusMessage, systemImage: "info.circle")
                            .font(.subheadline.weight(.medium)).foregroundStyle(PhoneTheme.accent)
                            .accessibilityAddTraits(.updatesFrequently)
                    }
                }
                VStack(alignment: .leading, spacing: 8) {
                    Label("DEMO ONLY", systemImage: "info.circle")
                        .font(.caption.weight(.semibold)).tracking(0.6)
                    Text("This app does not call emergency services.").font(.caption)
                }
                .foregroundStyle(PhoneTheme.muted)
                .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                .background(PhoneTheme.panel, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(PhoneTheme.border))
            }
            .padding(20).frame(maxWidth: 560).frame(maxWidth: .infinity)
        }
        .background(PhoneTheme.canvas.ignoresSafeArea()).foregroundStyle(PhoneTheme.text)
        .tint(PhoneTheme.accent).preferredColorScheme(.dark)
        .sheet(isPresented: $showDetails) { BeaconDetails(adv: adv) }
        .onChange(of: adv.running) { _, running in
            UIApplication.shared.isIdleTimerDisabled = running
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { adv.stop() }
        }
    }
}

// Matches the operator dashboard's Ops palette.
enum PhoneTheme {
    static let canvas = Color(red: 11/255, green: 11/255, blue: 12/255)
    static let panel = Color(red: 19/255, green: 19/255, blue: 20/255)
    static let raised = Color(red: 31/255, green: 31/255, blue: 34/255)
    static let border = Color.white.opacity(0.13)
    static let text = Color(red: 237/255, green: 237/255, blue: 238/255)
    static let muted = Color(red: 157/255, green: 157/255, blue: 163/255)
    static let accent = Color(red: 240/255, green: 112/255, blue: 30/255)
    static let green = Color(red: 34/255, green: 197/255, blue: 94/255)
    static let red = Color(red: 239/255, green: 68/255, blue: 68/255)
}
