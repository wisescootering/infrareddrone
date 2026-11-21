# -*- coding: utf-8 -*-
"""Makes the DNG written by sjcam_raw2dng readable by RawTherapee 5.13 (and the versions after 5.10).

The converter declares the raw image of its DNG as a colour filter array with 3 samples per pixel
(``SamplesPerPixel`` = 3) and 3 component lossless JPEG tiles, although each pixel holds one value.
The old dcraw reader of RawTherapee 5.10 rebuilt the image anyway; the LibRaw of RawTherapee 5.13 (also rawpy,
LibRaw 0.22) keeps one value out of three: the infrared images come out torn into shifted horizontal bands.
Checked: 5.10 develops the original DNG correctly, 5.13 tears it; 5.11 and 5.12 were not tested.

``fix_sjcam_dng`` rewrites the raw image as a standard DNG: one 16 bits sample per pixel, uncompressed, in
one strip (RawTherapee 5.10 and older read uncompressed data in strips only, not in tiles), made from the 12 bits
packed .RAW the DNG was converted from. Nothing else of the DNG changes (colour matrices, white balance, dates,
GPS ...): the IFD of the raw image is rewritten in place, the strip is appended to the file.
"""
import os
import struct
from pathlib import Path

import numpy as np

# TIFF tags
IMAGE_WIDTH, IMAGE_LENGTH, BITS_PER_SAMPLE, COMPRESSION = 256, 257, 258, 259
SAMPLES_PER_PIXEL, TILE_WIDTH, TILE_LENGTH, TILE_OFFSETS, TILE_BYTE_COUNTS = 277, 322, 323, 324, 325
STRIP_OFFSETS, ROWS_PER_STRIP, STRIP_BYTE_COUNTS = 273, 278, 279
SUB_IFDS, NEW_SUBFILE_TYPE, BLACK_LEVEL, WHITE_LEVEL = 330, 254, 50714, 50717
SHORT, LONG = 3, 4
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8}


class DngFixError(Exception):
    """The DNG or its .RAW is not the one expected."""


def unpack_raw12(raw_bytes, width, height):
    """The mosaic of a SJCam .RAW: 12 bits samples, two per 3 bytes, low bits first (uint16, height x width)."""
    expected = width * height * 3 // 2
    if len(raw_bytes) != expected:
        raise DngFixError(f"The .RAW has {len(raw_bytes)} bytes instead of {expected} ({width}x{height}, 12 bits).")
    b = np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.uint16)
    mosaic = np.empty(width * height, dtype=np.uint16)
    mosaic[0::2] = b[0::3] | ((b[1::3] & 0x0F) << 8)
    mosaic[1::2] = (b[1::3] >> 4) | (b[2::3] << 4)
    return mosaic.reshape(height, width)


class _Tiff:
    """The few things needed to patch a classic TIFF in place."""

    def __init__(self, data):
        if data[:4] not in (b"II*\x00", b"MM\x00*"):
            raise DngFixError("Not a classic TIFF / DNG file.")
        self.data = data
        self.bo = "<" if data[:2] == b"II" else ">"

    def u16(self, offset):
        return struct.unpack_from(self.bo + "H", self.data, offset)[0]

    def u32(self, offset):
        return struct.unpack_from(self.bo + "I", self.data, offset)[0]

    def ifd(self, offset):
        """{tag: (type, count, entry offset, offset of the values)}."""
        entries = {}
        for i in range(self.u16(offset)):
            entry = offset + 2 + 12 * i
            tag, kind, count = self.u16(entry), self.u16(entry + 2), self.u32(entry + 4)
            inline = TYPE_SIZE.get(kind, 1) * count <= 4
            entries[tag] = (kind, count, entry, entry + 8 if inline else self.u32(entry + 8))
        return entries

    def values(self, entry):
        kind, count, _, where = entry
        fmt = {SHORT: "H", LONG: "I", 1: "B", 7: "B"}[kind]
        return list(struct.unpack_from(self.bo + str(count) + fmt, self.data, where))

    def set_short(self, entry, value):
        """The entry becomes one SHORT, stored in the entry."""
        _, _, offset, _ = entry
        struct.pack_into(self.bo + "HI", self.data, offset + 2, SHORT, 1)       # type, count
        struct.pack_into(self.bo + "HH", self.data, offset + 8, value, 0)       # value, padding

    def set_count(self, entry, count):
        struct.pack_into(self.bo + "I", self.data, entry[2] + 4, count)

    def raw_ifd_offset(self):
        main = self.ifd(self.u32(4))
        _, count, _, where = main[SUB_IFDS]
        for i in range(count):
            offset = self.u32(where + 4 * i)
            sub = self.ifd(offset)
            if (TILE_OFFSETS in sub or STRIP_OFFSETS in sub) and (
                    NEW_SUBFILE_TYPE not in sub or self.values(sub[NEW_SUBFILE_TYPE])[0] == 0):
                return offset
        raise DngFixError("No raw image found in the DNG.")

    def raw_ifd(self):
        """The full resolution sub IFD holding the raw image."""
        return self.ifd(self.raw_ifd_offset())


