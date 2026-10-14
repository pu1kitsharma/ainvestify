// Local source transcription only. It does not infer claims or approve figures.
import Foundation
import Vision
import ImageIO
import Darwin

var operationStage = "request"

struct ImageInput: Decodable {
    let id: String
    let path: String
    let sha256: String
}
struct OCRInput: Decodable {
    let contract: String
    let images: [ImageInput]
    let languages: [String]
}
struct Observation: Encodable {
    let text: String
    let confidence: Float
    let bbox: [Double]
}
struct ImageOutput: Encodable {
    let id: String
    let image_sha256: String
    let observations: [Observation]
}
struct OCROutput: Encodable {
    let contract: String
    let engine: String
    let language_correction: Bool
    let coordinate_system: String
    let images: [ImageOutput]
}

do {
    guard CommandLine.arguments.count == 3 else {
        throw NSError(domain: "privateOCR", code: 1)
    }
    let request = try JSONDecoder().decode(OCRInput.self,
        from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
    guard request.contract == "private-vision-ocr-v1",
          !request.images.isEmpty, request.images.count <= 120,
          !request.languages.isEmpty, request.languages.count <= 4 else {
        throw NSError(domain: "privateOCR", code: 2)
    }
    var outputs: [ImageOutput] = []
    for image in request.images {
        operationStage = "load_raster"
        let url = URL(fileURLWithPath: image.path)
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let raster = CGImageSourceCreateImageAtIndex(source, 0, nil),
              raster.width * raster.height <= 12000000 else {
            throw NSError(domain: "privateOCR", code: 3)
        }
        let task = VNRecognizeTextRequest()
        task.recognitionLevel = .accurate
        // No Metal/ANE context or cache is required by the private boundary.
        task.usesCPUOnly = true
        task.usesLanguageCorrection = false
        task.recognitionLanguages = request.languages
        task.minimumTextHeight = 0.004
        operationStage = "recognize"
        try VNImageRequestHandler(cgImage: raster, options: [:]).perform([task])
        let rows: [Observation] = (task.results ?? []).compactMap { result in
            guard let candidate = result.topCandidates(1).first else { return nil }
            let rect = result.boundingBox
            return Observation(text: candidate.string, confidence: candidate.confidence,
                bbox: [Double(rect.minX), Double(rect.minY), Double(rect.width), Double(rect.height)])
        }
        outputs.append(ImageOutput(id: image.id, image_sha256: image.sha256, observations: rows))
    }
    let output = OCROutput(contract: request.contract, engine: "AppleVision-VNRecognizeTextRequest",
        language_correction: false, coordinate_system: "normalized-bottom-left",
        images: outputs)
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    operationStage = "write_result"
    let data = try encoder.encode(output)
    guard let stream = fopen(CommandLine.arguments[2], "wb") else {
        throw NSError(domain: "privateOCR", code: 4)
    }
    let count = data.withUnsafeBytes { fwrite($0.baseAddress, 1, $0.count, stream) }
    fclose(stream)
    guard count == data.count else { throw NSError(domain: "privateOCR", code: 5) }
} catch {
    // Source text and paths belong only to private output files, never stdout.
    let failure = error as NSError
    if CommandLine.arguments.count == 3 {
        let diagnostic: [String: Any] = ["stage": operationStage, "domain": failure.domain, "code": failure.code,
            "description": failure.localizedDescription, "details": String(reflecting: failure)]
        if let data = try? JSONSerialization.data(withJSONObject: diagnostic, options: [.sortedKeys]) {
            if let stream = fopen(CommandLine.arguments[2] + ".error.json", "wb") {
                data.withUnsafeBytes { _ = fwrite($0.baseAddress, 1, $0.count, stream) }
                fclose(stream)
            }
        }
    }
    fputs("private_local_ocr_failed \(operationStage) \(failure.domain) \(failure.code)\n", stderr)
    exit(1)
}
