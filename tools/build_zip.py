"""Build an installable add-on zip: python tools/build_zip.py  ->  dist/banana-<version>.zip"""

import ast
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "banana")


def version():
    tree = ast.parse(open(os.path.join(PKG, "__init__.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "bl_info":
            info = ast.literal_eval(node.value)
            return ".".join(str(v) for v in info["version"])
    return "dev"


def main():
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "banana-%s.zip" % version())
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder, _dirs, files in os.walk(PKG):
            if "__pycache__" in folder:
                continue
            for name in files:
                if name.endswith(".pyc"):
                    continue
                path = os.path.join(folder, name)
                zf.write(path, os.path.relpath(path, ROOT))
    print(out)
    return out


if __name__ == "__main__":
    main()
