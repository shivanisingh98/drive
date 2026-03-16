"""Consolidation engine: moves unique files to primary drive, deletes duplicates."""

import io
import time
from dataclasses import dataclass, field

from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from drive_consolidator.dedup import DeduplicationResult, DuplicateGroup
from drive_consolidator.scanner import DriveFile


@dataclass
class ConsolidationPlan:
    """Plan describing what the consolidation will do."""

    files_to_keep: list[DriveFile] = field(default_factory=list)
    files_to_delete: list[DriveFile] = field(default_factory=list)
    files_to_transfer: list[DriveFile] = field(default_factory=list)
    primary_account: str = ""
    secondary_account: str | None = None
    primary_free_bytes: int = 0
    secondary_free_bytes: int = 0
    transfer_size_bytes: int = 0

    @property
    def delete_size_bytes(self) -> int:
        return sum(f.size for f in self.files_to_delete)

    @property
    def transfer_size_gb(self) -> float:
        return self.transfer_size_bytes / (1024 * 1024 * 1024)

    @property
    def delete_size_gb(self) -> float:
        return self.delete_size_bytes / (1024 * 1024 * 1024)


def get_storage_info(service) -> dict:
    """Get storage quota info for a drive account."""
    about = service.about().get(fields="storageQuota").execute()
    quota = about.get("storageQuota", {})
    limit = int(quota.get("limit", 0))
    usage = int(quota.get("usage", 0))
    return {
        "limit": limit,
        "usage": usage,
        "free": limit - usage if limit > 0 else float("inf"),
    }


def _pick_keeper(group: DuplicateGroup, primary_account: str, secondary_account: str | None) -> DriveFile:
    """Pick which file to keep from a duplicate group.

    Priority: primary account > secondary account > earliest created.
    """
    # Prefer file already on primary
    for f in group.files:
        if f.account_name == primary_account:
            return f

    # Then secondary
    if secondary_account:
        for f in group.files:
            if f.account_name == secondary_account:
                return f

    # Otherwise keep the earliest created
    return min(group.files, key=lambda f: f.created_time)


def build_plan(
    dedup_result: DeduplicationResult,
    services: dict,
) -> ConsolidationPlan:
    """Build a consolidation plan from dedup results and account info."""
    # Identify primary and secondary accounts
    primary = None
    secondary = None
    for name, info in services.items():
        if info["role"] == "primary":
            primary = name
        elif info["role"] == "secondary":
            secondary = name

    if not primary:
        raise ValueError("No account with role 'primary' found in config.")

    primary_storage = get_storage_info(services[primary]["service"])
    secondary_storage = (
        get_storage_info(services[secondary]["service"]) if secondary else None
    )

    plan = ConsolidationPlan(
        primary_account=primary,
        secondary_account=secondary,
        primary_free_bytes=primary_storage["free"],
        secondary_free_bytes=secondary_storage["free"] if secondary_storage else 0,
    )

    # Process duplicate groups
    for group in dedup_result.duplicate_groups:
        keeper = _pick_keeper(group, primary, secondary)
        plan.files_to_keep.append(keeper)

        for f in group.files:
            if f.id != keeper.id:
                plan.files_to_delete.append(f)

        # If keeper isn't on primary, we need to transfer it
        if keeper.account_name != primary:
            plan.files_to_transfer.append(keeper)

    # Process unique files not on primary
    for f in dedup_result.unique_files:
        plan.files_to_keep.append(f)
        if f.account_name != primary:
            plan.files_to_transfer.append(f)

    plan.transfer_size_bytes = sum(f.size for f in plan.files_to_transfer)

    return plan


def _get_or_create_folder(service, folder_name: str, parent_id: str | None = None) -> str:
    """Get or create a folder in Drive. Returns folder ID."""
    q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    results = service.files().list(q=q, fields="files(id)").execute()
    existing = results.get("files", [])

    if existing:
        return existing[0]["id"]

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _ensure_path(service, path: str) -> str:
    """Ensure a full folder path exists in Drive. Returns the leaf folder ID."""
    parts = [p for p in path.split("/") if p]
    parent_id = None

    for part in parts:
        parent_id = _get_or_create_folder(service, part, parent_id)

    return parent_id


