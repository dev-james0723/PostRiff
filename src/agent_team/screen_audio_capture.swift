// macOS-only capture control helper. Built in cloud CI; no microphone or upload.
import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreGraphics
import CoreMedia

final class RecordingDelegate: NSObject, SCRecordingOutputDelegate {
    var finished = false
    var failure: Error?
    func recordingOutputDidFinishRecording(_ output: SCRecordingOutput) { finished = true }
    func recordingOutput(_ output: SCRecordingOutput, didFailWithError error: Error) {
        failure = error; finished = true
    }
}

enum CaptureFailure: Error { case invalidArguments, permissionRequired, recordingFailed, invalidTracks, playbackTimeout }

@main struct ScreenAudioCapture {
    static func emit(_ value: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }
    static func inspect(_ url: URL) async throws -> [String: Any] {
        let asset = AVURLAsset(url: url)
        let video = try await asset.loadTracks(withMediaType: .video)
        let audio = try await asset.loadTracks(withMediaType: .audio)
        let duration = try await asset.load(.duration).seconds
        guard video.count == 1, audio.count == 1, duration > 0 else { throw CaptureFailure.invalidTracks }
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
        do {
            let args = CommandLine.arguments
            guard args.count >= 3 else { throw CaptureFailure.invalidArguments }
            let mode = args[1], url = URL(fileURLWithPath: args[2])
            if mode == "verify" {
                var metadata = try await inspect(url)
                let item = AVPlayerItem(url: url), player = AVPlayer()
                var ended = false
                let observer = NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: nil) { _ in ended = true }
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
            guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else { throw CaptureFailure.permissionRequired }
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
            let start = Date(); try await stream.startCapture()
            try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            try await stream.stopCapture()
            let deadline = Date().addingTimeInterval(15)
            while !delegate.finished && Date() < deadline { try await Task.sleep(nanoseconds: 50_000_000) }
            guard delegate.finished, delegate.failure == nil else { throw CaptureFailure.recordingFailed }
            var metadata = try await inspect(url)
            metadata["executionState"] = "captured_screen_and_system_audio"
            metadata["startedAt"] = ISO8601DateFormatter().string(from: start)
            metadata["finishedAt"] = ISO8601DateFormatter().string(from: Date())
            metadata["screenSamplingFps"] = 1; metadata["width"] = configuration.width; metadata["height"] = configuration.height
            try emit(metadata)
        } catch {
            let reason = error is CaptureFailure && String(describing: error) == "permissionRequired" ? "macos_screen_system_audio_permission_required" : "native_capture_or_playback_failed"
            try? emit(["executionState": "failed", "reason": reason, "errorType": String(describing: type(of: error))])
            exit(3)
        }
    }
}
