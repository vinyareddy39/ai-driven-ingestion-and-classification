import os
import fitz # PyMuPDF

def create_sample_pdf(path: str, title: str, fields: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    
    # Title
    page.insert_text((50, 60), title, fontsize=18, fontname="helv", color=(0.1, 0.2, 0.4))
    
    y = 100
    for label, val in fields.items():
        page.insert_text((50, y), f"{label}: {val}", fontsize=12, fontname="helv", color=(0.1, 0.1, 0.1))
        y += 25
        
    doc.save(path)
    doc.close()

def main():
    base = os.path.abspath("data/test_folders")
    os.makedirs(base, exist_ok=True)
    
    # 1. 3 Folders (FolderA, FolderB, FolderC)
    for fld, prefix in [("FolderA", "A"), ("FolderB", "B"), ("FolderC", "C")]:
        for i in range(1, 4):
            pdf_path = os.path.join(base, "three_folders", fld, f"doc_{prefix}{i}.pdf")
            create_sample_pdf(pdf_path, f"Document {prefix}-{i}", {
                "Document ID": f"DOC-{prefix}00{i}",
                "Department": f"Unit {prefix}",
                "Status": "Verified",
                "Amount": f"${i * 150}.00"
            })
            
    # 2. Parent with nested subfolders
    parent = os.path.join(base, "parent_folder")
    create_sample_pdf(os.path.join(parent, "root_doc.pdf"), "Root Level Document", {"Category": "Root", "Priority": "Normal"})
    create_sample_pdf(os.path.join(parent, "Sub1", "sub1_doc.pdf"), "Subfolder 1 Document", {"Category": "Sub1", "Code": "S1-99"})
    create_sample_pdf(os.path.join(parent, "Sub2", "sub2_doc.pdf"), "Subfolder 2 Document", {"Category": "Sub2", "Code": "S2-88"})
    create_sample_pdf(os.path.join(parent, "Sub2", "Nested", "nested_doc.pdf"), "Deeply Nested Document", {"Category": "Nested", "Level": "3"})

    # 3. Folder with unsupported files
    unsup = os.path.join(base, "unsupported_test", "MixedFolder")
    create_sample_pdf(os.path.join(unsup, "valid_doc.pdf"), "Valid Document", {"Status": "OK"})
    # create text file
    with open(os.path.join(unsup, "notes.txt"), "w") as f:
        f.write("This is a plain text file which should be skipped.")
    with open(os.path.join(unsup, "Thumbs.db"), "wb") as f:
        f.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    with open(os.path.join(unsup, "desktop.ini"), "w") as f:
        f.write("[.ShellClassInfo]\nIconResource=...")

    # 4. Same names in different folders
    same_base = os.path.join(base, "same_names")
    create_sample_pdf(os.path.join(same_base, "Accounting", "invoice.pdf"), "Accounting Invoice", {
        "Invoice Number": "INV-ACCT-2026",
        "Total Due": "$1,450.00",
        "Entity": "Accounting Branch"
    })
    create_sample_pdf(os.path.join(same_base, "Procurement", "invoice.pdf"), "Procurement Invoice", {
        "Invoice Number": "INV-PROC-9912",
        "Total Due": "$3,820.00",
        "Entity": "Procurement Branch"
    })

    # 5. 105 files for big batch test
    large = os.path.join(base, "large_batch_100", "BulkFolder")
    for i in range(1, 106):
        create_sample_pdf(os.path.join(large, f"bulk_file_{i:03d}.pdf"), f"Bulk Record #{i}", {
            "Record ID": f"REC-{i:04d}",
            "Sequence": str(i),
            "Checksum": f"CHK-{i*7}"
        })

    print("All test folders generated successfully.")

if __name__ == "__main__":
    main()
