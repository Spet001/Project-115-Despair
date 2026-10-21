#!/usr/bin/env python3
"""
build_wad.py
============
Standalone repacker for Project 115 - Despair.

Repacks the unpacked source tree into:
  1. A monolithic, complete, playable Doom PWAD: 'Project115.wad'
  2. A modern GZDoom PK3 zip archive: 'Project115.pk3'

Usage:
  python build_wad.py                  # Builds Project115.wad (default)
  python build_wad.py --pk3            # Builds Project115.pk3
  python build_wad.py --format both    # Builds both Project115.wad and Project115.pk3
  python build_wad.py --verify         # Verifies integrity of the repacked archive
"""

import os
import sys
import struct
import json
import zipfile
import argparse
from pathlib import Path


def read_map_lumps(map_wad_path: Path):
    """Read the lumps from a standalone map WAD file."""
    lumps = []
    with open(map_wad_path, "rb") as f:
        header = f.read(12)
        wad_type, num_lumps, dir_offset = struct.unpack("<4sII", header)
        f.seek(dir_offset)
        entries = []
        for _ in range(num_lumps):
            pos, size, name_bytes = struct.unpack("<II8s", f.read(16))
            name = name_bytes.split(b"\x00")[0].decode("ascii", errors="replace").strip()
            entries.append((pos, size, name))
        for pos, size, name in entries:
            f.seek(pos)
            data = f.read(size)
            lumps.append((name, data))
    return lumps


