"""Offline lowering for selected gfx1013 and gfx1030 pixel shaders."""
import argparse
import ctypes as C
from fractions import Fraction
import hashlib
import json
import math
import mmap
from pathlib import Path
import re
import struct
import tempfile
import zlib

from resource_inventory import parts


def inflate(data, size, window):
    if not 0 < size <= 16 << 20:
        raise ValueError("Invalid decoded size")
    decoder = zlib.decompressobj(window)
    image = decoder.decompress(data, size + 1)
    if len(image) != size or not decoder.eof:
        raise ValueError("Incomplete or mismatched compressed stream")
    return image


def _read_named_container(data: mmap.mmap, end: int) -> bytes:
    payload = end + 17
    if payload > len(data):
        raise ValueError("Missing or truncated named record")
    stored, _, repeat, size = struct.unpack_from("<4I", data, end + 1)
    if stored != repeat or not 0 < stored <= 8 << 20 or payload + stored > len(data):
        raise ValueError("Invalid record extent")
    return inflate(data[payload:payload + stored], size, -15)


def _select_named_container(data: mmap.mmap, needle: bytes, digest: str) -> bytes:
    selected = None
    cursor = 0
    while (pos := data.find(needle, cursor)) >= 0:
        # Advance past the name, independent of the candidate's claimed payload extent.
        cursor = pos + len(needle)
        try:
            blob = _read_named_container(data, cursor)
        except (ValueError, zlib.error):
            continue
        if hashlib.sha256(blob).hexdigest() == digest:
            if selected is not None:
                raise ValueError("Multiple records match the name and container SHA-256")
            selected = blob
    if selected is None:
        raise ValueError("No record matches the name and container SHA-256")
    return selected


def _bounded_code(image, start):
    """Strip code padding within the FSSM v0x101 section directory."""
    if len(image) < 240 or struct.unpack_from("<I", image, 4)[0] != 0x101:
        raise ValueError("Unknown multi-exit FSSM layout")
    base, size = struct.unpack_from("<QQ", image, 192)
    limit, = struct.unpack_from("<Q", image, 232)
    if limit == 0xdeadbeefdeadbeef:
        limit = base + size
        if image[limit:limit+16] != b"\x00\x00\x9f\xbf" * 4:
            raise ValueError("Unverified FSSM sentinel extent")
    if (base < 240 or base + 40 != start or size % 16 or base + size != limit
            or limit > len(image) or limit <= start):
        raise ValueError("Inconsistent FSSM code extent")
    end = limit
    while end > start and image[end-4:end] == b"\x00\x00\x9f\xbf":
        end -= 4
    if end <= start or end == limit or image[end-4:end] != b"\x00\x00\x81\xbf":
        raise ValueError("Expected termination followed by code padding")
    return image[start:end]


def _check_two_exits(code, llvm, *, cpu, features):
    """Both decoded exits must be reachable from the single entry."""
    instructions = dict(disassemble(code, llvm, offsets=True, cpu=cpu, features=features))
    exits = [pc for pc, line in instructions.items() if line == "s_endpgm"]
    if len(exits) != 2 or exits[-1] + 4 != len(code):
        raise ValueError("Expected two decoded exits")
    # An aligned word can be a literal or the second half of an instruction.
    # Follow branches only from decoded PCs and reject unresolved transfers.
    pcs = list(instructions)
    following = dict(zip(pcs, pcs[1:] + [len(code)]))
    pending, visited, targets = [0], set(), set()
    while pending:
        pc = pending.pop()
        if pc in visited:
            continue
        if pc not in instructions:
            raise ValueError("Branch outside decoded instruction boundaries")
        visited.add(pc)
        op = instructions[pc].split()[0]
        if op == "s_endpgm":
            continue
        if op == "s_branch" or op in ("s_cbranch_scc0", "s_cbranch_scc1", "s_cbranch_vccz",
                                      "s_cbranch_vccnz", "s_cbranch_execz", "s_cbranch_execnz"):
            target = pc + 4 + 4 * struct.unpack_from("<h", code, pc)[0]
            targets.add(target)
            pending.append(target)
            if op == "s_branch":
                continue
        elif not (op.startswith(("v_", "image_", "buffer_", "tbuffer_", "ds_", "flat_", "global_",
                                 "scratch_", "exp", "s_load_", "s_buffer_load_", "s_cmp", "s_bitcmp",
                                 "s_mov_", "s_and", "s_or_", "s_xor_", "s_not_", "s_lsh", "s_ash",
                                 "s_add", "s_sub", "s_mul", "s_min_", "s_max_", "s_cselect", "s_bfe",
                                 "s_bfm", "s_brev", "s_ff", "s_bcnt", "s_wqm", "s_quadmask"))
                  or op in ("s_nop", "s_version", "s_inst_prefetch", "s_waitcnt", "s_clause", "s_delay_alu",
                            "s_setprio", "s_sleep", "s_movk_i32", "s_cmovk_i32", "s_mulk_i32",
                            "s_flbit_i32_b32", "s_abs_i32", "s_cmov_b32", "s_bitset0_b32", "s_bitset1_b32",
                            "s_bitreplicate_b64_b32", "s_bitset0_b64", "s_bitset1_b64",
                            "s_setreg_imm32_b32", "s_setreg_b32", "s_getreg_b32")):
            raise ValueError(f"Unverified multi-exit control flow: {op}")
        pending.append(following[pc])
    # A direct branch may skip alignment NOPs. Keep them in the original span.
    unreachable = instructions.keys() - visited
    if exits[0] + 4 not in targets or any(instructions[pc].split()[0] not in ("s_nop", "v_nop") for pc in unreachable):
        raise ValueError("Unreachable code or unverified alternate exit")


def native_program(archive: Path, record: str, *, container_sha256: str | None = None, llvm=None,
                   cpu=b"gfx1013", features=b"") -> tuple[bytes, bytes]:
    name = record.encode("ascii")
    if not 0 < len(name) < 255 or b"\0" in name:
        raise ValueError("Invalid length-prefixed record name")
    needle = bytes([len(name) + 1]) + name + b"\0"
    if container_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", container_sha256):
        raise ValueError("Invalid decoded container SHA-256")
    with archive.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if container_sha256 is None:
            pos = data.find(needle)
            end = pos + len(needle)
            if pos < 0 or end + 17 > len(data):
                raise ValueError("Missing or truncated named record")
            if data.find(needle, end) >= 0:
                raise ValueError("Multiple records match the name")
            blob = _read_named_container(data, end)
        else:
            blob = _select_named_container(data, needle, container_sha256.lower())
    return blob, container_code(parts(blob)[b"DXIL"], stage=0, llvm=llvm, cpu=cpu, features=features)


def container_image(program, *, stage):
    """Inflate the native FSSM image of a DXIL program part."""
    if len(program) < 24 or struct.unpack_from("<H", program, 2)[0] != stage:
        raise ValueError("Unexpected shader stage")
    table = program.index(b"XDAT", 24)
    if table + 12 > len(program):
        raise ValueError("Truncated XDAT header")
    count, = struct.unpack_from("<I", program, table+4)
    if table + 12 + count*12 > len(program):
        raise ValueError("Truncated XDAT table")
    entries = struct.iter_unpack("<3I", program[table+12:table+12+count*12])
    native_entries = [(o, n) for tag, o, n in entries if tag == 13]
    if len(native_entries) != 1:
        raise ValueError("Expected one native program entry")
    offset, length = native_entries[0]
    if offset < table + 12 + count * 12 or offset+length > len(program) or length < 24 or program[offset:offset+4] != b"XBCH":
        raise ValueError("Invalid native program entry")
    size, = struct.unpack_from("<I", program, offset+16)
    image = inflate(program[offset+24:offset+length], size, 15)
    if len(image) < 196 or image[:4] != b"FSSM":
        raise ValueError("Invalid native program header")
    return image


def container_code(program, *, stage, llvm=None, cpu=b"gfx1013", features=b""):
    """Extract the stage-specific instruction stream from a DXIL program part."""
    image = container_image(program, stage=stage)
    start = struct.unpack_from("<I", image, 192)[0] + 40
    if start < 196 or start % 4 or start + 4 > len(image):
        raise ValueError("Invalid native code offset")
    if struct.unpack_from("<I", image, 4)[0] == 0x101:
        code = _bounded_code(image, start)
        markers = sum(word == 0xbf810000 for word, in struct.iter_unpack("<I", code))
        if markers == 1:
            return code
        # Exactly two exits, verified for pixel (0) and compute (5) only. Mesh and other
        # stages, and three or more markers, stay rejected.
        if stage in (0, 5) and markers == 2 and llvm is not None:
            _check_two_exits(code, llvm, cpu=cpu, features=features)
            return code
        raise ValueError("Unverified multi-exit program")
    # Older fixtures lack the section extent; preserve their unique-marker rule.
    if stage != 0:
        raise ValueError("Compute requires a bounded FSSM section")
    ends = [i+4 for i in range(start, len(image)-3, 4) if image[i:i+4] == b"\0\0\x81\xbf"]
    if len(ends) != 1:
        raise ValueError("Expected one aligned, terminated program")
    return image[start:ends[0]]


def disassemble(code, library, *, cpu=b"gfx1013", offsets=False, features=b""):
    llvm = C.CDLL(library)
    for component in ("TargetInfo", "Target", "TargetMC", "AsmPrinter", "Disassembler"):
        getattr(llvm, "LLVMInitializeAMDGPU" + component)()
    pointer, string = C.c_void_p, C.c_char_p
    llvm.LLVMCreateDisasmCPUFeatures.argtypes = [string, string, string, pointer, C.c_int, pointer, pointer]
    llvm.LLVMCreateDisasmCPUFeatures.restype = pointer
    llvm.LLVMDisasmInstruction.argtypes = [pointer, pointer, C.c_uint64, C.c_uint64, pointer, C.c_size_t]
    llvm.LLVMDisasmInstruction.restype = C.c_size_t
    llvm.LLVMDisasmDispose.argtypes = [pointer]
    ctx = llvm.LLVMCreateDisasmCPUFeatures(b"amdgcn--amdpal", cpu, features, None, 0, None, None)
    if not ctx:
        raise ValueError(f"LLVM has no {cpu.decode()} disassembler")
    raw = C.create_string_buffer(code)
    offset = 0
    instructions = []
    try:
        while offset < len(code):
            line = C.create_string_buffer(1024)
            size = llvm.LLVMDisasmInstruction(ctx, C.byref(raw, offset), len(code)-offset,
                                              offset, line, len(line))
            if not size:
                raise ValueError(f"Unknown instruction at byte {offset}")
            decoded = line.value.decode("ascii").strip()
            instructions.append((offset, decoded) if offsets else decoded)
            offset += size
    finally:
        llvm.LLVMDisasmDispose(ctx)
    return instructions


SAMPLED_RESOURCES = """Texture2D<float4> tex : register(t0);
SamplerState samp : register(s0);"""

GATHER_RESOURCES = """Texture2D<float4> tex : register(t0);
float4 gather_2d(float2 uv, int2 offset, int mip, uint component) {
    uint width, height, levels;
    tex.GetDimensions(mip, width, height, levels);
    int2 edge = int2(width, height) - 1;
    precise float2 scaled = uv * float2(width, height) - 0.5f;
    int2 origin = int2(floor(scaled)) + offset;
    // In increasing (x, y) coordinates, the taps are (0,1), (1,1), (1,0), (0,0).
    return float4(tex.Load(int3(clamp(origin + int2(0, 1), 0, edge), mip))[component],
                  tex.Load(int3(clamp(origin + int2(1, 1), 0, edge), mip))[component],
                  tex.Load(int3(clamp(origin + int2(1, 0), 0, edge), mip))[component],
                  tex.Load(int3(clamp(origin,               0, edge), mip))[component]);
}"""


def check_gather_sampler(words, mips, *, comparison):
    # SQ_IMG_SAMP_WORD0: clamp to last texel in X/Y, normalized coordinates, no truncation.
    # WORD1: zero MIN_LOD, MAX_LOD at or above the last visible mip. WORD2: bilinear XY,
    # point mip, zero biases. Keep the other fields zero in this profile.
    w0, w1, w2, w3 = words
    compare_mask = 0x7000 if comparison else 0
    if ((w0 & ~compare_mask) != 0x12
            or w1 & ~0x00fff000 or (w1 >> 12) < ((mips - 1) << 8)
            or w2 != 0x04500000 or w3 != 0):
        raise ValueError("Unsupported gather sampler: requires normalized clamp, bilinear XY, point mip and no LOD modifiers")


def gather_offset(bits):
    if bits is None or bits & ~0x3f3f:
        raise ValueError("Gather requires a static packed XY offset")
    x, y = bits & 63, (bits >> 8) & 63
    return (x ^ 32) - 32, (y ^ 32) - 32


# SQ_TEX_DEPTH_COMPARE values (sampler word 0, bits 14:12). D3D12_COMPARISON_FUNC is the same order plus one.
# The hardware compares the reference against the texel: the result is (reference OP texel).
DEPTH_COMPARE = ("NEVER", "LESS", "EQUAL", "LESS_EQUAL", "GREATER", "NOT_EQUAL", "GREATER_EQUAL", "ALWAYS")


def gather_compare_resources(compare):
    if compare in (0, 7):
        result = "0.0f" if compare == 0 else "1.0f"
    else:
        op = (None, "<", "==", "<=", ">", "!=", ">=", None)[compare]
        result = f"float4(reference.xxxx {op} taps)"
    return GATHER_RESOURCES + f"""
float4 gather_compare(float2 uv, int2 offset, int mip, float reference) {{
    float4 taps = gather_2d(uv, offset, mip, 0);
    return {result};
}}"""


# D3D12_FILTER_COMPARISON_MIN_MAG_MIP_POINT and D3D12_FILTER_COMPARISON_MIN_MAG_LINEAR_MIP_POINT.
COMPARISON_FILTERS = {0: ("point", 0x80), 1: ("bilinear", 0x94)}


def sample_offset_arg(reg, vector, sample_dest, known_ssa_bits):
    if reg in sample_dest:
        raise ValueError("Sample offset used before vmcnt wait")
    value = vector.get(reg)
    if not isinstance(value, str) or value not in known_ssa_bits:
        raise ValueError("Sample offset must be a known packed integer word")
    packed = known_ssa_bits[value]
    # RDNA 2 packs signed six-bit X and Y at bits [5:0] and [13:8].
    if packed & ~0x3f3f:
        raise ValueError("Sample offset must be a canonical 2D offset word")
    x = ((packed & 0x3f) ^ 0x20) - 0x20
    y = (((packed >> 8) & 0x3f) ^ 0x20) - 0x20
    if not (-8 <= x <= 7 and -8 <= y <= 7):
        raise ValueError("Sample offset is outside the DXIL immediate range [-8, 7]")
    return f", int2({x}, {y})"


def comparison_sampler_state(words):
    """Decode the sampler descriptor fields that change an image_sample_c_lz result on a 2D texture.

    Field positions are those of SQ_IMG_SAMP_WORD0..3 (registers 0x8F30..0x8F3C in Mesa
    src/amd/registers/gfx10-rsrc.json; enum values in the Linux navi10_enum.h). Not read, because the accepted profile makes them irrelevant: CLAMP_Z,
    DISABLE_CUBE_WRAP and Z_FILTER (2D only), ANISO_THRESHOLD and ANISO_BIAS (ratio 1), word 0 bit 31
    (degamma control; no effect on a float depth texel), MAX_LOD, PERF_MIP and PERF_Z (LOD 0 only), and
    BORDER_COLOR_PTR and BORDER_COLOR_TYPE (no border addressing). Any other non-zero field is refused,
    including word 2 bits 28-31 (MIP_POINT_PRECLAMP, ANISO_OVERRIDE, BLEND_ZERO_PRT) and word 3 bits 12-29,
    which gfx10 leaves unnamed (bit 29 is UPGRADED_DEPTH on GFX8).

    TRUNC_COORD (word 0 bit 27) applies to X and Y for every filter on gfx10 (Mesa ac_gpu_info.h). With 1 the
    texel-space coordinate is truncated; with 0 it is rounded to nearest even at six fraction bits, and point
    sampling then drops the fraction (Mesa commit d573d1d8), so it can select the next texel up to 1/128 texel
    below an edge. D3D point sampling takes the floor (D3D11.3 7.18.7). The accepted pairs are the ones RADV
    programs on gfx10 by default (radv_sampler.c), point with 1 and bilinear with 0; the other two are refused,
    including point with 0, which RADV programs for DXVK and vkd3d-proton. Bilinear results are in the
    contract where the texel-space position is a multiple of 1/64, so the rounding is exact on both sides.
    """
    w0, w1, w2, w3 = words
    if (w0 & 7, (w0 >> 3) & 7) != (2, 2):
        raise ValueError("Comparison sampling requires CLAMP_LAST_TEXEL in X and Y")
    if (w0 >> 9) & 7:
        raise ValueError("Comparison sampling with anisotropy is not supported")
    if (w0 >> 15) & 1:
        raise ValueError("Comparison sampling with unnormalized coordinates is not supported")
    if (w0 >> 19) & 3:
        raise ValueError("Comparison sampling with MC_COORD_TRUNC or FORCE_DEGAMMA is not supported")
    if (w0 >> 29) & 3:
        raise ValueError("Comparison sampling requires the blend filter mode")
    if w1 & 0xfff:
        raise ValueError("Comparison sampling at LOD zero requires MIN_LOD 0")
    if w2 & 0xfffff:
        raise ValueError("Comparison sampling with an LOD bias is not supported")
    mag, minify, mip = (w2 >> 20) & 3, (w2 >> 22) & 3, (w2 >> 26) & 3
    if mag != minify or mag not in COMPARISON_FILTERS:
        raise ValueError("Comparison sampling requires one point or bilinear XY filter")
    if mip == 3 or w2 >> 28:
        raise ValueError("Unsupported mip filter or word 2 bits 28-31")
    if (w3 >> 12) & 0x3ffff:
        raise ValueError("Comparison sampling with word 3 bits 12-29 (UPGRADED_DEPTH on GFX8) is not supported")
    func = (w0 >> 12) & 7
    filter_name, d3d_filter = COMPARISON_FILTERS[mag]
    trunc_coord = (w0 >> 27) & 1
    if trunc_coord != (filter_name == "point"):
        raise ValueError(f"Comparison sampling with {filter_name} filtering requires TRUNC_COORD "
                         f"{int(filter_name == 'point')}")
    return {"compare": DEPTH_COMPARE[func], "d3d12_comparison_func": func + 1,
            "filter": filter_name, "d3d12_filter": d3d_filter, "address": "clamp",
            "trunc_coord": trunc_coord}


def comparison_resources(state):
    return (f"// s0 comparison sampler: D3D12_FILTER 0x{state['d3d12_filter']:x}, "
            f"D3D12_COMPARISON_FUNC {state['d3d12_comparison_func']} ({state['compare']}), address CLAMP\n"
            f"// Console TRUNC_COORD {state['trunc_coord']}. Contract: reference and texels in [0, 1] on an R32_FLOAT "
            "view; outside it the result depends on the image format, which is not decoded.\n"
            "Texture2D<float> tex : register(t0);\n"
            "SamplerComparisonState samp : register(s0);")
PREAMBLE = """// v_cmp_class_f32: the ten binary32 classes of LLVM SIInstrFlags::ClassFlags, from the raw encoding:
// signaling NaN, quiet NaN, -inf, -normal, -denormal, -0, +0, +denormal, +normal, +inf.
uint class32(float value) {
    uint bits = asuint(value);
    uint magnitude = bits & 0x7fffffffu;
    bool negative = bits >= 0x80000000u;
    if (magnitude > 0x7f800000u) return (bits & 0x00400000u) != 0u ? 0x2u : 0x1u;
    if (magnitude == 0x7f800000u) return negative ? 0x4u : 0x200u;
    if (magnitude >= 0x00800000u) return negative ? 0x8u : 0x100u;
    if (magnitude != 0u) return negative ? 0x10u : 0x80u;
    return negative ? 0x20u : 0x40u;
}
// v_cmp_class_f16: the ten binary16 classes of LLVM SIInstrFlags::ClassFlags, from bits [15:0]:
// signaling NaN, quiet NaN, -inf, -normal, -denormal, -0, +0, +denormal, +normal, +inf.
uint class16(uint bits) {
    uint h = bits & 0xffffu;
    uint magnitude = h & 0x7fffu;
    bool negative = h >= 0x8000u;
    if (magnitude > 0x7c00u) return (h & 0x0200u) != 0u ? 0x2u : 0x1u;
    if (magnitude == 0x7c00u) return negative ? 0x4u : 0x200u;
    if (magnitude >= 0x0400u) return negative ? 0x8u : 0x100u;
    if (magnitude != 0u) return negative ? 0x10u : 0x80u;
    return negative ? 0x20u : 0x40u;
}
// binary16 operand is not a NaN: decided on the encoding, because some desktop compilers fold float NaN tests.
bool num16(uint bits) {
    return (bits & 0x7fffu) <= 0x7c00u;
}
// binary32 comparison key (issue 958): an unsigned key whose order is the IEEE order of every non-NaN binary32,
// including both infinities and both zeros, which share one key. A driver compiler can bracket an fcmp with
// s_denorm_mode 14, which reads a subnormal operand as zero; an integer compare gives it nothing to bracket.
uint key32(uint bits) {
    bits = (bits & 0x7fffffffu) == 0u ? 0u : bits;
    return (bits & 0x80000000u) != 0u ? ~bits : (bits | 0x80000000u);
}
// v_med3_f32: the median of three. If any operand is NaN, the RDNA 2 ISA returns V_MIN3_F32 of the three, which with
// IEEE mode off is the smallest operand that is not NaN; desktop min and max alone would skip only the NaN operand.
// The NaN test is on the encoding, because some desktop compilers fold float NaN tests.
float med3_32(float a, float b, float c) {
    uint top = max(max(asuint(a) & 0x7fffffffu, asuint(b) & 0x7fffffffu), asuint(c) & 0x7fffffffu);
    return top > 0x7f800000u ? min(min(a, b), c) : max(min(a, b), min(max(a, b), c));
}
// v_fract_f32: x - floor(x) clamped to 0x3f7fffff, so a tiny negative input cannot round up to 1.0.
// D3D frac has no clamp and differs between adapters. NaN fails the comparison and propagates.
float fract32(float value) {
    float f = frac(value);
    return f >= 1.0f ? asfloat(0x3f7fffffu) : f;
}
// v_mad_f32 and v_mac_f32 round the product before the add and do not support binary32 denormals.
// Flush each operand, the product and the sum to signed zero; NaN fails the comparison and propagates.
float ftz32(float value) {
    return abs(value) < asfloat(0x00800000u) ? asfloat(asuint(value) & 0x80000000u) : value;
}
float mad32(float a, float b, float c) {
    precise float product = ftz32(ftz32(a) * ftz32(b));
    precise float sum = product + ftz32(c);
    return ftz32(sum);
}
// v_frexp_mant_f32: normalized significand in (-1, -0.5] U [0.5, 1), preserving +/-0, +/-Inf and NaN.
float frexp_mant32(float value) {
    uint bits = asuint(value);
    uint exp = (bits >> 23) & 0xffu;
    uint mant = bits & 0x7fffffu;
    if (exp == 0xffu || (exp == 0u && mant == 0u)) return value;
    uint sign = bits & 0x80000000u;
    if (exp == 0u) {
        uint shift = 23u - firstbithigh(mant);
        mant = (mant << shift) & 0x7fffffu;
    }
    return asfloat(sign | 0x3f000000u | mant);
}
// v_frexp_exp_i32_f32 returns the signed exponent of the normalized significand.
int frexp_exp32(float value) {
    uint magnitude = asuint(value) & 0x7fffffffu;
    uint exp = magnitude >> 23;
    if (magnitude == 0u || exp == 0xffu) return 0;
    if (exp == 0u) return (int)firstbithigh(magnitude) - 148;
    return (int)exp - 126;
}
// v_ldexp_f32: exact binary32 scaling by 2^delta, preserving +/-0, +/-Inf and NaN.
float ldexp32(float value, int delta) {
    uint bits = asuint(value);
    uint sign = bits & 0x80000000u;
    uint exp = (bits >> 23) & 0xffu;
    uint mant = bits & 0x7fffffu;
    if (exp == 0xffu || (exp == 0u && mant == 0u)) return value;
    int e = (int)exp;
    if (exp == 0u) {
        uint shift = 23u - firstbithigh(mant);
        mant = (mant << shift) & 0x7fffffu;
        e = 1 - (int)shift;
    }
    e += clamp(delta, -512, 512);
    if (e >= 255) return asfloat(sign | 0x7f800000u);
    if (e <= 0) {
        if (e < -23) return asfloat(sign);
        uint full = mant | 0x800000u;
        uint shift = (uint)(1 - e);
        uint half_bit = 1u << (shift - 1u);
        uint mask = (1u << shift) - 1u;
        uint rem = full & mask;
        uint q = full >> shift;
        if (rem > half_bit || (rem == half_bit && (q & 1u) != 0u)) q++;
        return asfloat(sign | q);
    }
    return asfloat(sign | ((uint)e << 23) | mant);
}
// v_sin_f32 and v_cos_f32 take revolutions: sin(2 * pi * x). Removing the nearest integer is exact in
// binary32 and keeps the radian argument within [-pi, pi], where D3D bounds the sin and cos error;
// x * 2 * pi on the unreduced input would round away the fraction of a large argument. Inputs of at
// most half a turn pass unchanged, so -0 keeps its sign. An infinity reduces to NaN.
float turns(float value) {
    return abs(value) > 0.5f ? value - round(value) : value;
}
float sin32(float value) {
    return sin(turns(value) * 6.28318548f);
}
float cos32(float value) {
    return cos(turns(value) * 6.28318548f);
}
// Finite binary32 to binary16, round toward zero, then widen for the float target.
float export16(float value) {
    uint h = f32tof16(value);
    if (abs(f16tof32(h)) > abs(value)) h--;
    return f16tof32(h);
}
// v_cvt_f32_f16: widen the binary16 in the low half of a word, built from its encoding so that
// desktop denormal handling cannot change it. Subnormal halves stay exact as m * 2^-24; NaN payloads widen.
float widen16(uint word) {
    uint h = word & 0xffffu;
    uint sign = (h & 0x8000u) << 16;
    uint exponent = (h >> 10) & 0x1fu;
    uint mantissa = h & 0x3ffu;
    if (exponent == 0u) {
        precise float magnitude = float(mantissa) * asfloat(0x33800000u);
        return sign != 0u ? -magnitude : magnitude;
    }
    uint wide = exponent == 0x1fu ? 0xffu : exponent + 112u;
    return asfloat(sign | (wide << 23) | (mantissa << 13));
}
// v_cvt_f16_f32: binary32 to the binary16 encoding, rounding to nearest even in integer arithmetic so that
// desktop conversion and denormal handling cannot change it. Overflow gives infinity, a binary16 subnormal
// result is kept, and a NaN keeps its sign and top payload bits with the quiet bit set.
uint narrow16(float value) {
    uint bits = asuint(value);
    uint sign = (bits >> 16) & 0x8000u;
    uint exponent = (bits >> 23) & 0xffu;
    uint mantissa = bits & 0x7fffffu;
    if (exponent == 0xffu) {
        return sign | 0x7c00u | (mantissa != 0u ? 0x200u | (mantissa >> 13) : 0u);
    }
    if (exponent < 102u) {
        return sign;
    }
    uint full = mantissa | 0x800000u;
    if (exponent < 113u) {
        uint shift = 126u - exponent;
        return sign | ((full + (1u << (shift - 1u)) - 1u + ((full >> shift) & 1u)) >> shift);
    }
    if (exponent > 142u) {
        return sign | 0x7c00u;
    }
    uint rounded = (full + 0xfffu + ((full >> 13) & 1u)) >> 13;
    return sign | min(((exponent - 113u) << 10) + rounded, 0x7c00u);
}
"""


DIV_FMAS_HELPERS = """// v_div_fmas_f32: fused multiply-add with conditional 2^32 scale when condition is true.
// Double-precision 2Sum tracks which side of a binary32 midpoint the finite sum lies on.
// Scaling is applied before conversion to binary32.
float div_fmas32_core(float s0, float s1, float s2, bool cond, bool clamp_res) {
    precise double p = (double)s0 * (double)s1;
    precise double s = p + (double)s2;
    precise double v = s - p;
    precise double err = (p - (s - v)) + ((double)s2 - v);

    double scale = cond ? 4294967296.0 : 1.0;
    precise double s_sc = s * scale;
    precise double err_sc = err * scale;

    uint u0, u1;
    asuint(s_sc, u0, u1);
    uint exp = (u1 >> 20) & 0x7ffu;
    // Binary32 subnormals retain a fixed 2^-149 spacing. The guard may
    // move into the high word or become the implicit bit at 2^-150.
    bool midpoint = false;
    if (exp >= 873u && exp <= 1150u) {
        uint discarded = exp < 897u ? 926u - exp : 29u;
        if (discarded <= 32u) {
            uint guard = 1u << (discarded - 1u);
            midpoint = (u0 & (guard | (guard - 1u))) == guard;
        } else {
            uint guard = 1u << (discarded - 33u);
            uint significand_hi = (u1 & 0x000fffffu) | 0x00100000u;
            midpoint = u0 == 0u && (significand_hi & (guard | (guard - 1u))) == guard;
        }
    }
    if (midpoint && err_sc != 0.0) {
        // Both values are finite and nonzero here, so >= matches >. The Windows 10 in-box
        // WARP faults on double ogt and ole comparisons; oge and olt run on every adapter.
        if ((s_sc >= 0.0 && err_sc >= 0.0) || (s_sc < 0.0 && err_sc < 0.0)) {
            if (++u0 == 0u) ++u1;
        } else {
            if (u0-- == 0u) --u1;
        }
        s_sc = asdouble(u0, u1);
    }
    if (clamp_res) {
        s_sc = clamp(s_sc, 0.0, 1.0);
    }
    return (float)s_sc;
}
float div_fmas32(float s0, float s1, float s2, bool cond) {
    return div_fmas32_core(s0, s1, s2, cond, false);
}
float div_fmas32_clamp(float s0, float s1, float s2, bool cond) {
    return div_fmas32_core(s0, s1, s2, cond, true);
}
"""


def registers(first, last, count):
    first, last = int(first), int(last)
    if last - first + 1 != count:
        raise ValueError("Descriptor or vector width mismatch")
    return range(first, last+1)


def vgpr_span(token, count):
    if count == 1:
        m = re.fullmatch(r"v(\d+)", token)
        if not m:
            raise ValueError(f"Expected single VGPR: {token}")
        reg = int(m[1])
        if reg > 255:
            raise ValueError(f"VGPR index out of range: {token}")
        return [f"v{reg}"]
    m = re.fullmatch(r"v\[(\d+):(\d+)\]", token)
    if not m:
        raise ValueError(f"Expected VGPR span v[first:last]: {token}")
    first, last = int(m[1]), int(m[2])
    if first > 255 or last > 255 or last - first + 1 != count:
        raise ValueError(f"Invalid VGPR span {token} for width {count}")
    return [f"v{n}" for n in range(first, last + 1)]


HINT_LIMITS = {"s_clause": 0x3f, "s_setprio": 3, "s_sleep": 0x7f, "s_incperflevel": 0xf, "s_decperflevel": 0xf,
               "s_ttracedata_imm": 0xffff}
# Operandless hints: instruction cache invalidation, a thread-trace marker that reads M0, and the wakeup of waves
# sleeping in s_sleep. None changes a register, memory or the exported result.
OPERANDLESS_HINTS = ("s_icache_inv", "s_ttracedata", "s_wakeup")

# s_setreg_imm32_b32 and s_setreg_b32 are accepted for two targets only; s_getreg_b32 reads back the first only.
# MODE[3:2] is the rounding mode shared by binary16 and binary64 results (LLVM SIDefines.h, FP_ROUND_MODE_DP):
# 0 is round to nearest even, which the binary16 lowerings assume and shader entry is taken to hold, and 3 is
# round toward zero. The directed modes 1 and 2 are refused. s_setreg_b32 writes the low `size` bits of an SGPR into
# the field (LLVM 15 SIISelLowering.cpp:4354-4417 builds SetMask = WidthMask << Offset and takes ImmVal & 0xf for the
# four-bit round field); it is accepted only when the SGPR holds a known integer that is exactly 0 or 3, the same
# values as the immediate form, so a value with higher bits set is refused rather than truncated.
# s_getreg_b32 of the field returns the field right-aligned with every other bit zero (SIISelLowering.cpp:3553-3572
# reads the one-bit TRAPSTS.MEM_VIOL field and compares the whole register with zero). The entry value of MODE is only
# assumed, so the read is accepted once the program has itself written the field, and the result is that known value.
HALF_ROUNDING = {"0": "nearest even", "3": "toward zero"}
# Under round toward zero no rounding binary16 or binary64 form has a lowering. These two do not depend on the
# mode: the widening is exact and the pack always truncates.
HALF_ROUNDING_EXEMPT = ("v_cvt_f32_f16", "v_cvt_pkrtz_f16_f32")
# MODE[7:6] (FP_DENORM_DP/16) value 3 keeps binary16 and binary64 inputs and results denormal. The state is not
# tracked: the caller declares it for the shader entry with lower(half_denorm="preserve"), taking it from validated
# guest state. None (the default) means unknown, and the plain binary16 arithmetic forms are then refused. Every
# MODE write other than the rounding field is refused above, so a declared entry state cannot change in the program.
# The lowering itself never reads MODE; the declaration only scopes the claim to preserved denormals.
HALF_DENORM_PRESERVE = "preserve"
# FLAT_SCR_LO and FLAT_SCR_HI hold the scratch base address. Only scratch_* and flat_* memory instructions and
# s_getreg_b32 can observe it. scratch_* and s_getreg_b32 of these registers are not lowered, and the one lowered flat
# form, flat_load_dword, reads only through the title ranges below (no private aperture), so a whole-register write
# (an immediate or any SGPR value) changes no result.
FLAT_SCRATCH = ("HW_REG_FLAT_SCR_LO", "HW_REG_FLAT_SCR_HI")

# flat_load_dword and global_load_dword with `off` read one DWORD at a 64-bit title address: the address pair
# plus the instruction offset, sign-extended to 64 bits with the carry or borrow taken into the high word.
# TitleLookup (src/title_va_lookup.hlsli) finds the range holding the whole DWORD; the load then reads that
# range's aliased buffer at the byte offset. An address in no range, a DWORD that does not lie inside a single
# range and a misaligned address read TITLE_MISS instead of zero. The range count is fixed at translation time
# (lower(title_ranges=...)), and TITLE_ALIAS_SLOTS bounds the aliased descriptors; a slot past it also reads
# TITLE_MISS. LLVM 15 assembles gfx1013 flat offsets as 11-bit unsigned and global offsets as 12-bit signed.
TITLE_ALIAS_SLOTS = 8
TITLE_MISS = 0xdeadbeef
TITLE_OFFSETS = {"flat": range(0, 2048), "global": range(-2048, 2048)}
TITLE_MEMORY = """StructuredBuffer<TitleRange> TitleRanges : register(t0, space1);
ByteAddressBuffer TitleAliases[{slots}] : register(t1, space1);
static const uint TITLE_RANGE_COUNT = {count}u;
// The DWORD at base + offset, where offset is the instruction offset sign-extended to 64 bits.
uint title_load_dword(uint2 base, uint2 offset)
{{
    const uint low = base.x + offset.x;
    const uint2 address = uint2(low, base.y + offset.y + (low < base.x ? 1u : 0u));
    uint slot;
    uint byteOffset;
    if (!TitleLookup(TitleRanges, TITLE_RANGE_COUNT, address, 4, slot, byteOffset) || slot >= {slots}u) {{
        return {miss:#x}u;
    }}
    return TitleAliases[NonUniformResourceIndex(slot)].Load(byteOffset);
}}
"""

ALU = {
    "log": (1, "log2({0})"), "exp": (1, "exp2({0})"), "rcp": (1, "(1.0f / {0})"),
    # Same reciprocal; the integer-divide flag it raises has no desktop equivalent.
    "rcp_iflag": (1, "(1.0f / {0})"),
    "sqrt": (1, "sqrt({0})"), "rsq": (1, "rsqrt({0})"),
    "floor": (1, "floor({0})"), "ceil": (1, "ceil({0})"), "fract": (1, "fract32({0})"),
    "trunc": (1, "trunc({0})"), "frexp_mant": (1, "frexp_mant32({0})"),
    "rndne": (1, "round({0})"),  # HLSL round is DXIL Round_ne: ties to even
    "sin": (1, "sin32({0})"), "cos": (1, "cos32({0})"),
    "add": (2, "({0} + {1})"), "mul": (2, "({0} * {1})"),
    "max": (2, "max({0}, {1})"), "min": (2, "min({0}, {1})"), "sub": (2, "({0} - {1})"),
    "subrev": (2, "({1} - {0})"),
    "mul_legacy": (2, "(({0} == 0 || {1} == 0) ? 0.0f : {0} * {1})"),
    # Legacy multiply, then an unfused add: 0 * x is 0 even for an infinite or NaN x.
    "mad_legacy": (3, "((({0} == 0 || {1} == 0) ? 0.0f : {0} * {1}) + {2})"),
    # The same, with the destination as the accumulator operand (LLVM 15 VOP2Instructions.td: VOP_MAC_LEGACY_F32).
    "mac_legacy": (3, "((({0} == 0 || {1} == 0) ? 0.0f : {0} * {1}) + {2})"),
    "fma": (3, "mad({0}, {1}, {2})"), "fmac": (3, "mad({0}, {1}, {2})"),
    "mad": (3, "mad32({0}, {1}, {2})"), "mac": (3, "mad32({0}, {1}, {2})"),
    # Each result is one of the operands, so finite inputs need no rounding.
    "min3": (3, "min(min({0}, {1}), {2})"), "max3": (3, "max(max({0}, {1}), {2})"),
    "med3": (3, "med3_32({0}, {1}, {2})"),
}
# LLVM 15 sets HasExtDPP = 0 for v_mac_legacy_f32, and fma, mad, mad_legacy, min3, max3 and med3 are VOP3-only, so
# none of them has a DPP form (llvm-mc for gfx1013: "dpp variant of this instruction is not supported").
DPP_ALU = {k: v for k, v in ALU.items() if k not in ("fma", "mac_legacy", "mad", "mad_legacy", "min3", "max3", "med3")}
# N-prefixed predicates include unordered operands. Keep NLG's NaN case explicit in DXIL.
COMPARE = {
    "f": "false", "tru": "true",
    "lt": "{0} < {1}", "eq": "{0} == {1}", "le": "{0} <= {1}", "gt": "{0} > {1}",
    "lg": "({0} < {1} || {0} > {1})", "ge": "{0} >= {1}",
    "o": "({0} == {0} && {1} == {1})", "u": "({0} != {0} || {1} != {1})",
    "nge": "({0} < {1} || isnan({0}) || isnan({1}))", "nlg": "({0} == {1} || isnan({0}) || isnan({1}))",
    "ngt": "({0} <= {1} || isnan({0}) || isnan({1}))", "nle": "({0} > {1} || isnan({0}) || isnan({1}))",
    "neq": "!({0} == {1})", "nlt": "({0} >= {1} || isnan({0}) || isnan({1}))",
}
# The six ordered binary32 relations, decided on the key32 encoding order instead of a float comparison (issue 958).
F32_KEY_COMPARE = {
    "lt": "{0} < {1}", "eq": "{0} == {1}", "le": "{0} <= {1}",
    "gt": "{0} > {1}", "lg": "{0} != {1}", "ge": "{0} >= {1}",
}
INT_COMPARE = {
    "f": "false", "lt": "{0} < {1}", "eq": "{0} == {1}", "le": "{0} <= {1}",
    "gt": "{0} > {1}", "ne": "{0} != {1}", "ge": "{0} >= {1}", "t": "true",
}
# 64-bit comparisons from the (low, high) words. The high words decide unless equal; a signed high word is an int.
INT64_COMPARE = {
    "f": "false", "t": "true",
    "lt": "({h0} < {h1}) || ({h0} == {h1} && {l0} < {l1})",
    "le": "({h0} < {h1}) || ({h0} == {h1} && {l0} <= {l1})",
    "gt": "({h0} > {h1}) || ({h0} == {h1} && {l0} > {l1})",
    "ge": "({h0} > {h1}) || ({h0} == {h1} && {l0} >= {l1})",
    "eq": "{h0} == {h1} && {l0} == {l1}",
    "ne": "!({h0} == {h1} && {l0} == {l1})",
}
# 32-bit integer operations on register bits. Shift counts use their low five bits, as on the target.
INTEGER = {
    "and_b32": (2, "{0} & {1}"), "or_b32": (2, "{0} | {1}"), "xor_b32": (2, "{0} ^ {1}"),
    "xnor_b32": (2, "~({0} ^ {1})"),
    "not_b32": (1, "~{0}"), "bfi_b32": (3, "({0} & {1}) | (~{0} & {2})"),
    # Copies the low binary16 encoding of each source into one half of the destination, with no conversion,
    # rounding or NaN handling (AMD RDNA ISA reference, VOP3OpSel: D[15:0].f16 = S0.f16, D[31:16].f16 = S1.f16).
    "pack_b32_f16": (2, "({0} & 0xffffu) | (({1} & 0xffffu) << 16)"),
    # Saturating packs: src0 gives the low and src1 the high 16 bits (AMD RDNA 2 ISA reference, VOP3 opcodes
    # 874 and 875). The ISA text does not define its conversion functions; the bounds are the clamp Mesa
    # documents for the NIR operations its ACO backend selects these instructions for.
    "cvt_pk_u16_u32": (2, "min({0}, 65535u) | (min({1}, 65535u) << 16u)"),
    "cvt_pk_i16_i32": (2, "(asuint(clamp(asint({0}), -32768, 32767)) & 0xffffu) | "
                          "(asuint(clamp(asint({1}), -32768, 32767)) << 16u)"),
    # Clamp both signed halfwords independently and write a full dword with bits 31:16 clear.
    "sat_pk_u8_i16": (1, "uint(clamp(asint({0} << 16) >> 16, 0, 255)) | "
                         "(uint(clamp(asint({0}) >> 16, 0, 255)) << 8)"),
    "alignbit_b32": (3, "(({2} & 31u) == 0u ? {1} : (({1} >> ({2} & 31u)) | ({0} << (32u - ({2} & 31u)))))"),
    "alignbyte_b32": (3, "(({2} & 3u) == 0u ? {1} : (({1} >> (({2} & 3u) * 8u)) | ({0} << (32u - (({2} & 3u) * 8u)))))"),
    "add3_u32": (3, "({0} + {1} + {2})"),
    "or3_b32": (3, "({0} | {1} | {2})"),
    "xor3_b32": (3, "({0} ^ {1} ^ {2})"),
    "and_or_b32": (3, "(({0} & {1}) | {2})"),
    "xad_u32": (3, "(({0} ^ {1}) + {2})"),
    "lshl_or_b32": (3, "(({0} << ({1} & 31u)) | {2})"),
    "lshl_add_u32": (3, "(({0} << ({1} & 31u)) + {2})"),
    "add_lshl_u32": (3, "(({0} + {1}) << ({2} & 31u))"),
    "lshlrev_b32": (2, "{1} << ({0} & 31u)"), "lshrrev_b32": (2, "{1} >> ({0} & 31u)"),
    "ashrrev_i32": (2, "asuint(asint({1}) >> ({0} & 31u))"),
    "mul_u32_u24": (2, "mul24_u32({0}, {1})"),
    "mul_i32_i24": (2, "mul24_i32({0}, {1})"),
    "mul_hi_u32_u24": (2, "mul24_hi_u32({0}, {1})"),
    "mul_hi_i32_i24": (2, "mul24_hi_i32({0}, {1})"),
    "mul_lo_u32": (2, "({0} * {1})"),
    "bfrev_b32": (1, "reversebits({0})"), "ffbl_b32": (1, "firstbitlow({0})"),
    "ffbh_u32": (1, "dpp_ffbh_u32({0})"), "ffbh_i32": (1, "dpp_ffbh_i32({0})"),
    "bfe_u32": (3, "(({0} >> ({1} & 31u)) & ((1u << ({2} & 31u)) - 1u))"),
    "bfe_i32": (3, "s_bfe_i32({0}, ({1} & 31u) | (({2} & 31u) << 16u))"),
    "bfm_b32": (2, "(((1u << ({0} & 31u)) - 1u) << ({1} & 31u))"),
    "bcnt_u32_b32": (2, "(countbits({0}) + {1})"),
    # Sums of absolute differences, all unsigned and modulo 2^32 (AMD RDNA 2 ISA reference, VOP3 opcodes 346 to
    # 349 and 369). src1 is the reference: v_msad_u8 leaves out each byte lane whose src1 byte is zero.
    "sad_u8": (3, "sad4_u8({0}, {1}, false) + {2}"),
    "sad_hi_u8": (3, "(sad4_u8({0}, {1}, false) << 16u) + {2}"),
    "sad_u16": (3, "sad2_u16({0}, {1}) + {2}"),
    "sad_u32": (3, "(max({0}, {1}) - min({0}, {1})) + {2}"),
    "msad_u8": (3, "sad4_u8({0}, {1}, true) + {2}"),
}
# The ffbh helpers are the ones the DPP spellings use (DPP_INT32); the definitions live in SALU_HELPERS.
INTEGER_HELPERS = {"ffbh_u32": ("dpp_ffbh_u32",), "ffbh_i32": ("dpp_ffbh_i32",), "bfe_i32": ("s_bfe_i32",)}
# v_add_co_u32, v_sub_co_u32 and v_subrev_co_u32 as (32-bit result, carry-out written to the lane mask).
# The add carries when the 33-bit sum does not fit, which is when the wrapped sum {r} is below src0. The
# subtracts borrow when the subtrahend is above the minuend; subrev computes src1 - src0.
CARRY_OUT = {
    "add": ("{0} + {1}", "{r} < {0}"),
    "sub": ("{0} - {1}", "{1} > {0}"),
    "subrev": ("{1} - {0}", "{0} > {1}"),
}
# v_add_co_ci_u32, v_sub_co_ci_u32 and v_subrev_co_ci_u32 as (partial result {p} of the two sources, result {r}
# after the carry-in {c}, carry-out). The add carries when either step wraps. The subtracts borrow when the
# subtrahend is above the minuend or the borrow-in is above the partial difference, which together is when
# subtrahend + borrow-in exceeds the minuend; subrev computes src1 - src0 - borrow-in.
CARRY_IN = {
    "add": ("{0} + {1}", "{p} + {c}", "{p} < {0} || {r} < {p}"),
    "sub": ("{0} - {1}", "{p} - {c}", "{1} > {0} || {c} > {p}"),
    "subrev": ("{1} - {0}", "{p} - {c}", "{0} > {1} || {c} > {p}"),
}
MUL24_HELPERS = {
    "mul_u32_u24": ("mul24_u32",),
    "mul_i32_i24": ("mul24_i32",),
    "mul_hi_u32_u24": ("mul24_hi_u32",),
    "mul_hi_i32_i24": ("mul24_hi_u32", "mul24_hi_i32"),
}
# Two-source integer operations that exist in the VOP3 encoding only on gfx10.
INTEGER_VOP3_ONLY = ("cvt_pk_u16_u32", "cvt_pk_i16_i32", "bfm_b32", "bcnt_u32_b32", "pack_b32_f16")
SAD_HELPERS = {"sad_u8": ("sad4_u8",), "sad_hi_u8": ("sad4_u8",), "sad_u16": ("sad2_u16",), "msad_u8": ("sad4_u8",)}
LANE_MASK = r"(vcc(?:_lo)?|s\d+|s\[\d+:\d+\])"


def check_vopc_e32_dst(enc, dst):
    # VOPC e32 writes VCC only; LLVM rejects an SGPR destination on the explicit spelling.
    if enc == "_e32" and dst not in ("vcc", "vcc_lo"):
        raise ValueError("VOPC e32 destination must be vcc")


SALU_BIT64 = {
    "and": "uint2({0} & {2}, {1} & {3})",
    "or": "uint2({0} | {2}, {1} | {3})",
    "xor": "uint2({0} ^ {2}, {1} ^ {3})",
    "andn2": "uint2({0} & ~{2}, {1} & ~{3})",
    "orn2": "uint2({0} | ~{2}, {1} | ~{3})",
    "nand": "uint2(~({0} & {2}), ~({1} & {3}))",
    "nor": "uint2(~({0} | {2}), ~({1} | {3}))",
    "xnor": "uint2(~({0} ^ {2}), ~({1} ^ {3}))",
}
SALU_HELPERS = {
    "scalar_mul_hi": """uint mul_hi_u32(uint a, uint b) {
    // Carry the low halfword product into the two cross products.
    uint low_a = a & 0xffffu;
    uint low_b = b & 0xffffu;
    uint middle = (a >> 16) * low_b + ((low_a * low_b) >> 16);
    return (a >> 16) * (b >> 16) + (middle >> 16)
         + (((middle & 0xffffu) + low_a * (b >> 16)) >> 16);
}
uint mul_hi_i32(uint a, uint b) {
    // Reinterpreting either operand as signed subtracts its partner from the high word.
    return mul_hi_u32(a, b) - ((a >> 31) != 0u ? b : 0u) - ((b >> 31) != 0u ? a : 0u);
}
""",
    "cmp_f64": """// v_cmp_*_f64 and v_cmp_class_f64 on the raw (low, high) words of binary64 sources; no HLSL double is used.
// num64: the encoding is not a NaN. key64: an unsigned (low, high) key with the order of the non-NaN values, in
// which -0 and +0 share one key; the high words decide unless equal. Denormals compare as their values.
bool num64(uint lo, uint hi) {
    uint magnitude = hi & 0x7fffffffu;
    return magnitude < 0x7ff00000u || (magnitude == 0x7ff00000u && lo == 0u);
}
uint2 key64(uint lo, uint hi) {
    if (((hi & 0x7fffffffu) | lo) == 0u) return uint2(0u, 0x80000000u);
    return hi >= 0x80000000u ? uint2(~lo, ~hi) : uint2(lo, hi | 0x80000000u);
}
bool lt64(uint2 a, uint2 b) {
    return a.y < b.y || (a.y == b.y && a.x < b.x);
}
bool eq64(uint2 a, uint2 b) {
    return a.y == b.y && a.x == b.x;
}
// The ten binary64 classes of LLVM SIInstrFlags::ClassFlags, in the order of class32.
uint class64(uint lo, uint hi) {
    uint magnitude = hi & 0x7fffffffu;
    bool negative = hi >= 0x80000000u;
    if (!num64(lo, hi)) return (hi & 0x00080000u) != 0u ? 0x2u : 0x1u;
    if (magnitude == 0x7ff00000u) return negative ? 0x4u : 0x200u;
    if (magnitude >= 0x00100000u) return negative ? 0x8u : 0x100u;
    if ((magnitude | lo) != 0u) return negative ? 0x10u : 0x80u;
    return negative ? 0x20u : 0x40u;
}""",
    "s_lshl_b64": (
        "uint2 s_lshl_b64(uint2 v, uint s) {\n"
        "    s &= 63u;\n"
        "    if (s == 0u) return v;\n"
        "    if (s < 32u) return uint2(v.x << s, (v.y << s) | (v.x >> (32u - s)));\n"
        "    return uint2(0u, v.x << (s - 32u));\n"
        "}"
    ),
    "s_lshr_b64": (
        "uint2 s_lshr_b64(uint2 v, uint s) {\n"
        "    s &= 63u;\n"
        "    if (s == 0u) return v;\n"
        "    if (s < 32u) return uint2((v.x >> s) | (v.y << (32u - s)), v.y >> s);\n"
        "    return uint2(v.y >> (s - 32u), 0u);\n"
        "}"
    ),
    "s_ashr_i64": (
        "uint2 s_ashr_i64(uint2 v, uint s) {\n"
        "    s &= 63u;\n"
        "    if (s == 0u) return v;\n"
        "    if (s < 32u) return uint2((v.x >> s) | (v.y << (32u - s)), asuint(asint(v.y) >> s));\n"
        "    return uint2(asuint(asint(v.y) >> (s - 32u)), asuint(asint(v.y) >> 31));\n"
        "}"
    ),
    "s_quadmask_b32": """uint s_quadmask_b32(uint value) {
    uint result = 0u;
    [unroll]
    for (uint group = 0u; group < 8u; ++group) {
        if ((value & (0xfu << (group * 4u))) != 0u) result |= 1u << group;
    }
    return result;
}
""",
    "s_quadmask_b64": """uint2 s_quadmask_b64(uint2 value) {
    uint result = s_quadmask_b32(value.x) | (s_quadmask_b32(value.y) << 8u);
    return uint2(result, 0u);
}
""",
    "s_bitreplicate_b64_b32": """uint2 s_bitreplicate_b64_b32(uint value) {
    uint low = value & 0xffffu;
    uint high = value >> 16u;
    low = (low | (low << 8u)) & 0x00ff00ffu;
    high = (high | (high << 8u)) & 0x00ff00ffu;
    low = (low | (low << 4u)) & 0x0f0f0f0fu;
    high = (high | (high << 4u)) & 0x0f0f0f0fu;
    low = (low | (low << 2u)) & 0x33333333u;
    high = (high | (high << 2u)) & 0x33333333u;
    low = (low | (low << 1u)) & 0x55555555u;
    high = (high | (high << 1u)) & 0x55555555u;
    return uint2(low | (low << 1u), high | (high << 1u));
}
""",
    "s_bfm_b64": (
        "uint2 s_bfm_b64(uint width, uint offset) {\n"
        "    uint w = width & 63u;\n"
        "    uint2 m = uint2(0u, 0u);\n"
        "    if (w > 0u && w < 32u) m = uint2((1u << w) - 1u, 0u);\n"
        "    else if (w == 32u) m = uint2(0xffffffffu, 0u);\n"
        "    else if (w > 32u) m = uint2(0xffffffffu, (1u << (w - 32u)) - 1u);\n"
        "    return s_lshl_b64(m, offset);\n"
        "}"
    ),
    "s_bfe_u32": (
        "uint s_bfe_u32(uint src, uint ctrl) {\n"
        "    uint off = ctrl & 31u;\n"
        "    uint w = (ctrl >> 16) & 127u;\n"
        "    if (w == 0u) return 0u;\n"
        "    if (off + w < 32u) return (src << (32u - off - w)) >> (32u - w);\n"
        "    return src >> off;\n"
        "}"
    ),
    "s_bfe_i32": (
        "uint s_bfe_i32(uint src, uint ctrl) {\n"
        "    uint off = ctrl & 31u;\n"
        "    uint w = (ctrl >> 16) & 127u;\n"
        "    if (w == 0u) return 0u;\n"
        "    if (off + w < 32u) return asuint(asint(src << (32u - off - w)) >> (32u - w));\n"
        "    return asuint(asint(src) >> off);\n"
        "}"
    ),
    "dpp_frexp_mant_f32": (
        "float dpp_frexp_mant_f32(uint bits) {\n"
        "    uint exp = (bits >> 23) & 0xffu;\n"
        "    uint mant = bits & 0x7fffffu;\n"
        "    if (exp == 0xffu || (exp == 0u && mant == 0u)) return asfloat(bits);\n"
        "    uint sign = bits & 0x80000000u;\n"
        "    if (exp == 0u) {\n"
        "        uint shift = 23u - firstbithigh(mant);\n"
        "        mant = (mant << shift) & 0x7fffffu;\n"
        "    }\n"
        "    return asfloat(sign | 0x3f000000u | mant);\n"
        "}"
    ),
    "dpp_frexp_exp_i32_f32": (
        "uint dpp_frexp_exp_i32_f32(uint bits) {\n"
        "    uint exp = (bits >> 23) & 0xffu;\n"
        "    uint mant = bits & 0x7fffffu;\n"
        "    if (exp == 0xffu || (exp == 0u && mant == 0u)) return 0u;\n"
        "    if (exp == 0u) return asuint(int(firstbithigh(mant)) - 148);\n"
        "    return asuint(int(exp) - 126);\n"
        "}"
    ),
    "dpp_dot4c_i32_i8": (
        "uint dpp_dot4c_i32_i8(uint a, uint b, uint acc) {\n"
        "    int s0 = (asint(a << 24) >> 24) * (asint(b << 24) >> 24);\n"
        "    int s1 = (asint(a << 16) >> 24) * (asint(b << 16) >> 24);\n"
        "    int s2 = (asint(a << 8) >> 24) * (asint(b << 8) >> 24);\n"
        "    int s3 = (asint(a) >> 24) * (asint(b) >> 24);\n"
        "    return acc + asuint(s0) + asuint(s1) + asuint(s2) + asuint(s3);\n"
        "}"
    ),
    "s_bfe64": (
        "uint2 s_bfe64(uint2 src, uint ctrl, bool is_signed) {\n"
        "    uint offset = ctrl & 63u;\n"
        "    uint width = min((ctrl >> 16) & 127u, 64u - offset);\n"
        "    if (width == 0u) return uint2(0u, 0u);\n"
        "    uint right = 64u - width;\n"
        "    uint2 aligned = s_lshl_b64(src, right - offset);\n"
        "    return is_signed ? s_ashr_i64(aligned, right) : s_lshr_b64(aligned, right);\n"
        "}"
    ),
    "dpp_ffbh_u32": (
        "uint dpp_ffbh_u32(uint x) {\n"
        "    return x == 0u ? 0xffffffffu : (31u - firstbithigh(x));\n"
        "}"
    ),
    "dpp_ffbh_i32": (
        "uint dpp_ffbh_i32(uint x) {\n"
        "    uint m = asint(x) < 0 ? ~x : x;\n"
        "    return m == 0u ? 0xffffffffu : (31u - firstbithigh(m));\n"
        "}"
    ),
    "dpp_mul_hi_u24": (
        "uint dpp_mul_hi_u24(uint a, uint b) {\n"
        "    a &= 0xffffffu;\n"
        "    b &= 0xffffffu;\n"
        "    uint a0 = a & 0xfffu, a1 = a >> 12;\n"
        "    uint b0 = b & 0xfffu, b1 = b >> 12;\n"
        "    uint p0 = a0 * b0;\n"
        "    uint mid = a0 * b1 + a1 * b0 + (p0 >> 12);\n"
        "    uint p2 = a1 * b1 + (mid >> 12);\n"
        "    return p2 >> 8;\n"
        "}"
    ),
    "dpp_mul_hi_i24": (
        "uint dpp_mul_hi_i24(uint a, uint b) {\n"
        "    int sa = asint(a << 8) >> 8;\n"
        "    int sb = asint(b << 8) >> 8;\n"
        "    uint ma = asuint(sa < 0 ? -sa : sa);\n"
        "    uint mb = asuint(sb < 0 ? -sb : sb);\n"
        "    uint a0 = ma & 0xfffu, a1 = ma >> 12;\n"
        "    uint b0 = mb & 0xfffu, b1 = mb >> 12;\n"
        "    uint p0 = a0 * b0;\n"
        "    uint mid = a0 * b1 + a1 * b0 + (p0 >> 12);\n"
        "    uint p2 = a1 * b1 + (mid >> 12);\n"
        "    uint mag_lo = (p0 & 0xfffu) | ((mid & 0xfffu) << 12) | ((p2 & 0xffu) << 24);\n"
        "    uint mag_hi = p2 >> 8;\n"
        "    if ((sa < 0) != (sb < 0)) return ~mag_hi + (mag_lo == 0u ? 1u : 0u);\n"
        "    return mag_hi;\n"
        "}"
    ),
    "pack16_rne": (
        "// IEEE binary32 to binary16, round to nearest even, independent of driver f32tof16 rounding.\n"
        "uint pack16_rne(float value) {\n"
        "    uint bits = asuint(value);\n"
        "    uint sign = (bits >> 16) & 0x8000u;\n"
        "    uint abs_bits = bits & 0x7fffffffu;\n"
        "    if (abs_bits > 0x7f800000u) return 0x7e00u;\n"
        "    if (abs_bits >= 0x477ff000u) return sign | 0x7c00u;\n"
        "    if (abs_bits >= 0x38800000u) {\n"
        "        uint shifted = abs_bits - 0x38000000u;\n"
        "        uint round_bit = 0x00000fffu + ((shifted >> 13) & 1u);\n"
        "        return sign | ((shifted + round_bit) >> 13);\n"
        "    }\n"
        "    if (abs_bits < 0x33000000u) return sign;\n"
        "    uint sig = 0x00800000u | (abs_bits & 0x007fffffu);\n"
        "    uint shift = 126u - (abs_bits >> 23);\n"
        "    uint half_m = sig >> shift;\n"
        "    uint rem = sig & ((1u << shift) - 1u);\n"
        "    uint mid = 1u << (shift - 1u);\n"
        "    if (rem > mid || (rem == mid && (half_m & 1u) != 0u)) half_m += 1u;\n"
        "    return sign | half_m;\n"
        "}"
    ),
    "fma16_rne": (
        "// Exact fused binary16 multiply-accumulate (a * b + c), rounding once to binary16 RNE.\n"
        "// Operates on finite binary16 encodings in bits [15:0] using 32-bit integer arithmetic only,\n"
        "// avoiding intermediate binary32 rounding and remaining independent of binary32 FTZ modes.\n"
        "uint fma16_rne(uint a_bits, uint b_bits, uint c_bits) {\n"
        "    uint a = a_bits & 0xffffu;\n"
        "    uint b = b_bits & 0xffffu;\n"
        "    uint c = c_bits & 0xffffu;\n"
        "    uint sa = (a >> 15u) & 1u;\n"
        "    uint ea_f = (a >> 10u) & 31u;\n"
        "    uint ma = (a & 0x3ffu) | (ea_f != 0u ? 0x400u : 0u);\n"
        "    int ea = ea_f != 0u ? (int)ea_f - 25 : -24;\n"
        "    uint sb = (b >> 15u) & 1u;\n"
        "    uint eb_f = (b >> 10u) & 31u;\n"
        "    uint mb = (b & 0x3ffu) | (eb_f != 0u ? 0x400u : 0u);\n"
        "    int eb = eb_f != 0u ? (int)eb_f - 25 : -24;\n"
        "    uint sc = (c >> 15u) & 1u;\n"
        "    uint ec_f = (c >> 10u) & 31u;\n"
        "    uint mc = (c & 0x3ffu) | (ec_f != 0u ? 0x400u : 0u);\n"
        "    int ec = ec_f != 0u ? (int)ec_f - 25 : -24;\n"
        "    uint sp = sa ^ sb;\n"
        "    uint mp = ma * mb;\n"
        "    int ep = ea + eb;\n"
        "    if (mp == 0u && mc == 0u) return (sp != 0u && sc != 0u) ? 0x8000u : 0u;\n"
        "    if (mp == 0u) return c;\n"
        "    uint norm;\n"
        "    int res_exp;\n"
        "    uint res_sign;\n"
        "    if (mc == 0u) {\n"
        "        uint top = firstbithigh(mp);\n"
        "        norm = mp << (31u - top);\n"
        "        res_exp = ep + (int)top;\n"
        "        res_sign = sp;\n"
        "    } else {\n"
        "        uint bp = firstbithigh(mp);\n"
        "        uint px = mp << (30u - bp);\n"
        "        int ex = ep + (int)bp;\n"
        "        uint bc = firstbithigh(mc);\n"
        "        uint cx = mc << (30u - bc);\n"
        "        int ey = ec + (int)bc;\n"
        "        uint big_m, small_m, big_s, small_s;\n"
        "        int big_e, small_e;\n"
        "        if (ex > ey || (ex == ey && px >= cx)) {\n"
        "            big_m = px; big_e = ex; big_s = sp;\n"
        "            small_m = cx; small_e = ey; small_s = sc;\n"
        "        } else {\n"
        "            big_m = cx; big_e = ey; big_s = sc;\n"
        "            small_m = px; small_e = ex; small_s = sp;\n"
        "        }\n"
        "        if (big_e == small_e && big_m == small_m && big_s != small_s) return 0u;\n"
        "        uint diff_e = (uint)(big_e - small_e);\n"
        "        uint y_main = 0u;\n"
        "        uint y_sticky = 1u;\n"
        "        if (diff_e < 30u) {\n"
        "            y_main = (small_m >> diff_e) & 0xfffffffeu;\n"
        "            y_sticky = (small_m & ((1u << (diff_e + 1u)) - 1u)) != 0u ? 1u : 0u;\n"
        "        }\n"
        "        res_sign = big_s;\n"
        "        uint mag = big_s == small_s ? (big_m + y_main + y_sticky) : (big_m - y_main - y_sticky);\n"
        "        uint top = firstbithigh(mag);\n"
        "        norm = mag << (31u - top);\n"
        "        res_exp = big_e + (int)top - 30;\n"
        "    }\n"
        "    if (res_exp >= -14) {\n"
        "        uint sig = norm >> 21u;\n"
        "        uint rem = norm & 0x001fffffu;\n"
        "        if (rem > 0x00100000u || (rem == 0x00100000u && (sig & 1u) != 0u)) sig += 1u;\n"
        "        if (sig == 0x800u) {\n"
        "            sig = 0x400u;\n"
        "            res_exp += 1;\n"
        "        }\n"
        "        if (res_exp > 15) return (res_sign << 15u) | 0x7c00u;\n"
        "        return (res_sign << 15u) | ((uint)(res_exp + 15) << 10u) | (sig & 0x3ffu);\n"
        "    }\n"
        "    if (res_exp == -25) return (res_sign << 15u) | (norm > 0x80000000u ? 1u : 0u);\n"
        "    if (res_exp < -25) return res_sign << 15u;\n"
        "    uint shift = (uint)(7 - res_exp);\n"
        "    uint sig = norm >> shift;\n"
        "    uint half_bit = 1u << (shift - 1u);\n"
        "    uint mask = (1u << shift) - 1u;\n"
        "    uint rem = norm & mask;\n"
        "    if (rem > half_bit || (rem == half_bit && (sig & 1u) != 0u)) sig += 1u;\n"
        "    return (res_sign << 15u) | sig;\n"
        "}"
    ),
    "min16_num": (
        "float min16_num(float a, float b) {\n"
        "    return isnan(a) ? b : (isnan(b) ? a : min(a, b));\n"
        "}"
    ),
    "max16_num": (
        "float max16_num(float a, float b) {\n"
        "    return isnan(a) ? b : (isnan(b) ? a : max(a, b));\n"
        "}"
    ),
    "dot_u64_add": (
        "uint2 dot_u64_add(uint2 acc, uint v) {\n"
        "    uint lo = acc.x + v;\n"
        "    return uint2(lo, acc.y + (lo < acc.x ? 1u : 0u));\n"
        "}"
    ),
    "dot_u64_sat": (
        "uint dot_u64_sat(uint2 s) {\n"
        "    return s.y != 0u ? 0xffffffffu : s.x;\n"
        "}"
    ),
    "dot_i64_add": (
        "uint2 dot_i64_add(uint2 acc, int v) {\n"
        "    uint uv = asuint(v);\n"
        "    uint lo = acc.x + uv;\n"
        "    uint hi = acc.y + (v < 0 ? 0xffffffffu : 0u) + (lo < acc.x ? 1u : 0u);\n"
        "    return uint2(lo, hi);\n"
        "}"
    ),
    "dot_i64_sat": (
        "uint dot_i64_sat(uint2 s) {\n"
        "    if (asint(s.y) > 0 || (s.y == 0u && s.x > 0x7fffffffu)) return 0x7fffffffu;\n"
        "    if (asint(s.y) < -1 || (s.y == 0xffffffffu && s.x < 0x80000000u)) return 0x80000000u;\n"
        "    return s.x;\n"
        "}"
    ),
    "v_dot2_i32_i16": (
        "uint v_dot2_i32_i16(uint a0, uint a1, uint b0, uint b1, uint c, bool sat) {\n"
        "    int p0 = (asint(a0 << 16) >> 16) * (asint(b0 << 16) >> 16);\n"
        "    int p1 = (asint(a1 << 16) >> 16) * (asint(b1 << 16) >> 16);\n"
        "    uint2 s = dot_i64_add(dot_i64_add(dot_i64_add(uint2(0u, 0u), asint(c)), p0), p1);\n"
        "    return sat ? dot_i64_sat(s) : s.x;\n"
        "}"
    ),
    "v_dot2_u32_u16": (
        "uint v_dot2_u32_u16(uint a0, uint a1, uint b0, uint b1, uint c, bool sat) {\n"
        "    uint p0 = (a0 & 0xffffu) * (b0 & 0xffffu);\n"
        "    uint p1 = (a1 & 0xffffu) * (b1 & 0xffffu);\n"
        "    uint2 s = dot_u64_add(dot_u64_add(uint2(c, 0u), p0), p1);\n"
        "    return sat ? dot_u64_sat(s) : s.x;\n"
        "}"
    ),
    "v_dot4_i32_i8": (
        "uint v_dot4_i32_i8(uint a, uint b, uint c, bool sat) {\n"
        "    int sum = 0;\n"
        "    for (uint k = 0u; k < 4u; ++k) {\n"
        "        int x = asint(((a >> (k * 8u)) & 0xffu) << 24) >> 24;\n"
        "        int y = asint(((b >> (k * 8u)) & 0xffu) << 24) >> 24;\n"
        "        sum += x * y;\n"
        "    }\n"
        "    uint r = c + asuint(sum);\n"
        "    if (sat && asint(c) >= 0x40000000 && asint(r) < 0) return 0x7fffffffu;\n"
        "    if (sat && asint(c) < -0x40000000 && asint(r) >= 0) return 0x80000000u;\n"
        "    return r;\n"
        "}"
    ),
    "v_dot4_u32_u8": (
        "uint v_dot4_u32_u8(uint a, uint b, uint c, bool sat) {\n"
        "    uint sum = 0u;\n"
        "    for (uint k = 0u; k < 4u; ++k) {\n"
        "        sum += ((a >> (k * 8u)) & 0xffu) * ((b >> (k * 8u)) & 0xffu);\n"
        "    }\n"
        "    uint2 s = dot_u64_add(uint2(c, 0u), sum);\n"
        "    return sat ? dot_u64_sat(s) : s.x;\n"
        "}"
    ),
    "v_dot8_i32_i4": (
        "uint v_dot8_i32_i4(uint a, uint b, uint c, bool sat) {\n"
        "    int sum = 0;\n"
        "    for (uint k = 0u; k < 8u; ++k) {\n"
        "        int x = asint(((a >> (k * 4u)) & 0xfu) << 28) >> 28;\n"
        "        int y = asint(((b >> (k * 4u)) & 0xfu) << 28) >> 28;\n"
        "        sum += x * y;\n"
        "    }\n"
        "    uint r = c + asuint(sum);\n"
        "    if (sat && asint(c) >= 0x40000000 && asint(r) < 0) return 0x7fffffffu;\n"
        "    if (sat && asint(c) < -0x40000000 && asint(r) >= 0) return 0x80000000u;\n"
        "    return r;\n"
        "}"
    ),
    "v_dot8_u32_u4": (
        "uint v_dot8_u32_u4(uint a, uint b, uint c, bool sat) {\n"
        "    uint sum = 0u;\n"
        "    for (uint k = 0u; k < 8u; ++k) {\n"
        "        sum += ((a >> (k * 4u)) & 0xfu) * ((b >> (k * 4u)) & 0xfu);\n"
        "    }\n"
        "    uint2 s = dot_u64_add(uint2(c, 0u), sum);\n"
        "    return sat ? dot_u64_sat(s) : s.x;\n"
        "}"
    ),
    "sad4_u8": (
        "uint sad4_u8(uint a, uint b, bool masked) {\n"
        "    uint sum = 0u;\n"
        "    for (uint k = 0u; k < 32u; k += 8u) {\n"
        "        uint x = (a >> k) & 0xffu;\n"
        "        uint y = (b >> k) & 0xffu;\n"
        "        if (!masked || y != 0u) sum += x > y ? x - y : y - x;\n"
        "    }\n"
        "    return sum;\n"
        "}"
    ),
    "sad2_u16": (
        "uint sad2_u16(uint a, uint b) {\n"
        "    uint lo_a = a & 0xffffu, lo_b = b & 0xffffu, hi_a = a >> 16u, hi_b = b >> 16u;\n"
        "    return (lo_a > lo_b ? lo_a - lo_b : lo_b - lo_a) + (hi_a > hi_b ? hi_a - hi_b : hi_b - hi_a);\n"
        "}"
    ),
    "mul24_u32": (
        "uint mul24_u32(uint a, uint b) {\n"
        "    return (a & 0xffffffu) * (b & 0xffffffu);\n"
        "}"
    ),
    "mul24_i32": (
        "uint mul24_i32(uint a, uint b) {\n"
        "    int sa = asint(a << 8u) >> 8;\n"
        "    int sb = asint(b << 8u) >> 8;\n"
        "    return asuint(sa) * asuint(sb);\n"
        "}"
    ),
    "mul24_hi_u32": (
        "uint mul24_hi_u32(uint a, uint b) {\n"
        "    uint ua = a & 0xffffffu;\n"
        "    uint ub = b & 0xffffffu;\n"
        "    uint al = ua & 0xfffu;\n"
        "    uint ah = ua >> 12u;\n"
        "    uint bl = ub & 0xfffu;\n"
        "    uint bh = ub >> 12u;\n"
        "    uint p0 = al * bl;\n"
        "    uint p1 = al * bh + ah * bl;\n"
        "    uint p2 = ah * bh;\n"
        "    uint mid = (p0 >> 12u) + p1;\n"
        "    return (p2 + (mid >> 12u)) >> 8u;\n"
        "}"
    ),
    "mul24_hi_i32": (
        "uint mul24_hi_i32(uint a, uint b) {\n"
        "    int sa = asint(a << 8u) >> 8;\n"
        "    int sb = asint(b << 8u) >> 8;\n"
        "    bool neg = (sa < 0) != (sb < 0);\n"
        "    uint ua = (uint)(sa < 0 ? -sa : sa);\n"
        "    uint ub = (uint)(sb < 0 ? -sb : sb);\n"
        "    uint lo = ua * ub;\n"
        "    uint hi = mul24_hi_u32(ua, ub);\n"
        "    if (neg && (lo != 0u || hi != 0u)) return ~hi + (lo == 0u ? 1u : 0u);\n"
        "    return hi;\n"
        "}"
    ),
    # v_cvt_flr_i32_f32 is floor(x) and v_cvt_rpi_i32_f32 the floor of the exact x + 0.5 (x - floor(x) is exact).
    # Exceptional inputs follow the native RDNA 2 (gfx1036) and RDNA 4 raw words cited in issue #1772, not gfx1013:
    # a NaN gives 0x7fffffff with its sign bit clear and 0x80000000 with it set, quiet or signalling, and both
    # infinities and out-of-range values saturate to the i32 limits. The NaN is replaced before any float operation
    # and the rounded value is clamped to [-2^31, 2^31 - 128] (2^31 - 1 is not a binary32), so every cast is in range.
    "cvt_flr_i32_f32": (
        "uint cvt_flr_i32_f32(uint bits) {\n"
        "    bool nan = (bits & 0x7fffffffu) > 0x7f800000u;\n"
        "    float x = asfloat(nan ? 0u : bits);\n"
        "    float r = clamp(floor(x), -2147483648.0f, 2147483520.0f);\n"
        "    uint word = x >= 2147483648.0f ? 0x7fffffffu : asuint(int(r));\n"
        "    return nan ? 0x7fffffffu + (bits >> 31) : word;\n"
        "}"
    ),
    "cvt_rpi_i32_f32": (
        "uint cvt_rpi_i32_f32(uint bits) {\n"
        "    bool nan = (bits & 0x7fffffffu) > 0x7f800000u;\n"
        "    float x = asfloat(nan ? 0u : bits);\n"
        "    float f = floor(x);\n"
        "    float r = clamp(f + ((x - f) >= 0.5f ? 1.0f : 0.0f), -2147483648.0f, 2147483520.0f);\n"
        "    uint word = x >= 2147483648.0f ? 0x7fffffffu : asuint(int(r));\n"
        "    return nan ? 0x7fffffffu + (bits >> 31) : word;\n"
        "}"
    ),
}
# (bit/float source, expression, shared conversion helper)
DPP_CVT = {
    "cvt_f32_i32": (False, "float(asint({0}))", None),
    "cvt_f32_u32": (False, "float({0})", None),
    "cvt_f32_ubyte0": (False, "float({0} & 0xffu)", None),
    "cvt_f32_ubyte1": (False, "float(({0} >> 8) & 0xffu)", None),
    "cvt_f32_ubyte2": (False, "float(({0} >> 16) & 0xffu)", None),
    "cvt_f32_ubyte3": (False, "float(({0} >> 24) & 0xffu)", None),
    "cvt_off_f32_i4": (False, "(float(asint({0} << 28) >> 28) * 0.0625f)", None),
    "cvt_i32_f32": (True, "asfloat(cvt_i32_f32({0}))", "cvt_i32_f32"),
    "cvt_u32_f32": (True, "asfloat(cvt_u32_f32({0}))", "cvt_u32_f32"),
}
DPP_INT32 = {
    "not_b32": (1, "(~{0})", None),
    "bfrev_b32": (1, "reversebits({0})", None),
    # Each signed halfword clamped to [0, 255] into bits 7:0 and 15:8, as the e32 form (INTEGER).
    "sat_pk_u8_i16": (1, "(uint(clamp(asint({0} << 16) >> 16, 0, 255)) | "
                         "(uint(clamp(asint({0}) >> 16, 0, 255)) << 8))", None),
    "ffbl_b32": (1, "firstbitlow({0})", None),
    "ffbh_u32": (1, "dpp_ffbh_u32({0})", "dpp_ffbh_u32"),
    "ffbh_i32": (1, "dpp_ffbh_i32({0})", "dpp_ffbh_i32"),
    "add_nc_u32": (2, "({0} + {1})", None),
    "sub_nc_u32": (2, "({0} - {1})", None),
    "subrev_nc_u32": (2, "({1} - {0})", None),
    "min_i32": (2, "asuint(min(asint({0}), asint({1})))", None),
    "max_i32": (2, "asuint(max(asint({0}), asint({1})))", None),
    "min_u32": (2, "min({0}, {1})", None),
    "max_u32": (2, "max({0}, {1})", None),
    "mul_u32_u24": (2, "(({0} & 0xffffffu) * ({1} & 0xffffffu))", None),
    "mul_hi_u32_u24": (2, "dpp_mul_hi_u24({0}, {1})", "dpp_mul_hi_u24"),
    "mul_i32_i24": (2, "(asuint(asint({0} << 8) >> 8) * asuint(asint({1} << 8) >> 8))", None),
    "mul_hi_i32_i24": (2, "dpp_mul_hi_i24({0}, {1})", "dpp_mul_hi_i24"),
    "and_b32": (2, "({0} & {1})", None),
    "or_b32": (2, "({0} | {1})", None),
    "xor_b32": (2, "({0} ^ {1})", None),
    "xnor_b32": (2, "(~({0} ^ {1}))", None),
    "lshlrev_b32": (2, "({1} << ({0} & 31u))", None),
    "lshrrev_b32": (2, "({1} >> ({0} & 31u))", None),
    "ashrrev_i32": (2, "asuint(asint({1}) >> ({0} & 31u))", None),
}

VOP3P_F16 = {
    "add": (2, "({0} + {1})"),
    "mul": (2, "({0} * {1})"),
    "min": (2, "min16_num({0}, {1})"),
    "max": (2, "max16_num({0}, {1})"),
    "fma": (3, "mad({0}, {1}, {2})"),
}
INLINE_F16 = {
    "0.5": 0x3800, "-0.5": 0xb800, "1.0": 0x3c00, "-1.0": 0xbc00,
    "2.0": 0x4000, "-2.0": 0xc000, "4.0": 0x4400, "-4.0": 0xc400,
    "0.15915494": 0x3118,
}
VOP3P_INT16 = {
    "add_i16": (2, True), "add_u16": (2, True),
    "sub_i16": (2, True), "sub_u16": (2, True),
    "min_i16": (2, False), "min_u16": (2, False),
    "max_i16": (2, False), "max_u16": (2, False),
    "mul_lo_u16": (2, False),
    "mad_i16": (3, True), "mad_u16": (3, True),
    "lshlrev_b16": (2, False), "lshrrev_b16": (2, False), "ashrrev_i16": (2, False),
}
# Non-packed VOP3 16-bit integer forms (llvm-mc spelling -> pk_int16_lane_expr key). Each defines only the
# low half of the destination.
VOP3_INT16 = {
    "add_nc_u16": "add_u16", "add_nc_i16": "add_i16",
    "sub_nc_u16": "sub_u16", "sub_nc_i16": "sub_i16",
    "min_u16": "min_u16", "max_u16": "max_u16", "min_i16": "min_i16", "max_i16": "max_i16",
    "mul_lo_u16": "mul_lo_u16",
    "lshlrev_b16": "lshlrev_b16", "lshrrev_b16": "lshrrev_b16", "ashrrev_i16": "ashrrev_i16",
}
# Three-operand forms of the same contract (LLVM 15 VOP3Instructions.td: V_MAD_{U,I}16 are Ternary_i16_Pats<mul, add>,
# V_{MIN3,MAX3,MED3}_{I,U}16 are AMDGPU{s,u}{min3,max3,med3}). clamp and op_sel are not modelled and are refused.
VOP3_INT16_TERNARY = {
    "mad_u16": "mad_u16", "mad_i16": "mad_i16",
    "min3_i16": "min3_i16", "min3_u16": "min3_u16", "max3_i16": "max3_i16", "max3_u16": "max3_u16",
    "med3_i16": "med3_i16", "med3_u16": "med3_u16",
}

# Quad-local DPP16/DPP8 extra f32, carry-in/carry-out, and dot-accumulate ops.
# Tuple fields: (kind, allow_fp_mods, helper_name)
DPP_EXTRA = {
    "v_rndne_f32_dpp": ("f32_unary", True, None),
    "v_sin_f32_dpp": ("f32_unary", True, None),
    "v_cos_f32_dpp": ("f32_unary", True, None),
    "v_rcp_iflag_f32_dpp": ("f32_unary", True, None),
    "v_frexp_mant_f32_dpp": ("frexp_mant", True, "dpp_frexp_mant_f32"),
    "v_frexp_exp_i32_f32_dpp": ("frexp_exp", True, "dpp_frexp_exp_i32_f32"),
    "v_mac_f32_dpp": ("mac_f32", True, None),
    "v_add_co_ci_u32_dpp": ("co_ci", False, None),
    "v_sub_co_ci_u32_dpp": ("co_ci", False, None),
    "v_subrev_co_ci_u32_dpp": ("co_ci", False, None),
    "v_dot4c_i32_i8_dpp": ("dot4c_i8", False, "dpp_dot4c_i32_i8"),
}

# Quad-local DPP16/DPP8 relative VGPR-indexing move instructions.
DPP_MOVREL = ("v_movreld_b32_dpp", "v_movrels_b32_dpp", "v_movrelsd_b32_dpp", "v_movrelsd_2_b32_dpp")
DPP_MOVREL_PATTERN = re.compile(rf"({'|'.join(DPP_MOVREL)}) (.+)")
# The plain VOP1 (e32) and VOP3 (e64) encodings of the same four moves, as LLVM 15 prints them for gfx1013 and
# gfx1030 (two VGPR operands; the VOP3 form takes no clamp, omod or source modifier in that spelling).
PLAIN_MOVREL_PATTERN = re.compile(r"(v_movreld_b32|v_movrels_b32|v_movrelsd_b32|v_movrelsd_2_b32)_e(?:32|64) (v\d+), (v\d+)")


def scalar_const_u32(token, scalar, pending):
    """Return an exact 32-bit unsigned constant if token is statically known, else None."""
    if re.fullmatch(r"s\d+", token):
        if token in pending:
            return None
        val = scalar.get(token)
        return val & 0xffffffff if isinstance(val, int) else None
    if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", token):
        return int(token, 0) & 0xffffffff
    return None


def scalar_mask_u64(token, scalar, scalar_mask, pending):
    """Return (lo_mask, hi_mask) of bits that may be 1 in a 64-bit scalar operand."""
    if token.startswith("s["):
        lo, hi = sgpr_pair(token)
        return scalar_mask.get(lo, 0xffffffff), scalar_mask.get(hi, 0xffffffff)
    if re.fullmatch(r"-?\d+", token):
        bits = int(token) & 0xffffffffffffffff
        return bits & 0xffffffff, bits >> 32
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        return int(token, 16), 0
    return 0xffffffff, 0xffffffff


def masked_offsets(mask, *, limit=16):
    """Enumerate all offsets whose 1-bits are a subset of mask, bounded to <= limit entries and <= 255."""
    if mask > 255 or (1 << mask.bit_count()) > limit:
        raise ValueError("Dynamic m0 offset range exceeds supported bound")
    offsets = [0]
    for bit in range(8):
        if mask & (1 << bit):
            offsets.extend(v | (1 << bit) for v in list(offsets))
    return sorted(offsets)


def movrel_vgpr(reg_num, vector, sample_dest):
    """Fetch a defined numeric VGPR by integer index (allowing completed uv.x/uv.y)."""
    if not 0 <= reg_num <= 255:
        raise ValueError(f"VGPR index out of range: v{reg_num}")
    name = f"v{reg_num}"
    value = vector.get(name)
    if not isinstance(value, str) or not value.startswith(("sample", "alu", "uv.")):
        raise ValueError(f"Expected a numeric VGPR at {name}")
    if name in sample_dest:
        raise ValueError("Sample used before vmcnt wait")
    return value


def sgpr_name(token):
    if not (m := re.fullmatch(r"s(\d+)", token)):
        raise ValueError(f"Expected a scalar register, got {token}")
    if not 0 <= int(m.group(1)) <= 105:
        raise ValueError(f"Scalar register out of range: {token}")
    return token


def sgpr_pair(token):
    if not (m := re.fullmatch(r"s\[(\d+):(\d+)\]", token)):
        raise ValueError(f"Expected a 64-bit scalar register pair, got {token}")
    regs = registers(*m.groups(), 2)
    if regs.start < 0 or regs.stop - 1 > 105 or regs.start % 2:
        raise ValueError(f"Invalid 64-bit scalar register pair: {token}")
    return [f"s{n}" for n in regs]


def scalar_u32(token, scalar, pending):
    if re.fullmatch(r"s\d+", token):
        sgpr_name(token)
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = scalar[token]
        if isinstance(value, int):
            return f"{value}u"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return value[1]
        if isinstance(value, str) and value.startswith("params"):
            return f"asuint({value})"
        raise ValueError(f"Expected a numeric scalar register: {token}")
    if re.fullmatch(r"-?\d+", token):
        value = int(token)
        if not -0x80000000 <= value <= 0xffffffff:
            raise ValueError(f"32-bit scalar immediate out of range: {token}")
        return f"{value & 0xffffffff}u"
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        return f"{int(token, 16)}u"
    if re.fullmatch(r"-?\d+\.\d+", token):
        bits, = struct.unpack("<I", struct.pack("<f", float(token)))
        return f"{bits}u"
    raise ValueError(f"Unsupported 32-bit scalar operand {token}")


def sopk_imm16(token, *, signed=True):
    """Parse a 16-bit SOPK immediate as a sign-extended or zero-extended 32-bit word."""
    word = int(token, 16) if token.startswith("0x") else int(token)
    if signed:
        if not -0x8000 <= word <= 0xffff:
            raise ValueError("Invalid sopk immediate")
        value = word - 0x10000 if word >= 0 and word & 0x8000 else word
        return value & 0xffffffff
    if not 0 <= word <= 0xffff:
        raise ValueError("Invalid sopk immediate")
    return word


def scalar_u64(token, scalar, pending, *, signed=False):
    if token.startswith("s["):
        lo, hi = sgpr_pair(token)
        return scalar_u32(lo, scalar, pending), scalar_u32(hi, scalar, pending)
    if re.fullmatch(r"-?\d+", token):
        value = int(token)
        if not -0x8000000000000000 <= value <= 0xffffffffffffffff:
            raise ValueError(f"64-bit scalar immediate out of range: {token}")
        bits = value & 0xffffffffffffffff
        return f"{bits & 0xffffffff}u", f"{bits >> 32}u"
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        value = int(token, 16)
        high = 0xffffffff if signed and (value & 0x80000000) else 0
        return f"{value}u", f"{high}u"
    raise ValueError(f"Unsupported 64-bit scalar operand {token}")


def lane_mask(token):
    """Name the registers of a per-lane condition for either wavefront width."""
    if token in ("vcc", "vcc_lo"):
        return ["vcc"]
    if m := re.fullmatch(r"s\[(\d+):(\d+)\]", token):
        return sgpr_pair(token)
    return [token]


# 32-bit scalar ALU on uniform register bits as (source count, result, SCC); SCC None leaves it unchanged.
# {r} names the result. Shift counts use their low five bits; signed overflow sets SCC for _i32 add/sub.
NONZERO = "{r} != 0u"
SCALAR = {
    "ff0_i32_b32": (1, "firstbitlow(~{0})", None),
    "ff1_i32_b32": (1, "firstbitlow({0})", None),
    "flbit_i32_b32": (1, "dpp_ffbh_u32({0})", None),
    "flbit_i32": (1, "dpp_ffbh_i32({0})", None),
    "bcnt0_i32_b32": (1, "32u - countbits({0})", NONZERO),
    "bcnt1_i32_b32": (1, "countbits({0})", NONZERO),
    "mul_hi_u32": (2, "mul_hi_u32({0}, {1})", None),
    "mul_hi_i32": (2, "mul_hi_i32({0}, {1})", None),
    "pack_ll_b32_b16": (2, "({0} & 0xffffu) | ({1} << 16)", None),
    "pack_lh_b32_b16": (2, "({0} & 0xffffu) | ({1} & 0xffff0000u)", None),
    "pack_hh_b32_b16": (2, "({0} >> 16) | ({1} & 0xffff0000u)", None),
    "sext_i32_i8": (1, "asuint(asint({0} << 24) >> 24)", None),
    "sext_i32_i16": (1, "asuint(asint({0} << 16) >> 16)", None),
    "abs_i32": (1, "(asint({0}) < 0 ? (0u - {0}) : {0})", NONZERO),
    "absdiff_i32": (2, "asuint(abs(asint({0}) - asint({1})))", NONZERO),
    "add_u32": (2, "{0} + {1}", "{r} < {0}"), "sub_u32": (2, "{0} - {1}", "{0} < {1}"),
    "add_i32": (2, "{0} + {1}", "(({0} ^ {r}) & ({1} ^ {r})) >> 31 != 0u"),
    "sub_i32": (2, "{0} - {1}", "(({0} ^ {1}) & ({0} ^ {r})) >> 31 != 0u"),
    "mul_i32": (2, "{0} * {1}", None),
    "min_u32": (2, "min({0}, {1})", "{0} < {1}"), "max_u32": (2, "max({0}, {1})", "{0} > {1}"),
    "min_i32": (2, "asuint(min(asint({0}), asint({1})))", "asint({0}) < asint({1})"),
    "max_i32": (2, "asuint(max(asint({0}), asint({1})))", "asint({0}) > asint({1})"),
    "and_b32": (2, "{0} & {1}", NONZERO), "or_b32": (2, "{0} | {1}", NONZERO),
    "xor_b32": (2, "{0} ^ {1}", NONZERO), "andn2_b32": (2, "{0} & ~{1}", NONZERO),
    "orn2_b32": (2, "{0} | ~{1}", NONZERO), "not_b32": (1, "~{0}", NONZERO),
    "nand_b32": (2, "~({0} & {1})", NONZERO), "nor_b32": (2, "~({0} | {1})", NONZERO),
    "xnor_b32": (2, "~({0} ^ {1})", NONZERO),
    # SCC is not written. Both counts are masked to five bits, so every shift stays below 32.
    "bfm_b32": (2, "((1u << ({0} & 31u)) - 1u) << ({1} & 31u)", None),
    # Like s_brev_b64, SCC is not written; reversebits reverses all 32 bits.
    "brev_b32": (1, "reversebits({0})", None),
    "lshl_b32": (2, "{0} << ({1} & 31u)", NONZERO), "lshr_b32": (2, "{0} >> ({1} & 31u)", NONZERO),
    "ashr_i32": (2, "asuint(asint({0}) >> ({1} & 31u))", NONZERO),
    "lshl1_add_u32": (2, "({0} << 1u) + {1}", "({0} >> 31u != 0u) || ({r} < {1})"),
    "lshl2_add_u32": (2, "({0} << 2u) + {1}", "({0} >> 30u != 0u) || ({r} < {1})"),
    "lshl3_add_u32": (2, "({0} << 3u) + {1}", "({0} >> 29u != 0u) || ({r} < {1})"),
    "lshl4_add_u32": (2, "({0} << 4u) + {1}", "({0} >> 28u != 0u) || ({r} < {1})"),
}


def parse_cvt_f32_e64_source(token):
    """Parse a register or hex literal with optional VOP3 neg and abs modifiers.

    Rejects bare `-0x...` because llvm-mc folds integer two's-complement negation on hex
    literals rather than setting the VOP3 sign-flip modifier (printed as `neg(0x...)`).
    """
    neg = False
    if token.startswith("neg(") and token.endswith(")"):
        neg = True
        token = token[4:-1]
    elif token.startswith("-"):
        neg = True
        token = token[1:]
        if token.startswith("0x"):
            return None
    has_abs = False
    if (token.startswith("|") and token.endswith("|")) or (
            token.startswith("abs(") and token.endswith(")")):
        has_abs = True
        token = token[1:-1] if token.startswith("|") else token[4:-1]
    if not re.fullmatch(r"[vs]\d+|0x[0-9a-f]{1,8}", token):
        return None
    return token, has_abs, neg


# Plain non-fused binary16 VOP2 arithmetic (issue #839): llvm-mc mnemonic -> operand expression. v_subrev_f16 computes
# src1 - src0 (LLVM 15 VOP2Instructions.td revOp naming and the translator's binary32 convention).
VOP2_F16 = {"add": "{0} + {1}", "sub": "{0} - {1}", "subrev": "{1} - {0}", "mul": "{0} * {1}"}


def f16_vop2_result(name, a, b):
    """Exact binary16 result bits of one VOP2_F16 op on two finite operands, or None when it overflows.

    Integer arithmetic on exact rationals followed by one round to nearest even on the binary16 grid. It is used at
    translation time, so that an overflowing program is refused and a chained result stays a proven value.
    """
    def value(bits):
        sign = -1 if bits & 0x8000 else 1
        exponent, mantissa = (bits >> 10) & 0x1f, bits & 0x3ff
        if exponent == 0:
            return sign * Fraction(mantissa, 1 << 24)
        return sign * Fraction(mantissa | 0x400) * Fraction(2) ** (exponent - 25)

    negative_a, negative_b = bool(a & 0x8000), bool(b & 0x8000)
    x, y = value(a), value(b)
    if name == "mul":
        exact, zero_negative = x * y, negative_a != negative_b
    else:
        # A sum is -0 only when both addends are -0 (round to nearest even); a subtraction negates one addend.
        exact, zero_negative = {"add": (x + y, negative_a and negative_b),
                                "sub": (x - y, negative_a and not negative_b),
                                "subrev": (y - x, negative_b and not negative_a)}[name]
    magnitude = abs(exact)
    if magnitude == 0:
        # Exact zero: a product keeps the XOR of the signs.
        return 0x8000 if zero_negative else 0
    if magnitude >= 65520:  # halfway between 65504 and 2^16: ties to even rounds up to infinity
        return None
    exponent = max(magnitude.numerator.bit_length() - magnitude.denominator.bit_length(), -14)
    while magnitude < Fraction(2) ** exponent and exponent > -14:
        exponent -= 1
    while magnitude >= Fraction(2) ** (exponent + 1):
        exponent += 1
    scaled = magnitude / Fraction(2) ** (exponent - 10)
    count = scaled.numerator // scaled.denominator
    remainder = scaled - count
    if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and count & 1):
        count += 1
    if count >= 0x800:
        count, exponent = 0x400, exponent + 1
    sign = 0x8000 if (exact < 0) else 0
    if count < 0x400:  # subnormal (exponent is -14 here), or a rounded-to-zero result keeping the exact sign
        return sign | count
    return sign | ((exponent + 15) << 10) | (count - 0x400)


def f16_pk_fmac_lane_result(a, b, c):
    """Exact fused binary16 result bits of a * b + c on three finite operands, or None when it overflows.

    Evaluates a * b + c in exact rationals (fractions.Fraction) and rounds once to nearest even on the
    binary16 grid, preserving subnormals. Used at translation time to reject overflowing results and keep
    chained v_pk_fmac_f16 operands statically proven.
    """
    def value(bits):
        sign = -1 if bits & 0x8000 else 1
        exponent, mantissa = (bits >> 10) & 0x1f, bits & 0x3ff
        if exponent == 0:
            return sign * Fraction(mantissa, 1 << 24)
        return sign * Fraction(mantissa | 0x400) * Fraction(2) ** (exponent - 25)

    exact = value(a) * value(b) + value(c)
    magnitude = abs(exact)
    if magnitude == 0:
        prod_zero = (a & 0x7fff) == 0 or (b & 0x7fff) == 0
        acc_zero = (c & 0x7fff) == 0
        if prod_zero and acc_zero:
            prod_neg = bool((a ^ b) & 0x8000)
            acc_neg = bool(c & 0x8000)
            return 0x8000 if (prod_neg and acc_neg) else 0
        return 0
    if magnitude >= 65520:  # halfway between 65504 and 2^16: ties to even rounds up to infinity
        return None
    exponent = max(magnitude.numerator.bit_length() - magnitude.denominator.bit_length(), -14)
    while magnitude < Fraction(2) ** exponent and exponent > -14:
        exponent -= 1
    while magnitude >= Fraction(2) ** (exponent + 1):
        exponent += 1
    scaled = magnitude / Fraction(2) ** (exponent - 10)
    count = scaled.numerator // scaled.denominator
    remainder = scaled - count
    if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and count & 1):
        count += 1
    if count >= 0x800:
        count, exponent = 0x400, exponent + 1
    sign = 0x8000 if exact < 0 else 0
    if count < 0x400:
        return sign | count
    return sign | ((exponent + 15) << 10) | (count - 0x400)


# Plain binary16 VOP2 forms with an accumulator or an integer exponent (issue #839), lowered under the rules of VOP2_F16
# arithmetic: v_fmac_f16 is D = S0 * S1 + D rounded once, and v_ldexp_f16 is D = S0 * 2^S1 with S1 a signed 16-bit
# integer (AMD RDNA 2 ISA, VOP2 opcodes 54 and 59; LLVM 15 VOP2Instructions.td VOP_F16_F16_I16). Plain e32 only.
VOP2_F16_FUSED_SCALE = ("fmac", "ldexp")
# The exponent of v_ldexp_f16 must be statically known and within this magnitude. Hardware behaviour for an exponent
# beyond it (clamping) is not stated by the ISA reference, and 2^64 times the smallest binary16 is a binary32 normal.
LDEXP_F16_EXPONENT_LIMIT = 64


def f16_ldexp_result(bits, exponent):
    """Exact binary16 result bits of v_ldexp_f16 (bits * 2^exponent) on a finite operand, or None on overflow.

    One round to nearest even on the binary16 grid (a result below the smallest subnormal rounds to a signed zero), and
    a zero operand keeps its sign. Used at translation time so that a chained result stays a proven value.
    """
    sign, exponent_bits, mantissa = bits & 0x8000, (bits >> 10) & 0x1f, bits & 0x3ff
    if exponent_bits == 0x1f:
        raise ValueError(f"binary16 operand is not finite: {bits:#06x}")
    magnitude = (Fraction(mantissa, 1 << 24) if exponent_bits == 0
                 else Fraction(mantissa | 0x400) * Fraction(2) ** (exponent_bits - 25)) * Fraction(2) ** exponent
    if magnitude == 0:
        return sign
    if magnitude >= 65520:  # halfway between 65504 and 2^16: ties to even rounds up to infinity
        return None
    top = max(magnitude.numerator.bit_length() - magnitude.denominator.bit_length(), -14)
    while magnitude < Fraction(2) ** top and top > -14:
        top -= 1
    while magnitude >= Fraction(2) ** (top + 1):
        top += 1
    scaled = magnitude / Fraction(2) ** (top - 10)
    count = scaled.numerator // scaled.denominator
    remainder = scaled - count
    if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and count & 1):
        count += 1
    if count >= 0x800:
        count, top = 0x400, top + 1
    if count < 0x400:  # subnormal, or rounded to zero keeping the sign of the operand
        return sign | count
    return sign | ((top + 15) << 10) | (count - 0x400)


def pk_fmac_f16_source(token, scalar, vector, pending, sample_dest, known_ssa_bits):
    """Return (HLSL uint word expression, 32-bit packed bits) for one v_pk_fmac_f16 source operand.

    Both binary16 halves must be statically proven finite (exponent != 0x1f). Inline f16 float constants
    occupy bits [15:0] with bits [31:16] zeroed (+0.0), matching gfx1013 hardware. Unproven runtime values
    (constant-buffer words, samples, interpolants, scalar half16/low16 results) and non-finite halves are
    refused.
    """
    if token in INLINE_F16:
        bits = INLINE_F16[token]
        return f"{bits}u", bits
    if token == "0":
        return "0u", 0
    if re.fullmatch(r"-?\d+", token):
        raise ValueError(f"Unsupported binary16 integer inline constant {token}")
    if token.startswith(("-", "|", "abs(", "neg(")):
        raise ValueError(f"Unsupported binary16 source modifier {token}")
    if re.fullmatch(r"0x[0-9a-f]+", token):
        bits = int(token, 16)
        if bits > 0xffffffff:
            raise ValueError(f"32-bit literal out of range: {token}")
        word = f"{bits}u"
    elif m := re.fullmatch(r"([vs])(\d+)", token):
        limit = 255 if m.group(1) == "v" else 105
        if not 0 <= int(m.group(2)) <= limit:
            raise ValueError(f"Register out of range: {token}")
        if token in pending:
            raise ValueError("Constant read before load completion")
        if token in sample_dest:
            raise ValueError("Sample used before vmcnt wait")
        if m.group(1) == "s":
            if token not in scalar:
                raise ValueError(f"Unbound scalar input {token} at v_pk_fmac_f16")
            value = scalar[token]
            if isinstance(value, int):
                bits, word = value & 0xffffffff, f"{value & 0xffffffff}u"
            else:
                raise ValueError(f"binary16 operand lacks a finite proof: {token}")
        else:
            if token not in vector:
                raise ValueError(f"Unbound pixel input {token} at v_pk_fmac_f16")
            value = vector[token]
            if isinstance(value, str) and value in known_ssa_bits:
                bits, word = known_ssa_bits[value] & 0xffffffff, f"asuint({value})"
            else:
                raise ValueError(f"binary16 operand lacks a finite proof: {token}")
    else:
        raise ValueError(f"Unsupported binary16 operand {token}")
    if (bits & 0x7c00) == 0x7c00 or ((bits >> 16) & 0x7c00) == 0x7c00:
        raise ValueError(f"binary16 operand is not finite: {token}")
    return word, bits


# Plain binary16 VOP1 rounding (issue #839): llvm-mc mnemonic -> binary32 HLSL call. LLVM 15.0.7 VOP1Instructions.td
# L449-452 selects ffloor, fceil, ftrunc and frint for them; frint is round to nearest even under the default
# rounding mode, and HLSL round is round-half-to-even in DXIL (the binary32 rndne entry of ALU relies on it).
VOP1_F16_ROUND = {"floor": "floor({0})", "ceil": "ceil({0})", "trunc": "trunc({0})", "rndne": "round({0})"}


def f16_round_result(name, bits):
    """Exact binary16 result bits of one VOP1_F16_ROUND op on a finite operand.

    The rounded value of a finite binary16 is an integer of magnitude at most 65504, which is representable, so no
    rounding happens on the way back. An exact zero result keeps the sign of the operand (floor(-0), ceil(-0.3),
    trunc(-0.5) and rndne(-0.4) are -0; floor(0.3) is +0). Used at translation time so that a chained result stays a
    proven value.
    """
    sign = bits & 0x8000
    exponent, mantissa = (bits >> 10) & 0x1f, bits & 0x3ff
    if exponent == 0x1f:
        raise ValueError(f"binary16 operand is not finite: {bits:#06x}")
    magnitude = Fraction(mantissa, 1 << 24) if exponent == 0 else Fraction(mantissa | 0x400) * Fraction(2) ** (exponent - 25)
    value = -magnitude if sign else magnitude
    integer = {"floor": math.floor, "ceil": math.ceil, "trunc": math.trunc, "rndne": round}[name](value)
    if integer == 0:
        return sign
    count = abs(integer)
    top = count.bit_length() - 1
    if top <= 10:
        fraction = (count << (10 - top)) & 0x3ff
    else:
        assert count % (1 << (top - 10)) == 0, (name, bits)  # a binary16 value this large is already an integer
        fraction = (count >> (top - 10)) & 0x3ff
    return sign | ((top + 15) << 10) | fraction


def f16_cvt_int_result(signed, value):
    """Exact binary16 result bits of v_cvt_f16_i16 (signed) or v_cvt_f16_u16 of the low 16 bits of value, or None when
    the result overflows to infinity.

    LLVM 15.0.7 VOP1Instructions.td L432-433 selects sint_to_fp and uint_to_fp, and the default rounding mode is round
    to nearest even. Integer arithmetic with one rounding, used at translation time so that a proven source gives a
    proven result. Zero is +0. Every i16 value is finite (at most 32768); a u16 value of 65520 or more rounds to 2^16,
    which rounds up to infinity, so the boundary is refused.
    """
    value &= 0xffff
    if signed and value & 0x8000:
        value -= 0x10000
    sign = 0x8000 if value < 0 else 0
    magnitude = abs(value)
    if magnitude == 0:
        return 0
    top = magnitude.bit_length() - 1
    if top <= 10:  # at most 11 significant bits: exact
        return sign | ((top + 15) << 10) | ((magnitude << (10 - top)) & 0x3ff)
    shift = top - 10
    count, remainder, half = magnitude >> shift, magnitude & ((1 << shift) - 1), 1 << (shift - 1)
    if remainder > half or (remainder == half and count & 1):
        count += 1
    if count == 0x800:
        count, top = 0x400, top + 1
    if top > 15:
        return None
    return sign | ((top + 15) << 10) | (count & 0x3ff)


def f16_to_int_result(signed, bits):
    """Low 16 bits of v_cvt_i16_f16 (signed) or v_cvt_u16_f16 of a finite binary16 value, or None when the result is not
    in range.

    LLVM 15.0.7 VOP1Instructions.td L436-437 selects fp_to_sint and fp_to_uint, and AMD RDNA 2 section 12.8 (VOP1 entries
    82 and 83) specifies truncation toward zero. The range check applies to the truncated integer: -32768 to 32767 for
    the signed op, 0 to 65535 for the unsigned one, so -0.5 truncates to 0 and is valid for both, while -1 is out of range
    for the unsigned op. Exact integer arithmetic on the operand in units of 2^-24, used at translation time. The result
    is the two's-complement low half; a non-finite operand is an error because the caller requires a finite proof first.
    """
    exponent, mantissa = (bits >> 10) & 0x1f, bits & 0x3ff
    if exponent == 0x1f:
        raise ValueError(f"binary16 operand is not finite: {bits:#06x}")
    units = mantissa if exponent == 0 else (mantissa | 0x400) << (exponent - 1)
    value = -(units >> 24) if bits & 0x8000 else units >> 24
    if not (-0x8000 <= value <= 0x7fff if signed else 0 <= value <= 0xffff):
        return None
    return value & 0xffff


def int16_known_value(token, scalar, vector, known_ssa_bits):
    """Low 16 bits of a 16-bit integer source whose value is statically known, else None.

    Known: an integer inline constant, a literal, a tracked SGPR integer and a VGPR copied from a known constant.
    A constant-buffer word, a sample, an interpolant and a 16-bit integer result are not. The token must already have
    been accepted by int16_operand.
    """
    if re.fullmatch(r"-?\d+", token):
        return int(token) & 0xffff
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        return int(token, 16) & 0xffff
    if token.startswith("s"):
        value = scalar.get(token)
        return value & 0xffff if isinstance(value, int) else None
    value = vector.get(token)
    return known_ssa_bits[value] & 0xffff if isinstance(value, str) and value in known_ssa_bits else None


def half16_name(token, vector):
    """Return the HLSL variable of a VGPR that holds a binary16 arithmetic result, else None.

    The plain binary16 VOP2 ops store ("half16", name): bits 15:0 are the result and bits 31:16 are unspecified.
    The tag is distinct from ("low16", name), so that no 16-bit integer reader can observe a binary16 result and no
    binary16 reader a 16-bit integer one. Its first element must not start with "sample" or "alu", which the
    compressed export and the pack checks accept for string pairs. Only the readers named in the lowering read it.
    """
    value = vector.get(token) if re.fullmatch(r"v\d+", token) else None
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "half16":
        return value[1]
    return None


def half16_arith_source(token, scalar, vector, pending, sample_dest, known_ssa_bits, known_half):
    """Return (HLSL word expression, binary16 bits) of one source of a plain binary16 VOP2 op.

    Only a source whose low half is statically known and finite is accepted: a binary16 inline constant, a 16-bit
    literal, a tracked SGPR integer, a VGPR copied from a known constant, or the result of an earlier accepted op.
    Everything else (constant-buffer words, samples, interpolants) lacks the finite proof and is refused. Integer
    inline constants other than 0 are refused: LLVM prints a literal of 0x0001..0x0040 or 0xfff0..0xffff as an integer
    and the hardware reading of such an inline constant on a binary16 operand is not established.
    """
    if token in INLINE_F16:
        bits = INLINE_F16[token]
        return f"{bits}u", bits
    if token == "0":
        return "0u", 0
    if re.fullmatch(r"-?\d+", token):
        raise ValueError(f"Unsupported binary16 integer inline constant {token}")
    if token.startswith(("-", "|", "abs(", "neg(")):
        raise ValueError(f"Unsupported binary16 source modifier {token}")
    if re.fullmatch(r"0x[0-9a-f]+", token):
        bits = int(token, 16)
        if bits > 0xffff:
            raise ValueError(f"16-bit literal out of range: {token}")
        word = f"{bits}u"
    elif m := re.fullmatch(r"([vs])(\d+)", token):
        if not 0 <= int(m.group(2)) <= (255 if m.group(1) == "v" else 105):
            raise ValueError(f"Register out of range: {token}")
        if token in pending:
            raise ValueError("Constant read before load completion")
        if token in sample_dest:
            raise ValueError("Sample used before vmcnt wait")
        value = (vector if m.group(1) == "v" else scalar).get(token)
        if isinstance(value, int) and m.group(1) == "s":
            bits, word = value & 0xffff, f"{value & 0xffffffff}u"
        elif m.group(1) == "v" and isinstance(value, str) and value in known_ssa_bits:
            bits, word = known_ssa_bits[value] & 0xffff, f"asuint({value})"
        elif half16_name(token, vector) in known_half:
            name = half16_name(token, vector)
            bits, word = known_half[name], f"asuint({name})"
        else:
            raise ValueError(f"binary16 operand lacks a finite proof: {token}")
    else:
        raise ValueError(f"Unsupported binary16 operand {token}")
    if (bits >> 10) & 0x1f == 0x1f:
        raise ValueError(f"binary16 operand is not finite: {token}")
    return word, bits


CVT_F64_F32_INLINE = {"0": 0x00000000, "0.5": 0x3f000000, "-0.5": 0xbf000000, "1.0": 0x3f800000, "-1.0": 0xbf800000,
                      "2.0": 0x40000000, "-2.0": 0xc0000000, "4.0": 0x40800000, "-4.0": 0xc0800000,
                      "0.15915494": 0x3e22f983}
CVT_F64_F32_E64_SOURCE = re.compile(r"neg\((0x[0-9a-f]{1,8})\)|(-?)(\|?)([vs]\d+|0x[0-9a-f]{1,8})(\|?)")


def cvt_f64_f32_words(bits):
    """Return the (low, high) binary64 words of the exact conversion of binary32 bits, or raise ValueError.

    Exact for every finite normal value: sign kept, exponent rebased from 127 to 1023, the 23-bit fraction placed at
    the top of the 52-bit fraction. Zero keeps its sign (hi 0x80000000 for -0) and infinity maps to exponent 0x7ff
    with a zero fraction. A subnormal input is refused because the f32 denorm mode (MODE[5:4]) has no declared
    profile in this translator, and a NaN is refused (issue 312).
    """
    sign, exponent, fraction = bits >> 31, (bits >> 23) & 0xff, bits & 0x7fffff
    if exponent == 0xff and fraction:
        raise ValueError(f"v_cvt_f64_f32 source 0x{bits:08x} is a NaN")
    if exponent == 0 and fraction:
        raise ValueError(f"v_cvt_f64_f32 source 0x{bits:08x} is a subnormal")
    if exponent == 0:
        return 0, sign << 31
    if exponent == 0xff:
        return 0, (sign << 31) | 0x7ff00000
    return (fraction & 7) << 29, (sign << 31) | ((exponent - 127 + 1023) << 20) | (fraction >> 3)


def cvt_f32_f64_exact_bits(low, high):
    """Return the binary32 bits of the binary64 words (low, high), or raise ValueError.

    Only a value that is exactly a normal binary32 or a signed zero is accepted: the narrowing is then exact and does
    not depend on either rounding field (MODE[1:0] or MODE[3:2]) or either denorm field (MODE[5:4] or MODE[7:6]). The value is narrowed with
    struct, then widened again with cvt_f64_f32_words, and the result must equal the input words bit for bit.
    Both infinities and NaNs ("is not finite"), a subnormal binary32 ("is a subnormal") and any value that needs
    rounding, including one that overflows or underflows binary32 ("requires rounding"), are refused.
    """
    if (high >> 20) & 0x7ff == 0x7ff:
        raise ValueError(f"v_cvt_f32_f64 source 0x{high:08x}{low:08x} is not finite")
    value, = struct.unpack("<d", struct.pack("<II", low, high))
    try:
        bits, = struct.unpack("<I", struct.pack("<f", value))
    except OverflowError:
        raise ValueError(f"v_cvt_f32_f64 source 0x{high:08x}{low:08x} requires rounding") from None
    narrowed, = struct.unpack("<f", struct.pack("<I", bits))
    if struct.pack("<d", narrowed) != struct.pack("<II", low, high):
        raise ValueError(f"v_cvt_f32_f64 source 0x{high:08x}{low:08x} requires rounding")
    if (bits >> 23) & 0xff == 0 and bits & 0x7fffff:
        raise ValueError(f"v_cvt_f32_f64 source 0x{high:08x}{low:08x} is a subnormal binary32")
    if cvt_f64_f32_words(bits) != (low, high):
        raise ValueError(f"v_cvt_f32_f64 source 0x{high:08x}{low:08x} requires rounding")
    return bits


def cvt_f64_f32_source_bits(base, scalar, vector, pending, sample_dest, known_ssa_bits):
    """Return the statically known binary32 bits of the source of v_cvt_f64_f32, or raise ValueError.

    The accepted sources are a hex literal, a binary32 inline constant, a SGPR that holds a tracked integer, or a
    VGPR whose bits known_ssa_bits records. Any other register is an unproven runtime input. An integer inline
    constant other than 0 is a subnormal (1..64) or an all-ones NaN pattern (-16..-1), never a float, and is refused
    with the other unlisted spellings.
    """
    if base in CVT_F64_F32_INLINE:
        return CVT_F64_F32_INLINE[base]
    if re.fullmatch(r"0x[0-9a-f]{1,8}", base):
        return int(base, 16)
    if not (m := re.fullmatch(r"([vs])(\d+)", base)):
        raise ValueError(f"Unsupported v_cvt_f64_f32 source {base}")
    if int(m.group(2)) > (255 if m.group(1) == "v" else 105):
        raise ValueError(f"Register out of range: {base}")
    if base in pending:
        raise ValueError("Constant read before load completion")
    if base in sample_dest:
        raise ValueError("Sample used before vmcnt wait")
    if m.group(1) == "s":
        value = scalar.get(base)
        if not isinstance(value, int):
            raise ValueError(f"Unproven runtime input {base} at v_cvt_f64_f32")
        return value & 0xffffffff
    ssa = vector.get(base)
    if not isinstance(ssa, str) or ssa not in known_ssa_bits:
        raise ValueError(f"Unproven runtime input {base} at v_cvt_f64_f32")
    return known_ssa_bits[ssa] & 0xffffffff


def fp_operand(token, scalar, vector, pending, sample_dest, *,
               quad_values: dict[str, bool] | None = None, ignore_sign=False):
    if re.fullmatch(r"-\d+", token):
        return f"asfloat({int(token) & 0xffffffff}u)"
    if token.startswith("-"):
        inner = fp_operand(token[1:], scalar, vector, pending, sample_dest,
                           quad_values=quad_values, ignore_sign=ignore_sign)
        return inner if ignore_sign else f"(-{inner})"
    if absolute := re.fullmatch(r"abs\(([^()|]+)\)|\|([^()|]+)\|", token):
        inner = fp_operand(absolute.group(1) or absolute.group(2), scalar, vector, pending, sample_dest,
                           quad_values=quad_values, ignore_sign=ignore_sign)
        return inner if ignore_sign else f"abs({inner})"
    if re.fullmatch(r"[vs]\d+", token):
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = (vector if token.startswith("v") else scalar)[token]
        if quad_values is not None and token.startswith("v") and value not in quad_values:
            raise ValueError("Operand lacks a helper-lane definition")
        if isinstance(value, tuple) and value[0] == "uint":
            return f"asfloat({value[1]})"
        if isinstance(value, int):
            return f"asfloat({value}u)"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return f"asfloat({value[1]})"
        if not isinstance(value, str) or not (value.startswith(("sample", "alu", "params"))
                or (quad_values is not None and value in quad_values)):
            raise ValueError("Expected a numeric register")
        if token in sample_dest:
            raise ValueError("Sample used before vmcnt wait")
        return value
    if re.fullmatch(r"0x[0-9a-f]{1,8}|\d+", token):
        return f"asfloat({int(token, 0)}u)"
    if re.fullmatch(r"\d+\.\d+", token):
        return token + "f"
    raise ValueError(f"Unsupported arithmetic operand {token}")



SDWA_NEG_DECIMAL = re.compile(r"^neg\((-?\d+\.\d+)\)$")


def f32_compare_word(token, scalar, vector, pending, sample_dest):
    """The binary32 word of one f32 comparison operand as a uint expression, with neg and abs applied to the word.

    The modifiers are bit operations on the encoding, as in the f16 path, so no float operation is left in the
    comparison and a denormal flush cannot reach the operand.
    """
    word = f"asuint({fp_operand(token, scalar, vector, pending, sample_dest, ignore_sign=True)})"
    if re.fullmatch(r"-\d+", token):
        return word  # an integer immediate is the word itself, not a negated value
    neg = token.startswith("-")
    if neg:
        token = token[1:]
    if re.fullmatch(r"abs\(([^()|]+)\)|\|([^()|]+)\|", token):
        word = f"({word} & 0x7fffffffu)"
    if neg:
        word = f"({word} ^ 0x80000000u)"
    return word


def f32_comparison(op, tokens, scalar, vector, pending, sample_dest):
    if op in F32_KEY_COMPARE:
        # The relation is decided on the words, under the same encoding-level NaN guard: an fcmp is what the
        # driver compiler can enclose in a flushing s_denorm_mode window, and a key comparison is not one.
        words = [f32_compare_word(t, scalar, vector, pending, sample_dest) for t in tokens]
        ordered = " && ".join(f"(({w} & 0x7fffffffu) <= 0x7f800000u)" for w in words)
        relation = F32_KEY_COMPARE[op].format(*(f"key32({w})" for w in words))
        return f"({ordered} && ({relation}))"
    return COMPARE[op].format(*[fp_operand(t, scalar, vector, pending, sample_dest) for t in tokens])


def low16_name(token, vector):
    """Return the HLSL variable of a VGPR that holds only a defined low half, else None.

    The non-packed 16-bit integer VOP3 ops store ("low16", name). The variable holds a 32-bit word whose
    bits 15:0 are the result; bits 31:16 are unspecified and no accepted reader may observe them. Only the
    16-bit integer ops, the 16-bit integer compares and v_mov_b32_sdwa with a low-half selection read it.
    Every other reader sees a tuple and refuses it.
    """
    value = vector.get(token) if re.fullmatch(r"v\d+", token) else None
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "low16":
        return value[1]
    return None


def int_operand(token, scalar, vector, pending, sample_dest, *, signed):
    if re.fullmatch(r"v\d+", token):
        value = vector[token]
        if not isinstance(value, str) or not value.startswith(("sample", "alu", "params")):
            raise ValueError("Expected a numeric register")
        if token in sample_dest:
            raise ValueError("Sample used before vmcnt wait")
        return f"asint({value})" if signed else f"asuint({value})"
    bits = scalar_u32(token, scalar, pending)
    if signed and bits.startswith("asuint(") and bits.endswith(")"):
        return f"asint({bits[7:-1]})"
    return f"asint({bits})" if signed else bits


def int16_operand(token, scalar, vector, pending, sample_dest, *, signed):
    """Return the low 16 bits of a 16-bit integer source as a sign- or zero-extended HLSL value.

    Registers, integer inline constants (-16..64) and 16-bit literals are accepted. llvm-mc prints a
    float inline constant on a 16-bit integer operand as its binary16 literal (1.0 as 0x3c00), so a
    float token or a wider literal never names a valid operand here and is refused.
    """
    if re.fullmatch(r"-?\d+", token):
        if not -16 <= int(token) <= 64:
            raise ValueError(f"Unsupported 16-bit integer inline constant {token}")
    elif re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        if int(token, 16) > 0xffff:
            raise ValueError(f"16-bit literal out of range: {token}")
    elif not re.fullmatch(r"[vs]\d+", token):
        raise ValueError(f"Unsupported 16-bit integer operand {token}")
    if (name := low16_name(token, vector)) is not None:
        bits = f"asuint({name})"
    else:
        bits = int_operand(token, scalar, vector, pending, sample_dest, signed=False)
    return f"(asint({bits} << 16) >> 16)" if signed else f"({bits} & 0xffffu)"


def int64_operand(token, scalar, vector, pending, sample_dest, *, signed, encoding, position):
    """Return the (low, high) HLSL words of a 64-bit integer comparison source.

    Accepted: a VGPR pair v[a:a+1] (0 <= a <= 254, unaligned allowed: LLVM 15 assembles it; hardware legality is
    assumed), an aligned SGPR pair s[a:a+1], and an integer inline constant from -16 to 64, sign-extended to 64 bits
    (assumed to follow the scalar b64 rule, pinned by the -1 pairs of the draw). Literals, floats, hex and modifiers
    are refused. Both words are raw bits; only the high word is signed, the low word always compares unsigned.
    VOPC e32 takes a VGPR pair as src1 (position 1), because LLVM refuses an SGPR there.
    """
    invalid = ValueError(f"Invalid 64-bit comparison operand: {token}")
    pair = re.fullmatch(r"v\[(0|[1-9]\d*):(0|[1-9]\d*)\]", token)
    if encoding == "e32" and position == 1 and not pair:
        raise ValueError("64-bit comparison e32 src1 must be a VGPR pair")
    if pair:
        first, last = int(pair.group(1)), int(pair.group(2))
        if last != first + 1 or first > 254:
            raise invalid
        names = (f"v{first}", f"v{last}")
        if any(name not in vector for name in names):
            raise ValueError(f"Untracked 64-bit comparison source: {token}")
        return (int_operand(names[0], scalar, vector, pending, sample_dest, signed=False),
                int_operand(names[1], scalar, vector, pending, sample_dest, signed=signed))
    if re.fullmatch(r"s\[\d+:\d+\]", token):
        names = sgpr_pair(token)
        if any(name not in pending and name not in scalar for name in names):
            raise ValueError(f"Untracked 64-bit comparison source: {token}")
        return (int_operand(names[0], scalar, vector, pending, sample_dest, signed=False),
                int_operand(names[1], scalar, vector, pending, sample_dest, signed=signed))
    if re.fullmatch(r"0|-?[1-9]\d*", token) and -16 <= int(token) <= 64:
        value = int(token) & 0xffffffffffffffff
        high = f"{value >> 32}u"
        return f"{value & 0xffffffff}u", f"asint({high})" if signed else high
    raise invalid


# Inline constants a binary64 comparison source accepts, as high words (the low word is 0). The integer 0 is +0.0
# under either reading of an integer inline constant on a binary64 operand; other integers and 1/(2*pi) are refused.
F64_INLINE_HIGH = {"0": 0x00000000, "0.5": 0x3fe00000, "-0.5": 0xbfe00000, "1.0": 0x3ff00000, "-1.0": 0xbff00000,
                   "2.0": 0x40000000, "-2.0": 0xc0000000, "4.0": 0x40100000, "-4.0": 0xc0100000}
# Ordered binary64 relations on the key64 keys {a} and {b}; the n* predicates are their negations, true on NaN.
F64_RELATION = {"lt": "lt64({a}, {b})", "eq": "eq64({a}, {b})", "le": "!lt64({b}, {a})", "gt": "lt64({b}, {a})",
                "lg": "!eq64({a}, {b})", "ge": "!lt64({a}, {b})"}
F64_NEGATED = {"nge": "ge", "nlg": "lg", "ngt": "gt", "nle": "le", "nlt": "lt", "neq": "eq"}


def f64_operand(token, scalar, vector, pending, sample_dest, *, encoding, position, allow_mods=True):
    """Return the (low, high) HLSL words of a binary64 comparison source.

    Registers follow int64_operand. Inline constants are 0 and the binary64 values in F64_INLINE_HIGH. The e64
    neg (-x) and abs (|x|) modifiers act on the sign bit of the high word, as binary64 operand modifiers do.
    """
    invalid = ValueError(f"Invalid 64-bit comparison operand: {token}")
    raw, negate, absolute = token, False, False
    if raw.startswith("-") and raw not in F64_INLINE_HIGH:
        raw, negate = raw[1:], True
    if m := re.fullmatch(r"\|([^|]+)\|", raw):
        raw, absolute = m[1], True
    if (negate or absolute) and (encoding != "e64" or not allow_mods):
        raise invalid
    if raw in F64_INLINE_HIGH:
        if encoding == "e32" and position == 1:
            raise ValueError("64-bit comparison e32 src1 must be a VGPR pair")
        low, high = "0u", f"{F64_INLINE_HIGH[raw]}u"
    elif re.fullmatch(r"-?\d+", raw):
        raise invalid
    else:
        low, high = int64_operand(raw, scalar, vector, pending, sample_dest, signed=False,
                                  encoding=encoding, position=position)
    if absolute:
        high = f"({high} & 0x7fffffffu)"
    if negate:
        high = f"({high} ^ 0x80000000u)"
    return low, high


def f64_comparison(i, op, tokens, encoding, scalar, vector, pending, sample_dest):
    """HLSL word declarations and the predicate of a binary64 v_cmp or v_cmpx of `tokens` (op may be "class").

    The predicates compare the raw (low, high) words with the cmp_f64 helpers and use no HLSL double; the caller
    adds the helpers and checks the binary64 denormal entry state.
    """
    if op == "class":
        low, high = f64_operand(tokens[0], scalar, vector, pending, sample_dest, encoding=encoding, position=0,
                                allow_mods=False)
        classes = tokens[1]
        if encoding == "e32" and not re.fullmatch(r"v\d+", classes):
            raise ValueError("VOPC e32 src1 must be a VGPR")
        if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", classes):
            bits = f"{int(classes, 0) & 0xffffffff}u"
        elif re.fullmatch(r"[vs]\d+", classes):
            bits = int_operand(classes, scalar, vector, pending, sample_dest, signed=False)
        else:
            raise ValueError("Unsupported class mask")
        return [], f"(class64({low}, {high}) & {bits}) != 0u"
    words = [f64_operand(t, scalar, vector, pending, sample_dest, encoding=encoding, position=n)
             for n, t in enumerate(tokens)]
    lines = [f"    uint cmp{i}_{name} = {value};" for name, value in zip(("l0", "h0", "l1", "h1"), (*words[0], *words[1]))]
    lines += [f"    bool cmp{i}_o = num64(cmp{i}_l0, cmp{i}_h0) && num64(cmp{i}_l1, cmp{i}_h1);",
              f"    uint2 cmp{i}_a = key64(cmp{i}_l0, cmp{i}_h0);",
              f"    uint2 cmp{i}_b = key64(cmp{i}_l1, cmp{i}_h1);"]
    keys = {"a": f"cmp{i}_a", "b": f"cmp{i}_b"}
    if op in F64_RELATION:
        expr = f"cmp{i}_o && {F64_RELATION[op].format(**keys)}"
    elif op in F64_NEGATED:
        expr = f"!(cmp{i}_o && {F64_RELATION[F64_NEGATED[op]].format(**keys)})"
    else:
        expr = {"o": f"cmp{i}_o", "u": f"!cmp{i}_o"}.get(op, COMPARE[op])
    return lines, expr


def int64_comparison(i, op, kind, tokens, encoding, scalar, vector, pending, sample_dest):
    """HLSL word declarations and the predicate of a 64-bit integer v_cmp or v_cmpx of `tokens`."""
    words = [int64_operand(t, scalar, vector, pending, sample_dest, signed=kind == "i64",
                           encoding=encoding, position=n) for n, t in enumerate(tokens)]
    word_type = "int" if kind == "i64" else "uint"
    names = [f"cmp{i}_l0", f"cmp{i}_h0", f"cmp{i}_l1", f"cmp{i}_h1"]
    lines = [f"    {'uint' if name[-2] == 'l' else word_type} {name} = {value};"
             for name, value in zip(names, (words[0][0], words[0][1], words[1][0], words[1][1]))]
    return lines, INT64_COMPARE[op].format(l0=names[0], h0=names[1], l1=names[2], h1=names[3])


def dpp_vgpr(token, vector, sample_dest, *, allow_mods):
    """Parse one DPP VGPR operand (allowing completed uv.* interpolation outputs in DPP)."""
    neg = False
    use_abs = False
    raw = token
    if raw.startswith("-"):
        if not allow_mods:
            raise ValueError(f"Source modifiers are not allowed on {token}")
        neg = True
        raw = raw[1:]
    if m := re.fullmatch(r"abs\(([^()|]+)\)|\|([^()|]+)\|", raw):
        if not allow_mods:
            raise ValueError(f"Source modifiers are not allowed on {token}")
        use_abs = True
        raw = m.group(1) or m.group(2)
    m = re.fullmatch(r"v(\d+)", raw)
    if not m or not 0 <= int(m.group(1)) <= 255:
        raise ValueError(f"DPP operand must be a VGPR, got {token}")
    if raw not in vector:
        raise ValueError(f"DPP operand {raw} is read before it is written")
    value = vector[raw]
    if not isinstance(value, str) or not value.startswith(("sample", "alu", "uv.")):
        raise ValueError(f"Expected a numeric VGPR in DPP, got {raw}")
    if raw in sample_dest:
        raise ValueError("Sample used before vmcnt wait")
    return value, use_abs, neg


def parse_dpp(rest, operand_count):
    """Parse operands and quad-local DPP16 (quad_perm) or DPP8 (dpp8) modifiers."""
    parts_ = rest.split(", ")
    if len(parts_) != operand_count:
        raise ValueError("Invalid DPP operand count")
    last_op, _, mod_text = parts_[-1].partition(" ")
    operands = [*parts_[:-1], last_op]
    mods = mod_text.split()
    if not mods:
        raise ValueError("Missing DPP control modifiers")
    if m := re.fullmatch(r"dpp8:\[([0-7](?:,[0-7]){7})\]", mods[0]):
        perm8 = [int(b) for b in m.group(1).split(",")]
        if mods[1:]:
            raise ValueError(f"Unsupported DPP8 modifier {mods[1]}")
        if not all(p < 4 for p in perm8[:4]):
            raise ValueError(f"Cross-quad DPP8 permutation is unsupported: {mods[0]}")
        if perm8[4:] != [p + 4 for p in perm8[:4]]:
            raise ValueError(f"DPP8 permutation must repeat the same quad selection in both halves: {mods[0]}")
        return operands, perm8[:4], True
    if m := re.fullmatch(r"quad_perm:\[([0-3],[0-3],[0-3],[0-3])\]", mods[0]):
        perm4 = [int(b) for b in m.group(1).split(",")]
        seen = set()
        for mod in mods[1:]:
            if mod in ("row_mask:0xf", "bank_mask:0xf"):
                key = mod.split(":", 1)[0]
                if key in seen:
                    raise ValueError(f"Duplicate DPP16 modifier {mod}")
                seen.add(key)
            else:
                raise ValueError(f"Unsupported DPP16 modifier {mod}")
        return operands, perm4, False
    raise ValueError(f"Unsupported DPP control {mods[0]}")


def emit_quad_swizzle_u32(lines, idx, base_expr, perm):
    """Swizzle a 32-bit value across a 2x2 quad as uint bits so subnormals/bit patterns stay exact."""
    bits = f"asuint({base_expr})"
    if perm == [0, 1, 2, 3]:
        return bits
    svar = f"dpp{idx}_s"
    if perm == [1, 0, 3, 2]:
        lines.append(f"    uint {svar} = QuadReadAcrossX({bits});")
        return svar
    if perm == [2, 3, 0, 1]:
        lines.append(f"    uint {svar} = QuadReadAcrossY({bits});")
        return svar
    if perm == [3, 2, 1, 0]:
        lines.append(f"    uint {svar} = QuadReadAcrossDiagonal({bits});")
        return svar
    if len(set(perm)) == 1:
        lines.append(f"    uint {svar} = QuadReadLaneAt({bits}, {perm[0]});")
        return svar
    lines.append(f"    uint dpp{idx}_in = {bits};")
    lines.append(f"    uint dpp{idx}_q = WaveGetLaneIndex() & 3u;")
    lane_vars = {}
    for lane in sorted(set(perm)):
        lv = f"dpp{idx}_l{lane}"
        lines.append(f"    uint {lv} = QuadReadLaneAt(dpp{idx}_in, {lane});")
        lane_vars[lane] = lv
    l0, l1, l2, l3 = (lane_vars[p] for p in perm)
    # Select with bits so the quad reads stay outside divergent branch arms (#1024).
    even, top = f"dpp{idx}_even", f"dpp{idx}_top"
    lines.append(f"    uint {even} = (dpp{idx}_q & 1u) - 1u;")
    lines.append(f"    uint {top} = (dpp{idx}_q >> 1u) - 1u;")
    lines.append(f"    uint {svar} = ((({l0} & {even}) | ({l1} & ~{even})) & {top}) | "
                 f"((({l2} & {even}) | ({l3} & ~{even})) & ~{top});")
    return svar


def vop3p_f16_word(token, scalar, vector, pending, sample_dest):
    """Return a 32-bit uint HLSL expression for one packed binary16 VOP3P source operand.

    On gfx1013 (RDNA 2), inline f16 float constants occupy bits [15:0] with bits [31:16] zeroed.
    """
    if token in INLINE_F16:
        return f"{INLINE_F16[token]}u"
    if m := re.fullmatch(r"([vs])(\d+)", token):
        limit = 255 if m.group(1) == "v" else 105
        if not 0 <= int(m.group(2)) <= limit:
            raise ValueError(f"Register out of range: {token}")
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = (vector if m.group(1) == "v" else scalar)[token]
        if isinstance(value, int):
            return f"{value}u"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return value[1]
        if not isinstance(value, str) or not value.startswith(("sample", "alu", "params")):
            raise ValueError("Expected a numeric register")
        if token in sample_dest:
            raise ValueError("Sample used before vmcnt wait")
        return f"asuint({value})"
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        return f"{int(token, 16)}u"
    if re.fullmatch(r"-?\d+", token):
        value = int(token)
        if not -16 <= value <= 64:
            raise ValueError(f"Unsupported packed integer inline constant {token}")
        return f"{value & 0xffffffff}u"
    raise ValueError(f"Unsupported packed operand {token}")


def f16_cmp_operand(token, scalar, vector, pending, sample_dest, *, allow_mods, as_bits):
    """Return one binary16 comparison source as low-16-bit uint bits or a widened float."""
    neg = False
    use_abs = False
    if token not in INLINE_F16 and not re.fullmatch(r"-\d+", token):
        if token.startswith("-"):
            neg = True
            token = token[1:]
        if m := re.fullmatch(r"abs\(([^()|]+)\)|\|([^()|]+)\|", token):
            use_abs = True
            token = m.group(1) or m.group(2)
        if (neg or use_abs) and not allow_mods:
            raise ValueError("Input modifiers require VOP3 encoding")
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token) and int(token, 16) > 0xffff:
        raise ValueError(f"16-bit literal out of range: {token}")
    word = vop3p_f16_word(token, scalar, vector, pending, sample_dest)
    if as_bits:
        expr = f"({word} & 0xffffu)"
        if use_abs:
            expr = f"({expr} & 0x7fffu)"
        if neg:
            expr = f"({expr} ^ 0x8000u)"
        return expr
    expr = f"widen16({word})"
    if use_abs:
        expr = f"abs({expr})"
    if neg:
        expr = f"(-{expr})"
    return expr


def f16_comparison(op, tokens, scalar, vector, pending, sample_dest, *, allow_mods):
    """The predicate of a binary16 v_cmp or v_cmpx of `tokens`: ordered relations also require num16 of both."""
    values = [f16_cmp_operand(t, scalar, vector, pending, sample_dest, allow_mods=allow_mods, as_bits=False)
              for t in tokens]
    raw = [f16_cmp_operand(t, scalar, vector, pending, sample_dest, allow_mods=allow_mods, as_bits=True)
           for t in tokens]
    ordered = f"(num16({raw[0]}) && num16({raw[1]}))"
    direct = {"lt": "lt", "eq": "eq", "le": "le", "gt": "gt", "lg": "lg", "ge": "ge"}
    negated = {"nge": "ge", "nlg": "lg", "ngt": "gt", "nle": "le", "nlt": "lt", "neq": "eq"}
    if op in direct:
        return f"({ordered} && ({COMPARE[op].format(*values)}))"
    if op in negated:
        return f"!({ordered} && ({COMPARE[negated[op]].format(*values)}))"
    if op == "o":
        return ordered
    if op == "u":
        return f"!{ordered}"
    return COMPARE[op]


def f16_class(value, classes, scalar, vector, pending, sample_dest, *, allow_mods):
    """The predicate of a binary16 v_cmp_class or v_cmpx_class: the class of the low 16 bits of `value` in the mask."""
    if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", classes):
        bits = f"{int(classes, 0) & 0xffffffff}u"
    elif re.fullmatch(r"[vs]\d+", classes):
        bits = int_operand(classes, scalar, vector, pending, sample_dest, signed=False)
    else:
        raise ValueError("Unsupported class mask")
    operand = f16_cmp_operand(value, scalar, vector, pending, sample_dest, allow_mods=allow_mods, as_bits=True)
    return f"(class16({operand}) & {bits}) != 0u"


def parse_vop3p_f16(rest, arity):
    parts_ = rest.split(", ")
    if len(parts_) != arity:
        raise ValueError("Invalid packed operand count")
    last_op, _, mod_text = parts_[-1].partition(" ")
    operands = [*parts_[:-1], last_op]
    opts = {}
    clamp = False
    for mod in mod_text.split():
        if mod == "clamp":
            if clamp:
                raise ValueError("Duplicate clamp modifier")
            clamp = True
        elif m := re.fullmatch(r"(op_sel|op_sel_hi|neg_lo|neg_hi):\[([01](?:,[01])*)\]", mod):
            name = m.group(1)
            bits = [int(b) for b in m.group(2).split(",")]
            if name in opts or len(bits) != arity:
                raise ValueError(f"Invalid packed modifier {mod}")
            opts[name] = bits
        else:
            raise ValueError(f"Unsupported packed modifier {mod}")
    return operands, opts, clamp
def fma_mix_reg(token, scalar, vector, pending, sample_dest):
    m = re.fullmatch(r"([vs])(\d+)", token)
    if not m:
        raise ValueError(f"Expected register, got {token}")
    limit = 255 if m.group(1) == "v" else 105
    if not 0 <= int(m.group(2)) <= limit:
        raise ValueError(f"Register out of range: {token}")
    if token in pending:
        raise ValueError("Constant read before load completion")
    value = (vector if m.group(1) == "v" else scalar)[token]
    if isinstance(value, int):
        return f"asfloat({value}u)", f"{value}u"
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
        return f"asfloat({value[1]})", value[1]
    if not isinstance(value, str) or not value.startswith(("sample", "alu", "params")):
        raise ValueError("Expected a numeric register")
    if token in sample_dest:
        raise ValueError("Sample used before vmcnt wait")
    return value, f"asuint({value})"


def fma_mix_operand(token, is_f16, is_hi, scalar, vector, pending, sample_dest):
    """Lower one v_fma_mix* source operand, widening f16 sources before abs/neg."""
    if token in INLINE_F16:
        if is_f16:
            word = f"{INLINE_F16[token]}u"
            return f"widen16({word} >> 16)" if is_hi else f"widen16({word})"
        return f"({token}f)"
    neg = False
    if not re.fullmatch(r"-\d+", token) and token.startswith("-"):
        neg = True
        token = token[1:]
    use_abs = False
    if m := re.fullmatch(r"abs\(([^()|]+)\)|\|([^()|]+)\|", token):
        use_abs = True
        token = m.group(1) or m.group(2)
    if is_f16:
        if token in INLINE_F16:
            word = f"{INLINE_F16[token]}u"
        elif re.fullmatch(r"[vs]\d+", token):
            _, word = fma_mix_reg(token, scalar, vector, pending, sample_dest)
        elif re.fullmatch(r"0x[0-9a-f]{1,8}", token):
            word = f"{int(token, 16)}u"
        elif re.fullmatch(r"-?\d+", token):
            val = int(token)
            if not -16 <= val <= 64:
                raise ValueError(f"Unsupported mixed-precision inline constant {token}")
            word = f"{val & 0xffffffff}u"
        else:
            raise ValueError(f"Unsupported mixed-precision operand {token}")
        expr = f"widen16({word} >> 16)" if is_hi else f"widen16({word})"
    else:
        if token in INLINE_F16:
            expr = f"({token}f)"
        elif re.fullmatch(r"[vs]\d+", token):
            expr, _ = fma_mix_reg(token, scalar, vector, pending, sample_dest)
        elif re.fullmatch(r"0x[0-9a-f]{1,8}", token):
            expr = f"asfloat({int(token, 16)}u)"
        elif re.fullmatch(r"-?\d+", token):
            val = int(token)
            if not -16 <= val <= 64:
                raise ValueError(f"Unsupported mixed-precision inline constant {token}")
            expr = f"asfloat({val & 0xffffffff}u)"
        else:
            raise ValueError(f"Unsupported mixed-precision operand {token}")
    if use_abs:
        expr = f"abs({expr})"
    if neg:
        expr = f"(-{expr})"
    return expr


def parse_fma_mix(rest):
    parts_ = rest.split(", ")
    if len(parts_) != 3:
        raise ValueError("Invalid mixed-precision operand count")
    last_op, _, mod_text = parts_[-1].partition(" ")
    operands = [*parts_[:-1], last_op]
    opts = {}
    clamp = False
    for mod in mod_text.split():
        if mod == "clamp":
            if clamp:
                raise ValueError("Duplicate clamp modifier")
            clamp = True
        elif m := re.fullmatch(r"(op_sel|op_sel_hi):\[([01],[01],[01])\]", mod):
            name = m.group(1)
            if name in opts:
                raise ValueError(f"Duplicate modifier {mod}")
            opts[name] = [int(b) for b in m.group(2).split(",")]
        else:
            raise ValueError(f"Unsupported mixed-precision modifier {mod}")
    op_sel = opts.get("op_sel", [0, 0, 0])
    op_sel_hi = opts.get("op_sel_hi", [0, 0, 0])
    if any(hi and not f16 for f16, hi in zip(op_sel, op_sel_hi)):
        raise ValueError("High-half selection requires an f16 operand")
    return operands, op_sel, op_sel_hi, clamp


def parse_div_fmas(rest):
    parts_ = rest.split(", ")
    if len(parts_) != 3:
        raise ValueError("Invalid div_fmas operand count")
    last_op, _, mod_text = parts_[-1].partition(" ")
    operands = [*parts_[:-1], last_op]
    clamp = False
    for mod in mod_text.split():
        if mod == "clamp":
            if clamp:
                raise ValueError("Duplicate clamp modifier")
            clamp = True
        else:
            raise ValueError(f"Unsupported div_fmas modifier {mod}")
    return operands, clamp
def dot_word(token, scalar, vector, pending, sample_dest, *, allow_f16=False):
    """Return a 32-bit uint HLSL expression for one VOP3P dot-product source operand."""
    if allow_f16 and token in INLINE_F16:
        return f"{INLINE_F16[token]}u"
    if m := re.fullmatch(r"([vs])(\d+)", token):
        limit = 255 if m.group(1) == "v" else 105
        if not 0 <= int(m.group(2)) <= limit:
            raise ValueError(f"Register out of range: {token}")
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = (vector if m.group(1) == "v" else scalar).get(token)
        if isinstance(value, int):
            return f"{value}u"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return value[1]
        if not isinstance(value, str) or not value.startswith(("sample", "alu", "params")):
            raise ValueError("Expected a numeric register")
        if token in sample_dest:
            raise ValueError("Sample used before vmcnt wait")
        return f"asuint({value})"
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        return f"{int(token, 16)}u"
    if re.fullmatch(r"-?\d+", token):
        val = int(token)
        if not -16 <= val <= 64:
            raise ValueError(f"Unsupported dot-product inline constant {token}")
        return f"{val & 0xffffffff}u"
    raise ValueError(f"Unsupported dot-product operand {token}")


def dot_f32_accum(token, scalar, vector, pending, sample_dest):
    if token in INLINE_F16:
        return f"({token}f)"
    return f"asfloat({dot_word(token, scalar, vector, pending, sample_dest)})"


def parse_dot(rest, *, allow_opsel, allow_neg):
    parts_ = rest.split(", ")
    if len(parts_) != 3:
        raise ValueError("Invalid dot-product operand count")
    last_op, _, mod_text = parts_[-1].partition(" ")
    operands = [*parts_[:-1], last_op]
    opts = {}
    clamp = False
    for mod in mod_text.split():
        if mod == "clamp":
            if clamp:
                raise ValueError("Duplicate clamp modifier")
            clamp = True
        elif m := re.fullmatch(r"(op_sel|op_sel_hi|neg_lo|neg_hi):\[([01],[01],[01])\]", mod):
            name = m.group(1)
            if name in opts:
                raise ValueError(f"Duplicate modifier {mod}")
            if name in ("op_sel", "op_sel_hi") and not allow_opsel:
                raise ValueError(f"Unsupported dot-product modifier {mod}")
            if name in ("neg_lo", "neg_hi") and not allow_neg:
                raise ValueError(f"Unsupported dot-product modifier {mod}")
            opts[name] = [int(b) for b in m.group(2).split(",")]
        else:
            raise ValueError(f"Unsupported dot-product modifier {mod}")
    op_sel = opts.get("op_sel", [0, 0, 0])
    op_sel_hi = opts.get("op_sel_hi", [1, 1, 1])
    neg_lo = opts.get("neg_lo", [0, 0, 0])
    neg_hi = opts.get("neg_hi", [0, 0, 0])
    if op_sel[2] != 0 or op_sel_hi[2] != 1 or neg_hi[2] != 0:
        raise ValueError("Unsupported accumulator lane modifier on dot product")
    return operands, op_sel, op_sel_hi, neg_lo, neg_hi, clamp
def vop3p_int_word(token, scalar, vector, pending, sample_dest):
    """Return a 32-bit uint HLSL expression for one packed 16-bit integer VOP3P source operand."""
    if m := re.fullmatch(r"([vs])(\d+)", token):
        limit = 255 if m.group(1) == "v" else 105
        if not 0 <= int(m.group(2)) <= limit:
            raise ValueError(f"Register out of range: {token}")
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = (vector if m.group(1) == "v" else scalar)[token]
        if isinstance(value, int):
            return f"{value}u"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return value[1]
        if not isinstance(value, str) or not value.startswith(("sample", "alu", "params")):
            raise ValueError("Expected a numeric register")
        if token in sample_dest:
            raise ValueError("Sample used before vmcnt wait")
        return f"asuint({value})"
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        return f"{int(token, 16)}u"
    if re.fullmatch(r"-?\d+", token):
        value = int(token)
        if not -16 <= value <= 64:
            raise ValueError(f"Unsupported packed integer inline constant {token}")
        return f"{value & 0xffffffff}u"
    raise ValueError(f"Unsupported packed integer operand {token}")


def parse_vop3p_int16(rest, arity, *, allow_clamp):
    parts_ = rest.split(", ")
    if len(parts_) != arity:
        raise ValueError("Invalid packed integer operand count")
    last_op, _, mod_text = parts_[-1].partition(" ")
    operands = [*parts_[:-1], last_op]
    opts = {}
    clamp = False
    for mod in mod_text.split():
        if mod == "clamp":
            if clamp or not allow_clamp:
                raise ValueError("Invalid clamp modifier")
            clamp = True
        elif m := re.fullmatch(r"(op_sel|op_sel_hi):\[([01](?:,[01])*)\]", mod):
            name = m.group(1)
            bits = [int(b) for b in m.group(2).split(",")]
            if name in opts or len(bits) != arity:
                raise ValueError(f"Invalid packed integer modifier {mod}")
            opts[name] = bits
        else:
            raise ValueError(f"Unsupported packed integer modifier {mod}")
    return operands, opts, clamp


def pk_int16_lane_expr(op, word_vars, sel, clamp):
    def u16(w, hi):
        return f"(({w} >> 16) & 0xffffu)" if hi else f"({w} & 0xffffu)"

    def i16(w, hi):
        return f"(asint({w}) >> 16)" if hi else f"(asint({w} << 16) >> 16)"

    if op == "add_i16":
        r = f"({i16(word_vars[0], sel[0])} + {i16(word_vars[1], sel[1])})"
        return f"(asuint(clamp({r}, -32768, 32767)) & 0xffffu)" if clamp else f"(asuint({r}) & 0xffffu)"
    if op == "add_u16":
        r = f"({u16(word_vars[0], sel[0])} + {u16(word_vars[1], sel[1])})"
        return f"min({r}, 65535u)" if clamp else f"({r} & 0xffffu)"
    if op == "sub_i16":
        r = f"({i16(word_vars[0], sel[0])} - {i16(word_vars[1], sel[1])})"
        return f"(asuint(clamp({r}, -32768, 32767)) & 0xffffu)" if clamp else f"(asuint({r}) & 0xffffu)"
    if op == "sub_u16":
        a, b = u16(word_vars[0], sel[0]), u16(word_vars[1], sel[1])
        return f"({a} < {b} ? 0u : ({a} - {b}))" if clamp else f"(({a} - {b}) & 0xffffu)"
    if op == "min_i16":
        return f"(asuint(min({i16(word_vars[0], sel[0])}, {i16(word_vars[1], sel[1])})) & 0xffffu)"
    if op == "min_u16":
        return f"min({u16(word_vars[0], sel[0])}, {u16(word_vars[1], sel[1])})"
    if op == "max_i16":
        return f"(asuint(max({i16(word_vars[0], sel[0])}, {i16(word_vars[1], sel[1])})) & 0xffffu)"
    if op == "max_u16":
        return f"max({u16(word_vars[0], sel[0])}, {u16(word_vars[1], sel[1])})"
    if op == "mul_lo_u16":
        return f"(({u16(word_vars[0], sel[0])} * {u16(word_vars[1], sel[1])}) & 0xffffu)"
    if op == "mad_i16":
        r = f"({i16(word_vars[0], sel[0])} * {i16(word_vars[1], sel[1])} + {i16(word_vars[2], sel[2])})"
        return f"(asuint(clamp({r}, -32768, 32767)) & 0xffffu)" if clamp else f"(asuint({r}) & 0xffffu)"
    if op == "mad_u16":
        r = f"({u16(word_vars[0], sel[0])} * {u16(word_vars[1], sel[1])} + {u16(word_vars[2], sel[2])})"
        return f"min({r}, 65535u)" if clamp else f"({r} & 0xffffu)"
    if op in ("min3_i16", "max3_i16", "med3_i16", "min3_u16", "max3_u16", "med3_u16"):
        kind = op[-3:]
        a, b, c = ((i16 if kind == "i16" else u16)(w, hi) for w, hi in zip(word_vars, sel))
        r = {"min3": f"min(min({a}, {b}), {c})", "max3": f"max(max({a}, {b}), {c})",
             "med3": f"max(min({a}, {b}), min(max({a}, {b}), {c}))"}[op[:4]]
        return f"(asuint({r}) & 0xffffu)" if kind == "i16" else r
    if op == "lshlrev_b16":
        return f"(({u16(word_vars[1], sel[1])} << ({u16(word_vars[0], sel[0])} & 15u)) & 0xffffu)"
    if op == "lshrrev_b16":
        return f"({u16(word_vars[1], sel[1])} >> ({u16(word_vars[0], sel[0])} & 15u))"
    if op == "ashrrev_i16":
        return f"(asuint({i16(word_vars[1], sel[1])} >> ({u16(word_vars[0], sel[0])} & 15u)) & 0xffffu)"
    raise ValueError(f"Unknown 16-bit integer op {op}")
# SDWA selections: (bit offset, width). A source selection is zero-extended, or sign-extended with sext();
# a destination selection writes the low bits of the result into that field. Following the equivalences in
# LLVM's SIPeepholeSDWA, UNUSED_PAD zeroes the other bits and UNUSED_PRESERVE keeps them from the destination.
SDWA_SEL = {"BYTE_0": (0, 8), "BYTE_1": (8, 8), "BYTE_2": (16, 8), "BYTE_3": (24, 8),
            "WORD_0": (0, 16), "WORD_1": (16, 16), "DWORD": (0, 32)}


def sdwa_source(word, sel, sext):
    offset, width = SDWA_SEL[sel]
    if width == 32:
        return word
    if sext:
        return f"asuint(asint({word} << {32 - offset - width}u) >> {32 - width}u)"
    return f"(({word} >> {offset}u) & {(1 << width) - 1:#x}u)"


def sdwa_dest(result, sel, unused, old):
    offset, width = SDWA_SEL[sel]
    if width == 32:
        return result
    if unused == "UNUSED_SEXT":
        raise ValueError("UNUSED_SEXT is not lowered")
    field = f"(({result} & {(1 << width) - 1:#x}u) << {offset}u)"
    if unused == "UNUSED_PAD":
        return field
    # The kept bits must come from a tracked numeric value; hardware would keep whatever an untracked register holds.
    if not (isinstance(old, str) and old.startswith(("sample", "alu", "params"))):
        raise ValueError("UNUSED_PRESERVE needs a tracked numeric destination")
    keep = ~(((1 << width) - 1) << offset) & 0xffffffff
    return f"((asuint({old}) & {keep:#x}u) | {field})"
# Binary32 arithmetic with SDWA forms on gfx1013 (docs/coverage/gfx1013.tsv): the exact operations, then the
# remaining unary ones. Each reuses its e32/e64 entry in ALU unchanged.
SDWA_ALU = ("add", "sub", "subrev", "mul", "mul_legacy", "max", "min", "floor", "ceil", "fract", "trunc",
            "exp", "log", "rcp_iflag", "rcp", "rsq", "sqrt", "sin", "cos", "rndne", "frexp_mant")

# 32-bit integer operations with SDWA forms: (source count, expression on the selected unsigned words). The
# selections never change the operation: LLVM's SIPeepholeSDWA folds a byte or word extract (zero-extended, or
# sign-extended under sext()) into a source of whichever instruction consumes it, and a left shift by 16 or 24
# of the result into its dst_sel, so each form is its e32 operation on the extracted words, placed like a move.
SDWA_INT = {
    **{op: INTEGER[op] for op in ("and_b32", "or_b32", "xor_b32", "xnor_b32", "not_b32",
                                  "lshlrev_b32", "lshrrev_b32", "ashrrev_i32")},
    "add_nc_u32": (2, "{0} + {1}"), "sub_nc_u32": (2, "{0} - {1}"), "subrev_nc_u32": (2, "{1} - {0}"),
    "min_u32": (2, "min({0}, {1})"), "max_u32": (2, "max({0}, {1})"),
    "min_i32": (2, "asuint(min(asint({0}), asint({1})))"), "max_i32": (2, "asuint(max(asint({0}), asint({1})))"),
}
SDWA_INT_SOURCE = r"(sext\()?([vs]\d+)(\))?"
SDWA_INT_OPERANDS = re.compile(
    rf"(v\d+), {SDWA_INT_SOURCE}(?:, {SDWA_INT_SOURCE})? dst_sel:(BYTE_[0-3]|WORD_[01]|DWORD)"
    r" dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE) src0_sel:(BYTE_[0-3]|WORD_[01]|DWORD)"
    r"(?: src1_sel:(BYTE_[0-3]|WORD_[01]|DWORD))?")


class VectorRegisters(dict):
    """Register tracker for vector registers with uniform provenance tracking."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uniform = set()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.uniform.discard(key)

    def is_uniform(self, reg):
        return reg in self.uniform

MISSING = object()

# Only operations with per-lane, safe speculative evaluation enter the region. Stage 2 of issue #932 adds the
# per-lane binary32 forms the translator already lowers outside regions, in the encodings measured in real
# regions; each still passes the per-instruction check in lower() (only VGPRs may change).
REGION_ALU = re.compile(
    r"v_(?:mov_b32|(?:add|sub|subrev|mul|min|max)_f32)(?:_e32|_e64)? "
    r"|v_(?:fmac|mac|rcp|rsq|sqrt)_f32_e32 |v_cvt_f32_ubyte[0-3]_e32 |v_mul_legacy_f32_e(?:32|64) "
    r"|v_(?:fma|mad|med3)_f32 ")
# Only scalar ALU whose lowerings already validate their operands and effects may run in a region.
REGION_SALU = re.compile(
    r"s_(?:mov_b32|movk_i32) s\d+, (?:s\d+|0x[0-9a-f]+|\d+)"
    r"|s_(?:add|mul)_i32 s\d+, [^,]+, [^,]+"
    r"|s_cmp_(?:eq|lg|gt|ge|lt|le)_i32 [^,]+, [^,]+"
    r"|s_cselect_b32 s\d+, [^,]+, [^,]+")
REGION_SALU_DEST = re.compile(r"s_(?:mov_b32|movk_i32|add_i32|mul_i32|cselect_b32) (s\d+),")
# Stage 1 of issue #987: scalar instructions that leave every tracked register and counter unchanged may also sit
# in a region, because skipping them with the whole wave (s_cbranch_execz) or running them changes nothing.
REGION_NOP = re.compile(r"s_nop (?:0x[0-9a-f]+|\d+)")
# Stage 3 of issue #987: scalar loads run whatever the execution mask, so the constant and pointer loads the
# translator already lowers may sit in a region. Group 1 is a single destination SGPR, groups 2 and 3 a range.
REGION_SLOAD = re.compile(
    r"s_(?:buffer_)?load_dword(?:x(?:2|4|8))? (?:s(\d+)|s\[(\d+):(\d+)\]), s\[\d+:\d+\], (?:0x[0-9a-f]+|null)")
WAIT_COUNTERS = {"vmcnt": "vm", "lgkmcnt": "lgkm", "expcnt": "exp", "vscnt": "vs"}


def wait_counters(line):
    """The counters a wait instruction names, or None when line is not a wait.

    Only the names are read here. The main wait handler still validates operands and field widths and refuses
    every form it does not model, so a malformed wait is rejected there.
    """
    if m := re.fullmatch(r"s_waitcnt_(vmcnt|lgkmcnt|expcnt|vscnt)(?:\s.*)?", line):
        return {WAIT_COUNTERS[m[1]]}
    if m := re.fullmatch(r"s_waitcnt\s+(.*)", line):
        payload = m[1].strip()
        if payload in ("0", "0x0"):
            return {"vm", "lgkm", "exp"}
        return {WAIT_COUNTERS[token.split("(", 1)[0]] for token in payload.split()
                if token.split("(", 1)[0] in WAIT_COUNTERS}
    return None


SCALAR_OPERAND = re.compile(r"s(?:\d|[1-9]\d|10[0-5])|vcc")
VECTOR_OPERAND = re.compile(r"v(?:\d|[1-9]\d|1\d\d|2[0-4]\d|25[0-5])")


class UnboundOperand(ValueError):
    """A guest register is read while lower() holds no value for it.

    The register is an entry register the caller did not bind (only the texture table, the interpolation base,
    v0, v1 and the entry registers of the constant contract start bound) or a register no earlier instruction
    wrote. bank is "scalar" or "vector", index the 0-based instruction number, offset its byte offset when lower()
    received (offset, text) pairs and None otherwise. Only s0-s105, vcc and v0-v255 are reported this way: any
    other missing key in the register state is an internal lookup error and stays a KeyError.
    """

    def __init__(self, bank, register, index, offset, instruction):
        self.bank, self.register = bank, register
        self.index, self.offset, self.instruction = index, offset, instruction
        where = "" if offset is None else f" (byte offset {offset:#x})"
        super().__init__(f"Unbound {bank} operand {register} at instruction {index}{where}: {instruction}")


def unbound_operand(registers, key, pattern, bank):
    """Raise UnboundOperand for a missing guest register read inside an instruction, else a plain KeyError."""
    if registers.site is not None and isinstance(key, str) and pattern.fullmatch(key):
        raise UnboundOperand(bank, key, *registers.site)
    raise KeyError(key)


class TrackedVector(VectorRegisters):
    """Vector register names that record reads, so a conditionally-written register can be refused."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = []
        self.masked = False
        self.conditional = set()
        self.site = None  # (index, byte offset or None, text) of the instruction being lowered

    def __getitem__(self, key):
        self.reads.append(key)
        return super().__getitem__(key)

    def __missing__(self, key):
        unbound_operand(self, key, VECTOR_OPERAND, "vector")

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)

    def __setitem__(self, key, value):
        if not self.masked:
            self.conditional.discard(key)
        super().__setitem__(key, value)


class TrackedScalar(dict):
    """Track conditional scalar definitions and invalidate bitmasks on writes."""

    def __init__(self, initial, mask_map):
        super().__init__(initial)
        self._mask_map = mask_map
        self.reads = []
        self.masked = False
        self.conditional = set()
        self.site = None  # as TrackedVector.site

    def __getitem__(self, key):
        self.reads.append(key)
        return super().__getitem__(key)

    def __missing__(self, key):
        unbound_operand(self, key, SCALAR_OPERAND, "scalar")

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)

    def __setitem__(self, key, value):
        self._mask_map.pop(key, None)
        if not self.masked:
            self.conditional.discard(key)
        super().__setitem__(key, value)


def lower(instructions, texture_sgpr, interp_sgpr, sampler, constant_descriptor=None, *,
          texture_offset=0, second_texture_offset=None, integer_export=False, texcoord_components=2, extra_constants=(),
          title_ranges=None, flat_global_only=False, return_write_mask=False, wave_size=None, half_denorm=None,
          pointer_constants=(), cpu="gfx1013", gather_mips=None):
    """Track descriptor provenance, interpolation and packed or uncompressed exports.

    texture_offset is the aligned byte offset of t0 in the texture descriptor table.
    gather_mips declares the number of visible mips in matching gfx1030 and desktop 2D views.
    For comparison gather the selected red texel values and the reference must be in [0, 1].
    Gather coordinates must map to the same half-texel lattice on both views (see experiments.md).
    constant_descriptor is the byte offset, on the texture table, of the descriptor mapped to b0.
    Each extra_constants entry is an (entry SGPR, byte offset) pair naming one further 16-byte
    descriptor; the entries map in order to b1 onward. The SGPR may be the texture table or another
    entry register that holds the low word of a table address.
    Each pointer_constants entry is an (entry SGPR, pointer byte offset, pointer dwords, descriptor byte offset)
    tuple naming one 16-byte descriptor in a nested table. The entry SGPR names a table as in extra_constants;
    the pointer at that table offset is read by s_load_dwordx2 (2 dwords, a full 64-bit address) or by
    s_load_dword (1 dword, a low word whose high word the program must set to 0). The descriptor sits at the
    given offset of the table that pointer addresses. The entries map in order to the slots after extra_constants.
    title_ranges is the bound range count at t0, space1. flat_global_only
    requires every flat address to be global and excludes the scratch and LDS apertures.
    return_write_mask returns (source, RT0 mask). For partial compressed exports the caller
    must supply normalized whole-pair instructions and apply the returned mask in the PSO.
    Uncompressed partial exports use the same opt-in for floating-point and integer targets.
    wave_size names the guest execution width (32 or 64). Low-only execution mask operations
    (s_mov_b32 save of exec_lo, s_wqm_b32, and s_and_b32/s_mov_b32 restore) require a validated
    guest wave32 profile (wave_size=32); native Scarlett/GFX10 wave64 operations remain independent
    of guest profile declarations.
    half_denorm declares the binary16 denormal state at shader entry (MODE[7:6]). Only "preserve" is accepted; None
    means unknown, and the plain binary16 VOP2 arithmetic forms are then refused. The caller takes it from validated
    guest state; the translator does not measure or track it.
    A read of a guest register that holds no tracked value raises UnboundOperand, a ValueError that names the
    register and the instruction, so a missing entry binding is not mistaken for an unsupported instruction.
    """
    if cpu not in ("gfx1013", "gfx1030"):
        raise ValueError("Unsupported pixel target")
    if gather_mips is not None:
        if (cpu != "gfx1030" or sampler is None or second_texture_offset is not None or integer_export
                or type(gather_mips) is not int or not 1 <= gather_mips <= 16):
            raise ValueError("Gather requires a gfx1030 float pixel profile with one texture and 1 to 16 visible mips")
    if title_ranges is not None and (isinstance(title_ranges, bool) or not isinstance(title_ranges, int)
                                     or not 1 <= title_ranges <= 0xffffffff):
        raise ValueError("Invalid title range count")
    if texture_sgpr == interp_sgpr or not 0 <= texture_sgpr <= 105 or not 0 <= interp_sgpr <= 105:
        raise ValueError("Invalid scalar inputs")
    if sampler is not None and (len(sampler) != 4 or any(not 0 <= word <= 0xffffffff for word in sampler)):
        raise ValueError("Invalid sampler descriptor words")
    if texture_offset < 0 or texture_offset % 32:
        raise ValueError("Texture descriptor offset must be non-negative and 32-byte aligned")
    if sampler is None and texture_offset != 0:
        raise ValueError("Texture offset requires a sampler")
    if texcoord_components not in (2, 4):
        raise ValueError("Expected two or four TEXCOORD components")
    if wave_size is not None and (not isinstance(wave_size, int) or wave_size not in (32, 64)):
        raise ValueError(f"Invalid guest wave size: {wave_size}")
    guest_wave32 = wave_size == 32
    if half_denorm not in (None, HALF_DENORM_PRESERVE):
        raise ValueError(f"Invalid binary16 denormal entry state: {half_denorm}")
    scalar_mask = {}
    scalar = TrackedScalar({f"s{texture_sgpr}": "texture_ptr", f"s{interp_sgpr}": "interp_base"}, scalar_mask)
    vector = TrackedVector({"v0": "bary_i", "v1": "bary_j"})
    known_ssa_bits: dict[str, int] = {}
    # Provenance of binary64 words: SSA name of a VGPR word -> (record, 0 for the low word or 1 for the high word).
    # The record names what the pair holds: ("i32" | "u32", name of the uint source of v_cvt_f64_i32 | v_cvt_f64_u32)
    # or ("static", low, high) for v_cvt_f64_f32 of a statically known source. Every word value is an immutable
    # HLSL temporary, so an overwritten word names another SSA value and loses its entry; v_mov_b32 and a join of
    # equal entries are the only ways the entry travels. v_cvt_i32_f64, v_cvt_u32_f64 and v_cvt_f32_f64 read it.
    f64_words: dict[str, tuple] = {}
    known_half: dict[str, int] = {}  # half16 result name -> proven binary16 bits
    # Each emitted value has a unique identity. Entry-only writes never gain a helper definition.
    # The boolean records whether the quad value depends on interpolated coordinates.
    quad_values = {"uv.x": True, "uv.y": True}
    lines = [PREAMBLE] if sampler is None else [SAMPLED_RESOURCES, PREAMBLE]
    if constant_descriptor is not None:
        if constant_descriptor < 0 or constant_descriptor % 4:
            raise ValueError("Invalid constant descriptor offset")
        constant_vector = "uint4" if integer_export else "float4"
        lines.insert(0, f"cbuffer Constants : register(b0) {{ {constant_vector} params[16]; }};")
    bindings = {} if sampler is None else {texture_offset: "tex"}
    if second_texture_offset is not None:
        if sampler is None:
            raise ValueError("Second texture requires a sampler")
        if (second_texture_offset < 0 or second_texture_offset % 32
                or abs(second_texture_offset - texture_offset) < 32):
            raise ValueError("Second texture descriptor must have a distinct aligned offset")
        bindings[second_texture_offset] = "tex1"
        lines.insert(0, "Texture2D<float4> tex1 : register(t1);")
    if constant_descriptor is not None and any(
            start < constant_descriptor + 16 and constant_descriptor < start + 32 for start in bindings):
        raise ValueError("Texture and constant descriptors overlap")
    # (table marker, descriptor byte offset) -> HLSL array. A table other than the texture table
    # is an entry SGPR whose only accepted use is the low address word of a descriptor load.
    constants = {} if constant_descriptor is None else {("texture_ptr", constant_descriptor): "params"}
    for slot, entry in enumerate(extra_constants, 1):
        if (len(entry) != 2 or any(type(word) is not int for word in entry) or not 0 <= entry[0] <= 105
                or entry[0] == interp_sgpr or entry[1] < 0 or entry[1] % 4):
            raise ValueError("Invalid constant descriptor binding")
        table = "texture_ptr" if entry[0] == texture_sgpr else ("constant_table", entry[0])
        if any(other == table and abs(start - entry[1]) < 16 for other, start in constants):
            raise ValueError("Constant descriptors overlap")
        if table == "texture_ptr" and any(start < entry[1] + 16 and entry[1] < start + 32 for start in bindings):
            raise ValueError("Texture and constant descriptors overlap")
        constants[table, entry[1]] = f"params{slot}"
        scalar[f"s{entry[0]}"] = table
        lines.insert(0, f"cbuffer Constants{slot} : register(b{slot}) {{ float4 params{slot}[16]; }};")
    # Nested tables: (parent table, pointer byte offset) -> pointer dwords. The low SGPR of a loaded pointer
    # holds ("pointer_table", parent, offset); a 64-bit pointer's high SGPR holds ("pointer_high", parent, offset).
    pointers = {}
    integer_params = {"params"} if integer_export else set()
    for slot, entry in enumerate(pointer_constants, len(extra_constants) + 1):
        if (len(entry) != 4 or any(type(word) is not int for word in entry) or not 0 <= entry[0] <= 105
                or entry[0] == interp_sgpr or entry[1] < 0 or entry[1] % 4 or entry[2] not in (1, 2)
                or entry[3] < 0 or entry[3] % 4):
            raise ValueError("Invalid pointer constant binding")
        sgpr, pointer_offset, dwords, descriptor_offset = entry
        parent = "texture_ptr" if sgpr == texture_sgpr else ("constant_table", sgpr)
        if pointers.get((parent, pointer_offset), dwords) != dwords:
            raise ValueError("Pointer width differs between bindings")
        span = (pointer_offset, pointer_offset + 4 * dwords)
        if any(other == parent and start != pointer_offset and start < span[1] and span[0] < start + 4 * width
               for (other, start), width in pointers.items()):
            raise ValueError("Table pointers overlap")
        if any(other == parent and start < span[1] and span[0] < start + 16 for other, start in constants):
            raise ValueError("Table pointer overlaps a constant descriptor")
        if parent == "texture_ptr" and any(start < span[1] and span[0] < start + 32 for start in bindings):
            raise ValueError("Table pointer overlaps a texture descriptor")
        pointers[parent, pointer_offset] = dwords
        table = ("pointer_table", parent, pointer_offset)
        if any(other == table and abs(start - descriptor_offset) < 16 for other, start in constants):
            raise ValueError("Constant descriptors overlap")
        constants[table, descriptor_offset] = f"params{slot}"
        if integer_export:
            integer_params.add(f"params{slot}")
        if parent != "texture_ptr":
            scalar[f"s{sgpr}"] = parent
        vector_type = "uint4" if integer_export else "float4"
        lines.insert(0, f"cbuffer Constants{slot} : register(b{slot}) {{ {vector_type} params{slot}[16]; }};")
    pending = set()
    scc = None
    helpers = set()
    half_rounding = HALF_ROUNDING["0"]
    mode_rounding = None  # MODE[3:2] as this program last wrote it; None while only the assumed entry value exists
    mask = "entry"
    wqm_width = None
    samples = 0
    sampled_textures = set()
    sample_kind = None  # "plain", "comparison" or "gather" resource interpretation
    vector_loads = 0  # image samples and title loads issued, in vmcnt order
    title_loads = False
    sample_dest = {}  # VGPR -> issue number of its outstanding image_sample or title load
    ds_needs_wait = False
    exported = False
    channel_mask = 0xF
    ended = False
    entry_line = len(lines)
    result_type = "uint4" if integer_export else "float4"
    lines.append(f"{result_type} main(float2 uv : TEXCOORD0) : SV_Target0 {{")
    attribute_input = False
    interpolated = False
    region = None
    seen_skip = False
    has_scratch = False
    scratch_written = set()
    instructions = tuple(instructions)
    if any(isinstance(element, tuple) for element in instructions):
        offset_index = {}
        previous_offset = -1
        for index, element in enumerate(instructions):
            if (not isinstance(element, tuple) or len(element) != 2
                    or type(element[0]) is not int or not isinstance(element[1], str)):
                raise ValueError("Invalid (offset, text) instruction pair")
            offset = element[0]
            if offset <= previous_offset or offset % 4:
                raise ValueError("Instruction offsets must be strictly increasing and DWORD aligned")
            offset_index[offset] = index
            previous_offset = offset
        positioned = instructions
    else:
        if not all(isinstance(element, str) for element in instructions):
            raise ValueError("Invalid instruction element")
        offset_index = {}
        positioned = ((None, line) for line in instructions)

    def join_f64_word(name, *values):
        """A joined register keeps its binary64 word provenance only if every path carries the same entry."""
        entry = f64_words.get(values[0])
        if entry is not None and all(f64_words.get(value) == entry for value in values[1:]):
            f64_words[name] = entry

    def close_region(i, pair):
        """Merge every register the open region rewrote with a per-lane select on its condition."""
        nonlocal scc
        if (region is None or pair != region["save"]
                or (region["skip"] is not None and region["skip"] != i)):
            raise ValueError("Unexpected execution mask restore")
        if region["else"] is not None:
            # Join of an if/else (issue #1315): each register takes its then-arm value where the condition holds
            # and its else-arm value elsewhere, the pre-region value standing in for an arm that did not write it.
            # A register undefined before the region and on either arm stays undefined after the join.
            else_written = region["else_written"]
            for dst in [*region["written"], *(d for d in else_written if d not in region["written"])]:
                outer = region["written"][dst] if dst in region["written"] else else_written[dst]
                in_then, in_else = dst in region["then"], dst in else_written
                if dst in vector.conditional or (outer is MISSING and not (in_then and in_else)):
                    vector.conditional.add(dst)
                    continue
                if outer is not MISSING and (not isinstance(outer, str) or outer in ("bary_i", "bary_j")):
                    raise ValueError("Masked region rewrites a register without a numeric value")
                then_value = region["then"][dst] if in_then else outer
                else_value = dict.get(vector, dst) if in_else else outer
                lines.append(f"    precise float alu{i}_{dst} = ({region['cond']} ? {then_value} : {else_value});")
                vector[dst] = f"alu{i}_{dst}"
                join_f64_word(vector[dst], then_value, else_value)
        for dst, outer in ({} if region["else"] is not None else region["written"]).items():
            if outer is MISSING or dst in vector.conditional:
                vector.conditional.add(dst)
                continue
            if not isinstance(outer, str) or outer in ("bary_i", "bary_j"):
                raise ValueError("Masked region rewrites a register without a numeric value")
            inner = vector[dst]
            lines.append(f"    precise float alu{i}_{dst} = ({region['cond']} ? {inner} : {outer});")
            vector[dst] = f"alu{i}_{dst}"
            join_f64_word(vector[dst], inner, outer)
        if region["skipped"]:
            # A wave that skipped the region (or one arm) never ran its waits, so what was outstanding at the opener
            # still is.
            before_pending, before_samples = region["outstanding"]
            pending.update(before_pending)
            sample_dest.update(before_samples)
        vector.masked = False
        vector.reads.clear()
        scalar.masked = False
        scalar.conditional.update(region["scalar_written"])
        if region["scc_written"]:
            scc = None

    for i, (offset, line) in enumerate(positioned):
        if region is not None and region["opener"] == "scc" and i == region["end"]:
            if region["join"] is not None and region["else"] is None:
                # Block A's terminal s_branch (issue #1413 stage 2): switch to block B, which starts from the
                # incoming vector state. A register first defined by A is undefined in B until B writes it.
                region["then"] = {dst: dict.get(vector, dst) for dst in region["written"]}
                for dst, outer in region["written"].items():
                    if outer is MISSING:
                        region["else_undefined"].add(dst)
                    else:
                        vector[dst] = outer
                region["else"] = region["arm_start"] = i
                region["end"] = region["join"]
                continue
            # A uniform skip block, or a diamond at JOIN, ends where its branch lands, before that instruction
            # runs and is checked.
            close_region(i, None)
            region = None
        vector.reads.clear()
        scalar.reads.clear()
        scalar.site = vector.site = (i, offset, line)
        conditional = set(vector.conditional)
        scalar_conditional = set(scalar.conditional)
        def match(pattern):
            return re.fullmatch(pattern, line)

        if ended:
            raise ValueError("Instruction follows program end")
        if ds_needs_wait:
            if line != "s_waitcnt lgkmcnt(0)":
                raise ValueError("ds_swizzle_b32 requires an immediate s_waitcnt lgkmcnt(0)")
            ds_needs_wait = False
        rstate = None
        if region is not None and region["opener"] == "scc":
            # A uniform skip block (issue #1413) admits only per-lane vector ALU and s_nop: no memory, EXEC,
            # scalar or wave updates and no nested branch or region.
            if REGION_NOP.fullmatch(line):
                pass
            elif not REGION_ALU.match(line):
                raise ValueError(f"Instruction cannot run in a uniform skip block: {line}")
            else:
                rstate = (dict(scalar), dict(vector), scc, set(pending), dict(sample_dest),
                          exported, ended, mask, attribute_input, interpolated,
                          dict(quad_values), samples, False)
        elif region is not None:
            if re.fullmatch(r"s_or_b64 exec, exec, s\[\d+:\d+\]|s_mov_b64 exec, s\[\d+:\d+\]", line):
                pass
            elif re.fullmatch(r"s_andn2_b64 exec, s\[\d+:\d+\], exec", line):
                pass
            elif (re.fullmatch(r"s_cbranch_execz -?(?:0x[0-9a-f]+|\d+)", line)
                    and i == region["arm_start"] + 1 and region["skip"] is None):
                pass
            elif REGION_NOP.fullmatch(line):
                pass
            elif (counters := wait_counters(line)) is not None:
                if re.match(r"s_waitcnt_expcnt\s+s\d+,", line):
                    raise ValueError(f"Unsupported s_waitcnt_expcnt SGPR operand in a masked region: {line}")
                # A wait is a scalar instruction: it runs whatever the execution mask, so the main wait handler
                # below resolves outstanding vm/lgkm work exactly as it does outside a region. A region that the
                # whole wave may skip (s_cbranch_execz) leaves that work outstanding on the skipping path, so
                # close_region puts the pre-region outstanding state back after such a region. No export can be
                # outstanding (only s_endpgm may follow one). Scratch stores are not tracked on the store
                # counter, so vscnt is unknown once any store has been lowered.
                if "vs" in counters and scratch_written:
                    raise ValueError(f"Store counter state is unknown after a scratch store in a masked region: {line}")
            elif sload := REGION_SLOAD.fullmatch(line):
                loaded = ({f"s{sload[1]}"} if sload[1] is not None
                          else {f"s{n}" for n in range(int(sload[2]), int(sload[3]) + 1)})
                if loaded.intersection(region["save"]):
                    raise ValueError(f"Masked scalar load overwrites the saved execution pair: {line}")
                rstate = (dict(scalar), dict(vector), scc, set(pending), dict(sample_dest),
                          exported, ended, mask, attribute_input, interpolated,
                          dict(quad_values), samples, loaded)
            elif REGION_SALU.fullmatch(line):
                destination = REGION_SALU_DEST.match(line)
                if destination and destination[1] in region["save"]:
                    raise ValueError(f"Masked scalar ALU overwrites the saved execution pair: {line}")
                rstate = (dict(scalar), dict(vector), scc, set(pending), dict(sample_dest),
                          exported, ended, mask, attribute_input, interpolated,
                          dict(quad_values), samples, True)
            elif not REGION_ALU.match(line):
                raise ValueError(f"Instruction cannot run in a masked region: {line}")
            else:
                rstate = (dict(scalar), dict(vector), scc, set(pending), dict(sample_dest),
                          exported, ended, mask, attribute_input, interpolated,
                          dict(quad_values), samples, False)
        if match(r"(?:s_inst_prefetch|s_nop) (?:0x[0-9a-f]+|\d+)"):
            continue
        # SOPK s_version K (gfx10+) has no destination and does not write SCC: a marker with no effect.
        # Like s_nop it is also accepted after the color export. The operand is a 16-bit immediate.
        if line == "s_version" or line.startswith("s_version "):
            if not (m := match(r"s_version (0x[0-9a-f]+|0|[1-9]\d*)")) or int(m[1], 0) > 0xffff:
                raise ValueError(f"Invalid s_version operand: {line}")
            continue
        if match(r"s_waitcnt_expcnt\s+(?:(?:null|s\d+),\s*)?(?:0x[0-7]|[0-7])"):
            continue
        if match(r"s_waitcnt\s+expcnt\([0-7]\)"):
            continue
        if exported and line != "s_endpgm":
            raise ValueError("Unexpected instruction after color export")
        # The operandless DS NOP leaves registers and memory untouched in either EXEC region.
        if line == "ds_nop":
            continue
        # v_nop_e64 is the VOP3 encoding of the same no-op; LLVM 15 prints both encodings as v_nop.
        if line in ("v_nop", "v_nop_e64"):
            if mask != "entry":
                raise ValueError("Unexpected v_nop with non-entry mask")
            continue
        # v_pipeflush flushes a VALU destination cache and v_clrexcp clears the wave's exception state, which only
        # s_getreg_b32 of the trap status could observe and which is not lowered; LLVM 15 prints both encodings of
        # each without a suffix (#1791).
        if line in ("v_clrexcp", "v_clrexcp_e64", "v_pipeflush", "v_pipeflush_e64"):
            if mask != "entry":
                raise ValueError(f"Unexpected {line} with non-entry mask")
            continue
        # Scheduling, performance and trace hints with no effect on results. Each operand is limited to the width of
        # its RDNA 2 field: clause length minus one, wave priority, sleep duration, the performance counter in
        # SIMM16[3:0], and the 16-bit trace data.
        if m := match(rf"({'|'.join(HINT_LIMITS)}) (0x[0-9a-f]+|\d+)"):
            if int(m[2], 0) > HINT_LIMITS[m[1]]:
                raise ValueError(f"Invalid {m[1]} operand")
            continue
        if line in OPERANDLESS_HINTS:
            continue
        # A hardware register write is state, not a hint: it is accepted only where its effect on the
        # lowered program is known, and every other register, field or value is refused.
        if m := match(r"s_setreg_imm32_b32 hwreg\((\w+)(?:, (\d+), (\d+))?\), (\S+)"):
            register, offset, size, value = m.groups()
            if register in FLAT_SCRATCH and offset is None:
                if re.fullmatch(r"0x[0-9a-f]{1,8}", value):
                    continue
                if re.fullmatch(r"-?[0-9]{1,10}", value) and -0x80000000 <= int(value) <= 0xffffffff:
                    continue
            if (register, offset, size) != ("HW_REG_MODE", "2", "2"):
                raise ValueError(f"Unsupported hardware register write: {line}")
            if value not in HALF_ROUNDING:
                raise ValueError(f"Unsupported binary16 rounding mode: {line}")
            half_rounding = HALF_ROUNDING[value]
            mode_rounding = int(value)
            continue
        # The register forms. The source SGPR is read, so it must be bound, resolved and defined on every path; the
        # shared check at the end of the loop is skipped by `continue`, hence the explicit test here. Neither form can
        # run in a masked region (they are not in REGION_SALU), so the tracked state is straight-line.
        if line == "s_setreg_b32" or line.startswith("s_setreg_b32 "):
            if not (m := match(r"s_setreg_b32 hwreg\((\w+)(?:, (\d+), (\d+))?\), (s\d+)")):
                raise ValueError(f"Malformed s_setreg_b32 operands: {line}")
            register, offset, size, source = m.groups()
            sgpr_name(source)
            whole_scratch = register in FLAT_SCRATCH and offset is None
            if not whole_scratch and (register, offset, size) != ("HW_REG_MODE", "2", "2"):
                raise ValueError(f"Unsupported hardware register write: {line}")
            if source in pending:
                raise ValueError("Unresolved scalar memory dependency")
            value = scalar[source]
            if source in scalar_conditional:
                raise ValueError(f"Read of a register defined only on the masked path {i}: {line}")
            if not whole_scratch:
                if type(value) is not int:
                    raise ValueError(f"Unsupported binary16 rounding mode, the SGPR is not a known integer: {line}")
                if str(value) not in HALF_ROUNDING:
                    raise ValueError(f"Unsupported binary16 rounding mode: {line}")
                half_rounding = HALF_ROUNDING[str(value)]
                mode_rounding = value
            continue
        if line == "s_getreg_b32" or line.startswith("s_getreg_b32 "):
            if not (m := match(r"s_getreg_b32 (s\d+), hwreg\((\w+)(?:, (\d+), (\d+))?\)")):
                raise ValueError(f"Malformed s_getreg_b32 operands: {line}")
            dst, register, offset, size = m.groups()
            sgpr_name(dst)
            if (register, offset, size) != ("HW_REG_MODE", "2", "2"):
                raise ValueError(f"Unsupported hardware register read: {line}")
            if mode_rounding is None:
                raise ValueError(f"MODE rounding is read before the program writes it: {line}")
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            scalar[dst] = mode_rounding
            scalar_mask[dst] = mode_rounding
            continue
        if (half_rounding != HALF_ROUNDING["0"] and re.match(r"v_\w*_f(?:16|64)", line)
                and not line.startswith(HALF_ROUNDING_EXEMPT)):
            raise ValueError(f"Unsupported binary16 or binary64 operation under round {half_rounding}: {line.split()[0]}")
        # gfx10 SOPK wait forms: `s_waitcnt_<counter> <sgpr|null>, <simm16>`. Only null is modelled, since it
        # reads as 0 and the count is then the immediate; an SGPR value would add to or replace it.
        # vmcnt and lgkmcnt act exactly like the vmcnt(K) and lgkmcnt(K) tokens of s_waitcnt. vscnt is a no-op:
        # this translator lowers no vector memory stores, so nothing is outstanding on the store counter.
        sopk_wait = None
        if m := match(r"s_waitcnt_(vmcnt|lgkmcnt|vscnt)(?:\s+(.*))?"):
            counter = m[1]
            label = {"vmcnt": "VM", "lgkmcnt": "LGKM", "vscnt": "VS"}[counter]
            operands = [part.strip() for part in (m[2] or "").split(",")]
            if len(operands) != 2 or not re.fullmatch(r"0x[0-9a-f]+|0|[1-9]\d*", operands[1]):
                raise ValueError(f"Malformed s_waitcnt_{counter} operands: {line}")
            if operands[0] != "null":
                raise ValueError(f"Unsupported s_waitcnt_{counter} SGPR operand (only null is modelled): {line}")
            count = int(operands[1], 0)
            if count > 63:
                raise ValueError(f"{label} wait count exceeds the gfx10 six-bit field")
            if counter == "vscnt":
                continue
            sopk_wait = f"{counter}({count})"
        wait_match = match(r"s_waitcnt\s+(.*)")
        if sopk_wait is not None or wait_match:
            payload = sopk_wait if sopk_wait is not None else wait_match[1].strip()
            if payload in ("0", "0x0"):
                pending.clear()
                sample_dest.clear()
            else:
                has_vm, has_lgkm, has_exp = False, False, False
                for token in payload.split():
                    if vm_match := re.fullmatch(r"vmcnt\((\d+)\)", token):
                        if has_vm:
                            raise ValueError(f"Duplicate vmcnt in waitcnt: {line}")
                        has_vm = True
                        limit = int(vm_match[1])
                        if limit > 63:
                            raise ValueError("VM wait count exceeds the gfx10 six-bit field")
                        if limit == 0:
                            sample_dest.clear()
                        elif None not in sample_dest.values():
                            # Only the newest limit samples can remain outstanding. Filtering
                            # the current set also preserves guarantees made by earlier waits.
                            sample_dest = {reg: issue for reg, issue in sample_dest.items() if issue > vector_loads - limit}
                    elif lgkm_match := re.fullmatch(r"lgkmcnt\((\d+)\)", token):
                        if has_lgkm:
                            raise ValueError(f"Duplicate lgkmcnt in waitcnt: {line}")
                        has_lgkm = True
                        limit = int(lgkm_match[1])
                        if limit > 63:
                            raise ValueError("LGKM wait count exceeds the gfx10 six-bit field")
                        if limit == 0:
                            pending.clear()
                    elif exp_match := re.fullmatch(r"expcnt\((\d+)\)", token):
                        if has_exp:
                            raise ValueError(f"Duplicate expcnt in waitcnt: {line}")
                        has_exp = True
                        limit = int(exp_match[1])
                        if limit > 7:
                            raise ValueError("Export wait count exceeds the gfx10 three-bit field")
                    else:
                        raise ValueError(f"Unsupported s_waitcnt token: {token}")
                if not (has_vm or has_lgkm or has_exp):
                    raise ValueError(f"Empty or unsupported s_waitcnt: {line}")
        elif m := match(r"s_mov_b64 (s\[\d+:\d+\]), (?:exec|exec_lo)"):
            lo, hi = sgpr_pair(m.group(1))
            if lo in pending or hi in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            scalar[lo] = (mask, 0)
            scalar[hi] = (mask, 1)
        elif m := match(r"(s_mov_b64|s_mov_b32) (s\d+), (?:exec|exec_lo)"):
            op, reg = m.groups()
            if reg in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            if op == "s_mov_b64":
                n = int(reg[1:])
                if n % 2 != 0 or n + 1 > 105:
                    raise ValueError(f"Invalid 64-bit scalar register pair: {reg}")
                if f"s{n+1}" in pending:
                    raise ValueError("Write overlaps an outstanding scalar load")
                scalar[reg] = (mask, 0)
                scalar[f"s{n+1}"] = (mask, 1)
            else:
                if not guest_wave32:
                    raise ValueError("32-bit execution mask save requires a validated wave32 guest profile")
                scalar[sgpr_name(reg)] = (mask, "w32")
        elif (line in ("s_wqm_b64 exec, exec", "s_wqm_b64 exec_lo, exec_lo")
              and mask == "entry"):
            mask = "quad"
            wqm_width = 64
            scc = None
        elif (line in ("s_wqm_b32 exec_lo, exec_lo", "s_wqm_b32 exec, exec")
              and mask == "entry"):
            if not guest_wave32:
                raise ValueError("32-bit whole-quad mask requires a validated wave32 guest profile")
            mask = "quad"
            wqm_width = 32
            scc = None
        elif m := match(r"s_and_b64 (?:exec|exec_lo), (?:exec|exec_lo), (s\[\d+:\d+\])"):
            lo, hi = sgpr_pair(m.group(1))
            if mask != "quad" or wqm_width != 64 or [scalar.get(lo), scalar.get(hi)] != [("entry", 0), ("entry", 1)]:
                raise ValueError("Unsupported execution mask")
            mask = "entry"
            wqm_width = None
            scc = None
        elif m := match(r"s_and_b64 (?:exec|exec_lo), (?:exec|exec_lo), (s\d+)"):
            reg = m.group(1)
            n = int(reg[1:])
            if n % 2 != 0 or n + 1 > 105:
                raise ValueError(f"Invalid 64-bit scalar register pair: {reg}")
            if mask != "quad" or wqm_width != 64 or [scalar.get(reg), scalar.get(f"s{n+1}")] != [("entry", 0), ("entry", 1)]:
                raise ValueError("Unsupported execution mask")
            mask = "entry"
            wqm_width = None
            scc = None
        elif m := match(r"s_and_b32 (?:exec|exec_lo), (?:exec|exec_lo), (s\d+)"):
            if not guest_wave32:
                raise ValueError("32-bit execution mask restore requires a validated wave32 guest profile")
            reg = m.group(1)
            if mask != "quad" or wqm_width != 32 or scalar.get(reg) != ("entry", "w32"):
                raise ValueError("Unsupported execution mask")
            mask = "entry"
            wqm_width = None
            scc = None
        elif region is not None and (m := match(r"s_mov_b64 exec, (s\[\d+:\d+\])")):
            # Either opener may close with an exact copy of the saved pair (issue #1315 for s_and_saveexec_b64).
            # EXEC inside the region is a subset of the saved entry mask, so this restores the same mask as
            # s_or_b64 exec, exec, s[a:b]. Unlike s_or_b64 it leaves SCC; after s_and_saveexec_b64, which wrote
            # SCC from the new EXEC, SCC is already untracked, so no reader can follow either close.
            close_region(i, sgpr_pair(m[1]))
            region = None
        elif m := match(r"s_mov_b64 (?:exec|exec_lo), (s\[\d+:\d+\])"):
            lo, hi = sgpr_pair(m.group(1))
            if mask != "quad" or wqm_width != 64 or [scalar.get(lo), scalar.get(hi)] != [("entry", 0), ("entry", 1)]:
                raise ValueError("Unsupported execution mask")
            mask = "entry"
            wqm_width = None
            scc = None
        elif m := match(r"s_mov_b64 (?:exec|exec_lo), (s\d+)"):
            reg = m.group(1)
            n = int(reg[1:])
            if n % 2 != 0 or n + 1 > 105:
                raise ValueError(f"Invalid 64-bit scalar register pair: {reg}")
            if mask != "quad" or wqm_width != 64 or [scalar.get(reg), scalar.get(f"s{n+1}")] != [("entry", 0), ("entry", 1)]:
                raise ValueError("Unsupported execution mask")
            mask = "entry"
            wqm_width = None
            scc = None
        elif m := match(r"s_mov_b32 (?:exec|exec_lo), (s\d+)"):
            if not guest_wave32:
                raise ValueError("32-bit execution mask restore requires a validated wave32 guest profile")
            reg = m.group(1)
            if mask != "quad" or wqm_width != 32 or scalar.get(reg) != ("entry", "w32"):
                raise ValueError("Unsupported execution mask")
            mask = "entry"
            wqm_width = None
            scc = None
        elif m := match(r"s_and_saveexec_b64 (s\[\d+:\d+\]), (vcc|s\[\d+:\d+\])"):
            # A masked-if from a known full entry mask: the source must hold a tracked
            # comparison, whose lanes select which registers the region may rewrite.
            pair = sgpr_pair(m[1])
            regs = lane_mask(m[2])
            condition = scalar.get(regs[0])
            if (region is not None or mask != "entry" or pending.intersection(pair)
                    or not isinstance(condition, tuple) or condition[0] != "condition"
                    or [scalar.get(r) for r in regs]
                        != [(*condition[:2], j, len(regs)) for j in range(len(regs))]):
                raise ValueError("Unsupported execution mask save")
            scalar[pair[0]] = scalar[pair[1]] = ("exec_saved",)
            region = {"save": pair, "cond": condition[1], "written": {}, "skip": None, "start": i, "arm_start": i, "else": None, "then": {}, "else_written": {},
                      "else_undefined": set(), "skipped": False,
                      "scalar_written": set(), "scc_written": False, "opener": "saveexec",
                      "outstanding": (set(pending), dict(sample_dest))}
            vector.masked = True
            scalar.masked = True
            scc = None
        elif m := match(rf"v_cmpx_(?:({'|'.join(COMPARE)})_f32|({'|'.join(INT_COMPARE)})_(i32|u32|i64|u64)"
                        rf"|(eq|ne|lt|le|gt|ge)_(i16|u16)|(class)_f32"
                        rf"|({'|'.join(COMPARE)})_f16|(class)_f16"
                        rf"|({'|'.join(COMPARE)}|class)_f64)_(e32|e64) ([^,]+), ([^,]+)"):
            # A masked-if opened by a VOPC compare that writes EXEC (issue #932). It must directly
            # follow `s_mov_b64 s[a:b], exec` of the known entry mask, so EXEC becomes the entry mask
            # intersected with the comparison, as after s_and_saveexec_b64. v_cmpx writes neither VCC nor
            # SCC, so both keep their tracked values; the region closes with s_mov_b64 or s_or_b64.
            # The integer forms compare as the v_cmp of the same width (gfx10 has no f/t forms at 16 bits).
            # v_cmpx_class_f32 tests the class of the raw binary32 encoding in src0 against the mask in VSRC1,
            # as the e32 v_cmp_class_f32 does. The binary16 forms and v_cmpx_class_f16 read the low 16 bits
            # of each source through the lowering of the e32 v_cmp_f16 and v_cmp_class_f16. The binary64 forms
            # (and v_cmpx_class_f64) lower as the e32 v_cmp_*_f64 and need the same declared binary64 denormal
            # entry state. The VOP3 (e64) forms write only EXEC on gfx10, as e32 does: they take no SGPR
            # destination, and accept an SGPR or constant src1 and, on the float forms, neg and abs, as the
            # e64 v_cmp of the same type does.
            fop, iop, kind, op16, kind16, cls, hop, hcls, f64op, enc, src0, src1 = m.groups()
            if op16 is not None:
                iop, kind = op16, kind16
            previous = instructions[i - 1] if i else ""
            previous = previous[1] if isinstance(previous, tuple) else previous
            saved = re.fullmatch(r"s_mov_b64 (s\[\d+:\d+\]), exec", previous)
            pair = sgpr_pair(saved[1]) if saved else None
            if (region is not None or mask != "entry" or pair is None
                    or [scalar.get(r) for r in pair] != [("entry", 0), ("entry", 1)]):
                raise ValueError("Unsupported v_cmpx execution mask save")
            # VOPC e32 encodes VSRC1 as a VGPR (a VGPR pair at 64 bits) and carries no source modifiers.
            wide = kind in ("i64", "u64") or f64op not in (None, "class")
            vsrc1 = r"v\[\d+:\d+\]" if wide else r"v\d+"
            if enc == "e32" and (not re.fullmatch(vsrc1, src1) or re.search(r"\||abs\(|neg\(|^-[vs]", src0)):
                raise ValueError(f"Invalid VOPC e32 operands: {line}")
            if cls is not None and not re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}|[vs]\d+", src1):
                raise ValueError("Unsupported class mask")
            if fop is not None:
                expr = f32_comparison(fop, [src0, src1], scalar, vector, pending, sample_dest)
            elif hop is not None or hcls is not None:
                if hcls is not None:
                    expr = f16_class(src0, src1, scalar, vector, pending, sample_dest, allow_mods=enc == "e64")
                else:
                    expr = f16_comparison(hop, [src0, src1], scalar, vector, pending, sample_dest,
                                          allow_mods=enc == "e64")
            elif f64op is not None:
                if half_denorm != HALF_DENORM_PRESERVE:
                    raise ValueError("binary64 denormal mode unknown at entry")
                helpers.add("cmp_f64")
                declarations, expr = f64_comparison(i, f64op, [src0, src1], enc, scalar, vector, pending,
                                                    sample_dest)
                lines.extend(declarations)
            elif cls is not None:
                operand = fp_operand(src0, scalar, vector, pending, sample_dest)
                bits = (f"{int(src1, 0) & 0xffffffff}u" if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", src1)
                        else f"asuint({fp_operand(src1, scalar, vector, pending, sample_dest)})")
                expr = f"(class32({operand}) & {bits}) != 0u"
            elif kind in ("i64", "u64"):
                declarations, expr = int64_comparison(i, iop, kind, [src0, src1], enc,
                                                      scalar, vector, pending, sample_dest)
                lines.extend(declarations)
            else:
                read = int16_operand if kind in ("i16", "u16") else int_operand
                values = [read(t, scalar, vector, pending, sample_dest, signed=kind in ("i32", "i16"))
                          for t in (src0, src1)]
                expr = INT_COMPARE[iop].format(*values)
            lines.append(f"    bool cmp{i} = {expr};")
            scalar[pair[0]] = scalar[pair[1]] = ("exec_saved",)
            region = {"save": pair, "cond": f"cmp{i}", "written": {}, "skip": None, "start": i, "arm_start": i, "else": None, "then": {}, "else_written": {},
                      "else_undefined": set(), "skipped": False,
                      "scalar_written": set(), "scc_written": False, "opener": "cmpx",
                      "outstanding": (set(pending), dict(sample_dest))}
            vector.masked = True
            scalar.masked = True
        elif m := match(r"s_cbranch_scc([01]) (-?0x[0-9a-f]+|-?\d+)"):
            # A forward branch on a tracked scalar compare (issue #1413). SCC is a wave value, so the whole wave
            # skips the block or runs it. The block's vector writes merge with a select on the condition under
            # which it runs: SCC for s_cbranch_scc0, !SCC for s_cbranch_scc1. Offsets count from the next
            # instruction, and the target must be a later instruction boundary.
            if region is not None or mask != "entry" or offset is None:
                raise ValueError("Unsupported uniform branch")
            if not isinstance(scc, str) or not re.fullmatch(r"scc\d+", scc):
                raise ValueError("Uniform branch requires a tracked scalar compare")
            imm = int(m[2], 0)
            if not -0x8000 <= imm <= 0x7fff:
                raise ValueError("Uniform branch displacement out of range")
            end = offset_index.get(offset + 4 + imm * 4)
            if end is None or end <= i:
                raise ValueError("Uniform branch targets no later instruction boundary")
            # Stage 2: when the instruction just before the target is a forward s_branch, the branch selects
            # between block A (up to that s_branch, run when not taken) and block B (from the target to the
            # s_branch's JOIN, run when taken). JOIN must be a later boundary after B's first instruction.
            join = None
            last = instructions[end - 1]
            last_offset, last_line = last if isinstance(last, tuple) else (None, last)
            if end - 1 > i and (jm := re.fullmatch(r"s_branch (-?0x[0-9a-f]+|-?\d+)", last_line)):
                jimm = int(jm[1], 0)
                join = (offset_index.get(last_offset + 4 + jimm * 4)
                        if last_offset is not None and -0x8000 <= jimm <= 0x7fff else None)
                if join is None or join <= end:
                    raise ValueError("Uniform branch join targets no later instruction boundary")
            region = {"save": None, "cond": scc if m[1] == "0" else f"(!{scc})", "written": {}, "skip": None,
                      "start": i, "arm_start": i, "else": None, "then": {}, "else_written": {},
                      "else_undefined": set(), "skipped": False, "scalar_written": set(), "scc_written": False,
                      "opener": "scc", "end": end - 1 if join is not None else end, "join": join,
                      "outstanding": (set(pending), dict(sample_dest))}
            vector.masked = True
        elif m := match(r"s_cbranch_execz (-?0x[0-9a-f]+|-?\d+)"):
            # The whole-wave empty-mask skip may sit right after the save, or right after the else transition
            # (issue #1315); its target must be the matching restore exactly, or for the skip after the save of a
            # region with an else, that transition. Offsets count from the next instruction. Only the arms of one
            # region may carry skips.
            if (region is None or offset is None or i != region["arm_start"] + 1
                    or region["skip"] is not None or (seen_skip and not region["skipped"])):
                raise ValueError("Unsupported execution skip")
            imm = int(m[1], 0)
            if not -0x8000 <= imm <= 0x7fff:
                raise ValueError("Execution skip displacement out of range")
            restore = offset_index.get(offset + 4 + imm * 4)
            if restore is None or restore <= i:
                raise ValueError("Execution skip targets no instruction boundary")
            target = instructions[restore][1] if isinstance(instructions[restore], tuple) else instructions[restore]
            rm = re.fullmatch(r"s_or_b64 exec, exec, s\[(\d+):(\d+)\]", target)
            if rm is None:
                rm = re.fullmatch(r"s_mov_b64 exec, s\[(\d+):(\d+)\]", target)
            if rm is None and region["else"] is None:
                rm = re.fullmatch(r"s_andn2_b64 exec, s\[(\d+):(\d+)\], exec", target)
            if rm is None or [f"s{n}" for n in registers(*rm.groups(), 2)] != region["save"]:
                raise ValueError("Execution skip does not target the matching restore")
            region["skip"] = restore
            region["skipped"] = True
            seen_skip = True
        elif region is not None and (m := match(r"s_andn2_b64 exec, (s\[\d+:\d+\]), exec")):
            # The else transition (issue #1315): EXEC becomes saved & ~EXEC, the saved lanes whose condition is
            # false. The else arm starts from the pre-region vector state; a register first defined by the then
            # arm is undefined there. A then-arm skip must land exactly here. s_andn2_b64 writes SCC from the new
            # EXEC, which is untracked.
            if (sgpr_pair(m[1]) != region["save"] or region["else"] is not None
                    or (region["skip"] is not None and region["skip"] != i)):
                raise ValueError("Unexpected execution mask else transition")
            region["then"] = {dst: dict.get(vector, dst) for dst in region["written"]}
            for dst, outer in region["written"].items():
                if outer is MISSING:
                    region["else_undefined"].add(dst)
                else:
                    vector[dst] = outer
            if region["skip"] is not None:
                # A wave that skipped the then arm did not run its scalar writes or its waits before the else arm:
                # what was outstanding at the opener may still be outstanding here.
                scalar.conditional.update(region["scalar_written"])
                before_pending, before_samples = region["outstanding"]
                pending.update(before_pending)
                sample_dest.update(before_samples)
            region["skip"] = None
            region["else"] = region["arm_start"] = i
            scc = None
        elif m := match(r"s_or_b64 exec, exec, (s\[\d+:\d+\])"):
            close_region(i, sgpr_pair(m[1]))
            region = None
            # s_or_b64 writes SCC from the restored mask, a wave property the per-lane model cannot compute.
            scc = None
        elif m := match(r"s_(cmov|not|brev)_b64 (s\[\d+:\d+\]), ([^,]+)"):
            op, dst, src = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            s0, s1 = scalar_u64(src, scalar, pending)
            if op == "cmov":
                if scc is None:
                    raise ValueError("Conditional move requires a tracked SCC")
                d0, d1 = scalar_u64(dst, scalar, pending)
                expr = f"({scc} ? uint2({s0}, {s1}) : uint2({d0}, {d1}))"
            elif op == "not":
                expr = f"uint2(~{s0}, ~{s1})"
            else:
                expr = f"uint2(reversebits({s1}), reversebits({s0}))"
            lines.append(f"    uint2 salu{i} = {expr};")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
            scalar_mask.pop(regs[0], None)
            scalar_mask.pop(regs[1], None)
            if op == "not":
                scc = f"((salu{i}.x | salu{i}.y) != 0u)"
        elif m := match(r"s_cselect_b64 (s\[\d+:\d+\]), ([^,]+), ([^,]+)"):
            dst, src0, src1 = m.groups()
            if scc is None:
                raise ValueError("Select condition is not a tracked scalar result")
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            a0, a1 = scalar_u64(src0, scalar, pending)
            b0, b1 = scalar_u64(src1, scalar, pending)
            lines.append(f"    uint2 salu{i} = {scc} ? uint2({a0}, {a1}) : uint2({b0}, {b1});")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
        elif m := match(rf"s_({'|'.join(SALU_BIT64)})_b64 (s\[\d+:\d+\]), ([^,]+), ([^,]+)"):
            op, dst, src0, src1 = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            a0, a1 = scalar_u64(src0, scalar, pending)
            b0, b1 = scalar_u64(src1, scalar, pending)
            ma0, ma1 = scalar_mask_u64(src0, scalar, scalar_mask, pending)
            mb0, mb1 = scalar_mask_u64(src1, scalar, scalar_mask, pending)
            lines.append(f"    uint2 salu{i} = {SALU_BIT64[op].format(a0, a1, b0, b1)};")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
            if op == "and":
                scalar_mask[regs[0]], scalar_mask[regs[1]] = ma0 & mb0, ma1 & mb1
            elif op == "or":
                scalar_mask[regs[0]], scalar_mask[regs[1]] = ma0 | mb0, ma1 | mb1
            else:
                scalar_mask.pop(regs[0], None)
                scalar_mask.pop(regs[1], None)
            scc = f"((salu{i}.x | salu{i}.y) != 0u)"
        elif m := match(r"(s_lshl_b64|s_lshr_b64|s_ashr_i64|s_bfm_b64) (s\[\d+:\d+\]), ([^,]+), ([^,]+)"):
            op, dst, src0, src1 = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            shift = scalar_u32(src1, scalar, pending)
            ma0, ma1 = scalar_mask_u64(src0, scalar, scalar_mask, pending)
            cshift = scalar_const_u32(src1, scalar, pending)
            if op == "s_bfm_b64":
                width = scalar_u32(src0, scalar, pending)
                helpers.update(("s_lshl_b64", "s_bfm_b64"))
                expr = f"s_bfm_b64({width}, {shift})"
            else:
                a0, a1 = scalar_u64(src0, scalar, pending, signed=(op == "s_ashr_i64"))
                helpers.add(op)
                expr = f"{op}(uint2({a0}, {a1}), {shift})"
            lines.append(f"    uint2 salu{i} = {expr};")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
            if op == "s_lshl_b64" and cshift is not None:
                sh = cshift & 63
                full = ((ma0 | (ma1 << 32)) << sh) & 0xffffffffffffffff
                scalar_mask[regs[0]], scalar_mask[regs[1]] = full & 0xffffffff, full >> 32
            elif op == "s_lshr_b64" and cshift is not None:
                sh = cshift & 63
                full = (ma0 | (ma1 << 32)) >> sh
                scalar_mask[regs[0]], scalar_mask[regs[1]] = full & 0xffffffff, full >> 32
            else:
                scalar_mask.pop(regs[0], None)
                scalar_mask.pop(regs[1], None)
            if op != "s_bfm_b64":
                scc = f"((salu{i}.x | salu{i}.y) != 0u)"
        elif m := match(r"s_bfe_([ui])64 (s\[\d+:\d+\]), ([^,]+), ([^,]+)"):
            kind, dst, src, ctrl = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            is_signed = kind == "i"
            lo, hi = scalar_u64(src, scalar, pending, signed=is_signed)
            field = scalar_u32(ctrl, scalar, pending)
            helpers.update(("s_lshl_b64", "s_lshr_b64", "s_ashr_i64", "s_bfe64"))
            lines.append(f"    uint2 salu{i} = s_bfe64(uint2({lo}, {hi}), {field}, {str(is_signed).lower()});")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
            scc = f"((salu{i}.x | salu{i}.y) != 0u)"
        elif m := match(r"(s_bfe_u32|s_bfe_i32) (s\d+), ([^,]+), ([^,]+)"):
            op, dst, src0, src1 = m.groups()
            sgpr_name(dst)
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            a = scalar_u32(src0, scalar, pending)
            b = scalar_u32(src1, scalar, pending)
            cctrl = scalar_const_u32(src1, scalar, pending)
            helpers.add(op)
            lines.append(f"    uint salu{i} = {op}({a}, {b});")
            scalar[dst] = ("uint", f"salu{i}")
            if op == "s_bfe_u32" and cctrl is not None:
                w = (cctrl >> 16) & 127
                scalar_mask[dst] = (1 << min(w, 32)) - 1
            else:
                scalar_mask.pop(dst, None)
            scc = f"(salu{i} != 0u)"
        elif m := match(r"(s_cmp_eq_u64|s_cmp_lg_u64) ([^,]+), ([^,]+)"):
            op, src0, src1 = m.groups()
            a0, a1 = scalar_u64(src0, scalar, pending)
            b0, b1 = scalar_u64(src1, scalar, pending)
            cond = f"({a0} == {b0} && {a1} == {b1})" if op == "s_cmp_eq_u64" else f"({a0} != {b0} || {a1} != {b1})"
            lines.append(f"    bool scc{i} = {cond};")
            scc = f"scc{i}"
        elif m := match(r"(s_bitcmp0_b64|s_bitcmp1_b64) ([^,]+), ([^,]+)"):
            op, src0, src1 = m.groups()
            a0, a1 = scalar_u64(src0, scalar, pending)
            b = scalar_u32(src1, scalar, pending)
            bit_test = f"((({b} & 32u) != 0u ? ({a1} & (1u << ({b} & 31u))) : ({a0} & (1u << ({b} & 31u)))) {'==' if op == 's_bitcmp0_b64' else '!='} 0u)"
            lines.append(f"    bool scc{i} = {bit_test};")
            scc = f"scc{i}"
        elif m := match(r"(s_bitcmp0_b32|s_bitcmp1_b32) ([^,]+), ([^,]+)"):
            op, src0, src1 = m.groups()
            a = scalar_u32(src0, scalar, pending)
            b = scalar_u32(src1, scalar, pending)
            bit_test = f"(({a} & (1u << ({b} & 31u))) {'==' if op == 's_bitcmp0_b32' else '!='} 0u)"
            lines.append(f"    bool scc{i} = {bit_test};")
            scc = f"scc{i}"
        elif m := match(r"(s_cmp_(?:eq|lg|gt|ge|lt|le)_(?:i32|u32)) ([^,]+), ([^,]+)"):
            op, src0, src1 = m.groups()
            signed = op.endswith("_i32")
            comp = op.split("_")[2]
            op_sym = {"eq": "==", "lg": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}[comp]
            a = scalar_u32(src0, scalar, pending)
            b = scalar_u32(src1, scalar, pending)
            cond = f"(asint({a}) {op_sym} asint({b}))" if signed else f"({a} {op_sym} {b})"
            lines.append(f"    bool scc{i} = {cond};")
            scc = f"scc{i}"
        elif m := match(r"(s_movrels_b32|s_movrels_b64|s_movreld_b32|s_movreld_b64|s_movrelsd_2_b32) "
                         r"(s\d+|s\[\d+:\d+\]), (s\d+|s\[\d+:\d+\])"):
            # Scalar relative moves (#1882): s_movrels reads SGPR[src + m0], s_movreld writes SGPR[dst + m0], and
            # s_movrelsd_2_b32 reads SGPR[src + m0[9:0]] and writes SGPR[dst + m0[25:16]]; _b64 moves a pair.
            op, dst, src = m.groups()
            width = 2 if op.endswith("_b64") else 1
            dbase = int((sgpr_pair(dst)[0] if width == 2 else sgpr_name(dst))[1:])
            sbase = int((sgpr_pair(src)[0] if width == 2 else sgpr_name(src))[1:])
            m0 = scalar.get("m0")
            if isinstance(m0, int):
                m0_u = m0 & 0xffffffff
                soffs, doffs = {"s_movrels_b32": ([m0_u], [0]), "s_movrels_b64": ([m0_u], [0]),
                                "s_movreld_b32": ([0], [m0_u]), "s_movreld_b64": ([0], [m0_u]),
                                "s_movrelsd_2_b32": ([m0_u & 0x3ff], [(m0_u >> 16) & 0x3ff])}[op]
                soff_expr = doff_expr = None
            elif isinstance(m0, tuple) and len(m0) == 2 and m0[0] == "uint":
                if "m0" not in scalar_mask:
                    raise ValueError(f"Dynamic m0 offset is unbounded for {op}")
                mask_u = scalar_mask["m0"] & 0xffffffff
                whole = f"{m0[1]}"
                if op.startswith("s_movrels_"):
                    soffs, doffs, soff_expr, doff_expr = masked_offsets(mask_u), [0], whole, None
                elif op.startswith("s_movreld_"):
                    soffs, doffs, soff_expr, doff_expr = [0], masked_offsets(mask_u), None, whole
                else:
                    soffs, doffs = masked_offsets(mask_u & 0x3ff), masked_offsets((mask_u >> 16) & 0x3ff)
                    soff_expr, doff_expr = f"({whole} & 0x3ffu)", f"(({whole} >> 16) & 0x3ffu)"
            else:
                raise ValueError(f"Unsupported m0 value for {op}")
            if any(sbase + k + width - 1 > 105 for k in soffs) or any(dbase + k + width - 1 > 105 for k in doffs):
                raise ValueError(f"Indexed SGPR exceeds s105 for {op}")
            if width == 2 and any((sbase + k) % 2 or (dbase + k) % 2 for k in (*soffs, *doffs)):
                raise ValueError(f"Odd 64-bit SGPR pair base for {op}")
            reach_src = [f"s{sbase + k + h}" for k in soffs for h in range(width)]
            reach_dst = [f"s{dbase + k + h}" for k in doffs for h in range(width)]
            if any(r in pending for r in (*reach_src, *reach_dst)):
                raise ValueError("Unresolved scalar memory dependency")
            if soff_expr is None and doff_expr is None:
                # A static index: the move is an s_mov from or to the indexed SGPR, tracked value and mask included.
                moved = [(scalar[f"s{sbase + soffs[0] + h}"], scalar_mask.get(f"s{sbase + soffs[0] + h}"))
                         for h in range(width)]
                for h, (val, src_mask) in enumerate(moved):
                    reg = f"s{dbase + doffs[0] + h}"
                    scalar[reg] = val
                    if isinstance(val, int):
                        scalar_mask[reg] = val & 0xffffffff
                    elif src_mask is not None:
                        scalar_mask[reg] = src_mask
            else:
                # A dynamic index selects among plain numeric SGPRs only, so no resource depends on a runtime index.
                words = []
                if soff_expr is not None:
                    lines.append(f"    uint smov_soff{i} = {soff_expr};")
                for h in range(width):
                    if soff_expr is None:
                        reg = f"s{sbase + soffs[0] + h}"
                        words.append((scalar_u32(reg, scalar, pending), scalar_mask.get(reg, 0xffffffff)))
                        continue
                    choices = [(k, f"s{sbase + k + h}") for k in soffs]
                    value = scalar_u32(choices[-1][1], scalar, pending)
                    mask_or = scalar_mask.get(choices[-1][1], 0xffffffff)
                    for k, reg in reversed(choices[:-1]):
                        value = f"(smov_soff{i} == {k}u ? {scalar_u32(reg, scalar, pending)} : {value})"
                        mask_or |= scalar_mask.get(reg, 0xffffffff)
                    lines.append(f"    uint salu{i}_s{h} = {value};")
                    words.append((f"salu{i}_s{h}", mask_or))
                if doff_expr is None:
                    for h, (word, mask_w) in enumerate(words):
                        reg = f"s{dbase + doffs[0] + h}"
                        scalar[reg] = ("uint", word)
                        scalar_mask[reg] = mask_w
                else:
                    lines.append(f"    uint smov_doff{i} = {doff_expr};")
                    old = {reg: (scalar_u32(reg, scalar, pending), scalar_mask.get(reg, 0xffffffff))
                           for reg in dict.fromkeys(reach_dst)}
                    for k in doffs:
                        for h, (word, mask_w) in enumerate(words):
                            reg = f"s{dbase + k + h}"
                            prev, prev_mask = old[reg]
                            name = f"salu{i}_d{dbase + k + h}"
                            lines.append(f"    uint {name} = (smov_doff{i} == {k}u ? {word} : {prev});")
                            old[reg] = (name, prev_mask | mask_w)
                    for reg, (name, mask_w) in old.items():
                        scalar[reg] = ("uint", name)
                        scalar_mask[reg] = mask_w
        elif m := match(r"(s_mov_b32|s_movk_i32) (s\d+|m0), (s\d+|0x[0-9a-f]+|\d+)"):
            op, dst, src = m.groups()
            if src in pending or dst in pending:
                raise ValueError("Unresolved scalar memory dependency")
            val = scalar[src] if src.startswith("s") else int(src, 0)
            if op == "s_movk_i32":
                if not isinstance(val, int) or not 0 <= val <= 0xffff:
                    raise ValueError("Invalid movk immediate")
                val = (val if val < 0x8000 else val - 0x10000) & 0xffffffff
            src_mask = scalar_mask.get(src) if src.startswith("s") else None
            scalar[dst] = val
            if isinstance(val, int):
                scalar_mask[dst] = val & 0xffffffff
            elif src_mask is not None:
                scalar_mask[dst] = src_mask
        elif m := match(r"s_flbit_i32_([bi])64 (s\d+), ([^,]+)"):
            kind, dst, src = m.groups()
            sgpr_name(dst)
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            lo, hi = scalar_u64(src, scalar, pending)
            if kind == "i":
                # Normalize both halves using bit 63, including when the high word becomes zero.
                lines.append(f"    uint signmask{i} = 0u - ({hi} >> 31);")
                lo, hi = f"({lo} ^ signmask{i})", f"({hi} ^ signmask{i})"
            lines.append(f"    uint salu{i} = {hi} != 0u ? 31u - firstbithigh({hi}) : "
                         f"({lo} != 0u ? 63u - firstbithigh({lo}) : 0xffffffffu);")
            scalar[dst] = ("uint", f"salu{i}")
        elif m := match(r"s_ff([01])_i32_b64 (s\d+), ([^,]+)"):
            bit, dst, src = m.groups()
            sgpr_name(dst)
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            lo, hi = scalar_u64(src, scalar, pending)
            if bit == "0":
                lo, hi = f"(~{lo})", f"(~{hi})"
            lines.append(f"    uint salu{i} = {lo} != 0u ? firstbitlow({lo}) : "
                         f"({hi} != 0u ? 32u + firstbitlow({hi}) : 0xffffffffu);")
            scalar[dst] = ("uint", f"salu{i}")
        elif m := match(r"s_bcnt([01])_i32_b64 (s\d+), ([^,]+)"):
            bit, dst, src = m.groups()
            sgpr_name(dst)
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            lo, hi = scalar_u64(src, scalar, pending)
            ones = f"(countbits({lo}) + countbits({hi}))"
            value = f"64u - {ones}" if bit == "0" else ones
            lines.append(f"    uint salu{i} = {value};")
            scalar[dst] = ("uint", f"salu{i}")
            scc = NONZERO.format(r=f"salu{i}")
        elif m := match(r"(s_addc_u32|s_subb_u32) (s\d+), ([^,]+), ([^,]+)"):
            op, dst, src0, src1 = m.groups()
            sgpr_name(dst)
            if scc is None:
                raise ValueError("Carry or borrow input is not tracked")
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            a, b = (scalar_u32(t, scalar, pending) for t in (src0, src1))
            result = f"salu{i}"
            partial = f"partial{i}"
            step = f"carry_in{i}"
            lines.append(f"    uint {step} = {scc} ? 1u : 0u;")
            # Keep both steps in uint32 so the two possible wrap points remain visible.
            if op == "s_addc_u32":
                lines.append(f"    uint {partial} = {a} + {b};")
                lines.append(f"    uint {result} = {partial} + {step};")
                scc = f"({partial} < {a} || {result} < {partial})"
            else:
                lines.append(f"    uint {partial} = {a} - {b};")
                lines.append(f"    uint {result} = {partial} - {step};")
                scc = f"({a} < {b} || {partial} < {step})"
            scalar[dst] = ("uint", result)
        elif m := match(rf"s_({'|'.join(SCALAR)}) (s\d+), (.+)"):
            # Uniform values become HLSL uint locals; an exec mask does not affect them.
            op, dst, operands = m.groups()
            sgpr_name(dst)
            arity, template, carry = SCALAR[op]
            tokens = operands.split(", ")
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            if len(tokens) != arity:
                raise ValueError("Invalid scalar operation")
            if op in ("mul_hi_u32", "mul_hi_i32"):
                helpers.add("scalar_mul_hi")
            elif op == "flbit_i32_b32":
                helpers.add("dpp_ffbh_u32")
            elif op == "flbit_i32":
                helpers.add("dpp_ffbh_i32")
            values = [scalar_u32(t, scalar, pending) for t in tokens]
            lines.append(f"    uint salu{i} = {template.format(*values)};")
            if carry:
                scc = f"({carry.format(*values, r=f'salu{i}')})"
            scalar[dst] = ("uint", f"salu{i}")
        elif m := match(r"s_cselect_b32 (s\d+), ([^,]+), ([^,]+)"):
            dst, *tokens = m.groups()
            if scc is None:
                raise ValueError("Select condition is not a tracked scalar result")
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            values = [scalar_u32(t, scalar, pending) for t in tokens]
            lines.append(f"    uint salu{i} = {scc} ? {values[0]} : {values[1]};")
            scalar[dst] = ("uint", f"salu{i}")
        elif m := match(r"(s_cmpk_(?:eq|lg|gt|ge|lt|le)_(?:i32|u32)) (s\d+), (-?\d+|0x[0-9a-f]+)"):
            op, dst, imm = m.groups()
            operand = scalar_u32(dst, scalar, pending)
            signed = op.endswith("_i32")
            op_sym = {"eq": "==", "lg": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}[op.split("_")[2]]
            val = sopk_imm16(imm, signed=signed)
            cond = f"(asint({operand}) {op_sym} asint({val}u))" if signed else f"({operand} {op_sym} {val}u)"
            lines.append(f"    bool scc{i} = {cond};")
            scc = f"scc{i}"
        elif m := match(r"s_cmovk_i32 (s\d+), (-?\d+|0x[0-9a-f]+)"):
            dst, imm = m.groups()
            if scc is None:
                raise ValueError("Select condition is not a tracked scalar result")
            prev = scalar_u32(dst, scalar, pending)
            val = sopk_imm16(imm, signed=True)
            scalar[dst] = ("uint", f"salu{i}")
            lines.append(f"    uint salu{i} = {scc} ? {val}u : {prev};")
        elif m := match(r"s_cmov_b32 (s\d+), ([^,]+)"):
            dst, src = m.groups()
            if scc is None:
                raise ValueError("Select condition is not a tracked scalar result")
            prev = scalar_u32(dst, scalar, pending)
            val = scalar_u32(src, scalar, pending)
            lines.append(f"    uint salu{i} = {scc} ? {val} : {prev};")
            scalar[dst] = ("uint", f"salu{i}")
        elif m := match(r"(s_bitset[01]_b32) (s\d+), ([^,]+)"):
            op, dst, src = m.groups()
            prev = scalar_u32(dst, scalar, pending)
            bit = scalar_u32(src, scalar, pending)
            expr = f"({prev} & ~(1u << ({bit} & 31u)))" if op == "s_bitset0_b32" else f"({prev} | (1u << ({bit} & 31u)))"
            lines.append(f"    uint salu{i} = {expr};")
            scalar[dst] = ("uint", f"salu{i}")
        elif m := match(r"(s_quadmask_b32) (s\d+), ([^,]+)"):
            op, dst, src = m.groups()
            sgpr_name(dst)
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            value = scalar_u32(src, scalar, pending)
            helpers.add(op)
            lines.append(f"    uint salu{i} = {op}({value});")
            scalar[dst] = ("uint", f"salu{i}")
            scc = f"(salu{i} != 0u)"
        elif m := match(r"(s_bitset[01]_b64) (s\[\d+:\d+\]), ([^,]+)"):
            op, dst, src = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            initial_lo, initial_hi = scalar_u64(dst, scalar, pending)
            bit = scalar_u32(src, scalar, pending)
            make_mask = f"(1u << (salu{i}_bit & 31u))"
            if op == "s_bitset0_b64":
                clear = f"~{make_mask}"
                low = f"({initial_lo} & ((salu{i}_bit & 32u) ? 0xffffffffu : {clear}))"
                high = f"({initial_hi} & ((salu{i}_bit & 32u) ? {clear} : 0xffffffffu))"
            else:
                low = f"({initial_lo} | ((salu{i}_bit & 32u) ? 0u : {make_mask}))"
                high = f"({initial_hi} | ((salu{i}_bit & 32u) ? {make_mask} : 0u))"
            lines.append(f"    uint salu{i}_bit = {bit} & 63u;")
            lines.append(f"    uint2 salu{i} = uint2({low}, {high});")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
        elif m := match(r"(s_quadmask_b64) (s\[\d+:\d+\]), ([^,]+)"):
            op, dst, src = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            low, high = scalar_u64(src, scalar, pending)
            helpers.update(("s_quadmask_b32", op))
            lines.append(f"    uint2 salu{i} = {op}(uint2({low}, {high}));")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
            scc = f"((salu{i}.x | salu{i}.y) != 0u)"
        elif m := match(r"(s_bitreplicate_b64_b32) (s\[\d+:\d+\]), ([^,]+)"):
            op, dst, src = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            value = scalar_u32(src, scalar, pending)
            helpers.add(op)
            lines.append(f"    uint2 salu{i} = {op}({value});")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
        elif m := match(r"(s_addk_i32|s_mulk_i32) (s\d+), (-?\d+|0x[0-9a-f]+)"):
            op, dst, imm = m.groups()
            operand = scalar_u32(dst, scalar, pending)
            addend = sopk_imm16(imm, signed=True)
            operation = "+" if op == "s_addk_i32" else "*"
            scalar[dst] = ("uint", f"alu{i}")
            lines.append(f"    uint alu{i} = ({operand} {operation} {addend}u);")

            if op == "s_addk_i32":
                scc = f"((({operand} ^ alu{i}) & ({addend}u ^ alu{i}) & 0x80000000u) != 0u)"
        elif m := match(r"(?:s_load_dwordx2 s\[(\d+):(\d+)\]|s_load_dword s(\d+)), s\[(\d+):(\d+)\], (0x[0-9a-f]+|null)"):
            # A nested table pointer: only a contract slot read from a resolved table, with the full width.
            first, last, single, low, high, imm = m.groups()
            width = 1 if single is not None else 2
            if single is not None:
                first = last = single
            if int(last) > 105 or int(first) % width or int(low) % 2 or int(high) > 105:
                raise ValueError("Invalid scalar load registers")
            dst = [f"s{n}" for n in registers(first, last, width)]
            base = [f"s{n}" for n in registers(low, high, 2)]
            offset = 0 if imm == "null" else int(imm, 16)
            table = scalar.get(base[0])
            if (pending.intersection(base) or scalar.get(base[1]) != 0
                    or not (table == "texture_ptr" or isinstance(table, tuple) and table[0] == "constant_table")):
                raise ValueError("Unresolved table pointer address")
            if pointers.get((table, offset)) != width:
                raise ValueError("Table pointer differs from binding contract")
            if pending.intersection(dst):
                raise ValueError("Write overlaps an outstanding scalar load")
            scalar[dst[0]] = ("pointer_table", table, offset)
            if width == 2:
                scalar[dst[1]] = ("pointer_high", table, offset)
            pending.update(dst)
        elif m := match(r"s_load_dwordx8 s\[(\d+):(\d+)\], s\[(\d+):(\d+)\], (null|0x[0-9a-f]+)"):
            dst = registers(*m.groups()[:2], 8)
            addr = registers(*m.groups()[2:4], 2)
            offset = 0 if m[5] == "null" else int(m[5], 16)
            if offset not in bindings:
                raise ValueError("Unbound texture descriptor offset")
            if any(f"s{n}" in pending for n in (*addr, *dst)) or [scalar.get(f"s{n}") for n in addr] != ["texture_ptr", 0]:
                raise ValueError("Texture address differs from binding contract")
            for j, n in enumerate(dst):
                scalar[f"s{n}"] = (bindings[offset], j)
                scalar_mask.pop(f"s{n}", None)
                pending.add(f"s{n}")
        elif m := match(r"(?:(s_load_dwordx4|s_buffer_load_dwordx[24]) s\[(\d+):(\d+)\]|s_buffer_load_dword s(\d+))"
                        r", s\[(\d+):(\d+)\], (0x[0-9a-f]+|null)"):
            op, first, last, single, low, high, imm = m.groups()
            offset = 0 if imm == "null" else int(imm, 16)
            descriptor = op == "s_load_dwordx4"
            width = 1 if single is not None else 2 if op == "s_buffer_load_dwordx2" else 4
            if single is not None:
                first = last = single
            # LLVM names a 64-bit scalar destination only as an even-aligned pair.
            if width < 4 and (int(last) > 105 or int(first) % width or int(low) % 4 or int(high) > 105):
                raise ValueError("Invalid scalar buffer registers")
            dst = registers(first, last, width)
            base = [f"s{n}" for n in registers(low, high, 2 if descriptor else 4)]
            source = [scalar.get(r) for r in base]
            table = source[0]
            if descriptor:
                resolved = (source[1] == 0
                            and (table == "texture_ptr" or isinstance(table, tuple) and table[0] == "constant_table"))
                if isinstance(table, tuple) and table[0] == "pointer_table":
                    # A 32-bit pointer needs an explicit zero high word; a 64-bit one its own loaded high word.
                    high = 0 if pointers[table[1], table[2]] == 1 else ("pointer_high", table[1], table[2])
                    resolved = source[1] == high
            else:
                resolved = (isinstance(table, tuple) and table[0] == "cbv"
                            and source == [("cbv", table[1], n) for n in range(4)])
            if not constants or pending.intersection(base) or not resolved:
                raise ValueError("Unresolved constant buffer binding")
            if descriptor and (table, offset) not in constants:
                raise ValueError("Constant descriptor differs from binding contract")
            params = constants[table, offset] if descriptor else table[1]
            if not descriptor and (offset % 4 or offset + 4 * len(dst) > 256):
                raise ValueError("Constant read exceeds binding or is unaligned")
            for j, n in enumerate(dst):
                if f"s{n}" in pending:
                    raise ValueError("Write overlaps an outstanding scalar load")
                word = offset // 4 + j
                if descriptor:
                    scalar[f"s{n}"] = ("cbv", params, j)
                else:
                    value = f"{params}[{word // 4}].{'xyzw'[word % 4]}"
                    scalar[f"s{n}"] = ("uint", value) if params in integer_params else value
                pending.add(f"s{n}")
        elif m := match(r"scratch_(load|store)_dword(x[234])?\s+(.*)"):
            if title_ranges is not None:
                raise ValueError(f"Unsupported instruction {i}: {line}")
            kind, width_str, rest = m.groups()
            if mask != "entry":
                raise ValueError("Invalid scratch operation in non-entry mask")
            count = int(width_str[1:]) if width_str else 1
            parts = [p.strip() for p in rest.split(",")]
            if len(parts) != 3:
                raise ValueError("Scratch instruction requires exactly 3 operands")
            last_words = parts[2].split()
            if not last_words:
                raise ValueError("Missing third operand")
            op0, op1 = parts[0], parts[1]
            op2 = last_words[0]
            mods = last_words[1:]

            offset = 0
            seen_offset = False
            seen_mods = set()
            for mod in mods:
                if mod.startswith("offset:"):
                    if seen_offset:
                        raise ValueError("Duplicate offset modifier")
                    seen_offset = True
                    off_val = int(mod.split(":", 1)[1])
                    if not -2048 <= off_val <= 2047:
                        raise ValueError(f"Scratch offset out of range (-2048..2047): {off_val}")
                    offset = off_val
                elif mod in ("glc", "slc", "dlc"):
                    if mod in seen_mods:
                        raise ValueError(f"Duplicate modifier {mod}")
                    seen_mods.add(mod)
                elif mod == "lds":
                    raise ValueError("LDS modifier is not supported in pixel shaders")
                else:
                    raise ValueError(f"Unsupported scratch modifier: {mod}")

            if offset % 4 != 0:
                raise ValueError("Scratch dword offset must be 4-byte aligned")

            if kind == "load":
                vdst_str = op0
                vaddr_str = op1
                saddr_str = op2
                regs = vgpr_span(vdst_str, count)
                if any(reg in sample_dest for reg in regs):
                    raise ValueError("Write overlaps an outstanding sample")
            else:
                vaddr_str = op0
                vdata_str = op1
                saddr_str = op2
                regs = vgpr_span(vdata_str, count)
                values = [int_operand(reg, scalar, vector, pending, sample_dest, signed=False) for reg in regs]

            if vaddr_str != "off":
                raise ValueError(f"Dynamic or unproven scratch address: vaddr must be off, got {vaddr_str}")
            if saddr_str != "off":
                m_s = re.fullmatch(r"s(\d+)", saddr_str)
                if not m_s or not 0 <= int(m_s[1]) <= 105:
                    raise ValueError(f"Invalid saddr register: {saddr_str}")
                if saddr_str not in scalar:
                    raise ValueError(f"Uninitialized or pending scalar register {saddr_str}")
                base = scalar[saddr_str]
                if not isinstance(base, int):
                    raise ValueError(f"Dynamic or unproven scratch address: saddr {saddr_str} is not a proven integer constant")
                addr_byte = base + offset
            else:
                addr_byte = offset

            if addr_byte < 0:
                raise ValueError("Negative scratch address")
            if addr_byte % 4 != 0:
                raise ValueError("Scratch dword offset must be 4-byte aligned")
            if addr_byte + 4 * count > 1024:
                raise ValueError(f"Scratch access exceeds frame: {addr_byte + 4 * count}")
            addr_idx = addr_byte // 4

            if not has_scratch:
                lines.append("    uint scratch[256] = (uint[256])0;")
                has_scratch = True

            if kind == "load":
                for comp, reg in enumerate(regs):
                    dword_idx = addr_idx + comp
                    if dword_idx not in scratch_written:
                        raise ValueError(f"Scratch load from unwritten address: {addr_byte + 4 * comp}")
                    if reg in sample_dest:
                        raise ValueError("Write overlaps an outstanding sample")
                    # A scratch result requires a full VM drain. Keep mixed loads
                    # pending on partial waits because their relative order is unproven.
                    sample_dest[reg] = None
                    offset_term = f" + {comp}u" if comp else ""
                    tag = f"alu{i}_{comp}" if count > 1 else f"alu{i}"
                    vector[reg] = tag
                    lines.append(f"    precise float {tag} = asfloat(scratch[{addr_idx}u{offset_term}]);")
            else:
                for comp, val in enumerate(values):
                    dword_idx = addr_idx + comp
                    scratch_written.add(dword_idx)
                    offset_term = f" + {comp}u" if comp else ""
                    lines.append(f"    scratch[{addr_idx}u{offset_term}] = {val};")
        elif m := match(r"v_cube(id|sc|tc|ma)_f32(?:_e64)? (v\d+), ([^,]+), ([^,]+), ([^,]+?)( clamp)?"):
            # LLVM ConstantFoldAMDGCNCubeIntrinsic: z, then y, then x is the major axis; a face is negative
            # only for a nonzero, non-NaN negative coordinate.
            op, dst, *tokens, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid cube operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            x, y, z = [fp_operand(t, scalar, vector, pending, sample_dest) for t in tokens]
            lines.append(f"    precise float3 cube{i} = float3({x}, {y}, {z});")
            c, a = f"cube{i}", f"abs(cube{i})"
            zmajor = f"({a}.z >= {a}.x && {a}.z >= {a}.y)"
            ymajor = f"({a}.y >= {a}.x)"
            expression = {
                "id": f"({zmajor} ? ({c}.z < 0.0f ? 5.0f : 4.0f) : {ymajor} ? ({c}.y < 0.0f ? 3.0f : 2.0f) : ({c}.x < 0.0f ? 1.0f : 0.0f))",
                "sc": f"({zmajor} ? ({c}.z < 0.0f ? -{c}.x : {c}.x) : {ymajor} ? {c}.x : ({c}.x < 0.0f ? {c}.z : -{c}.z))",
                "tc": f"({zmajor} ? -{c}.y : {ymajor} ? ({c}.y < 0.0f ? -{c}.z : {c}.z) : -{c}.y)",
                "ma": f"(({zmajor} ? {c}.z : {ymajor} ? {c}.y : {c}.x) * 2.0f)",
            }[op]
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        # The VOP3 (e64) spelling is accepted only in the operand shape of the e32 form. Its source modifiers,
        # clamp and output modifiers do not match here and stay unrecognised.
        elif m := match(r"v_interp_p([12])_f32_e(?:32|64) (v\d+), (v\d+), attr0\.([xyzw])"):
            phase, dst, src, component = m.groups()
            entry_interp = mask == "entry" and sampler is None
            if ((not entry_interp and (mask not in ("entry", "quad") or component not in "xy"))
                    or scalar.get("m0") != "interp_base"):
                raise ValueError("Unknown interpolation context")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if phase == "1" and vector.get(src) == "bary_i":
                vector[dst] = ("partial", component, mask)
            elif phase == "2" and vector.get(src) == "bary_j" and vector.get(dst) == ("partial", component, mask):
                interpolated = True
                if entry_interp:
                    attribute_input = True
                    vector[dst] = f"alu{i}"
                    lines.append(f"    float alu{i} = uv.{component};")
                else:
                    vector[dst] = f"uv.{component}" if mask == "quad" else ("entry_uv", component)
            else:
                raise ValueError("Unpaired interpolation")
        elif m := match(r"(image_sample(?:(?:_lz|_l|_b)?(?:_o)?|_c?d(?:_o)?(?:_g16)?)) (?:v\[(\d+):(\d+)\]|v(\d+)), "
                        r"v\[(\d+):(\d+)\], s\[(\d+):(\d+)\], s\[(\d+):(\d+)\] dmask:0x([1-9a-f]) dim:SQ_RSRC_IMG_2D"):
            op, dst_first, dst_last, dst_single, *rest, dmask_hex = m.groups()
            dmask = int(dmask_hex, 16)
            if op != "image_sample" and dmask != 0xf:
                raise ValueError(f"{op} requires dmask:0xf")
            g16 = op.endswith("_g16")
            sample_op = op.removesuffix("_g16")
            base_op = sample_op.removesuffix("_o")
            has_offset = sample_op != base_op
            coarse = base_op == "image_sample_cd"
            gradient = coarse or base_op == "image_sample_d"
            if coarse and cpu != "gfx1030":
                raise ValueError("Coarse-gradient sampling requires gfx1030")
            if gradient:
                # LLVM disassembly lists only the live address operands.
                coord_width = (4 if g16 else 6) + has_offset
            else:
                coord_width = (3 if base_op in ("image_sample_l", "image_sample_b") else 2) + has_offset
            channels = ["xyzw"[bit] for bit in range(4) if (dmask >> bit) & 1]
            if len(channels) == 1:
                if dst_single is None:
                    raise ValueError("Single-channel image_sample requires a single VGPR destination")
                dest = range(int(dst_single), int(dst_single) + 1)
            else:
                if dst_single is not None:
                    raise ValueError("Multi-channel image_sample requires a VGPR range destination")
                dest = registers(dst_first, dst_last, len(channels))
            coords, image, state = [registers(*rest[k:k+2], width)
                                    for k, width in zip((0, 2, 4), (coord_width, 8, 4))]
            if dest.stop > 256:
                raise ValueError("Texture sample destination VGPR out of range")
            if coords.stop > 256:
                raise ValueError("Texture sample coordinate VGPR out of range")
            if any(f"v{n}" in sample_dest for n in dest):
                raise ValueError("Write overlaps an outstanding sample")
            descriptor = [scalar.get(f"s{n}") for n in image]
            texture = next((name for name in bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
            if (mask != "entry" or any(f"s{n}" in pending for n in (*image, *state))
                    or texture is None
                    or [scalar.get(f"s{n}") for n in state] != list(sampler)):
                raise ValueError("Unsupported image or sampler binding")
            if sample_kind == "comparison":
                raise ValueError("Comparison and ordinary sampling in one program")
            sample_kind = "plain"
            if op != "image_sample" and second_texture_offset is not None:
                raise ValueError(f"{op} requires a single texture binding")
            coord_regs = [f"v{n}" for n in coords]
            offset_arg = ""
            if has_offset:
                offset_arg = sample_offset_arg(coord_regs.pop(0), vector, sample_dest, known_ssa_bits)
            if any(reg not in vector for reg in coord_regs):
                raise ValueError("Unsupported texture coordinate")

            def sample_coord(reg):
                value = vector[reg]
                if isinstance(value, tuple) and value[0] == "entry_uv":
                    return f"uv.{value[1]}"
                if value in ("uv.x", "uv.y"):
                    return value
                return fp_operand(reg, scalar, vector, pending, sample_dest)

            if gradient:
                u, v = [sample_coord(reg) for reg in coord_regs[-2:]]
                if coarse:
                    # Uniform slopes give the same inputs if the texture unit shares
                    # gradient operands between invocations. Refuse lane-varying slopes.
                    words = [known_ssa_bits.get(vector[reg]) for reg in coord_regs[:-2]]
                    if any(word is None for word in words):
                        raise ValueError("Coarse gradients require statically known slopes")
                    if g16:
                        finite = all((word & 0x7c00) != 0x7c00
                                     and (word >> 16 & 0x7c00) != 0x7c00 for word in words)
                    else:
                        finite = all((word & 0x7f800000) != 0x7f800000 for word in words)
                    if not finite:
                        raise ValueError("Coarse gradients require finite slopes")
                # Two coordinate slopes per screen axis, horizontal first. G16 packs
                # U in the low half and V in the high half of each gradient word.
                if g16:
                    h, vert = [int_operand(reg, scalar, vector, pending, sample_dest, signed=False)
                               for reg in coord_regs[:2]]
                    ddx = f"float2(widen16({h}), widen16({h} >> 16))"
                    ddy = f"float2(widen16({vert}), widen16({vert} >> 16))"
                else:
                    dudx, dvdx, dudy, dvdy = [sample_coord(reg) for reg in coord_regs[:4]]
                    ddx = f"float2({dudx}, {dvdx})"
                    ddy = f"float2({dudy}, {dvdy})"
                call = f"SampleGrad(samp, float2({u}, {v}), {ddx}, {ddy}{offset_arg})"
            elif base_op in ("image_sample_lz", "image_sample_l"):
                u, v = [sample_coord(reg) for reg in coord_regs[:2]]
                lod = sample_coord(coord_regs[2]) if base_op == "image_sample_l" else "0.0f"
                call = f"SampleLevel(samp, float2({u}, {v}), {lod}{offset_arg})"
            else:
                # RDNA2 places bias before the UV pair. Only UV contributes derivatives.
                uv = [vector[reg] for reg in coord_regs[-2:]]
                if any(value not in quad_values for value in uv):
                    raise ValueError("Unsupported texture coordinate")
                coordinate = f"float2({', '.join(uv)})"
                if base_op == "image_sample_b":
                    bias = sample_coord(coord_regs[0])
                    call = f"SampleBias(samp, {coordinate}, {bias}{offset_arg})"
                else:
                    call = f"Sample(samp, {coordinate}{offset_arg})"
            lines.append(f"    float4 sample{i} = {texture}.{call};")
            samples += 1
            sampled_textures.add(texture)
            vector_loads += 1
            for ch, n in zip(channels, dest):
                vector[f"v{n}"] = f"sample{i}.{ch}"
                sample_dest[f"v{n}"] = vector_loads
        elif m := match(r"image_get_lod v\[(\d+):(\d+)\], v\[(\d+):(\d+)\], "
                        r"s\[(\d+):(\d+)\], s\[(\d+):(\d+)\] dmask:0x3 dim:SQ_RSRC_IMG_2D"):
            dest, coords, image, state = [registers(*m.groups()[k:k+2], width)
                                          for k, width in zip((0, 2, 4, 6), (2, 2, 8, 4))]
            if dest.stop > 256 or coords.stop > 256:
                raise ValueError("Texture LOD VGPR out of range")
            if any(f"v{n}" in sample_dest for n in dest):
                raise ValueError("Write overlaps an outstanding sample")
            descriptor = [scalar.get(f"s{n}") for n in image]
            if (mask != "entry" or sampler is None or sample_kind == "comparison"
                    or second_texture_offset is not None
                    or descriptor != [(bindings[texture_offset], j) for j in range(8)]
                    or any(f"s{n}" in pending for n in (*image, *state))
                    or [scalar.get(f"s{n}") for n in state] != list(sampler)):
                raise ValueError("Unsupported texture LOD image or sampler binding")
            uv = [vector.get(f"v{n}") for n in coords]
            if any(value not in quad_values for value in uv):
                raise ValueError("Texture LOD requires coordinates with quad provenance")
            coord = f"float2({', '.join(uv)})"
            lines.append(f"    float2 sample{i} = float2(tex.CalculateLevelOfDetail(samp, {coord}), "
                         f"tex.CalculateLevelOfDetailUnclamped(samp, {coord}));")
            sample_kind = "plain"
            samples += 1
            sampled_textures.add(bindings[texture_offset])
            vector_loads += 1
            for channel, n in zip("xy", dest):
                vector[f"v{n}"] = f"sample{i}.{channel}"
                sample_dest[f"v{n}"] = vector_loads
        elif m := match(r"(flat|global)_load_dword (v\d+), v\[(\d+):(\d+)\](, off)?(?: offset:(-?\d+))?"):
            # One DWORD through a 64-bit title address. Cache-policy bits, the global saddr form and
            # every other width or direction are refused by the fall-through.
            segment, dst, first, last, off, imm = m.groups()
            offset = int(imm or 0)
            if (segment == "global") != (off is not None) or offset not in TITLE_OFFSETS[segment]:
                raise ValueError(f"Unsupported {segment} load form")
            if title_ranges is None:
                raise ValueError("Title memory is not bound")
            if segment == "flat" and not flat_global_only:
                raise ValueError("Flat loads require the global-only address profile")
            if mask != "entry" or int(dst[1:]) > 255 or int(last) > 255 or dst in sample_dest:
                raise ValueError("Invalid title memory load")
            low, high = [int_operand(f"v{n}", scalar, vector, pending, sample_dest, signed=False)
                         for n in registers(first, last, 2)]
            extended = offset & 0xffffffffffffffff
            lines.append(f"    precise float alu{i} = asfloat(title_load_dword(uint2({low}, {high}), "
                         f"uint2({extended & 0xffffffff:#x}u, {extended >> 32:#x}u)));")
            title_loads = True
            vector_loads += 1
            vector[dst] = f"alu{i}"
            sample_dest[dst] = vector_loads
        elif m := match(r"(image_sample_c(?:_lz)?(?:_o)?) (v\d+), (?:v\[(\d+):(\d+)\]|\[(v\d+), (v\d+), (v\d+)\]), "
                        r"s\[(\d+):(\d+)\], s\[(\d+):(\d+)\] dmask:0x1 dim:SQ_RSRC_IMG_2D"):
            # The optional packed offset precedes the reference, followed by the UV pair.
            op, dst, first, last, *nsa = m.groups()[:7]
            image = registers(*m.groups()[7:9], 8)
            state = registers(*m.groups()[9:11], 4)
            has_offset = op.endswith("_o")
            explicit_zero = op.removesuffix("_o") == "image_sample_c_lz"
            if first is None and op != "image_sample_c_lz":
                raise ValueError("Comparison sample requires a contiguous address")
            address = ([f"v{n}" for n in registers(first, last, 3 + has_offset)]
                       if first is not None else nsa)
            if any(int(reg[1:]) > 255 for reg in (dst, *address)):
                raise ValueError("Comparison sample VGPR out of range")
            if sampler is None or second_texture_offset is not None or sample_kind == "plain":
                raise ValueError("Comparison sampling requires one texture and no ordinary sampling")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            descriptor = [scalar.get(f"s{n}") for n in image]
            if (mask != "entry" or any(f"s{n}" in pending for n in (*image, *state))
                    or descriptor != [("tex", j) for j in range(8)]
                    or [scalar.get(f"s{n}") for n in state] != list(sampler)):
                raise ValueError("Unsupported image or sampler binding")
            if not explicit_zero and sampler[1] & 0xfff000:
                raise ValueError("Implicit comparison sampling requires MAX_LOD 0")
            offset_arg = sample_offset_arg(address.pop(0), vector, sample_dest, known_ssa_bits) if has_offset else ""
            if not explicit_zero and any(vector.get(reg) not in quad_values for reg in address[1:]):
                raise ValueError("Implicit comparison sampling requires coordinates with quad provenance")
            if sample_kind is None:
                lines[lines.index(SAMPLED_RESOURCES)] = comparison_resources(comparison_sampler_state(sampler))
            sample_kind = "comparison"
            values = [vector.get(reg) for reg in address]
            values = [f"uv.{v[1]}" if isinstance(v, tuple) and v[0] == "entry_uv" else v for v in values]
            for reg, value in zip(address, values):
                if reg in sample_dest:
                    raise ValueError("Sample used before vmcnt wait")
                if not isinstance(value, str) or not (value in quad_values or value.startswith(("sample", "alu", "params"))):
                    raise ValueError("Unsupported comparison sample operand")
            reference, u, v = values
            method = "SampleCmpLevelZero" if explicit_zero else "SampleCmp"
            lines.append(f"    float sample{i} = tex.{method}(samp, float2({u}, {v}), {reference}{offset_arg});")
            samples += 1
            sampled_textures.add("tex")
            vector_loads += 1
            vector[dst] = f"sample{i}"
            sample_dest[dst] = vector_loads
        elif m := match(r"image_gather4(_c)?(_lz|_l)?(_o)? v\[(\d+):(\d+)\], v\[(\d+):(\d+)\], "
                        r"s\[(\d+):(\d+)\], s\[(\d+):(\d+)\] dmask:0x([0-9a-f]+) dim:SQ_RSRC_IMG_2D"):
            comparison, lod_mode, offset_mode, dst_first, dst_last, addr_first, addr_last, image_first, image_last, \
                sampler_first, sampler_last, dmask = m.groups()
            if gather_mips is None or mask != "entry" or region is not None or sample_kind is not None:
                raise ValueError("Gather requires one unguarded instruction and a declared gather view")
            if lod_mode is None and gather_mips != 1:
                raise ValueError("Implicit gather requires a single visible mip")
            check_gather_sampler(sampler, gather_mips, comparison=bool(comparison))
            channels = {"1": 0, "2": 1, "4": 2, "8": 3}
            if comparison and dmask != "1":
                raise ValueError("Comparison gather requires red DMASK 0x1")
            if dmask not in channels:
                raise ValueError("Gather requires a one-hot source DMASK")
            dest = registers(dst_first, dst_last, 4)
            address = registers(addr_first, addr_last, 2 + bool(comparison) + bool(offset_mode) + (lod_mode == "_l"))
            image = registers(image_first, image_last, 8)
            state = registers(sampler_first, sampler_last, 4)
            if (max(dest.stop, address.stop) > 256 or max(image.stop, state.stop) > 106
                    or image.start % 4 or state.start % 4):
                raise ValueError("Invalid gather register range")
            if (any(f"s{n}" in pending for n in (*image, *state))
                    or [scalar.get(f"s{n}") for n in image] != [("tex", j) for j in range(8)]
                    or [scalar.get(f"s{n}") for n in state] != list(sampler)):
                raise ValueError("Unsupported gather image or sampler binding")
            if any(f"v{n}" in sample_dest for n in (*dest, *address)):
                raise ValueError("Gather overlaps an outstanding vector load")
            addr = [f"v{n}" for n in address]
            xoff, yoff = gather_offset(known_ssa_bits.get(vector[addr.pop(0)])) if offset_mode else (0, 0)
            if comparison:
                reference_reg = addr.pop(0)
                value = vector[reference_reg]
                if isinstance(value, tuple) and value[0] == "entry_uv":
                    reference = f"uv.{value[1]}"
                elif value in ("uv.x", "uv.y"):
                    reference = value
                else:
                    reference = fp_operand(reference_reg, scalar, vector, pending, sample_dest)
            mip = 0
            if lod_mode == "_l":
                raw = known_ssa_bits.get(vector[addr.pop()])
                level = struct.unpack("<f", struct.pack("<I", raw))[0] if raw is not None else None
                if level is None or not level.is_integer() or not 0 <= level < gather_mips:
                    raise ValueError("Gather requires a known integer LOD inside the view")
                mip = int(level)
            coords = [f"uv.{value[1]}" if isinstance(value, tuple) and value[0] == "entry_uv" else value
                      for value in (vector[reg] for reg in addr)]
            if any(not isinstance(value, str) or not (value in ("uv.x", "uv.y")
                   or value.startswith(("sample", "alu", "params"))) for value in coords):
                raise ValueError("Unsupported gather coordinate")
            u, v = coords
            resources, function, operand = GATHER_RESOURCES, "gather_2d", channels[dmask]
            if comparison:
                resources = gather_compare_resources((sampler[0] >> 12) & 7)
                function, operand = "gather_compare", reference
            lines[lines.index(SAMPLED_RESOURCES)] = resources
            lines.append(f"    float4 sample{i} = {function}(float2({u}, {v}), int2({xoff}, {yoff}), {mip}, {operand});")
            sample_kind = "gather"
            samples += 1
            sampled_textures.add("tex")
            vector_loads += 1
            for lane, reg in zip("xyzw", dest):
                vector[f"v{reg}"] = f"sample{i}.{lane}"
                sample_dest[f"v{reg}"] = vector_loads
        elif m := match(r"v_(fmaak|fmamk|madak|madmk)_f32 (v\d+), ([^,]+), ([^,]+), ([^,]+)"):
            # The mad forms use the unfused, denormal-flushing helper; the fma forms are fused.
            op, dst, *tokens = m.groups()
            literal = tokens[2] if op.endswith("ak") else tokens[1]
            if mask != "entry" or not re.fullmatch(r"0x[0-9a-f]{1,8}", literal):
                raise ValueError("Invalid literal multiply-add")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            values = [fp_operand(t, scalar, vector, pending, sample_dest) for t in tokens]
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {ALU['fma' if op.startswith('fma') else 'mad'][1].format(*values)};")
        elif m := match(r"v_mov_b32_sdwa (v\d+), (sext\()?([vs]\d+|-?\d+(?:\.\d+)?)(\))? dst_sel:(BYTE_[0-3]|WORD_[01]|DWORD) dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE) src0_sel:(BYTE_[0-3]|WORD_[01]|DWORD)"):
            dst, sext, src, close, dst_sel, unused, src_sel = m.groups()
            if mask != "entry" or bool(sext) != bool(close):
                raise ValueError("Invalid register move")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if (src_name := low16_name(src, vector)) is not None:
                # A 16-bit integer result defines only bits 15:0. A selection inside that half widens it
                # into a fully defined word; any other selection would read the undefined high half.
                if src_sel not in ("WORD_0", "BYTE_0", "BYTE_1"):
                    raise ValueError("Reads the undefined high half of a 16-bit result")
                word = f"asuint({src_name})"
            elif (half_name := half16_name(src, vector)) is not None:
                # A binary16 result is read through WORD_0 only (BYTE selections are for integer results).
                if src_sel != "WORD_0" or sext:
                    raise ValueError("Reads the undefined high half of a 16-bit result")
                word = f"asuint({half_name})"
            else:
                word = f"asuint({fp_operand(src, scalar, vector, pending, sample_dest)})"
            keep_old = SDWA_SEL[dst_sel][1] != 32 and unused == "UNUSED_PRESERVE"
            old_value = vector.get(dst) if keep_old else None
            if isinstance(old_value, tuple) and old_value[0] in ("low16", "half16"):
                raise ValueError("Reads the undefined high half of a 16-bit result")
            result = sdwa_dest(sdwa_source(word, src_sel, bool(sext)), dst_sel, unused, old_value)
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({result});")
        elif m := match(r"v_cvt_f32_f16_sdwa (v\d+), (-?)(?:\|([vs]\d+)\||([vs]\d+))( clamp)? dst_sel:DWORD dst_unused:UNUSED_(?:PAD|PRESERVE) src0_sel:(WORD_[01])"):
            # The SDWA form widens the selected half; modifiers apply after widening, as in the e64 form.
            dst, negate, bars, plain, clamp, src_sel = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if (half_name := half16_name(bars or plain, vector)) is not None:
                if src_sel != "WORD_0":
                    raise ValueError("Reads the undefined high half of a 16-bit result")
                if negate or bars or clamp:
                    raise ValueError("Modifiers on a binary16 arithmetic result are not lowered")
                word = f"asuint({half_name})"
            else:
                word = f"asuint({fp_operand(bars or plain, scalar, vector, pending, sample_dest)})"
            expression = f"widen16({sdwa_source(word, src_sel, False)})"
            if bars:
                expression = f"abs({expression})"
            if negate:
                expression = f"(-{expression})"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(rf"v_({'|'.join(SDWA_ALU)})_f32_sdwa (v\d+), (.+?)( clamp)? dst_sel:(BYTE_[0-3]|WORD_[01]|DWORD) dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE) src0_sel:DWORD( src1_sel:DWORD)?"):
            # SDWA forms of binary32 arithmetic take whole-dword sources, so the binary32 denormal mode never
            # applies to a zero-extended field; the result is placed like an SDWA move.
            op, dst, operands, clamp, dst_sel, unused, src1_sel = m.groups()
            tokens = operands.split(", ")
            arity, template = ALU[op]
            if mask != "entry" or len(tokens) != arity or bool(src1_sel) != (arity == 2):
                raise ValueError("Invalid arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            expression = template.format(*[fp_operand(t, scalar, vector, pending, sample_dest) for t in tokens])
            if clamp:
                expression = f"saturate({expression})"
            if dst_sel != "DWORD":
                expression = f"asfloat({sdwa_dest(f'asuint({expression})', dst_sel, unused, vector.get(dst) if unused == 'UNUSED_PRESERVE' else None)})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_mov_b32(?:_e32|_e64)? (v\d+), (-?\d+(?:\.\d+)?|0x[0-9a-f]{1,8}|[vs]\d+)"):
            # A bit copy of a numeric value; integer inline constants are bit patterns.
            dst, src = m.groups()
            if mask != "entry":
                raise ValueError("Invalid register move")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            value = fp_operand(src, scalar, vector, pending, sample_dest)
            src_bits = None
            if re.fullmatch(r"0x[0-9a-f]{1,8}", src):
                src_bits = int(src, 16)
            elif re.fullmatch(r"-?\d+", src):
                src_bits = int(src) & 0xffffffff
            elif re.fullmatch(r"-?\d+\.\d+", src):
                src_bits, = struct.unpack("<I", struct.pack("<f", float(src)))
            elif src.startswith("s") and isinstance(scalar.get(src), int):
                src_bits = scalar[src] & 0xffffffff
            elif src.startswith("v") and isinstance(vector.get(src), str) and vector[src] in known_ssa_bits:
                src_bits = known_ssa_bits[vector[src]]
            is_uniform = src.startswith("s") or bool(re.fullmatch(r"-?\d+(?:\.\d+)?|0x[0-9a-f]{1,8}", src)) or vector.is_uniform(src)
            word = f64_words.get(vector.get(src)) if src.startswith("v") else None
            vector[dst] = f"alu{i}"
            if word is not None:
                f64_words[f"alu{i}"] = word
            if src_bits is not None:
                known_ssa_bits[f"alu{i}"] = src_bits
            if is_uniform:
                vector.uniform.add(dst)
            lines.append(f"    precise float alu{i} = {value};")
        elif m := match(r"v_swap_b32(?:_e32)? (v\d+), (v\d+)"):
            # Both registers exchange their old values. Every vector entry names an immutable HLSL
            # temporary, so exchanging the entries is the whole lowering and emits no code.
            dst, src = m.groups()
            if mask != "entry" or int(dst[1:]) > 255 or int(src[1:]) > 255:
                raise ValueError("Invalid register swap")
            for reg in (dst, src):
                value = vector.get(reg)
                if not isinstance(value, str) or not value.startswith(("sample", "alu", "params")):
                    raise ValueError("Expected a numeric register")
                if reg in pending:
                    raise ValueError("Constant read before load completion")
                if reg in sample_dest:
                    raise ValueError("Swap overlaps an outstanding sample")
            u_dst = vector.is_uniform(dst)
            u_src = vector.is_uniform(src)
            vector[dst], vector[src] = vector[src], vector[dst]
            if u_dst:
                vector.uniform.add(src)
            else:
                vector.uniform.discard(src)
            if u_src:
                vector.uniform.add(dst)
            else:
                vector.uniform.discard(dst)
        elif m := match(r"v_readfirstlane_b32(?:_e32)? (s\d+), (.+)"):
            dst, src = m.groups()
            sgpr_name(dst)
            if mask != "entry":
                raise ValueError("Invalid lane read operation")
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            if src.startswith("v") and not vector.is_uniform(src):
                raise ValueError(f"v_readfirstlane_b32 requires a uniform source register: {src}")
            arg = int_operand(src, scalar, vector, pending, sample_dest, signed=False)
            lines.append(f"    uint salu{i} = WaveReadLaneFirst({arg});")
            scalar[dst] = ("uint", f"salu{i}")
        elif m := match(rf"v_({'|'.join(ALU)})_f32(?:_e32|_e64)? (v\d+), (.+?)( clamp)?"):
            op, dst, operands, clamp = m.groups()
            tokens = operands.split(", ")
            if op in ("fmac", "mac", "mac_legacy"):
                tokens.append(dst)
            arity, template = ALU[op]
            quad = mask == "quad"
            if (mask not in ("entry", "quad") or len(tokens) != arity
                    or (quad and (samples or second_texture_offset is not None
                                  or op not in ("add", "fma", "mul_legacy")))):
                raise ValueError("Invalid arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if quad and (clamp or any("|" in t or "abs(" in t for t in tokens)):
                raise ValueError("Whole-quad coordinate arithmetic must be affine")
            provenance = quad_values if quad else None
            values = [fp_operand(t, scalar, vector, pending, sample_dest, quad_values=provenance) for t in tokens]
            if quad:
                varying = [quad_values.get(vector.get(t.lstrip("-"), ""), False) for t in tokens]
                if op != "add" and all(varying[:2]):
                    raise ValueError("Whole-quad coordinate arithmetic must be affine")
                quad_values[f"alu{i}"] = any(varying)
            expression = template.format(*values)
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(rf"v_({'|'.join(SDWA_INT)})_sdwa (.+)"):
            # The e32 operation on the selected source words, placed with the SDWA move rules. Sources are
            # registers; an inline constant, clamp, a float modifier or a missing field is refused.
            op, rest = m.groups()
            arity, template = SDWA_INT[op]
            parsed = SDWA_INT_OPERANDS.fullmatch(rest)
            if not parsed:
                raise ValueError(f"Unsupported SDWA integer operands: v_{op}_sdwa {rest}")
            dst, sext0, src0, close0, sext1, src1, close1, dst_sel, unused, sel0, sel1 = parsed.groups()
            if bool(src1) != (arity == 2) or bool(sel1) != (arity == 2):
                raise ValueError(f"v_{op}_sdwa takes {arity} source(s), each with its own selection")
            if bool(sext0) != bool(close0) or bool(sext1) != bool(close1):
                raise ValueError("Unbalanced sext() on an SDWA source")
            if mask != "entry" or int(dst[1:]) > 255:
                raise ValueError("Invalid integer operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            args = [sdwa_source(int_operand(token, scalar, vector, pending, sample_dest, signed=False), sel, bool(sext))
                    for token, sel, sext in ((src0, sel0, sext0), (src1, sel1, sext1))[:arity]]
            result = sdwa_dest(f"({template.format(*args)})", dst_sel, unused, vector.get(dst))
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({result});")
        elif m := match(r"v_(lshlrev_b64|lshrrev_b64|ashrrev_i64)(?:_e64)? (v\[\d+:\d+\]), ([^,\s]+), ([^,\s]+)"):
            # VOP3 64-bit shifts (issue #928): D = S1 << S0[5:0], S1 >> S0[5:0], or signext(S1) >> S0[5:0]
            # (AMD RDNA 2 ISA §12.12, opcodes 767-769). The 64-bit value is two 32-bit words. Both source words
            # are read into temporaries before the destination pair is written, so the in-place form keeps the
            # original value, and no 32-bit HLSL shift ever receives a count of 32 or more.
            op, dst, amount, value = m.groups()
            first, last = (int(n) for n in re.fullmatch(r"v\[(\d+):(\d+)\]", dst).groups())
            names = (f"v{first}", f"v{last}")
            if mask != "entry" or last != first + 1 or last > 255 or any(n in sample_dest for n in names):
                raise ValueError(f"Invalid 64-bit shift destination: {line}")
            if re.search(r"\||abs\(|neg\(|^-[vs]", amount) or re.search(r"\||abs\(|neg\(|^-[vs]", value):
                raise ValueError(f"Source modifiers are not allowed on a 64-bit shift: {line}")
            # The ISA allows one scalar broadcast constant: an SGPR, an SGPR pair or a literal.
            scalar_like = [bool(re.fullmatch(r"s\d+|s\[\d+:\d+\]|0x[0-9a-f]+", t)) for t in (amount, value)]
            if all(scalar_like):
                raise ValueError(f"A 64-bit shift reads at most one scalar or literal source: {line}")
            if not re.fullmatch(r"v\d+|s\d+|-?\d+|0x[0-9a-f]{1,8}", amount) or (
                    re.fullmatch(r"-?\d+", amount) and not -16 <= int(amount) <= 64):
                raise ValueError(f"Invalid 64-bit shift amount: {amount}")
            count = int_operand(amount, scalar, vector, pending, sample_dest, signed=False)
            low, high = int64_operand(value, scalar, vector, pending, sample_dest, signed=False,
                                      encoding="e64", position=1)
            lines.append(f"    uint sh{i} = {count} & 63u;")
            lines.append(f"    uint sb{i} = sh{i} & 31u;")
            lines.append(f"    uint sc{i} = (32u - sb{i}) & 31u;")
            lines.append(f"    uint lo{i} = {low};")
            lines.append(f"    uint hi{i} = {high};")
            if op == "lshlrev_b64":
                lines.append(f"    uint cy{i} = sb{i} == 0u ? 0u : (lo{i} >> sc{i});")
                result_lo = f"(sh{i} < 32u ? (lo{i} << sb{i}) : 0u)"
                result_hi = f"(sh{i} < 32u ? ((hi{i} << sb{i}) | cy{i}) : (lo{i} << sb{i}))"
            else:
                lines.append(f"    uint cy{i} = sb{i} == 0u ? 0u : (hi{i} << sc{i});")
                if op == "lshrrev_b64":
                    shifted_hi, fill = f"(hi{i} >> sb{i})", "0u"
                else:
                    shifted_hi, fill = f"asuint(asint(hi{i}) >> sb{i})", f"asuint(asint(hi{i}) >> 31u)"
                result_lo = f"(sh{i} < 32u ? ((lo{i} >> sb{i}) | cy{i}) : {shifted_hi})"
                result_hi = f"(sh{i} < 32u ? {shifted_hi} : {fill})"
            lines.append(f"    precise float alu{i}_lo = asfloat({result_lo});")
            lines.append(f"    precise float alu{i}_hi = asfloat({result_hi});")
            vector[names[0]] = f"alu{i}_lo"
            vector[names[1]] = f"alu{i}_hi"
        elif m := match(rf"v_({'|'.join(INTEGER)})(?:_(e32|e64))? (v\d+), (.+)"):
            op, encoding, dst, sources = m.groups()
            tokens = sources.split(", ")
            arity, template = INTEGER[op]
            if mask != "entry" or int(dst[1:]) > 255 or dst in sample_dest or len(tokens) != arity:
                raise ValueError("Invalid integer operation")
            if arity > 2 and encoding == "e32":
                raise ValueError(f"Three-operand operation does not support e32 encoding: v_{op}")
            if op in INTEGER_VOP3_ONLY and encoding == "e32":
                raise ValueError(f"VOP3-only operation does not support e32 encoding: v_{op}")
            if op == "pack_b32_f16":
                # LLVM types the sources as binary16 and prints an inline float constant as a decimal float;
                # its binary16 encoding is used (1.0 is 0x3c00), as for the packed VOP3P forms. Any other
                # decimal float never names a valid operand here and is refused.
                for t in tokens:
                    if t not in INLINE_F16 and re.fullmatch(r"-?\d+\.\d+", t):
                        raise ValueError(f"Unsupported binary16 operand {t}")
                args = [f"{INLINE_F16[t]}u" if t in INLINE_F16
                        else int_operand(t, scalar, vector, pending, sample_dest, signed=False) for t in tokens]
            else:
                args = [int_operand(t, scalar, vector, pending, sample_dest, signed=False) for t in tokens]
            if op in MUL24_HELPERS:
                helpers.update(MUL24_HELPERS[op])
            helpers.update(INTEGER_HELPERS.get(op, ()))
            helpers.update(SAD_HELPERS.get(op, ()))
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({template.format(*args)});")
        elif m := match(rf"v_cmp_class_f32(_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            enc, dst, value, classes = m.groups()
            check_vopc_e32_dst(enc, dst)
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", classes):
                bits = f"{int(classes, 0) & 0xffffffff}u"
            elif re.fullmatch(r"[vs]\d+", classes):
                bits = f"asuint({fp_operand(classes, scalar, vector, pending, sample_dest)})"
            else:
                raise ValueError("Unsupported class mask")
            operand = fp_operand(value, scalar, vector, pending, sample_dest)
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = (class32({operand}) & {bits}) != 0u;")
        elif m := match(rf"v_cmp_class_f16(_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            enc, dst, value, classes = m.groups()
            check_vopc_e32_dst(enc, dst)
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            expr = f16_class(value, classes, scalar, vector, pending, sample_dest, allow_mods=enc == "_e64")
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = {expr};")

        elif m := (match(r"v_(add|sub|subrev)_nc_u32(?:_e32|_e64)? (v\d+), ([^,\s]+), ([^,\s]+)")
                   or match(r"v_(add|sub)_nc_i32 (v\d+), ([^,\s]+), ([^,\s]+)")):
            # 32-bit wraparound without carry. v_add_nc_i32 and v_sub_nc_i32 are VOP3-only and the same
            # bits without clamp. A trailing clamp or an operand modifier is left to the fall-through.
            op, dst, src0, src1 = m.groups()
            if mask != "entry" or dst in sample_dest:
                raise ValueError("Invalid integer operation")
            a = int_operand(src0, scalar, vector, pending, sample_dest, signed=False)
            b = int_operand(src1, scalar, vector, pending, sample_dest, signed=False)
            expression = {"add": f"{a} + {b}", "sub": f"{a} - {b}", "subrev": f"{b} - {a}"}[op]
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({expression});")
        elif m := match(rf"v_(add|sub|subrev)_co_u32 (v\d+), {LANE_MASK}, ([^,\s]+), ([^,\s]+)"):
            # 32-bit add or subtract that also writes the unsigned carry or borrow of each lane to a lane
            # mask. gfx10 encodes these three as VOP3 only and LLVM 15 prints them without a suffix. A
            # trailing clamp, an e32 or e64 suffix or an operand modifier is left to the fall-through.
            op, dst, carry, src0, src1 = m.groups()
            regs = lane_mask(carry)
            if mask != "entry" or dst in sample_dest or int(dst[1:]) > 255 or pending.intersection(regs):
                raise ValueError("Invalid carry-out operation")
            a = int_operand(src0, scalar, vector, pending, sample_dest, signed=False)
            b = int_operand(src1, scalar, vector, pending, sample_dest, signed=False)
            result, carry_out = CARRY_OUT[op]
            lines.append(f"    uint co{i} = {result.format(a, b)};")
            lines.append(f"    bool cmp{i} = {carry_out.format(a, b, r=f'co{i}')};")
            lines.append(f"    precise float alu{i} = asfloat(co{i});")
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            vector[dst] = f"alu{i}"
        elif m := match(r"v_mad_(u64_u32|i64_i32) v\[(\d+):(\d+)\], ([^,\s]+), ([^,\s]+), ([^,\s]+), ([^,\s]+)"):
            # 64-bit multiply-add of two 32-bit factors: D = S0 * S1 + S2 modulo 2^64, with S2 a 64-bit pair.
            # The unsigned form zero-extends the factors and writes the carry-out of the 64-bit add (the wrapped
            # sum is below S2) to the lane mask. The signed form sign-extends the factors; its carry-out is not
            # established here, so it is accepted only with the discarding `null` destination and never leaves
            # a lane mask behind. Every operand is read before the destination is written. gfx10 encodes both as
            # VOP3 only; a trailing clamp or modifier is left to the fall-through, a literal S2 is refused.
            kind, first, last, carry, src0, src1, src2 = m.groups()
            signed = kind == "i64_i32"
            first, last = int(first), int(last)
            if signed != (carry == "null"):
                raise ValueError("64-bit multiply-add carry-out must be null for the signed form and a lane mask otherwise")
            regs = []
            if not signed:
                if not re.fullmatch(LANE_MASK, carry):
                    raise ValueError("Invalid 64-bit multiply-add carry-out")
                regs = lane_mask(carry)
                if re.fullmatch(r"s\d+", carry):
                    sgpr_name(carry)
            names = (f"v{first}", f"v{last}")
            if (mask != "entry" or last != first + 1 or last > 255 or pending.intersection(regs)
                    or any(name in sample_dest for name in names)):
                raise ValueError("Invalid 64-bit multiply-add")
            a = int_operand(src0, scalar, vector, pending, sample_dest, signed=False)
            b = int_operand(src1, scalar, vector, pending, sample_dest, signed=False)
            c_lo, c_hi = int64_operand(src2, scalar, vector, pending, sample_dest, signed=False,
                                       encoding="e64", position=2)
            helpers.add("scalar_mul_hi")
            high = "mul_hi_i32" if signed else "mul_hi_u32"
            for word, value in (("a", a), ("b", b), ("cl", c_lo), ("ch", c_hi)):
                lines.append(f"    uint m{i}{word} = {value};")
            lines.append(f"    uint m{i}pl = m{i}a * m{i}b;")
            lines.append(f"    uint m{i}ph = {high}(m{i}a, m{i}b);")
            lines.append(f"    uint m{i}lo = m{i}pl + m{i}cl;")
            lines.append(f"    uint m{i}h1 = m{i}ph + m{i}ch;")
            lines.append(f"    uint m{i}hi = m{i}h1 + (m{i}lo < m{i}pl ? 1u : 0u);")
            if not signed:
                lines.append(f"    bool cmp{i} = m{i}h1 < m{i}ph || m{i}hi < m{i}h1;")
                for j, reg in enumerate(regs):
                    scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    precise float alu{i}l = asfloat(m{i}lo);")
            lines.append(f"    precise float alu{i}h = asfloat(m{i}hi);")
            vector[names[0]], vector[names[1]] = f"alu{i}l", f"alu{i}h"
        elif m := match(r"v_cvt_f64_(i32|u32)(?:_e32)? v\[(0|[1-9]\d*):(0|[1-9]\d*)\], ([^,\s]+)"):
            # Exact 32-bit integer to binary64 conversion into a VGPR pair v[d:d+1]. Every 32-bit integer is
            # representable, so there is no rounding: the two binary64 words are built from uint operations (sign,
            # exponent 1023 + the index of the highest set bit, the bits below it shifted to the top of the 52-bit
            # fraction) and no HLSL double is used. Zero gives +0.0 (both words 0); INT_MIN gives 0xc1e00000_00000000.
            # Only the unmodified VOP1 forms are lowered (plain and _e32, as LLVM 15 prints them); an _e64 suffix, clamp,
            # omod, DPP and SDWA are left to the fall-through. The source is read before the pair is written. The two
            # words are ordinary numeric registers, including for the supported binary64 comparisons.
            kind, first, last, src = m.groups()
            first, last = int(first), int(last)
            names = (f"v{first}", f"v{last}")
            if (mask != "entry" or last != first + 1 or last > 255 or any(name in sample_dest for name in names)):
                raise ValueError("Invalid 32-bit integer to binary64 conversion")
            signed = kind == "i32"
            lines.append(f"    uint c{i}x = {int_operand(src, scalar, vector, pending, sample_dest, signed=False)};")
            if signed:
                lines.append(f"    uint c{i}s = c{i}x & 0x80000000u;")
                lines.append(f"    uint c{i}u = c{i}s != 0u ? 0u - c{i}x : c{i}x;")
            else:
                lines.append(f"    uint c{i}s = 0u;")
                lines.append(f"    uint c{i}u = c{i}x;")
            lines.append(f"    uint c{i}n = c{i}u == 0u ? 0u : firstbithigh(c{i}u);")
            lines.append(f"    uint c{i}f = (c{i}u << (31u - c{i}n)) & 0x7fffffffu;")
            lines.append(f"    precise float alu{i}l = asfloat(c{i}u == 0u ? 0u : c{i}f << 21);")
            lines.append(f"    precise float alu{i}h = asfloat(c{i}u == 0u ? 0u : c{i}s | ((1023u + c{i}n) << 20) | (c{i}f >> 11));")
            vector[names[0]], vector[names[1]] = f"alu{i}l", f"alu{i}h"
            f64_words[f"alu{i}l"], f64_words[f"alu{i}h"] = ((kind, f"c{i}x"), 0), ((kind, f"c{i}x"), 1)
        elif m := match(r"v_cvt_f64_f32(_e32|_e64)? v\[(0|[1-9]\d*):(0|[1-9]\d*)\], ([^,\s]+)"):
            # Exact binary32 to binary64 conversion into a VGPR pair v[d:d+1], for a statically known source only
            # (cvt_f64_f32_source_bits). Both result words are computed here, in Python, and emitted as constants:
            # no HLSL double, no runtime input. Finite normal values, +-0 and +-infinity convert exactly;
            # subnormals, NaNs and unproven registers are refused. LLVM 15 prints the unmodified VOP1 form as _e32;
            # the only VOP3 (_e64) spellings it prints for this opcode are -x, |x|, -|x| and neg(0xLITERAL), and
            # those are accepted here (abs is applied first, then neg, as in the v_cvt_*_f32_e64 lowering; the order is not checked against the ISA document). An _e64 form without a
            # modifier, clamp, omod, DPP and SDWA are left to the fall-through.
            suffix, first, last, src = m.groups()
            first, last = int(first), int(last)
            names = (f"v{first}", f"v{last}")
            if (mask != "entry" or last != first + 1 or last > 255 or any(name in sample_dest for name in names)):
                raise ValueError("Invalid 32-bit float to binary64 conversion")
            has_abs = has_neg = False
            if suffix == "_e64":
                parts = CVT_F64_F32_E64_SOURCE.fullmatch(src)
                if not parts:
                    raise ValueError(f"Unsupported v_cvt_f64_f32_e64 source {src}")
                if parts.group(1):
                    src, has_neg = parts.group(1), True
                else:
                    neg, bar_open, src, bar_close = parts.groups()[1:]
                    if bar_open != bar_close or (neg == "" and bar_open == "") or (neg and not bar_open and src.startswith("0x")):
                        raise ValueError(f"Unsupported v_cvt_f64_f32_e64 source {src}")
                    has_abs, has_neg = bool(bar_open), bool(neg)
            bits = cvt_f64_f32_source_bits(src, scalar, vector, pending, sample_dest, known_ssa_bits)
            if has_abs:
                bits &= 0x7fffffff
            if has_neg:
                bits ^= 0x80000000
            low, high = cvt_f64_f32_words(bits)
            lines.append(f"    precise float alu{i}l = asfloat({low}u);")
            lines.append(f"    precise float alu{i}h = asfloat({high}u);")
            vector[names[0]], vector[names[1]] = f"alu{i}l", f"alu{i}h"
            f64_words[f"alu{i}l"], f64_words[f"alu{i}h"] = (("static", low, high), 0), (("static", low, high), 1)
        elif m := match(r"v_cvt_(i32|u32)_f64(?:_e32)? (v\d+), v\[(0|[1-9]\d*):(0|[1-9]\d*)\]"):
            # Binary64 to 32-bit integer, for a pair whose provenance is proven (f64_words); no HLSL double is used.
            # Accepted: the pair of v_cvt_f64_i32 read by v_cvt_i32_f64 and the pair of v_cvt_f64_u32 read by
            # v_cvt_u32_f64 (every 32-bit integer is exact in binary64, so the round trip returns the source word),
            # and the pair of v_cvt_f64_f32 of a static source, truncated toward zero here in Python when the value is
            # finite and the truncated result fits the destination. Both words must carry the same record, the low
            # word as word 0 and the high word as word 1. Cross-signedness, NaN, infinity, out-of-range values, a
            # pair of unknown provenance (raw constants, runtime registers) and a pair with one overwritten word are
            # refused; so are the _e64 spelling and every modifier, which fall through to the unsupported error.
            kind, dst, first, last = m.groups()
            first, last = int(first), int(last)
            names = (f"v{first}", f"v{last}")
            if (mask != "entry" or last != first + 1 or last > 255 or int(dst[1:]) > 255 or dst in sample_dest
                    or any(name in sample_dest or name in pending for name in names)):
                raise ValueError("Invalid binary64 to 32-bit integer conversion")
            low_word, high_word = (f64_words.get(vector.get(name)) for name in names)
            if (low_word is None or high_word is None or low_word[0] != high_word[0]
                    or (low_word[1], high_word[1]) != (0, 1)):
                raise ValueError(f"Unproven binary64 source v[{first}:{last}] at v_cvt_{kind}_f64")
            record = low_word[0]
            if record[0] == "static":
                value = struct.unpack("<d", struct.pack("<II", record[1], record[2]))[0]
                if not math.isfinite(value):
                    raise ValueError(f"v_cvt_{kind}_f64 source is not finite")
                result = math.trunc(value)
                if not (-0x80000000 if kind == "i32" else 0) <= result <= (0x7fffffff if kind == "i32" else 0xffffffff):
                    raise ValueError(f"v_cvt_{kind}_f64 source {value!r} is out of range")
                expression = f"{result & 0xffffffff}u"
            elif record[0] != kind:
                raise ValueError(f"v_cvt_{kind}_f64 of a v_cvt_f64_{record[0]} pair is not a supported round trip")
            else:
                expression = record[1]
            lines.append(f"    precise float alu{i} = asfloat({expression});")
            vector[dst] = f"alu{i}"
        elif m := match(r"v_cvt_f32_f64(?:_e32)? (v\d+), v\[(0|[1-9]\d*):(0|[1-9]\d*)\]"):
            # Binary64 to binary32 narrowing, for the pair of a v_cvt_f64_f32 of a static source only (a record
            # ("static", low, high) on both words, the low word as word 0 and the high word as word 1), and only when the
            # value is exactly a normal binary32 or a signed zero (cvt_f32_f64_exact_bits: narrowed and widened again it
            # returns the same words). The result is that binary32 word, computed here and emitted as a constant, so no
            # HLSL double is used and neither the rounding mode nor the denorm mode is read. Infinities, NaNs,
            # subnormals, a value that would need rounding, a pair of integer origin (v_cvt_f64_i32 or v_cvt_f64_u32,
            # even where the integer would fit), a pair of unknown provenance, a pair with one overwritten word or
            # words of different pairs, the _e64 spelling and every modifier are refused (the last fall through to the
            # unsupported error). Which MODE field governs the binary64 narrowing is not decided here.
            dst, first, last = m.groups()
            first, last = int(first), int(last)
            names = (f"v{first}", f"v{last}")
            if (mask != "entry" or last != first + 1 or last > 255 or int(dst[1:]) > 255 or dst in sample_dest
                    or any(name in sample_dest or name in pending for name in names)):
                raise ValueError("Invalid binary64 to binary32 conversion")
            low_word, high_word = (f64_words.get(vector.get(name)) for name in names)
            if (low_word is None or high_word is None or low_word[0] != high_word[0]
                    or (low_word[1], high_word[1]) != (0, 1)):
                raise ValueError(f"Unproven binary64 source v[{first}:{last}] at v_cvt_f32_f64")
            record = low_word[0]
            if record[0] != "static":
                raise ValueError(f"v_cvt_f32_f64 of a v_cvt_f64_{record[0]} pair (integer origin) is not supported")
            lines.append(f"    precise float alu{i} = asfloat({cvt_f32_f64_exact_bits(record[1], record[2])}u);")
            vector[dst] = f"alu{i}"
        elif m := match(rf"v_(add|sub|subrev)_co_ci_u32_(e32|e64) (v\d+), {LANE_MASK}, ([^,\s]+), ([^,\s]+), {LANE_MASK}"):
            # The carry-out add and subtracts above with a carry or borrow of each lane read from a lane mask.
            # LLVM 15 prints both encodings with their suffix. The VOP2 (e32) encoding reads and writes VCC and
            # takes a VGPR as src1; the VOP3 (e64) encoding names both masks, which must have the same width.
            # The carry-in must be a per-lane condition the translator tracks, as for v_cndmask_b32. A trailing
            # clamp or an operand modifier is left to the fall-through.
            op, encoding, dst, carry, src0, src1, carry_in = m.groups()
            regs, in_regs = lane_mask(carry), lane_mask(carry_in)
            condition = scalar.get(in_regs[0])
            if (mask != "entry" or dst in sample_dest or int(dst[1:]) > 255 or len(regs) != len(in_regs)
                    or pending.intersection(regs + in_regs)
                    or (encoding == "e32" and not (regs == in_regs == ["vcc"] and re.fullmatch(r"v\d+", src1)))
                    or not isinstance(condition, tuple) or condition[0] != "condition"
                    or [scalar.get(r) for r in in_regs]
                    != [(*condition[:2], j, len(in_regs)) for j in range(len(in_regs))]):
                raise ValueError("Invalid carry-in operation")
            a = int_operand(src0, scalar, vector, pending, sample_dest, signed=False)
            b = int_operand(src1, scalar, vector, pending, sample_dest, signed=False)
            partial, result, carry_out = CARRY_IN[op]
            lines.append(f"    uint ci{i} = {condition[1]} ? 1u : 0u;")
            lines.append(f"    uint cp{i} = {partial.format(a, b)};")
            lines.append(f"    uint co{i} = {result.format(p=f'cp{i}', c=f'ci{i}')};")
            lines.append(f"    bool cmp{i} = {carry_out.format(a, b, p=f'cp{i}', c=f'ci{i}', r=f'co{i}')};")
            lines.append(f"    precise float alu{i} = asfloat(co{i});")
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            vector[dst] = f"alu{i}"
        elif m := match(r"v_(min|max)_(i32|u32)(?:_e32|_e64)? (v\d+), ([^,]+), ([^,]+)"):
            op, kind, dst, *tokens = m.groups()
            if mask != "entry":
                raise ValueError("Invalid integer arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            values = [int_operand(t, scalar, vector, pending, sample_dest, signed=kind == "i32")
                      for t in tokens]
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({op}({values[0]}, {values[1]}));")
        elif m := match(r"v_(min3|max3|med3)_(i32|u32)(?:_e64)? (v\d+), ([^,]+), ([^,]+), ([^,]+)"):
            op, kind, dst, *tokens = m.groups()
            if mask != "entry":
                raise ValueError("Invalid integer arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            values = [int_operand(t, scalar, vector, pending, sample_dest, signed=kind == "i32")
                      for t in tokens]
            if op == "med3":
                vec_type = "int3" if kind == "i32" else "uint3"
                lines.append(f"    {vec_type} med{i} = {vec_type}({values[0]}, {values[1]}, {values[2]});")
                expression = f"max(min(med{i}.x, med{i}.y), min(max(med{i}.x, med{i}.y), med{i}.z))"
            else:
                fn = op[:-1]
                expression = f"{fn}({fn}({values[0]}, {values[1]}), {values[2]})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({expression});")

        elif m := match(r"v_frexp_exp_i32_f32(?:_e32|_e64)? (v\d+), ([^,]+)"):
            dst, src = m.groups()
            if mask != "entry":
                raise ValueError("Invalid arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            # Only the magnitude bits matter. Float sign operations can flush subnormal inputs.
            value = fp_operand(src, scalar, vector, pending, sample_dest, ignore_sign=True)
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat(frexp_exp32({value}));")

        elif m := match(r"v_ldexp_f32(?:_e64)? (v\d+), ([^,]+), ([^,]+?)( clamp)?"):
            dst, src0, src1, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            value = fp_operand(src0, scalar, vector, pending, sample_dest)
            exponent = int_operand(src1, scalar, vector, pending, sample_dest, signed=True)
            expression = f"ldexp32({value}, {exponent})"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(rf"v_cmp_({'|'.join(COMPARE)})_f32(_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            op, enc, dst, *tokens = m.groups()
            check_vopc_e32_dst(enc, dst)
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            expr = f32_comparison(op, tokens, scalar, vector, pending, sample_dest)
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = {expr};")
        elif m := match(rf"v_cmp_({'|'.join(COMPARE)})_f16(_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            op, enc, dst, *tokens = m.groups()
            check_vopc_e32_dst(enc, dst)
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            expr = f16_comparison(op, tokens, scalar, vector, pending, sample_dest, allow_mods=enc == "_e64")
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = {expr};")
        elif m := match(rf"v_cmp_({'|'.join(INT_COMPARE)})_(i32|u32)(_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            op, kind, enc, dst, *tokens = m.groups()
            check_vopc_e32_dst(enc, dst)
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            values = [int_operand(t, scalar, vector, pending, sample_dest, signed=kind == "i32")
                      for t in tokens]
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = {INT_COMPARE[op].format(*values)};")
        elif m := match(rf"v_cmp_(eq|ne|lt|le|gt|ge)_(i16|u16)(_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            # Only the low 16 bits of each source take part; gfx10 has no f/t forms at this width.
            op, kind, enc, dst, *tokens = m.groups()
            check_vopc_e32_dst(enc, dst)
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            values = [int16_operand(t, scalar, vector, pending, sample_dest, signed=kind == "i16")
                      for t in tokens]
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = {INT_COMPARE[op].format(*values)};")
        elif m := match(rf"v_cmp_({'|'.join(INT_COMPARE)})_(i64|u64)(_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            # 64-bit comparisons: the two words are compared separately, so no 64-bit HLSL type is needed.
            op, kind, enc, dst, *tokens = m.groups()
            # Without a suffix LLVM 15 picks e32 when the operands fit it (vcc destination, VGPR-pair src1) and
            # e64 otherwise; its disassembly always prints the suffix.
            if enc is None:
                enc = "_e32" if dst in ("vcc", "vcc_lo") and re.fullmatch(r"v\[\d+:\d+\]", tokens[1]) else "_e64"
            enc = enc[1:]
            if enc == "e32" and dst not in ("vcc", "vcc_lo"):
                raise ValueError("64-bit comparison e32 destination must be vcc")
            regs = lane_mask(dst)
            if dst.startswith("s["):
                sgpr_pair(dst)
            elif dst.startswith("s"):
                sgpr_name(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            declarations, expr = int64_comparison(i, op, kind, tokens, enc, scalar, vector, pending, sample_dest)
            lines.extend(declarations)
            lines.append(f"    bool cmp{i} = {expr};")
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
        elif m := (match(rf"v_cmp_({'|'.join(COMPARE)})_f64_(e32|e64) {LANE_MASK}, ([^,]+), ([^,]+)")
                   or match(rf"v_cmp_(class)_f64_(e32|e64) {LANE_MASK}, ([^,]+), ([^,]+)")):
            # binary64 comparisons on the source words (cmp_f64 helpers). MODE[7:6] also decides whether binary64
            # denormal inputs are flushed, so the forms need the declared preserving entry state.
            op, enc, dst, *tokens = m.groups()
            check_vopc_e32_dst("_" + enc, dst)
            regs = lane_mask(dst)
            if dst.startswith("s["):
                sgpr_pair(dst)
            elif dst.startswith("s"):
                sgpr_name(dst)
            if half_denorm != HALF_DENORM_PRESERVE:
                raise ValueError("binary64 denormal mode unknown at entry")
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            helpers.add("cmp_f64")
            declarations, expr = f64_comparison(i, op, tokens, enc, scalar, vector, pending, sample_dest)
            lines.extend(declarations)
            lines.append(f"    bool cmp{i} = {expr};")
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
        elif m := match(rf"v_cmp_({'|'.join(COMPARE)})_f32_sdwa {LANE_MASK}, ([^,]+), ([^,]+) src0_sel:DWORD src1_sel:DWORD"):
            # With whole-dword selections the SDWA comparison is the e32/e64 one; byte and word selections
            # would compare zero-extended fields as binary32 and are refused.
            op, dst, *tokens = m.groups()
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            # The decoder prints the explicit modifier. Retain the existing decimal
            # float path; an integer inline constant names bits and is a distinct form.
            tokens = [SDWA_NEG_DECIMAL.sub(r"-\1", token) for token in tokens]
            expr = f32_comparison(op, tokens, scalar, vector, pending, sample_dest)
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = {expr};")
        elif m := match(rf"v_cndmask_b32(?:_e32|_e64)? (v\d+), ([^,]+), ([^,]+), {LANE_MASK}"):
            dst, unset, chosen, source = m.groups()
            regs = lane_mask(source)
            condition = scalar.get(regs[0])
            if (mask != "entry" or pending.intersection(regs) or not isinstance(condition, tuple)
                    or condition[0] != "condition"
                    or [scalar.get(r) for r in regs] != [(*condition[:2], j, len(regs)) for j in range(len(regs))]):
                raise ValueError("Select mask is not a tracked comparison")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            values = [fp_operand(t, scalar, vector, pending, sample_dest) for t in (chosen, unset)]
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {condition[1]} ? {values[0]} : {values[1]};")
        elif m := match(r"v_cvt_f32_f16(?:_e32|_e64)? (v\d+), (-?)(?:\|([vs]\d+|0x[0-9a-f]{1,8}|\d+)\||abs\(([vs]\d+|0x[0-9a-f]{1,8}|\d+)\)|([vs]\d+|0x[0-9a-f]{1,8}|\d+))( clamp)?"):
            dst, negate, bars, call, plain, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            source = bars or call or plain
            if (half_name := half16_name(source, vector)) is not None:
                # A binary16 arithmetic result defines bits 15:0, which widen16 reads; modifiers are not lowered.
                if negate or bars or call or clamp:
                    raise ValueError("Modifiers on a binary16 arithmetic result are not lowered")
                word = f"asuint({half_name})"
            elif re.fullmatch(r"0x[0-9a-f]{1,8}|\d+", source):
                word = f"{int(source, 0) & 0xffffffff}u"
            else:
                word = f"asuint({fp_operand(source, scalar, vector, pending, sample_dest)})"
            expression = f"widen16({word})"
            if bars or call:
                expression = f"abs({expression})"
            if negate:
                expression = f"(-{expression})"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif (m := DPP_MOVREL_PATTERN.fullmatch(line)) or (plain := PLAIN_MOVREL_PATTERN.fullmatch(line)):
            # The plain forms index exactly as the DPP forms do, each lane reading its own VGPRs (no swizzle).
            if m:
                op, rest = m.groups()
                if mask != "entry":
                    raise ValueError("Invalid DPP movrel outside entry mask")
                ops, perm, _ = parse_dpp(rest, 2)
                if not all(re.fullmatch(r"v\d+", t) for t in ops):
                    raise ValueError(f"Expected two VGPR operands without modifiers for {op}")
            else:
                op, *ops = plain.groups()
                perm = None
                if mask != "entry":
                    raise ValueError(f"Invalid {op} outside entry mask")
            kind = op if op.endswith("_dpp") else f"{op}_dpp"  # the indexing rule is the same for both encodings
            dst_base, src_base = int(ops[0][1:]), int(ops[1][1:])
            if not (0 <= dst_base <= 255 and 0 <= src_base <= 255):
                raise ValueError(f"VGPR base out of range for {op}")
            m0 = scalar.get("m0")
            if isinstance(m0, int):
                m0_u = m0 & 0xffffffff
                if kind == "v_movreld_b32_dpp":
                    src_offsets, dst_offsets = [0], [m0_u]
                elif kind == "v_movrels_b32_dpp":
                    src_offsets, dst_offsets = [m0_u], [0]
                elif kind == "v_movrelsd_b32_dpp":
                    src_offsets, dst_offsets = [m0_u], [m0_u]
                else:
                    src_offsets, dst_offsets = [m0_u & 0x3ff], [(m0_u >> 16) & 0x3ff]
                if src_offsets[0] > 255 or dst_offsets[0] > 255:
                    raise ValueError(f"Static m0 offset out of range for {op}")
                soff_expr = doff_expr = None
            elif isinstance(m0, tuple) and len(m0) == 2 and m0[0] == "uint":
                if "m0" not in scalar_mask:
                    raise ValueError(f"Dynamic m0 offset is unbounded for {op}")
                m0_mask = scalar_mask["m0"]
                m0_expr = m0[1]
                if kind == "v_movreld_b32_dpp":
                    src_offsets, dst_offsets = [0], masked_offsets(m0_mask)
                    soff_expr, doff_expr = None, m0_expr
                elif kind == "v_movrels_b32_dpp":
                    src_offsets, dst_offsets = masked_offsets(m0_mask), [0]
                    soff_expr, doff_expr = m0_expr, None
                elif kind == "v_movrelsd_b32_dpp":
                    offs = masked_offsets(m0_mask)
                    src_offsets, dst_offsets = offs, offs
                    soff_expr, doff_expr = m0_expr, m0_expr
                else:
                    src_offsets = masked_offsets(m0_mask & 0x3ff)
                    dst_offsets = masked_offsets((m0_mask >> 16) & 0x3ff)
                    soff_expr = f"({m0_expr} & 0x3ffu)"
                    doff_expr = f"(({m0_expr} >> 16) & 0x3ffu)"
            else:
                raise ValueError(f"Unsupported m0 value for {op}")
            if any(src_base + k > 255 for k in src_offsets) or any(dst_base + k > 255 for k in dst_offsets):
                raise ValueError(f"Indexed VGPR exceeds 255 for {op}")
            if any(f"v{dst_base + k}" in sample_dest for k in dst_offsets):
                raise ValueError("Write overlaps an outstanding sample")
            # Read all reachable source VGPRs before any destination update (supports overlapping banks).
            src_exprs = [(k, movrel_vgpr(src_base + k, vector, sample_dest)) for k in src_offsets]
            if len(src_exprs) == 1:
                swizzled = (f"asuint({src_exprs[0][1]})" if perm is None
                            else emit_quad_swizzle_u32(lines, i, src_exprs[0][1], perm))
            else:
                lines.append(f"    uint dpp_soff{i} = {soff_expr};")
                sel = f"asuint({src_exprs[-1][1]})"
                for k, expr in reversed(src_exprs[:-1]):
                    sel = f"(dpp_soff{i} == {k}u ? asuint({expr}) : {sel})"
                lines.append(f"    precise float dpp_src{i} = asfloat({sel});")
                swizzled = (f"asuint(dpp_src{i})" if perm is None
                            else emit_quad_swizzle_u32(lines, i, f"dpp_src{i}", perm))
            if len(dst_offsets) == 1:
                dst_reg = f"v{dst_base + dst_offsets[0]}"
                vector[dst_reg] = f"alu{i}"
                lines.append(f"    precise float alu{i} = asfloat({swizzled});")
            else:
                prev_dsts = [(k, movrel_vgpr(dst_base + k, vector, sample_dest)) for k in dst_offsets]
                lines.append(f"    uint dpp_val{i} = {swizzled};")
                lines.append(f"    uint dpp_doff{i} = {doff_expr};")
                for k, prev in prev_dsts:
                    dst_reg = f"v{dst_base + k}"
                    vector[dst_reg] = f"alu{i}_{k}"
                    lines.append(f"    precise float alu{i}_{k} = (dpp_doff{i} == {k}u) ? asfloat(dpp_val{i}) : {prev};")
        elif m := match(r"v_swaprel_b32 (v\d+), (v\d+)"):
            # VGPR[vdst + m0[25:16]] and VGPR[vsrc + m0[9:0]] exchange their values (#1795), with the m0 rules of
            # the movrel forms: both sides are read before either is written, so a pair naming one register is
            # unchanged.
            if mask != "entry":
                raise ValueError("Invalid v_swaprel_b32 outside entry mask")
            dst_base, src_base = int(m.group(1)[1:]), int(m.group(2)[1:])
            m0 = scalar.get("m0")
            if isinstance(m0, int):
                m0_u = m0 & 0xffffffff
                src_offsets, dst_offsets = [m0_u & 0x3ff], [(m0_u >> 16) & 0x3ff]
                if src_offsets[0] > 255 or dst_offsets[0] > 255:
                    raise ValueError("Static m0 offset out of range for v_swaprel_b32")
                soff_expr, doff_expr = f"{src_offsets[0]}u", f"{dst_offsets[0]}u"
            elif isinstance(m0, tuple) and len(m0) == 2 and m0[0] == "uint":
                if "m0" not in scalar_mask:
                    raise ValueError("Dynamic m0 offset is unbounded for v_swaprel_b32")
                m0_mask = scalar_mask["m0"]
                src_offsets = masked_offsets(m0_mask & 0x3ff)
                dst_offsets = masked_offsets((m0_mask >> 16) & 0x3ff)
                soff_expr, doff_expr = f"({m0[1]} & 0x3ffu)", f"(({m0[1]} >> 16) & 0x3ffu)"
            else:
                raise ValueError("Unsupported m0 value for v_swaprel_b32")
            if any(src_base + k > 255 for k in src_offsets) or any(dst_base + k > 255 for k in dst_offsets):
                raise ValueError("Indexed VGPR exceeds 255 for v_swaprel_b32")
            touched = sorted({dst_base + k for k in dst_offsets} | {src_base + k for k in src_offsets})
            if any(f"v{r}" in sample_dest for r in touched):
                raise ValueError("Write overlaps an outstanding sample")
            old = {r: movrel_vgpr(r, vector, sample_dest) for r in touched}
            lines.append(f"    uint swap_soff{i} = {soff_expr};")
            lines.append(f"    uint swap_doff{i} = {doff_expr};")
            for side, base, offsets, offset in (("s", src_base, src_offsets, f"swap_soff{i}"),
                                                ("d", dst_base, dst_offsets, f"swap_doff{i}")):
                value = f"asuint({old[base + offsets[-1]]})"
                for k in reversed(offsets[:-1]):
                    value = f"({offset} == {k}u ? asuint({old[base + k]}) : {value})"
                lines.append(f"    uint swap_{side}val{i} = {value};")
            for r in touched:
                value = old[r]
                if r - src_base in src_offsets:
                    value = f"(swap_soff{i} == {r - src_base}u ? asfloat(swap_dval{i}) : {value})"
                if r - dst_base in dst_offsets:
                    value = f"(swap_doff{i} == {r - dst_base}u ? asfloat(swap_sval{i}) : {value})"
                vector[f"v{r}"] = f"alu{i}_r{r}"
                lines.append(f"    precise float alu{i}_r{r} = {value};")
        elif m := match(rf"v_({'|'.join(DPP_CVT)})_dpp (v\d+), (.+)"):
            op, dst, rest = m.groups()
            float_source, template, helper = DPP_CVT[op]
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid conversion DPP operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            tokens, perm, is_dpp8 = parse_dpp(rest, 1)
            value, absolute, negate = dpp_vgpr(
                tokens[0], vector, sample_dest, allow_mods=float_source and not is_dpp8
            )
            bits = emit_quad_swizzle_u32(lines, i, value, perm)
            if absolute:
                bits = f"({bits} & 0x7fffffffu)"
            if negate:
                bits = f"({bits} ^ 0x80000000u)"
            if helper:
                helpers.add(helper)
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {template.format(bits)};")
        elif m := match(rf"({'|'.join(DPP_EXTRA)}) (v\d+), (.+)"):
            op, dst, rest = m.groups()
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid DPP operation outside entry mask")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            kind, allow_fp_mods, helper_name = DPP_EXTRA[op]
            operand_count = 4 if kind == "co_ci" else (1 if kind in ("f32_unary", "frexp_mant", "frexp_exp") else 2)
            ops, perm, is_dpp8 = parse_dpp(rest, operand_count)
            mods_ok = (not is_dpp8) and allow_fp_mods
            if kind == "co_ci":
                carry_out, src0, src1, carry_in = ops
                if carry_out != carry_in or carry_in not in ("vcc", "vcc_lo"):
                    raise ValueError(f"Unsupported carry mask for {op}")
                condition = scalar.get("vcc")
                if (pending.intersection(("vcc",)) or not isinstance(condition, tuple)
                        or condition[0] != "condition" or condition[2:] != (0, 1)):
                    raise ValueError("Carry mask is not a tracked condition")
                s0_val, _, _ = dpp_vgpr(src0, vector, sample_dest, allow_mods=False)
                s1_val, _, _ = dpp_vgpr(src1, vector, sample_dest, allow_mods=False)
                s0_bits = emit_quad_swizzle_u32(lines, i, s0_val, perm)
                lines.append(f"    uint dpp_a{i} = {s0_bits};")
                lines.append(f"    uint dpp_b{i} = asuint({s1_val});")
                lines.append(f"    uint dpp_ci{i} = {condition[1]} ? 1u : 0u;")
                if op == "v_add_co_ci_u32_dpp":
                    lines.append(f"    uint dpp_t{i} = dpp_a{i} + dpp_b{i};")
                    lines.append(f"    uint dpp_r{i} = dpp_t{i} + dpp_ci{i};")
                    lines.append(f"    bool cmp{i} = (dpp_t{i} < dpp_a{i}) || (dpp_r{i} < dpp_t{i});")
                elif op == "v_sub_co_ci_u32_dpp":
                    lines.append(f"    uint dpp_t{i} = dpp_a{i} - dpp_b{i};")
                    lines.append(f"    uint dpp_r{i} = dpp_t{i} - dpp_ci{i};")
                    lines.append(f"    bool cmp{i} = (dpp_a{i} < dpp_b{i}) || (dpp_t{i} < dpp_ci{i});")
                else:
                    lines.append(f"    uint dpp_t{i} = dpp_b{i} - dpp_a{i};")
                    lines.append(f"    uint dpp_r{i} = dpp_t{i} - dpp_ci{i};")
                    lines.append(f"    bool cmp{i} = (dpp_b{i} < dpp_a{i}) || (dpp_t{i} < dpp_ci{i});")
                scalar["vcc"] = ("condition", f"cmp{i}", 0, 1)
                vector[dst] = f"alu{i}"
                lines.append(f"    precise float alu{i} = asfloat(dpp_r{i});")
            elif kind in ("f32_unary", "frexp_mant", "frexp_exp"):
                src0 = ops[0]
                s0_val, abs0, neg0 = dpp_vgpr(src0, vector, sample_dest, allow_mods=mods_ok)
                s0_bits = emit_quad_swizzle_u32(lines, i, s0_val, perm)
                if kind in ("frexp_mant", "frexp_exp"):
                    helpers.add(helper_name)
                    bits = s0_bits
                    if abs0:
                        bits = f"({bits} & 0x7fffffffu)"
                    if neg0:
                        bits = f"({bits} ^ 0x80000000u)"
                    if kind == "frexp_mant":
                        expr = f"{helper_name}({bits})"
                    else:
                        expr = f"asfloat({helper_name}({bits}))"
                else:
                    val = f"asfloat({s0_bits})"
                    if abs0:
                        val = f"abs({val})"
                    if neg0:
                        val = f"(-{val})"
                    expr = {
                        "v_rndne_f32_dpp": f"round({val})",
                        "v_sin_f32_dpp": f"sin32({val})",
                        "v_cos_f32_dpp": f"cos32({val})",
                        "v_rcp_iflag_f32_dpp": f"(1.0f / ({val}))",
                    }[op]
                vector[dst] = f"alu{i}"
                lines.append(f"    precise float alu{i} = {expr};")
            else:
                src0, src1 = ops
                acc_val, _, _ = dpp_vgpr(dst, vector, sample_dest, allow_mods=False)
                s0_val, abs0, neg0 = dpp_vgpr(src0, vector, sample_dest, allow_mods=mods_ok)
                s1_val, abs1, neg1 = dpp_vgpr(src1, vector, sample_dest, allow_mods=mods_ok)
                s0_bits = emit_quad_swizzle_u32(lines, i, s0_val, perm)
                if kind == "mac_f32":
                    a = f"asfloat({s0_bits})"
                    if abs0:
                        a = f"abs({a})"
                    if neg0:
                        a = f"(-{a})"
                    b = s1_val
                    if abs1:
                        b = f"abs({b})"
                    if neg1:
                        b = f"(-{b})"
                    expr = f"mad32({a}, {b}, {acc_val})"
                else:
                    helpers.add(helper_name)
                    expr = f"asfloat({helper_name}({s0_bits}, asuint({s1_val}), asuint({acc_val})))"
                vector[dst] = f"alu{i}"
                lines.append(f"    precise float alu{i} = {expr};")
        elif m := match(r"(v_dot4c_i32_i8)(?:_e32)? (.+)"):
            op, rest = m.groups()
            parts_ = rest.split(", ")
            if len(parts_) != 3:
                raise ValueError("Invalid dot-accumulate operand count")
            dst, src0, src1 = parts_
            if mask != "entry":
                raise ValueError("Invalid dot-accumulate operation")
            if not (dm := re.fullmatch(r"v(\d+)", dst)) or not 0 <= int(dm.group(1)) <= 255:
                raise ValueError(f"Invalid dot-accumulate destination {dst}")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if " " in src1:
                raise ValueError(f"Unsupported modifier on {op}: {src1}")
            if not (s1m := re.fullmatch(r"v(\d+)", src1)) or not 0 <= int(s1m.group(1)) <= 255:
                raise ValueError(f"{op} e32 src1 must be a VGPR, got {src1}")
            if re.fullmatch(r"-?(?:abs\([^)]+\)|\|[^|]+\|)|-[vs]\d+", src0):
                raise ValueError(f"Source modifiers are not allowed on {op} e32: {src0}")
            acc_val, _, _ = dpp_vgpr(dst, vector, sample_dest, allow_mods=False)
            u0 = dot_word(src0, scalar, vector, pending, sample_dest)
            u1 = dot_word(src1, scalar, vector, pending, sample_dest)
            helpers.add("dpp_dot4c_i32_i8")
            expr = f"asfloat(dpp_dot4c_i32_i8({u0}, {u1}, asuint({acc_val})))"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expr};")
        elif m := match(r"ds_swizzle_b32 (v\d+), (v\d+) offset:swizzle\(QUAD_PERM,([0-3](?:,[0-3]){3})\)"):
            dst, src, selectors = m.groups()
            value = vector.get(src)
            if (mask != "quad" or int(dst[1:]) > 255 or int(src[1:]) > 255
                    or src in sample_dest or dst in sample_dest
                    or not isinstance(value, str) or value not in quad_values):
                raise ValueError(f"ds_swizzle_b32 requires a whole-quad VGPR source and destination: {line}")
            perm = [int(selector) for selector in selectors.split(",")]
            bits = emit_quad_swizzle_u32(lines, i, value, perm)
            result = f"alu{i}"
            vector[dst] = result
            quad_values[result] = quad_values[value]
            lines.append(f"    precise float {result} = asfloat({bits});")
            ds_needs_wait = True
        elif m := match(r"v_cvt_f16_f32_dpp (v\d+), (.+)"):
            # Quad-local DPP16/DPP8 binary32-to-binary16 conversion under the shared low-16-only
            # contract (#732/#881): bits 15:0 are defined and tagged ("half16", alu); bits 31:16
            # are unspecified, so no previous high half is merged and whole-word / WORD_1 readers
            # reject the destination. Uses the existing narrow16 nearest-even helper and requires
            # explicit half_denorm="preserve" (with HW_REG_MODE RNE enforced above).
            dst, rest = m.groups()
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid f16 DPP operation")
            if half_denorm != HALF_DENORM_PRESERVE:
                raise ValueError("binary16 denormal mode unknown at entry")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            tokens, perm, is_dpp8 = parse_dpp(rest, 1)
            src0_val, abs0, neg0 = dpp_vgpr(tokens[0], vector, sample_dest, allow_mods=not is_dpp8)
            bits = emit_quad_swizzle_u32(lines, i, src0_val, perm)
            if abs0:
                bits = f"({bits} & 0x7fffffffu)"
            if neg0:
                bits = f"({bits} ^ 0x80000000u)"
            vector[dst] = ("half16", f"alu{i}")
            lines.append(f"    precise float alu{i} = asfloat(narrow16(asfloat({bits})));")
        elif m := match(rf"v_({'|'.join(DPP_INT32)})_dpp (v\d+), (.+)"):
            op, dst, rest = m.groups()
            arity, template, helper = DPP_INT32[op]
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid integer DPP operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            tokens, perm, _ = parse_dpp(rest, arity)
            src0_val, _, _ = dpp_vgpr(tokens[0], vector, sample_dest, allow_mods=False)
            s0_u32 = emit_quad_swizzle_u32(lines, i, src0_val, perm)
            args = [s0_u32]
            if arity == 2:
                src1_val, _, _ = dpp_vgpr(tokens[1], vector, sample_dest, allow_mods=False)
                args.append(f"asuint({src1_val})")
            if helper is not None:
                helpers.add(helper)
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({template.format(*args)});")
        elif m := match(rf"v_(mov_b32|cvt_f32_f16|cndmask_b32|(?:{'|'.join(DPP_ALU)})_f32)_dpp (v\d+), (.+)"):
            op, dst, rest = m.groups()
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid DPP operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if op in ("mov_b32", "cvt_f32_f16"):
                operand_count = 1
            elif op == "cndmask_b32":
                operand_count = 3
            else:
                base_op = op[:-4]
                operand_count = 2 if base_op == "fmac" else DPP_ALU[base_op][0]
            tokens, perm, is_dpp8 = parse_dpp(rest, operand_count)
            allow_mods = (not is_dpp8) and op not in ("mov_b32", "cndmask_b32")
            src0_val, abs0, neg0 = dpp_vgpr(tokens[0], vector, sample_dest, allow_mods=allow_mods)
            swz_bits = emit_quad_swizzle_u32(lines, i, src0_val, perm)
            if op == "mov_b32":
                expr = f"asfloat({swz_bits})"
            elif op == "cvt_f32_f16":
                expr = f"widen16({swz_bits})"
                if abs0:
                    expr = f"abs({expr})"
                if neg0:
                    expr = f"(-{expr})"
            elif op == "cndmask_b32":
                src1_val, _, _ = dpp_vgpr(tokens[1], vector, sample_dest, allow_mods=False)
                if tokens[2] not in ("vcc", "vcc_lo"):
                    raise ValueError(f"v_cndmask_b32_dpp requires vcc/vcc_lo, got {tokens[2]}")
                condition = scalar.get("vcc")
                if not isinstance(condition, tuple) or condition[0] != "condition" or condition[3] != 1:
                    raise ValueError("Select mask is not a tracked comparison")
                expr = f"{condition[1]} ? {src1_val} : asfloat({swz_bits})"
            else:
                base_op = op[:-4]
                s0 = f"asfloat({swz_bits})"
                if abs0:
                    s0 = f"abs({s0})"
                if neg0:
                    s0 = f"(-{s0})"
                args = [s0]
                if operand_count == 2:
                    src1_val, abs1, neg1 = dpp_vgpr(tokens[1], vector, sample_dest, allow_mods=allow_mods)
                    s1 = src1_val
                    if abs1:
                        s1 = f"abs({s1})"
                    if neg1:
                        s1 = f"(-{s1})"
                    args.append(s1)
                if base_op == "fmac":
                    acc_val, _, _ = dpp_vgpr(dst, vector, sample_dest, allow_mods=False)
                    args.append(acc_val)
                expr = DPP_ALU[base_op][1].format(*args)
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expr};")
        elif m := match(r"v_pk_fmac_f16(?:_e32)? (v\d+), ([^,\s]+), ([^,\s]+)"):
            # VOP2 packed binary16 fused multiply-accumulate (AMD RDNA 2 ISA §12.11, opcode 60 / 0x3c;
            # LLVM 15 VOP2Instructions.td: V_PK_FMAC_F16):
            # D.f16[0] = fma(S0.f16[0], S1.f16[0], D.f16[0]),
            # D.f16[1] = fma(S0.f16[1], S1.f16[1], D.f16[1]),
            # rounded once to binary16 RNE under the finite preserve/RNE profile.
            # Plain 32-bit VOP2 encoding only: src1 must be a VGPR, vdst is the implicit packed
            # accumulator and must already be initialized, all six operand halves must be statically
            # proven finite, both fused results must stay finite (overflow is refused), half_denorm
            # must be declared as "preserve", and no modifiers or _e64/DPP/SDWA spellings are accepted.
            dst, src0, src1 = m.groups()
            if mask != "entry":
                raise ValueError("Invalid packed operation")
            if half_denorm != HALF_DENORM_PRESERVE:
                raise ValueError("binary16 denormal mode unknown at entry")
            if not 0 <= int(dst[1:]) <= 255:
                raise ValueError(f"Register out of range: {dst}")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if not re.fullmatch(r"v\d+", src1):
                raise ValueError("v_pk_fmac_f16 src1 must be a VGPR")
            if dst not in vector:
                raise ValueError(f"Uninitialized packed accumulator {dst} at v_pk_fmac_f16")
            words, proven = zip(*(pk_fmac_f16_source(t, scalar, vector, pending, sample_dest, known_ssa_bits)
                                  for t in (src0, src1, dst)))
            lo_res = f16_pk_fmac_lane_result(proven[0] & 0xffff, proven[1] & 0xffff, proven[2] & 0xffff)
            hi_res = f16_pk_fmac_lane_result((proven[0] >> 16) & 0xffff, (proven[1] >> 16) & 0xffff, (proven[2] >> 16) & 0xffff)
            if lo_res is None or hi_res is None:
                raise ValueError("binary16 result overflows: v_pk_fmac_f16")
            word_vars = []
            for k, expr in enumerate(words):
                wvar = f"pk{i}_{k}"
                lines.append(f"    uint {wvar} = {expr};")
                word_vars.append(wvar)
            lines.append(f"    uint pk{i}_l0 = fma16_rne({word_vars[0]}, {word_vars[1]}, {word_vars[2]});")
            lines.append(f"    uint pk{i}_l1 = fma16_rne({word_vars[0]} >> 16, {word_vars[1]} >> 16, {word_vars[2]} >> 16);")
            helpers.add("fma16_rne")
            vector[dst] = f"alu{i}"
            known_ssa_bits[f"alu{i}"] = lo_res | (hi_res << 16)
            lines.append(f"    precise float alu{i} = asfloat(pk{i}_l0 | (pk{i}_l1 << 16));")
        elif m := match(r"v_pk_(add|mul|min|max|fma)_f16 (v\d+), (.+)"):
            op, dst, rest = m.groups()
            arity, template = VOP3P_F16[op]
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid packed operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            tokens, opts, clamp = parse_vop3p_f16(rest, arity)
            words = [vop3p_f16_word(t, scalar, vector, pending, sample_dest) for t in tokens]
            word_vars = []
            for k, expr in enumerate(words):
                wvar = f"pk{i}_{k}"
                lines.append(f"    uint {wvar} = {expr};")
                word_vars.append(wvar)
            packed_lanes = []
            for lane, sel_key, neg_key, default_sel in ((0, "op_sel", "neg_lo", 0), (1, "op_sel_hi", "neg_hi", 1)):
                sel = opts.get(sel_key, [default_sel] * arity)
                neg = opts.get(neg_key, [0] * arity)
                lane_args = []
                for wvar, high, negate in zip(word_vars, sel, neg):
                    val = f"widen16({wvar} >> 16)" if high else f"widen16({wvar})"
                    lane_args.append(f"(-{val})" if negate else val)
                expr = template.format(*lane_args)
                if clamp:
                    expr = f"saturate({expr})"
                lvar = f"pk{i}_l{lane}"
                lines.append(f"    precise float {lvar} = {expr};")
                packed_lanes.append(f"pack16_rne({lvar})")
            helpers.add("pack16_rne")
            if op in ("min", "max"):
                helpers.add(f"{op}16_num")
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({packed_lanes[0]} | ({packed_lanes[1]} << 16));")
        elif m := match(r"v_cvt_u32_f32_e32 (v\d+), ([vs]\d+|0x[0-9a-f]{1,8})"):
            dst, src = m.groups()
            if int(dst[1:]) > 255 or (src.startswith(("v", "s")) and
                    int(src[1:]) > (255 if src.startswith("v") else 105)):
                raise ValueError("Invalid unsigned conversion register")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if src.startswith("v") and src not in vector:
                raise ValueError(f"Unbound pixel input {src} at v_cvt_u32_f32_e32")
            quad = mask == "quad"
            operand = fp_operand(src, scalar, vector, pending, sample_dest,
                                 quad_values=quad_values if quad else None)
            if quad and not quad_values.get(vector.get(src), False):
                # Uniform inputs stay uniform. A varying conversion is not an affine sample coordinate.
                quad_values[f"alu{i}"] = False
            helpers.add("cvt_u32_f32")
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat(cvt_u32_f32(asuint({operand})));")
        elif m := match(r"v_cvt_f32_ubyte([0-3])(?:_e32|_e64)? (v\d+), ([vs]\d+|0x[0-9a-f]{1,8}|\d+)( clamp)?"):
            # Byte N of the source word as an unsigned integer. The source is read as bits,
            # so float modifiers do not apply and are rejected by the pattern.
            byte, dst, source, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if re.fullmatch(r"0x[0-9a-f]{1,8}|\d+", source):
                word = f"{int(source, 0) & 0xffffffff}u"
            else:
                word = f"asuint({fp_operand(source, scalar, vector, pending, sample_dest)})"
            expression = f"float(({word} >> {8 * int(byte)}u) & 0xffu)"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_fma_mix(_f32|lo_f16|hi_f16) (v\d+), (.+)"):
            kind, dst, rest = m.groups()
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid mixed-precision FMA")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            tokens, op_sel, op_sel_hi, clamp = parse_fma_mix(rest)
            args = [fma_mix_operand(t, f16, hi, scalar, vector, pending, sample_dest)
                    for t, f16, hi in zip(tokens, op_sel, op_sel_hi)]
            expr = f"mad({args[0]}, {args[1]}, {args[2]})"
            if clamp:
                expr = f"saturate({expr})"
            if kind == "_f32":
                vector[dst] = f"alu{i}"
                lines.append(f"    precise float alu{i} = {expr};")
            else:
                _, prev_word = fma_mix_reg(dst, scalar, vector, pending, sample_dest)
                helpers.add("pack16_rne")
                lines.append(f"    precise float mix{i} = {expr};")
                lines.append(f"    uint mix{i}_p = {prev_word};")
                if kind == "lo_f16":
                    packed = f"(mix{i}_p & 0xffff0000u) | pack16_rne(mix{i})"
                else:
                    packed = f"(mix{i}_p & 0x0000ffffu) | (pack16_rne(mix{i}) << 16)"
                vector[dst] = f"alu{i}"
                lines.append(f"    precise float alu{i} = asfloat({packed});")
        elif re.fullmatch(r"v_fma_f16(?:_e64)? .+", line):
            raise ValueError("Unverified v_fma_f16 binary16 FMA semantics")
        elif re.fullmatch(r"v_div_scale_f32(?:_e64)? .+", line):
            raise ValueError("Unverified v_div_scale_f32 prescaling and VCC semantics")
        elif m := match(r"v_div_fmas_f32(?:_e64)? (v\d+), (.+)"):
            dst, rest = m.groups()
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid div_fmas operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            tokens, clamp = parse_div_fmas(rest)
            condition = scalar.get("vcc")
            if condition is None:
                condition = scalar.get("vcc_lo")
            if condition is None or not isinstance(condition, tuple) or condition[0] != "condition":
                raise ValueError("Divide FMA requires a tracked VCC condition")
            values = [fp_operand(t, scalar, vector, pending, sample_dest) for t in tokens]
            helpers.add("div_fmas32")
            func = "div_fmas32_clamp" if clamp else "div_fmas32"
            expr = f"{func}({values[0]}, {values[1]}, {values[2]}, {condition[1]})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expr};")
        elif m := match(r"(v_dot2_f32_f16|v_dot2_i32_i16|v_dot2_u32_u16|v_dot4_i32_i8|v_dot4_u32_u8|v_dot8_i32_i4|v_dot8_u32_u4) (v\d+), (.+)"):
            op, dst, rest = m.groups()
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid dot-product operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            is_f16 = op == "v_dot2_f32_f16"
            is_dot2 = op.startswith("v_dot2_")
            tokens, op_sel, op_sel_hi, neg_lo, neg_hi, clamp = parse_dot(
                rest, allow_opsel=is_dot2, allow_neg=is_f16,
            )
            if is_f16:
                w0 = dot_word(tokens[0], scalar, vector, pending, sample_dest, allow_f16=True)
                w1 = dot_word(tokens[1], scalar, vector, pending, sample_dest, allow_f16=True)
                c_expr = dot_f32_accum(tokens[2], scalar, vector, pending, sample_dest)
                lines.append(f"    uint dot{i}_0 = {w0};")
                lines.append(f"    uint dot{i}_1 = {w1};")
                a0 = f"widen16(dot{i}_0 >> 16)" if op_sel[0] else f"widen16(dot{i}_0)"
                b0 = f"widen16(dot{i}_1 >> 16)" if op_sel[1] else f"widen16(dot{i}_1)"
                a1 = f"widen16(dot{i}_0 >> 16)" if op_sel_hi[0] else f"widen16(dot{i}_0)"
                b1 = f"widen16(dot{i}_1 >> 16)" if op_sel_hi[1] else f"widen16(dot{i}_1)"
                if neg_lo[0]: a0 = f"(-{a0})"
                if neg_lo[1]: b0 = f"(-{b0})"
                if neg_hi[0]: a1 = f"(-{a1})"
                if neg_hi[1]: b1 = f"(-{b1})"
                if neg_lo[2]: c_expr = f"(-{c_expr})"
                expr = f"(({a0} * {b0}) + ({a1} * {b1}) + {c_expr})"
                if clamp:
                    expr = f"saturate({expr})"
                vector[dst] = f"alu{i}"
                lines.append(f"    precise float alu{i} = {expr};")
            else:
                w0 = dot_word(tokens[0], scalar, vector, pending, sample_dest)
                w1 = dot_word(tokens[1], scalar, vector, pending, sample_dest)
                w2 = dot_word(tokens[2], scalar, vector, pending, sample_dest)
                signed = "_i32_" in op
                helpers.update(("dot_i64_add", "dot_i64_sat", op) if signed else ("dot_u64_add", "dot_u64_sat", op))
                sat = "true" if clamp else "false"
                if is_dot2:
                    lines.append(f"    uint dot{i}_0 = {w0};")
                    lines.append(f"    uint dot{i}_1 = {w1};")
                    a0 = f"(dot{i}_0 >> 16)" if op_sel[0] else f"dot{i}_0"
                    a1 = f"(dot{i}_0 >> 16)" if op_sel_hi[0] else f"dot{i}_0"
                    b0 = f"(dot{i}_1 >> 16)" if op_sel[1] else f"dot{i}_1"
                    b1 = f"(dot{i}_1 >> 16)" if op_sel_hi[1] else f"dot{i}_1"
                    call = f"{op}({a0}, {a1}, {b0}, {b1}, {w2}, {sat})"
                else:
                    call = f"{op}({w0}, {w1}, {w2}, {sat})"
                vector[dst] = f"alu{i}"
                lines.append(f"    precise float alu{i} = asfloat({call});")
        elif m := match(rf"v_pk_({'|'.join(VOP3P_INT16)}) (v\d+), (.+)"):
            op, dst, rest = m.groups()
            arity, allow_clamp = VOP3P_INT16[op]
            if mask != "entry" or not 0 <= int(dst[1:]) <= 255:
                raise ValueError("Invalid packed integer operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            tokens, opts, clamp = parse_vop3p_int16(rest, arity, allow_clamp=allow_clamp)
            words = [vop3p_int_word(t, scalar, vector, pending, sample_dest) for t in tokens]
            word_vars = []
            for k, expr in enumerate(words):
                wvar = f"pki{i}_{k}"
                lines.append(f"    uint {wvar} = {expr};")
                word_vars.append(wvar)
            lo_expr = pk_int16_lane_expr(op, word_vars, opts.get("op_sel", [0] * arity), clamp)
            hi_expr = pk_int16_lane_expr(op, word_vars, opts.get("op_sel_hi", [1] * arity), clamp)
            lines.append(f"    uint pki{i}_l0 = {lo_expr};")
            lines.append(f"    uint pki{i}_l1 = {hi_expr};")
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat(pki{i}_l0 | (pki{i}_l1 << 16));")
        elif m := match(rf"v_({'|'.join([*VOP3_INT16, *VOP3_INT16_TERNARY])})(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+)(?:, ([^,\s]+))?"):
            # Non-packed 16-bit integer VOP3 ops. The result is tracked as ("low16", alu): only bits 15:0
            # are defined. The HLSL variable holds the zero-extended result, but its upper half is an
            # implementation detail that no accepted reader observes (16-bit ops, 16-bit compares and
            # v_mov_b32_sdwa with WORD_0/BYTE_0/BYTE_1). Whether hardware keeps or zeroes the destination's
            # high half is not measured here, so the destination may hold anything and nothing is merged.
            # Modifiers, op_sel, clamp, DPP and SDWA never match the anchored operands.
            name, dst, *sources = m.groups()
            sources = [tok for tok in sources if tok is not None]
            if mask != "entry":
                raise ValueError("Invalid 16-bit integer operation")
            if len(sources) != (3 if name in VOP3_INT16_TERNARY else 2):
                raise ValueError(f"Wrong 16-bit integer operand count for v_{name}")
            if not 0 <= int(dst[1:]) <= 255:
                raise ValueError(f"Register out of range: {dst}")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            word_vars = []
            for k, tok in enumerate(sources):
                if rm := re.fullmatch(r"([vs])(\d+)", tok):
                    limit = 255 if rm.group(1) == "v" else 105
                    if not 0 <= int(rm.group(2)) <= limit:
                        raise ValueError(f"Register out of range: {tok}")
                    if tok not in (vector if rm.group(1) == "v" else scalar):
                        raise ValueError(f"Untracked 16-bit source: {tok}")
                int16_operand(tok, scalar, vector, pending, sample_dest, signed=False)
                if (src_name := low16_name(tok, vector)) is not None:
                    bits = f"asuint({src_name})"
                else:
                    bits = int_operand(tok, scalar, vector, pending, sample_dest, signed=False)
                lines.append(f"    uint i16s{i}_{k} = {bits};")
                word_vars.append(f"i16s{i}_{k}")
            expr = pk_int16_lane_expr({**VOP3_INT16, **VOP3_INT16_TERNARY}[name], word_vars, [0] * len(word_vars), False)
            vector[dst] = ("low16", f"alu{i}")
            lines.append(f"    precise float alu{i} = asfloat({expr});")
        elif m := match(rf"v_({'|'.join(VOP2_F16)})_f16(_e32|_e64)? (v\d+), ([^,\s]+), ([^,\s]+)"):
            # Plain non-fused binary16 VOP2 arithmetic. Both sources must have a statically known finite low half
            # and the result must not overflow, so the lowering needs no NaN, infinity or overflow rule. Each half
            # is widened exactly and one binary32 operation is rounded once to binary16 by narrow16 (11-bit
            # significands: the product is exact in binary32, and a sum rounded to 24 bits first is innocuous
            # because 24 >= 2 * 11 + 2). The result is ("half16", alu): only bits 15:0 are defined.
            name, encoding, dst, *tokens = m.groups()
            if mask != "entry":
                raise ValueError("Invalid binary16 arithmetic operation")
            if half_denorm != HALF_DENORM_PRESERVE:
                raise ValueError("binary16 denormal mode unknown at entry")
            if not 0 <= int(dst[1:]) <= 255:
                raise ValueError(f"Register out of range: {dst}")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if encoding != "_e64" and not re.fullmatch(r"v\d+", tokens[1]):
                raise ValueError("Binary16 e32 src1 must be a VGPR")
            words, proven = zip(*(half16_arith_source(tok, scalar, vector, pending, sample_dest, known_ssa_bits, known_half)
                                  for tok in tokens))
            result = f16_vop2_result(name, *proven)
            if result is None:
                raise ValueError(f"binary16 result overflows: v_{name}_f16")
            for k, word in enumerate(words):
                lines.append(f"    uint hf{i}_{k} = ({word}) & 0xffffu;")
            expression = VOP2_F16[name].format(f"widen16(hf{i}_0)", f"widen16(hf{i}_1)")
            lines.append(f"    precise float hs{i} = {expression};")
            lines.append(f"    precise float alu{i} = asfloat(narrow16(hs{i}));")
            vector[dst] = ("half16", f"alu{i}")
            known_half[f"alu{i}"] = result
        elif m := match(r"v_(fmac|ldexp)_f16(?:_e32)? (v\d+), ([^,\s]+), ([^,\s]+)"):
            # Plain e32 binary16 fused multiply-accumulate (D = S0 * S1 + D) and scaling by a power of two (D = S0 * 2^S1,
            # S1 a signed 16-bit integer), under the rules of the VOP2 arithmetic above: statically proven finite
            # operands, no overflow, the declared entry profile, no modifier, clamp or omod (the _e64, DPP and SDWA
            # spellings fall through to the generic refusal). The fused form reads the accumulator as a third proven
            # operand and rounds once in integer arithmetic (fma16_rne). The scaling form needs a statically known
            # exponent: the binary32 product of a widened half and a power of two is exact (the multiplier and the
            # product are normals), and narrow16 rounds it once. Only bits 15:0 of S1 are read. The result is
            # ("half16", alu): only bits 15:0 are defined.
            name, dst, src0, src1 = m.groups()
            if mask != "entry":
                raise ValueError("Invalid binary16 arithmetic operation")
            if half_denorm != HALF_DENORM_PRESERVE:
                raise ValueError("binary16 denormal mode unknown at entry")
            if not 0 <= int(dst[1:]) <= 255:
                raise ValueError(f"Register out of range: {dst}")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if not re.fullmatch(r"v\d+", src1):
                raise ValueError("Binary16 e32 src1 must be a VGPR")
            if name == "fmac":
                words, proven = zip(*(half16_arith_source(tok, scalar, vector, pending, sample_dest, known_ssa_bits, known_half)
                                      for tok in (src0, src1, dst)))
                result = f16_pk_fmac_lane_result(*proven)
                if result is None:
                    raise ValueError("binary16 result overflows: v_fmac_f16")
                for k, word in enumerate(words):
                    lines.append(f"    uint hf{i}_{k} = ({word}) & 0xffffu;")
                lines.append(f"    uint hm{i} = fma16_rne(hf{i}_0, hf{i}_1, hf{i}_2);")
                helpers.add("fma16_rne")
                lines.append(f"    precise float alu{i} = asfloat(hm{i});")
            else:
                word, proven = half16_arith_source(src0, scalar, vector, pending, sample_dest, known_ssa_bits, known_half)
                if not 0 <= int(src1[1:]) <= 255:
                    raise ValueError(f"Register out of range: {src1}")
                if src1 not in vector:
                    raise ValueError(f"Untracked 16-bit source: {src1}")
                int16_operand(src1, scalar, vector, pending, sample_dest, signed=True)
                known = int16_known_value(src1, scalar, vector, known_ssa_bits)
                if known is None:
                    raise ValueError(f"binary16 ldexp exponent lacks a proof: {src1}")
                exponent = known - 0x10000 if known & 0x8000 else known
                if abs(exponent) > LDEXP_F16_EXPONENT_LIMIT:
                    raise ValueError(f"binary16 ldexp exponent out of range: {exponent}")
                result = f16_ldexp_result(proven, exponent)
                if result is None:
                    raise ValueError("binary16 result overflows: v_ldexp_f16")
                lines.append(f"    uint hf{i}_0 = ({word}) & 0xffffu;")
                lines.append(f"    precise float hs{i} = widen16(hf{i}_0) * asfloat({(127 + exponent) << 23}u);")
                lines.append(f"    precise float alu{i} = asfloat(narrow16(hs{i}));")
            vector[dst] = ("half16", f"alu{i}")
            known_half[f"alu{i}"] = result
        elif m := match(rf"v_({'|'.join(VOP1_F16_ROUND)})_f16(_e32|_e64)? (v\d+), ([^,\s]+)"):
            # Plain binary16 VOP1 rounding under the rules of the VOP2 arithmetic above: a statically proven finite
            # source, the declared entry profile, no modifier, clamp or omod (those fall through to the generic
            # refusal). The half is widened exactly, rounded to an integer in binary32 and narrowed back, which is
            # exact because the integer is representable in binary16. The result is ("half16", alu).
            name, encoding, dst, token = m.groups()
            if mask != "entry":
                raise ValueError("Invalid binary16 rounding operation")
            if half_denorm != HALF_DENORM_PRESERVE:
                raise ValueError("binary16 denormal mode unknown at entry")
            if not 0 <= int(dst[1:]) <= 255:
                raise ValueError(f"Register out of range: {dst}")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            word, proven = half16_arith_source(token, scalar, vector, pending, sample_dest, known_ssa_bits, known_half)
            result = f16_round_result(name, proven)
            lines.append(f"    uint hf{i}_0 = ({word}) & 0xffffu;")
            lines.append(f"    precise float hs{i} = {VOP1_F16_ROUND[name].format(f'widen16(hf{i}_0)')};")
            lines.append(f"    precise float alu{i} = asfloat(narrow16(hs{i}));")
            vector[dst] = ("half16", f"alu{i}")
            known_half[f"alu{i}"] = result
        elif m := match(r"v_cvt_f16_(i16|u16)(_e32|_e64)? (v\d+), ([^,\s]+)"):
            # Integer to binary16 (issue #839): LLVM 15.0.7 VOP1Instructions.td L432-433 selects sint_to_fp and uint_to_fp,
            # round to nearest even. The source is the low 16 bits through the audited reader int16_operand (sign-
            # extended for i16, zero-extended for u16, bits 31:16 never read). |x| <= 65535 < 2^24 converts to binary32
            # exactly, and narrow16 rounds once, so the result is the exact nearest-even binary16. The result is
            # ("half16", alu) under the rules of the VOP2 arithmetic above (declared entry profile, audited readers).
            # Every i16 value is finite, so a runtime i16 source needs no proof, but its result carries no known value
            # and cannot feed the binary16 arithmetic. A u16 source is accepted only when statically proven below 65520
            # (65520 and above ties up to infinity); a runtime u16 source is refused. Modifiers, clamp and omod never
            # match the anchored operands.
            kind, encoding, dst, token = m.groups()
            if mask != "entry":
                raise ValueError("Invalid binary16 conversion operation")
            if half_denorm != HALF_DENORM_PRESERVE:
                raise ValueError("binary16 denormal mode unknown at entry")
            if not 0 <= int(dst[1:]) <= 255:
                raise ValueError(f"Register out of range: {dst}")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            signed = kind == "i16"
            if rm := re.fullmatch(r"([vs])(\d+)", token):
                if not 0 <= int(rm.group(2)) <= (255 if rm.group(1) == "v" else 105):
                    raise ValueError(f"Register out of range: {token}")
                if token not in (vector if rm.group(1) == "v" else scalar):
                    raise ValueError(f"Untracked 16-bit source: {token}")
            word = int16_operand(token, scalar, vector, pending, sample_dest, signed=signed)
            known = int16_known_value(token, scalar, vector, known_ssa_bits)
            result = None
            if known is not None:
                result = f16_cvt_int_result(signed, known)
                if result is None:
                    raise ValueError(f"binary16 result overflows: v_cvt_f16_{kind}")
            elif not signed:
                raise ValueError(f"binary16 conversion source lacks a range proof: {token}")
            lines.append(f"    {'int' if signed else 'uint'} cv{i}_0 = {word};")
            lines.append(f"    precise float hs{i} = float(cv{i}_0);")
            lines.append(f"    precise float alu{i} = asfloat(narrow16(hs{i}));")
            vector[dst] = ("half16", f"alu{i}")
            if result is not None:
                known_half[f"alu{i}"] = result
        elif m := match(r"v_cvt_(i16|u16)_f16(_e32|_e64)? (v\d+), ([^,\s]+)"):
            # Binary16 to integer (issue #839): LLVM 15.0.7 VOP1Instructions.td L436-437 selects fp_to_sint and fp_to_uint,
            # and AMD RDNA 2 section 12.8 (VOP1 entries 82 and 83) specifies truncation toward zero. The source must be a
            # statically proven finite low half under the declared entry profile (half16_arith_source), and the truncated
            # integer must lie in the destination range (f16_to_int_result), so the lowering needs no NaN, infinity or
            # saturation rule. The half is widened exactly and truncated in binary32, which is exact. The result is
            # ("low16", alu): bits 15:0 are the two's-complement integer, bits 31:16 are unspecified, so the audited 16-bit
            # integer readers read it and the binary16 readers refuse it. Modifiers, clamp and omod never match the
            # anchored operands.
            kind, encoding, dst, token = m.groups()
            if mask != "entry":
                raise ValueError("Invalid binary16 to integer conversion operation")
            if half_denorm != HALF_DENORM_PRESERVE:
                raise ValueError("binary16 denormal mode unknown at entry")
            if not 0 <= int(dst[1:]) <= 255:
                raise ValueError(f"Register out of range: {dst}")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            word, proven = half16_arith_source(token, scalar, vector, pending, sample_dest, known_ssa_bits, known_half)
            if f16_to_int_result(kind == "i16", proven) is None:
                raise ValueError(f"binary16 value out of range: v_cvt_{kind}_f16")
            lines.append(f"    uint hf{i}_0 = ({word}) & 0xffffu;")
            lines.append(f"    precise float hs{i} = widen16(hf{i}_0);")
            lines.append(f"    int cv{i}_0 = int(trunc(hs{i}));")
            lines.append(f"    precise float alu{i} = asfloat(asuint(cv{i}_0) & 0xffffu);")
            vector[dst] = ("low16", f"alu{i}")
        elif m := match(r"v_cvt_off_f32_i4(?:_e32|_e64)? (v\d+), ([vs]\d+|0x[0-9a-f]{1,8}|\d+)( clamp)?"):
            # Bits 3:0 of the source as a signed nibble in units of 1/16, so 0x7 gives 0.4375
            # and 0x8 gives -0.5. The source is read as bits, so float modifiers do not apply.
            dst, source, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if re.fullmatch(r"0x[0-9a-f]{1,8}|\d+", source):
                word = f"{int(source, 0) & 0xffffffff}u"
            else:
                word = f"asuint({fp_operand(source, scalar, vector, pending, sample_dest)})"
            expression = f"(float(asint({word} << 28u) >> 28) * 0.0625f)"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_cvt_f16_f32(?:_e32|_e64)? (v\d+), ([^,\s]+)"):
            # GFX10 16-bit results replace only the low half; the high half of the destination is kept
            # (LLVM GCNSubtarget::zeroesHigh16BitsOfDest). A destination with no tracked value contributes zero.
            dst, src = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            old = vector.get(dst)
            if old is not None and not (isinstance(old, str) and old.startswith(("sample", "alu", "params"))):
                raise ValueError("Unsupported conversion destination")
            # fp_operand reads modifiers and inline constants, so -1 stays the bit pattern 0xffffffff.
            value = fp_operand(src, scalar, vector, pending, sample_dest)
            high = f"(asuint({old}) & 0xffff0000u)" if old is not None else "0u"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({high} | narrow16({value}));")
        elif m := match(r"v_cvt_f32_(u32|i32)_e32 (v\d+), ([vs]\d+|0x[0-9a-f]{1,8}|-?\d+)"):
            # Integer to binary32, plain e32 only: the e32 encoding carries no modifiers, so clamp
            # or omod suffixes and DPP or SDWA variants must not slip through the anchored operand
            # list; the e64 branch below carries clamp.
            op, dst, src = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            source = fp_operand(src, scalar, vector, pending, sample_dest)
            expression = f"float(asuint({source}))" if op == "u32" else f"float(asint({source}))"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_cvt_f32_(u32|i32)_e64 (v\d+), ([vs]\d+|0x[0-9a-f]{1,8}|-?\d+)( clamp)?"):
            # The e64 encoding of the same conversion adds clamp. omod stays refused in every
            # spelling: the LLVM 15 assembler rejects it on these forms, so it cannot round-trip;
            # abs/neg on the integer source are refused by the assembler too, and DPP or SDWA
            # variants must not slip through the anchored operand list.
            op, dst, src, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            source = fp_operand(src, scalar, vector, pending, sample_dest)
            expression = f"float(asuint({source}))" if op == "u32" else f"float(asint({source}))"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_cvt_(i32|flr_i32|rpi_i32)_f32_e32 (v\d+), ([vs]\d+|0x[0-9a-f]{1,8})"):
            kind, dst, src = m.groups()
            if int(dst[1:]) > 255 or (src.startswith(("v", "s")) and
                    int(src[1:]) > (255 if src.startswith("v") else 105)):
                raise ValueError("Invalid signed conversion register")
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if src.startswith("v") and src not in vector:
                raise ValueError(f"Unbound pixel input {src} at v_cvt_{kind}_f32_e32")
            operand = fp_operand(src, scalar, vector, pending, sample_dest)
            helper = f"cvt_{kind}_f32"
            helpers.add(helper)
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({helper}(asuint({operand})));")
        elif (m := match(r"v_cvt_(u32|i32|flr_i32|rpi_i32)_f32_e64 (v\d+), ([^,\s]+)")) and (
                parsed := parse_cvt_f32_e64_source(m.group(3))):
            # VOP3 float-to-int (truncate, floor, round-to-+inf) with optional bitwise source
            # abs/neg modifiers applied on the raw IEEE-754 word before conversion. Every kind accepts
            # arbitrary runtime inputs: the helpers define NaN, infinities and out-of-range values (issue
            # #1772 for flr/rpi). clamp, omod, decimal/float literals, DPP and SDWA remain rejected.
            kind, dst, _ = m.groups()
            base, has_abs, has_neg = parsed
            if int(dst[1:]) > 255 or (base.startswith(("v", "s")) and
                    int(base[1:]) > (255 if base.startswith("v") else 105)):
                raise ValueError(f"Invalid {'unsigned' if kind == 'u32' else 'signed'} conversion register")
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            if base.startswith("v") and base not in vector:
                raise ValueError(f"Unbound pixel input {base} at v_cvt_{kind}_f32_e64")
            operand = fp_operand(base, scalar, vector, pending, sample_dest)
            bits = f"asuint({operand})"
            if has_abs:
                bits = f"({bits} & 0x7fffffffu)"
            if has_neg:
                bits = f"({bits} ^ 0x80000000u)"
            helper = f"cvt_{kind}_f32"
            helpers.add(helper)
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({helper}({bits}));")
        elif m := match(r"v_cvt_pkrtz_f16_f32_e32 (v\d+), (v\d+), (v\d+)"):
            dst, lo, hi = m.groups()
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            pair = (vector[lo], vector[hi])
            if mask != "entry" or lo in sample_dest or hi in sample_dest or not all(isinstance(v, str) and v.startswith(("sample", "alu")) for v in pair):
                raise ValueError("Unsupported pack operand")
            vector[dst] = pair
        elif m := match(r"exp mrt0,? (v\d+|off), \1, (v\d+|off), \2 done compr vm"):
            if integer_export:
                raise ValueError("Integer export requires the uncompressed export form")
            low, high = m.groups()
            if low == "off" and high == "off":
                raise ValueError("Unsupported compressed export: enable mask must select whole packed pairs")
            if low == "off" and not return_write_mask:
                raise ValueError("High-pair compressed export requires an explicit RT0 write mask")
            regs = [reg for reg in (low, high) if reg != "off"]
            pairs = [vector.get(reg) for reg in regs]
            if (mask != "entry" or exported or any(reg in sample_dest for reg in regs)
                    or not all(isinstance(pair, tuple) and len(pair) == 2
                               and all(isinstance(value, str) and value.startswith(("sample", "alu"))
                                       for value in pair) for pair in pairs)):
                raise ValueError("Unsupported export")
            args = [f"export16({value})" for pair in pairs for value in pair]
            if low == "off":
                channel_mask = 0xC
                args[:0] = ["0.0f", "0.0f"]
            elif high == "off":
                channel_mask = 0x3
                if return_write_mask:
                    args.extend(["0.0f", "0.0f"])
            components = 4 if attribute_input else texcoord_components
            inputs = f"float{components} uv : TEXCOORD0"
            if not bindings and not interpolated:
                inputs = ""
            lines[entry_line] = f"float{len(args)} main({inputs}) : SV_Target0 {{"
            lines.append(f"    return float{len(args)}({', '.join(args)});")
            exported = True
        elif match(r"exp mrt0,? (?:v\d+|off), (?:v\d+|off), (?:v\d+|off), (?:v\d+|off) done compr vm"):
            raise ValueError("Unsupported compressed export: enable mask must select whole packed pairs")
        elif m := match(r"exp mrt0,? (v\d+|off), (v\d+|off), (v\d+|off), (v\d+|off) done vm"):
            channels = m.groups()
            export_regs = [reg for reg in channels if reg != "off"]
            values = [vector.get(reg) for reg in export_regs]
            if (mask != "entry" or exported or not export_regs or len(set(export_regs)) != len(export_regs)
                    or any(reg in sample_dest for reg in export_regs)
                    or not all(isinstance(v, str) and v.startswith(("sample", "alu")) for v in values)):
                raise ValueError("Unsupported export")
            channel_mask = sum(1 << index for index, reg in enumerate(channels) if reg != "off")
            if channel_mask != 0xF and not return_write_mask:
                raise ValueError("Partial uncompressed export requires an explicit RT0 write mask")
            args = [f"asuint({v})" for v in values] if integer_export else values
            padding = "0u" if integer_export else "0.0f"
            for index, reg in enumerate(channels):
                if reg == "off":
                    args.insert(index, padding)
            input_type = f"float{4 if attribute_input else texcoord_components}"
            lines[entry_line] = f"{result_type} main({input_type} uv : TEXCOORD0) : SV_Target0 {{"
            lines.append(f"    return {result_type}({', '.join(args)});")
            exported = True
        elif line == "s_endpgm" and exported:
            ended = True
        else:
            raise ValueError(f"Unsupported instruction {i}: {line}")
        if region is not None and region["else"] is not None and region["else_undefined"].intersection(vector.reads):
            raise ValueError(f"Else arm reads a register defined only in the then arm {i}: {line}")
        if rstate is not None:
            (old_scalar, old_vector, old_scc, old_pending, old_sample_dest, old_exported,
             old_ended, old_mask, old_attribute, old_interpolated, old_quad, old_samples, scalar_alu) = rstate
            writes = {k for k in set(vector) | set(old_vector)
                      if old_vector.get(k, MISSING) != dict.get(vector, k, MISSING)}
            if isinstance(scalar_alu, set):
                # A scalar load may only add its own destinations: they become outstanding and change nothing else.
                scalar_writes = {k for k in set(scalar) | set(old_scalar)
                                 if old_scalar.get(k, MISSING) != dict.get(scalar, k, MISSING)}
                if (not scalar_writes.issubset(scalar_alu) or writes or scc != old_scc
                        or pending != old_pending | scalar_alu or sample_dest != old_sample_dest
                        or exported != old_exported or ended != old_ended or mask != old_mask
                        or attribute_input != old_attribute or interpolated != old_interpolated
                        or quad_values != old_quad or samples != old_samples):
                    raise ValueError(f"Unsupported masked-region scalar load {i}: {line}")
                if region["skip"] is not None:
                    region["scalar_written"].update(scalar_alu)
                else:
                    # No wave can skip the region, so the load defines these registers on every wave and
                    # supersedes any earlier conditional write of them.
                    region["scalar_written"].difference_update(scalar_alu)
                    scalar.conditional.difference_update(scalar_alu)
            elif scalar_alu:
                destination = REGION_SALU_DEST.match(line)
                scalar_writes = {k for k in set(scalar) | set(old_scalar)
                                 if old_scalar.get(k, MISSING) != dict.get(scalar, k, MISSING)}
                expected_scalar_writes = {destination[1]} if destination else set()
                writes_scc = scc != old_scc
                expected_scc_write = line.startswith(("s_add_i32 ", "s_cmp_"))
                if (not scalar_writes.issubset(expected_scalar_writes)
                        or (scalar != old_scalar and scalar_writes != expected_scalar_writes)
                        or writes_scc != expected_scc_write or writes
                        or pending != old_pending or sample_dest != old_sample_dest
                        or exported != old_exported or ended != old_ended or mask != old_mask
                        or attribute_input != old_attribute or interpolated != old_interpolated
                        or quad_values != old_quad or samples != old_samples):
                    raise ValueError(f"Unsupported masked-region scalar ALU operation {i}: {line}")
                region["scalar_written"].update(expected_scalar_writes)
                region["scc_written"] |= writes_scc
            else:
                if (scalar != old_scalar or scc != old_scc or pending != old_pending
                        or sample_dest != old_sample_dest or exported != old_exported
                        or ended != old_ended or mask != old_mask
                        or attribute_input != old_attribute or interpolated != old_interpolated
                        or quad_values != old_quad or samples != old_samples or not writes
                        or any(not isinstance(dict.get(vector, k), str) for k in writes)):
                    raise ValueError(f"Unsupported masked-region operation {i}: {line}")
                arm = region["written"] if region["else"] is None else region["else_written"]
                for k in writes:
                    arm.setdefault(k, old_vector.get(k, MISSING))
                region["else_undefined"].difference_update(writes)
        if conditional.intersection(vector.reads):
            raise ValueError(f"Read of a register defined only on the masked path {i}: {line}")
        if scalar_conditional.intersection(scalar.reads):
            raise ValueError(f"Read of a register defined only on the masked path {i}: {line}")
    # Reads after the last instruction are not operand reads: a missing key there stays a KeyError.
    scalar.site = vector.site = None
    if region is not None:
        raise ValueError("Program ends inside a masked region")
    if gather_mips is not None and sample_kind != "gather":
        raise ValueError("Expected one gather for the declared view")
    if not ended or sampled_textures != set(bindings.values()):
        raise ValueError("Unexpected sample count or missing color export")
    if helpers:
        defs = [body for name, body in SALU_HELPERS.items() if name in helpers]
        if "div_fmas32" in helpers:
            defs.append(DIV_FMAS_HELPERS)
        if helpers & {"cvt_u32_f32", "cvt_i32_f32"}:
            defs.append((Path(__file__).resolve().parents[1] / "src/ffx_float_to_int.hlsli").read_text())
        lines[:0] = defs
    if title_loads:
        lookup = (Path(__file__).resolve().parents[1] / "src/title_va_lookup.hlsli").read_text()
        lines[:0] = [lookup, TITLE_MEMORY.format(slots=TITLE_ALIAS_SLOTS, count=title_ranges, miss=TITLE_MISS)]
    source = "\n".join([*lines, "}", ""])
    return (source, channel_mask) if return_write_mask else source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("record")
    parser.add_argument("--container-sha256", help="SHA-256 of the full decoded DXBC container to select by name")
    parser.add_argument("--llvm", required=True, help="LLVM C library with AMDGPU support")
    parser.add_argument("--cpu", choices=("gfx1013", "gfx1030"), default="gfx1013",
                        help="Source instruction set (gfx1030 uses the wave64 pixel profile)")
    parser.add_argument("--gather-mips", type=int, help="Declare the matching native and desktop 2D gather view mip count")
    parser.add_argument("--texture-sgpr", type=int, required=True, help="Entry register for the low descriptor-table address")
    parser.add_argument("--interp-sgpr", type=int, required=True, help="Entry register for the interpolation base")
    profile = parser.add_mutually_exclusive_group(required=True)
    profile.add_argument("--no-texture", action="store_true", help="Require zero texture samples")
    profile.add_argument("--sampler-words", nargs=4, type=lambda s: int(s, 0),
                        help="Four descriptor words to bind to the supplied desktop sampler at s0")
    parser.add_argument("--output", type=Path, required=True, help="Destination .hlsl in a local output directory")
    parser.add_argument("--constant-descriptor", type=lambda s: int(s, 0),
                        help="Byte offset of a descriptor mapped to the 256-byte desktop buffer b0")
    parser.add_argument("--texture-offset", type=lambda s: int(s, 0), default=0,
                        help="Byte offset of the t0 descriptor in the texture descriptor table")
    parser.add_argument("--extra-constant", type=lambda s: int(s, 0), nargs=2, action="append", default=[],
                        metavar=("SGPR", "OFFSET"),
                        help="Entry register and byte offset of a further descriptor; repeat for b1, b2 and onward")
    parser.add_argument("--pointer-constant", type=lambda s: int(s, 0), nargs=4, action="append", default=[],
                        metavar=("SGPR", "POINTER_OFFSET", "DWORDS", "OFFSET"),
                        help="Entry register, byte offset and width (1 or 2 dwords) of a table pointer, then the byte"
                             " offset of a descriptor in the table it addresses; maps after the --extra-constant slots")
    parser.add_argument("--half-denorm", choices=[HALF_DENORM_PRESERVE],
                        help="Declare the binary16 denormal state at shader entry; the plain binary16 VOP2 forms need it")
    parser.add_argument("--second-texture-offset", type=lambda s: int(s, 0), help="Byte offset of the t1 descriptor for a two-sample shader")
    parser.add_argument("--rt0-write-mask", action="store_true",
                        help="Emit the uncompressed RT0 mask for the caller to apply to the pipeline")
    args = parser.parse_args()
    dest = args.output.resolve()
    if dest.suffix.lower() != ".hlsl" or dest == args.archive.resolve():
        parser.error("Choose an HLSL destination distinct from the input")
    try:
        cpu = args.cpu.encode()
        features = b"+wavefrontsize64,-wavefrontsize32" if cpu == b"gfx1030" else b""
        blob, code = native_program(args.archive, args.record, container_sha256=args.container_sha256,
                                    llvm=args.llvm, cpu=cpu, features=features)
        instructions = disassemble(code, args.llvm, offsets=True, cpu=cpu, features=features)
        if args.rt0_write_mask and any(line.startswith("exp ") and "compr" in line.split()
                                       for _, line in instructions):
            raise ValueError("--rt0-write-mask only supports uncompressed exports")
        result = lower(instructions, args.texture_sgpr, args.interp_sgpr, args.sampler_words,
                       args.constant_descriptor, texture_offset=args.texture_offset,
                       second_texture_offset=args.second_texture_offset,
                       extra_constants=[tuple(entry) for entry in args.extra_constant],
                       pointer_constants=[tuple(entry) for entry in args.pointer_constant],
                       half_denorm=args.half_denorm, return_write_mask=args.rt0_write_mask,
                       cpu=args.cpu, gather_mips=args.gather_mips)
        source, write_mask = result if args.rt0_write_mask else (result, None)
    except (ValueError, KeyError, struct.error, OSError, AttributeError, zlib.error) as exc:
        parser.exit(1, f"Translation failed: {exc}\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, mode="wb") as f:
        f.write(source.encode("utf-8"))
    Path(f.name).replace(dest)
    summary = {"record": args.record, "container_sha256": hashlib.sha256(blob).hexdigest(),
               "native_sha256": hashlib.sha256(code).hexdigest(), "instructions": len(instructions),
               "hlsl_sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}
    if write_mask is not None:
        summary["rt0_write_mask"] = write_mask
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
