import Foundation

enum CompanionAuthorizationState: String, Equatable {
    case applicationNotReviewed = "Application review pending"
    case authorizationReady = "Authorization ready"
    case authorizationRevoked = "Authorization revoked"
}

struct CompanionConfiguration: Codable, Equatable {
    let studioDisplayName: String
    let expectedBilibiliUID: String
    let expectedBilibiliNickname: String
    let providerApplicationID: String?
    let authorizationURL: URL?
    let applicationReviewed: Bool

    static let phaseA = CompanionConfiguration(studioDisplayName: "James Au Studio", expectedBilibiliUID: "3747561334639021", expectedBilibiliNickname: "bili_16401752274", providerApplicationID: nil, authorizationURL: nil, applicationReviewed: false)

    var authorizationState: CompanionAuthorizationState {
        guard applicationReviewed, providerApplicationID?.isEmpty == false, let authorizationURL, isApprovedProviderURL(authorizationURL) else { return .applicationNotReviewed }
        return .authorizationReady
    }

    func authorizationDestination() -> URL? { authorizationState == .authorizationReady ? authorizationURL : nil }

    private func isApprovedProviderURL(_ url: URL) -> Bool {
        guard url.scheme == "https", let host = url.host?.lowercased() else { return false }
        return host == "open.bilibili.com" || host.hasSuffix(".bilibili.com")
    }
}

enum CompanionConfigurationLoader {
    static func load(bundle: Bundle = .main) -> CompanionConfiguration {
        guard let file = bundle.url(forResource: "CompanionConfiguration", withExtension: "json"), let data = try? Data(contentsOf: file), let configuration = try? JSONDecoder().decode(CompanionConfiguration.self, from: data) else { return .phaseA }
        return configuration
    }
}
