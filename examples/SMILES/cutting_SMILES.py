from competent_formatting.SMILES import SMILES_wlinebreaks

SMILES_examples = ["CCCCClCF", "BrCCBr", "OCC(F)C(Cl)O", "Br/C=N/C(Br)=C\\Br"]

for SMILES in SMILES_examples:
    print(SMILES)
    for i in range(len(SMILES)):
        freq = i + 1
        print(freq, SMILES_wlinebreaks(SMILES, freq))