def build_pwad(src_dir: Path, out_path: Path, verbose: bool = False):
    """Pack source directory into a classic monolithic PWAD."""
    print(f"\n[PWAD Builder] Building {out_path.name} from {src_dir}...")
    manifest_path = src_dir / "wad_manifest.json"

    # We collect all lumps as tuples: (name, data_bytes)
    all_lumps = []

    if manifest_path.exists():
        print("  Using wad_manifest.json for bit-accurate lump ordering.")
        with open(manifest_path, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)

        # Pre-cache map lumps
        maps_cache = {}
        for map_wad in (src_dir / "maps").glob("*.wad"):
            map_name = map_wad.stem.upper()
            maps_cache[map_name] = read_map_lumps(map_wad)

        # Pre-cache directory file lookups by lump name
        # Sprites
        sprites_files = {}
        if (src_dir / "sprites").exists():
            for p in (src_dir / "sprites").iterdir():
                if p.is_file():
                    sprites_files[p.stem.upper()] = p

        # Textures
        textures_files = {}
        if (src_dir / "textures").exists():
            for p in (src_dir / "textures").iterdir():
                if p.is_file():
                    textures_files[p.stem.upper()] = p

        # Sounds
        sounds_files = {}
        if (src_dir / "sounds").exists():
            for p in (src_dir / "sounds").iterdir():
                if p.is_file():
                    sounds_files[p.stem.upper()] = p

        # Music
        music_files = {}
        if (src_dir / "music").exists():
            for p in (src_dir / "music").iterdir():
                if p.is_file():
                    music_files[p.stem.upper()] = p

        # Graphics
        graphics_files = {}
        if (src_dir / "graphics").exists():
            for p in (src_dir / "graphics").iterdir():
                if p.is_file():
                    graphics_files[p.stem.upper()] = p

        # Maps track iterator per map
        map_lump_iter = {m: 0 for m in maps_cache}

        for entry in manifest["lump_order"]:
            name = entry["name"]
            sec = entry.get("section", "")

            if sec == "marker" or entry["size"] == 0 and name in ("SS_START", "SS_END", "S_START", "S_END", "TX_START", "TX_END", "ENDMAP"):
                all_lumps.append((name, b""))
            elif sec == "root_defs":
                filepath = src_dir / entry["file"]
                data = filepath.read_bytes() if filepath.exists() else b""
                all_lumps.append((name, data))
            elif sec in ("sprites_ss", "sprites_s"):
                p = sprites_files.get(name.upper())
                data = p.read_bytes() if p and p.exists() else b""
                all_lumps.append((name, data))
            elif sec == "graphics":
                p = graphics_files.get(name.upper())
                data = p.read_bytes() if p and p.exists() else b""
                all_lumps.append((name, data))
            elif sec == "sounds":
                p = sounds_files.get(name.upper())
                data = p.read_bytes() if p and p.exists() else b""
                all_lumps.append((name, data))
            elif sec == "music":
                p = music_files.get(name.upper())
                data = p.read_bytes() if p and p.exists() else b""
                all_lumps.append((name, data))
            elif sec == "textures":
                p = textures_files.get(name.upper())
                data = p.read_bytes() if p and p.exists() else b""
                all_lumps.append((name, data))
            elif sec == "maps":
                mname = entry.get("map", "")
                if mname in maps_cache:
                    mlumps = maps_cache[mname]
                    idx = map_lump_iter[mname]
                    if idx < len(mlumps):
                        lname, ldata = mlumps[idx]
                        map_lump_iter[mname] += 1
                        all_lumps.append((lname, ldata))
                    else:
                        all_lumps.append((name, b""))
                else:
                    all_lumps.append((name, b""))
            else:
                # General fallback
                all_lumps.append((name, b""))
    else:
        print("  Manifest not found. Assembling lumps using folder conventions...")
        # 1. Root definition files
        for txt_file in sorted(src_dir.glob("*.txt")):
            lump_name = txt_file.stem.upper()[:8]
            all_lumps.append((lump_name, txt_file.read_bytes()))

        # 2. Sprites
        all_lumps.append(("S_START", b""))
        if (src_dir / "sprites").exists():
            for sp in sorted((src_dir / "sprites").iterdir()):
                if sp.is_file():
                    all_lumps.append((sp.stem.upper()[:8], sp.read_bytes()))
        all_lumps.append(("S_END", b""))

        # 3. Graphics
        if (src_dir / "graphics").exists():
            for gp in sorted((src_dir / "graphics").iterdir()):
                if gp.is_file():
                    all_lumps.append((gp.stem.upper()[:8], gp.read_bytes()))

        # 4. Sounds & Music
        for audio_dir in ["sounds", "music"]:
            adir = src_dir / audio_dir
            if adir.exists():
                for ap in sorted(adir.iterdir()):
                    if ap.is_file():
                        all_lumps.append((ap.stem.upper()[:8], ap.read_bytes()))

        # 5. Textures
        all_lumps.append(("TX_START", b""))
        if (src_dir / "textures").exists():
            for tp in sorted((src_dir / "textures").iterdir()):
                if tp.is_file():
                    all_lumps.append((tp.stem.upper()[:8], tp.read_bytes()))
        all_lumps.append(("TX_END", b""))

        # 6. Maps
        if (src_dir / "maps").exists():
            for mw in sorted((src_dir / "maps").glob("*.wad")):
                map_lumps = read_map_lumps(mw)
                all_lumps.extend(map_lumps)

    print(f"  Total lumps to pack: {len(all_lumps)}")

    # Write out PWAD
    temp_out = out_path.with_suffix(".tmp")
    with open(temp_out, "wb") as f:
        # Placeholder header (12 bytes)
        f.write(struct.pack("<4sII", b"PWAD", len(all_lumps), 0))

        dir_entries = []
        for name, data in all_lumps:
            pos = f.tell()
            size = len(data)
            if size > 0:
                f.write(data)
            dir_entries.append((pos, size, name))

        dir_offset = f.tell()
        for pos, size, name in dir_entries:
            name_bytes = name.encode("ascii", errors="replace")[:8].ljust(8, b"\x00")
            f.write(struct.pack("<II8s", pos, size, name_bytes))

        # Seek back and write actual dir_offset
        f.seek(8)
        f.write(struct.pack("<I", dir_offset))

    # Rename temp to target
    if out_path.exists():
        out_path.unlink()
    temp_out.rename(out_path)

    final_size = out_path.stat().st_size
    print(f"  [PWAD Success] Repacked {len(all_lumps)} lumps into {out_path} ({final_size:,} bytes / {final_size/(1024*1024):.2f} MB)")
    return out_path


