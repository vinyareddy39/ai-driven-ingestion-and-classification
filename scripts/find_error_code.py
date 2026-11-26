import subprocess
content = subprocess.check_output(['git', 'show', 'eee61440:app/api/routes_documents.py'], text=True).splitlines()
for i, line in enumerate(content):
    if "couldn't read this one yet" in line.lower():
        for j in range(max(0, i-10), min(len(content), i+15)):
            print(f"{j+1}: {content[j]}")
        print('-'*40)
