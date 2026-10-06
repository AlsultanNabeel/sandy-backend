import XCTest
import UIKit
@testable import SandyApp

/// A photo for the album is made at most 2048 px on its long side before upload: a
/// full-size iPhone photo was sent whole and refused past the server's 8 MB.
final class ImageDownscaleTests: XCTestCase {
    private func bigPNG(width: Int, height: Int) -> Data {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let image = UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format)
            .image { ctx in
                UIColor.systemTeal.setFill()
                ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
            }
        return image.pngData()!
    }

    func testABigPhotoIsMadeSmallAndJPEG() throws {
        let jpeg = try XCTUnwrap(ImageDownscale.jpeg(from: bigPNG(width: 6000, height: 4000),
                                                    maxPixel: 2048))
        XCTAssertEqual(Array(jpeg.prefix(2)), [0xFF, 0xD8])
        let image = try XCTUnwrap(UIImage(data: jpeg))
        XCTAssertEqual(max(image.size.width * image.scale, image.size.height * image.scale), 2048)
        XCTAssertLessThan(jpeg.count, 8 * 1024 * 1024)
    }

    func testASmallPhotoKeepsItsSize() throws {
        let jpeg = try XCTUnwrap(ImageDownscale.jpeg(from: bigPNG(width: 800, height: 600),
                                                    maxPixel: 2048))
        let image = try XCTUnwrap(UIImage(data: jpeg))
        XCTAssertEqual(image.size.width * image.scale, 800)
    }

    func testNotAnImageIsNil() {
        XCTAssertNil(ImageDownscale.jpeg(from: Data("hello".utf8), maxPixel: 2048))
    }
}
