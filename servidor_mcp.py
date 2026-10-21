"""
Servidor MCP "Fábrica Modelo" (Aula 9)
======================================
Publica as ferramentas da fábrica fictícia. Ele NÃO decide quem pode usar
cada ferramenta: isso é responsabilidade da aplicação (agente.py).

Como rodar:
  python servidor_mcp.py          -> stdio (o agente.py inicia este arquivo sozinho)
  python servidor_mcp.py --http   -> HTTP em http://127.0.0.1:8000/mcp

Atenção (stdio): não use print() aqui. A saída padrão é o canal do protocolo.
"""

import asyncio
import json
import os
import random
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

import busca

load_dotenv(Path(__file__).parent / ".env")  # para quando o servidor roda sozinho

PASTA = Path(__file__).parent / "dados"
BANCO = Path(os.getenv("FABRICA_BANCO", PASTA / "fabrica.sqlite"))
EQUIPAMENTOS = json.loads((PASTA / "equipamentos.json").read_text(encoding="utf-8"))
PECAS_INICIAS = json.loads((PASTA / "pecas.json").read_text(encoding="utf-8"))

mcp = FastMCP(
    "Fabrica Modelo",
    instructions="Ferramentas fictícias de manutenção industrial, para fins didáticos",
    log_level="WARNING", # o log vai para registros/servidor_mcp.log
)

# ------------------------------------------------------------------
# Banco de dados (SQLite): chamados, reservas e estoque
# ------------------------------------------------------------------
@contextmanager
def banco():
    con = sqlite3.connect(BANCO, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def preparar_banco():
    with banco() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS chamados (
                protocolo TEXT PRIMARY KEY, equipamento TEXT, sintoma TEXT,
                codigo_erro TEXT, prioridade TEXT, status TEXT, criado_em TEXT);
            CREATE TABLE IF NOT EXISTS reservas (
                id TEXT PRIMARY KEY, protocolo TEXT, peca TEXT, quantidade INTEGER,
                status TEXT, criado_em TEXT, decidido_em TEXT);
            CREATE TABLE IF NOT EXISTS estoque (
                peca TEXT PRIMARY KEY, descricao TEXT, quantidade INTEGER);
        """)
        for peca, info in PECAS_INICIAS.items():
            con.execute("INSERT OR IGNORE INTO estoque VALUES (?, ?, ?)",
                        (peca, info["descricao"], info["quantidade"]))


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalizar_codigo(codigo: str) -> str:
    """'est 02', 'EST02' e 'est-02' viram 'EST-02'."""
    c = codigo.strip().upper().replace(" ", "-").replace("_", "-")
    if "-" not in c and len(c) > 3:
        c = c[:3] + "-" + c[3:]
    return c

# ------------------------------------------------------------------
# Ferramentas de consulta (só leem dados)
# ------------------------------------------------------------------
@mcp.tool()
async def consultar_equipamento(
    codigo: Annotated[str, Field(description="Código do equipamento, ex.: EST-02")],
) -> dict[str, Any]:
    """Consulta um equipamento da fábrica pelo código.

    Devolve nome, linha, setor, criticidade e equipe responsável.
    """
    if os.getenv("SIMULAR_LENTIDAO") == "1" and random.random() < 0.5:
        await asyncio.sleep(5)
    c = normalizar_codigo(codigo)
    if c not in EQUIPAMENTOS:
        return {"encontrado": False, "codigo": c, "codigos_validos": list(EQUIPAMENTOS)}
    return {"encontrado": True, "codigo": c, **EQUIPAMENTOS[c]}

@mcp.tool()
def buscar_manual(
    equipamento: Annotated[str, Field(description="Código do equipamento, ex.: EST-02")],
    pergunta: Annotated[str, Field(description="Código de erro e/ou sintoma observado")],
) -> dict[str, Any]:
    """Busca nos manuais de manutenção os trechos mais relevantes.

    Use para entender códigos de erro (ex.: E-12) e sintomas. Cada trecho
    vem com a fonte, que deve ser citada na resposta.
    """
    return busca.buscar(normalizar_codigo(equipamento), pergunta)

@mcp.tool()
def consultar_estoque(
    peca: Annotated[str, Field(description="Código da peça citado no manual, ex.: SNS-FC-01")],
) -> dict[str, Any]:
    """Consulta a quantidade disponível de uma peça no almoxarifado."""
    with banco() as con:
        linha = con.execute("SELECT * FROM estoque WHERE peca = ?",
                            (peca.strip().upper(),)).fetchone()
        if linha is None:
            return {"encontrada": False, "peca": peca}
        return {"encontrada": True, **dict(linha)}

preparar_banco()

if __name__ == "__main__":
    mcp.run("streamable-http" if "--http" in sys.argv else "stdio")