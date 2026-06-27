# Copyright (c) 2026, Rockify and contributors
# For license information, please see license.txt

import hashlib
import hmac
import json

import frappe


def _get_settings():
	return frappe.get_doc("Paystack Settings")


@frappe.whitelist(allow_guest=True)
def callback(reference=None, trxref=None, **kwargs):
	"""Browser redirect target after the customer pays on Paystack.

	Verifies the transaction server-side, then redirects the customer to a
	success or failure page. The webhook (below) is the authoritative source of
	truth; this just gives the customer immediate feedback.
	"""
	reference = reference or trxref
	settings = _get_settings()
	result = settings.verify_transaction(reference)

	redirect_to = "/payment-success" if result.get("ok") else "/payment-failed"

	# If the originating flow asked for a specific return page, honour it.
	try:
		if reference and frappe.db.exists("Integration Request", reference):
			integration_request = frappe.get_doc("Integration Request", reference)
			data = json.loads(integration_request.data or "{}")
			if data.get("redirect_to"):
				redirect_to = data.get("redirect_to")
	except Exception:
		pass

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = redirect_to


@frappe.whitelist(allow_guest=True)
def webhook(**kwargs):
	"""Server-to-server Paystack webhook — the source of truth.

	Fires even if the customer closes the browser before the redirect. The raw
	request body is verified against the `x-paystack-signature` header using
	HMAC-SHA512 with the secret key before anything is trusted.
	"""
	settings = _get_settings()

	signature = frappe.get_request_header("x-paystack-signature")
	raw_body = frappe.request.get_data()  # bytes — must hash the raw body
	secret = settings.get_password("secret_key")
	computed = hmac.new(
		secret.encode("utf-8"), raw_body, hashlib.sha512
	).hexdigest()

	if not signature or not hmac.compare_digest(signature, computed):
		frappe.local.response["http_status_code"] = 401
		return "Invalid signature"

	try:
		payload = json.loads(raw_body)
	except Exception:
		frappe.local.response["http_status_code"] = 400
		return "Bad payload"

	event = payload.get("event")
	data = payload.get("data") or {}
	reference = data.get("reference")

	# Only act on successful charges; verify independently regardless of payload.
	if event == "charge.success" and reference:
		settings.verify_transaction(reference)

	# Always 200 once received so Paystack stops retrying.
	frappe.local.response["http_status_code"] = 200
	return "OK"
