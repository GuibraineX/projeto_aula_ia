import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BANCO_TESTE = Path("dados/teste_acoes.sqlite")
BANCO_TESTE.unlink(missing_ok=True)

parametros = StdioServerParameters(
    command=sys.executable,
    args=["servidor_mcp.py"],
    env={**os.environ, "FABRICA_BANCO": str(BANCO_TESTE)},
)

CASOS = [
    ("Abrir chamado", "abrir_chamado",
     {"equipamento": "EST-02", "sintoma": "Esteira parou com erro E-12", "prioridade": "alta", "codigo_erro": "E-12"}),
    ("O mesmo chamado de novo", "abrir_chamado",
     {"equipamento": "est02", "sintoma": "parou de novo, E-12", "prioridade": "alta", "codigo_erro": "e-12"}),
    ("Chamado sem código de erro", "abrir_chamado",
     {"equipamento": "CMP-01", "sintoma": "Pressão da rede não chega a 7 bar", "prioridade": "media"}),
    ("Prioridade inválida", "abrir_chamado",
     {"equipamento": "CMP-01", "sintoma": "Pressão não sobe", "prioridade": "urgente"}),
    ("Equipamento inexistente", "abrir_chamado",
     {"equipamento": "XYZ-99", "sintoma": "Barulho estranho", "prioridade": "baixa"}),
    ("Pedir peça", "solicitar_reserva_peca",
     {"protocolo": "LAB-101", "peca": "SNS-FC-01", "quantidade": 1}),
    ("Pedir a mesma peça de novo", "solicitar_reserva_peca",
     {"protocolo": "LAB-101", "peca": "SNS-FC-01", "quantidade": 1}),
    ("Peça sem estoque", "solicitar_reserva_peca",
     {"protocolo": "LAB-102", "peca": "FLT-CMP-01", "quantidade": 1}),
    ("Chamado que não existe", "solicitar_reserva_peca",
     {"protocolo": "LAB-999", "peca": "SNS-FC-01", "quantidade": 1}),
    ("Aprovar a reserva", "aprovar_reserva", {"reserva": "RES-001"}),
    ("Aprovar de novo", "aprovar_reserva", {"reserva": "RES-001"}),
    ("Estoque depois da aprovação", "consultar_estoque", {"peca": "SNS-FC-01"}),
    ("Ferramenta perigosa", "reiniciar_equipamento", {"codigo": "EST-02"}),
]


async def main():
    async with stdio_client(parametros) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as sessao:
            await sessao.initialize()

            lista = await sessao.list_tools()
            print(len(lista.tools), "ferramentas:", [f.name for f in lista.tools])

            for titulo, nome, argumentos in CASOS:
                r = await sessao.call_tool(nome, argumentos)
                if r.isError:
                    linhas = r.content[0].text.splitlines()
                    print(f"\n[ERRO] {titulo}\n       " + " | ".join(linhas[:3]))
                else:
                    print(f"\n[ok]   {titulo}\n       "
                          + json.dumps(r.structuredContent, ensure_ascii=False))

            r = await sessao.call_tool("listar_chamados", {})
            print("\nChamados no banco:", [c["protocolo"] for c in r.structuredContent["chamados"]])


asyncio.run(main())