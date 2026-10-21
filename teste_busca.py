import busca

print("Trechos carregados:", len(busca.TRECHOS))
for t in busca.TRECHOS[:3]:
    print(" -", t.fonte)

for equipamento, pergunta in [
    ("EST-02", "parou com erro E-12"),
    ("PRN-01", "tem óleo vazando no chão"),
    ("CMP-01", "não está enchendo, acho que é o filtro"),
    ("INJ-04", "peça saindo com rebarba"),
]:
    r = busca.buscar(equipamento, pergunta)
    print(f"\n{equipamento} | {pergunta}")
    print("  método:", r["metodo"])
    print("  tem manual próprio:", r["tem_manual_do_equipamento"])
    for t in r["trechos"]:
        print(f"  {t['score']:<6}  {t['fonte']}")