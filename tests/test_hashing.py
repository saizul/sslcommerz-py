import hashlib

import pytest

from sslcommerz_py import HashVerificationError, compute_signature, verify_signature
from sslcommerz_py.hashing import build_hash_string, require_valid_signature

from .conftest import STORE_PASSWD, ipn_form


def md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()  # noqa: S324


def test_hash_string_follows_reference_algorithm():
    payload = {"verify_key": "tran_id,amount,status", "tran_id": "T1", "amount": "10.00", "status": "VALID"}
    expected = f"amount=10.00&status=VALID&store_passwd={md5('secret')}&tran_id=T1"
    assert build_hash_string(payload, "secret") == expected
    assert compute_signature(payload, "secret") == md5(expected)


def test_keys_are_sorted_in_byte_order():
    payload = {"verify_key": "value_a,Zeta,amount", "value_a": "x", "Zeta": "z", "amount": "1"}
    assert build_hash_string(payload, "p").split("&")[0] == "Zeta=z"


def test_missing_signed_field_hashes_as_empty():
    payload = {"verify_key": "tran_id,missing", "tran_id": "T1"}
    assert "missing=&" in build_hash_string(payload, "p")


def test_whitespace_and_empty_keys_ignored():
    a = {"verify_key": " tran_id , ,amount,", "tran_id": "T", "amount": "1"}
    b = {"verify_key": "tran_id,amount", "tran_id": "T", "amount": "1"}
    assert build_hash_string(a, "p") == build_hash_string(b, "p")


def test_verify_valid_payload():
    assert verify_signature(ipn_form(), STORE_PASSWD)


def test_verify_accepts_uppercase_sign():
    form = ipn_form()
    form["verify_sign"] = form["verify_sign"].upper()
    assert verify_signature(form, STORE_PASSWD)


def test_tampered_amount_fails():
    form = ipn_form()
    form["amount"] = "1.00"
    assert not verify_signature(form, STORE_PASSWD)


def test_wrong_password_fails():
    assert not verify_signature(ipn_form(passwd="other"), STORE_PASSWD)


def test_unsigned_field_change_is_not_detected():
    # Only fields listed in verify_key are covered by the signature.
    form = ipn_form()
    form["verify_key"] = "tran_id,amount"
    form["verify_sign"] = compute_signature(form, STORE_PASSWD)
    form["card_brand"] = "CHANGED"
    assert verify_signature(form, STORE_PASSWD)


def test_missing_fields_fail():
    form = ipn_form()
    del form["verify_sign"]
    assert not verify_signature(form, STORE_PASSWD)
    with pytest.raises(HashVerificationError, match="no verify_sign"):
        require_valid_signature(form, STORE_PASSWD)


def test_require_raises_on_mismatch():
    form = ipn_form()
    form["tran_id"] = "OTHER"
    with pytest.raises(HashVerificationError, match="does not match"):
        require_valid_signature(form, STORE_PASSWD)


def test_list_values_from_parse_qs():
    form = {k: [v] for k, v in ipn_form().items()}
    assert verify_signature(form, STORE_PASSWD)
