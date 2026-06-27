# Copyright (c) 2026, Rockify and contributors
# For license information, please see license.txt

import json

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils import call_hook_method, cint, flt, get_url

from payments.utils import create_payment_gateway

# Paystack settles in the smallest currency subunit (kobo, pesewas, cents).
# Every Paystack-supported currency uses a x100 subunit.
SUBUNIT_MULTIPLIER = 100
SUPPORTED_CURRENCIES = ["NGN", "GHS", "ZAR", "KES", "USD"]

PAYSTACK_API_BASE = "https://api.paystack.co"


def _clean(value):
	"""ERPNext sometimes passes byte-encoded strings (title/description/payer_name).
	Coerce bytes -> str so JSON serialisation to our DB and to Paystack never breaks.
	"""
	if isinstance(value, bytes):
		return value.decode("utf-8", errors="replace")
	return value


class PaystackSettings(Document):
	supported_currencies = SUPPORTED_CURRENCIES

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------
	def validate(self):
		if self.enabled and not self.get_password("secret_key", raise_exception=False):
			frappe.throw(
				_("Please enter the Paystack Secret Key before enabling the gateway.")
			)

	def on_update(self):
		# Register / refresh the Payment Gateway record so ERPNext can route to us.
		# Single doctype: self.name == "Paystack Settings".
		create_payment_gateway(
			"Paystack",
			settings="Paystack Settings",
			controller="Paystack Settings",
		)
		call_hook_method("payment_gateway_enabled", gateway="Paystack")

	# ------------------------------------------------------------------
	# Gateway contract (called by the Payments framework)
	# ------------------------------------------------------------------
	def validate_transaction_currency(self, currency):
		if currency not in self.supported_currencies:
			frappe.throw(
				_(
					"Paystack does not support transactions in the currency '{0}'. "
					"Supported currencies are: {1}"
				).format(currency, ", ".join(self.supported_currencies))
			)

	def get_payment_url(self, **kwargs):
		"""Called by Payment Request. Creates an Integration Request to track this
		attempt, initialises a Paystack transaction, and returns the hosted
		checkout URL for ERPNext to redirect the customer to.
		"""
		kwargs = {key: _clean(value) for key, value in kwargs.items()}

		# Track this payment attempt. We use the Integration Request name as the
		# Paystack `reference`, so the callback/webhook can resolve it directly.
		integration_request = frappe.get_doc(
			{
				"doctype": "Integration Request",
				"integration_request_service": "Paystack",
				"status": "Queued",
				"reference_doctype": kwargs.get("reference_doctype"),
				"reference_docname": kwargs.get("reference_docname"),
				"data": json.dumps(kwargs, default=str),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()  # noqa: persist the audit log before leaving for Paystack

		reference = integration_request.name
		amount = flt(kwargs.get("amount"))
		currency = kwargs.get("currency")
		subunit_amount = int(round(amount * SUBUNIT_MULTIPLIER))

		callback_url = get_url(
			"/api/method/paystack.api.callback?reference={0}".format(reference)
		)

		payload = {
			"email": kwargs.get("payer_email") or frappe.session.user,
			"amount": subunit_amount,
			"currency": currency,
			"reference": reference,
			"callback_url": callback_url,
			"metadata": {
				"reference_doctype": kwargs.get("reference_doctype"),
				"reference_docname": kwargs.get("reference_docname"),
				"description": kwargs.get("description"),
				"payer_name": kwargs.get("payer_name"),
				"integration_request": reference,
			},
		}

		try:
			response = requests.post(
				PAYSTACK_API_BASE + "/transaction/initialize",
				headers=self._auth_headers(),
				json=payload,
				timeout=30,
			)
			response_data = response.json()
		except Exception:
			self._fail_request(integration_request, frappe.get_traceback())
			frappe.log_error("Paystack: failed to initialise transaction")
			frappe.throw(
				_("Could not connect to Paystack. Please try again or contact support.")
			)

		if not response.ok or not response_data.get("status"):
			self._fail_request(integration_request, json.dumps(response_data))
			frappe.log_error(
				message=json.dumps(response_data),
				title="Paystack: transaction initialise rejected",
			)
			frappe.throw(
				_("Paystack rejected the payment: {0}").format(
					response_data.get("message") or _("unknown error")
				)
			)

		data = response_data.get("data") or {}
		integration_request.db_set("output", json.dumps(data), update_modified=False)
		integration_request.db_set("status", "Authorized", update_modified=False)
		frappe.db.commit()

		authorization_url = data.get("authorization_url")
		if not authorization_url:
			frappe.throw(_("Paystack did not return a checkout URL."))

		return authorization_url

	# ------------------------------------------------------------------
	# Verification — shared by the browser callback AND the webhook
	# ------------------------------------------------------------------
	def verify_transaction(self, reference):
		"""Confirm a transaction straight from Paystack and, on success, mark the
		linked document as paid. Idempotent, amount-checked, and currency-checked.
		Returns a small dict describing the outcome.
		"""
		if not reference:
			return {"ok": False, "message": "Missing reference"}

		if not frappe.db.exists("Integration Request", reference):
			frappe.log_error(
				message="Unknown reference: {0}".format(reference),
				title="Paystack: verify for unknown Integration Request",
			)
			return {"ok": False, "message": "Unknown reference"}

		integration_request = frappe.get_doc("Integration Request", reference)

		# Idempotency — never double-process a completed payment.
		if integration_request.status == "Completed":
			return {"ok": True, "message": "Already completed", "already": True}

		try:
			response = requests.get(
				PAYSTACK_API_BASE + "/transaction/verify/" + reference,
				headers=self._auth_headers(),
				timeout=30,
			)
			response_data = response.json()
		except Exception:
			frappe.log_error("Paystack: verify request failed")
			return {"ok": False, "message": "Could not reach Paystack"}

		data = response_data.get("data") or {}
		status = data.get("status")

		if not response.ok or not response_data.get("status") or status != "success":
			self._fail_request(integration_request, json.dumps(response_data))
			return {"ok": False, "message": "Payment not successful", "status": status}

		# ---- Security: confirm amount + currency match what we asked for ----
		expected = json.loads(integration_request.data or "{}")
		expected_amount = int(round(flt(expected.get("amount")) * SUBUNIT_MULTIPLIER))
		expected_currency = expected.get("currency")
		paid_amount = cint(data.get("amount"))
		paid_currency = data.get("currency")

		amount_mismatch = paid_amount < expected_amount
		currency_mismatch = bool(
			expected_currency and paid_currency and paid_currency != expected_currency
		)
		if amount_mismatch or currency_mismatch:
			self._fail_request(
				integration_request,
				"Amount/currency mismatch. Expected {0} {1}, got {2} {3}".format(
					expected_amount, expected_currency, paid_amount, paid_currency
				),
			)
			frappe.log_error(
				message=json.dumps({"expected": expected, "paystack": data}, default=str),
				title="Paystack: amount/currency mismatch",
			)
			return {"ok": False, "message": "Amount mismatch"}

		# ---- Mark the originating document as paid ----
		integration_request.db_set("output", json.dumps(data), update_modified=False)
		try:
			if (
				integration_request.reference_doctype
				and integration_request.reference_docname
			):
				ref_doc = frappe.get_doc(
					integration_request.reference_doctype,
					integration_request.reference_docname,
				)
				ref_doc.run_method("on_payment_authorized", "Completed")
			integration_request.db_set("status", "Completed", update_modified=False)
			frappe.db.commit()
		except Exception:
			self._fail_request(integration_request, frappe.get_traceback())
			frappe.log_error("Paystack: error completing reference document")
			return {"ok": False, "message": "Could not complete the order"}

		return {"ok": True, "message": "Payment verified"}

	# ------------------------------------------------------------------
	# helpers
	# ------------------------------------------------------------------
	def _auth_headers(self):
		secret = self.get_password("secret_key")
		return {
			"Authorization": "Bearer {0}".format(secret),
			"Content-Type": "application/json",
		}

	@staticmethod
	def _fail_request(integration_request, error):
		integration_request.db_set("error", error, update_modified=False)
		integration_request.db_set("status", "Failed", update_modified=False)
		frappe.db.commit()
