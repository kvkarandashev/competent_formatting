def phantom_string(e):
    return "\\phantom{" + str(e) + "}"


LaTeX_table_newline = "\\\\"

special_LaTeX_symbols = {"#": "\\#", "\\": "{\\textbackslash}", "[": "{[}", "]": "{]}"}
# for why square brackets are dangerous see https://tex.stackexchange.com/a/34468
