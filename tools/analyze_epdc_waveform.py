#!/usr/bin/env python3
"""Analyze the headerless i.MX7 EPDC waveform blob used by KOA3.

The active KOA3 blob uses 64-bit relative offsets, 32 source states, 32
destination states and two 4-bit actions per byte: 512 bytes per phase.
The 5-bit WBF parser and the active-WRF/DMA byte-for-byte comparison support
low-nibble-first packing.  The tool still requires an explicit --nibble-order
for auditability and keeps high-first as a diagnostic comparison path.
"""
import argparse
import csv
import hashlib
import struct
from pathlib import Path

STATES = 32
PHASE_BYTES = STATES * STATES // 2


def u64(blob, offset):
    if offset < 0 or offset + 8 > len(blob):
        raise ValueError("uint64 offset out of range: 0x%x" % offset)
    return struct.unpack_from("<Q", blob, offset)[0]


def infer_layout(blob):
    top_bytes = u64(blob, 0)
    if not top_bytes or top_bytes % 8 or top_bytes > 8192:
        raise ValueError("invalid top table size: 0x%x" % top_bytes)
    top_slots = top_bytes // 8
    top = [u64(blob, index * 8) for index in range(top_slots)]
    if top_slots < 2:
        raise ValueError("top table has fewer than two pointers")
    temp_count = (top[1] - top[0]) // 8
    if temp_count <= 0 or temp_count > 256:
        raise ValueError("invalid temperature count: %d" % temp_count)
    mode_count = 0
    for index, offset in enumerate(top):
        if offset != top[0] + index * temp_count * 8:
            break
        mode_count += 1
    if not mode_count:
        raise ValueError("no standard mode tables found")

    modes = []
    for mode in range(mode_count):
        blocks = [u64(blob, top[mode] + temp * 8) for temp in range(temp_count)]
        frames = [u64(blob, block) for block in blocks]
        for temp, (block, count) in enumerate(zip(blocks, frames)):
            if block < top_bytes or block + 8 > len(blob):
                raise ValueError("mode %d temp %d block out of range: 0x%x" %
                                 (mode, temp, block))
            if count <= 0 or count > 1024:
                raise ValueError("mode %d temp %d frame count invalid: %d" %
                                 (mode, temp, count))
            end = block + 8 + count * PHASE_BYTES
            if end > len(blob):
                raise ValueError("mode %d temp %d payload out of range: 0x%x" %
                                 (mode, temp, end))
        modes.append((blocks, frames))
    return {
        "top_bytes": top_bytes,
        "top": top,
        "mode_count": mode_count,
        "temp_count": temp_count,
        "advanced": top[mode_count:],
        "modes": modes,
    }


def unpack_phase(raw, low_first):
    if len(raw) != PHASE_BYTES:
        raise ValueError("phase must be %d bytes" % PHASE_BYTES)
    actions = []
    for byte in raw:
        if low_first:
            actions.extend((byte & 0x0F, byte >> 4))
        else:
            actions.extend((byte >> 4, byte & 0x0F))
    # Wire/file order follows the public WBF dumper: destination outer,
    # source inner. Return an ergonomic [source][destination] matrix.
    return [[actions[dst * STATES + src] for dst in range(STATES)]
            for src in range(STATES)]


def pack_phase(matrix, low_first):
    actions = [matrix[src][dst] for dst in range(STATES) for src in range(STATES)]
    output = bytearray(PHASE_BYTES)
    for index in range(0, len(actions), 2):
        first, second = actions[index], actions[index + 1]
        output[index // 2] = ((second << 4) | first) if low_first else ((first << 4) | second)
    return bytes(output)


def read_phases(blob, block, count, low_first):
    phases = []
    start = block + 8
    for frame in range(count):
        raw = blob[start + frame * PHASE_BYTES:start + (frame + 1) * PHASE_BYTES]
        matrix = unpack_phase(raw, low_first)
        if pack_phase(matrix, low_first) != raw:
            raise AssertionError("phase round-trip failed at frame %d" % frame)
        phases.append(matrix)
    return phases


def write_csv(path, phases):
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["source", "destination"] +
                        ["phase_%d" % index for index in range(len(phases))])
        for src in range(STATES):
            for dst in range(STATES):
                writer.writerow([src, dst] + [phase[src][dst] for phase in phases])


