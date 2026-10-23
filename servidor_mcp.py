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
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BeforeValidator, Field

import busca

load_dotenv(Path(__file__).parent / ".env")  # para quando o servidor roda sozinho

PASTA = Path(__file__).parent / "data"
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


def minusculo_sem_acento(valor):
    """'Alta' vira 'alta' e 'Média' vira 'media'. Valores que não são texto passam como estão.

    Roda ANTES da validação (Parte 8): aceita variações inofensivas,
    mas um valor errado, como 'urgente', continua sendo recusado.
    """
    if not isinstance(valor, str):
        return valor
    simples = unicodedata.normalize("NFKD", valor.strip().lower())
    return simples.encode("ascii", "ignore").decode()


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


# ------------------------------------------------------------------
# Ferramentas de ação (gravam dados)
# ------------------------------------------------------------------
@mcp.tool()
def abrir_chamado(
    equipamento: Annotated[str, Field(description="Código do equipamento, ex.: EST-02")],
    sintoma: Annotated[str, Field(description="O que foi observado, nas palavras da pessoa")],
    prioridade: Annotated[Literal["baixa", "media", "alta"],
                        BeforeValidator(minusculo_sem_acento),
                        Field(description="Prioridade conforme as normas")],
    codigo_erro: Annotated[str, Field(description="Código de erro, ex.: E-12. Vazio se não houver")] = "",
) -> dict[str, Any]:
    """Abre um chamado de manutenção e devolve o número de protocolo.

    Se já existir um chamado aberto igual, devolve o mesmo protocolo
    em vez de criar outro (controle de duplicatas).
    """
    eq = normalizar_codigo(equipamento)
    if eq not in EQUIPAMENTOS:
        raise ValueError(f"Equipamento {eq} não existe. Válidos: {', '.join(EQUIPAMENTOS)}")
    sintoma = sintoma.strip()
    if len(sintoma) < 5:
        raise ValueError("Descreve o sintoma com pelo menos 5 caracteres.")
    codigo_erro = codigo_erro.strip().upper()

    with banco() as con:
        if codigo_erro:
            igual = con.execute(
                "SELECT protocolo FROM chamados WHERE equipamento=? AND codigo_erro=? "
                "AND status='ABERTO'", (eq, codigo_erro)).fetchone()
        else:
            igual = con.execute(
                "SELECT protocolo FROM chamados WHERE equipamento=? AND sintoma=? "
                "AND status='ABERTO'", (eq, sintoma.lower())).fetchone()
        if igual:
            # Parte 8: conta ao modelo o que o chamado JÁ tem, para ele não pedir de novo
            reservas = con.execute(
                "SELECT id, peca, quantidade, status FROM reservas WHERE protocolo=?",
                (igual["protocolo"],)).fetchall()
            return {"protocolo": igual["protocolo"], "duplicado": True,
                    "mensagem": "Já existe um chamado aberto para este problema.",
                    "reservas_do_chamado": [dict(r) for r in reservas]}
        
        total = con.execute("SELECT COUNT(*) FROM chamados").fetchone()[0]
        protocolo = f"LAB-{101 + total}"
        con.execute("INSERT INTO chamados VALUES (?, ?, ?, ?, ?, 'ABERTO', ?)",
                    (protocolo, eq, sintoma, codigo_erro, prioridade, agora()))
    return {"protocolo": protocolo, "duplicado": False, "status": "ABERTO",
            "equipe": EQUIPAMENTOS[eq]["equipe"]}

