"""Read-only PrintNode readiness check. No postage or printing calls."""

import json

from shipping.print_provider import PrintNodeProvider
from shipping.settings import Settings


def main():
    cfg = Settings()
    key = cfg.printnode_api_key.get_secret_value()
    if not cfg.printnode_enabled or not key:
        print("PrintNode is disabled or its server key is missing.")
        return 1
    status = PrintNodeProvider(key, cfg.printnode_printer_id).health()
    print(json.dumps(status))
    return 0 if status["connected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
