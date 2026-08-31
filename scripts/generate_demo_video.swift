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
        title: "ReleaseGuard Overview",
        lines: [
            "SUBMISSION WALKTHROUGH / 01",
            "Persona: Tech Lead or Release Engineer cutting a production release",
            "Bottleneck: release signals scattered across CI, tests, locks, migrations & workflows",
            "Value: evidence-backed GO / REVIEW / NO-GO report bound to immutable commit SHA",
            "Architecture: Deterministic Checks -> Analyzer -> Verifier -> Decision Policy",
        ],
        accent: CGColor(red: 0.22, green: 0.78, blue: 0.78, alpha: 1.0)
    ),
    Slide(
        title: "Live Execution: Case 12",
        lines: [
            "SUBMISSION WALKTHROUGH / 02",
            "$ releaseguard audit --case eval/cases/case_12 --mode final",
            "Target: https://github.com/eval/case_12 | Requested ref: v4.0.0",
            "Resolved immutable commit SHA: fc00d35fc5c809b82e27fcd01df6e714c3efa9a1",
            "Provider: live xAI grok-4.6 | Prompt: final-v2 | Mode: final (50.8s runtime)",
        ],
        accent: CGColor(red: 0.98, green: 0.55, blue: 0.30, alpha: 1.0)
    ),
    Slide(
        title: "Deterministic Pre-flight",
        lines: [
            "SUBMISSION WALKTHROUGH / 03",
            "DC-01 Test execution [WARN]: 6 tests found, test report accounts for only 4",
            "DC-02 CI workflow [PASS]: Found .github/workflows/ci.yml configured for v4.0.0",
            "DC-04 CI status [PASS]: Latest recorded CI run for v4.0.0 is 'success'",
            "DC-05 Release version [PASS]: pyproject.toml '4.0.0' matches requested tag",
            "DC-10 Secret scan [PASS]: 0 secrets detected across 11 scanned text files",
        ],
        accent: CGColor(red: 0.95, green: 0.35, blue: 0.35, alpha: 1.0)
    ),
    Slide(
        title: "Analyzer Phase: Finding F-001",
        lines: [
            "SUBMISSION WALKTHROUGH / 04",
            "Tool call: read_file('.github/workflows/ci.yml') -> Evidence E-014",
            "Tool call: read_file('tests/test_payment_gateway_integration.py') -> Evidence E-017",
            "Finding F-001 (HIGH): CI runs pytest -v -m 'not integration', which excludes",
            "the two integration tests in tests/test_payment_gateway_integration.py",
            "Evidence: E-001 (test report), E-014 (ci.yml), E-017 (integration tests)",
        ],
        accent: CGColor(red: 0.68, green: 0.50, blue: 0.95, alpha: 1.0)
    ),
    Slide(
        title: "Verifier: Falsification Attempt",
        lines: [
            "SUBMISSION WALKTHROUGH / 05",
            "Routing: candidate F-001 sent to independent Verifier agent to search refutations",
            "Verifier queries workflow configs: checks for secondary/release test jobs",
            "Result: No overriding job found; claim verified against immutable tree",
            "Verification status: CONFIRMED | Confidence: 0.95",
        ],
        accent: CGColor(red: 0.68, green: 0.50, blue: 0.95, alpha: 1.0)
    ),
    Slide(
        title: "Audit Report: runs/<id>/report.md",
        lines: [
            "SUBMISSION WALKTHROUGH / 06",
            "Final Decision: REVIEW (0 critical, 1 confirmed high-risk blocker)",
            "Confirmed finding: F-001 integration tests excluded from CI on release ref",
            "Action: Run integration tests in a required CI job before shipping v4.0.0",
            "Artifacts persisted: report.md, report.json, snapshot.json, releaseguard.sqlite3",
        ],
        accent: CGColor(red: 0.98, green: 0.55, blue: 0.30, alpha: 1.0)
    ),
    Slide(
        title: "Security Redaction & Trajectory",
        lines: [
            "SUBMISSION WALKTHROUGH / 07",
            "Inspection: trajectories/<id>.jsonl (Analyzer + Verifier steps logged)",
            "Security: .env & secret bodies omitted; only structural hashes persisted",
            "Evidence integrity: every finding references immutable SHA fc00d35... evidence",
            "Read-only safety: GET-only GitHub adapter; private repos rejected",
        ],
        accent: CGColor(red: 0.98, green: 0.55, blue: 0.30, alpha: 1.0)
    ),
    Slide(
        title: "Live Results: Grok-4.6 vs B1",
        lines: [
            "SUBMISSION WALKTHROUGH / 08",
            "Critical Blocker Recall (CBR): 0.7778 -> 0.8889 (+11.11 percentage points)",
            "Precision: 0.2812 -> 0.4762 (+19.50 percentage points; held-out +14.42 pp)",
            "Development Decision Accuracy: 0.5000 -> 1.0000 (+50.00 pp, perfect 8/8)",
            "Critical Evidence Coverage: 100.0% (0 unsupported critical claims)",
        ],
        accent: CGColor(red: 0.45, green: 0.82, blue: 0.38, alpha: 1.0)
    ),
    Slide(
        title: "Live Verifier Ablation: ON vs OFF",
        lines: [
            "SUBMISSION WALKTHROUGH / 09",
            "Full 12-case live ablation: Verifier ON vs Verifier OFF (no_verifier)",
            "Zero quality delta: CBR 0.8889 = 0.8889 | Decision Accuracy 0.7500 = 0.7500",
            "False positive count: 11 (ON) vs 11 (OFF) | Verifier confirmed 21/21 candidates",
            "Overhead: +49.5% runtime (758.6s vs 507.4s) and +79.5% API cost ($1.18 vs $0.66)",
            "Quantitative negative result: Precision gain belongs to upstream It9 rubric",
        ],
        accent: CGColor(red: 0.68, green: 0.50, blue: 0.95, alpha: 1.0)
    ),
    Slide(
        title: "Key Takeaways & Governance",
        lines: [
            "SUBMISSION WALKTHROUGH / 10",
            "The valuable unit is a trustworthy evidence boundary, not extra agent layers",
            "Honest benchmark governance: we publish measured negative results openly",
            "Full reproduction: $ make setup && make test && make baseline && make evaluate",
            "ReleaseGuard: human Tech Lead retains full ownership with verified evidence",
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
