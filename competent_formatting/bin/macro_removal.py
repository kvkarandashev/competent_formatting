import click

from ..processing.macro_removal import IncompleteSpecialMacro
from ._common import exit_on_leftovers, markup_from, markup_options, write_output


def process_fields(fields):
    if fields is None:
        return []
    return fields.split(":")


@click.command()
@click.argument("filename")
@click.option("--output", "-o", default=None, help="Write here instead of to stdout.")
@markup_options
@click.option(
    "--removed_fields",
    default=None,
    help="Colon-separated form of --removed_macro (e.g. '\\marking{text}' -> '')",
)
@click.option(
    "--opened_fields",
    default=None,
    help="Colon-separated form of --opened_macro (e.g. '\\marking{text}' -> 'text')",
)
@click.option(
    "--removed_envs",
    default=None,
    help="Colon-separated form of --removed_env (e.g. '\\begin{marking}text\\end{marking}' -> '')",
)
@click.option(
    "--opened_envs",
    default=None,
    help="Colon-separated form of --opened_env "
    "(e.g. '\\begin{marking}text\\end{marking}' -> 'text')",
)
def main(
    filename,
    output,
    opened_macro,
    removed_macro,
    opened_env,
    removed_env,
    removed_fields,
    opened_fields,
    removed_envs,
    opened_envs,
):
    """
    Process input TeX file FILENAME to remove temporary macros with or without their content. (Designed to make sure comments or revision-based markings left inside LaTeX files are removed.)

    Revision markup comes as environments as well as macros, so the environment options do
    for \\begin{block}...\\end{block} what the macro options do for \\macro{...}, and a
    \\newcommand/\\newenvironment defining a listed name is dropped along with it. Each name
    can be given with a repeatable option (--opened_macro rev) or in a colon-separated list
    (--opened_fields rev:add). Exits 1 if a listed name survives the cleaning.
    """
    markup = markup_from(
        opened_macro + tuple(process_fields(opened_fields)),
        removed_macro + tuple(process_fields(removed_fields)),
        opened_env + tuple(process_fields(opened_envs)),
        removed_env + tuple(process_fields(removed_envs)),
    )
    with open(filename, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        cleaned, leftovers = markup.clean(text)
    except IncompleteSpecialMacro as error:
        raise click.ClickException(f"revision markup is unbalanced: {error}") from error
    write_output(cleaned, output)
    exit_on_leftovers(leftovers)
