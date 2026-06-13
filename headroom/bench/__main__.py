"""CLI entry point: ``python -m headroom.bench run --suite all``."""

from __future__ import annotations

import sys

import click

from . import adapters, loader, reporter, scorer
from ._types import BenchResult, SuiteConfig


@click.group()
def cli() -> None:
    """headroom-bench — single-command benchmark suite."""


@cli.command()
@click.option(
    "--suite",
    "suites",
    multiple=True,
    default=["all"],
    help="Suite(s) to run (all, numeric, adversarial). Repeatable.",
)
@click.option(
    "--tokenizer",
    "tokenizers",
    multiple=True,
    default=["cl100k_base"],
    help="Tokenizer encoding(s) (cl100k_base, o200k_base). Repeatable.",
)
@click.option("--csv", "csv_path", default=None, help="Write CSV to this path.")
@click.option("--md", "md_path", default=None, help="Write markdown to this path.")
@click.option("--pipeline", is_flag=True, help="Include full Headroom pipeline adapter (slow).")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
def run(
    suites: tuple[str, ...],
    tokenizers: tuple[str, ...],
    csv_path: str | None,
    md_path: str | None,
    pipeline: bool,
    verbose: bool,
) -> None:
    """Run the benchmark suite."""
    cfg = SuiteConfig(
        suites=list(suites),
        tokenizers=list(tokenizers),
        output_csv=csv_path,
        output_md=md_path,
        verbose=verbose,
    )

    # Load datasets
    datasets = []
    seen: set[str] = set()
    for suite in cfg.suites:
        for ds in loader.load_suite(suite):
            if ds.name not in seen:
                datasets.append(ds)
                seen.add(ds.name)

    if not datasets:
        click.echo("No datasets loaded.", err=True)
        sys.exit(1)

    click.echo(f"Loaded {len(datasets)} dataset(s): {[d.name for d in datasets]}")

    # Get adapters
    adapter_list = adapters.get_adapters(include_pipeline=pipeline)
    click.echo(f"Adapters: {[a.name for a in adapter_list]}")

    # Run
    results: list[BenchResult] = []
    for ds in datasets:
        for adapter in adapter_list:
            output = adapter.compress(ds.raw_json)
            for tok in cfg.tokenizers:
                result = scorer.score(ds, output, tokenizer_name=tok)
                results.append(result)
                if cfg.verbose:
                    click.echo(
                        f"  {ds.name:20s} {adapter.name:12s} {tok:14s} "
                        f"-> {result.tokens_saved_pct:5.1f}% saved"
                    )

    # Report
    click.echo("")
    md_text = reporter.write_markdown(results)
    click.echo(md_text)

    if cfg.output_csv:
        with open(cfg.output_csv, "w", newline="") as f:
            reporter.write_csv(results, f)
        click.echo(f"CSV written to {cfg.output_csv}")

    if cfg.output_md:
        with open(cfg.output_md, "w") as f:
            f.write(md_text)
        click.echo(f"Markdown written to {cfg.output_md}")


if __name__ == "__main__":
    cli()
