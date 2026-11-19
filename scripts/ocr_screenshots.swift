// ocr_screenshots.swift — OCR all images in docs/img via macOS Vision framework.
// Usage: swift ocr_screenshots.swift <dir> [output.md]
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2 else {
    print("usage: swift ocr_screenshots.swift <dir> [output.md]")
    exit(1)
}
let dir = URL(fileURLWithPath: args[1])
let fm = FileManager.default
let outPath = args.count >= 3 ? args[2] : nil

var files: [String] = []
if let entries = try? fm.contentsOfDirectory(atPath: dir.path) {
    for e in entries where e.lowercased().hasSuffix(".jpeg") || e.lowercased().hasSuffix(".jpg") || e.lowercased().hasSuffix(".png") {
        if e.hasPrefix("IMG_14") { files.append(e) }
    }
}
files.sort()

var md = "# OCR 结果（docs/img）\n\n"

for f in files {
    let url = dir.appendingPathComponent(f)
    guard let img = NSImage(contentsOf: url),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        md += "## \(f)\n\n[读取失败]\n\n"
        continue
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do {
        try handler.perform([request])
        var lines: [(Double, String)] = []
        for obs in request.results ?? [] {
            guard let cand = obs.topCandidates(1).first else { continue }
            let b = obs.boundingBox
            let y = 1.0 - b.midY // top-down order
            lines.append((y, cand.string))
        }
        lines.sort { $0.0 < $1.0 }
        md += "## \(f)\n\n```\n"
        for (_, s) in lines { md += s + "\n" }
        md += "```\n\n"
    } catch {
        md += "## \(f)\n\n[OCR 失败: \(error)]\n\n"
    }
}

if let out = outPath {
    try? md.write(toFile: out, atomically: true, encoding: .utf8)
    print("written: \(out)  (\(files.count) files)")
} else {
    print(md)
}
