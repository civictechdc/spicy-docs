# Read image header observations

`spicy_docs.sources.image_header.read_image_header(bytes)` returns an immutable
`ImageHeader(format, width, height)`. It needs no renderer or network package.
Retain the original bytes alongside these observations.

| Format | What dimensions mean | Minimum input for observation |
| --- | --- | --- |
| PNG | Width and height declared by the first IHDR chunk | 24 bytes; IHDR name and declared length 13 must match |
| GIF87a / GIF89a | Logical screen, which can contain smaller animation frames | 10 bytes |
| JPEG | First frame before scan data or end-of-image | Complete declared frame segment |

The field positions follow the [PNG IHDR specification](https://www.w3.org/TR/png-3/#11IHDR),
[CompuServe GIF89a specification, section 18](https://giflib.sourceforge.net/gifstandard/GIF89a.html),
and [JPEG T.81, Annex B](https://www.w3.org/Graphics/JPEG/itu-t81.pdf).

This reader does not decode or validate a complete image. PNG CRCs, EXIF
orientation, later JPEG height declarations and individual animation frames
are outside its scope. Zero dimensions survive as stated values. An unsupported
or short PNG/GIF header returns `unknown`; a recognized JPEG or sufficiently
long PNG without readable dimensions retains its format with `None` dimensions.

Use the [extraction API](pdf-extraction-api.md) when you need decoded pixels,
orientation, page regions or recognition. Header observations can remain useful
even when a decoder refuses the complete file.
