import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

parametros = StdioServerParameters(command=sys.executable, args=["servidor_mcp.py"])


async def main():
    async with stdio_client(parametros) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as sessao:
            await sessao.initialize()

            lista = await sessao.list_tools()
            print("Ferramentas:", [f.name for f in lista.tools])

            r = await sessao.call_tool("consultar_equipamento", {"codigo": "est 02"})
            print(r.structuredContent)

            r = await sessao.call_tool("consultar_equipamento", {"codigo": "XYZ-99"})
            print(r.structuredContent)

            r = await sessao.call_tool("consultar_estoque", {"peca": "SNS-FC-01"})
            print(r.structuredContent)

            r= await sessao.call_tool("buscar_manual", {"equipamento": "est02", "pergunta": "parou com E-12"})
            print(r.structuredContent["metodo"])
            print([t["fonte"] for t in r.structuredContent["trechos"]])


asyncio.run(main())