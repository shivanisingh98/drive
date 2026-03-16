"""CLI entry point for Google Drive Consolidator."""

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.prompt import Confirm

from drive_consolidator.auth import authenticate_all
from drive_consolidator.consolidator import build_plan, execute_plan
from drive_consolidator.dedup import find_duplicates
from drive_consolidator.report import (
    print_dedup_summary,
    print_execution_summary,
    print_plan_summary,
    print_scan_summary,
)
from drive_consolidator.scanner import scan_all_drives

console = Console()


def load_config(config_path: str) -> dict:
    """Load and validate config file."""
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        console.print("Copy config.example.json to config.json and edit it.")
        sys.exit(1)

    with open(path) as f:
        config = json.load(f)

    # Validate
    accounts = config.get("accounts", [])
    if not accounts:
        console.print("[red]No accounts configured.[/red]")
        sys.exit(1)

    roles = [a["role"] for a in accounts]
    if "primary" not in roles:
        console.print("[red]No account with role 'primary' found.[/red]")
        sys.exit(1)

    return config


@click.group()
def cli():
    """Google Drive Consolidator - Deduplicate and consolidate files across multiple Google Drive accounts."""
    pass


@cli.command()
@click.option("--config", "-c", default="config.json", help="Path to config file")
def scan(config):
    """Scan all drives and show file inventory."""
    cfg = load_config(config)
    console.print("[bold]Authenticating accounts...[/bold]")
    services = authenticate_all(cfg)
    console.print(f"[green]Authenticated {len(services)} accounts.[/green]\n")

    console.print("[bold]Scanning drives...[/bold]")
    index = scan_all_drives(services, cfg.get("scan_options", {}))
    print_scan_summary(index)


@cli.command()
@click.option("--config", "-c", default="config.json", help="Path to config file")
def analyze(config):
    """Scan drives and analyze duplicates (dry-run)."""
    cfg = load_config(config)
    console.print("[bold]Authenticating accounts...[/bold]")
    services = authenticate_all(cfg)
    console.print(f"[green]Authenticated {len(services)} accounts.[/green]\n")

    console.print("[bold]Scanning drives...[/bold]")
    index = scan_all_drives(services, cfg.get("scan_options", {}))
    print_scan_summary(index)

    console.print("\n[bold]Analyzing duplicates...[/bold]")
    dedup_result = find_duplicates(index, cfg.get("dedup_options", {}))
    print_dedup_summary(dedup_result)

    console.print("\n[bold]Building consolidation plan...[/bold]")
    plan = build_plan(dedup_result, services)
    print_plan_summary(plan)

    console.print(
        "\n[yellow]This was a dry-run. No files were moved or deleted.[/yellow]"
    )
    console.print("Run [bold]consolidate[/bold] to execute the plan.")


@cli.command()
@click.option("--config", "-c", default="config.json", help="Path to config file")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def consolidate(config, yes):
    """Scan, deduplicate, and consolidate files across drives."""
    cfg = load_config(config)
    console.print("[bold]Authenticating accounts...[/bold]")
    services = authenticate_all(cfg)
    console.print(f"[green]Authenticated {len(services)} accounts.[/green]\n")

    console.print("[bold]Scanning drives...[/bold]")
    index = scan_all_drives(services, cfg.get("scan_options", {}))
    print_scan_summary(index)

    console.print("\n[bold]Analyzing duplicates...[/bold]")
    dedup_result = find_duplicates(index, cfg.get("dedup_options", {}))
    print_dedup_summary(dedup_result)

    if dedup_result.total_duplicates == 0 and not any(
        f.account_name != next(
            n for n, s in services.items() if s["role"] == "primary"
        )
        for f in dedup_result.unique_files
    ):
        console.print("\n[green]Nothing to consolidate! All files are already on the primary drive.[/green]")
        return

    console.print("\n[bold]Building consolidation plan...[/bold]")
    plan = build_plan(dedup_result, services)
    print_plan_summary(plan)

    if not yes:
        console.print()
        proceed = Confirm.ask(
            "[bold yellow]Proceed with consolidation?[/bold yellow] "
            "This will transfer files and trash duplicates"
        )
        if not proceed:
            console.print("[yellow]Aborted.[/yellow]")
            return

    console.print("\n[bold]Executing consolidation...[/bold]\n")
    stats = execute_plan(plan, services)
    print_execution_summary(stats)


def main():
    cli()


if __name__ == "__main__":
    main()
