"""The tool audit's three edge cases left by PR #83 (experience/tool_matrix.py, `_calls_that_run`).

* A hook is a root only by the exact name pytest runs: a helper called `setup_shop` is not one.
* A name is resolved by where it is defined: `self.go()` reaches the class's own `go`, never a
  module-level `go`; a `test*` method runs only in a class pytest collects, or once it is made.
* A module-level helper running code hands on by name (`anyio.run(go)`) is reached, as a nested
  one is; named only by the file's top-level code, it is not.
"""

from __future__ import annotations

import textwrap

from experience import tool_matrix

DISPATCH = "from app.tools.dispatch import dispatch\nimport pytest\n"


def _cites(source: str) -> bool:
    return tool_matrix.read_test(textwrap.dedent(source)).calls_tool("probe_tool", "app.tools.probes", "probe_tool")


# ====================================================================== (1) hooks by their exact names


def test_a_helper_whose_name_only_starts_like_a_hook_is_not_run():
    for name in ("setup_shop", "teardown_all", "setupThing", "Setup_x", "setup", "teardown", "SETUP_MODULE"):
        assert not _cites(DISPATCH + f'async def {name}():\n    await dispatch("probe_tool", {{}})\n'
                                     'def test_other():\n    assert True\n'), name
        assert not _cites(DISPATCH + f'class TestIt:\n    async def {name}(self):\n'
                                     '        await dispatch("probe_tool", {})\n'
                                     '    def test_other(self):\n        assert True\n'), name


def test_the_module_hooks_pytest_runs_are_run():
    for name in ("setup_module", "teardown_module", "setup_function", "teardown_function",
                 "setUpModule", "tearDownModule"):
        assert _cites(DISPATCH + f'async def {name}():\n    await dispatch("probe_tool", {{}})\n'
                                 'def test_other():\n    assert True\n'), name


def test_the_class_hooks_pytest_runs_are_run_in_a_test_class():
    for name in ("setup_method", "teardown_method", "setup_class", "teardown_class"):
        assert _cites(DISPATCH + f'class TestShop:\n    async def {name}(self):\n'
                                 '        await dispatch("probe_tool", {})\n'
                                 '    def test_other(self):\n        assert True\n'), name
        assert not _cites(DISPATCH + f'class Shop:\n    async def {name}(self):\n'
                                     '        await dispatch("probe_tool", {})\n'
                                     '    def test_other(self):\n        assert True\n'), name


def test_unittests_hooks_are_run_in_a_testcase_class_and_only_there():
    for name in ("setUp", "tearDown", "setUpClass", "tearDownClass"):
        assert _cites(DISPATCH + f'import unittest\nclass Shop(unittest.TestCase):\n    def {name}(self):\n'
                                 '        dispatch("probe_tool", {})\n'
                                 '    def test_other(self):\n        assert True\n'), name
        assert _cites(DISPATCH + f'from unittest import TestCase\nclass Shop(TestCase):\n    def {name}(self):\n'
                                 '        dispatch("probe_tool", {})\n'), name
        assert not _cites(DISPATCH + f'class TestShop:\n    def {name}(self):\n'
                                     '        dispatch("probe_tool", {})\n'
                                     '    def test_other(self):\n        assert True\n'), name


# ====================================================================== (2) names resolved where defined


MODULE_GO = DISPATCH + 'async def go():\n    await dispatch("probe_tool", {})\n'


def test_self_go_never_reaches_a_module_level_go():
    assert not _cites(MODULE_GO + 'class TestIt:\n    async def go(self):\n        return None\n'
                                  '    async def test_it(self):\n        await self.go()\n')
    assert not _cites(MODULE_GO + 'class TestIt:\n    async def test_it(self):\n        await self.go()\n')


def test_self_go_reaches_the_classs_own_go_or_a_bases_and_not_an_unrelated_classs():
    assert _cites(DISPATCH + 'class TestIt:\n    async def go(self):\n        await dispatch("probe_tool", {})\n'
                             '    async def test_it(self):\n        await self.go()\n')
    assert _cites(DISPATCH + 'class Base:\n    async def go(self):\n        await dispatch("probe_tool", {})\n'
                             'class TestIt(Base):\n    async def test_it(self):\n        await self.go()\n')
    assert not _cites(DISPATCH + 'class Other:\n    async def go(self):\n        await dispatch("probe_tool", {})\n'
                                 'class TestIt:\n    async def test_it(self):\n        await self.go()\n')


def test_a_bare_call_from_a_test_method_reaches_the_module_level_function():
    assert _cites(MODULE_GO + 'class TestIt:\n    async def go(self):\n        return None\n'
                              '    async def test_it(self):\n        await go()\n')


def test_a_test_method_of_a_class_pytest_does_not_collect_runs_only_once_the_class_is_made():
    helper = DISPATCH + 'class Helper:\n    async def test_it(self):\n        await dispatch("probe_tool", {})\n'
    assert not _cites(helper + 'def test_other():\n    assert True\n')
    assert _cites(helper + '@pytest.fixture\ndef helper():\n    return Helper()\n'
                           'def test_other(helper):\n    assert helper\n')
    assert not _cites(helper + '@pytest.fixture\ndef helper():\n    return Helper()\n'
                               'def test_other():\n    assert True\n')


def test_a_test_class_with_its_own_init_is_not_collected():
    assert not _cites(DISPATCH + 'class TestIt:\n    def __init__(self, shop):\n        self.shop = shop\n'
                                 '    async def test_it(self):\n        await dispatch("probe_tool", {})\n'
                                 'def test_other():\n    assert True\n')
    assert _cites(DISPATCH + 'class TestIt:\n    async def test_it(self):\n        await dispatch("probe_tool", {})\n')


def test_a_test_method_a_collected_class_inherits_from_a_class_of_the_file_runs():
    assert _cites(DISPATCH + 'class _Checks:\n    async def test_it(self):\n        await dispatch("probe_tool", {})\n'
                             'class TestShop(_Checks):\n    pass\n')


# ====================================================================== (3) a helper handed on by name


def test_a_module_level_helper_handed_on_from_running_code_runs():
    assert _cites(MODULE_GO + 'import anyio\ndef test_it():\n    anyio.run(go)\n')
    assert _cites(MODULE_GO + 'def test_it(monkeypatch, provider):\n    monkeypatch.setattr(provider, "step", go)\n')
    assert _cites(MODULE_GO + '@pytest.fixture\ndef step():\n    return go\ndef test_it(step):\n    assert step\n')
    assert _cites(MODULE_GO + 'def test_it(runtime):\n    runtime.steps = [go]\n')


def test_a_module_level_class_handed_on_from_running_code_runs_its_methods():
    model = DISPATCH + 'class Model:\n    async def turn(self):\n        await dispatch("probe_tool", {})\n'
    assert _cites(model + 'def test_it(runtime):\n    runtime.provider = Model\n')
    assert not _cites(model + 'def test_it(runtime: Model):\n    assert runtime\n')


def test_a_helper_named_only_by_the_top_level_code_or_shadowed_by_the_test_is_not_run():
    assert not _cites(MODULE_GO + 'import anyio\nanyio.run(go)\ndef test_unrelated():\n    assert True\n')
    assert not _cites(MODULE_GO + 'import anyio\ndef test_it():\n    go = None\n    anyio.run(go)\n')
    assert not _cites(MODULE_GO + 'import anyio\ndef test_it():\n    async def go():\n        return None\n'
                                  '    anyio.run(go)\n')
