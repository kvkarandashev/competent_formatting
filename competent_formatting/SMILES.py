def latex_SMILES(SMILES):
    output = ""
    for el in SMILES:
        # add more "dangerous" symbols here as I recall them
        add = el
        if el in ["#"]:
            add = "\\" + add
        output += add
    return output
