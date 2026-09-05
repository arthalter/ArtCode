payload = "|".join(f"context-{index:05d}" for index in range(20000))
print(payload + "|CONTEXT_OK")
