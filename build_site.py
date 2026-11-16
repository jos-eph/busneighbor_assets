"""Assemble the website's hand-written pages for the Pages build.

A page names a shared piece with a marker on a line of its own:

    <!-- #include footer.html -->

The marker is replaced with partials/footer.html, indented to match. An unknown
partial, a partial that includes another, or a marker left behind fails the
build, so the deploy keeps the previous site instead of shipping a broken one.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTIALS = ROOT / "partials"
PAGES = ("index.html", "share.html", "go.html")

INCLUDE = re.compile(r"^([ \t]*)<!-- #include ([A-Za-z0-9_-]+\.html) -->[ \t]*$", re.M)
LEFTOVER = "#include"


def expand_includes(text: str, partials: Path = PARTIALS) -> str:
    def replace(match: re.Match) -> str:
        indent, name = match.groups()
        path = partials / name
        if not path.is_file():
            raise ValueError(f"unknown partial: {name}")
        body = path.read_text(encoding="utf-8").rstrip("\n")
        if LEFTOVER in body:
            raise ValueError(f"partial {name} includes another; nesting is not supported")
        return "\n".join(indent + line if line else line for line in body.split("\n"))

    expanded = INCLUDE.sub(replace, text)
    if LEFTOVER in expanded:
        raise ValueError("an include marker was not replaced; it must be alone on its line")
    return expanded


def build(output_dir: Path, pages=PAGES, source: Path = ROOT, partials: Path = PARTIALS) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        text = (source / page).read_text(encoding="utf-8")
        (output_dir / page).write_text(expand_includes(text, partials), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    build(Path(args.output_dir))
    print(f"assembled {len(PAGES)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
