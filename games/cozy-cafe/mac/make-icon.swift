// Draws the app icon (a warm tile with a steaming cup) into an .iconset.
import Cocoa

let out = CommandLine.arguments[1]
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)

func render(_ px: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let s = CGFloat(px)
    let inset = s * 0.1
    let tile = NSRect(x: inset, y: inset, width: s - inset * 2, height: s - inset * 2)
    let path = NSBezierPath(roundedRect: tile, xRadius: s * 0.18, yRadius: s * 0.18)
    NSGradient(colors: [NSColor(red: 0.95, green: 0.78, blue: 0.55, alpha: 1),
                        NSColor(red: 0.79, green: 0.46, blue: 0.25, alpha: 1)])!.draw(in: path, angle: -90)
    // rain streaks
    NSColor(white: 1, alpha: 0.28).setStroke()
    for i in 0..<9 {
        let x = tile.minX + tile.width * (0.08 + CGFloat(i) * 0.11)
        let y = tile.minY + tile.height * (0.62 + CGFloat(i % 3) * 0.1)
        let l = NSBezierPath(); l.lineWidth = max(1, s * 0.008)
        l.move(to: NSPoint(x: x, y: y)); l.line(to: NSPoint(x: x - s * 0.02, y: y - s * 0.07)); l.stroke()
    }
    let cup = "☕" as NSString
    let font = NSFont.systemFont(ofSize: s * 0.5)
    let attrs: [NSAttributedString.Key: Any] = [.font: font]
    let size = cup.size(withAttributes: attrs)
    cup.draw(at: NSPoint(x: (s - size.width) / 2, y: (s - size.height) / 2 - s * 0.04), withAttributes: attrs)
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for base in [16, 32, 128, 256, 512] {
    try! render(base).write(to: URL(fileURLWithPath: "\(out)/icon_\(base)x\(base).png"))
    try! render(base * 2).write(to: URL(fileURLWithPath: "\(out)/icon_\(base)x\(base)@2x.png"))
}
