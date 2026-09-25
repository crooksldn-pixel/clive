"""The bridge from CLIVE to the remote engineering loop.

CLIVE files an engineering objective as one JSON request on the loop's GitHub inbox branch
and reads back the status the loop publishes. Two modules and nothing else:

  requests.py   build and validate a request from structured fields, by the loop's own rules
  github.py     a small client over the GitHub contents API: read status, read the inbox,
                create one request file when it is absent

Neither decides anything the owner has not: a submission is a write tool
(app/tools/engineering_tools.py), staged by the gate and applied only by the owner's tap.
"""
