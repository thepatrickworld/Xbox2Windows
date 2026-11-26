"""Draw textures published by address (device slot 70) whose texels are in a console layout.

  <consumer> <backend>               seven textures, each drawn once; every pixel of the 512x128 target is
                                     compared with the texel the view names; then two held descriptions
                                     and one texture whose address is announced as XG rows after it
                                     was published
  <consumer> <backend> gate          the upload lifetime control described at check_gate
  <consumer> <backend> gate-ring     the same draws with X2W_TEST_ADDRESS_UPLOAD_RING=1: the 256 MiB ring
                                     refuses the uploads past its cap, the refused draws read the null view
                                     and the left half keeps payload 0
  <consumer> <backend> gate-ring-reuse  gate-ring, then once every submit has completed one more payload from
                                     the ring, which must not be refused
  <consumer> <backend> gate-ring-untracked  gate-ring under X2W_TEST_SUBMIT_FENCE_FAIL=1, then one more
                                     full-size payload after the recording was discarded: a chunk whose
                                     submits were never tracked must not be recycled (described at
                                     check_gate_ring_untracked)

The backing bytes are built here, independently of src/startup_stubs/gfx10_layout.h, from the address
equations of AMD addrlib's GFX10 pattern tables, written out below. Reference: addrlib as Mesa carries it
under src/amd/addrlib at the revision tools/fetch_addrlib.py pins (Mesa 25.1.0, commit
5c142e46f3f6e752ed745fd48912ebb8fad67145), files src/gfx10/gfx10SwizzlePattern.h, src/gfx10/gfx10addrlib.cpp
and src/core/addrlib2.cpp, each with the notice "Copyright (C) 2007-2024 Advanced Micro Devices, Inc. All
rights reserved. SPDX-License-Identifier: MIT". No addrlib code is included.
"""
import os
from pathlib import Path
import struct
import sys
import tempfile

from startup_address_srv_check import draw_texture

TARGET_W, TARGET_H = 512, 128
RGBA8, BC1 = 28, 71

# Address bits 0-7 of the 256-byte micro block by element size; above it y takes the even bits.
STANDARD = {4: "0 0 X0 X1 Y0 Y1 Y2 X2", 8: "0 0 0 X0 Y0 Y1 X1 X2"}
DISPLAY = {4: "0 0 X0 X1 Y0 Y1 Y2 X2", 8: "0 0 0 X0 Y0 X1 X2 Y1"}
MICRO = {4: (8, 8), 8: (8, 4)}


