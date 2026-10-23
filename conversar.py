"""
Conversa com o agente pelo terminal (Parte 6)
=============================================
Você digita o problema, o modelo decide quais ferramentas usar e responde.

Comandos:
  /aprovar RES-001   aprova uma reserva (você é a pessoa responsável)
  /recusar RES-001   recusa uma reserva
  /nova              começa uma conversa nova
  /sair              encerra

Rodar:  python conversar.py
"""

import asyncio

import agente


def descrever_erro(erro: BaseException) -> str:
    """Mostra o erro real, mesmo quando ele vem dentro de um grupo de erros."""
    raiz = agente.erro_raiz(erro)
    if hasattr(raiz, "status_code"): #erros do Ollama trazem o código HTTP
        return f"Erro {raiz.status_code} do Ollama: {raiz}"
    return f"{type(raiz).__name__}: {raiz}"


def mostrar_passos(saida: dict) -> None:
    """A evidência: quais ferramentas o modelo pediu e se funcionaram."""
    for passo in saida["passos"]:
        marca = "ok " if passo["resultado"]["ok"] else "ERR"
        argumentos = ", ".join(f"{k}={v!r}" for k, v in passo["argumentos"].items())
        print(f"  [{marca}] {passo['ferramenta']}({argumentos})")


def mostrar_pendentes(painel: dict) -> None:
    for r in painel["reservas"]:
        if r["status"] == "AGUARDANDO_APROVACAO":
            print(f"  >> {r['id']} aguarda aprovação: {r['quantidade']}x {r['peca']} "
                  f"para {r['protocolo']}  (use /aprovar {r['id']} ou /recusar {r['id']})")


async def main():
    print(f"Triagem de Manutenção · {agente.MODELO} ({agente.ONDE}) · MCP {agente.TRANSPORTE}")
    print("Descreva o problema. Comandos: /aprovar RES-..., /recusar RES-..., /nova, /sair")
    mensagens = [{"role": "system", "content": agente.SISTEMA}]

    while True:
        texto = input("\nVocê: ").strip()
        if not texto:
            continue

        if texto == "/sair":
            break

        if texto == "/nova":
            mensagens = [{"role": "system", "content": agente.SISTEMA}]
            print("   (conversa nova: o histórico foi apagado, os chamados continuam no banco)")
            continue

        comando, _, reserva = texto.partition(" ")
        if comando.startswith("/") and comando not in ("/aprovar", "/recusar"):
            print("   Comando desconhecido. Use /aprovar, /recusar, /nova ou /sair.")
            continue
        if comando in ("/aprovar", "/recusar"):
            aprovar = comando == "/aprovar"
            try:
                resultado, painel = await agente.decidir_reserva(reserva.strip(), aprovar)
            except Exception as erro:
                print("  ", descrever_erro(erro))
                continue
            if resultado["ok"]:
                acao = "aprovada" if aprovar else "recusada"
                print(f"   Reserva {reserva.strip().upper()} {acao}.")
                # O agente fica sabendo da decisão na próxima mensagem
                mensagens.append({"role": "user", "content":
                    f"[Registro da aplicação] A reserva {reserva.strip().upper()} "
                    f"foi {acao} por uma pessoa responsável."})
            else:
                print("  ", resultado["erro"])
            mostrar_pendentes(painel)
            continue

        # Uma mensagem normal: vai para o agente.
        # Trabalhamos numa CÓPIA: se der erro, o histórico anterior fica intacto.
        tentativa = mensagens + [{"role": "user", "content": texto}]
        print("   (trabalhando...)")
        try:
            saida = await agente.atender(tentativa)
        except Exception as erro:
            print("  ", descrever_erro(erro))
            continue
        mensagens = tentativa

        mostrar_passos(saida)
        print(f"\nAssistente: {saida['texto']}")
        print(f"   (status: {saida['status']} · {saida['rodadas']} rodada(s) · "
              f"{saida['ferramentas_usadas']} ferramenta(s) · {saida['segundos']} s)")
        mostrar_pendentes(saida["painel"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        pass
    print("\nAté logo!")