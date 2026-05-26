"""
Face recognition service.

Wraps `face_recognition` (dlib) to extract 128-D embeddings from a JPEG/PNG
image and match them against the `known_faces` table.

All heavy work runs in a thread pool so the FastAPI event loop stays responsive
(dlib calls release the GIL but still spend hundreds of ms on a frame).

Optional: if the `face_recognition` package isn't installed, this module
degrades gracefully — vision still works, just without name recognition.
Install with `./install_face_recognition.sh` or `pip install face_recognition`.
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Optional

import numpy as np
from PIL import Image

# face_recognition pulls dlib, which on CPUs without AVX needs to be built from
# source. If the build hasn't finished yet, expose the module as None and let
# every public call degrade gracefully — the server still boots and vision
# without recognition keeps working.
try:
    import face_recognition  # type: ignore
    _FACE_OK = True
    _FACE_ERR: Optional[str] = None
except Exception as _e:  # noqa: BLE001
    face_recognition = None  # type: ignore[assignment]
    _FACE_OK = False
    _FACE_ERR = repr(_e)
    print(f"[face_service] face_recognition NOT available yet: {_FACE_ERR}")

from database import (
    add_known_face,
    list_known_faces,
)

# Distance threshold for matching (lower = stricter). face_recognition's
# `compare_faces` defaults to 0.6 in Euclidean L2 space on the 128-D embedding.
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.6"))


def _decode_image_to_rgb(image_bytes: bytes) -> np.ndarray:
    """Decode arbitrary image bytes (JPEG/PNG/etc.) into an RGB uint8 array."""
    pil_img = Image.open(io.BytesIO(image_bytes))
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    return np.asarray(pil_img, dtype=np.uint8)


def _embedding_to_bytes(emb: np.ndarray) -> bytes:
    return np.ascontiguousarray(emb, dtype=np.float64).tobytes()


def _bytes_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float64)


def _embed_sync(image_bytes: bytes) -> list[np.ndarray]:
    """Synchronous core: decode → detect faces → embed each one. Returns a list
    of 128-D float64 vectors (one per detected face, possibly empty)."""
    if not _FACE_OK:
        return []
    rgb = _decode_image_to_rgb(image_bytes)
    # `hog` model is CPU-only and fast enough for live frames; `cnn` needs GPU.
    locations = face_recognition.face_locations(rgb, model="hog")
    if not locations:
        return []
    return face_recognition.face_encodings(rgb, known_face_locations=locations)


async def embed_image(image_bytes: bytes) -> list[np.ndarray]:
    """Async wrapper around `_embed_sync` — runs in the default thread pool."""
    return await asyncio.to_thread(_embed_sync, image_bytes)


async def enroll_face(owner_id: str, name: str, image_bytes: bytes) -> dict:
    """Detect the single face in `image_bytes`, store its embedding under `name`.

    Raises ValueError when no face is found or when multiple faces appear
    (enrollment images should contain exactly one person).
    """
    if not _FACE_OK:
        raise ValueError(
            "Face recognition isn't available (the library couldn't be loaded). "
            "Run ./install_face_recognition.sh and try again."
        )
    embeddings = await embed_image(image_bytes)
    if len(embeddings) == 0:
        raise ValueError("No face detected in the image.")
    if len(embeddings) > 1:
        raise ValueError(
            f"Detected {len(embeddings)} faces. The enrollment photo must contain only the person."
        )
    emb_bytes = _embedding_to_bytes(embeddings[0])
    return add_known_face(owner_id=owner_id, name=name.strip(), embedding_bytes=emb_bytes)


def _best_match_sync(
    embedding: np.ndarray,
    known: list[tuple[str, np.ndarray]],
    threshold: float,
) -> Optional[tuple[str, float]]:
    """Return (name, distance) of the closest enrolled face within threshold,
    or None if no enrollment is close enough."""
    if not known:
        return None
    names = [n for n, _ in known]
    matrix = np.stack([e for _, e in known], axis=0)
    distances = np.linalg.norm(matrix - embedding, axis=1)
    idx = int(np.argmin(distances))
    if distances[idx] <= threshold:
        return names[idx], float(distances[idx])
    return None


async def recognize_people_in_image(image_bytes: bytes) -> list[str]:
    """Detect every face in the image and return the unique list of recognized
    names (in the order they appear). Unknown faces are skipped — they don't
    appear in the output at all.
    """
    embeddings = await embed_image(image_bytes)
    if not embeddings:
        return []

    rows = list_known_faces(include_embeddings=True)
    known: list[tuple[str, np.ndarray]] = [
        (r["name"], _bytes_to_embedding(r["embedding"])) for r in rows
    ]
    if not known:
        return []

    seen: list[str] = []
    for emb in embeddings:
        match = _best_match_sync(emb, known, FACE_MATCH_THRESHOLD)
        if match is None:
            continue
        name, _dist = match
        if name not in seen:
            seen.append(name)
    return seen
