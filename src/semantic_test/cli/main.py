"""CLI entrypoint for semantic-test."""

import typer

from semantic_test.cli.commands.diff import diff_command
from semantic_test.cli.commands.exposure import exposure_command
from semantic_test.cli.commands.scan import scan_command
from semantic_test.cli.commands.trace import trace_command

app = typer.Typer(help="Semantic model testing and analysis tools.")
app.command("scan")(scan_command)
app.command("diff")(diff_command)
app.command("exposure")(exposure_command)
app.command("trace")(trace_command)


def main() -> None:
    """Console script entrypoint."""
    app()


if __name__ == "__main__":
    main()
