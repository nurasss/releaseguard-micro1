import AVFoundation
import CoreGraphics
import CoreText
import CoreVideo
import Foundation

struct Slide {
    let title: String
    let lines: [String]
    let accent: CGColor
}

let arguments = CommandLine.arguments
let outputPath = arguments.count > 1 ? arguments[1] : "submission/video/releaseguard_demo.mp4"
let outputURL = URL(fileURLWithPath: outputPath)
let outputDirectory = outputURL.deletingLastPathComponent()
try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
if FileManager.default.fileExists(atPath: outputURL.path) {
    try FileManager.default.removeItem(at: outputURL)
}

let width = 1280
let height = 720
let fps: Int32 = 24
let secondsPerSlide = 5
let slides = [
    Slide(
        title: "ReleaseGuard",
        lines: [
            "Submission demo — read-only release readiness auditing",
            "Public repository snapshot → evidence → decision",
        ],
        accent: CGColor(red: 0.22, green: 0.78, blue: 0.78, alpha: 1.0)
    ),
    Slide(
        title: "Security boundary",
        lines: [
            "Public repositories only; private targets stop before content access",
            "Redaction happens before evidence, report, trajectory, and SQLite persistence",
            "Secret-file bodies are omitted; hashes and structure remain",
        ],
        accent: CGColor(red: 0.98, green: 0.55, blue: 0.30, alpha: 1.0)
    ),
    Slide(
        title: "Frozen 12-case experiment",
        lines: [
            "Baseline CBR: 0.4444",
            "Final CBR: 1.0000  |  improvement: +55.56 percentage points",
            "Critical evidence: 100%  |  unsupported critical: 0  |  run rate: 100%",
        ],
        accent: CGColor(red: 0.45, green: 0.82, blue: 0.38, alpha: 1.0)
    ),
    Slide(
        title: "Case 12 and submission",
        lines: [
            "Analyzer identifies the excluded integration-test path",
            "Verifier confirms the evidence; policy returns NO-GO",
            "Curated trajectories, baseline/final, ablations, and ZIP are verified",
        ],
        accent: CGColor(red: 0.68, green: 0.50, blue: 0.95, alpha: 1.0)
    ),
]

let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: 2_000_000,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
    ],
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let pixelAttributes: [String: Any] = [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
    kCVPixelBufferCGImageCompatibilityKey as String: true,
    kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
]
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: pixelAttributes
)
writer.add(input)
writer.startWriting()
writer.startSession(atSourceTime: .zero)

func drawText(_ context: CGContext, _ text: String, x: CGFloat, y: CGFloat, size: CGFloat, color: CGColor, bold: Bool = false) {
    let fontName = bold ? "Helvetica-Bold" : "Helvetica"
    let font = CTFontCreateWithName(fontName as CFString, size, nil)
    let attributes: [NSAttributedString.Key: Any] = [
        NSAttributedString.Key(rawValue: kCTFontAttributeName as String): font,
        NSAttributedString.Key(rawValue: kCTForegroundColorAttributeName as String): color,
    ]
    let attributed = NSAttributedString(string: text, attributes: attributes)
    let line = CTLineCreateWithAttributedString(attributed)
    context.textPosition = CGPoint(x: x, y: y)
    CTLineDraw(line, context)
}

func makeBuffer(slide: Slide, progress: CGFloat) -> CVPixelBuffer? {
    var optionalBuffer: CVPixelBuffer?
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        width,
        height,
        kCVPixelFormatType_32ARGB,
        pixelAttributes as CFDictionary,
        &optionalBuffer
    )
    guard status == kCVReturnSuccess, let buffer = optionalBuffer else { return nil }
    CVPixelBufferLockBaseAddress(buffer, [])
    defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
    guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
    let bytesPerRow = CVPixelBufferGetBytesPerRow(buffer)
    guard let context = CGContext(
        data: base,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: bytesPerRow,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
    ) else { return nil }

    context.setFillColor(CGColor(red: 0.045, green: 0.06, blue: 0.10, alpha: 1.0))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.setFillColor(slide.accent)
    context.fill(CGRect(x: 0, y: 0, width: 14, height: height))
    drawText(context, slide.title, x: 76, y: 560, size: 52, color: .white, bold: true)

    var y: CGFloat = 455
    for line in slide.lines {
        context.setFillColor(slide.accent)
        context.fill(CGRect(x: 78, y: y + 5, width: 12, height: 12))
        drawText(context, line, x: 112, y: y, size: 26, color: CGColor(red: 0.88, green: 0.91, blue: 0.95, alpha: 1.0))
        y -= 66
    }

    let barWidth = CGFloat(width - 152) * progress
    context.setFillColor(CGColor(red: 0.18, green: 0.22, blue: 0.30, alpha: 1.0))
    context.fill(CGRect(x: 76, y: 52, width: CGFloat(width - 152), height: 5))
    context.setFillColor(slide.accent)
    context.fill(CGRect(x: 76, y: 52, width: barWidth, height: 5))
    return buffer
}

let totalFrames = Int(fps) * secondsPerSlide * slides.count
for frame in 0..<totalFrames {
    while !input.isReadyForMoreMediaData {
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.001))
    }
    let slideIndex = min(frame / (Int(fps) * secondsPerSlide), slides.count - 1)
    let slideFrame = frame % (Int(fps) * secondsPerSlide)
    let progress = CGFloat(slideFrame + 1) / CGFloat(Int(fps) * secondsPerSlide)
    guard let buffer = makeBuffer(slide: slides[slideIndex], progress: progress) else {
        throw NSError(domain: "ReleaseGuardVideo", code: 1, userInfo: [NSLocalizedDescriptionKey: "Could not allocate pixel buffer"])
    }
    let time = CMTime(value: CMTimeValue(frame), timescale: fps)
    if !adaptor.append(buffer, withPresentationTime: time) {
        throw writer.error ?? NSError(domain: "ReleaseGuardVideo", code: 2, userInfo: [NSLocalizedDescriptionKey: "Could not append video frame"])
    }
}

input.markAsFinished()
let finished = DispatchSemaphore(value: 0)
writer.finishWriting { finished.signal() }
finished.wait()
if writer.status != .completed {
    throw writer.error ?? NSError(domain: "ReleaseGuardVideo", code: 3, userInfo: [NSLocalizedDescriptionKey: "Video writer did not complete"])
}
print("Wrote \(outputURL.path) (\(slides.count * secondsPerSlide)s)")
