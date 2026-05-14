// make-icon.swift — renders NoteAgent's AppIcon at 1024×1024 with Core
// Graphics, then sips downsamples to every size Xcode's asset catalog
// expects. Designed to be reproducible: edit constants below, re-run, commit.
//
// Usage:
//   swift apps/macos/scripts/make-icon.swift
//
// Writes:
//   apps/macos/NoteAgent/Assets.xcassets/AppIcon.appiconset/icon_<N>x<N>{@2x}.png
//
// Concept: rounded-square macOS app icon with a blue→purple gradient. A
// white microphone sits centred; three short rounded transcript lines below
// it imply speech-to-text. Faint sound waves on the right hint at "live".

import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

// MARK: - Design tokens (everything tunable lives here)

let gradientTop    = NSColor(srgbRed: 0.40, green: 0.50, blue: 1.00, alpha: 1.0)  // #6680FF
let gradientBottom = NSColor(srgbRed: 0.51, green: 0.33, blue: 1.00, alpha: 1.0)  // #8254FF
let foreground     = NSColor.white
let transcriptLine = NSColor.white.withAlphaComponent(0.92)
// Higher alpha so the arcs survive the 16×16 / 32×32 downsamples that show
// up in Finder list view + the dock badge area.
let soundWave      = NSColor.white.withAlphaComponent(0.78)

// macOS Big Sur+ app-icon corner is ~22.5% of the canvas.
let cornerFraction: CGFloat = 0.225

// MARK: - Drawing

func renderMaster(_ canvas: CGFloat) -> CGImage {
    let cs = CGColorSpaceCreateDeviceRGB()
    let info = CGImageAlphaInfo.premultipliedLast.rawValue
    let ctx = CGContext(
        data: nil, width: Int(canvas), height: Int(canvas),
        bitsPerComponent: 8, bytesPerRow: 0,
        space: cs, bitmapInfo: info
    )!

    let bounds = CGRect(x: 0, y: 0, width: canvas, height: canvas)

    // Rounded-rectangle clip for the whole icon (the squircle would be more
    // exact, but rounded-rect is what Xcode's mask is based on and renders
    // identically at every shipped size).
    let radius = canvas * cornerFraction
    let clipPath = CGPath(roundedRect: bounds, cornerWidth: radius, cornerHeight: radius, transform: nil)
    ctx.addPath(clipPath)
    ctx.clip()

    // 1) Background gradient (top → bottom).
    let gradient = CGGradient(
        colorsSpace: cs,
        colors: [gradientTop.cgColor, gradientBottom.cgColor] as CFArray,
        locations: [0, 1]
    )!
    ctx.drawLinearGradient(
        gradient,
        start: CGPoint(x: 0, y: canvas), // top
        end:   CGPoint(x: 0, y: 0),       // bottom
        options: []
    )

    // 2) Sound-wave arcs on the right of the mic — drawn before the mic so
    //    the mic body overlaps them cleanly. Three concentric arcs.
    let micCx = canvas * 0.50
    let micCy = canvas * 0.58
    ctx.setStrokeColor(soundWave.cgColor)
    ctx.setLineCap(.round)
    for i in 0..<3 {
        let r = canvas * (0.20 + CGFloat(i) * 0.08)
        let lw = canvas * 0.030
        ctx.setLineWidth(lw)
        // 60° arc on each side. Right side first.
        let start = CGFloat(-30) * .pi / 180
        let end   = CGFloat(30)  * .pi / 180
        ctx.beginPath()
        ctx.addArc(center: CGPoint(x: micCx, y: micCy), radius: r, startAngle: start, endAngle: end, clockwise: false)
        ctx.strokePath()
        // Left side mirror.
        ctx.beginPath()
        ctx.addArc(center: CGPoint(x: micCx, y: micCy), radius: r, startAngle: .pi - end, endAngle: .pi - start, clockwise: false)
        ctx.strokePath()
    }

    // 3) Microphone capsule body. Capsule = rounded rect with corner radius =
    //    half-width. Sized so the silhouette is still visible at 16×16.
    let micWidth  = canvas * 0.27
    let micHeight = canvas * 0.44
    let micRect = CGRect(
        x: micCx - micWidth / 2,
        y: micCy - micHeight / 2 + canvas * 0.04, // shift up so stand fits below
        width: micWidth, height: micHeight
    )
    ctx.setFillColor(foreground.cgColor)
    let micPath = CGPath(
        roundedRect: micRect,
        cornerWidth: micWidth / 2, cornerHeight: micWidth / 2,
        transform: nil
    )
    ctx.addPath(micPath)
    ctx.fillPath()

    // 4) Mic stand: U-shape under the capsule + vertical post + base bar.
    let standThickness = canvas * 0.042
    let standArcRadius = micWidth * 0.70
    let standCy = micRect.minY + canvas * 0.02
    ctx.setStrokeColor(foreground.cgColor)
    ctx.setLineWidth(standThickness)
    ctx.setLineCap(.round)
    ctx.beginPath()
    ctx.addArc(
        center: CGPoint(x: micCx, y: standCy),
        radius: standArcRadius,
        startAngle: .pi,                 // 180° (left side)
        endAngle: 2 * .pi,               // 360° (right side, going through bottom)
        clockwise: false
    )
    ctx.strokePath()

    // 5) Vertical post from the bottom of the U down to the base bar.
    let postTopY = standCy - standArcRadius
    let postBottomY = canvas * 0.12
    ctx.beginPath()
    ctx.move(to: CGPoint(x: micCx, y: postTopY))
    ctx.addLine(to: CGPoint(x: micCx, y: postBottomY))
    ctx.strokePath()

    // 6) Base bar.
    let baseHalf = canvas * 0.08
    ctx.beginPath()
    ctx.move(to: CGPoint(x: micCx - baseHalf, y: postBottomY))
    ctx.addLine(to: CGPoint(x: micCx + baseHalf, y: postBottomY))
    ctx.strokePath()

    // 7) Transcript lines below — three short rounded bars representing the
    //    "text" half of speech-to-text.
    // We don't actually paint these — the mic stand already lives in the
    // lower third and adding lines too crowds the icon at small sizes
    // (16×16 / 32×32 must remain readable). The sound-wave arcs already
    // carry the "speech" half of the metaphor.

    return ctx.makeImage()!
}