def needs_fix(dng_path):
    """True for the DNG of sjcam_raw2dng not yet fixed (3 samples per pixel, JPEG tiles)."""
    try:
        with open(dng_path, "rb") as f:
            data = bytearray(f.read(1 << 20))      # the IFDs are at the beginning of the file
        sub = _Tiff(data).raw_ifd()
        tiff = _Tiff(data)
        return tiff.values(sub[SAMPLES_PER_PIXEL])[0] == 3 and tiff.values(sub[COMPRESSION])[0] == 7
    except (OSError, DngFixError, KeyError, struct.error):
        return False


def fix_sjcam_dng(dng_path, raw_path, black_level=0):
    """Patch ``dng_path`` in place (see the module doc). Returns False when there was nothing to do.

    ``black_level``: the converter writes 200 but RawTherapee up to 5.10 never subtracted it from these DNG (the
    developed images are identical with 0, checked pixel by pixel): 0 keeps every image as it has always been
    developed, whatever the version of RawTherapee. None keeps the 200 of the converter (darker blacks)."""
    dng_path, raw_path = Path(dng_path), Path(raw_path)
    data = bytearray(dng_path.read_bytes())
    tiff = _Tiff(data)
    sub = tiff.raw_ifd()
    if tiff.values(sub[SAMPLES_PER_PIXEL])[0] != 3 or tiff.values(sub[COMPRESSION])[0] != 7:
        return False
    width, height = tiff.values(sub[IMAGE_WIDTH])[0], tiff.values(sub[IMAGE_LENGTH])[0]
    mosaic = unpack_raw12(raw_path.read_bytes(), width, height)

    # the mosaic, uncompressed, in one strip at the end of the file
    if len(data) % 2:
        data.append(0)
    offset = len(data)
    data += mosaic.astype("<u2" if tiff.bo == "<" else ">u2").tobytes()

    # IFD of the raw image: one 16 bits sample per pixel, no compression, one strip instead of tiles
    ifd_offset = tiff.raw_ifd_offset()
    entries = {tag: bytearray(data[ifd_offset + 2 + 12 * i: ifd_offset + 14 + 12 * i])
               for i, tag in enumerate(sorted(sub, key=lambda t: sub[t][2]))}
    for tag in (TILE_WIDTH, TILE_LENGTH, TILE_OFFSETS, TILE_BYTE_COUNTS):
        del entries[tag]

    def entry(tag, kind, value, size=1):
        return bytearray(struct.pack(tiff.bo + "HHI", tag, kind, size) + (
            struct.pack(tiff.bo + "HH", value, 0) if kind == SHORT else struct.pack(tiff.bo + "I", value)))

    entries[BITS_PER_SAMPLE] = entry(BITS_PER_SAMPLE, SHORT, 16)
    entries[COMPRESSION] = entry(COMPRESSION, SHORT, 1)
    entries[SAMPLES_PER_PIXEL] = entry(SAMPLES_PER_PIXEL, SHORT, 1)
    entries[STRIP_OFFSETS] = entry(STRIP_OFFSETS, LONG, offset)
    entries[ROWS_PER_STRIP] = entry(ROWS_PER_STRIP, LONG, height)
    entries[STRIP_BYTE_COUNTS] = entry(STRIP_BYTE_COUNTS, LONG, width * height * 2)
    if BLACK_LEVEL in entries:      # a rational per sample: the first one stays
        struct.pack_into(tiff.bo + "I", entries[BLACK_LEVEL], 4, 1)
        if black_level is not None:
            struct.pack_into(tiff.bo + "II", data, sub[BLACK_LEVEL][3], int(black_level), 1)
    if WHITE_LEVEL in entries:
        entries[WHITE_LEVEL] = entry(WHITE_LEVEL, SHORT, tiff.values(sub[WHITE_LEVEL])[0])
    body = b"".join(bytes(entries[tag]) for tag in sorted(entries))
    struct.pack_into(tiff.bo + "H", data, ifd_offset, len(entries))
    data[ifd_offset + 2: ifd_offset + 2 + len(body)] = body
    struct.pack_into(tiff.bo + "I", data, ifd_offset + 2 + len(body), 0)       # no next IFD

    temporary = dng_path.with_suffix(".dng.fixing")
    temporary.write_bytes(data)
    os.replace(temporary, dng_path)
    return True
