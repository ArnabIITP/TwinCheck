import json
import re
import tempfile
import unittest
from pathlib import Path

from twincheck.schema import generate_schema_inputs, load_json_schema


class JsonSchemaGeneratorTests(unittest.TestCase):
    def test_generation_is_seeded_unique_and_respects_common_constraints(self):
        schema = {
            "title": "CreateOrder",
            "type": "object",
            "required": ["quantity", "currency"],
            "properties": {
                "quantity": {"type": "integer", "minimum": 1, "maximum": 20},
                "currency": {"type": "string", "enum": ["USD", "EUR"]},
                "labels": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 3, "uniqueItems": True},
                "code": {"type": "string", "pattern": "^[A-Z0-9]{6,10}$", "minLength": 6, "maxLength": 10},
            },
            "additionalProperties": False,
        }
        first = generate_schema_inputs(schema, count=15, seed=19)
        second = generate_schema_inputs(schema, count=15, seed=19)
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))
        for encoded in first:
            value = json.loads(encoded)
            self.assertTrue(1 <= value["quantity"] <= 20)
            self.assertIn(value["currency"], {"USD", "EUR"})
            if "labels" in value:
                self.assertLessEqual(len(value["labels"]), 3)
                self.assertEqual(len(value["labels"]), len(set(value["labels"])))
            if "code" in value:
                self.assertRegex(value["code"], re.compile(r"^[A-Z0-9]{6,10}$"))
            self.assertNotIn("extra_0", value)

    def test_local_ref_and_exclusive_number_bounds(self):
        schema = {
            "$defs": {"value": {"type": "integer", "exclusiveMinimum": 2, "exclusiveMaximum": 5}},
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"$ref": "#/$defs/value"}},
        }
        values = [json.loads(item)["value"] for item in generate_schema_inputs(schema, count=10, seed=4)]
        self.assertTrue(values)
        self.assertTrue(all(value in {3, 4} for value in values))

    def test_finite_schema_domain_returns_available_unique_cases(self):
        values = generate_schema_inputs({"const": {"only": True}}, count=50, seed=1)
        self.assertEqual(values, ['{"only":true}'])

    def test_remote_refs_and_unsupported_constraints_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "remote JSON Schema reference"):
            generate_schema_inputs({"$ref": "https://example.com/schema.json"}, count=1)
        with self.assertRaisesRegex(ValueError, "unsupported JSON Schema constraint"):
            generate_schema_inputs({"allOf": [{"type": "string"}]}, count=1)

    def test_array_false_items_and_fractional_multiple_of(self):
        values = generate_schema_inputs({"type": "array", "prefixItems": [{"type": "string"}], "items": False, "minItems": 1, "maxItems": 1}, count=1, seed=3)
        self.assertEqual(len(json.loads(values[0])), 1)
        multiples = generate_schema_inputs({"type": "integer", "minimum": 100000, "maximum": 100100, "multipleOf": 1.5}, count=5, seed=2)
        self.assertTrue(all(int(json.loads(value)) % 3 == 0 for value in multiples))

    def test_json_boolean_is_not_numeric_for_const_or_enum(self):
        with self.assertRaisesRegex(ValueError, "did not yield any JSON samples"):
            generate_schema_inputs({"const": True, "enum": [1]}, count=1, seed=0)

    def test_schema_loader_hashes_exact_source_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "schema.json"
            path.write_text('{"title":"T","type":"string"}\n', encoding="utf-8")
            document = load_json_schema(path)
            self.assertEqual(document.title, "T")
            self.assertEqual(len(document.sha256), 64)


if __name__ == "__main__":
    unittest.main()
