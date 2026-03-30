from openai import OpenAI

client = OpenAI(
    api_key="sk-684260c32a7712aa8c36f0f76d09bfff1234706e4dc80baf8ec38de455bb67e8",
    base_url="https://newapis.xyz/v1",
)

models = client.models.list()
for m in models.data:
    print(m.id)
