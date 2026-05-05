"""prediction-bot — AI-native prediction market trading system.

Usage:
    python -m src.main status               — Check connectivity and balances
    python -m src.main scan                 — Scan markets on Kalshi + Polymarket
    python -m src.main balance              — Show Kalshi demo balance
    python -m src.main markets              — List top Kalshi markets
    python -m src.main search TEXT          — Search Polymarket for TEXT
    python -m src.main analyze TICKER       — AI analysis of a Kalshi market
    python -m src.main edge [--bankroll N]  — Full AI scan + edge ranking
"""
import sys
import json
import os

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.clients.kalshi import KalshiClient
from src.clients.polymarket import PolymarketClient
from src.scanner.market_scanner import MarketScanner
from src.analyst.news_fetcher import NewsFetcher
from src.analyst.ai_analyst import AIAnalyst
from src.edge.edge_detector import EdgeDetector

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


@cli.command()
@click.argument("ticker")
@click.option("--news/--no-news", default=True, help="Fetch news headlines (default: on)")
def analyze(ticker, news):
    """AI analysis of a single Kalshi market.

    TICKER is the Kalshi market ticker, e.g. PRES-2024-DJT.
    Fetches live price, scrapes recent news, and asks Claude for a calibrated
    probability estimate.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set. Set it to enable AI analysis.[/red]")
        console.print("  export ANTHROPIC_API_KEY=sk-ant-...")
        return

    with KalshiClient() as k:
        # Fetch this specific market
        data = k.get_markets(limit=200, status="open")
        markets = data.get("markets", [])
        match = next((m for m in markets if m.get("ticker", "").upper() == ticker.upper()), None)

        if not match:
            console.print(f"[red]Market '{ticker}' not found in open Kalshi markets.[/red]")
            console.print("Hint: run 'markets --limit 100' to list available tickers.")
            return

        title = match.get("title", match.get("subtitle", ticker))
        yes_price = match.get("yes_ask", 50) / 100
        volume = match.get("volume", 0)

    console.print(f"\n[bold]Analyzing:[/bold] {title}")
    console.print(f"  Kalshi price: Yes={yes_price*100:.0f}¢  Volume={volume:,}\n")

    # Fetch news
    headlines = []
    if news:
        console.print("[dim]Fetching news...[/dim]")
        with NewsFetcher() as nf:
            headlines = nf.fetch_for_market(title, max_results=8)
        if headlines:
            console.print(f"  Found {len(headlines)} news item(s):")
            for h in headlines:
                console.print(f"    • {h.title[:80]}")
        else:
            console.print("  [yellow]No news found.[/yellow]")
        console.print()

    # Run AI analysis
    console.print("[dim]Calling Claude for probability estimate...[/dim]\n")
    with AIAnalyst(api_key=api_key) as analyst:
        result = analyst.analyze(title, yes_price, news=headlines)

    # Display result
    direction_color = "green" if result.direction == "BUY YES" else ("red" if result.direction == "BUY NO" else "yellow")
    console.print(Panel(
        f"[bold]Market:[/bold] {result.market_title[:80]}\n"
        f"[bold]Market price:[/bold] {result.market_price*100:.1f}%  "
        f"[bold]AI estimate:[/bold] {result.ai_probability*100:.1f}%\n"
        f"[bold]Edge:[/bold] [{direction_color}]{result.edge_pct:+.1f}%[/{direction_color}]  "
        f"[bold]Signal:[/bold] [{direction_color}]{result.direction}[/{direction_color}]\n"
        f"[bold]Confidence:[/bold] {result.confidence}  "
        f"[bold]News items:[/bold] {result.news_count}\n\n"
        f"[dim]{result.reasoning}[/dim]",
        title="[bold blue]AI Analysis[/bold blue]",
        border_style="blue",
    ))
    console.print()


@cli.command()
@click.option("--limit", default=30, help="Markets to scan per platform (default 30)")
@click.option("--bankroll", default=100.0, help="Virtual bankroll in USD for sizing (default $100)")
@click.option("--min-edge", default=4.0, help="Minimum edge %% to consider (default 4)")
@click.option("--no-news", is_flag=True, default=False, help="Skip news fetching (faster)")
def edge(limit, bankroll, min_edge, no_news):
    """Full AI-powered market scan with edge detection and Kelly sizing.

    Scans Kalshi markets, runs AI analysis on top candidates,
    and ranks by expected value with Kelly-optimal bet sizes.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red]")
        console.print("  export ANTHROPIC_API_KEY=sk-ant-...")
        return

    console.print(f"\n[bold]Edge Detection Scan[/bold]  bankroll=${bankroll:.0f}  min_edge={min_edge:.0f}%\n")

    # Step 1: Scan markets
    console.print("[dim]Step 1/3: Scanning markets...[/dim]")
    with KalshiClient() as k, PolymarketClient() as p:
        scanner = MarketScanner(k, p)
        scan = scanner.full_scan(limit=limit)

    # Filter to markets with actual prices and volume
    candidates = [
        m for m in scan["kalshi_markets"]
        if m.volume > 0 and 0.05 < m.yes_price < 0.95
    ]
    candidates.sort(key=lambda m: m.volume, reverse=True)
    candidates = candidates[:15]  # top 15 by volume to analyze

    console.print(f"  Kalshi: {scan['kalshi_count']} markets | {len(candidates)} candidates for AI analysis")
    console.print(f"  Polymarket: {scan['poly_count']} markets")
    console.print(f"  Cross-platform spreads: {scan['spread_count']}\n")

    if not candidates:
        console.print("[yellow]No suitable candidates found. Try increasing --limit.[/yellow]")
        return

    # Step 2: AI analysis
    console.print(f"[dim]Step 2/3: AI analysis of {len(candidates)} markets...[/dim]")
    pairs = []
    with AIAnalyst(api_key=api_key) as analyst, NewsFetcher() as nf:
        for i, snapshot in enumerate(candidates, 1):
            console.print(f"  [{i}/{len(candidates)}] {snapshot.ticker[:40]}", end=" ")
            # Optionally fetch news
            headlines = []
            if not no_news:
                headlines = nf.fetch_for_market(snapshot.title, max_results=6)
            result = analyst.analyze(snapshot.title, snapshot.yes_price, news=headlines)
            pairs.append((snapshot, result))
            edge_sign = "+" if result.edge > 0 else ""
            console.print(f"  AI={result.ai_probability*100:.0f}% edge={edge_sign}{result.edge*100:.1f}%")

    # Step 3: Edge ranking
    console.print(f"\n[dim]Step 3/3: Ranking by expected value...[/dim]\n")
    detector = EdgeDetector(min_edge=min_edge / 100)
    opportunities = detector.rank(pairs)
    sized = detector.dollar_sizes(opportunities, bankroll)

    if not sized:
        console.print(f"[yellow]No edges found above {min_edge:.0f}%. Market may be efficiently priced.[/yellow]")
        console.print("[dim]Try lowering --min-edge or scanning more markets with --limit.[/dim]")
    else:
        table = Table(title=f"[bold green]Edge Opportunities (bankroll ${bankroll:.0f})[/bold green]")
        table.add_column("Ticker", style="cyan", max_width=25)
        table.add_column("Market", max_width=40)
        table.add_column("Mkt", justify="right")
        table.add_column("AI", justify="right", style="magenta")
        table.add_column("Edge", justify="right", style="bold")
        table.add_column("EV", justify="right", style="green")
        table.add_column("Signal", justify="center")
        table.add_column("Bet $", justify="right", style="bold yellow")

        for opp, dollar_bet in sized:
            edge_color = "green" if opp.edge > 0 else "red"
            table.add_row(
                opp.snapshot.ticker[:25],
                opp.snapshot.title[:40],
                f"{opp.bet_price*100:.0f}¢",
                f"{opp.analysis.ai_probability*100:.0f}%",
                f"[{edge_color}]{opp.edge*100:+.1f}%[/{edge_color}]",
                f"{opp.expected_value*100:.2f}%",
                f"[bold]{opp.direction}[/bold]",
                f"${dollar_bet:.2f}",
            )
        console.print(table)

    # Also show cross-platform spreads if any
    if scan["cross_market_spreads"]:
        console.print(f"\n[bold yellow]Cross-Platform Spreads (Kalshi vs Polymarket)[/bold yellow]")
        t2 = Table()
        t2.add_column("Market", max_width=45)
        t2.add_column("Kalshi Yes", justify="right", style="cyan")
        t2.add_column("Poly Yes", justify="right", style="magenta")
        t2.add_column("Spread", justify="right", style="bold yellow")
        for s in scan["cross_market_spreads"][:5]:
            t2.add_row(
                s["kalshi"].title[:45],
                f"{s['kalshi_yes']*100:.1f}%",
                f"{s['poly_yes']*100:.1f}%",
                f"{s['spread']*100:.1f}%",
            )
        console.print(t2)

    console.print()


if __name__ == "__main__":
    cli()
