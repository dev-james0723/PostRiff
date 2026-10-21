// Candidate only. Not compiled, executed, or approved for recording.
// macOS 15+; no package dependencies, permissions requests, UI automation or uploads.
import AppKit
import AVFoundation
import CoreGraphics
import CoreMedia
import Darwin
import Foundation
import ScreenCaptureKit

private enum CaptureFailure: Error {
    case invalidArguments, staleObservation, permissionUnavailable, targetMismatch
    case outputUnavailable, recordingFailed, recordingIncomplete
}

private struct Options {
    let windowID: CGWindowID
    let chromePID: pid_t
    let title: String
    let output: URL

    init(_ arguments: [String]) throws {
        guard arguments.count == 11 else { throw CaptureFailure.invalidArguments }
        var values: [String: String] = [:]
        for index in stride(from: 1, to: arguments.count, by: 2) {
            let key = arguments[index]
            guard ["--window-id", "--chrome-pid", "--title", "--observed-at", "--output"].contains(key),
                  values[key] == nil else { throw CaptureFailure.invalidArguments }
            values[key] = arguments[index + 1]
        }
        guard let id = UInt32(values["--window-id"] ?? ""), id > 0,
              let pid = Int32(values["--chrome-pid"] ?? ""), pid > 0,
              let expectedTitle = values["--title"], !expectedTitle.isEmpty,
              let observedText = values["--observed-at"],
              let observed = ISO8601DateFormatter().date(from: observedText),
              let outputPath = values["--output"], outputPath.hasPrefix("/") else {
            throw CaptureFailure.invalidArguments
        }
        // Require a human/controller's fresh, exact surface observation.
        let age = Date().timeIntervalSince(observed)
        guard age >= 0, age <= 30 else { throw CaptureFailure.staleObservation }
        let allowed = URL(fileURLWithPath:
            "/Users/ouxianxing/Documents/.agent-worktrees/rafii-pinterest-production-prep-20261014/docs/pinterest-production-20261014/standard-access-video",
            isDirectory: true).resolvingSymlinksInPath().standardizedFileURL
        let destination = URL(fileURLWithPath: outputPath).standardizedFileURL
        let parent = destination.deletingLastPathComponent().resolvingSymlinksInPath()
        guard parent.path == allowed.path,
              destination.pathExtension.lowercased() == "mp4",
              !FileManager.default.fileExists(atPath: destination.path) else {
            throw CaptureFailure.outputUnavailable
        }
        windowID = id
        chromePID = pid
        title = expectedTitle
        output = parent.appendingPathComponent(destination.lastPathComponent)
    }
}

@available(macOS 15.0, *)
private final class Observer: NSObject, SCRecordingOutputDelegate, SCStreamDelegate {
    private let lock = NSLock()
    private var started = false
    private var finished = false
    private var failed = false

    func recordingOutputDidStartRecording(_ recordingOutput: SCRecordingOutput) {
        lock.lock(); started = true; lock.unlock()
    }
    func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput) {
        lock.lock(); finished = true; lock.unlock()
    }
    func recordingOutput(_ recordingOutput: SCRecordingOutput, didFailWithError error: Error) {
        lock.lock(); failed = true; lock.unlock()
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        lock.lock(); failed = true; lock.unlock()
    }
    func state() -> (started: Bool, finished: Bool, failed: Bool) {
        lock.lock()
        defer { lock.unlock() }
        return (started, finished, failed)
    }
}

