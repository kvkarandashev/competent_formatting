from .misc import LaTeX_table_newline, special_LaTeX_symbols

manysymbol_elements = ["He", "Li", "Be", "Na", "Mg", "Si", "Cl", "Br"]


def bad_SMILES_break(SMILES, possible_break):
    return SMILES[possible_break - 1 : possible_break + 1].capitalize() in manysymbol_elements


def SMILES_wlinebreaks(SMILES, linebreaks_freq):
    """
    For fitting long SMILES into narrow tables. Let me know if there is a better standard; I decided to settle to just not breaking element names.
    """
    linebreaks = [0]

    prev_good_linebreak = 0

    for possible_break in range(1, len(SMILES)):
        if bad_SMILES_break(SMILES, possible_break):
            continue
        if possible_break - prev_good_linebreak >= linebreaks_freq:
            if prev_good_linebreak in linebreaks:
                linebreaks.append(possible_break)
            else:
                linebreaks.append(prev_good_linebreak)
            prev_good_linebreak = possible_break

    output = []
    prev_linebreak = 0
    for linebreak in linebreaks[1:]:
        output.append(SMILES[prev_linebreak:linebreak])
        prev_linebreak = linebreak

    output.append(SMILES[prev_linebreak:])
    return output


def latex_SMILES(SMILES, linebreaks_freq=None):
    if linebreaks_freq is not None:
        return [
            latex_SMILES(SMILES_line)
            for SMILES_line in SMILES_wlinebreaks(SMILES, linebreaks_freq)
        ]
    output = ""
    for el_id, el in enumerate(SMILES):
        # add more "dangerous" symbols here as I recall them
        if (
            (el in special_LaTeX_symbols)
            and (SMILES[el_id : el_id + 2] != LaTeX_table_newline)
            and (SMILES[el_id - 1 : el_id + 1] != LaTeX_table_newline)
        ):
            add = special_LaTeX_symbols[el]
        else:
            add = el
        output += add
    return output
