"""
Testa o servidor MCP SEM o modelo de linguagem.

Mesma ideia das Aulas 6 e 7: antes de chamar a LLM, confira se as
ferramentas funcionam sozinhas. Usa um banco separado (data/teste.sqlite),
então não mexe nos chamados da interface.

Rodar:  python test/teste_servidor.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJETO = Path(__file__).resolve().parent.parent  # test/ -> pasta do projeto
sys.path.insert(0, str(PROJETO))                   # para o "import agente" achar o arquivo

os.environ["FABRICA_BANCO"] = str(PROJETO / "data" / "teste.sqlite")
(PROJETO / "data" / "teste.sqlite").unlink(missing_ok=True)  # começa do zero

import agente  # noqa: E402  (importado depois de definir o banco de teste)

CASOS = [
    ("Equipamento existente", "consultar_equipamento", {"codigo": "est 02"}),
    ("Equipamento inexistente", "consultar_equipamento", {"codigo": "XYZ-99"}),
    ("Manual pelo código de erro", "buscar_manual", {"equipamento": "EST-02", "pergunta": "parou com E-12"}),
    ("Manual pelo sintoma", "buscar_manual", {"equipamento": "PRN-01", "pergunta": "tem óleo vazando no chão"}),
    ("Equipamento sem manual", "buscar_manual", {"equipamento": "INJ-04", "pergunta": "peça saindo com rebarba"}),
    ("Estoque", "consultar_estoque", {"peca": "SNS-FC-01"}),
    ("Abrir chamado", "abrir_chamado", {"equipamento": "EST-02", "sintoma": "Esteira parou com erro E-12", "prioridade": "alta", "codigo_erro": "E-12"}),
    ("Mesmo chamado de novo (duplicata)", "abrir_chamado", {"equipamento": "EST-02", "sintoma": "parou de novo, E-12", "prioridade": "alta", "codigo_erro": "E-12"}),
    ("Prioridade inválida", "abrir_chamado", {"equipamento": "CMP-01", "sintoma": "Pressão não sobe", "prioridade": "urgente"}),
    ("Reservar peça", "solicitar_reserva_peca", {"protocolo": "LAB-101", "peca": "SNS-FC-01", "quantidade": 1}),
    ("Peça sem estoque", "solicitar_reserva_peca", {"protocolo": "LAB-101", "peca": "FLT-CMP-01", "quantidade": 1}),
    ("Ferramenta bloqueada", "reiniciar_equipamento", {"codigo": "EST-02"}),
    ("Ferramenta só da aplicação", "aprovar_reserva", {"reserva": "RES-001"}),
]


async def main():
    async with agente.conectar() as sessao:
        _, resumo = await agente.descobrir(sessao)
        print("Ferramentas descobertas:", len(resumo["descobertas"]))
        for grupo in ("modelo", "aplicacao", "bloqueadas"):
            print(f"  {grupo:<11}", ", ".join(resumo[grupo]))

        for titulo, nome, argumentos in CASOS:
            # Testamos como se fosse o MODELO pedindo (mesmas permissões)
            resultado, tentativas = await agente.chamar_ferramenta(
                sessao, nome, argumentos, agente.PARA_O_MODELO)
            marca = "OK " if resultado["ok"] else "ERR"
            texto = json.dumps(resultado, ensure_ascii=False)
            print(f"\n[{marca}] {titulo}  ({tentativas} tentativa(s))\n      {texto[:300]}")

        print("\nAgora a APLICAÇÃO aprova a reserva (o botão da interface faz isto):")
        resultado, _ = await agente.chamar_ferramenta(
            sessao, "aprovar_reserva", {"reserva": "RES-001"}, agente.SO_DA_APLICACAO)
        print("     ", resultado)


if __name__ == "__main__":
    asyncio.run(main())