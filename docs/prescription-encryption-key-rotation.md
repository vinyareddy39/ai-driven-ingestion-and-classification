# Prescription Column Encryption & Key Rotation Procedure

## Overview
Sensitive health fields (`PrescriptionModel.raw_text` and `ExtractedItemModel.raw_text`) are encrypted at rest using AES-128-CBC with HMAC-SHA256 authentication via Python's `cryptography.fernet.Fernet`.

## Storage Format
- When written to SQLite or PostgreSQL, raw text columns store ciphertext strings prefixed with `gAAAAA...`.
- Transparent decryption is handled at the ORM layer (`EncryptedText` TypeDecorator) upon database fetch.
- Raw SQL queries (`SELECT raw_text FROM prescriptions`) yield exclusively ciphertext, ensuring that stolen database dumps or backups never expose patient prescription text.

## Configuration
The encryption key is supplied via the environment variable:
```bash
ENCRYPTION_KEY=c2VjdXJlX2RldmVsb3BtZW50X2tleV9mb3JfcHJpdmFjeV8xMjM=
```
If not specified, a deterministic development key is utilized.

## Key Rotation Procedure

To rotate the encryption key without system downtime:

1. **Generate New Key**:
   ```python
   from cryptography.fernet import Fernet
   new_key = Fernet.generate_key().decode()
   print("NEW_KEY:", new_key)
   ```

2. **Run Re-encryption Migration**:
   Execute the key rotation script with `OLD_KEY` and `NEW_KEY`:
   ```powershell
   python scripts/rotate_encryption_key.py --old-key "$OLD_KEY" --new-key "$NEW_KEY"
   ```
   The migration:
   - Fetches all `PrescriptionModel` and `ExtractedItemModel` rows.
   - Decrypts `raw_text` using `OLD_KEY`.
   - Re-encrypts `raw_text` using `NEW_KEY`.
   - Commits within a single atomic database transaction.

3. **Promote New Key**:
   Update `ENCRYPTION_KEY` in `.env` to the new key and restart application workers.
   Archive the old key securely in your secret manager for disaster recovery audit purposes.

