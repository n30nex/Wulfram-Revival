"""Runtime validation for an extracted immutable server release."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import sys
from typing import Any

from wulfram_server import SERVER_APPLICATION_VERSION


MANIFEST_SCHEMA_VERSION = 1


class ReleaseValidationError(ValueError):
    """Raised before sockets open when a packaged release has drifted."""


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    version: str
    git_commit: str
    content_identity: str
    physics_version: str
    packaged: bool

    @classmethod
    def source_checkout(cls) -> "ReleaseIdentity":
        return cls(
            version=SERVER_APPLICATION_VERSION,
            git_commit="source-checkout",
            content_identity="source-checkout",
            physics_version="development",
            packaged=False,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseValidationError(f"release manifest {label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseValidationError(f"release manifest {label} must be a string")
    return value


def _safe_relative_path(value: Any, label: str) -> PurePosixPath:
    text = _string(value, label)
    relative = PurePosixPath(text)
    if (
        "\\" in text
        or ":" in text
        or relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or text != relative.as_posix()
    ):
        raise ReleaseValidationError(f"release manifest {label} is unsafe: {text!r}")
    return relative


def load_release_identity(release_root: Path) -> ReleaseIdentity:
    """Validate a packaged tree, or describe a normal source-checkout run."""

    root = release_root.resolve()
    manifest_path = root / "release.json"
    if not manifest_path.is_file():
        return ReleaseIdentity.source_checkout()

    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseValidationError(f"release.json is unreadable: {error}") from error
    manifest = _object(document, "root")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ReleaseValidationError(
            f"unsupported release manifest schema {manifest.get('schema_version')!r}"
        )

    runtime = _object(manifest.get("python_runtime"), "python_runtime")
    expected_implementation = _string(
        runtime.get("implementation"), "python_runtime.implementation"
    )
    if sys.implementation.name.casefold() != expected_implementation.casefold():
        raise ReleaseValidationError(
            "interpreter implementation mismatch: "
            f"expected {expected_implementation}, observed {sys.implementation.name}"
        )
    expected_version = _string(runtime.get("version"), "python_runtime.version")
    observed_version = ".".join(str(part) for part in sys.version_info[:3])
    if observed_version != expected_version:
        raise ReleaseValidationError(
            f"interpreter version mismatch: expected {expected_version}, observed {observed_version}"
        )
    expected_abi = _string(runtime.get("abi_tag"), "python_runtime.abi_tag")
    observed_abi = sys.implementation.cache_tag or ""
    if observed_abi != expected_abi:
        raise ReleaseValidationError(
            f"interpreter ABI mismatch: expected {expected_abi}, observed {observed_abi}"
        )
    expected_bits = runtime.get("pointer_bits")
    observed_bits = struct.calcsize("P") * 8
    if expected_bits != observed_bits:
        raise ReleaseValidationError(
            f"interpreter architecture mismatch: expected {expected_bits}-bit, "
            f"observed {observed_bits}-bit"
        )

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ReleaseValidationError("release manifest files must be a non-empty array")
    seen: set[PurePosixPath] = set()
    for index, raw_entry in enumerate(files):
        entry = _object(raw_entry, f"files[{index}]")
        relative = _safe_relative_path(entry.get("path"), f"files[{index}].path")
        if relative in seen:
            raise ReleaseValidationError(f"duplicate release manifest path: {relative}")
        seen.add(relative)
        path = root.joinpath(*relative.parts)
        if not path.is_file():
            raise ReleaseValidationError(f"packaged file is missing: {relative}")
        expected_size = entry.get("size")
        if expected_size != path.stat().st_size:
            raise ReleaseValidationError(f"packaged file size changed: {relative}")
        expected_hash = _string(entry.get("sha256"), f"files[{index}].sha256")
        if _sha256(path) != expected_hash.casefold():
            raise ReleaseValidationError(f"packaged file hash changed: {relative}")

    content = _object(manifest.get("content"), "content")
    physics = _object(manifest.get("physics"), "physics")
    return ReleaseIdentity(
        version=_string(manifest.get("release_version"), "release_version"),
        git_commit=_string(manifest.get("git_commit"), "git_commit"),
        content_identity=_string(content.get("identity"), "content.identity"),
        physics_version=_string(physics.get("semantic_version"), "physics.semantic_version"),
        packaged=True,
    )
