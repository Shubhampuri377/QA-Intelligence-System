"""The live Mapping Spec Agent's output for the Oracle run, reconstructed from the
report it produced: addressee = Bill_To_Information, and the exact slot set and
expected values shown in Demo2_MappingValidationReport.html."""
CI = "Customer_Information"
AA = f"{CI}/Account_Activity"
LIVE_SPEC = {
    "letters": [{"id": "main", "label": "Main Invoice Letter",
                 "addressee": {"kind": "fixed", "path": f"{CI}/Bill_To_Information"},
                 "counterparty": {"kind": "root"}, "presence": {"kind": "always"}}],
    "defaults": {},
    "slots": [
        ("CSC Address", {"kind": "root"}, ["CSC_Address"], ""),
        ("Creation Date", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Transaction_Date"], ""),
        ("Ship To Site Number", {"kind": "fixed", "path": f"{AA}/Site_Information"},
         ["Ship_To_Site_Number"], ""),
        ("Formatted Remit To Address", {"kind": "fixed", "path": f"{CI}/Remit_To"},
         ["Formatted_Remit_To_Address"], ""),
        ("Ship To Site Name", {"kind": "fixed", "path": f"{AA}/Site_Information"},
         ["Ship_To_Site_Name"], ""),
        ("CSC Phone Number", {"kind": "root"}, ["CSC_Phone_Number"], ""),
        ("Transaction Class", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Transaction_Class"], ""),
        ("Transaction Attribute", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Transaction_Type"], ""),
        ("Transaction Total", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Transaction_Total"], "currency"),
        ("Bill-To Name", {"kind": "fixed", "path": f"{CI}/Bill_To_Information"},
         ["Customer_Name"], ""),
        ("Formatted Bill-To Address", {"kind": "fixed", "path": f"{CI}/Bill_To_Information"},
         ["Formatted_Bill_To_Address"], ""),
        ("Amount Due", {"kind": "fixed", "path": f"{CI}/Invoice_Header"}, ["Amount_Due"], "currency"),
        ("Account Number", {"kind": "fixed", "path": f"{CI}/Invoice_Header"}, ["Account_Number"], ""),
        ("Formatted Ship To Site Address", {"kind": "fixed", "path": f"{AA}/Site_Information"},
         ["Formatted_Ship_To_Address"], ""),
        ("Invoice Number", {"kind": "fixed", "path": f"{CI}/Invoice_Header"}, ["Invoice_Number"], ""),
        ("Transaction Date", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Transaction_Date"], ""),
        ("Transaction Number", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Transaction_Number"], ""),
        ("Sales Order Number", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Sales_Order_Number"], ""),
        ("Minimum Bill Delivery", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Minimum_Bill_Delivery"], ""),
        ("Purchase Order Number", {"kind": "fixed", "path": f"{AA}/Transaction_Attributes"},
         ["Purchase_Order_Number"], ""),
        ("Scan Line", {"kind": "fixed", "path": f"{CI}/Remit_To"}, ["Scan_Line"], ""),
        ("Account Discount", {"kind": "fixed", "path": f"{AA}/Account_Discount"},
         ["Account_Discount_Type"], ""),
    ],
}
LIVE_SPEC["slots"] = [
    {"slot_id": f"S{i}", "slot_name": n, "brd_ref": n, "verifiable": True,
     "expected": {"kind": "fields", "block": b, "fields": f, "format": fmt}}
    for i, (n, b, f, fmt) in enumerate(LIVE_SPEC["slots"], 1)
] + [
    {"slot_id": "S23", "slot_name": "Senior Discount", "brd_ref": "Senior Discount",
     "verifiable": False, "not_verifiable_reason": "BRD names no text or data field for this element"},
    {"slot_id": "S24", "slot_name": "Multi-use Discount etc.", "brd_ref": "Multi-use Discount etc.",
     "verifiable": False, "not_verifiable_reason": "BRD names no text or data field for this element"},
]
