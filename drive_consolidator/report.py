"""Rich-formatted reports for scan, dedup, and consolidation results."""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from drive_consolidator.consolidator import ConsolidationPlan
from drive_consolidator.dedup import DeduplicationResult
from drive_consolidator.scanner import DriveIndex


console = Console()


def _fmt_bytes(b: int | float) -> str:
    """Format bytes into human-readable string."""
    if b == float("inf"):
        return "Unlimited"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def print_scan_summary(index: DriveIndex):
    """Print a summary of the scan results."""
    table = Table(title="Drive Scan Summary")
    table.add_column("Account", style="cyan")
    table.add_column("Files", justify="right", style="green")
    table.add_column("Total Size", justify="right", style="yellow")

    for account, files in index.by_account.items():
        total = sum(f.size for f in files)
        table.add_row(account, str(len(files)), _fmt_bytes(total))

    table.add_section()
    table.add_row(
        "TOTAL",
        str(len(index.files)),
        _fmt_bytes(index.total_size),
        style="bold",
    )

    console.print()
    console.print(table)


def print_dedup_summary(result: DeduplicationResult):
    """Print a summary of duplicate detection."""
    console.print()
    console.print(
        Panel(
            f"[bold]Duplicate Analysis[/bold]\n\n"
            f"  Duplicate groups found: [red]{len(result.duplicate_groups)}[/red]\n"
            f"  Total duplicate files:  [red]{result.total_duplicates}[/red]\n"
            f"  Space wasted:           [red]{_fmt_bytes(result.total_wasted_bytes)}[/red]\n"
            f"  Unique files:           [green]{len(result.unique_files)}[/green]",
            title="Deduplication Results",
        )
    )

    # Show top 20 largest duplicate groups
    if result.duplicate_groups:
        table = Table(title="Top Duplicate Groups (by wasted space)")
        table.add_column("#", justify="right", style="dim")
        table.add_column("File Name", style="cyan", max_width=50)
        table.add_column("Copies", justify="right", style="red")
        table.add_column("Accounts", style="yellow")
        table.add_column("Wasted", justify="right", style="red")
        table.add_column("Method", style="dim")

        for i, group in enumerate(result.duplicate_groups[:20], 1):
            table.add_row(
                str(i),
                group.files[0].name,
                str(len(group.files)),
                ", ".join(sorted(group.accounts_involved)),
                _fmt_bytes(group.wasted_size),
                group.method,
            )

        console.print()
        console.print(table)

        if len(result.duplicate_groups) > 20:
            console.print(
                f"\n  ... and {len(result.duplicate_groups) - 20} more duplicate groups"
            )


def print_plan_summary(plan: ConsolidationPlan):
    """Print the consolidation plan for user review."""
    console.print()
    console.print(
        Panel(
            f"[bold]Consolidation Plan[/bold]\n\n"
            f"  Primary drive:    [cyan]{plan.primary_account}[/cyan]  "
            f"(free: {_fmt_bytes(plan.primary_free_bytes)})\n"
            f"  Secondary drive:  [cyan]{plan.secondary_account or 'None'}[/cyan]  "
            f"(free: {_fmt_bytes(plan.secondary_free_bytes)})\n\n"
            f"  Files to keep:      [green]{len(plan.files_to_keep)}[/green]\n"
            f"  Files to transfer:  [yellow]{len(plan.files_to_transfer)}[/yellow]  "
            f"({_fmt_bytes(plan.transfer_size_bytes)})\n"
            f"  Files to delete:    [red]{len(plan.files_to_delete)}[/red]  "
            f"({_fmt_bytes(plan.delete_size_bytes)})\n",
            title="Consolidation Plan",
            border_style="yellow",
        )
    )

    # Breakdown by account
    table = Table(title="Deletions by Account")
    table.add_column("Account", style="cyan")
    table.add_column("Files to Delete", justify="right", style="red")
    table.add_column("Space Freed", justify="right", style="green")

    by_account: dict[str, list] = {}
    for f in plan.files_to_delete:
        by_account.setdefault(f.account_name, []).append(f)

    for account, files in sorted(by_account.items()):
        total = sum(f.size for f in files)
        table.add_row(account, str(len(files)), _fmt_bytes(total))

    console.print()
    console.print(table)


def print_execution_summary(stats: dict):
    """Print results after execution."""
    console.print()
    console.print(
        Panel(
            f"[bold green]Consolidation Complete![/bold green]\n\n"
            f"  Files transferred:    [green]{stats['transferred']}[/green]"
            f"  ({_fmt_bytes(stats['bytes_transferred'])})\n"
            f"  Transfer failures:    [red]{stats['transfer_failed']}[/red]\n"
            f"  Duplicates deleted:   [green]{stats['deleted']}[/green]"
            f"  ({_fmt_bytes(stats['bytes_freed'])} freed)\n"
            f"  Delete failures:      [red]{stats['delete_failed']}[/red]\n"
            f"  Overflow to secondary:[yellow]{stats['overflow_to_secondary']}[/yellow]",
            title="Execution Summary",
            border_style="green",
        )
    )
