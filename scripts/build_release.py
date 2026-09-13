"""Build and verify the HACS release archive using only the standard library."""

import ast
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/boiler_flow_control"
manifest = json.loads((COMPONENT / "manifest.json").read_text())
hacs = json.loads((ROOT / "hacs.json").read_text())
assert manifest["domain"] == "boiler_flow_control"
assert hacs["filename"] == "boiler_flow_control.zip" and hacs["zip_release"]
constants = ast.parse((COMPONENT / "const.py").read_text())
version = next(
    ast.literal_eval(node.value)
    for node in constants.body
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets)
)
assert version == manifest["version"], "Manifest and software versions differ"
for path in COMPONENT.rglob("*.py"):
    ast.parse(path.read_text(), filename=str(path), feature_version=(3, 13))
for name, dimension in (("icon.png", 256), ("icon@2x.png", 512)):
    image = (COMPONENT / "brand" / name).read_bytes()
    assert image[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(image[16:20], "big") == int.from_bytes(image[20:24], "big") == dimension
assert json.loads((COMPONENT / "strings.json").read_text()) == json.loads(
    (COMPONENT / "translations/en.json").read_text()
)
output = ROOT / "dist"
output.mkdir(exist_ok=True)
archive = output / hacs["filename"]
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
    for path in sorted(COMPONENT.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".json", ".png") and "__pycache__" not in path.parts:
            info = zipfile.ZipInfo(path.relative_to(COMPONENT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            package.writestr(info, path.read_bytes())
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    assert json.loads(package.read("manifest.json"))["version"] == version
    assert {"__init__.py", "brand/icon.png", "brand/icon@2x.png", "core/control.py"} <= set(package.namelist())
    assert all(not name.startswith("/") and ".." not in Path(name).parts for name in package.namelist())
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
print(f"Built {archive.name} for {version}: {len(package.namelist())} files, SHA256 {digest}")
