import XCTest
@testable import JamesAuStudioCompanion

final class CompanionAuthorizationTests: XCTestCase {
    func testPhaseAConfigurationCannotStartOAuth() {
        XCTAssertEqual(CompanionConfiguration.phaseA.authorizationState, .applicationNotReviewed)
        XCTAssertNil(CompanionConfiguration.phaseA.authorizationDestination())
    }

    func testReviewedConfigurationRejectsUntrustedAuthorizationURL() {
        let configuration = CompanionConfiguration(studioDisplayName: "James Au Studio", expectedBilibiliUID: "3747561334639021", expectedBilibiliNickname: "bili_16401752274", providerApplicationID: "approved-app-id", authorizationURL: URL(string: "https://example.com/authorize"), applicationReviewed: true)
        XCTAssertEqual(configuration.authorizationState, .applicationNotReviewed)
        XCTAssertNil(configuration.authorizationDestination())
    }

    func testReviewedBilibiliConfigurationCanProvideAnAuthorizationDestination() {
        let destination = URL(string: "https://open.bilibili.com/authorize")!
        let configuration = CompanionConfiguration(studioDisplayName: "James Au Studio", expectedBilibiliUID: "3747561334639021", expectedBilibiliNickname: "bili_16401752274", providerApplicationID: "approved-app-id", authorizationURL: destination, applicationReviewed: true)
        XCTAssertEqual(configuration.authorizationState, .authorizationReady)
        XCTAssertEqual(configuration.authorizationDestination(), destination)
    }
}
