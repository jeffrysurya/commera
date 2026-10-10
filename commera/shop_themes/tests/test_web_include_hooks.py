# Copyright (c) 2026, ivend and Contributors
# commera_web_include_js / commera_web_include_css: rendered by the theme base templates, and invisible
# (byte-identical <head>) when no app declares them.

import re
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.jinja import get_jenv

from commera.shop_themes.doctype.shop_theme.shop_theme import clear_render_theme_context, get_theme_context
from commera.shop_themes.theme_resolver import build_base_context, get_theme_environment

BASE_TEMPLATE = "components/base.html"
# The two loops the hooks add to a base template; removing them yields the template as it was before.
HOOK_LOOP = re.compile(r"\{% for \w+ in commera_web_include_(?:css|js) or \[\] %\}.*?\{% endfor %\}", re.DOTALL)


class IntegrationTestWebIncludeHooks(IntegrationTestCase):
	THEMES = ("Shop Base Theme", "Shop Default Theme")

	def setUp(self):
		self.original_active_theme = frappe.get_single("Shop Theme Settings").active_theme

	def tearDown(self):
		frappe.db.set_single_value("Shop Theme Settings", "active_theme", self.original_active_theme)
		frappe.clear_cache()
		clear_render_theme_context()

	def activate(self, theme_name):
		frappe.db.set_single_value("Shop Theme Settings", "active_theme", theme_name)
		frappe.clear_cache()
		clear_render_theme_context()

	def declare_hooks(self, js=None, css=None):
		"""Pretend exactly these apps' hook values exist, whatever is installed on the test site."""
		declared = {"commera_web_include_js": js or [], "commera_web_include_css": css or []}
		real_get_hooks = frappe.get_hooks

		def get_hooks(hook=None, *args, **kwargs):
			if hook in declared:
				return declared[hook]
			return real_get_hooks(hook, *args, **kwargs)

		return patch("frappe.get_hooks", side_effect=get_hooks)

	def render_head(self, theme_name, context, without_hook_loops=False):
		self.activate(theme_name)
		theme_env = get_theme_environment(get_jenv(), get_theme_context(theme_name)["dirs"])
		if without_hook_loops:
			source = theme_env.loader.get_source(theme_env, BASE_TEMPLATE)[0]
			stripped, loops_removed = HOOK_LOOP.subn("", source)
			self.assertEqual(loops_removed, 2, f"{theme_name}: expected the css and js hook loops in {BASE_TEMPLATE}")
			template = theme_env.from_string(stripped)
		else:
			template = theme_env.get_template(BASE_TEMPLATE)
		html = template.render(context)
		return html[html.index("<head>") : html.index("</head>")]

	def test_base_context_carries_the_declared_hooks(self):
		with self.declare_hooks(js=["/assets/probe/js/probe.js"], css=["/assets/probe/css/probe.css"]):
			context = build_base_context(None)
		self.assertEqual(context.commera_web_include_js, ["/assets/probe/js/probe.js"])
		self.assertEqual(context.commera_web_include_css, ["/assets/probe/css/probe.css"])

	def test_base_context_hooks_are_empty_lists_when_no_app_declares_them(self):
		with self.declare_hooks():
			context = build_base_context(None)
		self.assertEqual(context.commera_web_include_js, [])
		self.assertEqual(context.commera_web_include_css, [])

	def test_head_is_byte_identical_when_no_app_declares_the_hooks(self):
		# AC-27: both bundled base templates, compared with the same template minus the two hook loops.
		with self.declare_hooks():
			context = build_base_context(None)
		for theme_name in self.THEMES:
			with self.subTest(theme=theme_name):
				self.assertEqual(
					self.render_head(theme_name, context),
					self.render_head(theme_name, context, without_hook_loops=True),
				)

	def test_head_is_byte_identical_when_the_context_has_no_hook_keys(self):
		# Pages not built by build_base_context (plain www templates) never set the keys.
		with self.declare_hooks():
			context = build_base_context(None)
		for key in ("commera_web_include_js", "commera_web_include_css"):
			del context[key]
		for theme_name in self.THEMES:
			with self.subTest(theme=theme_name):
				self.assertEqual(
					self.render_head(theme_name, context),
					self.render_head(theme_name, context, without_hook_loops=True),
				)

	def test_declared_assets_render_the_style_after_theme_css_and_the_script_before_alpine(self):
		with self.declare_hooks(js=["/assets/probe/js/probe.js"], css=["/assets/probe/css/probe.css"]):
			context = build_base_context(None)
		for theme_name in self.THEMES:
			with self.subTest(theme=theme_name):
				head = self.render_head(theme_name, context)
				style = head.index('href="/assets/probe/css/probe.css"')
				script = head.index('src="/assets/probe/js/probe.js"')
				alpine_core = head.index("alpinejs/core.js")
				self.assertLess(style, head.index("persist.js"))
				self.assertLess(script, alpine_core)
				self.assertGreater(script, head.index("persist.js"))
