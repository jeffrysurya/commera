# Copyright (c) 2026, company@bwhstudios.com and Contributors
# Tests for the "Require Packing Slip Before Delivery" setting (utils.require_packing_slip_for_ecommerce_delivery).

import frappe
from frappe.tests import IntegrationTestCase

from commera.tests.test_admin_orders import make_test_sales_order

SETTING = "require_packing_slip_for_ecommerce_delivery"


def set_guard(enabled):
	frappe.db.set_single_value("Commera Settings", SETTING, enabled)
	frappe.clear_document_cache("Commera Settings", "Commera Settings")


def draft_delivery_note(sales_order):
	# ERPNext moved its mappers to a sibling `mapper` module; both layouts are in the wild.
	try:
		from erpnext.selling.doctype.sales_order.mapper import make_delivery_note
	except ImportError:
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	delivery_note = make_delivery_note(sales_order.name)
	delivery_note.flags.ignore_permissions = True
	delivery_note.insert()
	return delivery_note


def draft_packing_slip(delivery_note):
	try:
		from erpnext.stock.doctype.delivery_note.mapper import make_packing_slip
	except ImportError:
		from erpnext.stock.doctype.delivery_note.delivery_note import make_packing_slip

	packing_slip = make_packing_slip(delivery_note.name)
	packing_slip.flags.ignore_permissions = True
	packing_slip.insert()
	return packing_slip


class TestPackingSlipGuard(IntegrationTestCase):
	def setUp(self):
		self.sales_order = make_test_sales_order()
		frappe.db.set_value("Sales Order", self.sales_order.name, "custom_ecommerce_payment_mode", "Cash")
		self.addCleanup(set_guard, 0)
		set_guard(1)

	def test_a_storefront_order_cannot_ship_without_a_packing_slip(self):
		delivery_note = draft_delivery_note(self.sales_order)

		with self.assertRaises(frappe.ValidationError):
			delivery_note.submit()

	def test_a_draft_packing_slip_is_not_enough(self):
		delivery_note = draft_delivery_note(self.sales_order)
		draft_packing_slip(delivery_note)

		with self.assertRaises(frappe.ValidationError):
			delivery_note.submit()

	def test_a_storefront_order_ships_once_the_packing_slip_is_submitted(self):
		delivery_note = draft_delivery_note(self.sales_order)
		draft_packing_slip(delivery_note).submit()

		delivery_note.reload()
		delivery_note.submit()

		self.assertEqual(delivery_note.docstatus, 1)

	def test_a_desk_order_is_left_alone(self):
		frappe.db.set_value("Sales Order", self.sales_order.name, "custom_ecommerce_payment_mode", None)
		delivery_note = draft_delivery_note(self.sales_order)

		delivery_note.submit()

		self.assertEqual(delivery_note.docstatus, 1)

	def test_switching_the_setting_off_lets_a_storefront_order_ship(self):
		set_guard(0)
		delivery_note = draft_delivery_note(self.sales_order)

		delivery_note.submit()

		self.assertEqual(delivery_note.docstatus, 1)
