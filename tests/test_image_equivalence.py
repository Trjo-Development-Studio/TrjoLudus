"""Python and Rust must decode PNGs identically, and fail identically.

The Python implementation is the reference. For every input here -- valid or
corrupt -- both paths are run and compared: the same bytes out, or the same
exception with the same message.

Fixtures are generated rather than checked in, so the corpus can cover every
filter type against every colour type at sizes that would be tedious to store,
and so a failure is reproducible from the seed rather than from a file nobody
can regenerate.

These skip when there is no native library. That is the one thing that cannot
be arranged: you cannot compare against an implementation that is not built.
"""

import struct
import unittest
import zlib

from trjoludus import image as image_module
from trjoludus.image import ImageError
from trjoludus.native import library
from trjoludus.native import imaging

#: name -> (colour type, samples per pixel)
COLOUR_TYPES = {
    "greyscale": (0, 1),
    "truecolour": (2, 3),
    "indexed": (3, 1),
    "greyscale+alpha": (4, 2),
    "truecolour+alpha": (6, 4),
}

FILTERS = (0, 1, 2, 3, 4)


def noise(count, seed):
    """Deterministic bytes. A seed reproduces a failure exactly."""
    out = bytearray()
    value = seed
    for _ in range(count):
        value = (value * 1103515245 + 12345) & 0x7FFFFFFF
        out.append(value >> 16 & 0xFF)
    return bytes(out)


def scanlines(width, height, samples, filter_type, seed=7):
    """Filtered rows: one filter byte, then the row."""
    stride = width * samples
    rows = bytearray()
    for row in range(height):
        rows.append(filter_type)
        rows += noise(stride, seed + row * 31)
    return bytes(rows)


def mixed_scanlines(width, height, samples, seed=11):
    """A different filter on each row, as a real encoder emits."""
    stride = width * samples
    rows = bytearray()
    for row in range(height):
        rows.append(row % 5)
        rows += noise(stride, seed + row * 17)
    return bytes(rows)


def chunk(tag, body):
    return (struct.pack(">I", len(body)) + tag + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))


def png(width, height, colour_type=6, filter_type=0, rows=None,
        palette=None, transparency=b"", seed=7):
    """A whole PNG file."""
    samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type]
    if rows is None:
        rows = scanlines(width, height, samples, filter_type, seed)
    if palette is None:
        palette = bytes(range(256)) * 3 if colour_type == 3 else b""
        palette = palette[:768]

    out = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0))
    if colour_type == 3:
        out += chunk(b"PLTE", palette)
    if transparency:
        out += chunk(b"tRNS", transparency)
    return out + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class ImageEquivalence(unittest.TestCase):
    """Runs one input through both implementations and compares."""

    @classmethod
    def setUpClass(cls):
        library.forget()
        imaging.forget()
        if not imaging.available():
            raise unittest.SkipTest(
                "no native image implementation built here; run cargo build")

    def setUp(self):
        from trjoludus import engine
        from trjoludus.native import registry

        engine.end_run()
        registry.reset()
        self.addCleanup(registry.reset)
        self.addCleanup(engine.end_run)

    def both_unfilter(self, raw, width, height, samples):
        """Unfilter with each implementation, returning both results."""
        by_python = image_module._unfilter(raw, width, height, samples)
        answer = imaging.unfilter(raw, width, height, samples)
        return by_python, answer.pixels

    def assertSameBytes(self, raw, width, height, samples, note=""):
        by_python, by_rust = self.both_unfilter(raw, width, height, samples)
        self.assertIsNotNone(by_rust, f"the native side refused {note}")
        if by_python == by_rust:
            return
        for index, (expected, found) in enumerate(zip(by_python, by_rust)):
            if expected != found:
                self.fail(
                    f"byte {index} differs{note}: Python {expected}, "
                    f"Rust {found}")
        self.fail(f"different lengths{note}: "
                  f"{len(by_python)} vs {len(by_rust)}")

    def both_decode(self, data):
        """Decode with each backend; return both images or both errors."""
        from trjoludus import image as module
        from trjoludus.native import registry

        results = {}
        for engine in ("python", "rust"):
            registry.system("image").engine = engine
            try:
                decoded = module.decode_png(data)
                results[engine] = ("ok", decoded.width, decoded.height,
                                   decoded.pixels, decoded.is_opaque)
            except ImageError as error:
                results[engine] = ("error", str(error))
        return results["python"], results["rust"]


