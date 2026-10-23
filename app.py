"""
Triagem de Manutenção: interface (Gradio)
=========================================
Rodar no terminal do VS Code:   python app.py   ->   http://127.0.0.1:7860

A interface só conversa com a pessoa e mostra o painel. Todo o trabalho
de agente está em agente.py e as ferramentas estão em servidor_mcp.py.
"""

import json

import gradio as gr
from mcp.shared.exceptions import McpError
from ollama import ResponseError

import agente

COLUNAS_CHAMADOS = ["Protocolo", "Equipamento", "Prioridade", "Status", "Sintoma"]
COLUNAS_RESERVAS = ["Reserva", "Chamado", "Peça", "Qtd", "Status"]

EXEMPLOS = [
    "A EST-02 parou com erro E-12. Encaminhar à manutenção.",   # CH-101 da Aula 1
    "A máquina está estranha.",                                 # CH-102: falta informação
    "Reinicie a EST-02 remotamente agora.",                     # CH-103: fora do escopo
    "A prensa PRN-01 está vazando óleo no chão.",
    "O compressor CMP-01 não está enchendo, acho que é o filtro.",
]


# ------------------------------------------------------------------
# Conversões para a tela
# ------------------------------------------------------------------
def tabelas(painel: dict):
    """Painel (dados do servidor) -> tabelas e lista de reservas pendentes."""
    chamados = [[c["protocolo"], c["equipamento"], c["prioridade"], c["status"], c["sintoma"]]
                for c in painel["chamados"]]
    reservas = [[r["id"], r["protocolo"], r["peca"], r["quantidade"], r["status"]]
                for r in painel["reservas"]]
    pendentes = [r["id"] for r in painel["reservas"] if r["status"] == "AGUARDANDO_APROVACAO"]
    seletor = gr.update(choices=pendentes, value=pendentes[0] if pendentes else None)
    return chamados, reservas, seletor


def mostrar_passo(passo: dict) -> dict:
    """Cada ferramenta vira um bloco recolhível no chat: a evidência do que foi feito."""
    resultado = passo["resultado"]
    argumentos = ", ".join(f"{k}={v!r}" for k, v in passo["argumentos"].items())
    if resultado["ok"]:
        icone = "🔧"
    elif "não está autorizada" in resultado.get("erro", ""):
        icone = "⛔"
    else:
        icone = "⚠️"
    tentativas = f" · {passo['tentativas']} tentativas" if passo["tentativas"] > 1 else ""
    corpo = json.dumps(resultado, ensure_ascii=False, indent=1)
    if len(corpo) > 1500:
        corpo = corpo[:1500] + "\n..."
    return {
        "role": "assistant",
        "content": f"```json\n{corpo}\n```",
        "metadata": {"title": f"{icone} {passo['ferramenta']}({argumentos}){tentativas}",
                     "status": "done"},
    }


DICAS = {
    400: "o modelo aceita ferramentas (tools)? Experimente outro modelo.",
    401: "confira a OLLAMA_API_KEY no arquivo .env.",
    403: "a chave não tem permissão para esse modelo.",
    404: "o modelo existe? Confira o nome em MODELO no arquivo .env.",
    429: "limite de uso atingido. Espere um pouco e tente de novo.",
}


def explicar_erro(erro: BaseException) -> str:
    """Aula 2 (slide 'A chamada falhou'): cada erro com uma dica do que verificar."""
    erro = agente.erro_raiz(erro)
    if isinstance(erro, ResponseError):
        dica = DICAS.get(erro.status_code, "confira o endereço e o nome do modelo.")
        return f"⚠️ Erro {erro.status_code} do Ollama: {erro.error}\n\n**Dica:** {dica}"
    if isinstance(erro, ConnectionError):
        return ("⚠️ Não consegui conectar ao Ollama.\n\n**Dica:** no Ollama Cloud, confira "
                "a internet e o arquivo .env. No Ollama local, ele está aberto?")
    if "Timeout" in type(erro).__name__:
        return "⚠️ O modelo demorou demais para responder.\n\n**Dica:** tente um modelo menor."
    if isinstance(erro, McpError):
        return (f"⚠️ Falha no servidor MCP: {erro.error.message}\n\n"
                "**Dica:** veja `registros/servidor_mcp.log` e rode `python test/teste_servidor.py`.")
    return f"⚠️ {type(erro).__name__}: {erro}"


# ------------------------------------------------------------------
# Ações da interface
# ------------------------------------------------------------------
async def responder(texto: str, tela: list, historico: list):
    """Async generator: primeiro mostra 'trabalhando', depois o resultado."""
    texto = (texto or "").strip()
    if not texto:
        yield "", tela, historico, gr.skip(), gr.skip(), gr.skip()
        return

    tela = tela + [{"role": "user", "content": texto}]
    aguarde = {"role": "assistant", "content": "Consultando equipamento, manuais e ferramentas...",
               "metadata": {"title": "⏳ Trabalhando", "status": "pending"}}
    yield "", tela + [aguarde], historico, gr.skip(), gr.skip(), gr.skip()

    # Trabalhamos numa cópia: se der erro, o histórico anterior fica intacto
    mensagens = list(historico) or [{"role": "system", "content": agente.SISTEMA}]
    mensagens.append({"role": "user", "content": texto})

    try:
        saida = await agente.atender(mensagens)
    except Exception as erro:
        tela.append({"role": "assistant", "content": explicar_erro(erro)})
        yield "", tela, historico, gr.skip(), gr.skip(), gr.skip()
        return

    tela += [mostrar_passo(p) for p in saida["passos"]]
    rodape = (f"\n\n*status: {saida['status']} · {saida['rodadas']} rodada(s) · "
              f"{saida['ferramentas_usadas']} ferramenta(s) · {saida['segundos']} s*")
    tela.append({"role": "assistant", "content": saida["texto"] + rodape})
    chamados, reservas, seletor = tabelas(saida["painel"])
    yield "", tela, mensagens, chamados, reservas, seletor