def summarize(blob, layout):
    names = ["INIT", "DU", "GC16", "GC4", "A2/GLR16", "GL16/GLD16"]
    print("size=%d sha256=%s" % (len(blob), hashlib.sha256(blob).hexdigest()))
    print("top=%d bytes, slots=%d, standard_modes=%d, temperatures=%d" %
          (layout["top_bytes"], len(layout["top"]), layout["mode_count"],
           layout["temp_count"]))
    print("advanced pointers: %s" %
          " ".join("0x%x" % value for value in layout["advanced"]))
    for mode, (_blocks, frames) in enumerate(layout["modes"]):
        name = names[mode] if mode < len(names) else "?"
        print("mode %2d %-12s %s" %
              (mode, name, " ".join("%3d" % count for count in frames)))

    unique = {}
    for blocks, frames in layout["modes"]:
        for block, count in zip(blocks, frames):
            if block in unique and unique[block] != count:
                raise ValueError("shared block 0x%x has conflicting frame counts" % block)
            unique[block] = count
    ordered = sorted(unique)
    exact = 0
    mismatches = []
    for index, block in enumerate(ordered[:-1]):
        actual = ordered[index + 1] - block
        expected = 8 + unique[block] * PHASE_BYTES
        if actual == expected:
            exact += 1
        else:
            mismatches.append((block, actual, expected))
    print("unique standard blocks=%d; adjacent exact 8+frames*512=%d/%d" %
          (len(ordered), exact, max(0, len(ordered) - 1)))
    for block, actual, expected in mismatches[:8]:
        print("  mismatch block=0x%x span=%d expected=%d" % (block, actual, expected))


def transition_sequence(phases, src, dst):
    return "".join("%x" % phase[src][dst] for phase in phases)


def hexdump(blob, offset, length=96):
    end = min(len(blob), offset + length)
    for row in range(offset, end, 16):
        chunk = blob[row:min(row + 16, end)]
        hex_part = " ".join("%02x" % byte for byte in chunk)
        ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
        print("%08x  %-47s  %s" % (row, hex_part, ascii_part))


