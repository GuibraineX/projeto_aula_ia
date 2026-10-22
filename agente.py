"""
Agente de triagem (Aulas 6, 7, 8 e 9)
=====================================
O laço de controle que liga o modelo (Ollama) às ferramentas do servidor MCP.

O que é responsabilidade DESTE arquivo (e não do modelo, nem do servidor):
  1. Escolher o modelo e onde ele roda ............... Aula 2
  2. Decidir quais ferramentas o modelo pode usar ..... Aulas 1 e 9
  3. Aplicar os quatro limites ........................ Aula 8
  4. Dar as regras do atendimento (prompt) ............ Aula 4
  5. Conectar ao servidor MCP e descobrir ferramentas . Aula 9
  6. Executar com timeout e novas tentativas .......... Aula 8
  7. Rodar o laço e parar com um motivo ............... Aulas 6 e 8
  8. Guardar o percurso como evidência ................ Aulas 1 e 2
"""

import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from ollama import AsyncClient

PASTA = Path(__file__).parent
PASTA_REGISTROS = PASTA / "registros"

load_dotenv(PASTA / ".env")


# ------------------------------------------------------------------
# 1. MODELO (Aula 2: onde o modelo está executando?)
# ------------------------------------------------------------------
# Com OLLAMA_API_KEY no .env -> Ollama Cloud (nada para baixar).
# Sem a chave -> Ollama instalado no seu computador.
CHAVE = os.getenv("OLLAMA_API_KEY")
if CHAVE:
    llm = AsyncClient(host="https://ollama.com",
                      headers={"Authorization": f"Bearer {CHAVE}"}, timeout=180)
    MODELO = os.getenv("MODELO", "gpt-oss:20b")
    ONDE = "Ollama Cloud"
else:
    llm = AsyncClient(timeout=180) # usa OLLAMA_HOST ou http://127.0.0.1:11434
    MODELO = os.getenv("MODELO", "qwen2.5:7b")
    ONDE = "Ollama local"

OPCOES = {"temperature": 0.1} # triagem pede respostas estáveis, não criativas


# ------------------------------------------------------------------
# 2. PERMISSÕES (lista de permitidas: o que não está aqui, não roda)
# ------------------------------------------------------------------
PARA_O_MODELO = {
    "consultar_equipamento", "buscar_manual", "consultar_estoque",
    "abrir_chamado", "solicitar_reserva_peca",
}
SO_DA_APLICACAO = {  # usada pela interface; o modelo nem fica sabendo que existem
    "listar_chamados", "listar_reservas", "aprovar_reserva", "recusar_reserva",
}
# Qualquer outra ferramenta descoberta (ex.: reiniciar_equipamento) fica BLOQUEADA.

# Só repetimos o que é seguro repetir (Aula 8, slide 11).
# abrir_chamado entra porque o servidor tem controle de duplicatas.
PODE_REPETIR = {"consultar_equipamento", "buscar_manual", "consultar_estoque", "abrir_chamado"}


# ------------------------------------------------------------------
# 3. OS QUATRO LIMITES (Aula 8, slide 14)
# ------------------------------------------------------------------
TIMEOUT_PADRAO = 15 # Segundos por chamada
TIMEOUTS = {"consultar_equipamento": 3, "buscar_manual": 60}
TENTATIVAS = 3 # por ferramenta
MAX_RODADAS = 6 # chamadas ao modelo
MAX_POR_RODADA = 4 # ferramentas pedidas de uma vez
MAX_FERRAMENTAS =8 # ferramentas no pedido inteiro


