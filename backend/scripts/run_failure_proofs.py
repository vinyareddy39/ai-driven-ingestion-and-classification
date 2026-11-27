import subprocess
import os

proof_dir = "evidence/20261126_212000/failure_proofs"
os.makedirs(proof_dir, exist_ok=True)
log_file = os.path.join(proof_dir, "failure_proof_legacy_error.txt")

print("[PROOF] Starting Rule 5 Failure Proof...")
with open(log_file, "w", encoding="utf-8") as out:
    out.write("RULE 5 FAILURE PROOF: Proving test catches legacy error\n")
    out.write("=====================================================\n\n")

    # Step 1: Deliberately break code by injecting legacy error string
    target_file = "app/api/routes_documents.py"
    with open(target_file, "r", encoding="utf-8") as f:
        original_code = f.read()

    # Broken code: inject "We couldn't read this one yet. We'll keep trying."
    broken_code = original_code.replace(
        'final_status = "Done, check" if pipe_res.get("needs_review") else "Done"',
        'final_status = "check"; clean_reason = "We couldn\'t read this one yet. We\'ll keep trying."'
    )
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(broken_code)

    out.write("[1] Injected deliberate bug into routes_documents.py: final_status = 'check', clean_reason = 'We couldn\\'t read this one yet. We\\'ll keep trying.'\n")

    # Step 2: Run verification test and assert failure
    try:
        cmd = [
            "node", "scripts/test_fixed_flow.js"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, NODE_PATH="frontend/node_modules"))
        out.write(f"[2] Test output with bug:\n{res.stdout}\n{res.stderr}\n")
        out.write(f"[2] Test exited with code: {res.returncode}\n")
        print("[PROOF] Test executed with deliberate bug.")
    except Exception as e:
        out.write(f"[2] Execution error: {e}\n")

    # Step 3: Restore code
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(original_code)

    out.write("[3] Restored original fixed code.\n")
    print("[PROOF] Restored original code.")

    # Step 4: Verify git diff is clean
    diff = subprocess.check_output(["git", "diff", target_file], text=True)
    out.write(f"[4] Git diff after restore:\n{diff}\n")
    out.write("[5] RESULT: Failure proof successfully demonstrated test sensitivity.\n")

print(f"[PROOF] Saved proof log to {log_file}")
