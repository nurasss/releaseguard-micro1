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
let secondsPerSlide = 10
let slides = [
    Slide(
        title: "ReleaseGuard",
        lines: [
            "SUBMISSION WALKTHROUGH / 01",
            "Persona: Tech Lead or Release Engineer",
            "Bottleneck: release evidence is scattered across CI, tests, builds, and docs",
            "Value: a redacted, evidence-backed GO / REVIEW / NO-GO in minutes",
            "Scope: read-only public repository audit, bound to an immutable commit SHA",
        ],
        accent: CGColor(red: 0.22, green: 0.78, blue: 0.78, alpha: 1.0)
    ),
    Slide(
        title: "The fair baseline",
        lines: [
            "SUBMISSION WALKTHROUGH / 02",
            "$ make baseline",
            "12 identical frozen cases / same output contract",
            "B1: one direct general-purpose path, no checklist or Verifier",
            "CBR 0.4444   decision accuracy 0.4167   runtime 0.449s",
            "OfflineFixtureLLM simulation, not official Gemini",
        ],
        accent: CGColor(red: 0.98, green: 0.55, blue: 0.30, alpha: 1.0)
    ),
    Slide(
        title: "What the baseline misses",
        lines: [
            "SUBMISSION WALKTHROUGH / 03",
            "case_05  required production environment setting -> missed",
            "case_07  release ref and manifest version conflict -> missed",
            "case_09  release workflow excludes the release branch -> missed",
            "case_12  green CI does not exercise the critical integration path",
            "Failure mode: no structured coverage across cross-file signals",
        ],
        accent: CGColor(red: 0.95, green: 0.35, blue: 0.35, alpha: 1.0)
    ),
    Slide(
        title: "Final workflow",
        lines: [
            "SUBMISSION WALKTHROUGH / 04",
            "$ make evaluate",
            "resolve SHA -> snapshot -> deterministic checks",
            "AuditPlan -> Analyzer -> Verifier falsification",
            "evidence IDs -> policy -> JSON + Markdown + trajectory",
            "All 12 fixture runs completed successfully",
        ],
        accent: CGColor(red: 0.68, green: 0.50, blue: 0.95, alpha: 1.0)
    ),
    Slide(
        title: "Realistic execution: case 12",
        lines: [
            "SUBMISSION WALKTHROUGH / 05",
            "$ make demo CASE=case_12",
            "snapshot: immutable fixture SHA / CI conclusion: success",
            "Analyzer: integration tests are not run for the release path",
            "Verifier: confirms the cited workflow and test evidence",
            "Policy: NO-GO | report.json + report.md + snapshot.json saved",
        ],
        accent: CGColor(red: 0.68, green: 0.50, blue: 0.95, alpha: 1.0)
    ),
    Slide(
        title: "Evidence before persistence",
        lines: [
            "SUBMISSION WALKTHROUGH / 06",
            "read_file(.env) -> [REDACTED: secret file contents omitted]",
            "EvidenceStore -> redacted payload -> SQLite/report/trajectory",
            "private repository -> reject before ref or content access",
            "critical/high finding -> evidence IDs -> independent falsification",
            "No raw secret body is shipped in report.json or SQLite",
        ],
        accent: CGColor(red: 0.98, green: 0.55, blue: 0.30, alpha: 1.0)
    ),
    Slide(
        title: "Experiments that earned their place",
        lines: [
            "SUBMISSION WALKTHROUGH / 07",
            "Verifier ON CBR 1.0000 | OFF 1.0000 -> no lift on frozen cases",
            "Evidence ON/OFF -> same metrics; adversarial cases are still needed",
            "No deterministic checks -> CBR 0.0000 / decision accuracy 0.1667",
            "It5 CI + Security + Test subagents -> CBR 0.5556 -> REMOVE",
            "More agents are not a substitute for an evidence boundary",
        ],
        accent: CGColor(red: 0.68, green: 0.50, blue: 0.95, alpha: 1.0)
    ),
    Slide(
        title: "Measured result and boundary",
        lines: [
            "SUBMISSION WALKTHROUGH / 08",
            "OFFLINE FIXTURE SIMULATION / same frozen 12 cases",
            "B1 CBR 0.4444 -> Final CBR 1.0000 (+55.56 pp)",
            "Final: precision 1.0000 / critical evidence 100% / unsupported 0",
            "Final: successful run rate 100% / fixture cost $0.0000",
            "Official LLM baseline + final: UNAVAILABLE after provider HTTP 429",
        ],
        accent: CGColor(red: 0.45, green: 0.82, blue: 0.38, alpha: 1.0)
    ),
    Slide(
        title: "Reproduce and package",
        lines: [
            "SUBMISSION WALKTHROUGH / 09",
            "$ make setup && make test",
            "$ make baseline && make evaluate && make ablations",
            "$ make demo CASE=case_12",
            "$ .venv/bin/python scripts/package_submission.py",
            "$ .venv/bin/python scripts/verify_submission_zip.py dist/releaseguard_submission.zip",
        ],
        accent: CGColor(red: 0.22, green: 0.78, blue: 0.78, alpha: 1.0)
    ),
    Slide(
        title: "ReleaseGuard in one line",
        lines: [
            "SUBMISSION WALKTHROUGH / 10",
            "The user gets a release decision they can inspect and challenge",
            "The system does not deploy, push, merge, or access private repositories",
            "Analyzer proposes; Verifier tries to falsify; policy stays deterministic",
            "Offline numbers are labelled simulation until a live LLM pair exists",
            "Evidence is the boundary. Human approval remains the release gate.",
        ],
        accent: CGColor(red: 0.22, green: 0.78, blue: 0.78, alpha: 1.0)
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

func lineColor(_ line: String, accent: CGColor) -> CGColor {
    if line.hasPrefix("$") { return accent }
    if line.contains("UNAVAILABLE") || line.contains("missed") || line.contains("REMOVE") {
        return CGColor(red: 1.0, green: 0.52, blue: 0.40, alpha: 1.0)
    }
    if line.contains("100%") || line.contains("successfully") || line.contains("NO-GO") {
        return CGColor(red: 0.55, green: 0.92, blue: 0.55, alpha: 1.0)
    }
    return CGColor(red: 0.86, green: 0.90, blue: 0.95, alpha: 1.0)
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

    let background = CGColor(red: 0.035, green: 0.048, blue: 0.078, alpha: 1.0)
    let panel = CGColor(red: 0.055, green: 0.075, blue: 0.115, alpha: 1.0)
    let muted = CGColor(red: 0.42, green: 0.50, blue: 0.62, alpha: 1.0)
    context.setFillColor(background)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.setFillColor(slide.accent)
    context.fill(CGRect(x: 0, y: 0, width: 14, height: height))
    drawText(context, "RELEASEGUARD  /  AGENTIC WORKFLOWS HACKATHON", x: 76, y: 674, size: 17, color: muted, bold: true)
    drawText(context, slide.title, x: 76, y: 604, size: 48, color: .white, bold: true)

    let panelRect = CGRect(x: 68, y: 142, width: 1144, height: 390)
    context.setFillColor(panel)
    context.fill(panelRect)
    context.setFillColor(CGColor(red: 0.10, green: 0.13, blue: 0.19, alpha: 1.0))
    context.fill(CGRect(x: panelRect.minX, y: panelRect.maxY - 32, width: panelRect.width, height: 32))
    for (index, color) in [
        CGColor(red: 0.95, green: 0.34, blue: 0.31, alpha: 1.0),
        CGColor(red: 0.96, green: 0.72, blue: 0.25, alpha: 1.0),
        CGColor(red: 0.32, green: 0.78, blue: 0.44, alpha: 1.0),
    ].enumerated() {
        context.setFillColor(color)
        context.fillEllipse(in: CGRect(x: panelRect.minX + 18 + CGFloat(index) * 22, y: panelRect.maxY - 22, width: 10, height: 10))
    }
    drawText(context, "captured run notes", x: panelRect.minX + 98, y: panelRect.maxY - 24, size: 14, color: muted)

    let reveal = min(max(progress * 1.35, 0.0), 1.0)
    let visibleCount = min(slide.lines.count, max(0, Int(reveal * CGFloat(slide.lines.count + 1))))
    var y: CGFloat = panelRect.maxY - 76
    for (index, line) in slide.lines.enumerated() {
        if index >= visibleCount { break }
        drawText(context, ">", x: panelRect.minX + 22, y: y, size: 22, color: slide.accent, bold: true)
        drawText(context, line, x: panelRect.minX + 52, y: y, size: 21, color: lineColor(line, accent: slide.accent), bold: line.hasPrefix("$"))
        y -= 43
    }

    let barWidth = CGFloat(width - 152) * progress
    context.setFillColor(CGColor(red: 0.18, green: 0.22, blue: 0.30, alpha: 1.0))
    context.fill(CGRect(x: 76, y: 52, width: CGFloat(width - 152), height: 5))
    context.setFillColor(slide.accent)
    context.fill(CGRect(x: 76, y: 52, width: barWidth, height: 5))
    drawText(context, String(format: "SCENE %02d / %02d", slides.firstIndex(where: { $0.title == slide.title }).map { $0 + 1 } ?? 0, slides.count), x: 76, y: 28, size: 14, color: muted, bold: true)
    drawText(context, "simulation scope is labelled; no credentials or secret bodies", x: 694, y: 28, size: 14, color: muted)
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
