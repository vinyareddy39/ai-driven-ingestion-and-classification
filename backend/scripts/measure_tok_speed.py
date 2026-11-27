import json
import time
import requests

url = "http://127.0.0.1:11434/api/generate"
payload = {
    "model": "qwen2.5-coder:7b",
    "prompt": 'Extract JSON: {"fields":[{"label":"Total","value":"$1,180.00"}]}\n\nInvoice #9982\nDate: 2024-05-15\nTotal: $1,180.00',
    "stream": False,
    "format": "json",
    "options": {"temperature": 0.0, "num_ctx": 512}
}

t0 = time.perf_counter()
resp = requests.post(url, json=payload, timeout=60)
elapsed = time.perf_counter() - t0

if resp.status_code == 200:
    data = resp.json()
    eval_count = data.get("eval_count", 0)
    eval_duration_ns = data.get("eval_duration", 1)
    prompt_eval_count = data.get("prompt_eval_count", 0)
    prompt_eval_duration_ns = data.get("prompt_eval_duration", 1)
    
    tok_sec = eval_count / (eval_duration_ns / 1e9) if eval_duration_ns > 0 else 0
    prompt_tok_sec = prompt_eval_count / (prompt_eval_duration_ns / 1e9) if prompt_eval_duration_ns > 0 else 0
    
    print(f"Tokens Generated: {eval_count}")
    print(f"Elapsed Time: {elapsed:.2f}s")
    print(f"Eval Speed: {tok_sec:.2f} tokens/second")
    print(f"Prompt Processing Speed: {prompt_tok_sec:.2f} tokens/second")
    print(f"Response: {data.get('response')}")
else:
    print(f"Error {resp.status_code}: {resp.text}")
