"""Round 13 of the deploy review: the door's reading of this host's own addresses is checked against
every tailnet address tailscale0 holds (R9-A1a-F-05B-AVAIL).

A request the server sends itself through its own `tailscale serve` arrives from tailscaled with
the owner's login; it is told from his devices only by its forwarded address being one of the
server's own, read from the kernel's tables (/proc/net/fib_trie, /proc/net/if_inet6). A reading in
the kernel's own shape can still leave an address out. Round 10 took a reading as whole when it
held the one IPv4 address the SIOCGIFADDR ioctl names — the interface's primary address only — and
when the IPv6 table listed any tailnet address on tailscale0, which is the incomplete table
vouching for itself. So with a second address on tailscale0 left out of a reading, the server's
own request carrying that address was a device's, and let in as the owner.

Now every tailnet address tailscale0 holds, of the forwarded address's family, must be in the
reading, and which addresses those are is asked of the kernel apart from the tables: over
netlink (identity.interface_addresses), afresh every time, whole or not at all.

What stands in for the system: the fake /proc of tests/test_proxy_identity.py (kernel_world), and
the netlink and ioctl answers about tailscale0, which a test cannot make (no tailscale0 here, and
CI is not root). The netlink reader itself is run against this machine's own kernel for its
loopback interface, and its parser against the kernel's message shapes, built here.
"""

from __future__ import annotations

import errno
import ipaddress
import socket
import struct

import pytest

from app import identity
from app.routes import actions as actions_route
from tests.test_actions_routes import OWNER, client  # noqa: F401 - `client` is a fixture
from tests.test_host_addresses import _inet6_on, _trie
from tests.test_proxy_identity import (  # noqa: F401 - fixtures imported from the suite they belong to
    FORGED_REFUSED,
    HOST_TAILNET,
    HOST_TAILNET6,
    LINUX,
    LOCAL_REFUSED,
    _from,
    _gates,
    _request,
    _v6,
    kernel_world,
    owner_world,
    tailscale_interface,
)

ADMITTED = ("", "")
HOST_V4, HOST_V6 = HOST_TAILNET[0], HOST_TAILNET6[0]
SECOND_V4, SECOND_V6 = "100.101.102.104", "fd7a:115c:a1e0::abce"     # a second address on tailscale0


def _self(address: str):
    """A request this server sent itself through its own `tailscale serve`, forwarded for one of
    its own addresses."""
    return _request({"Tailscale-User-Login": OWNER, "X-Forwarded-For": address}, peer=("127.0.0.1", 40001))


def _netlink(monkeypatch, held: dict) -> list[str]:
    """What netlink says tailscale0 holds: `held["now"]`, asked afresh on every call (each call
    is recorded), or an OSError when it is None."""
    asked: list[str] = []

    def answer(name=identity.TAILSCALE_INTERFACE):
        asked.append(name)
        if held["now"] is None:
            raise OSError(errno.ENODEV, "No such device")
        return frozenset(held["now"])

    monkeypatch.setattr(identity, "interface_addresses", answer, raising=False)
    return asked


# --------------------------------------------------------------------------- the finding


async def test_a_second_ipv4_address_on_tailscale0_left_out_of_a_reading_is_never_the_owner(kernel_world, monkeypatch):  # noqa: F811
    """tailscale0 holds its primary address and a second one; the ioctl names the primary, and a
    reading in the kernel's own shape holds the primary and leaves the second out. On the code
    before round 13 the reading was whole by the ioctl's account, and the server's own request
    forwarded for the second address was a device's, admitted as the owner at both gates."""
    _netlink(monkeypatch, {"now": [HOST_V4, SECOND_V4, HOST_V6]})
    _trie(kernel_world, ["127.0.0.1", HOST_V4])
    assert _gates(_self(SECOND_V4)) == FORGED_REFUSED, "the server's own request is never the owner"
    assert _gates(_from(40001)) == FORGED_REFUSED, "nor a device's, on a reading that cannot tell them apart"
    route, why = actions_route.proxy_state(_from(40001))
    assert route == actions_route.FORGED and "holds a tailnet IPv4 address the reading does not" in why
    assert _gates(_self(HOST_V4)) == LOCAL_REFUSED, "an address the reading holds is still this host's"
    assert _gates(_v6()) == ADMITTED, "IPv6, read whole, still answers"
    # The reading whole again: the second address is this host's, and the phone is the owner.
    _trie(kernel_world, ["127.0.0.1", HOST_V4, SECOND_V4])
    assert _gates(_self(SECOND_V4)) == LOCAL_REFUSED
    assert _gates(_from(40001)) == ADMITTED


