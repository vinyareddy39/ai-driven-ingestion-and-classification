import urllib.request
import urllib.parse
import json

BASE_URL = "http://localhost:8000"

def test_live_server():
    print("=" * 80)
    print("VERIFYING LIVE RUNNING SERVER (HTTP://LOCALHOST:8000/REVIEW)")
    print("=" * 80)
    
    # 1. GET /review
    req = urllib.request.Request(f"{BASE_URL}/review")
    with urllib.request.urlopen(req, timeout=10) as resp:
        status_code = resp.getcode()
        html = resp.read().decode("utf-8")
    print(f"1. GET /review -> HTTP Status {status_code}, HTML length: {len(html)} bytes")
    assert status_code == 200
    assert "Human Review Desk" in html
    assert "task-" in html or "table" in html
    print("   Page Header & Review Table: CONFIRMED")

    # 2. Extract a pending task ID
    import re
    match = re.search(r'hx-get="/review/([a-f0-9\-]+)"', html)
    if match:
        doc_uid = match.group(1)
        print(f"2. Discovered live review task for document UID: {doc_uid}")
        
        # 3. GET /review/{doc_uid}
        req_detail = urllib.request.Request(f"{BASE_URL}/review/{doc_uid}")
        with urllib.request.urlopen(req_detail, timeout=10) as resp_detail:
            detail_status = resp_detail.getcode()
            detail_html = resp_detail.read().decode("utf-8")
        print(f"3. GET /review/{doc_uid} -> HTTP Status {detail_status}, Length: {len(detail_html)} bytes")
        assert detail_status == 200
        assert "Document Review:" in detail_html
        print("   Document Review Detail Form: CONFIRMED")
        
        # 4. POST /review/{doc_uid}/action
        form_data = {
            "action": "CORRECT",
            "reviewer_id": "browser-qa-operator",
            "corrected_type": "invoice",
            "review_notes": "Verified and corrected through browser manual review desk check",
            "field_invoice_number": "INV-LIVE-8888",
            "field_total_amount": "1250.00"
        }
        encoded_data = urllib.parse.urlencode(form_data).encode("utf-8")
        req_action = urllib.request.Request(f"{BASE_URL}/review/{doc_uid}/action", data=encoded_data, method="POST")
        req_action.add_header("Content-Type", "application/x-www-form-urlencoded")
        
        with urllib.request.urlopen(req_action, timeout=10) as resp_action:
            action_status = resp_action.getcode()
            action_html = resp_action.read().decode("utf-8")
        print(f"4. POST /review/{doc_uid}/action -> HTTP Status {action_status}")
        assert action_status == 200
        assert "alert-success" in action_html
        print("   Action Submission & ECM Commit: CONFIRMED")
        print(f"   Server Response Banner:\n{action_html.strip()}")
    else:
        print("2. No pending review tasks currently in queue.")

if __name__ == "__main__":
    test_live_server()
