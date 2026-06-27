// Copyright (c) 2026, Rockify and contributors
// For license information, please see license.txt

frappe.ui.form.on("Paystack Settings", {
	refresh(frm) {
		const base = window.location.origin;
		const webhook = `${base}/api/method/paystack.api.webhook`;

		frm.get_field("instructions_html").$wrapper.html(`
			<div style="padding:14px;border-radius:8px;background:#f0f7ff;border:1px solid #cfe3ff;line-height:1.6;">
				<p style="margin:0 0 8px;"><b>1.</b> Open the Paystack Dashboard → <b>Settings → API Keys &amp; Webhooks</b>.</p>
				<p style="margin:0 0 8px;"><b>2.</b> Copy your <b>Public Key</b> and <b>Secret Key</b> into the fields on the left.</p>
				<p style="margin:0 0 6px;"><b>3.</b> In that same Paystack page, set the <b>Webhook URL</b> to:</p>
				<pre style="user-select:all;padding:8px;background:#fff;border:1px solid #d9d9d9;border-radius:6px;margin:0 0 8px;">${webhook}</pre>
				<p style="margin:0;"><b>4.</b> Tick <b>Enabled</b> above and <b>Save</b>. Use <code>sk_test_</code> keys to test first.</p>
			</div>
		`);
	},
});