async def decidir(reserva: str, aprovar: bool, tela: list, historico: list):
    """Botões Aprovar/Recusar: a decisão é da PESSOA, não do modelo (Aula 1, slide 13)."""
    if not reserva:
        gr.Warning("Não há reserva selecionada.")
        return tela, historico, gr.skip(), gr.skip(), gr.skip()
    try:
        resultado, painel = await agente.decidir_reserva(reserva, aprovar)
    except Exception as erro:
        return tela + [{"role": "assistant", "content": explicar_erro(erro)}], historico, \
            gr.skip(), gr.skip(), gr.skip()

    if resultado["ok"]:
        acao = "aprovada" if aprovar else "recusada"
        aviso = f"{'✅' if aprovar else '❌'} Reserva **{reserva}** {acao} por uma pessoa responsável."
        if historico:  # o agente fica sabendo na próxima mensagem
            historico = historico + [{"role": "user", "content":
                f"[Registro da aplicação] A reserva {reserva} foi {acao} por uma pessoa responsável."}]
    else:
        aviso = f"⚠️ Não foi possível decidir a reserva {reserva}: {resultado['erro']}"
    chamados, reservas, seletor = tabelas(painel)
    return tela + [{"role": "assistant", "content": aviso}], historico, chamados, reservas, seletor


async def aprovar(reserva, tela, historico):
    return await decidir(reserva, True, tela, historico)


async def recusar(reserva, tela, historico):
    return await decidir(reserva, False, tela, historico)


async def carregar():
    """Ao abrir a página: conecta ao servidor MCP, descobre ferramentas e lê o painel."""
    cabecalho = f"**Modelo:** {agente.MODELO} ({agente.ONDE}) · **MCP:** {agente.TRANSPORTE}"
    try:
        resumo, painel = await agente.situacao()
    except Exception as erro:
        return cabecalho, explicar_erro(erro), [], [], gr.update(choices=[])
    detalhes = (
        f"**{len(resumo['descobertas'])} ferramentas descobertas** com `tools/list`.\n\n"
        f"🤖 **Para o modelo:** {', '.join(resumo['modelo'])}\n\n"
        f"🧑 **Só a aplicação (botões e painel):** {', '.join(resumo['aplicacao'])}\n\n"
        f"⛔ **Bloqueadas:** {', '.join(resumo['bloqueadas']) or 'nenhuma'}"
    )
    chamados, reservas, seletor = tabelas(painel)
    return cabecalho, detalhes, chamados, reservas, seletor


# ------------------------------------------------------------------
# Layout
# ------------------------------------------------------------------
with gr.Blocks(title="Triagem de Manutenção") as demo:
    gr.Markdown("# 🏭 Triagem de Manutenção\n"
                "Assistente de triagem da **Fábrica Modelo** (dados fictícios, para fins didáticos).")
    cabecalho = gr.Markdown()
    historico = gr.State([])  # mensagens completas no formato do Ollama

    with gr.Row():
        with gr.Column(scale=3):
            chat = gr.Chatbot(height=540, label="Atendimento")
            caixa = gr.Textbox(placeholder="Descreva o problema. Ex.: A EST-02 parou com erro E-12",
                               show_label=False)
            with gr.Row():
                enviar = gr.Button("Enviar", variant="primary")
                nova = gr.Button("Nova conversa")
            gr.Examples(EXEMPLOS, inputs=caixa, label="Chamados de teste")

        with gr.Column(scale=2):
            gr.Markdown("### 📋 Chamados")
            tab_chamados = gr.Dataframe(headers=COLUNAS_CHAMADOS, interactive=False,
                                        wrap=True, max_height=260)
            gr.Markdown("### ✋ Reservas de peças\nVocê é a pessoa responsável: "
                        "o assistente só **pede**, quem **aprova** é você.")
            tab_reservas = gr.Dataframe(headers=COLUNAS_RESERVAS, interactive=False,
                                        max_height=200)
            seletor = gr.Dropdown(label="Reserva aguardando aprovação", choices=[])
            with gr.Row():
                botao_aprovar = gr.Button("✅ Aprovar", variant="primary")
                botao_recusar = gr.Button("❌ Recusar", variant="stop")
            with gr.Accordion("🔌 Ferramentas do servidor MCP", open=False):
                ferramentas_md = gr.Markdown()

    painel = [tab_chamados, tab_reservas, seletor]
    caixa.submit(responder, [caixa, chat, historico], [caixa, chat, historico, *painel])
    enviar.click(responder, [caixa, chat, historico], [caixa, chat, historico, *painel])
    nova.click(lambda: ([], []), None, [chat, historico])
    botao_aprovar.click(aprovar, [seletor, chat, historico], [chat, historico, *painel])
    botao_recusar.click(recusar, [seletor, chat, historico], [chat, historico, *painel])
    demo.load(carregar, None, [cabecalho, ferramentas_md, *painel])


if __name__ == "__main__":
    demo.launch(inbrowser=True)  # abre o navegador sozinho