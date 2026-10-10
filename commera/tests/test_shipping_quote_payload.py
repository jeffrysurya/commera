# Copyright (c) 2026, company@bwhstudios.com and Contributors

"""What commera hands a shipping provider when it quotes delivery options.

Besides the address fields the connector always sent, the destination now names the Address and the Company and
lists the cart's lines (`cart_items`). The parcel is exactly what it was, so a carrier that reads parcel items
(AfterShip) and one that rates on weight and pincode (Shiprocket) must both price exactly as before.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.data import flt

from commera.api import shipping
from commera.api.shipping import (
	DEFAULT_ITEM_WEIGHT_KG,
	DEFAULT_PARCEL_DIMENSIONS,
	get_cart_parcels,
	get_cart_weight,
	get_item_unit_weights,
	quote_options,
	to_kg,
)

ADDRESS_PAYLOAD = {
	"contact_name": "Home",
	"company_name": "Home",
	"line1": "1 Street",
	"line2": None,
	"city": "Riyadh",
	"state": "Riyadh Province",
	"pincode": "12345",
	"country": "Saudi Arabia",
	"phone": "+966500000001",
	"email": "zz_quote@example.com",
}


def make_item(item_code, qty, rate=100.0):
	return SimpleNamespace(item_code=item_code, item_name=f"{item_code} name", qty=qty, rate=rate)


def make_quotation(items):
	return SimpleNamespace(
		items=items, shipping_address_name="ADDR-1", company="Some Company", currency="SAR", conversion_rate=1
	)


def item_rows(**weights):
	"""frappe.get_all('Item') rows: code -> (weight_per_unit, weight_uom)."""
	return [
		frappe._dict(name=code, weight_per_unit=weight, weight_uom=uom)
		for code, (weight, uom) in weights.items()
	]


def weight_before_the_change(quotation, rows):
	"""get_cart_weight exactly as it was before get_item_unit_weights was extracted."""
	if not list({item.item_code for item in quotation.items}):
		return 0.0
	weight_by_item = {row.name: row for row in rows}
	total = 0.0
	for item in quotation.items:
		row = weight_by_item.get(item.item_code)
		unit_weight = to_kg(row) if row else 0.0
		total += abs(flt(item.qty)) * (unit_weight or DEFAULT_ITEM_WEIGHT_KG)
	return flt(total, 3)


class TestCartWeight(IntegrationTestCase):
	def test_get_cart_weight_keeps_its_output(self):
		rows = item_rows(A=(1.5, "Kg"), B=(0, "Kg"), C=(500, "Gram"), D=(2, "Furlong"))
		carts = (
			[make_item("A", 2), make_item("B", 3), make_item("C", 1)],
			[make_item("D", 1), make_item("MISSING", 4)],
			[make_item("A", -2), make_item("A", 0.3333)],
			[],
		)
		for items in carts:
			with self.subTest(items=[(i.item_code, i.qty) for i in items]):
				quotation = make_quotation(items)
				with patch.object(shipping.frappe, "get_all", return_value=rows):
					self.assertEqual(get_cart_weight(quotation), weight_before_the_change(quotation, rows))

	def test_the_unit_weights_are_one_query_with_the_default_for_unknown_items(self):
		rows = item_rows(A=(1.5, "Kg"))
		quotation = make_quotation([make_item("A", 2), make_item("X", 1)])
		with patch.object(shipping.frappe, "get_all", return_value=rows) as get_all:
			unit_weights = get_item_unit_weights(quotation)
		self.assertEqual(get_all.call_count, 1)
		self.assertEqual(unit_weights, {"A": 1.5, "X": DEFAULT_ITEM_WEIGHT_KG})

	def test_an_empty_cart_has_no_weights_and_no_query(self):
		with patch.object(shipping.frappe, "get_all") as get_all:
			self.assertEqual(get_item_unit_weights(make_quotation([])), {})
			self.assertEqual(get_cart_weight(make_quotation([])), 0.0)
		get_all.assert_not_called()


def parcels_before_the_change(quotation, rows):
	"""get_cart_parcels exactly as it was before cart_items existed."""
	return [
		{
			**DEFAULT_PARCEL_DIMENSIONS,
			"weight": weight_before_the_change(quotation, rows) or DEFAULT_ITEM_WEIGHT_KG,
			"count": 1,
		}
	]


class TestCartParcels(IntegrationTestCase):
	def test_get_cart_parcels_output_is_identical_to_before(self):
		rows = item_rows(A=(1.5, "Kg"), C=(500, "Gram"))
		carts = (
			[make_item("A", 2, 100.0), make_item("X", 1, 50.0)],
			[make_item("C", 3)],
			[],
		)
		for items in carts:
			with self.subTest(items=[(i.item_code, i.qty) for i in items]):
				quotation = make_quotation(items)
				with patch.object(shipping.frappe, "get_all", return_value=rows):
					self.assertEqual(get_cart_parcels(quotation), parcels_before_the_change(quotation, rows))

	def test_the_parcel_has_no_items_key(self):
		with patch.object(shipping.frappe, "get_all", return_value=[]):
			parcel = get_cart_parcels(make_quotation([make_item("A", 1)]))[0]
		self.assertEqual(set(parcel), {"length", "width", "height", "weight", "count"})

	def test_an_empty_cart_still_gets_the_default_weight(self):
		self.assertEqual(get_cart_parcels(make_quotation([]))[0]["weight"], DEFAULT_ITEM_WEIGHT_KG)


class TestQuoteOptions(IntegrationTestCase):
	def run_quote_options(self, quotation, rows=()):
		with (
			patch(
				"bwh_shipping.bwh_shipping.pricing.quote_services", return_value=["quoted"]
			) as quote_services,
			patch("bwh_shipping.bwh_shipping.utils.get_address_payload", return_value=dict(ADDRESS_PAYLOAD)),
			patch.object(shipping.frappe, "get_all", return_value=list(rows)),
			patch.object(shipping, "get_cart_context", return_value={"weight": 1}),
		):
			self.assertEqual(quote_options(quotation), ["quoted"])
		return quote_services.call_args

	def test_the_destination_adds_address_name_company_and_cart_items(self):
		rows = item_rows(A=(1.5, "Kg"))
		quotation = make_quotation([make_item("A", 2, 100.0), make_item("X", 1, 50.0)])
		call = self.run_quote_options(quotation, rows)
		origin, destination, parcels, cart = call.args
		self.assertIsNone(origin)
		self.assertEqual(
			destination,
			{
				**ADDRESS_PAYLOAD,
				"address_name": "ADDR-1",
				"company": "Some Company",
				"cart_items": [
					{"sku": "A", "description": "A name", "quantity": 2.0, "rate": 100.0, "weight": 1.5},
					{"sku": "X", "description": "X name", "quantity": 1.0, "rate": 50.0, "weight": 0.5},
				],
			},
		)
		self.assertEqual(parcels, parcels_before_the_change(quotation, rows))
		self.assertEqual(cart, {"weight": 1})
		self.assertEqual(call.kwargs, {"cod": False})

	def test_the_cart_item_keys_are_the_ones_bwh_fulfilment_builds_plus_weight(self):
		destination = self.run_quote_options(make_quotation([make_item("A", 1)])).args[1]
		self.assertEqual(
			set(destination["cart_items"][0]), {"sku", "description", "quantity", "rate", "weight"}
		)


SERVICE = {
	"name": "Standard",
	"title": "Standard",
	"description": "",
	"provider": "Fake Carrier",
	"service_code": "9",
	"carrier": "Fake",
	"markup_percent": 10,
	"handling_fee": 5,
	"backup_charge": 99,
	"shipping_rule": None,
}


class FakeShiprocket:
	"""Prices like Shiprocket's get_rates: on the two pincodes and the billable weight, nothing else."""

	def get_rates(self, origin, destination, parcels, cod=False, declared_value=0.0):
		from bwh_shipping.units import billable_weight

		if not (origin.get("pincode") and destination.get("pincode")):
			return []
		return [fake_rate(40.0 + 25.0 * billable_weight(parcels))]


