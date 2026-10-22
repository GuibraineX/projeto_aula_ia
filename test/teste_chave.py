import os

from dotenv import load_dotenv
from ollama import Client

load_dotenv()

chave = os.getenv("OLLAMA_API_KEY")
print("Chave encontrada:", bool(chave))

cliente = Client(host="https://ollama.com", headers={"Authorization": f"Bearer {chave}"})
reposta = cliente.chat(
    model=os.getenv("MODELO", "gpt-oss:20b"),
    messages=[{"role": "user", "content": "Responda apenas: a conexão funcionou"}]
)
print(reposta.message.content)