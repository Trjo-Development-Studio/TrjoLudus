"""Time image loading, stage by stage.

    python tools/benchmark_images.py

Informational, like the rendering benchmark, and not a test: numbers that move
with the machine have no business failing a build. What this is for is knowing
where the time actually goes before anyone moves anything.

It measures each stage of a decode separately -- decompression, unfiltering,
colour conversion, the opacity scan -- because "decoding is slow" is not a
finding. Which part is slow, and for which kind of PNG, is.

Filter type matters more than size. A PNG saved by a real drawing program uses
adaptive filtering, and Paeth is the one that costs.
"""

import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trjoludus import image as image_module  # noqa: E402
from trjoludus.native import library  # noqa: E402

#: Filter types, by the names the PNG specification gives them.
FILTERS = {0: "None", 1: "Sub", 2: "Up", 3: "Average", 4: "Paeth"}

#: Colour types TrjoLudus decodes, and how many samples each pixel has.
COLOUR_TYPES = {
    0: ("greyscale", 1),
    2: ("truecolour", 3),
    3: ("indexed", 1),
    4: ("greyscale+alpha", 2),
    6: ("truecolour+alpha", 4),
}


def scanlines(width, height, samples, filter_type, seed=7):
    """Deterministic filtered scanlines: one filter byte, then the row."""
    rows = bytearray()
    value = seed
    for _ in range(height):
        rows.append(filter_type)
        for _ in range(width * samples):
            value = (value * 1103515245 + 12345) & 0x7FFFFFFF
            rows.append(value >> 16 & 0xFF)
    return bytes(rows)


def png(width, height, colour_type=6, filter_type=0, palette=b"",
        transparency=b""):
    """A whole PNG file, built here so the fixtures are deterministic."""
    samples = COLOUR_TYPES[colour_type][1]
    rows = scanlines(width, height, samples, filter_type)

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    out = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0))
    if palette:
        out += chunk(b"PLTE", palette)
    if transparency:
        out += chunk(b"tRNS", transparency)
    return out + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def best(work, rounds=7):
    """Fastest of several runs: the one least disturbed by everything else."""
    times = []
    for _ in range(rounds):
        start = time.perf_counter()
        work()
        times.append(time.perf_counter() - start)
    return min(times) * 1000


def report_decode_stages():
    print("Decoding, stage by stage. Truecolour+alpha, filter 0.")
    print()
    print(f"{'size':<12}{'whole':>10}{'zlib':>10}{'unfilter':>11}"
          f"{'to_bgra':>10}{'is_opaque':>11}")
    print("-" * 64)
    for size in (64, 128, 256, 512):
        data = png(size, size)
        rows = scanlines(size, size, 4, 0)
        compressed = zlib.compress(rows)
        unfiltered = image_module._unfilter(rows, size, size, 4)
        # Fully opaque, which is the case that costs: `all()` stops at the
        # first transparent pixel, so random alpha measures nothing but the
        # first comparison. Backgrounds and tiles are opaque, and they are
        # exactly the large images.
        pixels = bytes([10, 20, 30, 255]) * (size * size)
        whole = best(lambda: image_module.decode_png(data))
        inflate = best(lambda: zlib.decompress(compressed))
        unfiltering = best(
            lambda: image_module._unfilter(rows, size, size, 4))
        converting = best(
            lambda: image_module._to_bgra(unfiltered, size, size, 6, b"", b""))
        scanning = best(lambda: image_module._opacity_of(pixels))
        print(f"{f'{size}x{size}':<12}{whole:9.2f}ms{inflate:9.2f}ms"
              f"{unfiltering:10.2f}ms{converting:9.2f}ms{scanning:10.2f}ms")

    from trjoludus.native import imaging

    if imaging.available():
        print()
        print("The two migrated stages, Python against native:")
        print()
        print(f"{'size':<12}{'unfilter (Paeth)':>26}{'is_opaque':>26}")
        print("-" * 64)
        for size in (64, 128, 256, 512):
            rows = scanlines(size, size, 4, 4)
            pixels = bytes([10, 20, 30, 255]) * (size * size)
            py_u = best(lambda r=rows, s=size:
                        image_module._unfilter(r, s, s, 4))
            rs_u = best(lambda r=rows, s=size: imaging.unfilter(r, s, s, 4))
            py_o = best(lambda: image_module._opacity_of(pixels))
            rs_o = best(lambda: imaging.opaque(pixels))
            print(f"{f'{size}x{size}':<12}"
                  f"{py_u:11.2f}ms{rs_u:8.2f}ms{py_u / max(rs_u, 1e-9):5.0f}x"
                  f"{py_o:11.2f}ms{rs_o:8.2f}ms{py_o / max(rs_o, 1e-9):5.0f}x")