async def test_a_second_ipv6_address_on_tailscale0_left_out_of_a_reading_is_never_the_owner(kernel_world, monkeypatch):  # noqa: F811
    """The IPv6 half: before, the IPv6 table listing any tailnet address on tailscale0 made it whole
    by its own account. With a second one left out, the server's own request forwarded for it was
    admitted as the owner."""
    _netlink(monkeypatch, {"now": [HOST_V4, HOST_V6, SECOND_V6]})
    _inet6_on(kernel_world, [("::1", "lo"), (HOST_V6, "tailscale0")])
    assert _gates(_self(SECOND_V6)) == FORGED_REFUSED
    assert _gates(_v6()) == FORGED_REFUSED
    assert "holds a tailnet IPv6 address the reading does not" in actions_route.proxy_state(_v6())[1]
    assert _gates(_from(40001)) == ADMITTED and _gates(_self(HOST_V4)) == LOCAL_REFUSED, "IPv4 still answers"
    _inet6_on(kernel_world, [("::1", "lo"), (HOST_V6, "tailscale0"), (SECOND_V6, "tailscale0")])
    assert _gates(_self(SECOND_V6)) == LOCAL_REFUSED
    assert _gates(_v6()) == ADMITTED


# --------------------------------------------------------------------------- asked afresh, whole or not at all


async def test_what_tailscale0_holds_is_asked_afresh_for_every_request(kernel_world, monkeypatch):  # noqa: F811
    """Nothing about tailscale0 is remembered between requests (round 7 found a cached answer let an
    address the server gained pass as a device's): an address it gains is required of the very
    next reading, and one it loses is not required any more."""
    held = {"now": [HOST_V4, HOST_V6]}
    asked = _netlink(monkeypatch, held)
    assert _gates(_from(40001)) == ADMITTED
    before = len(asked)
    assert before >= 1
    held["now"] = [HOST_V4, SECOND_V4, HOST_V6]           # gained, and the reading has not caught up
    assert _gates(_from(40001)) == FORGED_REFUSED and _gates(_self(SECOND_V4)) == FORGED_REFUSED
    assert len(asked) > before, "asked again"
    held["now"] = [HOST_V4, HOST_V6]                      # lost again: the reading is whole
    assert _gates(_from(40001)) == ADMITTED


async def test_tailscale0_that_cannot_be_asked_or_holds_no_tailnet_address_is_cannot_say(kernel_world, monkeypatch):  # noqa: F811
    held = {"now": None}
    _netlink(monkeypatch, held)
    for request in (_from(40001), _v6(), _self(SECOND_V4)):
        assert _gates(request) == FORGED_REFUSED
    route, why = actions_route.proxy_state(_from(40001))
    assert route == actions_route.FORGED and "could not be read over netlink" in why
    assert _gates(_self(HOST_V4)) == LOCAL_REFUSED, "an address the reading holds is still this host's"
    ok, said = identity.tailnet_self_check()
    assert not ok and "could not be read over netlink" in said, "and the install is told so"
    held["now"] = ["10.0.0.5", "fe80::1"]                  # nothing in the tailnet's range
    assert _gates(_from(40001)) == FORGED_REFUSED and _gates(_v6()) == FORGED_REFUSED
    assert "holds no tailnet IPv4 address" in actions_route.proxy_state(_from(40001))[1]
    held["now"] = [HOST_V4, HOST_V6, "fe80::1"]            # an address outside the tailnet's range is not asked for
    assert _gates(_from(40001)) == ADMITTED and _gates(_v6()) == ADMITTED
    assert identity.tailnet_self_check()[0] is True