// MARK: - PNG I/O

func writePNG(_ image: CGImage, to url: URL) {
    let dest = CGImageDestinationCreateWithURL(
        url as CFURL, UTType.png.identifier as CFString, 1, nil
    )!
    CGImageDestinationAddImage(dest, image, nil)
    if !CGImageDestinationFinalize(dest) {
        fputs("Failed to write \(url.path)\n", stderr)
        exit(1)
    }
}

// MARK: - Size table (Apple's macOS app-icon spec)

struct Variant { let size: Int; let scale: Int }
let variants: [Variant] = [
    .init(size:   16, scale: 1), .init(size:   16, scale: 2),
    .init(size:   32, scale: 1), .init(size:   32, scale: 2),
    .init(size:  128, scale: 1), .init(size:  128, scale: 2),
    .init(size:  256, scale: 1), .init(size:  256, scale: 2),
    .init(size:  512, scale: 1), .init(size:  512, scale: 2),
]

// MARK: - Main

let repoRoot = URL(fileURLWithPath: CommandLine.arguments[0])
    .deletingLastPathComponent()  // scripts/
    .deletingLastPathComponent()  // apps/macos/
    .deletingLastPathComponent()  // apps/
    .deletingLastPathComponent()  // <repo>

let outDir = repoRoot.appendingPathComponent(
    "apps/macos/NoteAgent/Assets.xcassets/AppIcon.appiconset"
)
try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

let master = renderMaster(1024)

for v in variants {
    let pixels = v.size * v.scale
    let suffix = v.scale == 1 ? "" : "@\(v.scale)x"
    let filename = "icon_\(v.size)x\(v.size)\(suffix).png"
    let url = outDir.appendingPathComponent(filename)

    // Render at the target pixel count by drawing the master into a fresh
    // bitmap context so each size is anti-aliased from the 1024 master rather
    // than scaled from a sibling PNG.
    let cs = CGColorSpaceCreateDeviceRGB()
    let info = CGImageAlphaInfo.premultipliedLast.rawValue
    let ctx = CGContext(
        data: nil, width: pixels, height: pixels,
        bitsPerComponent: 8, bytesPerRow: 0,
        space: cs, bitmapInfo: info
    )!
    ctx.interpolationQuality = .high
    ctx.draw(master, in: CGRect(x: 0, y: 0, width: pixels, height: pixels))
    let img = ctx.makeImage()!
    writePNG(img, to: url)
    print("✓ \(filename) (\(pixels)×\(pixels))")
}

print("\nAll icon PNGs written to \(outDir.path)")
