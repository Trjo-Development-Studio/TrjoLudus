//! The two expensive parts of decoding a PNG.
//!
//! Not a PNG decoder. Python walks the chunks, checks the lengths and the
//! checksums, runs zlib, and expands palettes -- all of it cold, all of it
//! where clear error messages matter most. What is here is the two loops that
//! touch every byte:
//!
//! * [`unfilter`], which reverses the per-scanline filters. Paeth on a
//!   512x512 sprite costs the better part of a third of a second in Python.
//! * [`opaque`], which asks whether every pixel is fully opaque. A scan of
//!   every fourth byte, and the single most expensive step of decoding a large
//!   opaque image in Python.
//!
//! # Nothing is owned here
//!
//! Both take slices the caller owns and, where there is output, a slice the
//! caller has already allocated. Nothing is kept after the call. The same rule
//! the renderer and the world view follow, and the reason there is nothing to
//! free.
//!
//! # Byte for byte
//!
//! The Python implementation is the reference. These reproduce its arithmetic
//! exactly, including the wrapping addition PNG specifies -- everything is
//! modulo 256, and Rust's `wrapping_add` is what says so.

/// What went wrong, when something did.
#[derive(Debug, PartialEq, Eq)]
pub enum ImageError {
    /// A width, height or sample count that cannot describe an image.
    BadSize,
    /// The filtered data is shorter than the image's size implies.
    NotEnoughData,
    /// The output buffer is not exactly the size the image needs.
    WrongOutputSize,
    /// A filter byte that is not one of the five PNG defines. The value is
    /// carried so that Python can name it in the message it already raises.
    UnknownFilter(u8),
}

/// Reverse the per-scanline filters PNG applies before compression.
///
/// `raw` is the decompressed data: one filter byte then `stride` bytes, per
/// row. `out` is filled with `stride * height` unfiltered bytes and must be
/// exactly that long.
///
/// `samples` is bytes per pixel for the filters that look left -- 1 for
/// greyscale or indexed, 3 for truecolour, 4 with alpha. PNG calls this the
/// filter's byte offset, and at eight bits per sample it is the same thing.
pub fn unfilter(
    raw: &[u8],
    out: &mut [u8],
    width: usize,
    height: usize,
    samples: usize,
) -> Result<(), ImageError> {
    if width == 0 || height == 0 || samples == 0 {
        return Err(ImageError::BadSize);
    }
    let stride = width.checked_mul(samples).ok_or(ImageError::BadSize)?;
    let expected = stride
        .checked_add(1)
        .and_then(|row| row.checked_mul(height))
        .ok_or(ImageError::BadSize)?;
    if raw.len() < expected {
        return Err(ImageError::NotEnoughData);
    }
    if out.len() != stride.checked_mul(height).ok_or(ImageError::BadSize)? {
        return Err(ImageError::WrongOutputSize);
    }

    // Check every filter byte before writing anything. A row of an image is
    // not worth half-decoding: Python raises on an unknown filter, and it
    // should raise having changed nothing.
    for row in 0..height {
        let filter = raw[row * (stride + 1)];
        if filter > 4 {
            return Err(ImageError::UnknownFilter(filter));
        }
    }

    for row in 0..height {
        let filter = raw[row * (stride + 1)];
        let source = row * (stride + 1) + 1;
        let target = row * stride;

        match filter {
            // None: the row as it is.
            0 => out[target..target + stride]
                .copy_from_slice(&raw[source..source + stride]),

            // Sub: each byte plus the one `samples` to its left.
            1 => {
                for index in 0..stride {
                    let left = if index >= samples {
                        out[target + index - samples]
                    } else {
                        0
                    };
                    out[target + index] = raw[source + index].wrapping_add(left);
                }
            }

            // Up: each byte plus the one above it.
            2 => {
                for index in 0..stride {
                    let above = if row > 0 {
                        out[target - stride + index]
                    } else {
                        0
                    };
                    out[target + index] = raw[source + index].wrapping_add(above);
                }
            }

            // Average: plus the mean of left and above, rounded down.
            3 => {
                for index in 0..stride {
                    let left = if index >= samples {
                        out[target + index - samples] as u16
                    } else {
                        0
                    };
                    let above = if row > 0 {
                        out[target - stride + index] as u16
                    } else {
                        0
                    };
                    let mean = ((left + above) / 2) as u8;
                    out[target + index] = raw[source + index].wrapping_add(mean);
                }
            }

            // Paeth: plus whichever of left, above and above-left is nearest
            // to their combination. The one that costs, and the one real
            // encoders use most.
            4 => {
                for index in 0..stride {
                    let left = if index >= samples {
                        out[target + index - samples]
                    } else {
                        0
                    };
                    let above = if row > 0 {
                        out[target - stride + index]
                    } else {
                        0
                    };
                    let corner = if row > 0 && index >= samples {
                        out[target - stride + index - samples]
                    } else {
                        0
                    };
                    out[target + index] =
                        raw[source + index].wrapping_add(paeth(left, above, corner));
                }
            }

            // Unreachable: every filter byte was checked above.
            _ => return Err(ImageError::UnknownFilter(filter)),
        }
    }

    Ok(())
}

