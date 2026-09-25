"""CLIVE's side of the remote engineering loop: build a request the loop will admit, file it
on the loop's GitHub inbox branch, and read back the status the loop publishes.

The loop itself is app/remote_engineering; nothing here changes it or asserts anything it does
not already enforce. Filing is a write, and it is only ever staged for the owner through the
existing gate (app/tools/engineering_tools.py).
"""