// This reads metadata for the single exact ID. It never captures a display.
private func verifySelectedWindow(_ options: Options) throws {
    guard CGPreflightScreenCaptureAccess(),
          let application = NSRunningApplication(processIdentifier: options.chromePID),
          application.bundleIdentifier == "com.google.Chrome",
          let raw = CGWindowListCopyWindowInfo(
            [.optionIncludingWindow, .excludeDesktopElements], options.windowID),
          let rows = raw as? [[String: Any]],
          let row = rows.first(where: {
              ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == options.windowID
          }),
          (row[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == options.chromePID,
          (row[kCGWindowName as String] as? String) == options.title,
          (row[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue == true else {
        throw CaptureFailure.targetMismatch
    }
}

@available(macOS 15.0, *)
private func record(_ options: Options) async throws {
    guard CGPreflightScreenCaptureAccess() else { throw CaptureFailure.permissionUnavailable }
    try verifySelectedWindow(options)

    // Metadata enumeration is required by Apple's API. No other window metadata is logged.
    let content = try await SCShareableContent.excludingDesktopWindows(
        false, onScreenWindowsOnly: true)
    guard let selected = content.windows.first(where: { $0.windowID == options.windowID }),
          selected.owningApplication?.processID == options.chromePID,
          selected.owningApplication?.bundleIdentifier == "com.google.Chrome",
          selected.title == options.title,
          selected.isOnScreen,
          selected.windowLayer == 0,
          selected.frame.width >= 2, selected.frame.height >= 2 else {
        throw CaptureFailure.targetMismatch
    }
    try verifySelectedWindow(options)

    let parent = options.output.deletingLastPathComponent()
    let staging = parent.appendingPathComponent(".capture-unreviewed-" + UUID().uuidString)
    try FileManager.default.createDirectory(
        at: staging, withIntermediateDirectories: false,
        attributes: [.posixPermissions: 0o700])
    defer { try? FileManager.default.removeItem(at: staging) }
    let temporaryFile = staging.appendingPathComponent("recording.mp4")

    let width = max(2, (Int(min(960, selected.frame.width)) / 2) * 2)
    let height = max(2, (Int(Double(selected.frame.height) * Double(width) / Double(selected.frame.width)) / 2) * 2)
    let configuration = SCStreamConfiguration()
    configuration.width = width
    configuration.height = height
    configuration.minimumFrameInterval = CMTime(value: 1, timescale: 30)
    configuration.showsCursor = false
    configuration.capturesAudio = false
    configuration.captureMicrophone = false
    configuration.ignoreShadowsSingleWindow = true

    // Strict, independent window filter. There is no display or alternative-window fallback.
    let filter = SCContentFilter(desktopIndependentWindow: selected)
    let observer = Observer()
    let stream = SCStream(filter: filter, configuration: configuration, delegate: observer)
    let recordingConfiguration = SCRecordingOutputConfiguration()
    recordingConfiguration.outputURL = temporaryFile
    recordingConfiguration.videoCodecType = .h264
    recordingConfiguration.outputFileType = .mp4
    let recording = SCRecordingOutput(configuration: recordingConfiguration, delegate: observer)
    try stream.addRecordingOutput(recording)

    // Nominal six-second capture leaves two seconds to finalize. A hard process watchdog
    // bounds all possible capture to eight seconds and deletes only this new private staging dir.
    let watchdog = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
    watchdog.setEventHandler {
        try? FileManager.default.removeItem(at: staging)
        FileHandle.standardError.write(Data("ABORT capture hard limit; no deliverable.\n".utf8))
        Darwin.exit(124)
    }
    watchdog.schedule(deadline: .now() + 8)
    watchdog.resume()
    defer { watchdog.cancel() }

    let startedAt = DispatchTime.now().uptimeNanoseconds
    do {
        try verifySelectedWindow(options)
        try await stream.startCapture()
        print("CAPTURE_STARTED exact window only; audio off; output remains unreviewed.")
        while DispatchTime.now().uptimeNanoseconds - startedAt < 6_000_000_000 {
            try verifySelectedWindow(options)
            guard !observer.state().failed else { throw CaptureFailure.recordingFailed }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        try await stream.stopCapture()
        while !observer.state().finished {
            guard !observer.state().failed else { throw CaptureFailure.recordingFailed }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        try verifySelectedWindow(options)
        let result = observer.state()
        let seconds = CMTimeGetSeconds(recording.recordedDuration)
        guard result.started, result.finished, !result.failed,
              seconds.isFinite, seconds > 0, seconds <= 8,
              recording.recordedFileSize > 0,
              !FileManager.default.fileExists(atPath: options.output.path) else {
            throw CaptureFailure.recordingIncomplete
        }
        try FileManager.default.moveItem(at: temporaryFile, to: options.output)
        print("CAPTURE_SAVED_UNREVIEWED fps not yet verified; privacy and ffprobe review required.")
    } catch {
        // The hard watchdog also bounds a stalled stop. Never retry or choose another surface.
        try? await stream.stopCapture()
        throw error
    }
}

@main
private struct StrictWindowRecorder {
    static func main() async {
        do {
            let options = try Options(CommandLine.arguments)
            guard #available(macOS 15.0, *) else {
                throw CaptureFailure.recordingIncomplete
            }
            try await record(options)
        } catch let error as CaptureFailure {
            FileHandle.standardError.write(Data("ABORT \(error); no capture fallback.\n".utf8))
            Darwin.exit(1)
        } catch {
            // Avoid leaking window titles, URLs, account data or arbitrary OS error text.
            let value = error as NSError
            FileHandle.standardError.write(Data("ABORT native operation domain=\(value.domain) code=\(value.code); no fallback.\n".utf8))
            Darwin.exit(1)
        }
    }
}
