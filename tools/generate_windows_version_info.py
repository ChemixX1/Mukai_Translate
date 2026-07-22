"""Generate the PyInstaller Windows version resource from app/version.py."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?", args.version.strip())
    if not match:
        raise ValueError("Windows releases require a numeric version such as 1.0.2.")
    parts = [int(value or 0) for value in match.groups()]
    version_tuple = ", ".join(str(value) for value in parts)
    file_version = ".".join(str(value) for value in parts)

    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({version_tuple}),
    prodvers=({version_tuple}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Mukai Labs'),
          StringStruct('FileDescription', 'Mukai Translator'),
          StringStruct('FileVersion', '{file_version}'),
          StringStruct('InternalName', 'MukaiTranslate'),
          StringStruct('LegalCopyright', 'Copyright (c) Mukai Labs'),
          StringStruct('OriginalFilename', 'MukaiTranslate.exe'),
          StringStruct('ProductName', 'Mukai Translator'),
          StringStruct('ProductVersion', '{args.version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
