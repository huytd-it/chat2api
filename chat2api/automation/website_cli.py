"""Domain registration and a provider-neutral brief for external coding agents."""
import json

from .. import store
from ..errors import OpenAIError
from .websites import add_website, agent_brief, workspace_sites


def run(cfg, args):
    owns_store = store.default() is None
    try:
        if args.website_action == "brief":
            print(agent_brief(args.domain, args.request))
            return 0
        if owns_store:
            db = store.connect(cfg.db_path)
            db.migrate()
        if args.website_action == "add":
            result = add_website(args.domain)
        else:
            result = [{"id": site.id, "domain": site.origin, "title": site.title} for site in workspace_sites()]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except OpenAIError as error:
        print(f"{error.code}: {error.message}")
        return 2
    finally:
        if owns_store and store.default() is not None:
            store.shutdown()
