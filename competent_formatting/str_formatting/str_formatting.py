def phantom_string(e):
    return "\\phantom{" + str(e) + "}"


LaTeX_table_newline = "\\\\"

special_LaTeX_symbols = {"#": "\\#", "\\": "{\\textbackslash}", "[": "{[}", "]": "{]}", "_": "\\_"}
# for why square brackets are dangerous see https://tex.stackexchange.com/a/34468


def replace_special_LaTeX_symbols(str_in):
    output = ""
    for i, s in enumerate(str_in):
        if (
            (s in special_LaTeX_symbols)
            and (str_in[i : i + 2] != LaTeX_table_newline)
            and (str_in[i - 1 : i + 1] != LaTeX_table_newline)
        ):
            output += special_LaTeX_symbols[s]
        else:
            output += s
    return output
