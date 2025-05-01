import os
import pickle as pkl

from competent_formatting.tables import LaTeXScientific, latex_table


def test_2025_dataset_solvation_tables():
    workdir = os.path.dirname(__file__)
    with open(workdir + "/test_solvation_table.pkl", "rb") as f:
        (
            solvation_table,
            float_formatter,
            solvation_midrule_positions,
            nsolvation_headers,
            solvation_cline_positions,
        ) = pkl.load(f)
    with open(workdir + "/test_atomization_table.pkl", "rb") as f:
        (
            atomization_table,
            atomization_midrule_positions,
            natomization_headers,
            atomization_cline_positions,
        ) = pkl.load(f)
    float_formatter = LaTeXScientific(num_numerals=2)
    latex_solvation_energies = latex_table(
        solvation_table,
        float_formatter=float_formatter,
        midrule_positions=solvation_midrule_positions,
        column_types="l" * nsolvation_headers,
        cline_positions=solvation_cline_positions,
    )

    latex_atomization_energies = latex_table(
        atomization_table,
        float_formatter=float_formatter,
        midrule_positions=atomization_midrule_positions,
        column_types="l" * natomization_headers,
        cline_positions=atomization_cline_positions,
    )
    assert (
        latex_solvation_energies == open(workdir + "/SolQuest_extrema_solvation.tex", "r").read()
    )
    assert (
        latex_atomization_energies
        == open(workdir + "/SolQuest_extrema_total_energy.tex", "r").read()
    )


if __name__ == "__main__":
    test_2025_dataset_solvation_tables()
