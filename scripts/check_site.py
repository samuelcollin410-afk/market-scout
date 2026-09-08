"""Verify the static entry point and its local asset references."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

root = Path(__file__).resolve().parents[1] / "dist"


class Assets(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for field in ("href", "src"):
            ref = attrs.get(field, "")
            if ref and not ref.startswith("#") and not urlparse(ref).scheme:
                path = root / ref
                if not path.is_file():
                    raise ValueError("Missing site asset: " + ref)


Assets().feed((root / "index.html").read_text())
assert (root / "data/latest.json").is_file(), "Missing initial snapshot"
print("Static assets verified")