class Console:
    def __init__(self, width, height, mips, element, texels, layout):
        self.width, self.height, self.mips, self.element, self.texels = width, height, mips, element, texels
        mode = layout & 0xff
        self.log2 = {1: 8, 2: 8, 5: 12, 6: 12, 9: 16, 10: 16}[mode]
        bits = (DISPLAY if mode in (2, 6, 10) else STANDARD)[element].split()
        x_next, y_next = (sum(b[0] == axis for b in bits) for axis in "XY")
        for bit in range(8, self.log2):
            if bit & 1:
                bits.append(f"X{x_next}")
                x_next += 1
            else:
                bits.append(f"Y{y_next}")
                y_next += 1
        self.bits = bits
        self.block_w, self.block_h = 1 << x_next, 1 << y_next
        columns, rows = -(-width // texels), -(-height // texels)
        size = lambda v, mip: max(1, (v + (1 << mip) - 1) >> mip)
        tail_mips = self.log2 - 4
        self.first_tail = mips
        if mips > 1:
            for mip in range(mips):
                if size(columns, mip) <= self.block_w // 2 and size(rows, mip) <= self.block_h and mips - mip <= tail_mips:
                    self.first_tail = mip
                    break
        block = 1 << self.log2
        self.start, self.blocks_wide, self.origin = {}, {}, {}
        offset = block if self.first_tail < mips else 0
        for mip in range(self.first_tail - 1, -1, -1):
            self.blocks_wide[mip] = -(-size(columns, mip) // self.block_w)
            self.start[mip] = offset
            offset += self.blocks_wide[mip] * -(-size(rows, mip) // self.block_h) * block
        self.bytes = offset
        for mip in range(self.first_tail, mips):
            m = tail_mips - 1 - (mip - self.first_tail)
            tail = 16 << m if m > 6 else m << 8
            x = sum(((tail >> (9 + 2 * b)) & 1) << b for b in range(6))
            y = sum(((tail >> (8 + 2 * b)) & 1) << b for b in range(6))
            self.origin[mip] = (x * MICRO[element][0], y * MICRO[element][1])

    def in_block(self, x, y):
        value = 0
        for bit, name in enumerate(self.bits):
            if name != "0" and ((x if name[0] == "X" else y) >> int(name[1:])) & 1:
                value |= 1 << bit
        return value

    def columns(self, mip):
        return -(-max(1, self.width >> mip) // self.texels)

    def rows(self, mip):
        return -(-max(1, self.height >> mip) // self.texels)

    def address(self, mip, x, y):
        if mip >= self.first_tail:
            ox, oy = self.origin[mip]
            return self.in_block(ox + x, oy + y)
        block = (y // self.block_h) * self.blocks_wide[mip] + x // self.block_w
        return self.start[mip] + (block << self.log2) + self.in_block(x % self.block_w, y % self.block_h)


def rgba_texel(mip, x, y):
    return bytes(((7 * x + 40 * mip + 1) & 255, (5 * y + 3) & 255, (x ^ (3 * y)) & 255, 255))


def bc1_block(mip, x, y):
    # Both endpoints equal and every index 0: sixteen texels of one colour with full or empty channels.
    v = (5 * x + 3 * y + mip) % 8
    red, green, blue = v & 1, (v >> 1) & 1, (v >> 2) & 1
    colour = (0xf800 if red else 0) | (0x07e0 if green else 0) | (0x001f if blue else 0)
    return struct.pack("<HHI", colour, colour, 0), bytes((255 * red, 255 * green, 255 * blue, 255))


# name, width, height, mips, format, layout, viewed mip
CASES = [
    ("RGBA8 96x40 4 KiB standard", 96, 40, 1, RGBA8, 0x105, 0),
    ("BC1 192x96 4 KiB standard", 192, 96, 1, BC1, 0x105, 0),
    ("BC1 256x128 64 KiB display", 256, 128, 1, BC1, 0x10a, 0),
    ("RGBA8 256x256 chain 64 KiB display, mip 1", 256, 256, 4, RGBA8, 0x10a, 1),
    ("RGBA8 256x256 chain 64 KiB display, tail mip 2", 256, 256, 4, RGBA8, 0x10a, 2),
    ("RGBA8 256x256 chain 64 KiB display, tail mip 3", 256, 256, 4, RGBA8, 0x10a, 3),
    ("RGBA8 40x24 256 B standard", 40, 24, 1, RGBA8, 0x101, 0),
]


def build(width, height, mips, fmt, layout):
    """Backing bytes and, per mip, the RGBA texels a correct detile shows."""
    texels = 4 if fmt == BC1 else 1
    element = 8 if fmt == BC1 else 4
    images = []
    console = Console(width, height, mips, element, texels, layout)
    backing = bytearray(console.bytes)
    seen = set()
    for mip in range(mips):
        w, h = max(1, width >> mip), max(1, height >> mip)
        image = bytearray(w * h * 4)
        for y in range(console.rows(mip)):
            for x in range(console.columns(mip)):
                at = console.address(mip, x, y)
                if at in seen or at + element > len(backing):
                    raise AssertionError(f"oracle address {at:#x} of mip {mip} ({x},{y}) is shared or outside the texture")
                seen.add(at)
                if fmt == BC1:
                    block, colour = bc1_block(mip, x, y)
                    backing[at:at + 8] = block
                    for row in range(4 * y, min(4 * y + 4, h)):
                        for column in range(4 * x, min(4 * x + 4, w)):
                            image[4 * (row * w + column):4 * (row * w + column) + 4] = colour
                else:
                    backing[at:at + 4] = rgba_texel(mip, x, y)
                    image[4 * (y * w + x):4 * (y * w + x) + 4] = rgba_texel(mip, x, y)
        images.append(image)
    return backing, images


# Held descriptions: nothing is published and the draw reads a null view (zeros). The first is the first
# case above over an address announced as an XG copy of rows. The second runs past the size the XG
# stand-in reports: 257x257 RGBA8 in 64 KiB blocks is nine blocks (589,824 bytes), and the desktop
# footprint (257 rows of 1,280 bytes) rounded to 64 KiB is 393,216.
HELD = [
    (("RGBA8 96x40 4 KiB standard over XG rows", 96, 40, 1, RGBA8, 0x105, 0), {"X2W_TEST_CONSOLE_XG_ROWS": "1"},
     "console_layout_xg_rows"),
    (("RGBA8 257x257 64 KiB standard past the XG size", 257, 257, 1, RGBA8, 0x109, 0), {}, "console_layout_beyond_xg_size"),
]

# Published, then the address is announced as an XG copy of rows before the draw: the texture published
# there must sample the null view, as a partial-tile BC view does.
LATE = (("RGBA8 96x40 4 KiB standard, XG rows after publication", 96, 40, 1, RGBA8, 0x105, 0),
        {"X2W_TEST_CONSOLE_XG_ROWS": "after"})


def check(directory, consumer, backend, case, extra=None, held=None, late=False):
    name, width, height, mips, fmt, layout, viewed = case
    backing, images = build(width, height, mips, fmt, layout)
    source = directory / "texels.bin"
    source.write_bytes(backing)
    w, h = max(1, width >> viewed), max(1, height >> viewed)
    hlsl = ("Texture2D<float4> t : register(t0);\n"
            "float4 main(float4 p : SV_Position) : SV_Target {\n"
            f"  return t.Load(int3(uint(p.x) % {w}, uint(p.y) % {h}, 0));\n}}\n")
    trap_log = directory / "trap.log"
    modes = {"X2W_TEST_CONSOLE_VIEW": str(source), "X2W_TRAP_LOG": str(trap_log),
             "X2W_TEST_CONSOLE_DESC": f"{width},{height},{mips},{fmt},{layout},{viewed}", **(extra or {})}
    actual = draw_texture(directory, consumer, backend, hlsl, modes)
    if actual is None:
        return 77
    if len(actual) != TARGET_W * TARGET_H * 4:
        raise AssertionError(f"{name}: readback length {len(actual)}")
    log = trap_log.read_text(errors="replace")
    if held:
        if any(actual):
            raise AssertionError(f"{name}: a held description drew texels")
        if f"slot70 texture kind 1: {held};" not in log or "published console layout" in log:
            raise AssertionError(f"{name}: no '{held}' line in the log, or a publication")
        print(f"{backend} {name}: held ({held}), {TARGET_W * TARGET_H} pixels read the null view")
        return 0
    if late:
        if any(actual):
            raise AssertionError(f"{name}: the published texture drew texels after an XG copy of rows was announced")
        if "slot70 texture kind 1: published console layout" not in log:
            raise AssertionError(f"{name}: no 'published console layout' line in the log")
        print(f"{backend} {name}: published, then {TARGET_W * TARGET_H} pixels read the null view")
        return 0
    image = images[viewed]
    for y in range(TARGET_H):
        for x in range(TARGET_W):
            pixel = actual[4 * (y * TARGET_W + x):4 * (y * TARGET_W + x) + 4]
            expect = image[4 * ((y % h) * w + x % w):4 * ((y % h) * w + x % w) + 4]
            if pixel != expect:
                raise AssertionError(f"{name}: pixel ({x},{y}) actual {pixel.hex()} expected {expect.hex()}")
    if "slot70 texture kind 1: published console layout" not in log:
        raise AssertionError(f"{name}: no 'published console layout' line in the log")
    print(f"{backend} {name}: {TARGET_W * TARGET_H} RGBA pixels exact")
    return 0


GATE_PAYLOADS = 18


def gate_colour(payload):
    """The colour of every texel of a payload; tests/startup_address_srv.cpp writes the same bytes."""
    return bytes(((17 * payload + 3) & 255, (255 - 9 * payload) & 255, payload ^ 0x5a, 255))


def check_gate_ring_reuse(directory, consumer, backend):
    """After the gate-ring sequence has completed, one more payload must find ring capacity again.

    The fixture runs the gate-ring draws. While the queue is still held behind the gate, a negative
    control draw attempts a reservation from the exhausted ring; because submissions are still in flight,
    the reservation must be refused and payload 0 on the left half preserved. Once every submit has
    completed, a final draw uploads payload 18 over the right half from the recycled ring. The left half
    must hold payload 0 and the right half payload 18.
    """
    hlsl = ("Texture2D<float4> t : register(t0);\n"
            "float4 main(float4 p : SV_Position) : SV_Target {\n"
            "  return t.Load(int3(uint(p.x) % 2048, uint(p.y) % 2048, 0));\n}\n")
    trap_log = directory / "trap.log"
    modes = {"X2W_TEST_CONSOLE_GATE": "1", "X2W_TRAP_LOG": str(trap_log),
             "X2W_TEST_ADDRESS_UPLOAD_RING": "1", "X2W_TEST_ADDRESS_UPLOAD_RING_REUSE": "1"}
    actual = draw_texture(directory, consumer, backend, hlsl, modes)
    if actual is None:
        return 77
    if len(actual) != TARGET_W * TARGET_H * 4:
        raise AssertionError(f"gate-ring-reuse: readback length {len(actual)}")
    first, last = gate_colour(0), gate_colour(GATE_PAYLOADS)
    wrong = {"left": 0, "right": 0}
    seen = set()
    for y in range(TARGET_H):
        for x in range(TARGET_W):
            pixel = actual[4 * (y * TARGET_W + x):4 * (y * TARGET_W + x) + 4]
            side = "left" if x < TARGET_W // 2 else "right"
            if pixel != (first if side == "left" else last):
                wrong[side] += 1
                seen.add(pixel.hex())
    if wrong["left"] or wrong["right"]:
        raise AssertionError(f"gate-ring-reuse: {wrong} wrong pixels, found {sorted(seen)[:4]}; expected "
                             f"{first.hex()} left, {last.hex()} right (payload {GATE_PAYLOADS} after completion)")
    log = trap_log.read_text(errors="replace")
    if "x2w-draw upload ring reservation refused: no unused capacity" not in log:
        raise AssertionError("gate-ring-reuse: expected upload reservation refusal while queue was held")
    half = TARGET_W * TARGET_H // 2
    print(f"{backend} gate-ring-reuse: after all submits completed, payload {GATE_PAYLOADS} was uploaded from the ring; "
          f"{half} left pixels hold payload 0 and {half} right pixels payload {GATE_PAYLOADS}")
    return 0


def check_gate(directory, consumer, backend, ring):
    """Uploads recorded while the queue cannot run must still hold their bytes when it does.

    The normal fixture records and discards a draw using payload 0 before the first submit retries that
    payload. The fixture makes the queue wait on a fence it controls, then records and submits eighteen lists. Each
    republishes one 2048x2048 RGBA8 texture (64 KiB standard layout, 16 MiB) from the same address with a new
    payload and draws it: payload 0 over the left half of the target, the others over the right half. The list
    object and its allocator are reset between submits. Nothing may complete while the fence is unsignalled.
    The fixture then signals the fence, waits for the last submit and reads the target back: the left half
    must hold payload 0 and the right half payload 17.

    The shared ring refuses later reservations once its capacity is exhausted.
    The left half must retain payload 0 and the final right-half draw must
    read the null view.
    """
    hlsl = ("Texture2D<float4> t : register(t0);\n"
            "float4 main(float4 p : SV_Position) : SV_Target {\n"
            "  return t.Load(int3(uint(p.x) % 2048, uint(p.y) % 2048, 0));\n}\n")
    trap_log = directory / "trap.log"
    modes = {"X2W_TEST_CONSOLE_GATE": "1", "X2W_TRAP_LOG": str(trap_log)}
    if ring:
        modes["X2W_TEST_ADDRESS_UPLOAD_RING"] = "1"
    else:
        # The Windows switch checks for presence, including an empty value.
        os.environ.pop("X2W_TEST_ADDRESS_UPLOAD_RING", None)
    actual = draw_texture(directory, consumer, backend, hlsl, modes)
    if actual is None:
        return 77
    if len(actual) != TARGET_W * TARGET_H * 4:
        raise AssertionError(f"gate: readback length {len(actual)}")
    first = gate_colour(0)
    last = bytes(4) if ring else gate_colour(GATE_PAYLOADS - 1)
    wrong = {"left": 0, "right": 0}
    seen = set()
    for y in range(TARGET_H):
        for x in range(TARGET_W):
            pixel = actual[4 * (y * TARGET_W + x):4 * (y * TARGET_W + x) + 4]
            side = "left" if x < TARGET_W // 2 else "right"
            if pixel != (first if side == "left" else last):
                wrong[side] += 1
                seen.add(pixel.hex())
    log = trap_log.read_text(errors="replace")
    released = f"x2w-draw by-address uploads: {GATE_PAYLOADS} submits completed and released"
    half = TARGET_W * TARGET_H // 2
    if ring:
        if wrong["left"] or wrong["right"]:
            raise AssertionError(f"gate-ring: {wrong} wrong pixels; expected payload 0 left and null view right")
        if "x2w-draw upload ring reservation refused: no unused capacity" not in log:
            raise AssertionError("gate-ring: no upload reservation refusal")
        if "x2w-draw by-address uploads:" in log:
            raise AssertionError("gate-ring: the ring control retained upload buffers")
        print(f"{backend} gate, uploads from the shared ring: exhaustion refused; "
              f"{half} left pixels hold payload 0 and {half} right pixels read the null view")
        return 0
    if wrong["left"] or wrong["right"]:
        raise AssertionError(f"gate: {wrong} wrong pixels, found {sorted(seen)[:4]}; expected {first.hex()} left, {last.hex()} right")
    if released not in log or f"at most {GATE_PAYLOADS} pending" not in log:
        raise AssertionError("gate: no line reporting the retained uploads released after completion:\n"
                             + "\n".join(line for line in log.splitlines() if "by-address" in line))
    print(f"{backend} gate: {GATE_PAYLOADS} submits held behind the fence; after release the left half holds payload 0 and the "
          f"right half payload {GATE_PAYLOADS - 1}, {TARGET_W * TARGET_H} RGBA pixels exact; {GATE_PAYLOADS} retained uploads released")
    return 0


def check_gate_ring_untracked(directory, consumer, backend):
    """A chunk the ring served while no submit fence could be tracked must never be recycled.

    The fixture runs the gate-ring draws under X2W_TEST_SUBMIT_FENCE_FAIL=1: note_submits finds no fence to
    signal, so every chunk those recordings took from the shared ring is flagged untracked instead of being
    tied to a fence value. Sixteen payloads of 16 MiB fill the 256 MiB ring; the seventeenth and eighteenth
    are refused, and the only thing holding chunk 0 -- whose recordings count is already back to 0, its
    recording discarded by the Reset before the next payload -- is that flag.

    The fixture then lets the queue run every submit, resets the list once more so no chunk is recorded any
    more, and records one more full-size payload. The exhausted ring can only serve it by recycling a chunk,
    which must not happen: nothing ever recorded the GPU's completion of one. That last draw binds the null
    view, so the right half stays zero while the left half keeps payload 0.
    """
    hlsl = ("Texture2D<float4> t : register(t0);\n"
            "float4 main(float4 p : SV_Position) : SV_Target {\n"
            "  return t.Load(int3(uint(p.x) % 2048, uint(p.y) % 2048, 0));\n}\n")
    trap_log = directory / "trap.log"
    os.environ.pop("X2W_TEST_ADDRESS_UPLOAD_RING_REUSE", None)
    modes = {"X2W_TEST_CONSOLE_GATE": "1", "X2W_TRAP_LOG": str(trap_log),
             "X2W_TEST_ADDRESS_UPLOAD_RING": "1",
             "X2W_TEST_SUBMIT_FENCE_FAIL": "1"}
    actual = draw_texture(directory, consumer, backend, hlsl, modes)
    if actual is None:
        return 77
    if len(actual) != TARGET_W * TARGET_H * 4:
        raise AssertionError(f"gate-ring-untracked: readback length {len(actual)}")
    first, null = gate_colour(0), bytes(4)
    wrong = {"left": 0, "right": 0}
    seen = set()
    for y in range(TARGET_H):
        for x in range(TARGET_W):
            pixel = actual[4 * (y * TARGET_W + x):4 * (y * TARGET_W + x) + 4]
            side = "left" if x < TARGET_W // 2 else "right"
            if pixel != (first if side == "left" else null):
                wrong[side] += 1
                seen.add(pixel.hex())
    log = trap_log.read_text(errors="replace")
    refusals = log.count("x2w-draw upload ring reservation refused: no unused capacity")
    if wrong["left"] or wrong["right"]:
        raise AssertionError(f"gate-ring-untracked: {wrong} wrong pixels, found {sorted(seen)[:4]}; expected "
                             f"{first.hex()} left and the null view right. A chunk whose submit fence was never "
                             f"tracked was recycled ({refusals} refusals logged)")
    if not refusals:
        raise AssertionError("gate-ring-untracked: no upload reservation refusal")
    half = TARGET_W * TARGET_H // 2
    print(f"{backend} gate-ring-untracked: the gate payloads filled the ring and {refusals} upload reservations "
          f"were refused; after the recording was discarded (recordings 0) a full-size reservation was still "
          f"refused: {half} right pixels read the null view and {half} left pixels hold payload 0, no chunk was recycled")
    return 0


if __name__ == "__main__":
    gates = ("gate", "gate-ring", "gate-ring-reuse", "gate-ring-untracked")
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] not in gates):
        usage = "usage: startup_address_console_check.py <consumer> <backend> [gate | gate-ring | gate-ring-reuse | gate-ring-untracked]\n"
        sys.exit(usage + "\n\n".join(__doc__.split("\n\n")[:2]))
    if len(sys.argv) == 4 and sys.argv[3] == "gate-ring-untracked":
        with tempfile.TemporaryDirectory() as temporary:
            sys.exit(check_gate_ring_untracked(Path(temporary), sys.argv[1], sys.argv[2]))
    if len(sys.argv) == 4 and sys.argv[3] == "gate-ring-reuse":
        with tempfile.TemporaryDirectory() as temporary:
            sys.exit(check_gate_ring_reuse(Path(temporary), sys.argv[1], sys.argv[2]))
    if len(sys.argv) == 4:
        with tempfile.TemporaryDirectory() as temporary:
            sys.exit(check_gate(Path(temporary), sys.argv[1], sys.argv[2], sys.argv[3] == "gate-ring"))
    for case in CASES:
        with tempfile.TemporaryDirectory() as temporary:
            result = check(Path(temporary), *sys.argv[1:3], case)
            if result:
                sys.exit(result)
    for case, extra, held in HELD:
        with tempfile.TemporaryDirectory() as temporary:
            result = check(Path(temporary), *sys.argv[1:3], case, extra, held)
            if result:
                sys.exit(result)
    with tempfile.TemporaryDirectory() as temporary:
        sys.exit(check(Path(temporary), *sys.argv[1:3], LATE[0], LATE[1], late=True))
