"""This host's own addresses, whole or not at all (the 2026-09-28 deploy review, round 9,
F-05B-AVAIL).

A request the server sends through its own `tailscale serve` arrives from tailscaled stamped with
the owner's login, because the server is on his tailnet login; it is told from his devices only by
its forwarded address being one of the server's own. Round 8 read those addresses strictly — a
table in any shape but the kernel's was believed in no part — but a reading in the kernel's own
shape could still leave an address out (the kernel writes these tables while it walks them), and
an empty IPv6 table with IPv6 on was taken as "no IPv6 addresses". Either way the server's own
request was called a device's and let in as the owner.

Now "not this host" — the answer that lets a device in — is given only on a reading that can be
trusted whole: two readings running that agree; ::1 in the IPv6 table whenever IPv6 is on; this
host's own tailnet address of the forwarded address's family among them; and no socket on this
host holding the forwarded address as its own end. Every test below goes through both gates
(principal_verdict and caller_check) with production's switches (Tailscale verification on, the
server not the owner) and the fake /proc's own tables, nothing about the addresses stood in for.
"""

from __future__ import annotations

import ipaddress
import itertools

import pytest

from app import identity
from app.routes import actions as actions_route
from tests.test_actions_routes import OWNER, client  # noqa: F401 - `client` is a fixture
from tests.test_proxy_identity import (  # noqa: F401 - fixtures imported from the suite they belong to
    FORGED_REFUSED,
    HOST_TAILNET,
    HOST_TAILNET6,
    LOCAL_REFUSED,
    _from,
    _gates,
    _hex4,
    _request,
    _row,
    _rows,
    _v6,
    _write_rows,
    kernel_world,
    owner_world,
)

ADMITTED = ("", "")
HOST_V4, HOST_V6 = HOST_TAILNET[0], HOST_TAILNET6[0]


def _self(address: str):
    """A request this server sent itself through its own `tailscale serve`: tailscaled brought it
    (the fake /proc says tailscaled holds the connection), stamped with the owner's login, and
    forwarded for one of the server's own addresses."""
    return _request({"Tailscale-User-Login": OWNER, "X-Forwarded-For": address}, peer=("127.0.0.1", 40001))


def _trie(root, v4: list[str]) -> None:
    lines = ["Main:", "  +-- 0.0.0.0/0 3 0 5", "     |-- 0.0.0.0", "        /0 universe UNICAST"]
    for address in v4:
        lines += [f"     |-- {address}", "        /32 host LOCAL"]
    (root / "net" / "fib_trie").write_text("\n".join(lines) + "\n")


def _inet6(root, v6: list[str]) -> None:
    rows = [f"{ipaddress.IPv6Address(a).exploded.replace(':', '')} 02 40 00 80 tailscale0" for a in v6]
    (root / "net" / "if_inet6").write_text("".join(row + "\n" for row in rows))


def _switch(root, which: str, value: str) -> None:
    path = root / "sys" / "net" / "ipv6" / "conf" / which / "disable_ipv6"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


async def test_the_servers_own_request_with_its_tailnet_address_left_out_is_never_the_owner(kernel_world):  # noqa: F811
    """The finding's case: a reading in the kernel's own shape — loopback and all — that leaves out
    the server's tailnet IPv4 address. Before, the server's own request forwarded for that address
    was a device's and passed both gates; now nothing forwarded for IPv4 is let in on that reading,
    and the reason says which address is missing. IPv6, read whole, still answers."""
    _trie(kernel_world, ["127.0.0.1", "10.0.0.5"])
    assert identity.local_addresses(proc=kernel_world) is not None, "a well-formed reading"
    assert _gates(_self(HOST_V4)) == FORGED_REFUSED
    assert _gates(_from(40001)) == FORGED_REFUSED, "nor a device: the reading cannot tell them apart"
    route, why = actions_route.proxy_state(_from(40001))
    assert route == actions_route.FORGED and "tailnet IPv4 address is not among them" in why
    assert _gates(_v6()) == ADMITTED, "the IPv6 reading is whole and holds the server's own"
    assert _gates(_self(HOST_V6)) == LOCAL_REFUSED


