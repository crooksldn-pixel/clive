"""WeCom's callback crypto, proved against WeCom's own published vectors.

The vectors are WeCom's, not ours:
- developer.work.weixin.qq.com/document/path/90968 (加解密方案说明, "举例说明"): corpId
  wx5823bf96d3bd56c7, token QDG6eK, EncodingAESKey jWmYm7qr5nMoAUwZRjGtBxmz3KA1tkAj3ykkR6q2B2C, the
  POST with msg_signature 477715d1… whose Encrypt decrypts to the "hello" message below.
- WeCom's own sample libraries, linked from document/path/90307 (加解密库下载与返回码), e.g.
  github.com/sbzhu/weworkapi_golang sample.go: the URL check GET with msg_signature 5c45ff5e…,
  timestamp 1409659589, nonce 263014780 and its echostr, for the same company.
If any of these fail, CLIVE's crypto is not WeCom's, and no real callback would be accepted.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from app.clients import wecom

CORP = "wx5823bf96d3bd56c7"
TOKEN = "QDG6eK"
AES = "jWmYm7qr5nMoAUwZRjGtBxmz3KA1tkAj3ykkR6q2B2C"

POST_SIGNATURE = "477715d11cdb4164915debcba66cb864d751f3e6"
POST_TIMESTAMP = "1409659813"
POST_NONCE = "1372623149"
POST_ENCRYPT = (
    "RypEvHKD8QQKFhvQ6QleEB4J58tiPdvo+rtK1I9qca6aM/wvqnLSV5zEPeusUiX5L5X/0lWfrf0QADHHhGd3QczcdCUpj911L3vg3W/sYYvu"
    "JTs3TUUkSUXxaccAS0qhxchrRYt66wiSpGLYL42aM6A8dTT+6k4aSknmPj48kzJs8qLjvd4Xgpue06DOdnLxAUHzM6+kDZ+HMZfJYuR+LtwG"
    "c2hgf5gsijff0ekUNXZiqATP7PF5mZxZ3Izoun1s4zG4LUMnvw2r+KqCKIw+3IQH03v+BCA9nMELNqbSf6tiWSrXJB3LAVGUcallcrw8V2t9"
    "EL4EhzJWrQUax5wLVMNS0+rUPA3k22Ncx4XXZS9o0MBH27Bo6BpNelZpS+/uh9KsNlY6bHCmJU9p8g7m3fVKn28H3KDYA5Pl/T8Z1ptDAVe0"
    "lXdQ2YoyyH2uyPIGHBZZIs2pDBS8R07+qN+E7Q=="
)
POST_PLAIN = (
    "<xml><ToUserName><![CDATA[wx5823bf96d3bd56c7]]></ToUserName>\n"
    "<FromUserName><![CDATA[mycreate]]></FromUserName>\n"
    "<CreateTime>1409659813</CreateTime>\n"
    "<MsgType><![CDATA[text]]></MsgType>\n"
    "<Content><![CDATA[hello]]></Content>\n"
    "<MsgId>4561255354251345929</MsgId>\n"
    "<AgentID>218</AgentID>\n"
    "</xml>"
)
GET_SIGNATURE = "5c45ff5e21c57e6ad56bac8758b79b1d9ac89fd3"
GET_TIMESTAMP = "1409659589"
GET_NONCE = "263014780"
GET_ECHOSTR = "P9nAzCzyDtyTWESHep1vC5X9xho/qYX3Zpb4yKa9SKld1DsH3Iyt3tP3zNdtp+4RPcs8TgAE7OaBO+FZXvnaqQ=="
GET_PLAIN = "1616140317555161061"


def official() -> wecom.CallbackCrypto:
    return wecom.CallbackCrypto(TOKEN, AES, CORP)


def test_the_signature_is_wecoms_on_its_own_example():
    assert wecom.signature(TOKEN, POST_TIMESTAMP, POST_NONCE, POST_ENCRYPT) == POST_SIGNATURE
    assert wecom.signature(TOKEN, GET_TIMESTAMP, GET_NONCE, GET_ECHOSTR) == GET_SIGNATURE
    # The doc's own sort_str, sha1'd: the four values in dictionary order, joined.
    sort_str = "".join(sorted([TOKEN, POST_TIMESTAMP, POST_NONCE, POST_ENCRYPT]))
    assert sort_str.startswith("13726231491409659813QDG6eKRypEvHKD8QQ")
    assert hashlib.sha1(sort_str.encode()).hexdigest() == POST_SIGNATURE


def test_the_official_post_decrypts_to_the_official_message():
    assert official().decrypt_message(POST_SIGNATURE, POST_TIMESTAMP, POST_NONCE, POST_ENCRYPT) == POST_PLAIN
    fields = wecom.message_fields(POST_PLAIN)
    assert fields["MsgType"] == "text" and fields["Content"] == "hello" and fields["ToUserName"] == CORP


def test_the_official_url_check_answers_with_the_official_echo():
    assert official().verify_url(GET_SIGNATURE, GET_TIMESTAMP, GET_NONCE, GET_ECHOSTR) == GET_PLAIN


def test_the_key_is_the_encodingaeskey_plus_equals_decoded_and_the_iv_is_its_first_16_bytes():
    key = wecom.aes_key(AES)
    assert key == base64.b64decode(AES + "=") and len(key) == 32
    for bad in ("", AES[:-1], AES + "A", AES[:-1] + "!"):
        with pytest.raises(wecom.CryptoError) as refused:
            wecom.aes_key(bad)
        assert refused.value.code == -40004


def test_a_wrong_signature_is_refused_before_anything_is_decrypted(monkeypatch):
    crypto = official()
    decrypted = []
    monkeypatch.setattr(crypto, "decrypt", lambda *a: decrypted.append(a) or "")
    for signature in ("0" * 40, POST_SIGNATURE.upper()[:-1] + "0", ""):
        with pytest.raises(wecom.CryptoError) as refused:
            crypto.decrypt_message(signature, POST_TIMESTAMP, POST_NONCE, POST_ENCRYPT)
        assert refused.value.code == -40001
    with pytest.raises(wecom.CryptoError):
        crypto.decrypt_message(POST_SIGNATURE, str(int(POST_TIMESTAMP) + 1), POST_NONCE, POST_ENCRYPT)
    assert decrypted == []


def test_a_message_for_another_company_is_refused():
    other = wecom.CallbackCrypto(TOKEN, AES, "ww0000000000000000")
    with pytest.raises(wecom.CryptoError) as refused:
        other.decrypt_message(POST_SIGNATURE, POST_TIMESTAMP, POST_NONCE, POST_ENCRYPT)
    assert refused.value.code == -40005


def test_encrypting_is_the_same_scheme_and_round_trips_with_pkcs7_to_32_bytes():
    crypto = official()
    for text in ("", "你好，样衣下周一寄出。", "x" * 26, "y" * 58):   # 16+4+n+18: 26 and 58 land on a 32-byte boundary
        sealed = crypto.encrypt(text, random16=b"0123456789abcdef")
        raw = base64.b64decode(sealed)
        assert len(raw) % 32 == 0
        assert crypto.decrypt(sealed) == text
    aligned = base64.b64decode(crypto.encrypt("x" * 26, random16=b"0123456789abcdef"))
    assert len(aligned) == 16 + 4 + 26 + len(CORP) + 32       # a whole block of padding when aligned


def test_tampered_or_truncated_ciphertext_is_refused():
    crypto = official()
    raw = bytearray(base64.b64decode(POST_ENCRYPT))
    raw[-1] ^= 0x01
    for bad in (base64.b64encode(bytes(raw)).decode(), POST_ENCRYPT[:-8], "not base64!", ""):
        with pytest.raises(wecom.CryptoError):
            crypto.decrypt(bad)


def test_the_envelope_is_read_from_xml_or_json_and_a_doctype_is_refused():
    xml = (f"<xml><ToUserName><![CDATA[{CORP}]]></ToUserName><Encrypt><![CDATA[{POST_ENCRYPT}]]></Encrypt>"
           "<AgentID><![CDATA[218]]></AgentID></xml>").encode()
    assert wecom.envelope(xml) == {"ToUserName": CORP, "AgentID": "218", "Encrypt": POST_ENCRYPT}
    as_json = json.dumps({"ToUserName": CORP, "AgentID": "218", "Encrypt": POST_ENCRYPT}).encode()
    assert wecom.envelope(as_json)["Encrypt"] == POST_ENCRYPT
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><xml><Encrypt>&a;</Encrypt></xml>'
    for bad in (bomb, b"<xml><ToUserName>x</ToUserName></xml>", b"<xml", b"{}"):
        with pytest.raises(wecom.CryptoError):
            wecom.envelope(bad)


def test_a_body_in_another_encoding_never_reaches_the_xml_parser(monkeypatch):
    """Review note 2 (8 Oct): the document-type guard ran on raw bytes, so a UTF-16 body declaring an
    entity slipped past it and expat expanded the entity before the signature was checked. Now a
    body must be strict UTF-8 and start `<xml` or `{` (all WeCom sends) before any parser sees it."""
    parsed = []
    real = wecom.ET.fromstring
    monkeypatch.setattr(wecom.ET, "fromstring", lambda data, *a, **kw: parsed.append(data) or real(data, *a, **kw))
    declared = '<!DOCTYPE x [<!ENTITY a "expanded">]><xml><Encrypt>&a;</Encrypt></xml>'
    plain = f"<xml><Encrypt><![CDATA[{POST_ENCRYPT}]]></Encrypt></xml>"
    for bad in (
        declared.encode("utf-16"),                     # with its byte-order mark
        declared.encode("utf-16-le"), declared.encode("utf-16-be"), plain.encode("utf-16-le"),
        ('<?xml version="1.0" encoding="UTF-16"?>' + plain).encode(),   # a declaration in front
        b"\xef\xbb\xbf" + plain.encode(),              # a UTF-8 byte-order mark in front
        plain.encode().replace(b"<Encrypt>", b"<Encrypt>\xe9"),          # not UTF-8 at all
        b"<!-- x --><xml><Encrypt>e</Encrypt></xml>", b"[]",
    ):
        with pytest.raises(wecom.CryptoError) as refused:
            wecom.envelope(bad)
        assert refused.value.code == -40002, bad[:40]
    for opened in (declared, '<?xml version="1.0"?>' + plain, "﻿" + plain, "<!-- x -->" + plain):
        with pytest.raises(wecom.CryptoError):
            wecom.message_fields(opened)
    assert parsed == []
    assert wecom.envelope(plain.encode())["Encrypt"] == POST_ENCRYPT and len(parsed) == 1
