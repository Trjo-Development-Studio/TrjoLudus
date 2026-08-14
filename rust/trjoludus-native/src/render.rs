//! Drawing into a frame buffer someone else owns.
//!
//! No FFI here, and nothing unsafe: this is the drawing itself, written
//! against a borrowed slice of bytes. [`crate`] wraps it for C.
//!
//! # The buffer
//!
//! BGRA, four bytes per pixel, row by row from the top, exactly as
//! `trjoludus/rendering_python.py` lays it out. The buffer belongs to the
//! caller for its whole life; a [`Frame`] borrows it for one call and keeps
//! nothing.
//!
//! # Everything here is integers
//!
//! Positions arrive already rounded, and scaled sizes arrive already worked
//! out. That is deliberate. Python rounds half-to-even and Rust's `f64::round`
//! rounds half-away-from-zero, so a position rounded on this side of the
//! boundary would land on a different pixel from the Python renderer roughly
//! one time in two hundred. Rounding once, in Python, is what makes the two
//! renderers produce the same pixels rather than nearly the same pixels.

/// Bytes per pixel. BGRA.
pub const BYTES_PER_PIXEL: usize = 4;

/// A frame buffer borrowed for the length of one drawing call.
///
/// Holds no ownership: the bytes belong to whoever passed them in, and this
/// goes out of scope at the end of the call that made it.
#[derive(Debug)]
pub struct Frame<'a> {
    pixels: &'a mut [u8],
    width: i64,
    height: i64,
}

/// Everything that can go wrong before any drawing happens.
#[derive(Debug, PartialEq, Eq)]
pub enum FrameError {
    /// A width or height that cannot describe a buffer.
    BadSize,
    /// The buffer is not `width * height * 4` bytes.
    WrongLength,
}

impl<'a> Frame<'a> {
    /// Borrow a buffer as a frame of the given size.
    ///
    /// The size is checked against the buffer's length rather than trusted,
    /// because everything below indexes with arithmetic derived from it: if
    /// they disagree, every later bound is wrong.
    pub fn new(pixels: &'a mut [u8], width: i64, height: i64) -> Result<Self, FrameError> {
        if width <= 0 || height <= 0 {
            return Err(FrameError::BadSize);
        }
        let needed = (width as i128) * (height as i128) * (BYTES_PER_PIXEL as i128);
        if needed != pixels.len() as i128 {
            return Err(FrameError::WrongLength);
        }
        Ok(Frame { pixels, width, height })
    }

    /// Fill every pixel with one opaque colour.
    ///
    /// Writes one pixel, then doubles the filled region until the buffer is
    /// full. Each doubling is a `memcpy`, which is what the Python renderer
    /// gets for free from `pixels[:] = pattern * count` -- and a per-pixel
    /// loop here measured slower than that, which is a poor thing for a
    /// native renderer to be.
    pub fn clear(&mut self, red: u8, green: u8, blue: u8) {
        let total = self.pixels.len();
        if total < BYTES_PER_PIXEL {
            return;
        }
        self.pixels[..BYTES_PER_PIXEL].copy_from_slice(&[blue, green, red, 255]);
        let mut filled = BYTES_PER_PIXEL;
        while filled < total {
            let take = filled.min(total - filled);
            self.pixels.copy_within(0..take, filled);
            filled += take;
        }
    }

    /// Set one pixel, ignoring anything outside the buffer.
    pub fn set_pixel(&mut self, x: i64, y: i64, red: u8, green: u8, blue: u8) {
        if x < 0 || x >= self.width || y < 0 || y >= self.height {
            return;
        }
        let index = ((y * self.width + x) as usize) * BYTES_PER_PIXEL;
        self.pixels[index] = blue;
        self.pixels[index + 1] = green;
        self.pixels[index + 2] = red;
        self.pixels[index + 3] = 255;
    }

