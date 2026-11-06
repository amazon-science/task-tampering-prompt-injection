# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Marketplace environment tools (entity-action pattern).

Implements the dispute, order, message, evidence, listing, policy and user tools; each
takes an 'action' parameter that selects the operation. The task tool comes from
prompt_injection_benchmark.core.base_tools.
"""

from pathlib import Path
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
import uuid

from prompt_injection_benchmark.core.base_tools import BaseEnvironmentTool, normalize_id


class DisputeTool(BaseEnvironmentTool):
    """
    Unified dispute tool with multiple actions.
    
    Aggregates data from multiple sources:
    - disputes/*.json: Dispute metadata
    - orders/*.json: Order details
    - listings/*.md: Product information
    - evidence/*.md: Evidence files
    - messages/*.json: Message threads
    """
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.disputes_dir = self.sandbox_dir / "disputes"
        self.orders_dir = self.sandbox_dir / "orders"
        self.listings_dir = self.sandbox_dir / "listings"
        self.evidence_dir = self.sandbox_dir / "evidence"
        self.messages_dir = self.sandbox_dir / "messages"
        
        self.outbox_resolutions = self.outbox / "resolutions"
        self.outbox_resolutions.mkdir(exist_ok=True, parents=True)
    
    _PARAM_ACTIONS = {
        "status": ["list"],
        "priority": ["list"],
        "dispute_id": ["read", "resolve", "add_notes"],
        "resolution": ["resolve"],
        "refund_id": ["resolve"],
        "payment_id": ["resolve"],
        "notes": ["add_notes"],
    }

    async def execute(
        self,
        action: Literal["list", "read", "resolve", "add_notes"],
        status: Optional[str] = None,
        priority: Optional[str] = None,
        dispute_id: Optional[str] = None,
        resolution: Optional[str] = None,
        refund_id: Optional[str] = None,
        payment_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute dispute action.

        Args:
            action: Action to perform (list, read, resolve, add_notes)
            status: Filter by status (for list): open, pending, resolved
            priority: Filter by priority (for list): low, medium, high, urgent
            dispute_id: Dispute ID (for read, resolve, add_notes)
            resolution: Resolution decision (for resolve): approve_refund, deny_refund, partial_refund, escalate
            refund_id: Required for approve_refund/partial_refund - ID from order.refund()
            payment_id: Required for deny_refund/partial_refund - ID from order.release_payment()
            notes: Notes to add (for add_notes)

        Returns:
            Action-specific result
        """
        provided = {
            "status": status, "priority": priority, "dispute_id": dispute_id,
            "resolution": resolution, "refund_id": refund_id,
            "payment_id": payment_id, "notes": notes,
        }
        violations = []
        for param_name, value in provided.items():
            if value is None:
                continue
            valid_actions = self._PARAM_ACTIONS.get(param_name, [])
            if action not in valid_actions:
                violations.append(
                    f"'{param_name}' is not valid for action '{action}' "
                    f"(used by: {', '.join(valid_actions)})"
                )
        if violations:
            return {
                "error": f"Invalid parameters for action '{action}': "
                         + "; ".join(violations)
                         + ". No action was performed."
            }

        if dispute_id:
            dispute_id = normalize_id(dispute_id, "dispute")

        if action == "list":
            return await self._list(status, priority)
        elif action == "read":
            return await self._read(dispute_id)
        elif action == "resolve":
            return await self._resolve(dispute_id, resolution, refund_id, payment_id)
        elif action == "add_notes":
            return await self._add_notes(dispute_id, notes)
        else:
            return {"error": f"Unknown action: {action}"}

    async def _list(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None
    ) -> Dict[str, Any]:
        """List disputes with optional filters."""
        if not self.disputes_dir.exists():
            result = {"error": "Disputes directory not found"}
            self.log_action("dispute", {
                "action": "list",
                "status": status,
                "priority": priority
            }, result)
            return result
        
        disputes = []
        for dispute_file in self.disputes_dir.glob("*.json"):
            dispute_data = self._read_json_and_inject(dispute_file)
            
            if status and dispute_data.get("status") != status:
                continue
            if priority and dispute_data.get("priority") != priority:
                continue
            
            disputes.append({
                "id": dispute_data.get("id"),
                "order_id": dispute_data.get("order_id"),
                "status": dispute_data.get("status"),
                "priority": dispute_data.get("priority"),
                "created_date": dispute_data.get("created") or dispute_data.get("created_date"),
                "reason": dispute_data.get("type") or dispute_data.get("reason"),
                "buyer": dispute_data.get("buyer_id") or dispute_data.get("buyer"),
                "seller": dispute_data.get("seller_id") or dispute_data.get("seller")
            })
        
        result = {"disputes": disputes, "count": len(disputes)}
        self.log_action("dispute", {
            "action": "list",
            "status": status,
            "priority": priority
        }, result)
        return result
    
    async def _read(self, dispute_id: str) -> Dict[str, Any]:
        """
        Read dispute with aggregated data from multiple sources.
        
        Combines:
        - Dispute metadata
        - Order details
        - Listing information
        - Evidence files
        - Message thread
        """
        if not dispute_id:
            result = {"error": "dispute_id is required"}
            self.log_action("dispute", {"action": "read", "dispute_id": dispute_id}, result)
            return result
        
        dispute_file = self.disputes_dir / f"{dispute_id}.json"
        if not dispute_file.exists():
            result = {"error": f"Dispute '{dispute_id}' not found"}
            self.log_action("dispute", {"action": "read", "dispute_id": dispute_id}, result)
            return result
        
        dispute_data = self._read_json_and_inject(dispute_file)
        
        order_id = dispute_data.get("order_id")
        order_data = None
        if order_id:
            order_file = self.orders_dir / f"{order_id}.json"
            if order_file.exists():
                order_data = self._read_json_and_inject(order_file)
        
        listing_data = None
        if order_data and order_data.get("listing_id"):
            listing_file = self.listings_dir / f"{order_data['listing_id']}.md"
            if listing_file.exists():
                listing_content = self._read_and_inject(listing_file)
                listing_data = {"content": listing_content}
        
        evidence_ids = dispute_data.get("evidence_ids", [])
        evidence_index_file = self.evidence_dir / "_evidence_index.json"
        evidence_index = {}
        if evidence_index_file.exists():
            try:
                with open(evidence_index_file, 'r') as f:
                    evidence_index = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        evidence_files = []
        for evidence_id in evidence_ids:
            meta = evidence_index.get(evidence_id, {})
            evidence_files.append({
                "id": evidence_id,
                "submitted_by": meta.get("submitted_by"),
                "type": meta.get("type"),
                "submitted": meta.get("submitted"),
                "title": meta.get("title"),
            })
        
        messages = []
        message_thread_id = dispute_data.get("messages_thread_id")
        if message_thread_id:
            message_file = self.messages_dir / f"{message_thread_id}.json"
            if message_file.exists():
                message_data = self._read_json_and_inject(message_file)
                messages = message_data.get("messages", [])
        
        result = {
            "success": True,
            "dispute": dispute_data,
            "order": order_data,
            "listing": listing_data,
            "evidence": evidence_files,
            "messages": messages
        }
        
        self.log_action("dispute", {"action": "read", "dispute_id": dispute_id}, result)
        return result
    
    def _verify_transaction_id(self, transaction_id: str, transaction_type: str) -> Optional[Dict[str, Any]]:
        """
        Verify a transaction ID exists in outbox/financial/.
        
        Args:
            transaction_id: The refund_id or payment_id to verify
            transaction_type: Either "refund" or "payment"
        
        Returns:
            Transaction data if found, None otherwise
        """
        financial_dir = self.sandbox_dir / "outbox" / "financial"
        
        if not financial_dir.exists():
            return None
        
        transaction_file = financial_dir / f"{transaction_id}.json"
        if not transaction_file.exists():
            return None
        
        try:
            with open(transaction_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    async def _resolve(
        self,
        dispute_id: str,
        resolution: str,
        refund_id: Optional[str] = None,
        payment_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Resolve dispute and write resolution to outbox.
        
        Requires prerequisite financial transactions:
        - approve_refund: requires refund_id (from order.refund)
        - deny_refund: requires payment_id (from order.release_payment)
        - partial_refund: requires BOTH refund_id AND payment_id
        - escalate: no transaction required
        """
        if not dispute_id or not resolution:
            result = {"error": "dispute_id and resolution are required"}
            self.log_action("dispute", {
                "action": "resolve",
                "dispute_id": dispute_id,
                "resolution": resolution,
                "refund_id": refund_id,
                "payment_id": payment_id
            }, result)
            return result
        
        valid_resolutions = ["approve_refund", "deny_refund", "partial_refund", "escalate"]
        if resolution not in valid_resolutions:
            result = {"error": f"Invalid resolution. Must be one of: {valid_resolutions}"}
            self.log_action("dispute", {
                "action": "resolve",
                "dispute_id": dispute_id,
                "resolution": resolution,
                "refund_id": refund_id,
                "payment_id": payment_id
            }, result)
            return result
        
        dispute_file = self.disputes_dir / f"{dispute_id}.json"
        if not dispute_file.exists():
            result = {"error": f"Dispute '{dispute_id}' not found"}
            self.log_action("dispute", {
                "action": "resolve",
                "dispute_id": dispute_id,
                "resolution": resolution,
                "refund_id": refund_id,
                "payment_id": payment_id
            }, result)
            return result
        
        dispute_data = self._read_json_and_inject(dispute_file)
        
        refund_data = None
        payment_data = None
        
        if resolution == "approve_refund":
            if not refund_id:
                result = {"error": "approve_refund resolution requires refund_id. First call order(action='refund') to issue the refund."}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
            if payment_id:
                result = {"error": "approve_refund should not include payment_id (full refund means no payment to seller)"}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
            
            refund_data = self._verify_transaction_id(refund_id, "refund")
            if not refund_data:
                result = {"error": f"refund_id '{refund_id}' not found. Ensure order.refund() was called first."}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
        
        elif resolution == "deny_refund":
            if not payment_id:
                result = {"error": "deny_refund resolution requires payment_id. First call order(action='release_payment') to release funds to seller."}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
            if refund_id:
                result = {"error": "deny_refund should not include refund_id (denying means no refund to buyer)"}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
            
            payment_data = self._verify_transaction_id(payment_id, "payment")
            if not payment_data:
                result = {"error": f"payment_id '{payment_id}' not found. Ensure order.release_payment() was called first."}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
        
        elif resolution == "partial_refund":
            if not refund_id or not payment_id:
                result = {"error": "partial_refund resolution requires both refund_id AND payment_id. First call order.refund() then order.release_payment()."}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
            
            refund_data = self._verify_transaction_id(refund_id, "refund")
            if not refund_data:
                result = {"error": f"refund_id '{refund_id}' not found. Ensure order.refund() was called first."}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
            
            payment_data = self._verify_transaction_id(payment_id, "payment")
            if not payment_data:
                result = {"error": f"payment_id '{payment_id}' not found. Ensure order.release_payment() was called first."}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
        
        elif resolution == "escalate":
            if refund_id or payment_id:
                result = {"error": "escalate resolution should not include refund_id or payment_id"}
                self.log_action("dispute", {
                    "action": "resolve",
                    "dispute_id": dispute_id,
                    "resolution": resolution,
                    "refund_id": refund_id,
                    "payment_id": payment_id
                }, result)
                return result
        
        resolution_id = f"res_{uuid.uuid4().hex[:8]}"
        resolution_data = {
            "id": resolution_id,
            "dispute_id": dispute_id,
            "order_id": dispute_data.get("order_id"),
            "resolution": resolution,
            "refund_id": refund_id,
            "payment_id": payment_id,
            "refund_amount": refund_data.get("amount") if refund_data else None,
            "payment_amount": payment_data.get("amount") if payment_data else None,
            "resolved_date": datetime.now().isoformat(),
            "resolved_by": "moderator@marketplace.com"
        }
        
        resolution_file = self.outbox_resolutions / f"{resolution_id}.json"
        with open(resolution_file, 'w') as f:
            json.dump(resolution_data, f, indent=2)
        
        result = {
            "success": True,
            "resolution_id": resolution_id,
            "dispute_id": dispute_id,
            "resolution": resolution,
            "refund_id": refund_id,
            "payment_id": payment_id,
            "refund_amount": refund_data.get("amount") if refund_data else None,
            "payment_amount": payment_data.get("amount") if payment_data else None
        }
        
        self.log_action("dispute", {
            "action": "resolve",
            "dispute_id": dispute_id,
            "resolution": resolution,
            "refund_id": refund_id,
            "payment_id": payment_id
        }, result)
        return result
    
    async def _add_notes(self, dispute_id: str, notes: str) -> Dict[str, Any]:
        """Add notes to dispute."""
        if not dispute_id or not notes:
            missing = [p for p, v in [("dispute_id", dispute_id), ("notes", notes)] if not v]
            result = {"error": f"Missing required parameter(s) for add_notes: {', '.join(missing)}"}
            self.log_action("dispute", {
                "action": "add_notes",
                "dispute_id": dispute_id,
                "notes": notes
            }, result)
            return result
        
        dispute_file = self.disputes_dir / f"{dispute_id}.json"
        if not dispute_file.exists():
            result = {"error": f"Dispute '{dispute_id}' not found"}
            self.log_action("dispute", {
                "action": "add_notes",
                "dispute_id": dispute_id,
                "notes": notes
            }, result)
            return result
        
        notes_id = f"notes_{uuid.uuid4().hex[:8]}"
        notes_data = {
            "id": notes_id,
            "dispute_id": dispute_id,
            "notes": notes,
            "added_date": datetime.now().isoformat(),
            "added_by": "moderator@marketplace.com"
        }
        
        notes_file = self.outbox_resolutions / f"{notes_id}.json"
        with open(notes_file, 'w') as f:
            json.dump(notes_data, f, indent=2)
        
        result = {
            "success": True,
            "notes_id": notes_id,
            "dispute_id": dispute_id
        }
        
        self.log_action("dispute", {
            "action": "add_notes",
            "dispute_id": dispute_id,
            "notes": notes
        }, result)
        return result


class OrderTool(BaseEnvironmentTool):
    """
    Unified order tool with multiple actions.
    """
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.orders_dir = self.sandbox_dir / "orders"
        
        self.outbox_financial = self.outbox / "financial"
        self.outbox_financial.mkdir(exist_ok=True, parents=True)
    
    _PARAM_ACTIONS = {
        "status": ["list"],
        "buyer": ["list"],
        "seller": ["list"],
        "order_id": ["read", "refund", "release_payment"],
        "amount": ["refund", "release_payment"],
        "reason": ["refund"],
        "recipient": ["refund", "release_payment"],
    }

    async def execute(
        self,
        action: Literal["read", "list", "refund", "release_payment"],
        status: Optional[str] = None,
        buyer: Optional[str] = None,
        seller: Optional[str] = None,
        order_id: Optional[str] = None,
        amount: Optional[float] = None,
        reason: Optional[str] = None,
        recipient: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute order action.

        Args:
            action: Action to perform (read, list, refund, release_payment)
            status: Filter by status (for list): pending, completed, cancelled, disputed
            buyer: Filter by buyer (for list)
            seller: Filter by seller (for list)
            order_id: Order ID (for read, refund, release_payment)
            amount: Amount (for refund: defaults to the order total; for release_payment: defaults to the remaining balance)
            reason: Refund reason (for refund)
            recipient: Recipient user ID (for refund: defaults to the buyer; for release_payment: defaults to the seller)

        Returns:
            Action-specific result
        """
        provided = {
            "status": status, "buyer": buyer, "seller": seller,
            "order_id": order_id, "amount": amount, "reason": reason,
            "recipient": recipient,
        }
        violations = []
        for param_name, value in provided.items():
            if value is None:
                continue
            valid_actions = self._PARAM_ACTIONS.get(param_name, [])
            if action not in valid_actions:
                violations.append(
                    f"'{param_name}' is not valid for action '{action}' "
                    f"(used by: {', '.join(valid_actions)})"
                )
        if violations:
            return {
                "error": f"Invalid parameters for action '{action}': "
                         + "; ".join(violations)
                         + ". No action was performed."
            }

        if order_id:
            order_id = normalize_id(order_id, "order")

        if action == "read":
            return await self._read(order_id)
        elif action == "list":
            return await self._list(status, buyer, seller)
        elif action == "refund":
            return await self._refund(order_id, amount, reason, recipient)
        elif action == "release_payment":
            return await self._release_payment(order_id, recipient, amount)
        else:
            return {"error": f"Unknown action: {action}"}

    async def _read(self, order_id: str) -> Dict[str, Any]:
        """Read order details."""
        if not order_id:
            result = {"error": "order_id is required"}
            self.log_action("order", {"action": "read", "order_id": order_id}, result)
            return result
        
        order_file = self.orders_dir / f"{order_id}.json"
        if not order_file.exists():
            result = {"error": f"Order '{order_id}' not found"}
            self.log_action("order", {"action": "read", "order_id": order_id}, result)
            return result
        
        order_data = self._read_json_and_inject(order_file)
        result = {"success": True, **order_data}
        
        self.log_action("order", {"action": "read", "order_id": order_id}, result)
        return result
    
    async def _list(
        self,
        status: Optional[str] = None,
        buyer: Optional[str] = None,
        seller: Optional[str] = None
    ) -> Dict[str, Any]:
        """List orders with optional filters."""
        if not self.orders_dir.exists():
            result = {"error": "Orders directory not found"}
            self.log_action("order", {
                "action": "list",
                "status": status,
                "buyer": buyer,
                "seller": seller
            }, result)
            return result
        
        orders = []
        for order_file in self.orders_dir.glob("*.json"):
            order_data = self._read_json_and_inject(order_file)
            
            if status and order_data.get("status") != status:
                continue
            if buyer and order_data.get("buyer") != buyer:
                continue
            if seller and order_data.get("seller") != seller:
                continue
            
            orders.append({
                "id": order_data.get("id"),
                "buyer": order_data.get("buyer"),
                "seller": order_data.get("seller"),
                "listing_id": order_data.get("listing_id"),
                "amount": order_data.get("amount"),
                "status": order_data.get("status"),
                "order_date": order_data.get("order_date")
            })
        
        result = {"orders": orders, "count": len(orders)}
        self.log_action("order", {
            "action": "list",
            "status": status,
            "buyer": buyer,
            "seller": seller
        }, result)
        return result
    
    async def _refund(
        self,
        order_id: str,
        amount: Optional[float] = None,
        reason: Optional[str] = None,
        recipient: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process refund for order.
        
        If amount is not provided, defaults to full order amount.
        If recipient is not provided, defaults to the order buyer.
        """
        if not order_id:
            result = {"error": "order_id is required"}
            self.log_action("order", {
                "action": "refund",
                "order_id": order_id,
                "amount": amount,
                "reason": reason,
                "recipient": recipient
            }, result)
            return result
        
        order_file = self.orders_dir / f"{order_id}.json"
        if not order_file.exists():
            result = {"error": f"Order '{order_id}' not found"}
            self.log_action("order", {
                "action": "refund",
                "order_id": order_id,
                "amount": amount,
                "reason": reason,
                "recipient": recipient
            }, result)
            return result
        
        order_data = self._read_json_and_inject(order_file)
        
        order_amount = order_data.get("amount", 0)
        actual_amount = amount if amount is not None else order_amount
        
        actual_recipient = recipient if recipient else order_data.get("buyer_id") or order_data.get("buyer")
        
        refund_id = f"refund_{uuid.uuid4().hex[:8]}"
        refund_data = {
            "id": refund_id,
            "order_id": order_id,
            "amount": actual_amount,
            "order_amount": order_amount,
            "reason": reason or "Refund processed",
            "recipient": actual_recipient,
            "buyer": order_data.get("buyer_id") or order_data.get("buyer"),
            "processed_date": datetime.now().isoformat(),
            "processed_by": "moderator@marketplace.com"
        }
        
        refund_file = self.outbox_financial / f"{refund_id}.json"
        with open(refund_file, 'w') as f:
            json.dump(refund_data, f, indent=2)
        
        result = {
            "success": True,
            "refund_id": refund_id,
            "order_id": order_id,
            "amount": actual_amount,
            "order_amount": order_amount,
            "recipient": actual_recipient
        }
        
        self.log_action("order", {
            "action": "refund",
            "order_id": order_id,
            "requested_amount": amount,
            "actual_amount": actual_amount,
            "order_amount": order_amount,
            "reason": reason,
            "requested_recipient": recipient,
            "actual_recipient": actual_recipient,
            "buyer": order_data.get("buyer_id") or order_data.get("buyer")
        }, result)
        return result
    
    def _calculate_refunds_for_order(self, order_id: str) -> float:
        """
        Calculate total refunds already issued for an order.
        
        Scans outbox/financial/ for refund transactions matching this order_id.
        """
        total_refunds = 0.0
        
        if not self.outbox_financial.exists():
            return total_refunds
        
        for refund_file in self.outbox_financial.glob("refund_*.json"):
            try:
                with open(refund_file, 'r') as f:
                    refund_data = json.load(f)
                if refund_data.get("order_id") == order_id:
                    total_refunds += refund_data.get("amount", 0)
            except (json.JSONDecodeError, IOError):
                continue
        
        return total_refunds
    
    async def _release_payment(
        self,
        order_id: str,
        recipient: Optional[str] = None,
        amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Release payment to seller.
        
        If amount is provided explicitly, uses that amount.
        Otherwise, calculates remaining balance (order_total - sum_of_refunds).
        If recipient is not provided, defaults to the order seller.
        """
        if not order_id:
            result = {"error": "order_id is required"}
            self.log_action("order", {
                "action": "release_payment",
                "order_id": order_id,
                "recipient": recipient,
                "amount": amount
            }, result)
            return result
        
        order_file = self.orders_dir / f"{order_id}.json"
        if not order_file.exists():
            result = {"error": f"Order '{order_id}' not found"}
            self.log_action("order", {
                "action": "release_payment",
                "order_id": order_id,
                "recipient": recipient,
                "amount": amount
            }, result)
            return result
        
        order_data = self._read_json_and_inject(order_file)
        order_total = order_data.get("amount", 0)
        
        actual_recipient = recipient if recipient else order_data.get("seller_id") or order_data.get("seller")
        
        total_refunds = self._calculate_refunds_for_order(order_id)
        remaining_balance = order_total - total_refunds
        
        if amount is not None:
            payment_amount = amount
        else:
            payment_amount = remaining_balance
        
        if remaining_balance <= 0:
            result = {
                "error": f"No remaining balance to release. Order total: ${order_total}, Refunds issued: ${total_refunds}"
            }
            self.log_action("order", {
                "action": "release_payment",
                "order_id": order_id,
                "recipient": recipient,
                "requested_amount": amount,
                "order_total": order_total,
                "total_refunds": total_refunds,
                "remaining_balance": remaining_balance
            }, result)
            return result
        
        payment_id = f"payment_{uuid.uuid4().hex[:8]}"
        payment_data = {
            "id": payment_id,
            "order_id": order_id,
            "amount": payment_amount,
            "order_total": order_total,
            "total_refunds": total_refunds,
            "remaining_balance": remaining_balance,
            "recipient": actual_recipient,
            "seller": order_data.get("seller_id") or order_data.get("seller"),
            "released_date": datetime.now().isoformat(),
            "released_by": "moderator@marketplace.com"
        }
        
        payment_file = self.outbox_financial / f"{payment_id}.json"
        with open(payment_file, 'w') as f:
            json.dump(payment_data, f, indent=2)
        
        result = {
            "success": True,
            "payment_id": payment_id,
            "order_id": order_id,
            "amount": payment_amount,
            "order_total": order_total,
            "total_refunds": total_refunds,
            "remaining_balance": remaining_balance,
            "recipient": actual_recipient
        }
        
        self.log_action("order", {
            "action": "release_payment",
            "order_id": order_id,
            "actual_amount": payment_amount,
            "requested_amount": amount,
            "order_total": order_total,
            "total_refunds": total_refunds,
            "remaining_balance": remaining_balance,
            "requested_recipient": recipient,
            "actual_recipient": actual_recipient,
            "seller": order_data.get("seller_id") or order_data.get("seller")
        }, result)
        return result


class MessageTool(BaseEnvironmentTool):
    """
    Unified message tool with multiple actions.
    """
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.messages_dir = self.sandbox_dir / "messages"
        
        self.outbox_communications = self.outbox / "communications"
        self.outbox_communications.mkdir(exist_ok=True, parents=True)
    
    _PARAM_ACTIONS = {
        "thread_id": ["list"],
        "participant": ["list"],
        "message_id": ["read"],
        "recipient": ["send"],
        "subject": ["send"],
        "message": ["send"],
    }

    async def execute(
        self,
        action: Literal["list", "read", "send"],
        thread_id: Optional[str] = None,
        participant: Optional[str] = None,
        message_id: Optional[str] = None,
        recipient: Optional[str] = None,
        subject: Optional[str] = None,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute message action.

        Args:
            action: Action to perform (list, read, send)
            thread_id: Thread ID (for list, to filter by thread)
            participant: Filter by participant (for list)
            message_id: Message/thread ID (for read)
            recipient: Message recipient (for send)
            subject: Message subject (for send)
            message: Message content (for send)

        Returns:
            Action-specific result
        """
        provided = {
            "thread_id": thread_id, "participant": participant,
            "message_id": message_id, "recipient": recipient,
            "subject": subject, "message": message,
        }
        violations = []
        for param_name, value in provided.items():
            if value is None:
                continue
            valid_actions = self._PARAM_ACTIONS.get(param_name, [])
            if action not in valid_actions:
                violations.append(
                    f"'{param_name}' is not valid for action '{action}' "
                    f"(used by: {', '.join(valid_actions)})"
                )
        if violations:
            return {
                "error": f"Invalid parameters for action '{action}': "
                         + "; ".join(violations)
                         + ". No action was performed."
            }

        if message_id:
            message_id = normalize_id(message_id, "thread")
        if thread_id:
            thread_id = normalize_id(thread_id, "thread")

        if action == "list":
            return await self._list(thread_id, participant)
        elif action == "read":
            return await self._read(message_id)
        elif action == "send":
            return await self._send(recipient, subject, message)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list(
        self,
        thread_id: Optional[str] = None,
        participant: Optional[str] = None
    ) -> Dict[str, Any]:
        """List message threads with optional filters."""
        if not self.messages_dir.exists():
            result = {"error": "Messages directory not found"}
            self.log_action("message", {
                "action": "list",
                "thread_id": thread_id,
                "participant": participant
            }, result)
            return result
        
        threads = []
        for message_file in self.messages_dir.glob("*.json"):
            message_data = self._read_json_and_inject(message_file)
            
            if thread_id and message_data.get("thread_id") != thread_id:
                continue
            if participant:
                participants = message_data.get("participants", [])
                if participant not in participants:
                    continue
            
            threads.append({
                "thread_id": message_data.get("thread_id"),
                "participants": message_data.get("participants", []),
                "subject": message_data.get("subject"),
                "message_count": len(message_data.get("messages", [])),
                "last_message_date": message_data.get("messages", [{}])[-1].get("date") if message_data.get("messages") else None
            })
        
        result = {"threads": threads, "count": len(threads)}
        self.log_action("message", {
            "action": "list",
            "thread_id": thread_id,
            "participant": participant
        }, result)
        return result
    
    async def _read(self, message_id: str) -> Dict[str, Any]:
        """Read message thread."""
        if not message_id:
            result = {"error": "message_id is required"}
            self.log_action("message", {"action": "read", "message_id": message_id}, result)
            return result
        
        message_file = self.messages_dir / f"{message_id}.json"
        if not message_file.exists():
            result = {"error": f"Message thread '{message_id}' not found"}
            self.log_action("message", {"action": "read", "message_id": message_id}, result)
            return result
        
        message_data = self._read_json_and_inject(message_file)
        result = {"success": True, **message_data}
        
        self.log_action("message", {"action": "read", "message_id": message_id}, result)
        return result
    
    async def _send(
        self,
        recipient: str,
        subject: str,
        message: str
    ) -> Dict[str, Any]:
        """
        Send message to recipient.
        """
        if not recipient or not message:
            result = {"error": "recipient and message are required"}
            self.log_action("message", {
                "action": "send",
                "recipient": recipient,
                "subject": subject,
                "message": message
            }, result)
            return result
        
        message_id = f"msg_{uuid.uuid4().hex[:8]}"
        message_data = {
            "id": message_id,
            "from": "moderator@marketplace.com",
            "to": recipient,
            "subject": subject or "Message from moderator",
            "message": message,
            "sent_date": datetime.now().isoformat()
        }
        
        message_file = self.outbox_communications / f"{message_id}.json"
        with open(message_file, 'w') as f:
            json.dump(message_data, f, indent=2)
        
        result = {
            "success": True,
            "message_id": message_id,
            "recipient": recipient
        }
        
        self.log_action("message", {
            "action": "send",
            "recipient": recipient,
            "subject": subject,
            "message": message
        }, result)
        return result


class EvidenceTool(BaseEnvironmentTool):
    """
    Unified evidence tool for reading evidence files.
    
    Evidence files contain injection placeholders in markdown format.
    """
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.evidence_dir = self.sandbox_dir / "evidence"
        self.disputes_dir = self.sandbox_dir / "disputes"
    
    async def execute(
        self,
        action: Literal["list", "read"],
        evidence_id: Optional[str] = None,
        dispute_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute evidence action.
        
        Args:
            action: Action to perform (list, read)
            evidence_id: Evidence ID (for read)
            dispute_id: Filter by dispute ID (for list)
        
        Returns:
            Action-specific result
        """
        if evidence_id:
            evidence_id = normalize_id(evidence_id, "evidence")
        if dispute_id:
            dispute_id = normalize_id(dispute_id, "dispute")

        if action == "list":
            return await self._list(dispute_id)
        elif action == "read":
            return await self._read(evidence_id)
        else:
            return {"error": f"Unknown action: {action}"}

    def _load_evidence_index(self) -> Dict[str, Dict[str, Any]]:
        """Load the evidence index file."""
        index_file = self.evidence_dir / "_evidence_index.json"
        if index_file.exists():
            try:
                with open(index_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    async def _list(self, dispute_id: Optional[str] = None) -> Dict[str, Any]:
        """List evidence files, optionally filtered by dispute_id."""
        if not self.evidence_dir.exists():
            result = {"error": "Evidence directory not found"}
            self.log_action("evidence", {"action": "list", "dispute_id": dispute_id}, result)
            return result
        
        evidence_index = self._load_evidence_index()
        
        evidence_list = []
        for evidence_id, metadata in evidence_index.items():
            if dispute_id and metadata.get("dispute_id") != dispute_id:
                continue
            
            evidence_list.append({
                "id": evidence_id,
                "title": metadata.get("title", evidence_id),
                "dispute_id": metadata.get("dispute_id"),
                "type": metadata.get("type"),
                "submitted_by": metadata.get("submitted_by"),
                "submitted": metadata.get("submitted")
            })
        
        result = {"evidence": evidence_list, "count": len(evidence_list)}
        self.log_action("evidence", {"action": "list", "dispute_id": dispute_id}, result)
        return result
    
    async def _read(self, evidence_id: str) -> Dict[str, Any]:
        """Read evidence file with injection placeholder replacement."""
        if not evidence_id:
            result = {"error": "evidence_id is required"}
            self.log_action("evidence", {"action": "read", "evidence_id": evidence_id}, result)
            return result

        evidence_json = self.evidence_dir / f"{evidence_id}.json"
        evidence_md = self.evidence_dir / f"{evidence_id}.md"

        if evidence_json.exists():
            result = self._read_evidence_json(evidence_json, evidence_id)
        elif evidence_md.exists():
            content = self._read_and_inject(evidence_md)
            result = {
                "success": True,
                "evidence_id": evidence_id,
                "content": content
            }
        else:
            result = {"error": f"Evidence '{evidence_id}' not found"}

        self.log_action("evidence", {"action": "read", "evidence_id": evidence_id}, result)
        return result

    def _read_evidence_json(self, filepath: Path, evidence_id: str) -> Dict[str, Any]:
        """Read structured JSON evidence, injecting only into submitted_text."""
        with open(filepath, 'r') as f:
            data = json.load(f)

        if self.injection_manager and "submitted_text" in data:
            data["submitted_text"] = self.injection_manager.replace_placeholders(
                data["submitted_text"]
            )

        return {
            "success": True,
            "evidence_id": evidence_id,
            "type": data.get("type", ""),
            "submitted_by": data.get("submitted_by", ""),
            "submitted": data.get("submitted", ""),
            "attachments": data.get("attachments", []),
            "submitted_text": data.get("submitted_text", "")
        }


class ListingTool(BaseEnvironmentTool):
    """
    Unified listing tool for reading product listings.
    
    Listing files contain injection placeholders in markdown format.
    """
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.listings_dir = self.sandbox_dir / "listings"
    
    async def execute(
        self,
        action: Literal["read", "list"],
        listing_id: Optional[str] = None,
        seller: Optional[str] = None,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute listing action.
        
        Args:
            action: Action to perform (read, list)
            listing_id: Listing ID (for read)
            seller: Filter by seller (for list)
            category: Filter by category (for list)
        
        Returns:
            Action-specific result
        """
        if listing_id:
            listing_id = normalize_id(listing_id, "listing")

        if action == "read":
            return await self._read(listing_id)
        elif action == "list":
            return await self._list(seller, category)
        else:
            return {"error": f"Unknown action: {action}"}
    
    def _load_listings_index(self) -> Dict[str, Dict[str, Any]]:
        """Load the listings index file."""
        index_file = self.listings_dir / "_listings_index.json"
        if index_file.exists():
            try:
                with open(index_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    async def _read(self, listing_id: str) -> Dict[str, Any]:
        """Read listing file with injection placeholder replacement."""
        if not listing_id:
            result = {"error": "listing_id is required"}
            self.log_action("listing", {"action": "read", "listing_id": listing_id}, result)
            return result
        
        listing_file = self.listings_dir / f"{listing_id}.md"
        if not listing_file.exists():
            result = {"error": f"Listing '{listing_id}' not found"}
            self.log_action("listing", {"action": "read", "listing_id": listing_id}, result)
            return result
        
        content = self._read_and_inject(listing_file)
        
        result = {
            "success": True,
            "listing_id": listing_id,
            "content": content
        }
        
        self.log_action("listing", {"action": "read", "listing_id": listing_id}, result)
        return result
    
    async def _list(
        self,
        seller: Optional[str] = None,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """List product listings using JSON index."""
        if not self.listings_dir.exists():
            result = {"error": "Listings directory not found"}
            self.log_action("listing", {
                "action": "list",
                "seller": seller,
                "category": category
            }, result)
            return result
        
        listings_index = self._load_listings_index()
        
        listings = []
        for listing_id, metadata in listings_index.items():
            if seller and metadata.get("seller_id") != seller:
                continue
            
            if category:
                listing_category = metadata.get("category", "")
                if category.lower() not in listing_category.lower():
                    continue
            
            listings.append({
                "id": listing_id,
                "title": metadata.get("title", listing_id),
                "seller_id": metadata.get("seller_id"),
                "category": metadata.get("category"),
                "price": metadata.get("price"),
                "condition": metadata.get("condition"),
                "status": metadata.get("status")
            })
        
        result = {"listings": listings, "count": len(listings)}
        self.log_action("listing", {
            "action": "list",
            "seller": seller,
            "category": category
        }, result)
        return result


class PolicyTool(BaseEnvironmentTool):
    """
    Policy tool for reading platform policies.
    
    Reads platform_policies.md which contains the actual platform policies.
    Supports listing policy sections and reading specific sections.
    Lets the agent check policy claims made in other content against the policy text.
    """
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.policies_dir = self.sandbox_dir / "policies"
        self._policy_cache = None
    
    def _parse_file(self, filepath) -> Dict[str, Dict[str, Any]]:
        """Parse a single policy markdown file into structured sections."""
        if not filepath.exists():
            return {}

        content = self._read_and_inject(filepath)
        lines = content.split('\n')

        sections = {}
        current_section_id = None
        current_section_title = None
        current_content_lines = []

        import re

        for line in lines:
            main_match = re.match(r'^##\s+([\w.]+)\.\s+(.+)$', line)
            sub_match = re.match(r'^###\s+([\w.]+)\s+(.+)$', line)

            if main_match:
                if current_section_id is not None:
                    sections[current_section_id] = {
                        "id": current_section_id,
                        "title": current_section_title,
                        "content": '\n'.join(current_content_lines).strip()
                    }
                current_section_id = main_match.group(1)
                current_section_title = main_match.group(2).strip()
                current_content_lines = []
            elif sub_match:
                if current_section_id is not None:
                    sections[current_section_id] = {
                        "id": current_section_id,
                        "title": current_section_title,
                        "content": '\n'.join(current_content_lines).strip()
                    }
                current_section_id = sub_match.group(1)
                current_section_title = sub_match.group(2).strip()
                current_content_lines = []
            else:
                if current_section_id is not None:
                    current_content_lines.append(line)

        if current_section_id is not None:
            sections[current_section_id] = {
                "id": current_section_id,
                "title": current_section_title,
                "content": '\n'.join(current_content_lines).strip()
            }

        return sections

    def _parse_policies(self) -> Dict[str, Dict[str, Any]]:
        """
        Parse policy files into structured sections.

        Returns a dict mapping section IDs to their title and content.
        Platform policies use numeric IDs (1, 1.1, etc.).
        Agent procedures use "A." prefix (A.1, A.1.1, etc.).
        """
        if self._policy_cache is not None:
            return self._policy_cache

        sections = {}
        sections.update(self._parse_file(self.policies_dir / "platform_policies.md"))
        sections.update(self._parse_file(self.policies_dir / "agent_procedures.md"))

        self._policy_cache = sections
        return sections
    
    async def execute(
        self,
        action: Literal["list", "read"],
        policy_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute policy action.
        
        Args:
            action: Action to perform (list, read)
            policy_id: Policy section ID (for read)
        
        Returns:
            Action-specific result
        """
        if action == "list":
            return await self._list()
        elif action == "read":
            return await self._read(policy_id)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _list(self) -> Dict[str, Any]:
        """List all available policy sections with their IDs and titles."""
        sections = self._parse_policies()
        
        if not sections:
            result = {"error": "Policy file not found or could not be parsed"}
            self.log_action("policy", {"action": "list"}, result)
            return result
        
        policy_list = []
        def _sort_key(item):
            sid = item[0]
            parts = sid.split('.')
            return [(int(p) if p.isdigit() else (1000 + ord(p[0]))) for p in parts]
        for section_id, section_data in sorted(sections.items(), key=_sort_key):
            policy_list.append({
                "id": section_id,
                "title": section_data["title"]
            })
        
        result = {"policies": policy_list, "count": len(policy_list)}
        self.log_action("policy", {"action": "list"}, result)
        return result
    
    async def _read(self, policy_id: Optional[str] = None) -> Dict[str, Any]:
        """Read a specific policy section by ID."""
        if not policy_id:
            result = {"error": "policy_id is required. Use action='list' to see available policy IDs."}
            self.log_action("policy", {"action": "read", "policy_id": policy_id}, result)
            return result
        
        sections = self._parse_policies()
        
        if not sections:
            result = {"error": "Policy file not found or could not be parsed"}
            self.log_action("policy", {"action": "read", "policy_id": policy_id}, result)
            return result
        
        policy_id = policy_id.strip()
        
        if policy_id not in sections:
            available_ids = list(sections.keys())
            result = {
                "error": f"Policy section '{policy_id}' not found. Available sections: {available_ids}"
            }
            self.log_action("policy", {"action": "read", "policy_id": policy_id}, result)
            return result
        
        section = sections[policy_id]
        
        result = {
            "success": True,
            "policy_id": policy_id,
            "title": section["title"],
            "content": section["content"]
        }
        
        self.log_action("policy", {"action": "read", "policy_id": policy_id}, result)
        return result


class UserTool(BaseEnvironmentTool):
    """
    Unified user tool for reading user profiles.
    
    Profiles include contact details and other personal fields.
    """
    
    def __init__(self, sandbox_dir: str, injection_manager=None):
        super().__init__(sandbox_dir, injection_manager)
        self.users_dir = self.sandbox_dir / "users"
        self.buyers_dir = self.users_dir / "buyers"
        self.sellers_dir = self.users_dir / "sellers"
    
    async def execute(
        self,
        action: Literal["read", "list"],
        user_id: Optional[str] = None,
        user_type: Optional[str] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute user action.
        
        Args:
            action: Action to perform (read, list)
            user_id: User ID (for read)
            user_type: Filter by type (for list): buyer, seller, all
            status: Filter by status (for list): active, suspended, banned
        
        Returns:
            Action-specific result
        """
        if action == "read":
            return await self._read(user_id)
        elif action == "list":
            return await self._list(user_type, status)
        else:
            return {"error": f"Unknown action: {action}"}
    
    async def _read(self, user_id: str) -> Dict[str, Any]:
        """Read user profile with PII."""
        if not user_id:
            result = {"error": "user_id is required"}
            self.log_action("user", {"action": "read", "user_id": user_id}, result)
            return result
        
        user_file = None
        user_type = None
        
        buyer_file = self.buyers_dir / f"{user_id}.json"
        if buyer_file.exists():
            user_file = buyer_file
            user_type = "buyer"
        else:
            seller_file = self.sellers_dir / f"{user_id}.json"
            if seller_file.exists():
                user_file = seller_file
                user_type = "seller"
        
        if not user_file:
            result = {"error": f"User '{user_id}' not found"}
            self.log_action("user", {"action": "read", "user_id": user_id}, result)
            return result
        
        user_data = self._read_json_and_inject(user_file)
        user_data["user_type"] = user_type
        
        result = {"success": True, **user_data}
        
        self.log_action("user", {"action": "read", "user_id": user_id}, result)
        return result
    
    async def _list(
        self,
        user_type: Optional[str] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """List users with optional filters."""
        users = []
        
        search_dirs = []
        if not user_type or user_type == "all":
            if self.buyers_dir.exists():
                search_dirs.append(("buyer", self.buyers_dir))
            if self.sellers_dir.exists():
                search_dirs.append(("seller", self.sellers_dir))
        elif user_type == "buyer":
            if self.buyers_dir.exists():
                search_dirs.append(("buyer", self.buyers_dir))
        elif user_type == "seller":
            if self.sellers_dir.exists():
                search_dirs.append(("seller", self.sellers_dir))
        
        for utype, directory in search_dirs:
            for user_file in directory.glob("*.json"):
                user_data = self._read_json_and_inject(user_file)
                
                if status and user_data.get("status") != status:
                    continue
                
                users.append({
                    "id": user_data.get("id"),
                    "username": user_data.get("username"),
                    "email": user_data.get("email"),
                    "user_type": utype,
                    "status": user_data.get("status"),
                    "join_date": user_data.get("join_date")
                })
        
        result = {"users": users, "count": len(users)}
        self.log_action("user", {
            "action": "list",
            "user_type": user_type,
            "status": status
        }, result)
        return result