class TestEveryFilter(ImageEquivalence):
    def test_each_filter_on_its_own(self):
        for filter_type in FILTERS:
            for width, height, samples in ((1, 1, 4), (7, 3, 4), (16, 16, 4)):
                with self.subTest(filter=filter_type, size=(width, height)):
                    raw = scanlines(width, height, samples, filter_type)
                    self.assertSameBytes(raw, width, height, samples)

    def test_filters_mixed_row_by_row(self):
        """What a real encoder emits."""
        for width, height in ((13, 9), (32, 32), (1, 20), (20, 1)):
            with self.subTest(size=(width, height)):
                raw = mixed_scanlines(width, height, 4)
                self.assertSameBytes(raw, width, height, 4)

    def test_each_filter_at_each_sample_count(self):
        for filter_type in FILTERS:
            for samples in (1, 2, 3, 4):
                with self.subTest(filter=filter_type, samples=samples):
                    raw = scanlines(9, 5, samples, filter_type)
                    self.assertSameBytes(raw, 9, 5, samples)

    def test_a_tall_thin_image(self):
        raw = mixed_scanlines(1, 200, 4)
        self.assertSameBytes(raw, 1, 200, 4)

    def test_a_wide_flat_image(self):
        raw = mixed_scanlines(200, 1, 4)
        self.assertSameBytes(raw, 200, 1, 4)

    def test_a_large_image(self):
        raw = mixed_scanlines(128, 128, 4)
        self.assertSameBytes(raw, 128, 128, 4)

    def test_odd_widths(self):
        for width in (1, 2, 3, 5, 7, 11, 13, 17, 31, 33):
            with self.subTest(width=width):
                raw = mixed_scanlines(width, 4, 4)
                self.assertSameBytes(raw, width, 4, 4)

    def test_bytes_that_wrap_around(self):
        """PNG filtering is modulo 256; a signed slip shows up here."""
        stride = 4 * 4
        rows = bytearray()
        for row in range(4):
            rows.append(1 if row % 2 else 4)
            rows += bytes([255, 254, 128, 1] * 4)
        self.assertSameBytes(bytes(rows), 4, 4, 4)


class TestThePaethPredictor(ImageEquivalence):
    """The subtlest arithmetic in PNG, swept rather than sampled.

    Paeth picks whichever of left, above and above-left is nearest to their
    combination, and *how ties are broken* is the part an implementation gets
    quietly wrong: a variant that prefers "above" over "left" on a tie agrees
    with the reference on ordinary artwork and disagrees on particular byte
    triples. Random pixels do not reliably produce those triples, so this
    sweeps them on purpose.

    A two-row, one-sample image gives control of all three neighbours: the
    first row sets what is above, and the second row's own first byte becomes
    the left for its second byte.
    """

    def sweep(self):
        for above_a in range(0, 256, 17):
            for above_b in range(0, 256, 13):
                for filtered in range(0, 256, 29):
                    yield above_a, above_b, filtered

    def test_every_sampled_triple_agrees(self):
        cases = 0
        for above_a, above_b, filtered in self.sweep():
            raw = bytes([0, above_a, above_b, 4, filtered, filtered])
            by_python = image_module._unfilter(raw, 2, 2, 1)
            by_rust = imaging.unfilter(raw, 2, 2, 1).pixels
            if by_python != by_rust:
                self.fail(
                    f"Paeth disagreed for above=({above_a}, {above_b}), "
                    f"filtered={filtered}: Python {list(by_python)}, "
                    f"Rust {list(by_rust)}")
            cases += 1
        self.assertGreater(cases, 2000, "the sweep covered almost nothing")

    def test_the_sweep_reaches_all_three_branches(self):
        """Otherwise it would only prove one third of the predictor."""
        chosen = set()
        for above_a, above_b, filtered in self.sweep():
            raw = bytes([0, above_a, above_b, 4, filtered, filtered])
            out = image_module._unfilter(raw, 2, 2, 1)
            left, above, corner = out[2], above_b, above_a
            estimate = left + above - corner
            distances = (abs(estimate - left), abs(estimate - above),
                         abs(estimate - corner))
            if distances[0] <= distances[1] and distances[0] <= distances[2]:
                chosen.add("left")
            elif distances[1] <= distances[2]:
                chosen.add("above")
            else:
                chosen.add("corner")
        self.assertEqual(chosen, {"left", "above", "corner"},
                         f"the sweep only ever picks {sorted(chosen)}")

    def test_a_tie_between_left_and_above_cannot_change_the_answer(self):
        """Why the first comparison may be < or <= without it mattering.

        If left and above are equally close to the estimate but are not equal,
        then left + above = 2 * corner, so the estimate *is* corner and the
        distance to corner is zero -- and the guard that the left distance is
        no greater than the corner distance then forces left == corner ==
        above, contradicting them differing.

        So the case where the tie-break rule would matter does not exist. This
        is checked rather than argued because "no input can reach this" is
        exactly the kind of claim that is wrong.
        """
        for left in range(256):
            for above in range(256):
                if left == above:
                    continue
                for corner in range(256):
                    estimate = left + above - corner
                    from_left = abs(estimate - left)
                    from_above = abs(estimate - above)
                    from_corner = abs(estimate - corner)
                    if from_left == from_above and from_left <= from_corner:
                        self.fail(
                            f"left={left} above={above} corner={corner} "
                            f"reaches the tie, so the rule does matter")


