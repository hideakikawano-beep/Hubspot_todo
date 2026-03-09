"""
HubSpot API クライアント
- Todoタスクの取得
- 関連するメールスレッドの取得
- スレッドへのメール返信
"""

import os
import requests
from typing import Dict, List, Optional


BASE_URL = "https://api.hubapi.com"


class HubSpotClient:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })

    def _get(self, path: str, params: Dict = None) -> Dict:
        resp = self.session.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Dict) -> Dict:
        resp = self.session.post(f"{BASE_URL}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Tasks (Todo)
    # ------------------------------------------------------------------ #

    def get_tasks(
        self,
        limit: int = 10,
        status: Optional[str] = None,
        owner_id: Optional[str] = None,
        from_ts: Optional[int] = None,
    ) -> List[Dict]:
        """直近のTodoタスク一覧を取得する。

        Args:
            limit: 取得件数 (最大100)
            status: "WAITING" | "IN_PROGRESS" | "COMPLETED" | None(全て)
            owner_id: HubSpotオーナーID (自分のタスクのみ取得する場合)
            from_ts: この日時(ミリ秒)以降のタスクのみ取得
        """
        properties = [
            "hs_task_subject",
            "hs_task_body",
            "hs_task_status",
            "hs_task_priority",
            "hs_task_type",
            "hs_timestamp",
            "hubspot_owner_id",
        ]

        filters = []
        if status:
            filters.append({"propertyName": "hs_task_status", "operator": "EQ", "value": status})
        if owner_id:
            filters.append({"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id})
        if from_ts is not None:
            filters.append({"propertyName": "hs_timestamp", "operator": "GTE", "value": str(from_ts)})

        body = {
            "filterGroups": [{"filters": filters}] if filters else [],
            "properties": properties,
            "limit": limit,
            "sorts": [{"propertyName": "hs_timestamp", "direction": "ASCENDING"}],
        }
        data = self._post("/crm/v3/objects/tasks/search", body)

        return data.get("results", [])

    def get_task_associations(self, task_id: str, to_object_type: str) -> List[Dict]:
        """タスクに紐づくオブジェクト(contacts/deals/companies)を取得する。"""
        data = self._get(
            f"/crm/v3/objects/tasks/{task_id}/associations/{to_object_type}"
        )
        return data.get("results", [])

    # ------------------------------------------------------------------ #
    # Contacts
    # ------------------------------------------------------------------ #

    def get_contact(self, contact_id: str) -> dict:
        """コンタクト情報を取得する。"""
        return self._get(
            f"/crm/v3/objects/contacts/{contact_id}",
            params={"properties": "email,firstname,lastname,company"},
        )

    # ------------------------------------------------------------------ #
    # CRM Emails (Gmail連携などのメールEngagement)
    # ------------------------------------------------------------------ #

    EMAIL_PROPERTIES = [
        "hs_email_subject",
        "hs_email_text",
        "hs_email_html",
        "hs_email_from_email",
        "hs_email_from_firstname",
        "hs_email_from_lastname",
        "hs_email_to_email",
        "hs_email_to_firstname",
        "hs_email_to_lastname",
        "hs_email_status",
        "hs_email_direction",
        "hs_timestamp",
    ]

    def get_contact_emails(self, contact_id: str, limit: int = 10) -> List[Dict]:
        """コンタクトに紐づくメールEngagementを新しい順に取得する。"""
        # まずアソシエーションからメールIDを取得
        assoc = self._get(
            f"/crm/v3/objects/contacts/{contact_id}/associations/emails"
        )
        email_ids = [r.get("id") or r.get("toObjectId") for r in assoc.get("results", [])]
        if not email_ids:
            return []

        # バッチ取得
        batch_ids = [{"id": str(eid)} for eid in email_ids[:limit]]
        data = self._post(
            "/crm/v3/objects/emails/batch/read",
            {"inputs": batch_ids, "properties": self.EMAIL_PROPERTIES},
        )
        emails = data.get("results", [])
        # hs_timestamp 降順ソート
        emails.sort(
            key=lambda e: e.get("properties", {}).get("hs_timestamp") or "",
            reverse=True,
        )
        return emails

    def log_email(
        self,
        contact_id: str,
        from_email: str,
        to_email: str,
        subject: str,
        text: str,
        owner_id: Optional[str] = None,
    ) -> dict:
        """送信メールをCRMにEngagementとして記録し、コンタクトに紐づける。

        Note: 実際の送信はGmail側で行い、このAPIはHubSpotへの記録用。
        """
        props: Dict = {
            "hs_email_direction": "OUTGOING_EMAIL",
            "hs_email_status": "SENT",
            "hs_email_subject": subject,
            "hs_email_text": text,
            "hs_email_from_email": from_email,
            "hs_email_to_email": to_email,
            "hs_timestamp": str(int(__import__("time").time() * 1000)),
        }
        if owner_id:
            props["hubspot_owner_id"] = owner_id

        body: Dict = {
            "properties": props,
            "associations": [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 198,  # email -> contact
                        }
                    ],
                }
            ],
        }
        return self._post("/crm/v3/objects/emails", body)