class FakeAfterShip:
	"""Prices from what AfterShip's own build_parcel puts on the wire, which reads the parcel's items."""

	currency = "USD"

	def get_rates(self, origin, destination, parcels, cod=False, declared_value=0.0):
		from bwh_shipping.bwh_shipping.doctype.aftership_shipping_settings.aftership_shipping_settings import (
			AfterShipShippingSettings,
		)

		built = [AfterShipShippingSettings.build_parcel(self, parcel, declared_value) for parcel in parcels]
		self.sent = built
		weight = sum(
			item["weight"]["value"] * item["quantity"] for parcel in built for item in parcel["items"]
		)
		return [fake_rate(10.0 + 7.0 * weight)]

	def build_item(self, item, declared_value):
		from bwh_shipping.bwh_shipping.doctype.aftership_shipping_settings.aftership_shipping_settings import (
			AfterShipShippingSettings,
		)

		return AfterShipShippingSettings.build_item(self, item, declared_value)

	def build_default_item(self, declared_value):
		from bwh_shipping.bwh_shipping.doctype.aftership_shipping_settings.aftership_shipping_settings import (
			AfterShipShippingSettings,
		)

		return AfterShipShippingSettings.build_default_item(self, declared_value)


def fake_rate(amount):
	return {
		"service_code": "9",
		"service_name": "Fake Courier",
		"carrier": "Fake",
		"amount": amount,
		"currency": "INR",
		"transit_days": 2,
		"cod_available": False,
	}


