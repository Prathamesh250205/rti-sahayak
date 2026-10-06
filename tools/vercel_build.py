"""Vercel build command (see vercel.json): build the Chroma index, then drop
packages the running app never imports, to fit the 500 MB function limit.

- pymupdf (~62 MB): only rag/ingest.py reads the PDF, and that's done here.
- kubernetes (~40 MB): chromadb's distributed mode only; we use a local file.
- hf_xet (~12 MB): a Hugging Face download accelerator; nothing downloads at runtime.

Verified by loading every page/API route and checking sys.modules: none of
these get imported. Run: python -m tools.vercel_build
"""
import glob
import shutil
import site

from rag.ingest import ingest

UNUSED_AT_RUNTIME = ("pymupdf", "fitz", "kubernetes", "hf_xet")


def main():
    ingest()
    for packages_dir in site.getsitepackages():
        for name in UNUSED_AT_RUNTIME:
            for path in glob.glob(f"{packages_dir}/{name}") + glob.glob(f"{packages_dir}/{name}[-.]*"):
                shutil.rmtree(path, ignore_errors=True)
                print(f"[build] removed {path}")


if __name__ == "__main__":
    main()
