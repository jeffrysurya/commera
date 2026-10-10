# Copyright (c) 2026, company@bwhstudios.com and Contributors

"""The `commera_address_fields` hook: other apps may add Address fields to what checkout saves.

With no app declaring the hook, saving an address must behave exactly as it did before the hook existed.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from commera.api.payments import add_party_address, get_extension_address_values, get_party_address

CHECKOUT_ADDRESS = {
	"city": "Riyadh",
	"country": "Saudi Arabia",
	"state": "Riyadh Province",
	"full_address": "1 Billing Street",
	"landmark": "Near the park",
	"po_box": "12345",
	"phone_number": "+966500000001",
	"email": "zz_extension@example.com",
	"tata_shipping_location": "LOCATION-1",
}

# What add_party_address built before the hook existed.
TODAYS_VALUES = {
	"address_type": "Billing",
	"city": "Riyadh",
	"country": "Saudi Arabia",
	"state": "Riyadh Province",
	"address_line1": "1 Billing Street",
	"address_line2": "Near the park",
	"pincode": "12345",
	"phone": "+966500000001",
	"email_id": "zz_extension@example.com",
}


class TestExtensionAddressFields(IntegrationTestCase):
	def test_no_declaring_app_means_no_extra_values(self):
		with (
			patch("commera.api.payments.frappe.get_hooks", return_value=[]),
			patch("commera.api.payments.frappe.get_meta", return_value=SimpleNamespace(has_field=bool)),
		):
			self.assertEqual(get_extension_address_values(CHECKOUT_ADDRESS), {})

	def test_add_party_address_builds_exactly_todays_values_when_no_app_declares_fields(self):
		with (
			patch("commera.api.payments.frappe.get_hooks", return_value=[]),
			patch("commera.api.payments.frappe.get_meta", return_value=SimpleNamespace(has_field=bool)),
			patch("commera.api.payments.get_party_address", return_value="EXISTING") as lookup,
			patch("commera.api.payments.frappe.get_doc") as get_doc,
		):
			add_party_address("Some Customer", CHECKOUT_ADDRESS, "Billing")

		lookup.assert_called_once_with("Some Customer", TODAYS_VALUES)
		get_doc.assert_called_once_with("Address", "EXISTING")

	def test_the_dedupe_filter_is_unchanged_when_no_app_declares_fields(self):
		with (
			patch("commera.api.payments.frappe.get_hooks", return_value=[]),
			patch("commera.api.payments.frappe.get_all", return_value=[]) as get_all,
		):
			values = dict(TODAYS_VALUES, address_line2=None)
			get_party_address("Some Customer", values)

		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(
			filters,
			[
				["Address", "address_type", "=", "Billing"],
				["Address", "city", "=", "Riyadh"],
				["Address", "country", "=", "Saudi Arabia"],
				["Address", "state", "=", "Riyadh Province"],
				["Address", "address_line1", "=", "1 Billing Street"],
				["Address", "address_line2", "is", "not set"],
				["Address", "pincode", "=", "12345"],
				["Address", "phone", "=", "+966500000001"],
				["Address", "email_id", "=", "zz_extension@example.com"],
				["Address", "disabled", "=", 0],
				["Dynamic Link", "link_doctype", "=", "Customer"],
				["Dynamic Link", "link_name", "=", "Some Customer"],
			],
		)

	def test_a_declared_field_that_exists_on_address_is_saved_and_joins_the_dedupe(self):
		meta = SimpleNamespace(has_field=lambda fieldname: fieldname == "tata_shipping_location")
		with (
			patch("commera.api.payments.frappe.get_hooks", return_value=["tata_shipping_location", "ghost"]),
			patch("commera.api.payments.frappe.get_meta", return_value=meta),
			patch("commera.api.payments.get_party_address", return_value="EXISTING") as lookup,
			patch("commera.api.payments.frappe.get_doc"),
		):
			add_party_address("Some Customer", CHECKOUT_ADDRESS, "Billing")

		self.assertEqual(lookup.call_args.args[1], {**TODAYS_VALUES, "tata_shipping_location": "LOCATION-1"})

	def test_a_declared_field_the_shopper_did_not_send_is_none(self):
		meta = SimpleNamespace(has_field=lambda fieldname: True)
		without_location = {
			key: value for key, value in CHECKOUT_ADDRESS.items() if key != "tata_shipping_location"
		}
		with (
			patch("commera.api.payments.frappe.get_hooks", return_value=["tata_shipping_location"]),
			patch("commera.api.payments.frappe.get_meta", return_value=meta),
		):
			self.assertEqual(get_extension_address_values(without_location), {"tata_shipping_location": None})
			self.assertEqual(
				get_extension_address_values({**without_location, "tata_shipping_location": ""}),
				{"tata_shipping_location": None},
			)