class TestCarrierPricingIsUnchanged(IntegrationTestCase):
	def quote(self, carrier, destination, parcels):
		from bwh_shipping.bwh_shipping.pricing import quote_services

		cart = {
			"currency": "INR",
			"conversion_rate": 1,
			"base_net_total": 500,
			"weight": 2,
			"declared_value": 500,
		}
		with (
			patch("bwh_shipping.bwh_shipping.pricing.get_enabled_services", return_value=[dict(SERVICE)]),
			patch("bwh_shipping.bwh_shipping.pricing.get_default_origin", return_value={"pincode": "110001"}),
			patch("bwh_shipping.bwh_shipping.pricing.get_provider_controller", return_value=carrier),
		):
			return quote_services(None, destination, parcels, cart)

	def payloads(self):
		rows = item_rows(A=(1.5, "Kg"))
		quotation = make_quotation([make_item("A", 2), make_item("X", 1)])
		with patch.object(shipping.frappe, "get_all", return_value=rows):
			new_parcels = get_cart_parcels(quotation)
		old_parcels = parcels_before_the_change(quotation, rows)
		old_destination = dict(ADDRESS_PAYLOAD)
		new_destination = {
			**ADDRESS_PAYLOAD,
			"address_name": "ADDR-1",
			"company": "Some Company",
			"cart_items": [{"sku": "A", "description": "A", "quantity": 2.0, "rate": 1.0, "weight": 1.5}],
		}
		return old_destination, old_parcels, new_destination, new_parcels

	def test_shiprocket_amounts_are_identical(self):
		old_destination, old_parcels, new_destination, new_parcels = self.payloads()
		before = self.quote(FakeShiprocket(), old_destination, old_parcels)
		after = self.quote(FakeShiprocket(), new_destination, new_parcels)
		self.assertEqual(before, after)
		self.assertEqual(after[0]["amount"], round((40 + 25 * 3.5) * 1.1 + 5, 2))
		self.assertTrue(after[0]["is_live_rate"])

	def test_aftership_amounts_and_wire_parcels_are_identical(self):
		old_destination, old_parcels, new_destination, new_parcels = self.payloads()
		old_carrier, new_carrier = FakeAfterShip(), FakeAfterShip()
		before = self.quote(old_carrier, old_destination, old_parcels)
		after = self.quote(new_carrier, new_destination, new_parcels)
		self.assertEqual(before, after)
		self.assertEqual(old_carrier.sent, new_carrier.sent)
		# No items on the parcel, so AfterShip still declares its default item.
		self.assertEqual(new_carrier.sent[0]["items"][0]["sku"], "GOODS")