def _transfer_file(
    source_service,
    dest_service,
    file: DriveFile,
    dest_folder_id: str | None,
) -> str | None:
    """Transfer a file from source drive to destination drive.

    Downloads from source, uploads to destination.
    Returns the new file ID or None on failure.
    """
    try:
        # Download from source
        request = source_service.files().get_media(fileId=file.id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        buffer.seek(0)

        # Upload to destination
        metadata = {"name": file.name}
        if dest_folder_id:
            metadata["parents"] = [dest_folder_id]

        media = MediaIoBaseUpload(buffer, mimetype=file.mime_type, resumable=True)
        uploaded = (
            dest_service.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )

        return uploaded.get("id")

    except Exception as e:
        print(f"  [!] Failed to transfer {file.name}: {e}")
        return None


def _delete_file(service, file_id: str) -> bool:
    """Delete (trash) a file from Drive."""
    try:
        service.files().update(fileId=file_id, body={"trashed": True}).execute()
        return True
    except Exception as e:
        print(f"  [!] Failed to trash file {file_id}: {e}")
        return False


def execute_plan(plan: ConsolidationPlan, services: dict) -> dict:
    """Execute the consolidation plan. Returns summary stats."""
    primary_svc = services[plan.primary_account]["service"]
    secondary_svc = (
        services[plan.secondary_account]["service"]
        if plan.secondary_account
        else None
    )

    stats = {
        "transferred": 0,
        "transfer_failed": 0,
        "deleted": 0,
        "delete_failed": 0,
        "bytes_transferred": 0,
        "bytes_freed": 0,
        "overflow_to_secondary": 0,
    }

    # Track remaining space on primary
    remaining_primary = plan.primary_free_bytes

    # Create a consolidated folder in the destination
    consolidated_folder_id = _get_or_create_folder(primary_svc, "Consolidated Media")
    secondary_folder_id = None
    if secondary_svc:
        secondary_folder_id = _get_or_create_folder(secondary_svc, "Consolidated Media")

    # Phase 1: Transfer files to primary (overflow to secondary)
    if plan.files_to_transfer:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task(
                "[cyan]Transferring files...",
                total=len(plan.files_to_transfer),
            )

            for f in plan.files_to_transfer:
                source_svc = services[f.account_name]["service"]

                # Recreate folder structure under Consolidated Media
                if f.path and "/" in f.path:
                    folder_path = f.path.rsplit("/", 1)[0]
                else:
                    folder_path = ""

                # Decide destination: primary or secondary
                if f.size <= remaining_primary:
                    dest_svc = primary_svc
                    if folder_path:
                        dest_folder = _ensure_path(dest_svc, f"Consolidated Media/{folder_path}")
                    else:
                        dest_folder = consolidated_folder_id
                    remaining_primary -= f.size
                elif secondary_svc:
                    dest_svc = secondary_svc
                    if folder_path:
                        dest_folder = _ensure_path(dest_svc, f"Consolidated Media/{folder_path}")
                    else:
                        dest_folder = secondary_folder_id
                    stats["overflow_to_secondary"] += 1
                else:
                    print(f"  [!] No space for {f.name} ({f.size_mb():.1f} MB) - skipping")
                    stats["transfer_failed"] += 1
                    progress.advance(task)
                    continue

                new_id = _transfer_file(source_svc, dest_svc, f, dest_folder)
                if new_id:
                    stats["transferred"] += 1
                    stats["bytes_transferred"] += f.size
                else:
                    stats["transfer_failed"] += 1

                progress.advance(task)

                # Rate limiting
                time.sleep(0.1)

    # Phase 2: Delete duplicates
    if plan.files_to_delete:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task(
                "[red]Deleting duplicates...",
                total=len(plan.files_to_delete),
            )

            for f in plan.files_to_delete:
                svc = services[f.account_name]["service"]
                if _delete_file(svc, f.id):
                    stats["deleted"] += 1
                    stats["bytes_freed"] += f.size
                else:
                    stats["delete_failed"] += 1

                progress.advance(task)
                time.sleep(0.05)

    return stats