def report_filters():
    """The migration's whole point, Python against native."""
    from trjoludus.native import imaging

    native = imaging.available()
    print()
    print("Unfiltering, by filter type. Python | native.")
    print()
    header = f"{'filter':<10}" + "".join(f"{f'{s}x{s}':>20}"
                                         for s in (64, 128, 256, 512))
    print(header)
    print("-" * len(header))
    for filter_type, name in FILTERS.items():
        line = f"{name:<10}"
        for size in (64, 128, 256, 512):
            rows = scanlines(size, size, 4, filter_type)
            python = best(
                lambda r=rows, s=size: image_module._unfilter(r, s, s, 4))
            if native:
                rust = best(
                    lambda r=rows, s=size: imaging.unfilter(r, s, s, 4))
                line += f"{python:8.2f}|{rust:7.2f}ms"
            else:
                line += f"{python:16.2f}ms"
        print(line)
    if native:
        print()
        print("  (milliseconds; lower is better)")


def report_colour_types():
    print()
    print("Whole decode, by colour type. 256x256, Paeth filtered.")
    print()
    print(f"{'colour type':<20}{'whole decode':>14}")
    print("-" * 34)
    for colour_type, (name, _) in COLOUR_TYPES.items():
        palette = bytes(range(256)) * 3 if colour_type == 3 else b""
        palette = palette[:768] if colour_type == 3 else b""
        data = png(256, 256, colour_type=colour_type, filter_type=4,
                   palette=palette)
        whole = best(lambda: image_module.decode_png(data))
        print(f"{name:<20}{whole:13.2f}ms")


def report_cache():
    print()
    print("Loading the same files repeatedly.")
    print()
    import tempfile

    from trjoludus import engine

    folder = Path(tempfile.mkdtemp())
    paths = []
    for index in range(20):
        path = folder / f"frame{index}.png"
        path.write_bytes(png(64, 64, filter_type=4))
        paths.append(str(path))

    def load_all():
        for path in paths:
            image_module.load_image(path)

    engine.end_run()
    cold = best(load_all, rounds=1)
    warm = best(load_all, rounds=5)

    one = paths[0]
    engine.end_run()
    first = best(lambda: image_module.load_image(one), rounds=1)
    again = best(lambda: image_module.load_image(one), rounds=50)

    print(f"  20 frames, cold          : {cold:8.2f}ms")
    print(f"  20 frames, again         : {warm:8.2f}ms")
    print(f"  one image, first time    : {first:8.2f}ms")
    print(f"  one image, again         : {again:8.2f}ms")
    if warm > 0:
        ratio = cold / max(warm, 1e-9)
        print(f"  reuse is {ratio:.0f}x faster than decoding again")
    print()
    print(f"  images held by the run   : {len(engine.current().resources)}")


def main() -> int:
    library.forget()
    native = library.implements("image")
    print(f"Native image decoding available: {native}")
    print(f"image.engine resolves to: ", end="")
    from trjoludus.native import registry
    try:
        print(registry.system("image").resolve())
    except Exception as error:      # pragma: no cover -- diagnostic only
        print(f"unavailable ({error})")
    print()

    report_decode_stages()
    report_filters()
    report_colour_types()
    report_cache()
    print()
    print("Same pixels either way; the differential tests are what prove it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
