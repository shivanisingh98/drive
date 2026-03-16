"""Duplicate detection across drives using content hash and name+size fallback."""

from dataclasses import dataclass, field
from drive_consolidator.scanner import DriveFile, DriveIndex


@dataclass
class DuplicateGroup:
    """A group of files that are duplicates of each other."""

    key: str  # The hash or name+size key
    method: str  # "md5" or "name_size"
    files: list[DriveFile] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def wasted_size(self) -> int:
        """Size wasted by duplicates (total - one copy)."""
        if len(self.files) <= 1:
            return 0
        return self.total_size - max(f.size for f in self.files)

    @property
    def accounts_involved(self) -> set[str]:
        return {f.account_name for f in self.files}


@dataclass
class DeduplicationResult:
    """Result of the deduplication analysis."""

    duplicate_groups: list[DuplicateGroup] = field(default_factory=list)
    unique_files: list[DriveFile] = field(default_factory=list)

    @property
    def total_duplicates(self) -> int:
        return sum(len(g.files) - 1 for g in self.duplicate_groups)

    @property
    def total_wasted_bytes(self) -> int:
        return sum(g.wasted_size for g in self.duplicate_groups)

    @property
    def total_wasted_mb(self) -> float:
        return self.total_wasted_bytes / (1024 * 1024)

    @property
    def total_wasted_gb(self) -> float:
        return self.total_wasted_bytes / (1024 * 1024 * 1024)


def find_duplicates(
    index: DriveIndex,
    dedup_options: dict,
) -> DeduplicationResult:
    """Find duplicate files across all drives.

    Strategy:
    1. Group by MD5 hash (Google Drive provides md5Checksum for non-Docs files)
    2. For files without MD5 (large files or special cases), fall back to name+size
    """
    use_drive_md5 = dedup_options.get("use_drive_md5", True)
    fallback_to_name_size = dedup_options.get("fallback_to_name_size", True)

    # Phase 1: Group by MD5
    md5_groups: dict[str, list[DriveFile]] = {}
    no_md5_files: list[DriveFile] = []

    for f in index.files:
        if use_drive_md5 and f.md5:
            md5_groups.setdefault(f.md5, []).append(f)
        else:
            no_md5_files.append(f)

    result = DeduplicationResult()

    # Collect MD5-based duplicates
    for md5, files in md5_groups.items():
        if len(files) > 1:
            group = DuplicateGroup(key=md5, method="md5", files=files)
            result.duplicate_groups.append(group)
        else:
            result.unique_files.append(files[0])

    # Phase 2: Fallback for files without MD5
    if fallback_to_name_size and no_md5_files:
        name_size_groups: dict[str, list[DriveFile]] = {}
        for f in no_md5_files:
            key = f"{f.name}|{f.size}"
            name_size_groups.setdefault(key, []).append(f)

        for key, files in name_size_groups.items():
            if len(files) > 1:
                group = DuplicateGroup(key=key, method="name_size", files=files)
                result.duplicate_groups.append(group)
            else:
                result.unique_files.append(files[0])
    else:
        result.unique_files.extend(no_md5_files)

    # Sort groups by wasted size (largest first)
    result.duplicate_groups.sort(key=lambda g: g.wasted_size, reverse=True)

    return result