# ------------------------------------------------------------------
# 4. PROMPT DE SISTEMA (Aula 4: tarefa, contexto, formato e limites)
# ------------------------------------------------------------------
SISTEMA = """Você é o assistente de triagem de manutenção da Fábrica Modelo (ambiente fictício).
Objetivo: organizar cada chamado e encaminhá-lo à equipe responsável com os dados necessários.

Como trabalhar:
1. Descubra o código do equipamento (ex.: EST-02). Se a pessoa não informar, pergunte. Não adivinhe.
2. Confira o equipamento com consultar_equipamento.
3. Use buscar_manual com o código de erro e/ou o sintoma. Oriente SOMENTE com o que os trechos dizem e cite a fonte entre colchetes, ex.: [EST-02 · E-12 · Sensor de fim de curso].
4. Abra o chamado com abrir_chamado. Só diga que registrou se a ferramenta devolver um protocolo, e informe esse protocolo.
5. Se o manual indicar a troca de uma peça, consulte o estoque. Reservar peça depende de aprovação humana: use solicitar_reserva_peca e avise que a reserva aguarda aprovação.

Limites:
- Você não liga, desliga, rearma nem reinicia equipamentos. Recuse esses pedidos e oriente procurar o técnico da equipe responsável no local.
- Nunca invente códigos de erro, peças, protocolos, prazos ou procedimentos.
- Risco à segurança (fumaça, fogo, choque, vazamento grande, pessoa ferida): oriente afastar as pessoas e chamar a Segurança do Trabalho, e abra o chamado com prioridade alta.
- Se uma ferramenta devolver ok=false, explique o problema. Não finja que deu certo.

Responda em português, de forma curta e organizada."""


# ------------------------------------------------------------------
# 5. CONEXÃO COM O SERVIDOR MCP (Aula 9)
# ------------------------------------------------------------------
TRANSPORTE = f"HTTP ({os.getenv('MCP_URL')})" if os.getenv("MCP_URL") else "stdio"



@asynccontextmanager
async def conectar():
    """Abre uma sessão MCP. Por padrão inicia o servidor_mcp.py via stdio.

    Com a variável MCP_URL (ex.: http://127.0.0.1:8000/mcp), conecta por HTTP
    a um servidor que já está rodando em outro terminal.
    """
    url = os.getenv("MCP_URL")
    if url:
        async with streamable_http_client(url) as (leitura, escrita, _):
            async with ClientSession(leitura, escrita) as sessao:
                await sessao.initialize()
                yield sessao
        return

    parametro = StdioServerParameters(
        command=sys.executable,
        args=[str(PASTA / "servidor_mcp.py")],
        env=dict(os.environ),
        cwd=str(PASTA),
    )
    PASTA_REGISTROS.mkdir(exist_ok=True)
    with open(PASTA_REGISTROS / "servidor_mcp.log", "a", encoding="utf-8") as log:
        async with stdio_client(parametro, errlog=log) as (leitura, escrita):
            async with ClientSession(leitura, escrita) as sessao:
                await sessao.initialize()
                yield sessao

def para_ollama(ferramenta) -> dict:
    """Converte o esquema MCP para o formato de ferramentas do Ollama (Aula 9, slide 16)."""
    return {"type": "function", "function": {
        "name": ferramenta.name,
        "description": ferramenta.description or "",
        "parameters": ferramenta.inputSchema,
    }}


async def descobrir(sessao) -> tuple[list[dict], dict]:
    """tools/list: descobre tudo e separa pelo nível de permissao."""
    lista = await sessao.list_tools()
    nomes = [f.name for f in lista.tools]
    para_modelo = [para_ollama(f) for f in lista.tools if f.name in PARA_O_MODELO]
    resumo = {
        "descobertas": nomes,
        "modelo": [n for n in nomes if n in PARA_O_MODELO],
        "aplicacao": [n for n in nomes if n in SO_DA_APLICACAO],
        "bloqueadas": [n for n in nomes if n not in PARA_O_MODELO | SO_DA_APLICACAO],
    }
    return para_modelo, resumo


# ------------------------------------------------------------------
# 6. EXECUTAR UMA FERRAMENTA (Aula 8: isolar a falha, timeout e retry)
# ------------------------------------------------------------------
def ler_resultado(resultado) -> dict:
    """Transforma o retorno MCP em {ok, dados} ou {ok, erro} (Aula 9, slide 14)."""
    texto = "\n".join(b.text for b in resultado.content if getattr(b, "type", "") == "text")
    if resultado.isError:
        return {"ok": False, "erro": texto.strip() or "erro sem mensagem"}
    if resultado.structuredContent is not None:
        return {"ok": True, "dados": resultado.structuredContent}
    try:
        return {"ok": True, "dados": json.loads(texto)}
    except json.JSONDecodeError:
        return {"ok": False, "dados": {"texto": texto}}


