// macOS-only capture control helper. Built in cloud CI; no microphone or upload.
import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreGraphics
import CoreMedia

final class RecordingDelegate: NSObject, SCRecordingOutputDelegate {
    private let lock = NSLock()
    private var complete = false
    private var failed: Error?
    var finished: Bool { lock.lock(); defer { lock.unlock() }; return complete }
    var failure: Error? { lock.lock(); defer { lock.unlock() }; return failed }
    func recordingOutputDidFinishRecording(_ output: SCRecordingOutput) {
        lock.lock(); defer { lock.unlock() }; complete = true
    }
    func recordingOutput(_ output: SCRecordingOutput, didFailWithError error: Error) {
        lock.lock(); defer { lock.unlock() }; failed = error; complete = true
    }
}

enum CaptureFailure: Error { case invalidArguments, permissionRequired, recordingFailed, invalidTracks, playbackTimeout }

@main struct ScreenAudioCapture {
    static func emit(_ value: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }
    static func inspect(_ url: URL, requireAudio: Bool = true) async throws -> [String: Any] {
        let asset = AVURLAsset(url: url)
        let video = try await asset.loadTracks(withMediaType: .video)
        let audio = try await asset.loadTracks(withMediaType: .audio)
        let duration = try await asset.load(.duration).seconds
        guard video.count == 1, audio.count <= 1, duration > 0,
              !requireAudio || audio.count == 1 else { throw CaptureFailure.invalidTracks }
        if audio.isEmpty {
            return ["videoTracks": 1, "systemAudioTracks": 0, "durationSeconds": duration,
                    "audioSamples": 0, "nonSilentSystemAudio": false, "microphoneCaptured": false,
                    "audioObservation": "no_recorded_system_audio_samples"]
        }
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: audio[0], outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM, AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false])
        reader.add(output)
        guard reader.startReading() else { throw CaptureFailure.recordingFailed }
        var count: Int64 = 0; var peak = 0; var squares = 0.0
        while let sample = output.copyNextSampleBuffer() {
            guard let block = CMSampleBufferGetDataBuffer(sample) else { continue }
            let length = CMBlockBufferGetDataLength(block)
            var bytes = [UInt8](repeating: 0, count: length)
            guard CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: length, destination: &bytes) == kCMBlockBufferNoErr else { throw CaptureFailure.recordingFailed }
            for i in stride(from: 0, to: length - 1, by: 2) {
                let value = Int(Int16(bitPattern: UInt16(bytes[i]) | UInt16(bytes[i+1]) << 8))
                peak = max(peak, abs(value)); squares += Double(value) * Double(value); count += 1
            }
        }
        guard reader.status == .completed, count > 0 else { throw CaptureFailure.invalidTracks }
        return ["videoTracks": video.count, "systemAudioTracks": audio.count, "durationSeconds": duration,
                "audioSamples": count, "peakPcm16": peak, "rmsPcm16": sqrt(squares / Double(count)),
                "nonSilentSystemAudio": peak > 0, "microphoneCaptured": false]
    }
    static func main() async {
        var phase = "arguments"
        do {
            let args = CommandLine.arguments
            guard args.count >= 3 else { throw CaptureFailure.invalidArguments }
            let mode = args[1], url = URL(fileURLWithPath: args[2])
            if mode == "verify" {
                phase = "inspect_for_playback"
                var metadata = try await inspect(url)
                let item = AVPlayerItem(url: url), player = AVPlayer()
                var ended = false
                let observer = NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: nil) { _ in ended = true }
                phase = "playback"
                player.replaceCurrentItem(with: item); player.play()
                let deadline = Date().addingTimeInterval((metadata["durationSeconds"] as! Double) + 20)
                while !ended && Date() < deadline { try await Task.sleep(nanoseconds: 100_000_000) }
                NotificationCenter.default.removeObserver(observer)
                let position = player.currentTime().seconds; player.pause()
                guard ended && position > 0 else { throw CaptureFailure.playbackTimeout }
                metadata["playbackEnded"] = true; metadata["playbackPositionSeconds"] = position
                metadata["executionState"] = "native_playback_verified"
                try emit(metadata); return
            }
            guard mode == "capture", args.count == 4, let seconds = Double(args[3]), 1...120 ~= seconds else { throw CaptureFailure.invalidArguments }
            phase = "screen_audio_permission"
            guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else { throw CaptureFailure.permissionRequired }
            phase = "shareable_content"
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.first else { throw CaptureFailure.recordingFailed }
            let filter = SCContentFilter(display: display, excludingWindows: [])
            let configuration = SCStreamConfiguration()
            configuration.width = 640
            configuration.height = max(2, (Int(Double(display.height) / Double(display.width) * 640) / 2) * 2)
            configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            configuration.queueDepth = 3; configuration.showsCursor = true
            configuration.capturesAudio = true; configuration.sampleRate = 48000; configuration.channelCount = 2
            configuration.excludesCurrentProcessAudio = false
            let recordingConfig = SCRecordingOutputConfiguration()
            recordingConfig.outputURL = url; recordingConfig.videoCodecType = .h264; recordingConfig.outputFileType = .mp4
            let delegate = RecordingDelegate()
            let output = SCRecordingOutput(configuration: recordingConfig, delegate: delegate)
            let stream = SCStream(filter: filter, configuration: configuration, delegate: nil)
            try stream.addRecordingOutput(output)
            phase = "start_capture"
            let start = Date(); try await stream.startCapture()
            phase = "recording"
            try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            phase = "stop_capture"
            try await stream.stopCapture()
            phase = "recording_finalization"
            let deadline = Date().addingTimeInterval(15)
            while !delegate.finished && Date() < deadline { try await Task.sleep(nanoseconds: 50_000_000) }
            if let failure = delegate.failure { throw failure }
            guard delegate.finished else { throw CaptureFailure.recordingFailed }
            phase = "inspect_recorded_tracks"
            var metadata = try await inspect(url, requireAudio: false)
            metadata["executionState"] = (metadata["systemAudioTracks"] as! Int) == 1
                ? "captured_screen_and_system_audio" : "captured_screen_system_audio_unobserved"
            metadata["systemAudioRequested"] = true
            metadata["startedAt"] = ISO8601DateFormatter().string(from: start)
            metadata["finishedAt"] = ISO8601DateFormatter().string(from: Date())
            metadata["screenSamplingFps"] = 1; metadata["width"] = configuration.width; metadata["height"] = configuration.height
            try emit(metadata)
        } catch {
            let reason = error is CaptureFailure && String(describing: error) == "permissionRequired" ? "macos_screen_system_audio_permission_required" : "native_capture_or_playback_failed"
            let systemError = error as NSError
            // Fixed phase and numeric system error only; no private paths or userInfo.
            try? emit(["executionState": "failed", "reason": reason, "phase": phase,
                       "errorType": String(describing: type(of: error)), "errorCode": systemError.code,
                       "captureFailure": error is CaptureFailure ? String(describing: error) : "system_error"])
            exit(3)
        }
    }
}