    /// Fill a rectangle, clipped to the buffer.
    ///
    /// A rectangle with no area draws nothing rather than being an error, for
    /// the reason the Python renderer gives: a UI built from computed sizes
    /// will occasionally produce one.
    pub fn fill_rect(
        &mut self,
        x: i64,
        y: i64,
        width: i64,
        height: i64,
        red: u8,
        green: u8,
        blue: u8,
    ) {
        let left = x.max(0);
        let top = y.max(0);
        let right = self.width.min(x.saturating_add(width));
        let bottom = self.height.min(y.saturating_add(height));
        if left >= right || top >= bottom {
            return;
        }

        // Fill the top row a pixel at a time, then copy that row down. The
        // Python renderer builds the row once and slice-assigns it per line;
        // this is the same shape, and the copies become memcpy.
        let span = ((right - left) as usize) * BYTES_PER_PIXEL;
        let first = ((top * self.width + left) as usize) * BYTES_PER_PIXEL;
        for pixel in self.pixels[first..first + span].chunks_exact_mut(BYTES_PER_PIXEL) {
            pixel[0] = blue;
            pixel[1] = green;
            pixel[2] = red;
            pixel[3] = 255;
        }
        for line in (top + 1)..bottom {
            let start = ((line * self.width + left) as usize) * BYTES_PER_PIXEL;
            self.pixels.copy_within(first..first + span, start);
        }
    }

    /// Draw a one-pixel line between two points, ends included.
    ///
    /// Bresenham, stepping in whole pixels. The endpoints are put in a fixed
    /// order first: Bresenham is not symmetric on its own, and a line that
    /// changed depending on which end you named would be a surprise. The
    /// ordering is the same tuple comparison the Python renderer uses.
    pub fn draw_line(
        &mut self,
        x: i64,
        y: i64,
        end_x: i64,
        end_y: i64,
        red: u8,
        green: u8,
        blue: u8,
    ) {
        let (mut x, mut y, end_x, end_y) = if (x, y) > (end_x, end_y) {
            (end_x, end_y, x, y)
        } else {
            (x, y, end_x, end_y)
        };

        let dx = (end_x - x).abs();
        let dy = -(end_y - y).abs();
        let step_x = if x < end_x { 1 } else { -1 };
        let step_y = if y < end_y { 1 } else { -1 };
        let mut error = dx + dy;

        loop {
            self.set_pixel(x, y, red, green, blue);
            if x == end_x && y == end_y {
                return;
            }
            let doubled = 2 * error;
            if doubled >= dy {
                error += dy;
                x += step_x;
            }
            if doubled <= dx {
                error += dx;
                y += step_y;
            }
        }
    }

    /// Draw text from glyph columns the caller supplies.
    ///
    /// The font stays in Python. What arrives here is the column bytes for
    /// the whole string -- `character_width` of them per character, each bit
    /// a pixel down that column -- so there is one font, not a copy of it on
    /// each side of the boundary that could drift apart.
    ///
    /// `advance` is how far the pen moves per character, and
    /// `character_height` how many bits of each column count.
    pub fn draw_glyphs(
        &mut self,
        columns: &[u8],
        character_width: i64,
        character_height: i64,
        advance: i64,
        x: i64,
        y: i64,
        red: u8,
        green: u8,
        blue: u8,
    ) {
        if character_width <= 0 || character_height <= 0 || character_height > 8 {
            return;
        }
        for (index, bits) in columns.iter().enumerate() {
            if *bits == 0 {
                continue;
            }
            let index = index as i64;
            let character = index / character_width;
            let column = index % character_width;
            let pen = x + character * advance + column;
            for row in 0..character_height {
                if bits & (1 << row) != 0 {
                    self.set_pixel(pen, y + row, red, green, blue);
                }
            }
        }
    }

