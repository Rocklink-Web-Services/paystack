# Copyright (c) 2026, Rockify and contributors
# For license information, please see license.txt

import frappe

from payments.utils import create_payment_gateway


def after_install():
	"""Register the Paystack Payment Gateway record on install so it is
	immediately selectable when creating a Payment Gateway Account."""
	create_payment_gateway("Paystack")
	frappe.db.commit()


def after_uninstall():
	"""Remove the Payment Gateway record on uninstall."""
	if frappe.db.exists("Payment Gateway", "Paystack"):
		frappe.delete_doc(
			"Payment Gateway", "Paystack", ignore_permissions=True, force=True
		)
	frappe.db.commit()
