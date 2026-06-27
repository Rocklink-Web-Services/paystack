# Copyright (c) 2026, Rockify and contributors
# For license information, please see license.txt

app_name = "paystack"
app_title = "Paystack"
app_publisher = "Rockify"
app_description = "Paystack payment gateway integration for ERPNext / Frappe"
app_email = "payments@rockifyerp.com"
app_license = "MIT"

# This app builds on the Frappe Payments framework.
required_apps = ["frappe/payments"]

# Installation
# ------------
after_install = "paystack.install.after_install"
after_uninstall = "paystack.install.after_uninstall"
