"""Account outcomes shared by module execution and the migration boundary."""


class TrialLimitExceeded(RuntimeError):
    pass


class AccountLimitExceeded(RuntimeError):
    def __init__(self, account_key: str = "", matched: str = "",
                 retry_after: int = 0, recipe_slug: str = ""):
        self.account_key = account_key
        self.matched = matched
        self.retry_after = max(0, int(retry_after or 0))
        # Public compatibility field used by existing API error metadata.
        self.recipe_slug = recipe_slug
        super().__init__(
            f"Account {account_key or '?'} đã chạm giới hạn của '{recipe_slug or '?'}'"
            f"{(': ' + matched[:120]) if matched else ''}")