/// PNG's Paeth predictor: whichever neighbour is closest to `a + b - c`.
///
/// Ties go to the left neighbour, then the one above, which is what the
/// specification says and what the Python implementation does.
#[inline]
fn paeth(left: u8, above: u8, corner: u8) -> u8 {
    let estimate = left as i16 + above as i16 - corner as i16;
    let from_left = (estimate - left as i16).abs();
    let from_above = (estimate - above as i16).abs();
    let from_corner = (estimate - corner as i16).abs();
    if from_left <= from_above && from_left <= from_corner {
        left
    } else if from_above <= from_corner {
        above
    } else {
        corner
    }
}

/// Whether every pixel of a BGRA image is fully opaque.
///
/// Exactly `all(pixels[i] == 255 for i in range(3, len(pixels), 4))`: every
/// fourth byte from the fourth. A length that is not a whole number of pixels
/// is not an image, and says so rather than guessing which bytes are alpha.
pub fn opaque(pixels: &[u8]) -> Result<bool, ImageError> {
    if pixels.len() % 4 != 0 {
        return Err(ImageError::BadSize);
    }
    Ok(pixels.chunks_exact(4).all(|pixel| pixel[3] == 255))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The Python implementation, transcribed, to test against.
    fn reference(raw: &[u8], width: usize, height: usize, samples: usize) -> Vec<u8> {
        let stride = width * samples;
        let mut out = vec![0u8; stride * height];
        let mut previous = vec![0u8; stride];
        let mut position = 0;

        for row in 0..height {
            let filter = raw[position];
            position += 1;
            let line = &raw[position..position + stride];
            position += stride;
            let start = row * stride;

            for index in 0..stride {
                let left = if index >= samples {
                    out[start + index - samples]
                } else {
                    0
                };
                let above = previous[index];
                let corner = if index >= samples {
                    previous[index - samples]
                } else {
                    0
                };
                let value = match filter {
                    0 => line[index],
                    1 => line[index].wrapping_add(left),
                    2 => line[index].wrapping_add(above),
                    3 => line[index]
                        .wrapping_add(((left as u16 + above as u16) / 2) as u8),
                    4 => line[index].wrapping_add(paeth(left, above, corner)),
                    _ => panic!("bad filter"),
                };
                out[start + index] = value;
            }
            previous.copy_from_slice(&out[start..start + stride]);
        }
        out
    }

    fn scanlines(width: usize, height: usize, samples: usize, filter: u8) -> Vec<u8> {
        let mut rows = Vec::new();
        let mut value: u32 = 12345;
        for _ in 0..height {
            rows.push(filter);
            for _ in 0..(width * samples) {
                value = value.wrapping_mul(1103515245).wrapping_add(12345);
                rows.push((value >> 16) as u8);
            }
        }
        rows
    }

    #[test]
    fn every_filter_matches_the_reference() {
        for filter in 0..=4u8 {
            for &(width, height, samples) in
                &[(1, 1, 4), (1, 7, 4), (7, 1, 4), (5, 3, 1), (9, 4, 3), (16, 16, 4)]
            {
                let raw = scanlines(width, height, samples, filter);
                let mut out = vec![0u8; width * samples * height];
                unfilter(&raw, &mut out, width, height, samples).unwrap();
                assert_eq!(
                    out,
                    reference(&raw, width, height, samples),
                    "filter {filter}, {width}x{height}, {samples} samples"
                );
            }
        }
    }

    #[test]
    fn a_mixture_of_filters_matches_too() {
        // What a real encoder emits: a different filter per row.
        let (width, height, samples) = (12, 9, 4);
        let stride = width * samples;
        let mut raw = Vec::new();
        let mut value: u32 = 999;
        for row in 0..height {
            raw.push((row % 5) as u8);
            for _ in 0..stride {
                value = value.wrapping_mul(1103515245).wrapping_add(12345);
                raw.push((value >> 16) as u8);
            }
        }
        let mut out = vec![0u8; stride * height];
        unfilter(&raw, &mut out, width, height, samples).unwrap();
        assert_eq!(out, reference(&raw, width, height, samples));
    }

    #[test]
    fn an_unknown_filter_is_named_and_nothing_is_written() {
        let mut raw = scanlines(4, 2, 4, 0);
        raw[0] = 9;
        let mut out = vec![0u8; 4 * 4 * 2];
        assert_eq!(
            unfilter(&raw, &mut out, 4, 2, 4),
            Err(ImageError::UnknownFilter(9))
        );
        assert!(out.iter().all(|byte| *byte == 0), "it wrote anyway");
    }

    #[test]
    fn an_unknown_filter_on_a_later_row_is_caught_first() {
        let mut raw = scanlines(4, 3, 4, 0);
        let stride = 16;
        raw[2 * (stride + 1)] = 7;
        let mut out = vec![0u8; stride * 3];
        assert_eq!(
            unfilter(&raw, &mut out, 4, 3, 4),
            Err(ImageError::UnknownFilter(7))
        );
        assert!(out.iter().all(|byte| *byte == 0));
    }

    #[test]
    fn short_data_is_refused() {
        let raw = scanlines(4, 2, 4, 0);
        let mut out = vec![0u8; 4 * 4 * 2];
        assert_eq!(
            unfilter(&raw[..10], &mut out, 4, 2, 4),
            Err(ImageError::NotEnoughData)
        );
    }

    #[test]
    fn a_wrong_output_buffer_is_refused() {
        let raw = scanlines(4, 2, 4, 0);
        let mut out = vec![0u8; 5];
        assert_eq!(
            unfilter(&raw, &mut out, 4, 2, 4),
            Err(ImageError::WrongOutputSize)
        );
    }

    #[test]
    fn an_impossible_size_is_refused() {
        let raw = scanlines(4, 2, 4, 0);
        let mut out = vec![0u8; 32];
        assert_eq!(unfilter(&raw, &mut out, 0, 2, 4), Err(ImageError::BadSize));
        assert_eq!(unfilter(&raw, &mut out, 4, 0, 4), Err(ImageError::BadSize));
        assert_eq!(unfilter(&raw, &mut out, 4, 2, 0), Err(ImageError::BadSize));
    }

    #[test]
    fn a_size_that_would_overflow_is_refused() {
        let raw = [0u8; 8];
        let mut out = [0u8; 8];
        assert_eq!(
            unfilter(&raw, &mut out, usize::MAX, 2, 4),
            Err(ImageError::BadSize)
        );
    }

    #[test]
    fn opacity_agrees_with_python() {
        assert_eq!(opaque(&[]), Ok(true));
        assert_eq!(opaque(&[1, 2, 3, 255]), Ok(true));
        assert_eq!(opaque(&[1, 2, 3, 254]), Ok(false));
        assert_eq!(opaque(&[1, 2, 3, 0]), Ok(false));
        // Only the first pixel transparent.
        assert_eq!(opaque(&[1, 2, 3, 0, 4, 5, 6, 255]), Ok(false));
        // Only the last.
        assert_eq!(opaque(&[1, 2, 3, 255, 4, 5, 6, 0]), Ok(false));
    }

    #[test]
    fn a_length_that_is_not_whole_pixels_is_refused() {
        assert_eq!(opaque(&[1, 2, 3]), Err(ImageError::BadSize));
        assert_eq!(opaque(&[1, 2, 3, 255, 9]), Err(ImageError::BadSize));
    }

    #[test]
    fn a_large_opaque_image_is_opaque() {
        let pixels: Vec<u8> = [1u8, 2, 3, 255].repeat(64 * 64);
        assert_eq!(opaque(&pixels), Ok(true));
    }

    #[test]
    fn one_transparent_pixel_anywhere_is_enough() {
        for position in [0usize, 1, 500, 4095] {
            let mut pixels: Vec<u8> = [1u8, 2, 3, 255].repeat(4096);
            pixels[position * 4 + 3] = 254;
            assert_eq!(opaque(&pixels), Ok(false), "pixel {position}");
        }
    }
}
