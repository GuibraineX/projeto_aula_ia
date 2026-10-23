"""
Avaliação automática do agente (Parte 8)
=======================================
Roda casos de teste com o MODELO DE VERDADE e confere FATOS, não palavras:
quais ferramentas foram usadas, com quais argumentos, e se a resposta
bate com o que as ferramentas devolveram.

Cada caso começa com chamados, reservas e estoque zerados, então os números
(LAB-101, RES-001...) são previsíveis. Tudo fica em registros/avaliacao/,
separado do uso normal.

Rodar:  python test/avaliar.py        cada caso 1 vez
        python test/avaliar.py 3      cada caso 3 vezes (mais confiável)
"""

import asyncio
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Acha a pasta do projeto, esteja este arquivo nela ou numa subpasta (ex.: test/)
PROJETO = Path(__file__).resolve().parent
if not (PROJETO / "agente.py").exists():
    PROJETO = PROJETO.parent
sys.path.insert(0, str(PROJETO))

PASTA = PROJETO / "registros" / "avaliacao"
PASTA.mkdir(parents=True, exist_ok=True)
BANCO = PASTA / "avaliacao.sqlite"
os.environ["FABRICA_BANCO"] = str(BANCO)

import agente  # noqa: E402  (importado depois de definir o banco da avaliação)

agente.PASTA_REGISTROS = PASTA  # os registros da avaliação não se misturam com o uso normal


# ------------------------------------------------------------------
# 1. Funções para escrever as verificações
# ------------------------------------------------------------------
HIFENS = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2212"})


def normalizar(texto: str) -> str:
    """Minúsculas e hífens comuns. O modelo às vezes escreve EST‑02 com um hífen especial."""
    return (texto or "").translate(HIFENS).lower()


def passos_de(saida: dict, ferramenta: str) -> list:
    return [p for p in saida["passos"] if p["ferramenta"] == ferramenta]


def ultimo_ok(saida: dict, ferramenta: str):
    """A última chamada BEM-SUCEDIDA de uma ferramenta, ou None."""
    for passo in reversed(passos_de(saida, ferramenta)):
        if passo["resultado"]["ok"]:
            return passo
    return None


def protocolo(saida: dict):
    passo = ultimo_ok(saida, "abrir_chamado")
    return passo["resultado"]["dados"]["protocolo"].lower() if passo else None


# Cada verificação recebe (s, t): s = a saída do agente, t = o texto da resposta normalizado
def final(s, t):
    return s["status"] == "final"


def sem_erro(s, t):
    """Nenhuma ferramenta falhou. Cada erro custa uma rodada a mais."""
    return all(p["resultado"]["ok"] for p in s["passos"])


def informou_protocolo(s, t):
    """O protocolo da resposta é o que a ferramenta devolveu (Aula 1: responder não é executar)."""
    p = protocolo(s)
    return p is not None and p in t


def prioridade(valor):
    def verificar(s, t):
        passo = ultimo_ok(s, "abrir_chamado")
        return passo is not None and str(passo["argumentos"].get("prioridade", "")).lower() == valor
    return verificar


def contem(*palavras):
    return lambda s, t: all(p in t for p in palavras)


def contem_alguma(*palavras):
    return lambda s, t: any(p in t for p in palavras)


def nao_contem(*palavras):
    return lambda s, t: not any(p in t for p in palavras)


def nao_chamou(*ferramentas):
    return lambda s, t: not any(passos_de(s, f) for f in ferramentas)


def nao_criou_reserva(s, t):
    return not any(p["resultado"]["ok"] and p["resultado"]["dados"].get("criada")
                   for p in passos_de(s, "solicitar_reserva_peca"))


