"""Scan Google Drive accounts and index all files."""

from dataclasses import dataclass, field
from rich.progress import Progress, SpinnerColumn, TextColumn


@dataclass
class DriveFile:
    """Represents a file in Google Drive."""

    id: str
    name: str
    mime_type: str
    size: int  # bytes, 0 for Google Docs types
    md5: str | None  # None for Google Docs types
    parents: list[str]
    account_name: str
    created_time: str
    modified_time: str
    path: str = ""  # Reconstructed path

    @property
    def is_google_doc(self) -> bool:
        return self.mime_type.startswith("application/vnd.google-apps.")

    def size_mb(self) -> float:
        return self.size / (1024 * 1024)


@dataclass
class DriveIndex:
    """Index of all files across all drives."""

    files: list[DriveFile] = field(default_factory=list)
    by_account: dict[str, list[DriveFile]] = field(default_factory=dict)
    total_size: int = 0

    def add(self, f: DriveFile):
        self.files.append(f)
        self.by_account.setdefault(f.account_name, []).append(f)
        self.total_size += f.size


def _build_folder_path_map(service, account_name: str) -> dict[str, str]:
    """Build a map of folder_id -> full path for the entire drive."""
    folder_map = {}  # id -> (name, parent_id)
    page_token = None

    while True:
        resp = (
            service.files()
            .list(
                q="mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name, parents)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )

        for f in resp.get("files", []):
            parents = f.get("parents", [])
            folder_map[f["id"]] = (f["name"], parents[0] if parents else None)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Resolve full paths
    path_cache = {}

    def resolve(folder_id):
        if folder_id in path_cache:
            return path_cache[folder_id]
        if folder_id not in folder_map:
            path_cache[folder_id] = ""
            return ""
        name, parent_id = folder_map[folder_id]
        if parent_id:
            parent_path = resolve(parent_id)
            full = f"{parent_path}/{name}" if parent_path else name
        else:
            full = name
        path_cache[folder_id] = full
        return full

    return {fid: resolve(fid) for fid in folder_map}


def scan_drive(
    service,
    account_name: str,
    scan_options: dict,
    progress: Progress | None = None,
) -> list[DriveFile]:
    """Scan a single Google Drive and return all files."""
    skip_google_docs = scan_options.get("skip_google_docs", True)
    include_trashed = scan_options.get("include_trashed", False)
    mime_filter = scan_options.get("mime_types", [])

    folder_paths = _build_folder_path_map(service, account_name)

    q_parts = []
    if not include_trashed:
        q_parts.append("trashed=false")
    q_parts.append("mimeType!='application/vnd.google-apps.folder'")

    if skip_google_docs:
        q_parts.append("not mimeType contains 'application/vnd.google-apps.'")

    if mime_filter:
        mime_clauses = " or ".join(f"mimeType='{m}'" for m in mime_filter)
        q_parts.append(f"({mime_clauses})")

    query = " and ".join(q_parts)
    fields = "nextPageToken, files(id, name, mimeType, size, md5Checksum, parents, createdTime, modifiedTime)"

    files = []
    page_token = None
    task = None
    if progress:
        task = progress.add_task(f"[cyan]Scanning {account_name}...", total=None)

    while True:
        resp = (
            service.files()
            .list(
                q=query,
                fields=fields,
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )

        for f in resp.get("files", []):
            parents = f.get("parents", [])
            parent_path = folder_paths.get(parents[0], "") if parents else ""
            file_path = f"{parent_path}/{f['name']}" if parent_path else f["name"]

            df = DriveFile(
                id=f["id"],
                name=f["name"],
                mime_type=f.get("mimeType", ""),
                size=int(f.get("size", 0)),
                md5=f.get("md5Checksum"),
                parents=parents,
                account_name=account_name,
                created_time=f.get("createdTime", ""),
                modified_time=f.get("modifiedTime", ""),
                path=file_path,
            )
            files.append(df)

        if progress and task is not None:
            progress.update(task, description=f"[cyan]Scanning {account_name}... ({len(files)} files)")

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if progress and task is not None:
        progress.update(task, description=f"[green]Done {account_name}: {len(files)} files")

    return files


def scan_all_drives(services: dict, scan_options: dict) -> DriveIndex:
    """Scan all authenticated drives and build a unified index."""
    index = DriveIndex()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        for name, svc_info in services.items():
            files = scan_drive(
                svc_info["service"],
                name,
                scan_options,
                progress=progress,
            )
            for f in files:
                index.add(f)

    return index
