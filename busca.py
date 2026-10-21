"""
Busca nos manuais (RAG, Aula 5)
===============================
Usado pelo servidor MCP na ferramenta buscar_manual.

Etapas (slide 5 da Aula 5):
  1. Preparar documentos ... cada seção "## " de um manual vira um trecho
  2. Representar e buscar .. embeddings do Gemini, como no notebook da Aula 5
  3. Devolver os trechos ... com a fonte, para o modelo citar

Se não houver GEMINI_API_KEY (ou a API falhar), a busca cai para uma
comparação de palavras (busca lexical, slide 9 da Aula 5). O resultado
informa qual método foi usado, para ninguém ser enganado.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).parent / ".env")  # antes de ler qualquer variável

PASTA = Path(__file__).parent / "dados"
BANCO = Path(os.getenv("FABRICA_BANCO", PASTA / "fabrica.sqlite"))
MODELO_EMBEDDING = os.getenv("MODELO_EMBEDDING", "gemini-embedding-001")
K = 3  # quantos trechos vão para o contexto (o K da recuperação, não o top_k da LLM)

@dataclass
class Trecho:
    fonte: str    # ex.: "EST-02 · E-12 · Sensor de fim de curso"
    equipamento: str  # ex.: "EST-02" ou "GERAL"
    texto: str  # o conteúdo do trecho do manual



# ------------------------------------------------------------------
# 1. Preparar documentos (chunking por seção)
# ------------------------------------------------------------------
def carregar_trechos() -> list[Trecho]:
    """Cada seção '## ' vira um trecho.

    Dividir por seção mantém a regra junto da sua condição (Aula 5,
    slide 7): o significado do E-12 fica no mesmo trecho da verificação.
    """
    trechos = []
    for arquivo in sorted((PASTA / "manuais").glob("*.md")):
        equipamento = arquivo.stem.upper()
        conteudo = arquivo.read_text(encoding="utf-8")
        for secao in conteudo.split("\n## ")[1:]:
            titulo, _, corpo = secao.partition("\n")
            titulo = titulo.strip()
            trechos.append(Trecho(
                fonte=f"{equipamento} · {titulo}",
                equipamento=equipamento,
                texto=f"{titulo}\n{corpo.strip()}",
            ))
    return trechos


TRECHOS = carregar_trechos()



# ------------------------------------------------------------------
# 2a. Busca semântica (embeddings)
# ------------------------------------------------------------------
def _normalizar(vetor: list[float]) -> list[float]:
    tamanho = math.sqrt(sum(x * x for x in vetor)) or 1.0
    return [x / tamanho for x in vetor]


def _embedding(textos: list[str], papel: str) -> list[list[float]]:
    """Embeddings do Gemini. O task_type diz o papel de cada texto (Aula 5, slide 10)."""
    chave = os.getenv("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("GEMINI_API_KEY não definida no .env")
    cliente = genai.Client(api_key=chave, http_option=types.HttpOptions(timeout=30_000))
    resposta = cliente.models.embed_content(
        model=MODELO_EMBEDDING,
        contents=textos,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT" if papel == "documento" else "RETRIEVAL_QUERY",
            output_dimensionality=768,
        ),
    )
    return [_normalizar(e.values) for e in resposta.embeddings]


def _vetores_dos_trechos(trechos: list[Trecho]) -> list[list[float]]:
    """Calcula os vetores uma vez e guarda no SQLite (Aula 5, slide 19)."""
    chaves = [hashlib.sha256(f"{MODELO_EMBEDDING}|{t.texto}".encode()).hexdigest()
              for t in trechos]
    con = sqlite3.connect(BANCO, timeout=10)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS vetores (chave TEXT PRIMARY KEY, vetor TEXT)")
        marcas = ",".join("?" * len(chaves))
        salvos = dict(con.execute(
            f"SELECT chave, vetor FROM vetores WHERE chave IN ({marcas})", chaves))
        faltando = [i for i, chave in enumerate(chaves) if chave not in salvos]
        if faltando:
            novos = _embedding([trechos[i].texto for i in faltando], "documento")
            for i, vetor in zip(faltando, novos):
                salvos[chaves[i]] = json.dumps(vetor)
                con.execute("INSERT OR REPLACE INTO vetores VALUES (?, ?)",
                            (chaves[i], salvos[chaves[i]]))
                con.commit()
    finally:
        con.close()
    return [json.loads(salvos[chaves]) for chave in chaves]

# ------------------------------------------------------------------
# 2b. Busca lexical (plano B, sem embeddings)
# ------------------------------------------------------------------
PARADAS = set("""a o as os um uma de da do das dos em no na nos nas e ou que com
por para se nao sim esta esse essa isso ela ele foi ser ter tem mais muito pela
pelo como mas sem sobre entre quando qual quais meu minha""".split())

def _palavras(texto: str) -> list[str]:
    """Minúsculas, sem acento, sem palavras vazias e com um 'radical' grosseiro."""
    simples = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    palavras = set()
    for p in re.findall(r"[a-z]+-\d+|[a-z0=9]+", simples):
        if p in PARADAS or len(p) < 3:
            continue
        palavras.add(p if "-" in p or p.isdigit() else p[:4])
    return palavras

def _similaridade_lexical(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))

# ------------------------------------------------------------------
# 3. Buscar e devolver com fonte
# ------------------------------------------------------------------
def _codigos_de_erro(texto: str) -> list[str]:
    """Encontra códigos como E-12, E12 ou e-7 e devolve no formato E-12 / E-07."""
    return {f"E-{int(n):02d}" for n in re.findall(r"\bE-?(\d{1,3})\b", texto.upper())}

def buscar(equipamento: str, pergunta: str, k: int = K) -> dict:
    equipamento = equipamento.strip().upper()
    # Filtro por metadado: só manauais do equipamento + normas gerais
    candidatos = [t for t in TRECHOS if t.equipamento in (equipamento, "GERAL")]

    try:
        vetores = _vetores_dos_trechos(candidatos)
        pergunta_v = _embedding([pergunta], "pergunta")[0]
        scores = [sum(a * b for a, b in zip(v, pergunta_v)) for v in vetores]
        metodo = f"semântica ({MODELO_EMBEDDING})"
    except Exception as erro:
        palavras_pergunta = _palavras(pergunta)
        scores = [_similaridade_lexical(palavras_pergunta, _palavras(t.texto))
                  for t in candidatos]
        motivo = (str(erro).splitlines() or [type(erro).__name__])[0][:80]
        metodo = f"lexical (sem embedding: {motivo})"

    # Busca híbrida simples: um código de erro citado vale mais que a semelhança
    for i, trecho in enumerate(candidatos):
        if any(codigo in trecho.fonte for codigo in _codigos_de_erro(pergunta)):
            scores[i] += 1.0

    ordem = sorted(range(len(candidatos)), key=lambda i: scores[i], reverse=True)
    return {
        "metodo": metodo,
        "tem_manual_do_equipamento": any(t.equipamento == equipamento for t in TRECHOS),
        "trechos": [
            {"fonte": candidatos[i].fonte, "texto": candidatos[i].texto,
             "score": round(scores[i], 3)}
            for i in ordem[:k] if scores[i] > 0
        ],
    }