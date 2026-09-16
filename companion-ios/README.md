# James Au Studio Companion for iOS

This is the iOS companion planned for Bilibili developer-app association. Its bundle identifier is `com.jamesau.studio.companion`.

Phase A has no Bilibili network operation. It displays the expected Bilibili profile, refuses to start OAuth until an approved provider application ID and official authorization URL are configured, and contains no client secret, token, cookie, password, upload, or publishing function.

## Build prerequisite

This Mac needs full Xcode and XcodeGen before the project can be generated, compiled, or signed. Command Line Tools alone cannot build iOS applications.

After those tools are installed by the owner:

```sh
cd /Users/ouxianxing/Documents/James-Au-Studio/companion-ios
xcodegen generate
xcodebuild -scheme 'James Au Studio Companion' -sdk iphonesimulator -configuration Debug build
```

Do not add Bilibili credentials to source, `CompanionConfiguration.json`, Xcode project settings, logs, or chat. After a successful local build, prepare the separate developer-enrollment manifest before submitting any Bilibili form or enabling OAuth.
