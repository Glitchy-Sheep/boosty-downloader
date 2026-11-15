# Self-generated fallback assets

These fixtures contain only synthetic solid colours and hand-drawn geometry. They contain no third-party footage, audio or font outlines and are covered by the repository's MIT license. The sample generator copies them when ffmpeg is unavailable; it creates its own PNG images and WAV audio with the standard library. No neighboring worktree or downloaded fixture is needed.

The three H.264 MP4 files are 640 by 360, yuv420p, two frames per second, and exactly 24, 75 and 150 seconds long. They are intentionally tiny and playable, with a seekable fast-start MP4 container. Reproduce one with ffmpeg (use the matching duration, colour and output name):

```sh
ffmpeg -hide_banner -loglevel error -nostdin -n -f lavfi -i color=c=0x1a2980:s=640x360:r=2 -t 24 -c:v libx264 -crf 32 -preset veryfast -pix_fmt yuv420p -threads 1 -movflags +faststart video_24s.mp4
```

The colours for 75 and 150 seconds are `134e5e` and `3c3b3f`. Encoder versions may change binary output; duration, dimensions, codec and playable content are the contract.

`SampleSymbols.ttf` is a valid minimal TrueType font. Its `.notdef` and `A` glyphs are the same original diamond, and its space is empty. It is an attachment fixture, not an application font. It was built using fontTools 4.62.1; fontTools is needed only to reproduce this fixture and is not a project or runtime dependency:

```python
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

font = FontBuilder(1000, isTTF=True)
font.setupGlyphOrder(['.notdef', 'space', 'diamond'])
font.setupCharacterMap({32: 'space', 65: 'diamond'})
glyphs = {}
for name in ['.notdef', 'space', 'diamond']:
    pen = TTGlyphPen(None)
    if name != 'space':
        pen.moveTo((50, 350))
        pen.lineTo((300, 700))
        pen.lineTo((550, 350))
        pen.lineTo((300, 0))
        pen.closePath()
    glyphs[name] = pen.glyph()
font.setupGlyf(glyphs)
font.setupHorizontalMetrics({name: (600, 0) for name in glyphs})
font.setupHorizontalHeader(ascent=800, descent=-200)
font.setupNameTable({
    'familyName': 'Sample Symbols',
    'styleName': 'Regular',
    'uniqueFontIdentifier': 'BoostySampleSymbols',
    'fullName': 'Sample Symbols Regular',
    'psName': 'SampleSymbols-Regular',
})
font.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
font.setupPost()
font.setupMaxp()
font.font['head'].created = 3786912000
font.font['head'].modified = 3786912000
font.font.recalcTimestamp = False
font.save('SampleSymbols.ttf')
```
