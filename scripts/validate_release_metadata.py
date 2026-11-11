#!/usr/bin/env python3

"""Validate that a preview tag, package metadata, and wheel agree exactly."""

import argparse
import ast
import re
import zipfile
from email.parser import Parser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_PATH = ROOT / "src" / "sre" / "setup.py"
TAG_PATTERN = re.compile(r"^v(?P<version>[0-9]+\.[0-9]+\.[0-9]+b[0-9]+)$")
WHEEL_PATTERN = re.compile(r"^sre-(?P<version>[A-Za-z0-9.+_-]+)-py3-none-any\.whl$")


def package_version(setup_path: Path = SETUP_PATH) -> str:
    tree = ast.parse(setup_path.read_text(), filename=str(setup_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "VERSION"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError(f"VERSION string not found in {setup_path}")


def wheel_metadata_version(wheel_path: Path) -> str:
    match = WHEEL_PATTERN.fullmatch(wheel_path.name)
    if not match:
        raise ValueError(f"Unexpected wheel filename: {wheel_path.name}")
    filename_version = match.group("version")
    with zipfile.ZipFile(wheel_path) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError("Wheel must contain exactly one METADATA file")
        metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
    if metadata.get("Name") != "sre":
        raise ValueError("Wheel package name is not 'sre'")
    metadata_version = metadata.get("Version")
    if metadata_version != filename_version:
        raise ValueError(
            f"Wheel filename version {filename_version!r} does not match "
            f"METADATA version {metadata_version!r}"
        )
    return metadata_version


def validate(tag: str, wheel_path: Path | None = None) -> str:
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ValueError(
            "Release tag must match v<major>.<minor>.<patch>b<preview>, "
            "for example v1.0.0b1"
        )
    tag_version = match.group("version")
    source_version = package_version()
    if tag_version != source_version:
        raise ValueError(
            f"Tag version {tag_version!r} does not match setup.py VERSION "
            f"{source_version!r}"
        )
    if wheel_path is not None:
        built_version = wheel_metadata_version(wheel_path)
        if built_version != tag_version:
            raise ValueError(
                f"Wheel version {built_version!r} does not match tag version "
                f"{tag_version!r}"
            )
    return tag_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--wheel", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(validate(args.tag, args.wheel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