    /// Composite an image at its own size.
    ///
    /// Two paths, chosen by whether the image has any transparency, matching
    /// the Python renderer: an opaque image is a row-at-a-time copy, and a
    /// transparent one is per-pixel work only done when the image calls for
    /// it.
    pub fn draw_image(
        &mut self,
        source: &[u8],
        source_width: i64,
        source_height: i64,
        opaque: bool,
        x: i64,
        y: i64,
    ) {
        if source_width <= 0 || source_height <= 0 {
            return;
        }
        let needed = (source_width as i128) * (source_height as i128) * (BYTES_PER_PIXEL as i128);
        if needed != source.len() as i128 {
            return;
        }

        // Clip to the buffer, in image-local coordinates.
        let left = (-x).max(0);
        let top = (-y).max(0);
        let right = source_width.min(self.width - x);
        let bottom = source_height.min(self.height - y);
        if left >= right || top >= bottom {
            return;
        }

        let span = ((right - left) as usize) * BYTES_PER_PIXEL;

        for row in top..bottom {
            let source_start = ((row * source_width + left) as usize) * BYTES_PER_PIXEL;
            let target_start =
                (((y + row) * self.width + x + left) as usize) * BYTES_PER_PIXEL;

            if opaque {
                self.pixels[target_start..target_start + span]
                    .copy_from_slice(&source[source_start..source_start + span]);
                continue;
            }

            for column in 0..(right - left) as usize {
                let s = source_start + column * BYTES_PER_PIXEL;
                let t = target_start + column * BYTES_PER_PIXEL;
                blend(&mut self.pixels[t..t + 4], &source[s..s + 4]);
            }
        }
    }

    /// Composite an image at a different size, nearest-neighbour.
    ///
    /// Each destination pixel is asked which source pixel it lands on, which
    /// keeps pixel art crisp instead of blurring it and cannot read outside
    /// the source: the index is derived from the destination size.
    ///
    /// `target_width` and `target_height` are worked out by the caller, for
    /// the reason at the top of this file -- rounding happens once, in Python.
    pub fn draw_image_scaled(
        &mut self,
        source: &[u8],
        source_width: i64,
        source_height: i64,
        x: i64,
        y: i64,
        target_width: i64,
        target_height: i64,
    ) {
        if source_width <= 0 || source_height <= 0 {
            return;
        }
        let needed = (source_width as i128) * (source_height as i128) * (BYTES_PER_PIXEL as i128);
        if needed != source.len() as i128 {
            return;
        }
        if target_width <= 0 || target_height <= 0 {
            return;
        }

        let left = (-x).max(0);
        let top = (-y).max(0);
        let right = target_width.min(self.width - x);
        let bottom = target_height.min(self.height - y);
        if left >= right || top >= bottom {
            return;
        }

        for row in top..bottom {
            let source_row = (row * source_height) / target_height;
            let source_start = ((source_row * source_width) as usize) * BYTES_PER_PIXEL;
            let target_start =
                (((y + row) * self.width + x + left) as usize) * BYTES_PER_PIXEL;

            for (offset, column) in (left..right).enumerate() {
                let source_column = (column * source_width) / target_width;
                let s = source_start + (source_column as usize) * BYTES_PER_PIXEL;
                let t = target_start + offset * BYTES_PER_PIXEL;
                blend(&mut self.pixels[t..t + 4], &source[s..s + 4]);
            }
        }
    }
}

