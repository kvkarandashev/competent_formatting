class LaTeXScientific:
    def __init__(self, num_numerals=1):
        self.init_format_spring = "{:0." + str(num_numerals) + "e}"

    def __call__(self, number_in):
        def_sci = self.init_format_spring.format(number_in)
        parts = def_sci.split("e")
        output = parts[0]
        if len(parts) > 1:
            extra = parts[1]
            if extra != "+00":
                output += "\\cdot 10^{" + str(int(extra)) + "}"
        return r"$" + output + "$"