def test_the_install_check_asks_for_every_address_too(kernel_world, monkeypatch):  # noqa: F811
    _netlink(monkeypatch, {"now": [HOST_V4, SECOND_V4, HOST_V6]})
    ok, why = identity.tailnet_self_check()
    assert not ok and "holds a tailnet IPv4 address the reading does not" in why


# --------------------------------------------------------------------------- the netlink reader


def test_on_this_machine_netlink_names_the_loopback_interfaces_addresses():
    """identity.interface_addresses against this machine's own kernel, asked for its own loopback
    interface (no privilege, no other process's files): 127.0.0.1 is among them, and an interface
    that is not there is an OSError, never an answer."""
    if not LINUX:
        pytest.skip("netlink is a Linux kernel's")
    held = identity.interface_addresses("lo")
    assert "127.0.0.1" in held
    assert all(ipaddress.ip_address(a) for a in held)
    with pytest.raises(OSError):
        identity.interface_addresses("crooks-none0")


# The kernel's messages, built as linux/netlink.h and linux/rtnetlink.h lay them out.
def _attr(kind: int, value: bytes) -> bytes:
    raw = struct.pack("=HH", 4 + len(value), kind) + value
    return raw + b"\0" * (-len(raw) % 4)


def _message(kind: int, body: bytes, *, sequence: int = 1, flags: int = 0x2) -> bytes:
    raw = struct.pack("=IHHII", 16 + len(body), kind, flags, sequence, 0) + body
    return raw + b"\0" * (-len(raw) % 4)


def _address(index: int, address: str, *, local: bool = True, **kw) -> bytes:
    ip = ipaddress.ip_address(address)
    family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
    body = struct.pack("=BBBBI", family, 32 if ip.version == 4 else 128, 0, 0, index)
    body += _attr(1, ip.packed)                       # IFA_ADDRESS
    if local and ip.version == 4:
        body += _attr(2, ip.packed)                   # IFA_LOCAL
    return _message(20, body, **kw)                    # RTM_NEWADDR


DONE = _message(3, struct.pack("=i", 0))


def _read(*chunks: bytes, index: int = 7) -> frozenset[str]:
    found: set[str] = set()
    for chunk in chunks:
        if identity._netlink_chunk(chunk, 1, index, found):
            return frozenset(found)
    raise AssertionError("no end")


def test_the_netlink_answer_is_taken_whole_or_not_at_all():
    """The reader's parser, on the kernel's own message shapes: the addresses of the interface
    asked for and no other's, over any number of reads; and a dump the kernel marks as interrupted
    by a change, an error, a message cut short or out of shape, one answering another request, or
    anything else in an address dump, is an OSError."""
    whole = _address(7, HOST_V4) + _address(9, "10.0.0.5") + _address(7, HOST_V6)
    assert _read(whole, _address(7, SECOND_V4) + DONE) == frozenset({HOST_V4, HOST_V6, SECOND_V4})
    assert _read(_address(7, HOST_V4, local=False) + DONE) == frozenset({HOST_V4}), "IFA_ADDRESS alone will do"
    interrupted = _address(7, HOST_V4) + _message(3, struct.pack("=i", 0), flags=0x2 | 0x10)
    bad = {
        "interrupted by a change": interrupted,
        "interrupted, marked on an address": _address(7, HOST_V4, flags=0x2 | 0x10) + DONE,
        "an error": _message(2, struct.pack("=i", -errno.EPERM) + b"\0" * 16),
        "cut short": whole[:-5],
        "a length past the end": struct.pack("=IHHII", 400, 20, 2, 1, 0),
        "another request's answer": _address(7, HOST_V4, sequence=2) + DONE,
        "an attribute past its message": _message(20, struct.pack("=BBBBI", socket.AF_INET, 32, 0, 0, 7) + struct.pack("=HH", 40, 1) + b"\0" * 4),
        "an address of the wrong size": _message(20, struct.pack("=BBBBI", socket.AF_INET, 32, 0, 0, 7) + _attr(1, b"\x01\x02")),
        "no address at all": _message(20, struct.pack("=BBBBI", socket.AF_INET, 32, 0, 0, 7)),
        "a message an address dump does not hold": _message(16, b"\0" * 16) + DONE,
    }
    for what, chunk in bad.items():
        with pytest.raises(OSError):
            _read(chunk)
            pytest.fail(what)
