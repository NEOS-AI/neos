from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from neos.coding.sandbox.base import (
    SandboxNotFound,
    SandboxPolicyViolation,
)
from neos.coding.sandbox.paths import normalize_workspace_path


SNAPSHOT_SCHEMA_VERSION = 1
_EXCLUDED_PATHS = {
    ".env",
    ".git/credentials",
    ".neos/secrets",
}


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    schema_version: int
    source_sandbox_id: str
    workspace_revision: int
    created_at: datetime
    base_image_digest: str | None
    content_checksum: str

    def to_json(self) -> str:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> SnapshotManifest:
        try:
            payload = json.loads(value)
            return cls(
                schema_version=int(payload["schema_version"]),
                source_sandbox_id=str(payload["source_sandbox_id"]),
                workspace_revision=int(payload["workspace_revision"]),
                created_at=datetime.fromisoformat(payload["created_at"]),
                base_image_digest=payload.get("base_image_digest"),
                content_checksum=str(payload["content_checksum"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SandboxPolicyViolation("snapshot_manifest_invalid") from error


class LocalSnapshotStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def manifest_path(self, snapshot_id: str) -> Path:
        self._validate_snapshot_id(snapshot_id)
        return self._root / f"{snapshot_id}.json"

    def archive_path(self, snapshot_id: str) -> Path:
        self._validate_snapshot_id(snapshot_id)
        return self._root / f"{snapshot_id}.tar"

    def save_manifest(
        self,
        snapshot_id: str,
        manifest: SnapshotManifest,
    ) -> None:
        target = self.manifest_path(snapshot_id)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(manifest.to_json())
        os.replace(temporary, target)

    def load_manifest(self, snapshot_id: str) -> SnapshotManifest:
        try:
            return SnapshotManifest.from_json(
                self.manifest_path(snapshot_id).read_text()
            )
        except FileNotFoundError as error:
            raise SandboxNotFound(snapshot_id) from error

    @staticmethod
    def _validate_snapshot_id(snapshot_id: str) -> None:
        if not snapshot_id.startswith("ss_") or not snapshot_id[3:].isalnum():
            raise SandboxPolicyViolation("snapshot_id_invalid")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_workspace_archive(
    workspace: Path,
    destination: Path,
    *,
    max_archive_bytes: int,
) -> str:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with tarfile.open(temporary, "w") as archive:
            for item in sorted(workspace.rglob("*")):
                relative = item.relative_to(workspace).as_posix()
                if _is_excluded(relative) or item.is_socket():
                    continue
                if item.is_block_device() or item.is_char_device() or item.is_fifo():
                    continue
                archive.add(item, arcname=relative, recursive=False)
        if temporary.stat().st_size > max_archive_bytes:
            raise SandboxPolicyViolation("snapshot_archive_size_exceeded")
        checksum = sha256_file(temporary)
        os.replace(temporary, destination)
        return checksum
    finally:
        temporary.unlink(missing_ok=True)


def extract_workspace_archive(
    archive_path: Path,
    target: Path,
    *,
    max_expanded_bytes: int,
    max_entries: int = 100_000,
) -> None:
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > max_entries:
            raise SandboxPolicyViolation("archive_entry_count_exceeded")
        expanded = 0
        validated: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        for member in members:
            relative = _validate_archive_member(member)
            if member.isfile():
                expanded += member.size
                if expanded > max_expanded_bytes:
                    raise SandboxPolicyViolation(
                        "archive_expanded_size_exceeded"
                    )
            validated.append((member, relative))

        target.mkdir(parents=True, exist_ok=True)
        target_real = target.resolve(strict=True)
        for member, relative in validated:
            destination = target_real.joinpath(*relative.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                destination.symlink_to(member.linkname)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise SandboxPolicyViolation("archive_file_missing")
            with source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            os.chmod(destination, member.mode & 0o777)


def _validate_archive_member(member: tarfile.TarInfo) -> PurePosixPath:
    try:
        relative = normalize_workspace_path(member.name)
    except SandboxPolicyViolation as error:
        raise SandboxPolicyViolation("archive_path_escape") from error
    if relative == PurePosixPath("."):
        raise SandboxPolicyViolation("archive_path_invalid")
    if member.isdev() or member.isfifo() or member.islnk():
        raise SandboxPolicyViolation("archive_entry_type_forbidden")
    if not (member.isfile() or member.isdir() or member.issym()):
        raise SandboxPolicyViolation("archive_entry_type_forbidden")
    if member.issym():
        _validate_symlink_target(relative.parent, member.linkname)
    return relative


def _validate_symlink_target(parent: PurePosixPath, linkname: str) -> None:
    if "\0" in linkname or linkname.startswith("/"):
        raise SandboxPolicyViolation("archive_link_escape")
    parts: list[str] = list(parent.parts)
    for part in PurePosixPath(linkname).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise SandboxPolicyViolation("archive_link_escape")
            parts.pop()
        else:
            parts.append(part)


def _is_excluded(path: str) -> bool:
    return path in _EXCLUDED_PATHS or path.startswith(".neos/secrets/")