async def test_the_servers_own_ipv6_request_with_its_tailnet_address_left_out_is_never_the_owner(kernel_world):  # noqa: F811
    _inet6(kernel_world, ["::1"])
    assert _gates(_self(HOST_V6)) == FORGED_REFUSED and _gates(_v6()) == FORGED_REFUSED
    assert "tailnet IPv6 address is not among them" in actions_route.proxy_state(_v6())[1]
    assert _gates(_from(40001)) == ADMITTED and _gates(_self(HOST_V4)) == LOCAL_REFUSED


@pytest.mark.parametrize("contents", ["", "\n"])
async def test_an_empty_ipv6_table_with_ipv6_on_is_not_whole_for_either_family(kernel_world, contents):  # noqa: F811
    """The finding's other case: if_inet6 there and empty, IPv6 on. Not "no IPv6 addresses": the
    loopback interface holds ::1 whenever IPv6 is on, so a table without it is not whole."""
    (kernel_world / "net" / "if_inet6").write_text(contents)
    _switch(kernel_world, "all", "0\n")
    for request in (_from(40001), _v6(), _self(HOST_V4), _self(HOST_V6)):
        assert _gates(request) == FORGED_REFUSED
    assert "does not list ::1" in actions_route.proxy_state(_from(40001))[1]


async def test_ipv6_off_on_the_loopback_interface_excuses_only_the_missing_loopback_address(kernel_world):  # noqa: F811
    (kernel_world / "net" / "if_inet6").write_text("")
    _switch(kernel_world, "lo", "1\n")
    assert _gates(_from(40001)) == ADMITTED, "the IPv4 reading is whole"
    assert _gates(_self(HOST_V4)) == LOCAL_REFUSED
    assert _gates(_v6()) == FORGED_REFUSED, "but an IPv6 reading without the server's tailnet address is not"
    _inet6(kernel_world, HOST_TAILNET6)
    assert _gates(_v6()) == ADMITTED and _gates(_self(HOST_V6)) == LOCAL_REFUSED


async def test_a_socket_on_this_host_holding_the_address_makes_it_this_hosts(kernel_world):  # noqa: F811
    """Evidence apart from the address tables, and only ever toward "this host": the socket table.
    Here the reading holds some other tailnet-range address (a carrier-grade NAT address on another
    interface, say) and leaves out the server's own — which the tailnet-address rule alone would
    not catch — but the server's own request holds a socket whose own end is that address."""
    _trie(kernel_world, ["127.0.0.1", "100.64.50.50"])
    assert _gates(_self(HOST_V4)) == ADMITTED, "the reading alone cannot see it"
    rows = _rows(kernel_world)
    _write_rows(kernel_world, [*rows, _row(_hex4(HOST_V4, 51234), _hex4(HOST_V4, 443), 4242)])
    assert _gates(_self(HOST_V4)) == LOCAL_REFUSED
    assert actions_route.proxy_state(_self(HOST_V4))[0] == actions_route.THIS_HOST
    assert _gates(_from(40001)) == ADMITTED, "a device's address is on no socket here"


def test_the_socket_evidence_is_read_whole_or_says_it_cannot(tmp_path):
    root = tmp_path / "proc"
    (root / "net").mkdir(parents=True)
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode"
    (root / "net" / "tcp").write_text(header + "\n" + _row(_hex4(HOST_V4, 443), _hex4("0.0.0.0", 0), 5) + "\n")
    ip = ipaddress.ip_address(HOST_V4)
    assert identity.bound_here(ip, proc=root) == (True, "")
    assert identity.bound_here(ipaddress.ip_address("100.64.0.9"), proc=root) == (False, "")
    (root / "net" / "tcp6").write_text(header + "\n   0: garbage\n")
    found, why = identity.bound_here(ipaddress.ip_address("100.64.0.9"), proc=root)
    assert found is None and "tcp6" in why


