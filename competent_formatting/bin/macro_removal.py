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
def main(filename, removed_fields, opened_fields):
    """
    Process input TeX file FILENAME to remove temporary macros with or without their content. (Designed to make sure comments or revision-based markings left inside LaTeX files are removed.)
    """
    removed_fields = process_fields(removed_fields)
    opened_fields = process_fields(opened_fields)
    filename_str = open(filename, "r").read()
    print(remove_macros(filename_str, removed_fields=removed_fields, opened_fields=opened_fields))
