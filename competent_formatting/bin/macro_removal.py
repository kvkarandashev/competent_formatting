import click

from ..processing.macro_removal import remove_macros


def process_fields(fields):
    if fields is None:
        return []
    return fields.split(":")


@click.command()
@click.argument("filename")
@click.option(
    "--removed_fields",
    default=None,
    help="macros that are removed with the content they mark (e.g. '\\marking{text}' -> '')",
)
@click.option(
    "--opened_fields",
    default=None,
    help="macros that are removed with the content remaining where it is (e.g. '\\marking{text}' -> 'text')",
)
@click.option(
    "--removed_envs",
    default=None,
    help="environments removed with their body (e.g. '\\begin{marking}text\\end{marking}' -> '')",
)
@click.option(
    "--opened_envs",
    default=None,
    help="environments removed with their body left in place "
    "(e.g. '\\begin{marking}text\\end{marking}' -> 'text')",
)
def main(filename, removed_fields, opened_fields, removed_envs, opened_envs):
    """
    Process input TeX file FILENAME to remove temporary macros with or without their content. (Designed to make sure comments or revision-based markings left inside LaTeX files are removed.)

    Revision markup comes as environments as well as macros, so --removed_envs/--opened_envs
    do for \\begin{block}...\\end{block} what the field options do for \\macro{...}. Each option
    takes a colon-separated list, and a \\newcommand/\\newenvironment defining a listed name is
    dropped along with it.
    """
    filename_str = open(filename, "r").read()
    print(
        remove_macros(
            filename_str,
            removed_fields=process_fields(removed_fields),
            opened_fields=process_fields(opened_fields),
            removed_envs=process_fields(removed_envs),
            opened_envs=process_fields(opened_envs),
        )
    )
