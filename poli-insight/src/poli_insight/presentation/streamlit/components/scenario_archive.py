"""Safe inspection and temporary extraction of uploaded scenario archives."""

from __future__ import annotations

import io
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile, ZipInfo


MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 500
SCENARIO_CONFIG_NAMES = frozenset({"scenario.json", "scenario.jsonc"})


class ScenarioArchiveError(ValueError):
    """Safe structural failure for an uploaded scenario ZIP archive."""


@dataclass(frozen=True, slots=True)
class ScenarioArchiveInspection:
    filename: str
    archive_bytes: bytes = field(repr=False)
    package_root: PurePosixPath
    members: tuple[ZipInfo, ...]
    file_count: int
    total_uncompressed_bytes: int

    @property
    def package_label(self) -> str:
        if self.package_root == PurePosixPath("."):
            return "Archive root"
        return self.package_root.as_posix()


def inspect_scenario_archive(
    archive_bytes: bytes,
    *,
    filename: str,
) -> ScenarioArchiveInspection:
    """Validate archive boundaries and locate its single scenario package."""

    if not archive_bytes:
        raise ScenarioArchiveError("The uploaded archive is empty.")
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ScenarioArchiveError(
            "The archive exceeds the 25 MB compressed upload limit."
        )

    try:
        with ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = tuple(archive.infolist())
    except BadZipFile as error:
        raise ScenarioArchiveError(
            "The uploaded file is not a readable ZIP archive."
        ) from error

    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ScenarioArchiveError(
            "The archive contains too many entries."
        )

    normalized_paths: set[PurePosixPath] = set()
    scenario_configs: list[PurePosixPath] = []
    file_count = 0
    total_size = 0
    for member in members:
        path = _safe_member_path(member)
        if path in normalized_paths:
            raise ScenarioArchiveError(
                f"The archive contains a duplicate path: {path.as_posix()}."
            )
        normalized_paths.add(path)
        if member.is_dir():
            continue
        file_count += 1
        total_size += member.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise ScenarioArchiveError(
                "The archive exceeds the 100 MB extracted-size limit."
            )
        if path.name.casefold() in SCENARIO_CONFIG_NAMES:
            scenario_configs.append(path)

    if not file_count:
        raise ScenarioArchiveError("The archive does not contain any files.")
    if not scenario_configs:
        raise ScenarioArchiveError(
            "The archive must contain scenario.json or scenario.jsonc."
        )
    if len(scenario_configs) > 1:
        raise ScenarioArchiveError(
            "Import one scenario package at a time; multiple scenario "
            "configuration files were found."
        )

    package_root = scenario_configs[0].parent
    package_members = tuple(
        member
        for member in members
        if _is_within_package(_safe_member_path(member), package_root)
    )
    return ScenarioArchiveInspection(
        filename=Path(filename).name or "scenario.zip",
        archive_bytes=bytes(archive_bytes),
        package_root=package_root,
        members=package_members,
        file_count=sum(not member.is_dir() for member in package_members),
        total_uncompressed_bytes=sum(
            member.file_size
            for member in package_members
            if not member.is_dir()
        ),
    )


@contextmanager
def extracted_scenario_directory(
    inspection: ScenarioArchiveInspection,
) -> Iterator[Path]:
    """Yield a safely extracted scenario directory and remove it afterward."""

    with TemporaryDirectory(prefix="poli-insight-scenario-") as temp_name:
        temp_directory = Path(temp_name)
        with ZipFile(io.BytesIO(inspection.archive_bytes)) as archive:
            for member in inspection.members:
                member_path = _safe_member_path(member)
                destination = temp_directory.joinpath(*member_path.parts)
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(member) as source,
                    destination.open("wb") as target,
                ):
                    shutil.copyfileobj(source, target)

        source_directory = temp_directory.joinpath(
            *inspection.package_root.parts
        )
        if not source_directory.is_dir():
            raise ScenarioArchiveError(
                "The extracted scenario package root is unavailable."
            )
        yield source_directory


def _safe_member_path(member: ZipInfo) -> PurePosixPath:
    raw_name = member.filename.replace("\\", "/")
    if not raw_name or "\x00" in raw_name:
        raise ScenarioArchiveError("The archive contains an invalid path.")
    path = PurePosixPath(raw_name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ScenarioArchiveError(
            "The archive contains an unsafe file path."
        )
    mode = (member.external_attr >> 16) & 0xFFFF
    if mode and stat.S_ISLNK(mode):
        raise ScenarioArchiveError(
            "Symbolic links are not allowed in scenario archives."
        )
    if member.flag_bits & 0x1:
        raise ScenarioArchiveError(
            "Encrypted files are not supported in scenario archives."
        )
    return path


def _is_within_package(
    path: PurePosixPath,
    package_root: PurePosixPath,
) -> bool:
    if package_root == PurePosixPath("."):
        return True
    return path == package_root or package_root in path.parents
