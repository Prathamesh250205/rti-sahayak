"""Vercel build command (see vercel.json): build the Chroma index, then drop
packages the running app never imports, to fit the 500 MB function limit.

- pymupdf (~62 MB): only rag/ingest.py reads the PDF, and that's done here.
- kubernetes (~40 MB): chromadb's distributed mode only; we use a local file.
- hf_xet (~12 MB): a Hugging Face download accelerator; nothing downloads at runtime.
- the model's onnx.tar.gz (79 MB): already unpacked next to it; the runtime
  only checks for the unpacked files (see chromadb's ONNXMiniLM_L6_V2).

Verified by loading every page/API route and checking sys.modules: none of
these get imported. Run: python -m tools.vercel_build
"""
import glob
import os
import shutil
import site

from rag.ingest import ONNX_CACHE_DIR, ingest

UNUSED_AT_RUNTIME = ("pymupdf", "fitz", "kubernetes", "hf_xet")


def main():
    ingest()
    archive = os.path.join(ONNX_CACHE_DIR, "onnx.tar.gz")
    if os.path.exists(archive):
        os.remove(archive)
        print(f"[build] removed {archive}")
    for packages_dir in site.getsitepackages():
        for name in UNUSED_AT_RUNTIME:
            for path in glob.glob(f"{packages_dir}/{name}") + glob.glob(f"{packages_dir}/{name}[-.]*"):
                shutil.rmtree(path, ignore_errors=True)
                print(f"[build] removed {path}")


if __name__ == "__main__":
    main()
