import XCTest
import UIKit
@testable import SandyApp

/// M9: a chat photo «made 1600 wide» came out at the screen's scale, 4800 wide on a 3x
/// phone, bigger than it was; big ones then passed the server's 8 MB and were refused.
final class ChatAttachmentSizeTests: XCTestCase {
    private func photo(width: Int, height: Int) -> UIImage {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        return UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format)
            .image { ctx in
                UIColor.systemOrange.setFill()
                ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
            }
    }

    private func longSide(_ jpeg: Data?) throws -> CGFloat {
        let image = try XCTUnwrap(jpeg.flatMap(UIImage.init(data:)))
        return max(image.size.width * image.scale, image.size.height * image.scale)
    }

    func testACameraPhotoIsMadeAtMost1600Pixels() throws {
        XCTAssertEqual(try longSide(AttachmentComposer.jpeg(photo(width: 4032, height: 3024))), 1600)
    }

    func testALibraryPhotoIsMadeAtMost1600PixelsFromItsBytes() throws {
        let png = try XCTUnwrap(photo(width: 4032, height: 3024).pngData())
        XCTAssertEqual(try longSide(AttachmentComposer.jpeg(from: png)), 1600)
    }

    func testASmallPhotoKeepsItsSize() throws {
        XCTAssertEqual(try longSide(AttachmentComposer.jpeg(photo(width: 800, height: 600))), 800)
    }
}
