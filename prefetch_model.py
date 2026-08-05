"""Download and verify the ASR checkpoint during explicit setup only."""

from __future__ import annotations

import json
import argparse
import os
import threading
import time
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download


parser = argparse.ArgumentParser(description="Download an ASR model for Local Dictation.")
parser.add_argument("--model-id", default=None)
arguments = parser.parse_args()

config = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
model_id = arguments.model_id or config["model_id"]
cache_root = Path(os.environ.get("HF_HUB_CACHE", Path.home() / ".cache" / "huggingface" / "hub"))
blob_dir = cache_root / f"models--{model_id.replace('/', '--')}" / "blobs"


def downloaded_bytes() -> int:
    if not blob_dir.exists():
        return 0
    return sum(path.stat().st_size for path in blob_dir.iterdir() if path.is_file())


metadata = HfApi().model_info(model_id, files_metadata=True)
total_bytes = sum(sibling.size or 0 for sibling in metadata.siblings)
print(f"TOTAL_BYTES={total_bytes}", flush=True)
print(f"Downloading {model_id} (first run only) ...", flush=True)

finished = threading.Event()


def report_progress() -> None:
    while not finished.wait(0.5):
        print(f"PROGRESS_BYTES={downloaded_bytes()}", flush=True)


threading.Thread(target=report_progress, daemon=True).start()
# Downloading weights does not need CUDA. This allows model switching while the
# dictation model is already resident in GPU memory.
try:
    snapshot_download(repo_id=model_id, local_files_only=False)
finally:
    finished.set()
print(f"PROGRESS_BYTES={downloaded_bytes()}", flush=True)
print("ASR model is ready for offline use.", flush=True)
