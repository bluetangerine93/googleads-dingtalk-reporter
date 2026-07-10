from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PolicyIssue:
    customer_id: str
    customer_name: str
    issue_type: str
    approval_status: str
    review_status: str
    campaign_name: str
    ad_group_name: str
    item_name: str
    item_id: str
    policy_topics: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