class TestEveryColourType(ImageEquivalence):
    def test_whole_decodes_match(self):
        for name, (colour_type, samples) in COLOUR_TYPES.items():
            for filter_type in FILTERS:
                with self.subTest(colour=name, filter=filter_type):
                    data = png(11, 7, colour_type=colour_type,
                               filter_type=filter_type)
                    by_python, by_rust = self.both_decode(data)
                    self.assertEqual(by_python, by_rust)

    def test_palette_with_transparency(self):
        data = png(9, 5, colour_type=3, filter_type=4,
                   transparency=bytes([0, 128, 255] + [255] * 253))
        by_python, by_rust = self.both_decode(data)
        self.assertEqual(by_python, by_rust)
        self.assertEqual(by_python[0], "ok")

    def test_greyscale_with_alpha(self):
        data = png(8, 8, colour_type=4, filter_type=3)
        by_python, by_rust = self.both_decode(data)
        self.assertEqual(by_python, by_rust)

    def test_one_pixel_of_each_colour_type(self):
        for name, (colour_type, _) in COLOUR_TYPES.items():
            with self.subTest(colour=name):
                data = png(1, 1, colour_type=colour_type, filter_type=4)
                self.assertEqual(*self.both_decode(data))

    def test_a_row_and_a_column_of_each_colour_type(self):
        for name, (colour_type, _) in COLOUR_TYPES.items():
            for width, height in ((1, 9), (9, 1)):
                with self.subTest(colour=name, size=(width, height)):
                    data = png(width, height, colour_type=colour_type,
                               filter_type=2)
                    self.assertEqual(*self.both_decode(data))


class TestOpacity(ImageEquivalence):
    def compare(self, pixels, note=""):
        self.assertEqual(image_module._opacity_of(pixels),
                         imaging.opaque(pixels), note)

    def test_completely_opaque(self):
        self.compare(bytes([1, 2, 3, 255]) * 100, "all opaque")

    def test_completely_transparent(self):
        self.compare(bytes([1, 2, 3, 0]) * 100, "all clear")

    def test_mixed_alpha(self):
        pixels = bytearray()
        for index in range(100):
            pixels += bytes([1, 2, 3, (0, 128, 255, 64)[index % 4]])
        self.compare(bytes(pixels), "mixed")

    def test_only_the_first_pixel_transparent(self):
        pixels = bytearray(bytes([1, 2, 3, 255]) * 100)
        pixels[3] = 0
        self.compare(bytes(pixels))

    def test_only_the_final_pixel_transparent(self):
        pixels = bytearray(bytes([1, 2, 3, 255]) * 100)
        pixels[-1] = 254
        self.compare(bytes(pixels))

    def test_one_pixel_images(self):
        self.compare(bytes([1, 2, 3, 255]))
        self.compare(bytes([1, 2, 3, 0]))

    def test_an_empty_image(self):
        self.compare(b"")

    def test_a_large_image(self):
        self.compare(bytes([9, 9, 9, 255]) * (256 * 256), "large opaque")

    def test_every_single_position(self):
        """One transparent pixel anywhere at all must be found."""
        for position in range(64):
            pixels = bytearray(bytes([1, 2, 3, 255]) * 64)
            pixels[position * 4 + 3] = 200
            with self.subTest(position=position):
                self.compare(bytes(pixels))

    def test_alpha_values_either_side_of_opaque(self):
        for alpha in (0, 1, 127, 128, 254, 255):
            with self.subTest(alpha=alpha):
                self.compare(bytes([1, 2, 3, alpha]) * 8)


