"""The built-in text font.

TrjoLudus has no dependencies and cannot rely on a font file being installed,
so it carries its own: a 5x7 bitmap covering printable ASCII, which is enough
for scores, labels and menu text.

Each character is five columns of seven rows. A column is one byte, and bit
*n* of that byte is row *n* counting from the top -- so ``0x7F`` is a full
column and ``0x01`` is a single pixel on the top row. That packing is why the
whole font is under 500 bytes.

Anything outside printable ASCII is drawn as a hollow box rather than skipped,
so missing characters are visible instead of silently absent.
"""

__all__ = ["CHARACTER_HEIGHT", "CHARACTER_WIDTH", "SPACING", "columns_for"]

#: Size of one character cell, in pixels.
CHARACTER_WIDTH = 5
CHARACTER_HEIGHT = 7

#: Blank columns between characters.
SPACING = 1

#: The first character the table covers.
FIRST_CHARACTER = " "

#: Five bytes per character, starting at a space, running to ``~``.
_GLYPHS = bytes.fromhex(
    "0000000000"  # (space)
    "00005f0000"  # !
    "0007000700"  # "
    "147f147f14"  # #
    "242a7f2a12"  # $
    "2313086462"  # %
    "3649552250"  # &
    "0005030000"  # '
    "001c224100"  # (
    "0041221c00"  # )
    "14083e0814"  # *
    "08083e0808"  # +
    "0050300000"  # ,
    "0808080808"  # -
    "0060600000"  # .
    "2010080402"  # /
    "3e5149453e"  # 0
    "00427f4000"  # 1
    "4261514946"  # 2
    "2141454b31"  # 3
    "1814127f10"  # 4
    "2745454539"  # 5
    "3c4a494930"  # 6
    "0171090503"  # 7
    "3649494936"  # 8
    "064949291e"  # 9
    "0036360000"  # :
    "0056360000"  # ;
    "0814224100"  # <
    "1414141414"  # =
    "0041221408"  # >
    "0201510906"  # ?
    "324979413e"  # @
    "7e1111117e"  # A
    "7f49494936"  # B
    "3e41414122"  # C
    "7f4141221c"  # D
    "7f49494941"  # E
    "7f09090901"  # F
    "3e4149497a"  # G
    "7f0808087f"  # H
    "00417f4100"  # I
    "2040413f01"  # J
    "7f08142241"  # K
    "7f40404040"  # L
    "7f020c027f"  # M
    "7f0408107f"  # N
    "3e4141413e"  # O
    "7f09090906"  # P
    "3e4151215e"  # Q
    "7f09192946"  # R
    "4649494931"  # S
    "01017f0101"  # T
    "3f4040403f"  # U
    "1f2040201f"  # V
    "3f4038403f"  # W
    "6314081463"  # X
    "0708700807"  # Y
    "6151494543"  # Z
    "007f414100"  # [
    "0204081020"  # \
    "0041417f00"  # ]
    "0402010204"  # ^
    "4040404040"  # _
    "0001020400"  # `
    "2054545478"  # a
    "7f48444438"  # b
    "3844444420"  # c
    "384444487f"  # d
    "3854545418"  # e
    "087e090102"  # f
    "0c5252523e"  # g
    "7f08040478"  # h
    "00447d4000"  # i
    "2040443d00"  # j
    "7f10284400"  # k
    "00417f4000"  # l
    "7c04180478"  # m
    "7c08040478"  # n
    "3844444438"  # o
    "7c14141408"  # p
    "081414187c"  # q
    "7c08040408"  # r
    "4854545420"  # s
    "043f444020"  # t
    "3c4040207c"  # u
    "1c2040201c"  # v
    "3c4030403c"  # w
    "4428102844"  # x
    "0c5050503c"  # y
    "4464544c44"  # z
    "0008364100"  # {
    "00007f0000"  # |
    "0041360800"  # }
    "0804081008"  # ~
)

#: Drawn for anything the table does not cover: a hollow box.
_UNKNOWN = bytes((0x7F, 0x41, 0x41, 0x41, 0x7F))


def columns_for(character: str) -> bytes:
    """Return the five column bytes for one character.

    Characters outside the table come back as a hollow box, so text with an
    unsupported character still reads as text with something missing rather
    than quietly losing letters.
    """
    index = ord(character) - ord(FIRST_CHARACTER)
    start = index * CHARACTER_WIDTH
    if index < 0 or start + CHARACTER_WIDTH > len(_GLYPHS):
        return _UNKNOWN
    return _GLYPHS[start:start + CHARACTER_WIDTH]


def measure(text: str) -> tuple[int, int]:
    """Return the ``(width, height)`` one line of text will occupy."""
    if not text:
        return (0, CHARACTER_HEIGHT)
    return (
        len(text) * CHARACTER_WIDTH + (len(text) - 1) * SPACING,
        CHARACTER_HEIGHT,
    )
