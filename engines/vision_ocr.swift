// vision_ocr.swift — macOS 原生 Vision OCR CLI (零依赖, 离线, 支持中英混排)
// 用法: vision_ocr <image_path> [lang1,lang2]
// 编译: swiftc -O -o bin/vision_ocr vision_ocr.swift -framework Vision -framework AppKit
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: vision_ocr <image> [langs]\n".data(using: .utf8)!)
    exit(2)
}

let path = args[1]
guard let img = NSImage(contentsOfFile: path) else {
    FileHandle.standardError.write("cannot open image: \(path)\n".data(using: .utf8)!)
    exit(3)
}

var rect = NSRect(x: 0, y: 0, width: img.size.width, height: img.size.height)
guard let cg = img.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
    FileHandle.standardError.write("cannot decode image\n".data(using: .utf8)!)
    exit(4)
}

let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = true
if args.count >= 3 {
    req.recognitionLanguages = args[2].split(separator: ",").map { String($0) }
} else {
    req.recognitionLanguages = ["zh-Hans", "en-US"]
}

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([req])
} catch {
    FileHandle.standardError.write("vision failed: \(error)\n".data(using: .utf8)!)
    exit(5)
}

if let results = req.results {
    for obs in results {
        if let top = obs.topCandidates(1).first {
            print(top.string)
        }
    }
}