/// Put one source pixel over one target pixel.
///
/// The same three cases the Python renderer has, and the same integer
/// arithmetic: `(source * alpha + target * inverse) / 255`, truncating. A
/// different rounding here would differ by one in the last place on
/// semi-transparent pixels, which a pixel-exact comparison would catch and a
/// person would not.
#[inline]
fn blend(target: &mut [u8], source: &[u8]) {
    let alpha = source[3] as u32;
    if alpha == 0 {
        return;
    }
    if alpha == 255 {
        target.copy_from_slice(source);
        return;
    }
    let inverse = 255 - alpha;
    for channel in 0..3 {
        target[channel] =
            ((source[channel] as u32 * alpha + target[channel] as u32 * inverse) / 255) as u8;
    }
    target[3] = 255;
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame(width: i64, height: i64) -> Vec<u8> {
        vec![0u8; (width * height) as usize * BYTES_PER_PIXEL]
    }

    fn pixel(buffer: &[u8], width: i64, x: i64, y: i64) -> (u8, u8, u8) {
        let index = ((y * width + x) as usize) * BYTES_PER_PIXEL;
        (buffer[index + 2], buffer[index + 1], buffer[index])
    }

    #[test]
    fn a_frame_checks_its_buffer() {
        let mut small = frame(2, 2);
        assert!(Frame::new(&mut small, 4, 4).is_err());
        assert_eq!(
            Frame::new(&mut small, 0, 2).unwrap_err(),
            FrameError::BadSize
        );
        assert!(Frame::new(&mut small, 2, 2).is_ok());
    }

    #[test]
    fn clearing_sets_every_pixel_opaque() {
        let mut buffer = frame(3, 2);
        Frame::new(&mut buffer, 3, 2).unwrap().clear(10, 20, 30);
        for chunk in buffer.chunks_exact(BYTES_PER_PIXEL) {
            assert_eq!(chunk, &[30, 20, 10, 255]);
        }
    }

    #[test]
    fn a_pixel_outside_is_ignored() {
        let mut buffer = frame(2, 2);
        let mut target = Frame::new(&mut buffer, 2, 2).unwrap();
        target.set_pixel(-1, 0, 250, 0, 0);
        target.set_pixel(0, 5, 250, 0, 0);
        target.set_pixel(2, 2, 250, 0, 0);
        assert!(buffer.iter().all(|byte| *byte == 0));
    }

    #[test]
    fn a_rectangle_is_clipped() {
        let mut buffer = frame(4, 4);
        Frame::new(&mut buffer, 4, 4)
            .unwrap()
            .fill_rect(-1, -1, 3, 3, 250, 0, 0);
        assert_eq!(pixel(&buffer, 4, 0, 0), (250, 0, 0));
        assert_eq!(pixel(&buffer, 4, 1, 1), (250, 0, 0));
        assert_eq!(pixel(&buffer, 4, 2, 2), (0, 0, 0));
    }

    #[test]
    fn an_empty_rectangle_draws_nothing() {
        let mut buffer = frame(4, 4);
        Frame::new(&mut buffer, 4, 4)
            .unwrap()
            .fill_rect(0, 0, 0, 5, 250, 0, 0);
        assert!(buffer.iter().all(|byte| *byte == 0));
    }

    #[test]
    fn a_line_is_the_same_drawn_either_way() {
        let mut forwards = frame(8, 8);
        Frame::new(&mut forwards, 8, 8)
            .unwrap()
            .draw_line(0, 0, 7, 3, 250, 0, 0);
        let mut backwards = frame(8, 8);
        Frame::new(&mut backwards, 8, 8)
            .unwrap()
            .draw_line(7, 3, 0, 0, 250, 0, 0);
        assert_eq!(forwards, backwards);
    }

    #[test]
    fn a_line_of_no_length_is_one_pixel() {
        let mut buffer = frame(4, 4);
        Frame::new(&mut buffer, 4, 4)
            .unwrap()
            .draw_line(1, 1, 1, 1, 250, 0, 0);
        assert_eq!(pixel(&buffer, 4, 1, 1), (250, 0, 0));
        assert_eq!(pixel(&buffer, 4, 2, 1), (0, 0, 0));
    }

    #[test]
    fn an_opaque_image_is_copied() {
        let source: Vec<u8> = vec![1, 2, 3, 255, 4, 5, 6, 255];
        let mut buffer = frame(4, 1);
        Frame::new(&mut buffer, 4, 1)
            .unwrap()
            .draw_image(&source, 2, 1, true, 1, 0);
        assert_eq!(&buffer[4..12], &source[..]);
    }

    #[test]
    fn a_transparent_pixel_leaves_the_target() {
        let source: Vec<u8> = vec![9, 9, 9, 0];
        let mut buffer = frame(1, 1);
        {
            let mut target = Frame::new(&mut buffer, 1, 1).unwrap();
            target.clear(10, 20, 30);
            target.draw_image(&source, 1, 1, false, 0, 0);
        }
        assert_eq!(pixel(&buffer, 1, 0, 0), (10, 20, 30));
    }

    #[test]
    fn a_half_transparent_pixel_blends_the_way_python_does() {
        // (source * alpha + target * inverse) / 255, truncating.
        let source: Vec<u8> = vec![200, 100, 50, 128];
        let mut buffer = frame(1, 1);
        {
            let mut target = Frame::new(&mut buffer, 1, 1).unwrap();
            target.clear(0, 0, 0);
            target.draw_image(&source, 1, 1, false, 0, 0);
        }
        assert_eq!(buffer[0], ((200u32 * 128) / 255) as u8);
        assert_eq!(buffer[1], ((100u32 * 128) / 255) as u8);
        assert_eq!(buffer[2], ((50u32 * 128) / 255) as u8);
        assert_eq!(buffer[3], 255);
    }

    #[test]
    fn an_image_with_the_wrong_length_draws_nothing() {
        let source: Vec<u8> = vec![1, 2, 3, 255];
        let mut buffer = frame(4, 4);
        Frame::new(&mut buffer, 4, 4)
            .unwrap()
            .draw_image(&source, 2, 2, true, 0, 0);
        assert!(buffer.iter().all(|byte| *byte == 0));
    }

    #[test]
    fn scaling_doubles_the_pixels() {
        let source: Vec<u8> = vec![1, 2, 3, 255];
        let mut buffer = frame(4, 4);
        Frame::new(&mut buffer, 4, 4)
            .unwrap()
            .draw_image_scaled(&source, 1, 1, 0, 0, 2, 2);
        let lit = buffer
            .chunks_exact(BYTES_PER_PIXEL)
            .filter(|pixel| pixel[3] == 255)
            .count();
        assert_eq!(lit, 4);
    }

    #[test]
    fn scaling_to_nothing_draws_nothing() {
        let source: Vec<u8> = vec![1, 2, 3, 255];
        let mut buffer = frame(4, 4);
        Frame::new(&mut buffer, 4, 4)
            .unwrap()
            .draw_image_scaled(&source, 1, 1, 0, 0, 0, 0);
        assert!(buffer.iter().all(|byte| *byte == 0));
    }

    #[test]
    fn glyph_columns_become_pixels() {
        // One character, one lit column of one pixel.
        let columns = [0b0000_0001u8, 0, 0, 0, 0];
        let mut buffer = frame(8, 8);
        Frame::new(&mut buffer, 8, 8)
            .unwrap()
            .draw_glyphs(&columns, 5, 7, 6, 0, 0, 250, 0, 0);
        assert_eq!(pixel(&buffer, 8, 0, 0), (250, 0, 0));
        assert_eq!(pixel(&buffer, 8, 1, 0), (0, 0, 0));
    }

    #[test]
    fn the_second_character_is_advanced() {
        let columns = [0, 0, 0, 0, 0, 0b0000_0001u8, 0, 0, 0, 0];
        let mut buffer = frame(16, 8);
        Frame::new(&mut buffer, 16, 8)
            .unwrap()
            .draw_glyphs(&columns, 5, 7, 6, 0, 0, 250, 0, 0);
        assert_eq!(pixel(&buffer, 16, 6, 0), (250, 0, 0));
    }

    #[test]
    fn nothing_here_writes_outside_the_buffer() {
        // Every operation, aimed off every edge. A panic is the failure.
        let source: Vec<u8> = vec![7; 4 * 4 * BYTES_PER_PIXEL];
        for x in [-100i64, -3, 0, 3, 100] {
            for y in [-100i64, -3, 0, 3, 100] {
                let mut buffer = frame(5, 5);
                let mut target = Frame::new(&mut buffer, 5, 5).unwrap();
                target.set_pixel(x, y, 1, 2, 3);
                target.fill_rect(x, y, 9, 9, 1, 2, 3);
                target.draw_line(x, y, -x, -y, 1, 2, 3);
                target.draw_glyphs(&[255; 10], 5, 7, 6, x, y, 1, 2, 3);
                target.draw_image(&source, 4, 4, true, x, y);
                target.draw_image(&source, 4, 4, false, x, y);
                target.draw_image_scaled(&source, 4, 4, x, y, 9, 9);
            }
        }
    }
}