async def test_a_reading_that_changes_under_it_is_not_believed_until_it_holds_still(kernel_world, monkeypatch):  # noqa: F811
    """The kernel writes these tables while it walks them: a reading taken across a change can be
    well formed and still leave an entry out. Two readings running must agree; a reading that
    differs from the one before is followed by another, and four that never agree are "cannot
    say"."""
    whole = (kernel_world / "net" / "fib_trie").read_text()
    _trie(kernel_world, ["127.0.0.1", "100.64.50.50"])      # the server's own address left out
    partial = (kernel_world / "net" / "fib_trie").read_text()
    real = identity._read_table
    readings: list[str] = []

    def reading(path):
        if path.name == "fib_trie" and readings:
            return readings.pop(0)
        return real(path)

    monkeypatch.setattr(identity, "_read_table", reading)
    readings[:] = [whole, partial, whole, partial]
    request = _self(HOST_V4)
    assert _gates(request) == FORGED_REFUSED, "no two readings running agreed"
    assert "changed on every one of 4 readings" in actions_route.proxy_state(request)[1]
    readings[:] = [partial, whole, whole]
    assert _gates(_self(HOST_V4)) == LOCAL_REFUSED, "the last two agreed, and hold the server's address"
    readings[:] = [whole, whole]
    assert _gates(_from(40001)) == ADMITTED and readings == [], "two readings that agree, and no more"


async def test_whatever_a_whole_looking_reading_leaves_out_the_servers_own_request_is_never_the_owner(kernel_world):  # noqa: F811
    """Every way a reading in the kernel's own shape can leave out this host's addresses — any
    subset of them, IPv4 and IPv6 — and every one of the server's own addresses a request it sent
    itself could carry: at neither gate is it ever the owner. (With the owner's login and a whois
    that says every address is his, only the address rule stands between it and the owner.)"""
    v4 = [HOST_V4, "10.0.0.5"]
    v6 = [HOST_V6, "2a01:4f8:1c1c:60a3::1"]
    for left_out in itertools.chain.from_iterable(itertools.combinations(v4 + v6, n) for n in range(len(v4 + v6) + 1)):
        _trie(kernel_world, ["127.0.0.1", *(a for a in v4 if a not in left_out)])
        _inet6(kernel_world, ["::1", *(a for a in v6 if a not in left_out)])
        for own in v4 + v6:
            assert _gates(_self(own)) != ADMITTED, (left_out, own)
        # And the owner's own device is let in whenever the reading is whole enough to tell.
        device = _v6() if HOST_V4 in left_out and HOST_V6 not in left_out else _from(40001)
        expect = ADMITTED if (HOST_V4 not in left_out or HOST_V6 not in left_out) else FORGED_REFUSED
        assert _gates(device) == expect, left_out


# ------------------------------------------------ round 9 (A1b), F-05B-AVAIL: a passing failure is waited out, boundedly


async def test_a_failure_that_outlasts_an_immediate_reread_is_waited_out_within_a_bound(kernel_world, monkeypatch):  # noqa: F811
    """The A1b finding: a read that failed was tried again only at once, so a failure lasting a
    moment longer than that refused the owner's device. Now a reading that fails or differs is
    followed by another after a short wait that grows, up to ADDRESS_READS readings: a table that
    fails twice running still answers his device, on two readings that agree; one that never
    recovers is refused, having waited no more than ADDRESS_PAUSES_S in all; and readings that
    agree at once wait for nothing."""
    waited: list[float] = []
    monkeypatch.setattr(identity, "_pause", waited.append)
    real = identity._read_table
    failures = {"left": 0}

    def flaky(path):
        if path.name == "fib_trie" and failures["left"] > 0:
            failures["left"] -= 1
            raise OSError("Resource temporarily unavailable")
        return real(path)

    monkeypatch.setattr(identity, "_read_table", flaky)
    assert _gates(_from(40001)) == ADMITTED and waited == [], "two readings that agree wait for nothing"
    failures["left"] = 2
    request = _from(40001)
    assert _gates(request) == ADMITTED, "two failures running, and still the owner's device is answered"
    assert waited == list(identity.ADDRESS_PAUSES_S[:2]) and failures["left"] == 0
    assert _gates(_self(HOST_V4)) == LOCAL_REFUSED, "and the server itself is still the server"
    waited.clear()
    failures["left"] = identity.ADDRESS_READS
    route, why = actions_route.proxy_state(_from(40001))
    assert route == actions_route.FORGED and f"read {identity.ADDRESS_READS} times" in why
    assert len(waited) == identity.ADDRESS_READS - 1 and sum(waited) <= sum(identity.ADDRESS_PAUSES_S) <= 0.1