class TestMalformedInput(ImageEquivalence):
    """Both paths must refuse the same things, with the same words."""

    def test_an_unknown_filter_type(self):
        for bad in (5, 6, 99, 255):
            with self.subTest(filter=bad):
                raw = bytearray(scanlines(4, 3, 4, 0))
                raw[0] = bad
                data = png(4, 3, rows=bytes(raw))
                by_python, by_rust = self.both_decode(data)
                self.assertEqual(by_python, by_rust)
                self.assertEqual(by_python[0], "error")
                self.assertIn(f"unknown PNG filter type {bad}", by_python[1])

    def test_an_unknown_filter_on_a_later_row(self):
        raw = bytearray(scanlines(4, 3, 4, 0))
        raw[2 * (16 + 1)] = 7
        data = png(4, 3, rows=bytes(raw))
        by_python, by_rust = self.both_decode(data)
        self.assertEqual(by_python, by_rust)
        self.assertIn("unknown PNG filter type 7", by_python[1])

    def test_too_little_pixel_data(self):
        raw = scanlines(4, 4, 4, 0)[:20]
        data = png(4, 4, rows=raw)
        by_python, by_rust = self.both_decode(data)
        self.assertEqual(by_python, by_rust)
        self.assertIn("truncated", by_python[1])

    def test_every_structural_failure_still_behaves(self):
        good = png(4, 4)
        cases = {
            "not a png": b"GIF89a and then some",
            "nothing after the signature": b"\x89PNG\r\n\x1a\n",
            "no IEND": good[:good.rindex(b"IEND") - 4],
            "bad crc": good[:20] + bytes([good[20] ^ 0xFF]) + good[21:],
            "not deflate": png(4, 4, rows=b"") .replace(
                zlib.compress(scanlines(4, 4, 4, 0)), b"nonsense"),
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                by_python, by_rust = self.both_decode(data)
                self.assertEqual(by_python, by_rust)
                self.assertEqual(by_python[0], "error")

    def test_a_zero_sized_image(self):
        data = (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 0, 0, 8, 6, 0, 0, 0))
                + chunk(b"IEND", b""))
        by_python, by_rust = self.both_decode(data)
        self.assertEqual(by_python, by_rust)


class TestBruteForceCorruption(ImageEquivalence):
    """Every byte flipped, every length truncated. Nothing may crash."""

    def test_flipping_every_byte(self):
        good = png(6, 5, filter_type=4)
        for position in range(len(good)):
            damaged = bytearray(good)
            damaged[position] ^= 0xFF
            with self.subTest(position=position):
                by_python, by_rust = self.both_decode(bytes(damaged))
                self.assertEqual(
                    by_python, by_rust,
                    f"the two disagreed on a file corrupted at {position}")

    def test_truncating_at_every_length(self):
        good = png(5, 4, filter_type=1)
        for length in range(len(good)):
            with self.subTest(length=length):
                by_python, by_rust = self.both_decode(good[:length])
                self.assertEqual(by_python, by_rust)

    def test_corrupting_only_the_pixel_data(self):
        """Where the two implementations actually differ in code."""
        raw = bytearray(mixed_scanlines(6, 6, 4))
        for position in range(0, len(raw), 7):
            damaged = bytearray(raw)
            damaged[position] ^= 0xFF
            with self.subTest(position=position):
                data = png(6, 6, rows=bytes(damaged))
                by_python, by_rust = self.both_decode(data)
                self.assertEqual(by_python, by_rust)

    def test_random_filter_bytes(self):
        """Filter bytes are the one field that decides control flow."""
        stride = 6 * 4
        for value in range(256):
            raw = bytearray(scanlines(6, 3, 4, 0))
            raw[stride + 1] = value
            with self.subTest(filter=value):
                data = png(6, 3, rows=bytes(raw))
                by_python, by_rust = self.both_decode(data)
                self.assertEqual(by_python, by_rust)


class TestTheNativeSideRefusesSafely(ImageEquivalence):
    """The ABI's own failure paths, from Python."""

    def test_short_data_is_reported(self):
        answer = imaging.unfilter(b"\x00\x01", 4, 4, 4)
        self.assertTrue(answer.short)
        self.assertIsNone(answer.pixels)

    def test_a_bad_filter_is_reported_with_its_value(self):
        raw = bytearray(scanlines(4, 2, 4, 0))
        raw[0] = 200
        answer = imaging.unfilter(bytes(raw), 4, 2, 4)
        self.assertEqual(answer.bad_filter, 200)
        self.assertIsNone(answer.pixels)

    def test_an_impossible_size_is_refused(self):
        for width, height, samples in ((0, 4, 4), (4, 0, 4), (4, 4, 0)):
            with self.subTest(size=(width, height, samples)):
                answer = imaging.unfilter(b"\x00" * 100, width, height,
                                          samples)
                self.assertIsNone(answer.pixels)

    def test_opacity_of_a_ragged_length(self):
        self.assertIsNone(imaging.opaque(b"\x01\x02\x03"))

    def test_opacity_of_nothing(self):
        self.assertIs(imaging.opaque(b""), True)


if __name__ == "__main__":
    unittest.main()
