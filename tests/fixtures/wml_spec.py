"""The MAX_CASH_VALUE_LETTER mapping spec, hand-written from the real BRD.

Used to test the deterministic evaluator against real data before trusting the
Mapping Spec Agent to produce the same structure from the .docx.
"""

CONTROL_BLOCK = {"kind": "first_present", "root": "clientInfo",
                 "candidates": ["CUSTODIAN", "OWNER"]}
PAYOR_BLOCK = {"kind": "fixed", "path": "clientInfo/PAYOR"}
NAMEF = ["firstName", "middleName", "lastName", "nameSuffix"]

WML_SPEC = {
    "document": "MAX_CASH_VALUE_LETTER",
    "defaults": {"org_switch": {"discriminator": "clientType/code", "org_value": "ORG",
                                "org_fields": ["organizationName"], "person_fields": NAMEF}},
    "letters": [
        {"id": "control", "label": "Client with control of certificate",
         "addressee": CONTROL_BLOCK, "counterparty": PAYOR_BLOCK,
         "presence": {"kind": "always"}},
        {"id": "payor", "label": "Payor",
         "addressee": PAYOR_BLOCK, "counterparty": CONTROL_BLOCK,
         "presence": {"kind": "absent_if_equal", "fields": NAMEF}},
    ],
    "slots": [
        {"slot_id": "S-02", "slot_name": "Letter Title", "brd_ref": "row 2",
         "expected": {"kind": "constant", "value": "Change of Premium"}},
        {"slot_id": "S-03", "slot_name": "Insured label", "brd_ref": "row 3",
         "expected": {"kind": "constant", "value": "Insured"}},
        {"slot_id": "S-04", "slot_name": "Insured Name", "brd_ref": "row 4",
         "expected": {"kind": "fields", "block": {"kind": "fixed", "path": "clientInfo/PRIMARY"},
                      "fields": NAMEF}},
        {"slot_id": "S-05", "slot_name": "Certificate # label", "brd_ref": "row 5",
         "expected": {"kind": "constant", "value": "Certificate #"}},
        {"slot_id": "S-06", "slot_name": "Certificate # value", "brd_ref": "row 6",
         "expected": {"kind": "fields", "block": {"kind": "root"}, "fields": ["policyId"]}},
        {"slot_id": "S-08", "slot_name": "Addressee Name", "brd_ref": "row 8",
         "expected": {"kind": "block_name", "block": {"kind": "addressee"}}},
        {"slot_id": "S-09", "slot_name": "Addressee Address", "brd_ref": "row 9",
         "expected": {"kind": "block_address", "block": {"kind": "addressee"}}},
        {"slot_id": "S-10", "slot_name": "Sales Rep heading", "brd_ref": "row 10",
         "expected": {"kind": "constant", "value": "YOUR WOODMENLIFE SALES REPRESENTATIVE"}},
        {"slot_id": "S-11", "slot_name": "Sales Rep Name", "brd_ref": "row 11",
         "expected": {"kind": "fields", "block": {"kind": "fixed", "path": "producerInfo"},
                      "fields": ["firstName", "middleName", "lastName", "suffix"]}},
        {"slot_id": "S-12", "slot_name": "Sales Rep Phone", "brd_ref": "row 12",
         "expected": {"kind": "fields", "block": {"kind": "fixed", "path": "producerInfo"},
                      "fields": ["phoneNumber"], "format": "phone"}},
        {"slot_id": "S-13", "slot_name": "Sales Rep Email", "brd_ref": "row 13",
         "expected": {"kind": "fields", "block": {"kind": "fixed", "path": "producerInfo"},
                      "fields": ["emailAddress"]}},
        {"slot_id": "S-14", "slot_name": "Activity Date", "brd_ref": "row 14",
         "expected": {"kind": "fields", "block": {"kind": "root"},
                      "fields": ["activityDate"], "format": "date"}},
        {"slot_id": "S-15", "slot_name": "Dear line", "brd_ref": "row 15",
         "expected": {"kind": "block_name", "block": {"kind": "addressee"}, "prefix": "Dear "}},
        {"slot_id": "S-16", "slot_name": "Amount applied", "brd_ref": "row 16",
         "expected": {"kind": "fields", "block": {"kind": "root"},
                      "fields": ["billingPacAmount"], "format": "currency"}},
        {"slot_id": "S-19", "slot_name": "cc: line", "brd_ref": "row 19",
         "presence": {"kind": "absent_if_equal", "left": {"kind": "addressee"},
                      "right": {"kind": "counterparty"}, "fields": NAMEF},
         "expected": {"kind": "block_name", "block": {"kind": "counterparty"}, "prefix": "cc: "}},
        {"slot_id": "S-20", "slot_name": "Footer", "brd_ref": "row 20",
         "expected": {"kind": "constant",
                      "value": "1700 Farnam Street Omaha NE 68102"}},
        # Declared but not checkable from JSON + PDF text
        {"slot_id": "S-01", "slot_name": "WoodmenLife Logo", "brd_ref": "row 1",
         "verifiable": False, "not_verifiable_reason": "Image — not present in extracted text",
         "expected": {"kind": "constant", "value": ""}},
        {"slot_id": "S-07", "slot_name": "IMB code", "brd_ref": "row 7",
         "verifiable": False, "not_verifiable_reason": "Barcode image inserted by CCS",
         "expected": {"kind": "constant", "value": ""}},
    ],
    "not_verifiable_requirements": [
        {"ref": "§1.3", "text": "4/0 simplex on approved template, 20 lb bond with spot color, "
                                "z-fold if using 7949 envelopes"},
        {"ref": "§1.8", "text": "AK1 and AK2 files generated and uploaded to WML SFTP"},
        {"ref": "§1.9", "text": "Copy of each letter retained electronically in AWD with archive "
                                "and index file"},
    ],
}
