import SwiftUI

struct ContentView: View {
    private let configuration = CompanionConfigurationLoader.load()
    @Environment(\.openURL) private var openURL

    var body: some View {
        NavigationStack {
            List {
                Section("Studio companion") {
                    LabeledContent("Studio", value: configuration.studioDisplayName)
                    LabeledContent("Bundle ID", value: "com.jamesau.studio.companion")
                }
                Section("Expected Bilibili account") {
                    LabeledContent("UID", value: configuration.expectedBilibiliUID)
                    LabeledContent("Nickname", value: configuration.expectedBilibiliNickname)
                }
                Section("Authorization") {
                    LabeledContent("Status", value: configuration.authorizationState.rawValue)
                    Text("OAuth stays disabled until Bilibili approves the developer application and its exact authorization endpoint is configured.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    if let destination = configuration.authorizationDestination() {
                        Button("Continue to Bilibili") { openURL(destination) }
                    } else {
                        Button("Continue to Bilibili") {}.disabled(true)
                    }
                }
                Section("Privacy and safety") {
                    Text("This companion contains no Bilibili client secret, access token, refresh token, password, cookie, or upload control. It cannot publish videos in Phase A.")
                        .font(.footnote)
                }
            }
            .navigationTitle("Studio Companion")
        }
    }
}

#Preview { ContentView() }
