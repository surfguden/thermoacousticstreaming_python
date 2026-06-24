from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = ROOT / "main_html"
EXPORT_HTML = EXPORT_DIR / "main"
OUT_PATH = ROOT / "labview_manifest.json"


@dataclass(frozen=True)
class DocumentedVi:
    name: str
    images: list[str]
    source_path: str | None = None


@dataclass(frozen=True)
class ReferencedItem:
    name: str
    source_path: str


def _sections(document: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r'<A NAME="(.*?)"></A><H2>(.*?)</H2>', document))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        name = html.unescape(match.group(2))
        sections.append((name, document[start:end]))
    return sections


def _image_names(section: str) -> list[str]:
    return [
        html.unescape(match.group(1))
        for match in re.finditer(r'<IMG SRC="([^"]+)"', section)
    ]


def _referenced_items(document: str) -> list[ReferencedItem]:
    items: list[ReferencedItem] = []
    pattern = re.compile(r"<B><P>(.*?)</P>\s*</B><P>(.*?)</P>", re.S)
    for match in pattern.finditer(document):
        name = html.unescape(re.sub(r"<.*?>", "", match.group(1))).strip()
        path = html.unescape(re.sub(r"<.*?>", "", match.group(2))).strip()
        if name and path:
            items.append(ReferencedItem(name=name, source_path=path))
    return items


def parse_export() -> list[DocumentedVi]:
    document = EXPORT_HTML.read_text(encoding="utf-8", errors="replace")
    paths = {item.name: item.source_path for item in _referenced_items(document)}
    return [
        DocumentedVi(name=name, images=_image_names(section), source_path=paths.get(name))
        for name, section in _sections(document)
    ]


def main() -> None:
    document = EXPORT_HTML.read_text(encoding="utf-8", errors="replace")
    manifest = parse_export()
    references = _referenced_items(document)
    OUT_PATH.write_text(
        json.dumps(
            {
                "export_html": str(EXPORT_HTML),
                "documented_vis": [asdict(item) for item in manifest],
                "referenced_items": [asdict(item) for item in references],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"Wrote {OUT_PATH} with {len(manifest)} documented VIs "
        f"and {len(references)} referenced items."
    )


if __name__ == "__main__":
    main()