def build_pk3(src_dir: Path, out_path: Path, verbose: bool = False):
    """Pack source directory into a modern GZDoom PK3 zip archive."""
    print(f"\n[PK3 Builder] Building {out_path.name} from {src_dir}...")
    temp_out = out_path.with_suffix(".tmp")

    added_files = 0
    total_bytes = 0

    with zipfile.ZipFile(temp_out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 1. Root definition files
        for txt_file in sorted(src_dir.glob("*.txt")):
            zf.write(txt_file, arcname=txt_file.name)
            added_files += 1
            total_bytes += txt_file.stat().st_size

        # 2. Subdirectories: sprites, textures, sounds, music, graphics
        for folder in ["sprites", "textures", "sounds", "music", "graphics"]:
            fpath = src_dir / folder
            if fpath.exists():
                for item in sorted(fpath.rglob("*")):
                    if item.is_file():
                        arc_name = f"{folder}/{item.relative_to(fpath).as_posix()}"
                        zf.write(item, arcname=arc_name)
                        added_files += 1
                        total_bytes += item.stat().st_size

        # 3. Maps (standalone .wad files only, skipping source/ ACS text files)
        maps_dir = src_dir / "maps"
        if maps_dir.exists():
            for map_file in sorted(maps_dir.glob("*.wad")):
                arc_name = f"maps/{map_file.name}"
                zf.write(map_file, arcname=arc_name)
                added_files += 1
                total_bytes += map_file.stat().st_size

    if out_path.exists():
        out_path.unlink()
    temp_out.rename(out_path)

    final_size = out_path.stat().st_size
    print(f"  [PK3 Success] Packed {added_files} files into {out_path} ({final_size:,} bytes / {final_size/(1024*1024):.2f} MB)")
    return out_path


def verify_archive(path: Path):
    """Verify that the generated WAD or PK3 archive is valid and intact."""
    print(f"\n[Verification] Checking {path}...")
    if not path.exists():
        print(f"  Error: {path} does not exist!", file=sys.stderr)
        return False

    if path.suffix.lower() == ".wad":
        with open(path, "rb") as f:
            header = f.read(12)
            if len(header) < 12:
                print("  Failed: Header too short!", file=sys.stderr)
                return False
            wad_type, num_lumps, dir_offset = struct.unpack("<4sII", header)
            wad_type = wad_type.decode("ascii", errors="replace")
            print(f"  WAD Header: {wad_type}, Lumps: {num_lumps}, Dir Offset: {dir_offset}")
            if wad_type not in ("PWAD", "IWAD"):
                print(f"  Failed: Invalid WAD type {wad_type}", file=sys.stderr)
                return False
            f.seek(dir_offset)
            dir_data = f.read(num_lumps * 16)
            if len(dir_data) != num_lumps * 16:
                print("  Failed: Truncated directory entries!", file=sys.stderr)
                return False
        print(f"  [PASSED] WAD {path.name} is structurally valid ({num_lumps} lumps).")
        return True

    elif path.suffix.lower() in (".pk3", ".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            bad_file = zf.testzip()
            if bad_file:
                print(f"  Failed: Corrupt file inside PK3: {bad_file}", file=sys.stderr)
                return False
            namelist = zf.namelist()
            print(f"  [PASSED] PK3 {path.name} is structurally valid ({len(namelist)} files inside).")
            return True

    print(f"  Unknown archive format for verification: {path.suffix}", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description="Repack Project 115 - Despair into a playable WAD or PK3.")
    parser.add_argument("--src", type=Path, default=Path(__file__).resolve().parent, help="Source directory containing unpacked files")
    parser.add_argument("--format", "-f", choices=["wad", "pk3", "both"], default="wad", help="Output format (default: wad)")
    parser.add_argument("--wad", action="store_true", help="Build Project115.wad")
    parser.add_argument("--pk3", action="store_true", help="Build Project115.pk3")
    parser.add_argument("--all", "--both", dest="build_both", action="store_true", help="Build both Project115.wad and Project115.pk3")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Custom output filename or directory")
    parser.add_argument("--verify", action="store_true", help="Verify archive after building")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()
    src = args.src.resolve()

    # Determine what to build
    build_wad_flag = args.wad or (args.format in ("wad", "both") and not args.pk3)
    build_pk3_flag = args.pk3 or (args.format in ("pk3", "both") and not args.wad)
    if args.build_both or args.format == "both":
        build_wad_flag = True
        build_pk3_flag = True

    targets = []
    if build_wad_flag:
        wad_out = args.output if (args.output and args.output.suffix.lower() == ".wad") else (src / "Project115.wad")
        built_wad = build_pwad(src, wad_out, args.verbose)
        targets.append(built_wad)

    if build_pk3_flag:
        pk3_out = args.output if (args.output and args.output.suffix.lower() == ".pk3") else (src / "Project115.pk3")
        built_pk3 = build_pk3(src, pk3_out, args.verbose)
        targets.append(built_pk3)

    if args.verify or True:  # Always verify output
        all_passed = True
        for t in targets:
            if not verify_archive(t):
                all_passed = False
        if not all_passed:
            print("\nVerification FAILED on one or more archives!", file=sys.stderr)
            sys.exit(1)
        print("\nAll built archives verified successfully!")


if __name__ == "__main__":
    main()
