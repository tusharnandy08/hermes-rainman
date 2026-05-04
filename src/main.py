"""prediction-bot — AI-native prediction market trading system.

Usage:
    python -m src.main status       — Check connectivity and balances
    python -m src.main scan         — Scan markets on Kalshi + Polymarket
    python -m src.main balance      — Show Kalshi demo balance
    python -m src.main markets      — List top Kalshi markets
    python -m src.main search TEXT  — Search Polymarket for TEXT
"""
import sys
import json

import click
from rich.console import Console
from rich.table import Table

from src.clients.kalshi import KalshiClient
from src.clients.polymarket import PolymarketClient
from src.scanner.market_scanner import MarketScanner

console = Console()


@click.group()
def cli():
    """prediction-bot: AI-native prediction market trading system."""
    pass


@cli.command()
def status():
    """Check connectivity to Kalshi demo + Polymarket."""
    console.print("\n[bold]Connectivity Check[/bold]\n")

    with KalshiClient() as k:
        ok = k.health_check()
        if ok:
            bal = k.get_balance()
            balance_cents = bal.get("balance", 0)
            console.print(f"  Kalshi Demo:   [green]✓ Connected[/green]  "
                          f"Balance: ${balance_cents/100:.2f}")
        else:
            console.print(f"  Kalshi Demo:   [red]✗ Failed[/red]")

    with PolymarketClient() as p:
        ok = p.health_check()
        console.print(f"  Polymarket:    {'[green]✓ Connected[/green]' if ok else '[red]✗ Failed[/red]'}")

    console.print()


@cli.command()
def balance():
    """Show Kalshi demo balance and portfolio value."""
    with KalshiClient() as k:
        bal = k.get_balance()
        console.print(f"\n  Balance:         ${bal.get('balance', 0)/100:.2f}")
        console.print(f"  Portfolio value: ${bal.get('portfolio_value', 0)/100:.2f}")
        console.print()


@cli.command()
@click.option("--limit", default=20, help="Number of markets to show")
def markets(limit):
    """List top active Kalshi markets."""
    with KalshiClient() as k:
        data = k.get_markets(limit=limit, status="open")

    table = Table(title="Kalshi Active Markets")
    table.add_column("Ticker", style="cyan", max_width=30)
    table.add_column("Title", max_width=50)
    table.add_column("Yes", justify="right", style="green")
    table.add_column("No", justify="right", style="red")
    table.add_column("Volume", justify="right")

    for m in data.get("markets", []):
        yes = m.get("yes_ask", 0)
        no = m.get("no_ask", 0)
        table.add_row(
            m.get("ticker", ""),
            m.get("title", m.get("subtitle", ""))[:50],
            f"{yes}¢" if yes else "—",
            f"{no}¢" if no else "—",
            str(m.get("volume", 0)),
        )
    console.print(table)


@cli.command()
@click.argument("query")
@click.option("--limit", default=10)
def search(query, limit):
    """Search Polymarket events."""
    with PolymarketClient() as p:
        events = p.search_markets(query, limit=limit)

    if not events:
        console.print(f"\nNo results for '{query}'\n")
        return

    table = Table(title=f"Polymarket: '{query}'")
    table.add_column("Question", max_width=60)
    table.add_column("Yes%", justify="right", style="green")
    table.add_column("Volume", justify="right")

    for event in events:
        for m in event.get("markets", [event]):
            prices = PolymarketClient.parse_prices(m)
            yes_pct = f"{prices[0]*100:.1f}%" if prices else "—"
            vol = m.get("volume", m.get("volumeNum", 0))
            table.add_row(
                m.get("question", m.get("title", ""))[:60],
                yes_pct,
                f"${float(vol):,.0f}" if vol else "—",
            )
    console.print(table)


@cli.command()
@click.option("--limit", default=30, help="Markets per platform")
def scan(limit):
    """Full scan of both platforms + cross-market spread detection."""
    with KalshiClient() as k, PolymarketClient() as p:
        scanner = MarketScanner(k, p)
        result = scanner.full_scan(limit=limit)

    console.print(f"\n[bold]Market Scan Results[/bold]")
    console.print(f"  Kalshi markets:  {result['kalshi_count']}")
    console.print(f"  Polymarket:      {result['poly_count']}")
    console.print(f"  Cross-spreads:   {result['spread_count']}")

    if result["cross_market_spreads"]:
        console.print(f"\n[bold yellow]Cross-Market Spreads (≥3%)[/bold yellow]")
        table = Table()
        table.add_column("Market", max_width=50)
        table.add_column("Kalshi Yes", justify="right", style="cyan")
        table.add_column("Poly Yes", justify="right", style="magenta")
        table.add_column("Spread", justify="right", style="bold yellow")

        for s in result["cross_market_spreads"]:
            table.add_row(
                s["kalshi"].title[:50],
                f"{s['kalshi_yes']*100:.1f}%",
                f"{s['poly_yes']*100:.1f}%",
                f"{s['spread']*100:.1f}%",
            )
        console.print(table)

    # Show top Kalshi markets by volume
    top_k = sorted(result["kalshi_markets"], key=lambda m: m.volume, reverse=True)[:10]
    if top_k:
        console.print(f"\n[bold]Top Kalshi Markets (by volume)[/bold]")
        table = Table()
        table.add_column("Ticker", style="cyan", max_width=25)
        table.add_column("Title", max_width=45)
        table.add_column("Yes", justify="right", style="green")
        table.add_column("Vol", justify="right")

        for m in top_k:
            table.add_row(m.ticker[:25], m.title[:45],
                          f"{m.yes_price*100:.0f}%", f"{m.volume:,.0f}")
        console.print(table)

    console.print()


if __name__ == "__main__":
    cli()
