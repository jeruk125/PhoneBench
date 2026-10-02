import os
import tempfile
import unittest
import zipfile
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from phonebench import create_app
from phonebench.extensions import db
from phonebench.money import format_money, parse_money
from phonebench.models import (
    AppSetting, Customer, Device, Diagnosis, InventoryItem, InventoryMovement, Invoice, ManualGuide,
    Payment, Repair, RepairAttempt, Solution, Transaction, User,
)
from phonebench.security import new_portal_token
from phonebench.services.adb import ADBUnavailable, scan_devices
from phonebench.services.ai import AIProviderError, OpenAICompatibleProvider
from phonebench.services.backup import create_database_backup, restore_attachments, restore_database
from phonebench.services.whatsapp import CloudAPIProvider, WhatsAppProviderError


class PhoneBenchTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = os.path.join(self.temporary.name, "test.sqlite")
        self.app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret-not-for-deployment",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + self.database.replace("\\", "/"),
            "UPLOAD_FOLDER": os.path.join(self.temporary.name, "uploads"),
            "BACKUP_FOLDER": os.path.join(self.temporary.name, "backups"),
            "AI_BASE_URL": "",
            "AI_API_KEY": "",
            "AI_MODEL": "",
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.owner = User(username="owner", display_name="Test Owner", role="OWNER")
        self.owner.set_password("test-password-with-12")
        self.technician = User(username="tech", display_name="Assigned Tech", role="TECHNICIAN")
        self.technician.set_password("technician-password-12")
        self.other_technician = User(username="other", display_name="Other Tech", role="TECHNICIAN")
        self.other_technician.set_password("another-password-12")
        db.session.add_all([self.owner, self.technician, self.other_technician])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.temporary.cleanup()

    def login(self, username="owner", password="test-password-with-12"):
        return self.client.post("/login", data={"username": username, "password": password}, follow_redirects=True)

    def make_repair(self, assigned=None):
        customer = Customer(name="Test Customer", phone="+620000000099", email="test@example.invalid")
        device = Device(owner=customer, brand="Samsung", model="SM-A525F", device_code="SM-A525F")
        db.session.add_all([customer, device])
        db.session.flush()
        repair = Repair(
            ticket_number=f"SRV-2026-{Repair.query.count() + 1:05d}",
            customer=customer, device=device, assigned_technician_id=assigned,
            customer_problem="Bootloop after update", private_notes="NEVER SHOW THIS CUSTOMER SECRET",
            status="RECEIVED",
        )
        db.session.add(repair)
        db.session.commit()
        return customer, device, repair

    def test_language_switch_is_available_before_and_after_login(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-language="id"', response.data)

        self.login()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-language="en"', response.data)
        script_response = self.client.get("/static/app.js")
        self.assertIn(b"phonebench-language", script_response.data)
        script_response.close()

    def test_currency_setting_and_money_format(self):
        self.assertEqual(format_money(100000, "IDR"), "Rp.100.000")
        self.assertEqual(format_money("100000.50", "IDR"), "Rp.100.000,50")
        self.assertEqual(format_money(100000, "USD"), "$100,000.00")
        self.assertEqual(parse_money("100.000,50", "IDR"), Decimal("100000.50"))
        self.assertEqual(parse_money("100,000.50", "USD"), Decimal("100000.50"))

        self.login()
        response = self.client.get("/settings")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Indonesian rupiah (IDR)', response.data)
        response = self.client.post("/settings", data={
            "action": "set_currency",
            "currency": "USD",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AppSetting.query.filter_by(key="currency").one().value, "USD")
        response = self.client.get("/settings")
        self.assertIn(b'data-currency="USD"', response.data)
        response = self.client.post("/inventory", data={
            "action": "create",
            "name": "Test part",
            "unit_cost": "1,234.50",
            "selling_price": "2,000.00",
        })
        self.assertEqual(response.status_code, 302)
        item = InventoryItem.query.filter_by(name="Test part").one()
        self.assertEqual(item.unit_cost, Decimal("1234.50"))
        self.assertEqual(item.selling_price, Decimal("2000.00"))

    def test_manual_guide_is_separate_and_recommended_on_repair(self):
        _, _, repair = self.make_repair()
        repair.customer_problem = "Odin software is not installed"
        db.session.commit()
        self.login()

        response = self.client.post("/knowledge/manual", data={
            "category": "SOFTWARE",
            "title": "Install Odin software",
            "tool": "Odin",
            "software": "Odin",
            "problem": "Odin is not installed",
            "content": "Install the required software before troubleshooting.",
            "procedure": "Download the installer from the official source.",
            "reference_url": "https://example.invalid/odin",
        })
        self.assertEqual(response.status_code, 302)
        guide = ManualGuide.query.one()
        self.assertEqual(Solution.query.count(), 0)
        self.assertEqual(repair.status, "RECEIVED")

        response = self.client.get("/knowledge?q=Odin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"MANUAL GUIDE", response.data)
        self.assertIn(b"Install Odin software", response.data)
        self.assertNotIn(b"1 successes", response.data)

        response = self.client.get(f"/repairs/{repair.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Install Odin software", response.data)
        self.assertIn(b"Historical repair cases", response.data)

        response = self.client.post("/knowledge/manual", data={
            "category": "GUIDE",
            "title": "Unsafe reference",
            "content": "A guide with a non-http URL",
            "reference_url": "javascript:alert(1)",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ManualGuide.query.count(), 1)

    def test_authentication_customer_crud_and_workflow_to_knowledge(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.login()
        response = self.client.post("/customers/new", data={"name": "Repair Customer", "phone": "12345", "email": "c@example.invalid"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        customer = Customer.query.filter_by(name="Repair Customer").one()
        response = self.client.post(f"/customers/{customer.id}/edit", data={"name": "Updated Customer", "phone": "67890"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(customer.name, "Updated Customer")
        response = self.client.post("/devices/new", data={"brand": "Samsung", "model": "SM-A525F", "device_code": "SM-A525F", "identifier_type": "Serial", "identifier": "SERIAL-1234"})
        self.assertEqual(response.status_code, 302)
        device = Device.query.one()
        response = self.client.post("/repairs/new", data={
            "customer_id": customer.id, "device_id": device.id,
            "customer_problem": "Bootloop after update", "power_state": "Bootloop",
            "security_lock_state": ["FRP"], "estimated_cost": "100",
        })
        self.assertEqual(response.status_code, 302)
        repair = Repair.query.one()
        self.assertRegex(repair.ticket_number, r"^SRV-\d{4}-\d{5}$")
        self.assertEqual(repair.security_lock_state, "FRP")
        self.client.post(f"/repairs/{repair.id}/diagnosis", data={
            "problem_category": "Bootloop", "diagnosis": "Software corruption likely", "confidence": 75,
        })
        self.client.post(f"/repairs/{repair.id}/attempts", data={
            "tool": "Odin", "tool_version": "3.14.4", "method": "Flash full firmware",
            "result": "FAILED", "error_message": "SHA256 is invalid",
        })
        self.client.post(f"/repairs/{repair.id}/attempts", data={
            "tool": "Odin", "tool_version": "3.14.4", "method": "Flash complete firmware",
            "firmware": "A525FXXU", "result": "SUCCESS", "notes": "Complete firmware resolved the bootloop.",
        })
        attempt = RepairAttempt.query.filter_by(result="SUCCESS").one()
        self.client.post(f"/repairs/{repair.id}/attempts/{attempt.id}/solution", data={"title": "SM-A525F bootloop recovery"})
        solution = Solution.query.one()
        self.assertFalse(solution.verified)
        self.client.post(f"/knowledge/{solution.id}/verify", data={"verified": "true"})
        self.assertTrue(solution.verified)
        response = self.client.get("/search?q=SHA256%20is%20invalid")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SHA256 is invalid", response.data)
        response = self.client.get(f"/repairs/{repair.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SM-A525F bootloop recovery", response.data)

    def test_inventory_invoice_payment_accounting_and_pdf(self):
        self.login()
        customer, device, repair = self.make_repair()
        item = InventoryItem(name="USB flex", sku="USB-FLEX", quantity=2, minimum_quantity=1, selling_price=Decimal("25.00"))
        db.session.add(item)
        db.session.commit()
        self.client.post(f"/repairs/{repair.id}/parts", data={"item_id": item.id, "quantity": "1"})
        self.assertEqual(item.quantity, 1)
        self.assertEqual(InventoryMovement.query.filter_by(repair_id=repair.id).one().quantity, -1)
        response = self.client.post(f"/repairs/{repair.id}/invoices", data={"labor": "100.00", "service_description": "Diagnostic service", "service_amount": "10", "discount": "0", "tax": "0"})
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.query.one()
        self.assertEqual(invoice.total, Decimal("135.00"))
        self.assertEqual(len(invoice.items), 3)
        self.client.post(f"/invoices/{invoice.id}/issue")
        for amount in ["50", "85"]:
            response = self.client.post(f"/invoices/{invoice.id}/payments", data={"amount": amount, "method": "Cash", "kind": "PAYMENT"})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(invoice.status, "PAID")
        self.assertEqual(invoice.balance, Decimal("0"))
        self.assertEqual(Payment.query.count(), 2)
        self.assertEqual(Transaction.query.filter(Transaction.reference.like("PAYMENT:%")).count(), 2)
        response = self.client.get(f"/invoices/{invoice.id}/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.client.post(f"/invoices/{invoice.id}/payments", data={"amount": "10", "method": "Cash", "kind": "REFUND"})
        self.assertEqual(Transaction.query.filter_by(type="EXPENSE").count(), 1)

    def test_role_scoping_and_secure_customer_portal(self):
        _, _, repair = self.make_repair(assigned=self.technician.id)
        other_customer, other_device, other_repair = self.make_repair(assigned=self.other_technician.id)
        self.login("tech", "technician-password-12")
        self.assertEqual(self.client.get(f"/repairs/{repair.id}").status_code, 200)
        self.assertEqual(self.client.get(f"/repairs/{other_repair.id}").status_code, 403)
        self.assertEqual(self.client.post("/repairs/new").status_code, 403)
        self.assertNotIn(b"Receive a device", self.client.get("/repairs").data)
        self.assertEqual(self.client.get("/accounting").status_code, 403)
        self.assertEqual(self.client.get(f"/customers/{repair.customer_id}").status_code, 403)
        token, digest = new_portal_token()
        from phonebench.models import PortalToken
        db.session.add(PortalToken(token_hash=digest, repair_id=repair.id))
        db.session.commit()
        portal_response = self.client.get(f"/customer/{token}")
        self.assertEqual(portal_response.status_code, 200)
        self.assertNotIn(b"NEVER SHOW THIS CUSTOMER SECRET", portal_response.data)
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
        api_response = self.client.get(f"/api/v1/repairs/{repair.id}")
        self.assertEqual(api_response.status_code, 200)
        self.assertNotIn(b"NEVER SHOW THIS CUSTOMER SECRET", api_response.data)

    def test_search_ai_and_provider_configuration_errors(self):
        _, _, repair = self.make_repair()
        attempt = RepairAttempt(repair_id=repair.id, attempt_number=1, result="FAILED", error_message="SHA256 is invalid")
        db.session.add(attempt)
        db.session.commit()
        self.login()
        response = self.client.get("/search?q=SHA256")
        self.assertIn(b"SHA256 is invalid", response.data)
        response = self.client.post("/ai", data={"question": "What have I done for SM-A525F bootloop?"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"DATABASE EVIDENCE", response.data)
        with self.assertRaises(AIProviderError):
            OpenAICompatibleProvider("", "", "").generate("question", "evidence")
        with self.assertRaises(WhatsAppProviderError):
            CloudAPIProvider("", "").send_message("000", "message")

    def test_backup_restore_and_attachment_archive_validation(self):
        self.login()
        customer, _, _ = self.make_repair()
        customer_name = customer.name
        backup = create_database_backup()
        self.assertTrue(os.path.isfile(os.path.join(self.app.config["BACKUP_FOLDER"], backup["database"])))
        with open(os.path.join(self.app.config["BACKUP_FOLDER"], backup["database"]), "rb") as file_handle:
            from werkzeug.datastructures import FileStorage
            upload = FileStorage(stream=BytesIO(file_handle.read()), filename=backup["database"])
        restore_database(upload)
        self.assertEqual(Customer.query.filter_by(name=customer_name).count(), 1)
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("a" * 40 + ".txt", "test attachment")
        archive_bytes.seek(0)
        from werkzeug.datastructures import FileStorage
        restore_attachments(FileStorage(stream=archive_bytes, filename="attachments.zip"))
        self.assertTrue(os.path.isfile(os.path.join(self.app.config["UPLOAD_FOLDER"], "a" * 40 + ".txt")))
        bad = BytesIO()
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../outside.txt", "unsafe")
        bad.seek(0)
        with self.assertRaises(ValueError):
            restore_attachments(FileStorage(stream=bad, filename="bad.zip"))

    def test_adb_unavailable_and_json_api(self):
        with patch("phonebench.services.adb.shutil.which", return_value=None):
            with self.assertRaises(ADBUnavailable):
                scan_devices()
        self.login()
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.json["status"], "ok")
        self.assertEqual(self.client.get("/api/v1/knowledge").status_code, 400)

    def test_demo_seed_and_all_staff_pages_render(self):
        from phonebench.seed import seed_demo_data
        from phonebench.models import Attachment, PortalToken
        seed_demo_data()
        self.login()
        first = Repair.query.order_by(Repair.id).first()
        invoice = Invoice.query.first()
        customer = Customer.query.first()
        device = Device.query.first()
        token, digest = new_portal_token()
        db.session.add(PortalToken(token_hash=digest, repair_id=first.id))
        db.session.commit()
        paths = [
            "/", "/customers", f"/customers/{customer.id}", "/devices",
            f"/devices/{device.id}", "/repairs", f"/repairs/{first.id}",
            "/knowledge", "/inventory", "/invoices", f"/invoices/{invoice.id}",
            "/accounting", "/ai", "/scanner", "/reports", "/settings", "/audit",
            "/backups", "/users", "/search?q=SM-A525F", f"/customer/{token}",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:500])
        response = self.client.post("/settings", data={"template_repair_received": "Hello {{unknown}}"})
        self.assertEqual(response.status_code, 200)
        from phonebench.models import NotificationTemplate
        self.assertEqual(NotificationTemplate.query.count(), 0)
        self.assertGreaterEqual(RepairAttempt.query.count(), 10)
        self.assertGreaterEqual(Solution.query.count(), 5)
        self.assertEqual(Customer.query.filter(Customer.name.like("Demo Customer %")).count(), 3)


if __name__ == "__main__":
    unittest.main()