def summarize_advanced(blob, layout, source_size=None):
    advanced = layout["advanced"]
    if len(advanced) < 4:
        print("advanced layout has fewer than four pointers")
        return
    vcd_start, acd_start, acd_source_base, xswi_start = advanced[:4]
    vcd = blob[vcd_start:acd_start]
    records = [vcd[index:index + 16] for index in range(0, len(vcd), 16)]
    valid_records = sum(len(record) == 16 and
                        (sum(record[:15]) & 0xFF) == record[15]
                        for record in records)
    print("VCD 0x%x..0x%x: %d bytes, %d x 16-byte records, checksums %d/%d" %
          (vcd_start, acd_start, len(vcd), len(records), valid_records, len(records)))
    print("VCD unique records=%d (expected mode*temp=%d)" %
          (len(set(records)), layout["mode_count"] * layout["temp_count"]))
    record_counts = {}
    for record in records:
        record_counts[record] = record_counts.get(record, 0) + 1
    for record, count in sorted(record_counts.items(), key=lambda item: (-item[1], item[0])):
        modes = sorted({index // layout["temp_count"]
                        for index, candidate in enumerate(records) if candidate == record})
        version = struct.unpack_from("<H", record)[0]
        print("  VCD x%-3d modes=%s version=%d %s" %
              (count, ",".join(str(mode) for mode in modes), version, record.hex(" ")))
        if version == 4:
            (_version, vddh_ext, vee_ext, xon_len, xon_delay, vddh, vee,
             vcom_offset, v_l, vpdd_len, _checksum) = struct.unpack("<HBBBBHHHHBB", record)
            print("       vddh_ext=%d vee_ext=%d xon_len=%d xon_delay=%d "
                  "vddh=0x%04x vee=0x%04x vcom_offset=0x%04x v_l=0x%04x vpdd_len=%d" %
                  (vddh_ext, vee_ext, xon_len, xon_delay, vddh, vee,
                   vcom_offset, v_l, vpdd_len))
        else:
            (_version, vpos, vneg, vddh, vee, vcom_offset,
             unused_0, unused_1, _checksum) = struct.unpack("<7HBB", record)
            print("       vpos=0x%04x vneg=0x%04x vddh=0x%04x vee=0x%04x "
                  "vcom_offset=0x%04x unused_0=0x%04x unused_1=0x%02x" %
                  (vpos, vneg, vddh, vee, vcom_offset, unused_0, unused_1))

    acd = blob[acd_start:xswi_start]
    nonzero = [index for index, byte in enumerate(acd) if byte]
    print("ACD 0x%x..0x%x: %d bytes, nonzero=%d, first_nonzero=%s" %
          (acd_start, xswi_start, len(acd), len(nonzero),
           ("0x%x" % nonzero[0]) if nonzero else "none"))
    pointer_count = layout["mode_count"] * layout["temp_count"]
    table_size = pointer_count * 4
    if table_size > len(acd):
        raise ValueError("ACD is too short for mode*temperature pointer table")
    pointer_records = [acd[index:index + 4] for index in range(0, table_size, 4)]
    valid_pointers = sum((sum(record[:3]) & 0xFF) == record[3]
                         for record in pointer_records)
    pointers = [record[0] | (record[1] << 8) | (record[2] << 16)
                for record in pointer_records]
    print("ACD pointer table: %d modes x %d temps x 4 B = %d B, checksums %d/%d" %
          (layout["mode_count"], layout["temp_count"], table_size,
           valid_pointers, pointer_count))
    for mode in range(layout["mode_count"]):
        values = pointers[mode * layout["temp_count"]:(mode + 1) * layout["temp_count"]]
        nonzero_values = [value for value in values if value]
        summary = ("disabled" if not nonzero_values else
                   "0x%x..0x%x" % (min(nonzero_values), max(nonzero_values)))
        print("  mode %2d: nonzero=%2d unique=%2d %s" %
              (mode, len(nonzero_values), len(set(nonzero_values)), summary))
        if len(nonzero_values) >= 2:
            strides = {right - left for left, right in zip(nonzero_values, nonzero_values[1:])}
            if len(strides) == 1:
                stride = strides.pop()
                print("           source_record_stride=%d" % stride)

    print("ACD source pointers: nonzero=%d (source-file offsets; not dereferenced in expanded blob)" %
          (pointer_count - pointers.count(0)))
    source_region = acd[table_size:]
    print("ACD mapped source region: blob +0x%x..+0x%x -> source 0x%x..0x%x (%d B)" %
          (table_size, len(acd), acd_source_base,
           acd_source_base + len(source_region), len(source_region)))

    def source_bytes(pointer, size):
        relative = pointer - acd_source_base
        if relative < 0 or relative + size > len(source_region):
            raise ValueError("ACD source pointer out of mapped range: 0x%x" % pointer)
        return source_region[relative:relative + size]

    parameter_pointers = []
    descriptor_ends = []
    for mode in range(layout["mode_count"]):
        values = pointers[mode * layout["temp_count"]:(mode + 1) * layout["temp_count"]]
        nonzero_values = [value for value in values if value]
        if not nonzero_values:
            continue
        descriptors = []
        decoded = []
        for pointer in nonzero_values:
            header = source_bytes(pointer, 4)
            version = struct.unpack_from("<H", header)[0]
            parameter_count = header[2]
            descriptor_size = 4 + parameter_count * 4
            descriptor = source_bytes(pointer, descriptor_size)
            if (sum(header[:3]) & 0xFF) != header[3]:
                raise ValueError("ACD descriptor header checksum failed at 0x%x" % pointer)
            params = []
            for index in range(parameter_count):
                record = descriptor[4 + index * 4:8 + index * 4]
                if (sum(record[:3]) & 0xFF) != record[3]:
                    raise ValueError("ACD parameter pointer checksum failed at 0x%x" % pointer)
                param = record[0] | (record[1] << 8) | (record[2] << 16)
                params.append(param)
                parameter_pointers.append(param)
            descriptors.append(descriptor)
            decoded.append((version, parameter_count, params))
            descriptor_ends.append(pointer + descriptor_size)
        counts = {}
        for descriptor in descriptors:
            counts[descriptor] = counts.get(descriptor, 0) + 1
        versions = sorted(set((version, count) for version, count, _params in decoded))
        print("ACD mode %d descriptors: source 0x%x..0x%x, count=%d, unique=%d, headers=%s" %
              (mode, min(nonzero_values), max(descriptor_ends[-len(nonzero_values):]),
               len(descriptors), len(counts),
               ",".join("v%d/np%d" % item for item in versions)))
        for descriptor, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            print("  x%-2d %s" % (count, descriptor.hex(" ")))
        version, parameter_count, params = decoded[0]
        parameter_values = []
        for pointer in params:
            prefix = source_bytes(pointer, 2)
            payload_length = struct.unpack_from("<H", prefix)[0]
            record = source_bytes(pointer, payload_length + 3)
            checksum_ok = (sum(record[:-1]) & 0xFF) == record[-1]
            value = record[2] if payload_length else None
            parameter_values.append(value)
            print("       param 0x%x: payload_len=%d value=%s checksum=%s" %
                  (pointer, payload_length,
                   ("0x%02x" % value) if value is not None else "none",
                   "ok" if checksum_ok else "BAD"))
        # Kindle's fetch_epdc_adc_06_data defaults to SFT=3/ASV=21 and only
        # applies the first two parameter values for descriptor versions 1/6.
        sft, asv = 3, 21
        if version in (1, 6) and parameter_count <= 2:
            if parameter_values:
                sft = parameter_values[0]
            if len(parameter_values) >= 2:
                asv = parameter_values[1]
        print("       driver_effective_sft=%d driver_effective_asv=%d" % (sft, asv))

    if parameter_pointers:
        unique_parameter_pointers = sorted(set(parameter_pointers))
        shared_base = unique_parameter_pointers[0]
        shared_relative = shared_base - acd_source_base
        shared_region = source_region[shared_relative:]
        print("ACD shared parameter region: source 0x%x..0x%x (%d B), targets=%s" %
              (shared_base, acd_source_base + len(source_region), len(shared_region),
               " ".join("0x%x" % pointer for pointer in unique_parameter_pointers)))
        print("  descriptor region ends at 0x%x" % max(descriptor_ends))
        source_end = acd_source_base + len(source_region)
        if source_size is None:
            print("  mapped source end: 0x%x" % source_end)
        else:
            print("  mapped source end: 0x%x; reported source size: 0x%x (%s)" %
                  (source_end, source_size,
                   "match" if source_end == source_size else "MISMATCH"))
        print("  copied shared parameter bytes:")
        hexdump(blob, acd_start + table_size + shared_relative, len(shared_region))
        print("  note: source pointers refer to this relocated copy, not blob[pointer]")
    print("ACD data base pointer: 0x%x%s" %
          (acd_source_base, " (matches first nonzero table entry)"
           if acd_source_base == next((pointer for pointer in pointers if pointer), None) else ""))

    if xswi_start < len(blob):
        length = blob[xswi_start]
        end = xswi_start + 1 + length
        text = blob[xswi_start + 1:end]
        checksum = blob[end] if end < len(blob) else None
        expected = (length + sum(text)) & 0xFF
        print("XSWI 0x%x: len=%d text=%r checksum=%s expected=0x%02x" %
              (xswi_start, length, text.decode("ascii", "replace"),
               ("0x%02x" % checksum) if checksum is not None else "missing", expected))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("blob", type=Path)
    ap.add_argument("--mode", type=int)
    ap.add_argument("--temp", type=int)
    ap.add_argument("--nibble-order", choices=("low", "high"),
                    help="required with --mode/--temp; low is the evidenced 5-bit order, high is diagnostic")
    ap.add_argument("--source-size", type=lambda value: int(value, 0),
                    help="original WRF/WBF size from /proc/eink/waveform/info")
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--advanced", action="store_true",
                    help="decode and hexdump the four non-standard top-level entries")
    args = ap.parse_args()

    blob = args.blob.read_bytes()
    layout = infer_layout(blob)
    summarize(blob, layout)
    if args.advanced:
        summarize_advanced(blob, layout, args.source_size)
        for index, offset in enumerate(layout["advanced"]):
            print("advanced[%d] @ 0x%x" % (index, offset))
            hexdump(blob, offset)
    if args.mode is None and args.temp is None and args.csv is None:
        return 0
    if args.mode is None or args.temp is None:
        ap.error("--mode and --temp are required together")
    if args.nibble_order is None:
        ap.error("--nibble-order is required with --mode/--temp")
    if not 0 <= args.mode < layout["mode_count"]:
        ap.error("--mode out of range")
    if not 0 <= args.temp < layout["temp_count"]:
        ap.error("--temp out of range")

    blocks, frames = layout["modes"][args.mode]
    block, count = blocks[args.temp], frames[args.temp]
    low_first = args.nibble_order == "low"
    phases = read_phases(blob, block, count, low_first)
    print("selected mode=%d temp=%d block=0x%x phases=%d order=%s-first" %
          (args.mode, args.temp, block, count, args.nibble_order))
    for src, dst in ((0, 0), (30, 30), (0, 30), (30, 0), (31, 31)):
        print("%2d->%2d %s" % (src, dst, transition_sequence(phases, src, dst)))
    if args.csv:
        write_csv(args.csv, phases)
        print("wrote %s" % args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
