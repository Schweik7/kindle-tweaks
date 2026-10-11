#!/usr/bin/env python3
"""Build an offline KOA3 WRF with a detached long no-op LUT.

This tool never talks to a Kindle.  It preserves the vendor header and all
advanced-algorithm data, appends one zero-action waveform block, and repoints
every temperature entry of an existing all-zero one-phase mode to that block.
The intended template on the observed KOA3 waveform is mode 7.
"""
import argparse
import gzip
import hashlib
import struct
from pathlib import Path

from analyze_epdc_waveform import PHASE_BYTES, infer_layout

HEADER_BYTES = 48
MAX_FRAMES = 1023


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_file(path):
    raw = path.read_bytes()
    if path.name.lower().endswith(".gz"):
        return gzip.decompress(raw)
    return raw


def write_file(path, data):
    if path.name.lower().endswith(".gz"):
        with path.open("wb") as output:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as stream:
                stream.write(data)
    else:
        path.write_bytes(data)


def require_zero_template(blob, layout, mode):
    blocks, frame_counts = layout["modes"][mode]
    for temp, (block, count) in enumerate(zip(blocks, frame_counts)):
        if count != 1:
            raise ValueError("mode %d temp %d is not a one-phase template" % (mode, temp))
        phase = blob[block + 8:block + 8 + PHASE_BYTES]
        if phase != bytes(PHASE_BYTES):
            raise ValueError("mode %d temp %d is not an all-zero no-op template" %
                             (mode, temp))


def build(wrf, mode, frame_count):
    if len(wrf) < HEADER_BYTES:
        raise ValueError("WRF is shorter than its 48-byte header")
    header_mode_count = wrf[37] + 1
    header_temp_count = wrf[38] + 1
    payload_offset = HEADER_BYTES + header_temp_count + 1
    if payload_offset >= len(wrf):
        raise ValueError("WRF temperature table/padding is truncated")

    blob = bytearray(wrf[payload_offset:])
    layout = infer_layout(blob)
    if layout["mode_count"] != header_mode_count:
        raise ValueError("header/payload mode count mismatch: %d != %d" %
                         (header_mode_count, layout["mode_count"]))
    if layout["temp_count"] != header_temp_count:
        raise ValueError("header/payload temperature count mismatch: %d != %d" %
                         (header_temp_count, layout["temp_count"]))
    if not 0 <= mode < layout["mode_count"]:
        raise ValueError("mode %d is outside the standard mode table" % mode)
    require_zero_template(blob, layout, mode)

    padding = (-len(blob)) % 8
    blob.extend(bytes(padding))
    block_offset = len(blob)
    blob.extend(struct.pack("<Q", frame_count))
    blob.extend(bytes(frame_count * PHASE_BYTES))

    temp_table = layout["top"][mode]
    for temp in range(layout["temp_count"]):
        struct.pack_into("<Q", blob, temp_table + temp * 8, block_offset)

    rebuilt = bytes(wrf[:payload_offset]) + bytes(blob)
    verified = infer_layout(bytes(blob))
    new_blocks, new_counts = verified["modes"][mode]
    if set(new_blocks) != {block_offset} or set(new_counts) != {frame_count}:
        raise AssertionError("rebuilt mode table did not round-trip")
    if verified["advanced"] != layout["advanced"]:
        raise AssertionError("advanced pointers changed unexpectedly")
    return rebuilt, payload_offset, block_offset, padding, layout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="vendor .wrf or .wrf.gz")
    parser.add_argument("output", type=Path, help="new .wrf or .wrf.gz")
    parser.add_argument("--mode", type=int, default=7,
                        help="existing all-zero one-phase mode to replace (default: 7)")
    parser.add_argument("--frames", type=int, default=MAX_FRAMES,
                        help="number of zero-action phases (1..1023)")
    parser.add_argument("--force", action="store_true", help="overwrite output")
    args = parser.parse_args()

    if not 1 <= args.frames <= MAX_FRAMES:
        parser.error("--frames must be in 1..%d" % MAX_FRAMES)
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output must be different files")
    if args.output.exists() and not args.force:
        parser.error("output exists; use --force to replace it")

    source = read_file(args.input)
    rebuilt, payload_offset, block_offset, padding, layout = build(
        source, args.mode, args.frames)
    write_file(args.output, rebuilt)

    print("input_size=%d sha256=%s" % (len(source), digest(source)))
    print("output_size=%d sha256=%s" % (len(rebuilt), digest(rebuilt)))
    print("payload_offset=0x%x mode=%d temperatures=%d" %
          (payload_offset, args.mode, layout["temp_count"]))
    print("appended_block=0x%x alignment_padding=%d frames=%d phase_bytes=%d" %
          (block_offset, padding, args.frames, PHASE_BYTES))
    print("advanced pointers preserved: %s" %
          " ".join("0x%x" % value for value in layout["advanced"]))
    print("OFFLINE ONLY: generated file was not installed or loaded on the Kindle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
