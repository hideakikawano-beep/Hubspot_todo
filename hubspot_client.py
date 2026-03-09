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

    def get_tasks(self, limit: int = 10, status: Optional[str] = None) -> List[Dict]:
        """直近のTodoタスク一覧を取得する。

        Args:
            limit: 取得件数 (最大100)
            status: "WAITING" | "IN_PROGRESS" | "COMPLETED" | None(全て)
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

        if status:
            body = {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "hs_task_status",
                                "operator": "EQ",
                                "value": status,
                            }
                        ]
                    }
                ],
                "properties": properties,
                "limit": limit,
                "sorts": [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}],
            }
            data = self._post("/crm/v3/objects/tasks/search", body)
        else:
            data = self._get(
                "/crm/v3/objects/tasks",
                params={
                    "limit": limit,
                    "properties": ",".join(properties),
                    "sort": "-hs_timestamp",
                },
            )

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
    # Conversations (Email Threads)
    # ------------------------------------------------------------------ #

    def get_threads_by_contact(
        self, contact_id: str, thread_status: str = "OPEN", limit: int = 5
    ) -> List[Dict]:
        """コンタクトに紐づくメールスレッド一覧を取得する。

        Args:
            contact_id: HubSpotのコンタクトID
            thread_status: "OPEN" | "CLOSED"
            limit: 取得件数
        """
        data = self._get(
            "/conversations/v3/conversations/threads",
            params={
                "associatedContactId": contact_id,
                "threadStatus": thread_status,
                "limit": limit,
            },
        )
        return data.get("results", [])

    def get_thread_messages(self, thread_id: str, limit: int = 10) -> List[Dict]:
        """スレッド内のメッセージ一覧を取得する(新しい順)。"""
        data = self._get(
            f"/conversations/v3/conversations/threads/{thread_id}/messages",
            params={"limit": limit},
        )
        return data.get("results", [])

    def reply_to_thread(
        self,
        thread_id: str,
        text: str,
        sender_actor_id: str,
        channel_id: str,
        channel_account_id: str,
        recipients: List[Dict],
        subject: Optional[str] = None,
    ) -> dict:
        """スレッドにメールを返信する。

        Args:
            thread_id: 返信先スレッドID
            text: 本文 (HTMLも可)
            sender_actor_id: 送信者アクターID (例: "A-12345678")
            channel_id: チャンネルID (例: "1002")
            channel_account_id: チャンネルアカウントID
            recipients: 受信者リスト
                [{"actorID": "...", "name": "...", "recipientField": "TO",
                  "deliveryIdentifiers": [{"type": "HS_EMAIL_ADDRESS", "value": "..."}]}]
            subject: 件名 (省略可)
        """
        body: Dict = {
            "type": "MESSAGE",
            "text": text,
            "senderActorId": sender_actor_id,
            "channelId": channel_id,
            "channelAccountId": channel_account_id,
            "recipients": recipients,
        }
        if subject:
            body["subject"] = subject

        return self._post(
            f"/conversations/v3/conversations/threads/{thread_id}/messages", body
        )