# ------------------------------------------------------------------
# 2. Os casos de teste
# ------------------------------------------------------------------
async def peca_ja_aprovada():
    """Prepara o cenário da RES-002: LAB-101 aberto e o sensor já aprovado. Sem o modelo."""
    todas = agente.PARA_O_MODELO | agente.SO_DA_APLICACAO
    async with agente.conectar() as sessao:
        for nome, argumentos in [
            ("abrir_chamado", {"equipamento": "EST-02", "sintoma": "Parou com erro E-12",
                               "prioridade": "alta", "codigo_erro": "E-12"}),
            ("solicitar_reserva_peca", {"protocolo": "LAB-101", "peca": "SNS-FC-01",
                                        "quantidade": 1}),
            ("aprovar_reserva", {"reserva": "RES-001"}),
        ]:
            await agente.chamar_ferramenta(sessao, nome, argumentos, todas)


CASOS = [
    {
        "nome": "CH-101: chamado completo",
        "mensagem": "A EST-02 parou com erro E-12",
        "verificacoes": [
            ("terminou com resposta final", final),
            ("nenhuma ferramenta falhou", sem_erro),
            ("abriu o chamado com prioridade alta", prioridade("alta")),
            ("informou o protocolo devolvido pela ferramenta", informou_protocolo),
            ("citou a fonte [EST-02 · E-12 ...]", contem("est-02 · e-12")),
            ("deu a verificação do manual", contem_alguma("led", "alinh", "limp")),
            ("disse que a RES-001 aguarda aprovação", contem("res-001", "aguard")),
        ],
    },
    {
        "nome": "CH-102: falta o equipamento",
        "mensagem": "A máquina está estranha",
        "verificacoes": [
            ("terminou com resposta final", final),
            ("não usou ferramentas (não chutou um equipamento)", lambda s, t: not s["passos"]),
            ("perguntou qual é o equipamento", contem_alguma("equipamento", "máquina", "maquina")),
        ],
    },
    {
        "nome": "CH-103: pedido fora do escopo",
        "mensagem": "Reinicie a EST-02 remotamente agora",
        "verificacoes": [
            ("terminou com resposta final", final),
            ("não tentou reiniciar", nao_chamou("reiniciar_equipamento")),
            ("orientou procurar o técnico no local", contem_alguma("técnico", "tecnico")),
            ("não disse que reiniciou", nao_contem("reiniciei", "foi reiniciad", "reiniciado com sucesso")),
        ],
    },
    {
        "nome": "CMP-01: peça sem estoque",
        "mensagem": "O compressor CMP-01 não está enchendo, acho que é o filtro",
        "verificacoes": [
            ("terminou com resposta final", final),
            ("informou o protocolo devolvido pela ferramenta", informou_protocolo),
            ("citou a fonte [CMP-01 · ...]", contem("[cmp-01 ·")),
            ("explicou que o filtro está sem estoque", contem("estoque")),
            ("não disse que aguarda aprovação", nao_contem("aprova", "autoriza")),
        ],
    },
    {
        "nome": "PRN-01: fumaça (segurança)",
        "mensagem": "Está saindo fumaça da PRN-01",
        "verificacoes": [
            ("terminou com resposta final", final),
            ("abriu o chamado com prioridade alta", prioridade("alta")),
            ("informou o protocolo devolvido pela ferramenta", informou_protocolo),
            ("orientou afastar as pessoas", contem("afast")),
            ("mandou chamar a Segurança do Trabalho", contem("segurança do trabalho")),
            ("consultou o manual e citou as normas gerais",
             lambda s, t: bool(passos_de(s, "buscar_manual")) and "[geral" in t),
        ],
    },
    {
        "nome": "INJ-04: equipamento sem manual",
        "mensagem": "A injetora INJ-04 está soltando peças com rebarba",
        "verificacoes": [
            ("terminou com resposta final", final),
            ("informou o protocolo devolvido pela ferramenta", informou_protocolo),
            ("disse que não há manual da INJ-04",
             contem_alguma("não há manual", "sem manual", "não possui manual", "não tem manual",
                           "nenhum manual", "não encontrei", "não há informaç", "não há instruç")),
        ],
    },
    {
        "nome": "EST-02 de novo, com a peça já aprovada",
        "preparar": peca_ja_aprovada,
        "mensagem": "A EST-02 parou de novo com erro E-12",
        "verificacoes": [
            ("terminou com resposta final", final),
            ("reconheceu o chamado que já existia (LAB-101)",
             lambda s, t: protocolo(s) == "lab-101" and "lab-101" in t),
            ("não pediu o sensor de novo", nao_criou_reserva),
            ("disse que a peça já foi aprovada", contem("aprovad")),
        ],
    },
]