@mcp.tool()
def solicitar_reserva_peca(
    protocolo: Annotated[str, Field(description="Protocolo do chamado, ex.: LAB-101")],
    peca: Annotated[str, Field(description="Código da peça, ex.: SNS-FC-01")],
    quantidade: Annotated[int, Field(description="Quantidade de unidades, de 1 a 10",
                                     ge=1, le=10, strict=True)],
) -> dict[str, Any]:
    """Pede a reserva de uma peça para um chamado.

    A reserva fica AGUARDANDO_APROVACAO até uma pessoa responsável aprovar.
    """
    protocolo, peca = protocolo.strip().upper(), peca.strip().upper()
    with banco() as con:
        if con.execute("SELECT 1 FROM chamados WHERE protocolo=?", (protocolo,)).fetchone() is None:
            raise ValueError(f"O chamado {protocolo} não existe. Abra o chamado antes.")
        item = con.execute("SELECT * FROM estoque WHERE peca=?", (peca,)).fetchone()
        if item is None:
            raise ValueError(f"A peça {peca} não existe no almoxarifado.")
        if item["quantidade"] < quantidade:
            return {"criada": False, "motivo": "estoque insuficiente",
                    "disponivel": item["quantidade"], "peca": peca}
        igual = con.execute(
            "SELECT id FROM reservas WHERE protocolo=? AND peca=? "
            "AND status='AGUARDANDO_APROVACAO'", (protocolo, peca)).fetchone()
        if igual:
            return {"criada": False, "reserva": igual["id"], "duplicado": True,
                    "status": "AGUARDANDO_APROVACAO"}
        total = con.execute("SELECT COUNT(*) FROM reservas").fetchone()[0]
        reserva = f"RES-{total + 1:03d}"
        con.execute("INSERT INTO reservas VALUES (?, ?, ?, ?, 'AGUARDANDO_APROVACAO', ?, NULL)",
                    (reserva, protocolo, peca, quantidade, agora()))
    return {"criada": True, "reserva": reserva, "status": "AGUARDANDO_APROVACAO",
            "aviso": "A reserva só vale depois da aprovação de uma pessoa responsável."}


# ------------------------------------------------------------------
# Ferramentas que a aplicação usa, mas o MODELO não recebe
# ------------------------------------------------------------------
@mcp.tool()
def listar_chamados() -> dict[str, Any]:
    """Lista os 20 chamados mais recentes"""
    with banco() as con:
        linhas = con.execute(
            "SELECT * FROM chamados ORDER BY criado_em DESC, protocolo DESC LIMIT 20").fetchall()
    return {"chamados": [dict(l) for l in linhas]}


@mcp.tool()
def listar_reservas() -> dict[str, Any]:
    """Lista as 20 reservas de peças mais recentes."""
    with banco() as con:
        linhas = con.execute(
            "SELECT * FROM reservas ORDER BY criado_em DESC, id DESC LIMIT 20").fetchall()
    return {"reservas": [dict(l) for l in linhas]}


@mcp.tool()
def aprovar_reserva(
    reserva: Annotated[str, Field(description="Identificador da reserva, ex.: RES-001")],
) -> dict[str, Any]:
    """Aprova uma reserva pendente e baixa a peça do estoque."""
    reserva = reserva.strip().upper()
    with banco() as con:
        r = con.execute("SELECT * FROM reservas WHERE id=?", (reserva,)).fetchone()
        if r is None or r["status"] != "AGUARDANDO_APROVACAO":
            raise ValueError(f"A reserva {reserva} não está aguardando aprovação.")
        disponivel = con.execute("SELECT quantidade FROM estoque WHERE peca=?",
                                 (r["peca"],)).fetchone()[0]
        if disponivel < r["quantidade"]:
            raise ValueError(f"Estoque insuficiente: restam {disponivel} unidade(s).")
        con.execute("UPDATE estoque SET quantidade = quantidade - ? WHERE peca = ?",
                    (r["quantidade"], r["peca"]))
        con.execute("UPDATE reservas SET status = 'APROVADA', decidido_em=? WHERE id=?",
                    (agora(), reserva))
    return {"reserva": reserva, "status": "APROVADA"}


@mcp.tool()
def recusar_reserva(
    reserva: Annotated[str, Field(description="Identificador da reserva, ex.: RES-001")],
) -> dict[str, Any]:
    """Recusa uma reserva pendente."""
    reserva = reserva.strip().upper()
    with banco() as con:
        r = con.execute("SELECT status FROM reservas WHERE id=?", (reserva,)).fetchone()
        if r is None or r["status"] != "AGUARDANDO_APROVACAO":
            raise ValueError(f"A reserva {reserva} não está aguardando aprovação.")
        con.execute("UPDATE reservas SET status='RECUSADA', decidido_em=? WHERE id=?",
                    (agora(), reserva))
    return {"reserva": reserva, "status": "RECUSADA"}


@mcp.tool()
def reiniciar_equipamento(
    codigo: Annotated[str, Field(description="Código do equipamento")],
) -> dict[str, Any]:
    """Reinicia um equipamento remotamente (SIMULAÇÃO, nunca executa nada).

    Existe para mostrar que um servidor pode publicar uma ferramenta
    perigosa e a aplicação decide não entregá-la ao modelo.
    """
    return {"simulado": True, "executado": False, "codigo": normalizar_codigo(codigo),
            "aviso": "Ferramenta de demonstração. Nenhum equipamento foi comandado."}

preparar_banco()

if __name__ == "__main__":
    mcp.run("streamable-http" if "--http" in sys.argv else "stdio")
