import os
import re
import json

root_dir = 'C:/ml'

patterns = [
    (r"os\.getenv\(\s*['\"]([A-Za-z0-9_]+)['\"]", "os.getenv"),
    (r"os\.environ\.get\(\s*['\"]([A-Za-z0-9_]+)['\"]", "os.environ.get"),
    (r"os\.environ\[\s*['\"]([A-Za-z0-9_]+)['\"]", "os.environ[...]"),
    (r"process\.env\.([A-Za-z0-9_]+)", "process.env.X"),
    (r"process\.env\[\s*['\"]([A-Za-z0-9_]+)['\"]", "process.env['X']"),
    (r"import\.meta\.env\.([A-Za-z0-9_]+)", "import.meta.env.X"),
]

findings = {}

skip_dirs = {'.git', 'node_modules', '.venv', '.venv311', '__pycache__', 'dist', 'build', '.pytest_cache', 'brain'}

for dirpath, dirnames, filenames in os.walk(root_dir):
    dirnames[:] = [d for d in dirnames if d not in skip_dirs]
    for fname in filenames:
        ext = os.path.splitext(fname)[1].lower()
        if ext in ['.py', '.ts', '.tsx', '.js', '.jsx', '.cjs', '.mjs', '.json', '.yaml', '.yml', '.dockerfile', '.sh', '.bat', '.ps1', ''] or fname.startswith('Dockerfile') or fname.startswith('Makefile'):
            fpath = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(fpath, root_dir).replace('\\', '/')
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    for p, kind in patterns:
                        for match in re.finditer(p, content):
                            var_name = match.group(1)
                            if var_name not in findings:
                                findings[var_name] = []
                            line_no = content[:match.start()].count('\n') + 1
                            findings[var_name].append({
                                'file': rel_path,
                                'line': line_no,
                                'kind': kind
                            })
            except Exception:
                pass

output_path = 'C:/ml/backend/scripts/env_discovery_raw.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(findings, f, indent=2)

print(f"Total distinct env vars discovered: {len(findings)}")
for k in sorted(findings.keys()):
    files_str = ", ".join(f"{item['file']}:{item['line']}" for item in findings[k][:3])
    if len(findings[k]) > 3:
        files_str += f" (+{len(findings[k])-3} more)"
    print(f"- {k} ({len(findings[k])} refs): {files_str}")
