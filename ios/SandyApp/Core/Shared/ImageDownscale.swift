import Foundation
import ImageIO
import UniformTypeIdentifiers

/// A photo made small enough to send, straight from its file bytes: ImageIO decodes only
/// what the smaller size needs (a full decode of a 48 MP photo is ~190 MB), and the
/// photo's orientation is applied.
enum ImageDownscale {
    /// JPEG at most `maxPixel` on its long side (never enlarged), or nil when `data` is not
    /// an image.
    static func jpeg(from data: Data, maxPixel: Int, quality: Double = 0.85) -> Data? {
        let noCache = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, noCache),
              CGImageSourceGetCount(source) > 0 else { return nil }
        let thumb: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixel,
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, thumb as CFDictionary)
        else { return nil }
        let out = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil)
        else { return nil }
        CGImageDestinationAddImage(dest, image,
                                   [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        return CGImageDestinationFinalize(dest) ? out as Data : nil
    }
}