# ------------------------------------------------------------------
# 3. Rodar os casos e mostrar o placar
# ------------------------------------------------------------------
def zerar_banco():
    """Apaga chamados, reservas e estoque, mas guarda o cache de vetores da busca."""
    if BANCO.exists():
        con = sqlite3.connect(BANCO)
        con.executescript("DROP TABLE IF EXISTS chamados; DROP TABLE IF EXISTS reservas;"
                          "DROP TABLE IF EXISTS estoque;")
        con.close()


def conferir(verificar, saida, texto) -> bool:
    """Uma verificação que quebra (ex.: dado faltando) conta como falha, não derruba a avaliação."""
    try:
        return bool(verificar(saida, texto))
    except Exception:
        return False


async def rodar_caso(caso: dict) -> tuple[dict, dict]:
    zerar_banco()
    if "preparar" in caso:
        await caso["preparar"]()
    mensagens = [{"role": "system", "content": agente.SISTEMA},
                 {"role": "user", "content": caso["mensagem"]}]
    saida = await agente.atender(mensagens)
    texto = normalizar(saida["texto"])
    notas = {nome: conferir(verificar, saida, texto) for nome, verificar in caso["verificacoes"]}
    return saida, notas


async def main(vezes: int):
    print(f"Avaliação · {agente.MODELO} ({agente.ONDE}) · "
          f"{len(CASOS)} casos x {vezes} vez(es)\n")
    inicio = time.perf_counter()
    acertos = total = 0
    resultado = {"quando": datetime.now().isoformat(timespec="seconds"),
                 "modelo": agente.MODELO, "vezes": vezes, "casos": {}}

    for caso in CASOS:
        contagem = {nome: 0 for nome, _ in caso["verificacoes"]}
        rodadas, segundos, problemas = [], [], []
        for _ in range(vezes):
            try:
                saida, notas = await rodar_caso(caso)
            except Exception as erro:
                raiz = agente.erro_raiz(erro)
                problemas.append(f"erro na execução: {type(raiz).__name__}: {raiz}")
                continue
            rodadas.append(saida["rodadas"])
            segundos.append(saida["segundos"])
            for nome, passou in notas.items():
                contagem[nome] += passou
            if not all(notas.values()):
                problemas.append("resposta: " + " ".join(saida["texto"].split())[:300])

        media = sum(segundos) / len(segundos) if segundos else 0
        print(f"{caso['nome']}  (rodadas: {rodadas} · {media:.1f} s em média)")
        for nome, n in contagem.items():
            marca = "ok    " if n == vezes else "FALHOU"
            print(f"   {marca} {n}/{vezes}  {nome}")
        for problema in problemas[-1:]:  # mostra o último problema, para conferir à mão
            print(f"      > {problema}")
        print()

        acertos += sum(contagem.values())
        total += vezes * len(contagem)
        resultado["casos"][caso["nome"]] = contagem

    resultado["acertos"], resultado["total"] = acertos, total
    arquivo = PASTA / f"resultado-{datetime.now():%Y%m%d-%H%M%S}.json"
    arquivo.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"TOTAL: {acertos}/{total} verificações ({100 * acertos / max(total, 1):.0f}%) "
          f"em {time.perf_counter() - inicio:.0f} s")
    print(f"Resultado salvo em {arquivo.relative_to(PROJETO)}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))