async def chamar_ferramenta(sessao, nome: str, argumentos: dict,
                            permitidas: set[str]) -> tuple[dict, int]:
    """Devolve (resultado, tentativas).

    Erros da FERRAMENTA viram {"ok": False, ...}. Só uma falha da CONEXÃO
    com o servidor (ex.: o processo morreu) sobe como exceção.
    """
    if nome not in permitidas:
        return {"ok": False, "erro": f"A ferramenta '{nome}' não está autorizada."}, 0

    tentativas = TENTATIVAS if nome in PODE_REPETIR else 1
    espera = timedelta(seconds=TIMEOUTS.get(nome, TIMEOUT_PADRAO))
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = await sessao.call_tool(nome, argumentos, read_timeout_seconds=espera)
            return ler_resultado(resposta), tentativa
        except McpError as erro:
            deu_timeout = erro.erro.code == 408
            if deu_timeout and tentativa < tentativas:
                await asyncio.sleep(0.5 * 2 ** (tentativa -1))
                continue
            motivo = "não respondeu a tempo" if deu_timeout else erro.error.message or "erro sem mensagem"
            return {"ok": False,
                    "erro": f"{nome} falhou após {tentativa} tentativa(s): {motivo}"}, tentativa
    raise AssertionError("inalcançável")


async def ler_painel(sessao) -> dict:
    """Usa ferramentas SO_DA_APLICACAO para montar o painel da interface."""
    chamados, _ = await chamar_ferramenta(sessao, "listar_chamados", {}, SO_DA_APLICACAO)
    reservas, _ = await chamar_ferramenta(sessao, "listar_reservas", {}, SO_DA_APLICACAO)
    return {
        "chamados": chamados.get("dados", {}).get("chamados", []),
        "reservas": reservas.get("dados", {}).get("reservas", []),
    }


# ------------------------------------------------------------------
# 7. O LAÇO DO AGENTE (Aula 6) com os limites da Aula 8
# ------------------------------------------------------------------
async def atender(mensagens: list) -> dict:
    """Roda o laço para a última mensagem da pessoa. Acrescenta tudo em `mensagens`.

    Status possíveis (Aula 6, slide 17): final, vazio ou limite.
    Erros de conexão com o modelo sobem como exceção para a interface explicar.
    """
    inicio = time.perf_counter()
    passos, usadas, rodadas = [], 0, 0
    status = "limite"
    texto = "Parei: atingi o limite de rodadas sem chegar a uma resposta final."

    async with conectar() as sessao:
        ferramentas, _ = await descobrir(sessao)

        for rodadas in range(1, MAX_RODADAS + 1):
            resposta = await llm.chat(model=MODELO, messages=mensagens,
                                      tools=ferramentas, options=OPCOES)
            # Guarda o pedido do assistant ANTES dos resultados (Aula 7, slide 14)
            mensagens.append(resposta.message.model_dump(exclude_none=True))
            chamadas = resposta.message.tool_calls or []

            if not chamadas:
                texto = (resposta.message.content or "").strip()
                status = "final" if texto else "vazio"
                texto = texto or "(o modelo não devolveu texto)"
                break

            # Limite de execuções: recusa o LOTE inteiro com um motivo (Aula 8, slide 16)
            motivo_recusa = None
            if len(chamadas) > MAX_POR_RODADA:
                motivo_recusa = f"lote recusado: no máximo {MAX_POR_RODADA} ferramentas por vez"
            elif usadas + len(chamadas) > MAX_FERRAMENTAS:
                motivo_recusa = (f"lote recusado: limite de {MAX_FERRAMENTAS} ferramentas "
                                 "por pedido atingido; responda com o que já tem")

            for chamada in chamadas:
                nome = chamada.function.name
                argumentos = dict(chamada.function.arguments or {})
                if motivo_recusa:
                    resultado, tentativas = {"ok": False, "erro": motivo_recusa}, 0
                else:
                    resultado, tentativas = await chamar_ferramenta(
                        sessao, nome, argumentos, PARA_O_MODELO)
                    usadas += 1
                passos.append({"ferramenta": nome, "argumentos": argumentos,
                               "resultado": resultado, "tentativas": tentativas})
                # Um resultado tool para CADA chamada pedida (Aula 8, slide 16)
                mensagens.append({"role": "tool", "tool_name": nome,
                                  "content": json.dumps(resultado, ensure_ascii=False)})

        painel = await ler_painel(sessao)

    saida = {
        "texto": texto, "status": status, "rodadas": rodadas,
        "ferramentas_usadas": usadas, "passos": passos, "painel": painel,
        "segundos": round(time.perf_counter() - inicio, 1),
    }
    salvar_registro(mensagens, saida)
    return saida