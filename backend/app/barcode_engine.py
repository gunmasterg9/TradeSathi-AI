"""
TradeSathi AI — Phase 8: Enterprise Barcode & QR Code Identification Engine
Generates standard 2D QR codes and 1D Code128 barcodes, builds print-ready thermal labels,
resolves physical scans against authoritative ERP entities, and powers the Operational Portal.
"""

import base64
import hashlib
import io
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import qrcode
import qrcode.image.svg
import barcode
from barcode import Code128
from barcode.writer import SVGWriter, ImageWriter

from fastapi import HTTPException

from app.db import (
    get_connection,
    get_or_create_entity_barcode_record,
    get_barcode_record_by_value,
    get_barcode_record_by_id,
    list_entity_barcodes_record,
    deactivate_entity_barcode_record,
    get_shipment_by_id,
)
from app.master_data import verify_role_permission, record_erp_audit_log
from app.storage import get_storage_dir

logger = logging.getLogger(__name__)

PORTAL_STATUTORY_DISCLAIMER = (
    "TradeSathi AI Operational Portal — Internal ERP scan and verification record. "
    "Does not constitute official customs clearance, statutory e-invoicing, or carrier bill of lading."
)

EXPORT_COMPLIANCE_DISCLAIMER = (
    "TradeSathi AI Document Readiness Evaluation is an internal operational check and does not "
    "constitute official customs clearance, single-window approval, or regulatory certification."
)


# =========================================================================
# 1. Barcode & QR Rendering Utilities
# =========================================================================

def generate_qr_svg(payload: str) -> str:
    """Generate high-contrast vector SVG representation of a QR code."""
    factory = qrcode.image.svg.SvgPathImage
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
        image_factory=factory,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image()
    stream = io.BytesIO()
    img.save(stream)
    return stream.getvalue().decode("utf-8")


def generate_qr_png_base64(payload: str) -> str:
    """Generate base64-encoded PNG data URL of a QR code."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    stream = io.BytesIO()
    img.save(stream, format="PNG")
    b64 = base64.b64encode(stream.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def generate_code128_svg(code_text: str) -> str:
    """Generate vector SVG representation of a Code 128 1D linear barcode."""
    clean_text = re.sub(r"[^\w\-\.]", "_", code_text.strip())[:40]
    if not clean_text:
        clean_text = "EMPTY"
    try:
        writer = SVGWriter()
        c128 = Code128(clean_text, writer=writer)
        stream = io.BytesIO()
        c128.write(stream, options={"write_text": True, "module_height": 12.0, "font_size": 9})
        return stream.getvalue().decode("utf-8")
    except Exception as exc:
        logger.warning("Code128 generation fallback for '%s': %s", code_text, exc)
        return f'<svg width="200" height="40"><text x="10" y="25" font-family="monospace">{clean_text}</text></svg>'


# =========================================================================
# 2. Print-Ready Thermal Label Generation
# =========================================================================

def build_label_html(
    entity_type: str,
    entity_reference: str,
    qr_payload: str,
    metadata: dict[str, Any],
    label_size: str = "4x2",
) -> str:
    """
    Constructs a standalone, printer-ready HTML document formatted for
    standard 4"x2" (100mm x 50mm) or 2"x1" thermal label printers.
    """
    qr_svg = generate_qr_svg(qr_payload)
    barcode_svg = generate_code128_svg(entity_reference)

    import html as html_lib

    title = html_lib.escape(str(metadata.get("title") or entity_reference))
    subtitle = html_lib.escape(str(metadata.get("subtitle") or entity_type.replace("_", " ").upper()))
    safe_ref = html_lib.escape(str(entity_reference))
    extra_lines = metadata.get("extra_lines", [])

    extra_html = "".join(
        f'<div class="meta-line"><span>{html_lib.escape(str(k))}:</span> <strong>{html_lib.escape(str(v))}</strong></div>'
        for k, v in extra_lines
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TradeSathi Label - {safe_ref}</title>
<style>
  @page {{
    size: { "100mm 50mm" if label_size == "4x2" else "50mm 25mm" };
    margin: 0;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #111827;
    background: #ffffff;
    width: { "100mm" if label_size == "4x2" else "50mm" };
    height: { "50mm" if label_size == "4x2" else "25mm" };
    padding: 3mm 4mm;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    overflow: hidden;
  }}
  .label-header {{
    border-bottom: 1.5px solid #111827;
    padding-bottom: 1.5mm;
    margin-bottom: 1.5mm;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .brand {{
    font-weight: 800;
    font-size: 8pt;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }}
  .badge {{
    font-size: 6pt;
    background: #111827;
    color: #ffffff;
    padding: 0.5mm 1.5mm;
    border-radius: 1mm;
    font-weight: 700;
    text-transform: uppercase;
  }}
  .label-body {{
    display: flex;
    align-items: center;
    gap: 3mm;
    flex: 1;
  }}
  .qr-box {{
    width: 22mm;
    height: 22mm;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .qr-box svg {{
    width: 100%;
    height: 100%;
  }}
  .info-box {{
    flex: 1;
    overflow: hidden;
  }}
  .entity-title {{
    font-size: 9pt;
    font-weight: 800;
    line-height: 1.1;
    margin-bottom: 1mm;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .meta-line {{
    font-size: 6.5pt;
    line-height: 1.25;
    color: #374151;
  }}
  .meta-line strong {{
    color: #111827;
  }}
  .barcode-footer {{
    border-top: 1px dashed #9ca3af;
    padding-top: 1.5mm;
    margin-top: 1mm;
    display: flex;
    flex-direction: column;
    align-items: center;
  }}
  .barcode-svg {{
    max-height: 10mm;
    width: 100%;
    display: flex;
    justify-content: center;
  }}
  .barcode-svg svg {{
    max-height: 10mm;
    max-width: 90mm;
  }}
  .disclaimer {{
    font-size: 4.5pt;
    color: #6b7280;
    text-align: center;
    margin-top: 0.5mm;
  }}
  @media print {{
    body {{
      width: { "100mm" if label_size == "4x2" else "50mm" };
      height: { "50mm" if label_size == "4x2" else "25mm" };
    }}
  }}
</style>
</head>
<body onload="window.print()">
  <div class="label-header">
    <div class="brand">TradeSathi AI Logistics</div>
    <div class="badge">{subtitle}</div>
  </div>
  <div class="label-body">
    <div class="qr-box">
      {qr_svg}
    </div>
    <div class="info-box">
      <div class="entity-title">{title}</div>
      <div class="meta-line"><span>REF:</span> <strong>{safe_ref}</strong></div>
      {extra_html}
    </div>
  </div>
  <div class="barcode-footer">
    <div class="barcode-svg">
      {barcode_svg}
    </div>
    <div class="disclaimer">Internal verification label (v1) • Not customs clearance</div>
  </div>
</body>
</html>
"""


def save_label_artifact(
    barcode_id: str,
    label_html: str,
    entity_reference: str,
) -> str:
    """Save printable label HTML inside configured storage directory."""
    base_dir = get_storage_dir()
    labels_dir = base_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    safe_ref = re.sub(r"[^\w\-\.]", "_", entity_reference)[:30]
    filename = f"{barcode_id}_{safe_ref}.html"
    target_path = labels_dir / filename
    target_path.write_text(label_html, encoding="utf-8")
    return f"labels/{filename}"


# =========================================================================
# 3. Label Creation Orchestrator
# =========================================================================

def generate_entity_label(
    entity_type: str,
    entity_id: str,
    label_size: str = "4x2",
    symbology: str = "BOTH",
    created_by: str = "system",
) -> dict[str, Any]:
    """
    Look up entity metadata from authoritative database, register/retrieve barcode record,
    build print-ready label HTML, and persist label artifact safely.
    """
    entity_type_norm = entity_type.strip().lower()

    with get_connection() as conn:
        if entity_type_norm == "product":
            cur = conn.execute("SELECT * FROM products WHERE id = ? OR sku = ?", (entity_id, entity_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Product '{entity_id}' not found")
            entity_id_actual = row["id"]
            ref = row["sku"]
            metadata = {
                "title": row["name"],
                "subtitle": "PRODUCT ITEM",
                "extra_lines": [
                    ("CATEGORY", row["category"] or "General"),
                    ("UOM", row["uom"] or "PCS"),
                    ("REORDER", f"{row['reorder_level']} {row['uom'] or 'PCS'}"),
                ],
            }

        elif entity_type_norm == "location":
            cur = conn.execute(
                """
                SELECT loc.*, wh.code as warehouse_code, wh.name as warehouse_name
                FROM warehouse_locations loc
                JOIN warehouses wh ON wh.id = loc.warehouse_id
                WHERE loc.id = ? OR loc.location_code = ?
                """,
                (entity_id, entity_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Location '{entity_id}' not found")
            entity_id_actual = row["id"]
            ref = f"{row['warehouse_code']}:{row['location_code']}"
            metadata = {
                "title": f"BIN: {row['location_code']}",
                "subtitle": f"WAREHOUSE {row['warehouse_code']}",
                "extra_lines": [
                    ("FACILITY", row["warehouse_name"]),
                    ("ZONE", row["zone"] or "General"),
                    ("RACK/SHELF", f"{row['rack'] or '-'}/{row['shelf'] or '-'}"),
                ],
            }

        elif entity_type_norm == "purchase_order":
            cur = conn.execute("SELECT * FROM purchase_orders WHERE id = ? OR po_number = ?", (entity_id, entity_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Purchase Order '{entity_id}' not found")
            entity_id_actual = row["id"]
            ref = row["po_number"]
            metadata = {
                "title": f"PO: {row['po_number']}",
                "subtitle": "INBOUND PO",
                "extra_lines": [
                    ("VENDOR", row["supplier_name"]),
                    ("STATUS", row["status"].upper()),
                    ("DATE", row["order_date"]),
                ],
            }

        elif entity_type_norm == "goods_receipt":
            cur = conn.execute("SELECT * FROM goods_receipts WHERE id = ? OR gr_number = ?", (entity_id, entity_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Goods Receipt '{entity_id}' not found")
            entity_id_actual = row["id"]
            ref = row["gr_number"]
            metadata = {
                "title": f"GR: {row['gr_number']}",
                "subtitle": "GOODS RECEIPT",
                "extra_lines": [
                    ("PO REF", row["po_number"] or "Direct"),
                    ("STATUS", row["status"].upper()),
                    ("DATE", row["receipt_date"]),
                ],
            }

        elif entity_type_norm == "sales_order":
            cur = conn.execute("SELECT * FROM sales_orders WHERE id = ? OR order_number = ?", (entity_id, entity_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Sales Order '{entity_id}' not found")
            entity_id_actual = row["id"]
            ref = row["order_number"]
            metadata = {
                "title": f"SO: {row['order_number']}",
                "subtitle": "SALES ORDER",
                "extra_lines": [
                    ("CUSTOMER", row["customer_name"]),
                    ("STATUS", row["status"].upper()),
                    ("AMOUNT", f"{row['currency'] or 'INR'} {row['grand_total'] if 'grand_total' in row.keys() else 0.0}"),
                ],
            }

        elif entity_type_norm in ("sales_dispatch", "dispatch_package"):
            cur = conn.execute(
                """
                SELECT d.*, so.order_number as so_number, so.customer_name
                FROM sales_dispatches d
                JOIN sales_orders so ON so.id = d.sales_order_id
                WHERE d.id = ? OR d.dispatch_number = ?
                """,
                (entity_id, entity_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Dispatch '{entity_id}' not found")
            entity_id_actual = row["id"]
            ref = row["dispatch_number"]
            metadata = {
                "title": f"DISPATCH: {row['dispatch_number']}",
                "subtitle": "OUTBOUND CARGO",
                "extra_lines": [
                    ("ORDER", row["so_number"]),
                    ("CUSTOMER", row["customer_name"]),
                    ("PACKAGES", f"{row['packages_count']} PKG | {row['total_weight_kg']} KG"),
                ],
            }

        elif entity_type_norm == "export_shipment":
            cur = conn.execute("SELECT * FROM shipments WHERE id = ? OR reference = ?", (entity_id, entity_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Export Shipment '{entity_id}' not found")
            entity_id_actual = row["id"]
            ref = row["reference"]
            metadata = {
                "title": f"EXPORT: {row['reference']}",
                "subtitle": "EXPORT SHIPMENT",
                "extra_lines": [
                    ("CONSIGNEE", row.get("consignee_name") or row.get("buyer") or "Commercial Buyer"),
                    ("DESTINATION", f"{row.get('destination_port') or 'TBD'}, {row.get('destination_country') or ''}"),
                    ("READINESS", (row.get("readiness_status") or "pending").upper()),
                ],
            }

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported entity type '{entity_type}' for barcode generation")

    # 1. Register or retrieve idempotent barcode record
    db_symbology = "CODE128" if symbology.upper() == "CODE128" else "QR_CODE"
    barcode_rec = get_or_create_entity_barcode_record(
        entity_type=entity_type_norm,
        entity_id=entity_id_actual,
        entity_reference=ref,
        symbology=db_symbology,
        label_size=label_size,
        created_by=created_by,
    )

    # 2. Build HTML Label content
    label_html = build_label_html(
        entity_type=entity_type_norm,
        entity_reference=ref,
        qr_payload=barcode_rec["barcode_value"],
        metadata=metadata,
        label_size=label_size,
    )

    # 3. Save label file
    relative_path = save_label_artifact(
        barcode_id=barcode_rec["id"],
        label_html=label_html,
        entity_reference=ref,
    )

    # Update file_path in database
    with get_connection() as conn:
        conn.execute(
            "UPDATE entity_barcodes SET file_path = ? WHERE id = ?",
            (relative_path, barcode_rec["id"]),
        )
        conn.commit()

    barcode_rec["file_path"] = relative_path
    barcode_rec["label_html"] = label_html
    return {
        "barcode": barcode_rec,
        "entity_metadata": metadata,
        "html_content": label_html,
    }


# =========================================================================
# 4. Scanner Resolution Engine (Universal Scan Resolver)
# =========================================================================

def resolve_scanned_barcode_payload(
    scanned_text: str,
    user_role: str,
    user_id: str,
) -> dict[str, Any]:
    """
    Parses and resolves raw scanned text (structured QR payload or plain Code128/SKU/PO).
    Performs server-side authentication, RBAC authorization, and returns authoritative context.
    """
    verify_role_permission(user_role, "scan_portal")

    raw = scanned_text.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty barcode scan payload")

    entity_type: str | None = None
    target_ref: str = raw

    # 1. Check registered barcodes table and enforce deactivation
    bc_rec = get_barcode_record_by_value(raw)
    if bc_rec:
        if not bc_rec.get("is_active", 1):
            raise HTTPException(
                status_code=400,
                detail=f"Barcode '{raw}' has been deactivated and is not valid for operational scanning.",
            )
        entity_type = bc_rec["entity_type"]
        target_ref = bc_rec["entity_reference"]

    # 2. Structured QR Payload Format: TS:v1:<TYPE>:<REF> or TS:<TYPE>:<REF>
    elif raw.startswith("TS:"):
        parts = raw.split(":")
        if len(parts) >= 4 and parts[1] == "v1":
            code_type = parts[2].upper()
            target_ref = ":".join(parts[3:])
        elif len(parts) >= 3:
            code_type = parts[1].upper()
            target_ref = ":".join(parts[2:])
        else:
            code_type = ""

        code_map = {
            "PROD": "product",
            "PRODUCT": "product",
            "LOC": "location",
            "LOCATION": "location",
            "WAREHOUSE_LOCATION": "location",
            "PO": "purchase_order",
            "PURCHASE_ORDER": "purchase_order",
            "GR": "goods_receipt",
            "GOODS_RECEIPT": "goods_receipt",
            "SO": "sales_order",
            "SALES_ORDER": "sales_order",
            "DSP": "sales_dispatch",
            "DISPATCH": "sales_dispatch",
            "SALES_DISPATCH": "sales_dispatch",
            "PKG": "dispatch_package",
            "PACKAGE": "dispatch_package",
            "EXP": "export_shipment",
            "SHIPMENT": "export_shipment",
            "EXPORT_SHIPMENT": "export_shipment",
            "DOC": "document",
            "DOCUMENT": "document",
        }
        entity_type = code_map.get(code_type)


    # 3. Fallback Heuristics for plain linear barcodes or manual entry
    with get_connection() as conn:
        # Check Product SKU
        if not entity_type:
            prod = conn.execute("SELECT id, sku FROM products WHERE LOWER(sku) = LOWER(?)", (target_ref,)).fetchone()
            if prod:
                entity_type = "product"
                target_ref = prod["sku"]

        # Check PO Number
        if not entity_type and (target_ref.startswith("PO-") or "PO" in target_ref):
            po = conn.execute("SELECT id, po_number FROM purchase_orders WHERE LOWER(po_number) = LOWER(?)", (target_ref,)).fetchone()
            if po:
                entity_type = "purchase_order"
                target_ref = po["po_number"]

        # Check GR Number
        if not entity_type and (target_ref.startswith("GR-") or "GR" in target_ref):
            gr = conn.execute("SELECT id, gr_number FROM goods_receipts WHERE LOWER(gr_number) = LOWER(?)", (target_ref,)).fetchone()
            if gr:
                entity_type = "goods_receipt"
                target_ref = gr["gr_number"]

        # Check SO Number
        if not entity_type and (target_ref.startswith("SO-") or "SO" in target_ref):
            so = conn.execute("SELECT id, order_number FROM sales_orders WHERE LOWER(order_number) = LOWER(?)", (target_ref,)).fetchone()
            if so:
                entity_type = "sales_order"
                target_ref = so["order_number"]

        # Check Dispatch Number
        if not entity_type and (target_ref.startswith("DISP-") or "DISP" in target_ref):
            disp = conn.execute("SELECT id, dispatch_number FROM sales_dispatches WHERE LOWER(dispatch_number) = LOWER(?)", (target_ref,)).fetchone()
            if disp:
                entity_type = "sales_dispatch"
                target_ref = disp["dispatch_number"]

        # Check Export Shipment Reference
        if not entity_type and (target_ref.startswith("EXP-") or "EXP" in target_ref):
            shp = conn.execute("SELECT id, reference FROM shipments WHERE LOWER(reference) = LOWER(?)", (target_ref,)).fetchone()
            if shp:
                entity_type = "export_shipment"
                target_ref = shp["reference"]

        # Check Location Code
        if not entity_type:
            loc = conn.execute("SELECT id, location_code FROM warehouse_locations WHERE LOWER(location_code) = LOWER(?)", (target_ref,)).fetchone()
            if loc:
                entity_type = "location"
                target_ref = loc["location_code"]

    if not entity_type:
        raise HTTPException(status_code=404, detail=f"Unrecognized or unregistered barcode payload '{raw}'")

    # 4. Resolve Authoritative Entity Payload
    resolved_data = fetch_entity_scan_details(entity_type, target_ref)

    # Audit lookup event
    record_erp_audit_log(
        entity_type="portal_scan",
        entity_id=target_ref,
        action="scan_lookup",
        changes={"raw_payload": raw, "resolved_type": entity_type},
        performed_by=user_id,
    )

    return {
        "status": "success",
        "entity_type": entity_type,
        "entity_reference": target_ref,
        "scanned_raw": raw,
        "data": resolved_data,
        "statutory_notice": PORTAL_STATUTORY_DISCLAIMER,
    }


def fetch_entity_scan_details(entity_type: str, ref: str) -> dict[str, Any]:
    """Retrieve authorized operational context for the scanned entity."""
    with get_connection() as conn:
        if entity_type == "product":
            cur = conn.execute("SELECT * FROM products WHERE sku = ? OR id = ?", (ref, ref))
            prod = cur.fetchone()
            if not prod:
                raise HTTPException(status_code=404, detail=f"Product '{ref}' not found")
            prod_dict = dict(prod)

            # Live Balances by stock_type
            cur_bal = conn.execute(
                """
                SELECT stock_type, COALESCE(SUM(on_hand_qty), 0.0) as qty, COALESCE(SUM(total_value), 0.0) as val
                FROM inventory_balances
                WHERE product_id = ?
                GROUP BY stock_type
                """,
                (prod["id"],),
            )
            bal_map = {r["stock_type"]: float(r["qty"]) for r in cur_bal.fetchall()}

            # Active Reservations
            cur_res = conn.execute(
                "SELECT COALESCE(SUM(quantity), 0.0) FROM stock_reservations WHERE product_id = ? AND status = 'active'",
                (prod["id"],),
            )
            reserved_qty = float(cur_res.fetchone()[0] or 0.0)
            avail = bal_map.get("available", 0.0)
            net_avail = round(avail - reserved_qty, 2)
            reorder = float(prod["reorder_level"] or 0.0)

            if reorder > 0 and net_avail <= 0:
                health = "CRITICAL"
            elif reorder > 0 and net_avail <= reorder:
                health = "LOW_STOCK"
            else:
                health = "HEALTHY"

            # Location-level breakdown
            cur_loc = conn.execute(
                """
                SELECT lib.warehouse_id, wh.code as warehouse_code, lib.location_id,
                       loc.location_code, lib.stock_type, lib.on_hand_qty
                FROM location_inventory_balances lib
                JOIN warehouses wh ON wh.id = lib.warehouse_id
                JOIN warehouse_locations loc ON loc.id = lib.location_id
                WHERE lib.product_id = ? AND lib.on_hand_qty > 0
                ORDER BY wh.code, loc.location_code
                """,
                (prod["id"],),
            )
            locations = [dict(r) for r in cur_loc.fetchall()]

            return {
                "product": prod_dict,
                "balances": {
                    "available_qty": avail,
                    "reserved_qty": reserved_qty,
                    "net_available_qty": net_avail,
                    "quarantined_qty": bal_map.get("quarantined", 0.0),
                    "rejected_qty": bal_map.get("rejected", 0.0),
                    "in_transit_qty": bal_map.get("in_transit", 0.0),
                },
                "stock_health": health,
                "locations": locations,
            }

        elif entity_type == "purchase_order":
            cur = conn.execute("SELECT * FROM purchase_orders WHERE po_number = ? OR id = ?", (ref, ref))
            po = cur.fetchone()
            if not po:
                raise HTTPException(status_code=404, detail=f"Purchase Order '{ref}' not found")
            po_dict = dict(po)

            cur_items = conn.execute(
                """
                SELECT poi.*, p.name as product_name, p.uom,
                       MAX(0, poi.ordered_qty - poi.received_qty) as pending_qty
                FROM purchase_order_items poi
                JOIN products p ON p.id = poi.product_id
                WHERE poi.po_id = ?
                """,
                (po["id"],),
            )
            items = [dict(it) for it in cur_items.fetchall()]
            return {
                "purchase_order": po_dict,
                "lines": items,
                "can_receive": po["status"] in ("approved", "partial_receipt", "submitted"),
            }

        elif entity_type == "goods_receipt":
            cur = conn.execute(
                """
                SELECT gr.*, po.po_number, po.supplier_name, wh.code as warehouse_code
                FROM goods_receipts gr
                LEFT JOIN purchase_orders po ON po.id = gr.po_id
                LEFT JOIN warehouses wh ON wh.id = gr.warehouse_id
                WHERE gr.gr_number = ? OR gr.id = ?
                """,
                (ref, ref),
            )
            gr = cur.fetchone()
            if not gr:
                raise HTTPException(status_code=404, detail=f"Goods Receipt '{ref}' not found")
            gr_dict = dict(gr)

            cur_items = conn.execute(
                """
                SELECT gri.*, p.name as product_name, p.uom
                FROM goods_receipt_items gri
                JOIN products p ON p.id = gri.product_id
                WHERE gri.gr_id = ?
                """,
                (gr["id"],),
            )
            items = [dict(it) for it in cur_items.fetchall()]
            return {
                "goods_receipt": gr_dict,
                "items": items,
            }

        elif entity_type == "sales_order":
            cur = conn.execute("SELECT * FROM sales_orders WHERE order_number = ? OR id = ?", (ref, ref))
            so = cur.fetchone()
            if not so:
                raise HTTPException(status_code=404, detail=f"Sales Order '{ref}' not found")
            so_dict = dict(so)

            cur_items = conn.execute(
                """
                SELECT soi.*, p.name as product_name, p.uom
                FROM sales_order_items soi
                JOIN products p ON p.id = soi.product_id
                WHERE soi.sales_order_id = ?
                """,
                (so["id"],),
            )
            items = [dict(it) for it in cur_items.fetchall()]
            return {
                "sales_order": so_dict,
                "items": items,
                "can_pack": so["status"] in ("confirmed", "allocated", "picking", "partially_fulfilled"),
            }

        elif entity_type in ("sales_dispatch", "dispatch_package"):
            cur = conn.execute(
                """
                SELECT d.*, so.order_number, so.customer_name, wh.code as warehouse_code
                FROM sales_dispatches d
                JOIN sales_orders so ON so.id = d.sales_order_id
                JOIN warehouses wh ON wh.id = d.warehouse_id
                WHERE d.dispatch_number = ? OR d.id = ?
                """,
                (ref, ref),
            )
            disp = cur.fetchone()
            if not disp:
                raise HTTPException(status_code=404, detail=f"Dispatch '{ref}' not found")
            disp_dict = dict(disp)

            cur_items = conn.execute("SELECT * FROM sales_dispatch_items WHERE dispatch_id = ?", (disp["id"],))
            items = [dict(it) for it in cur_items.fetchall()]
            return {
                "dispatch": disp_dict,
                "items": items,
            }

        elif entity_type == "export_shipment":
            cur = conn.execute("SELECT * FROM shipments WHERE reference = ? OR id = ?", (ref, ref))
            shp = cur.fetchone()
            if not shp:
                raise HTTPException(status_code=404, detail=f"Export Shipment '{ref}' not found")
            shp_dict = dict(shp)

            # Linked Dispatches
            cur_dsp = conn.execute(
                """
                SELECT d.id, d.dispatch_number, d.packages_count, d.total_weight_kg, d.status
                FROM export_shipment_dispatches esd
                JOIN sales_dispatches d ON d.id = esd.dispatch_id
                WHERE esd.shipment_id = ?
                """,
                (shp["id"],),
            )
            dispatches = [dict(d) for d in cur_dsp.fetchall()]

            # Documents & Blockers
            cur_docs = conn.execute("SELECT * FROM documents WHERE shipment_id = ? ORDER BY created_at DESC", (shp["id"],))
            documents = [dict(doc) for doc in cur_docs.fetchall()]

            return {
                "shipment": shp_dict,
                "linked_dispatches": dispatches,
                "documents": documents,
                "readiness_status": shp_dict.get("readiness_status", "not_evaluated"),
                "disclaimer": EXPORT_COMPLIANCE_DISCLAIMER,
            }

        elif entity_type == "location":
            # Match composite 'WH:LOC' or plain 'LOC'
            if ":" in ref:
                wh_code, loc_code = ref.split(":", 1)
                cur = conn.execute(
                    """
                    SELECT loc.*, wh.code as warehouse_code, wh.name as warehouse_name
                    FROM warehouse_locations loc
                    JOIN warehouses wh ON wh.id = loc.warehouse_id
                    WHERE LOWER(wh.code) = LOWER(?) AND LOWER(loc.location_code) = LOWER(?)
                    """,
                    (wh_code.strip(), loc_code.strip()),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT loc.*, wh.code as warehouse_code, wh.name as warehouse_name
                    FROM warehouse_locations loc
                    JOIN warehouses wh ON wh.id = loc.warehouse_id
                    WHERE LOWER(loc.location_code) = LOWER(?)
                    """,
                    (ref.strip(),),
                )
            loc = cur.fetchone()
            if not loc:
                raise HTTPException(status_code=404, detail=f"Location '{ref}' not found")
            loc_dict = dict(loc)

            # Live inventory at this specific location
            cur_stock = conn.execute(
                """
                SELECT lib.*, p.name as product_name, p.uom
                FROM location_inventory_balances lib
                JOIN products p ON p.id = lib.product_id
                WHERE lib.location_id = ? AND lib.on_hand_qty > 0
                ORDER BY p.sku ASC
                """,
                (loc["id"],),
            )
            stock = [dict(s) for s in cur_stock.fetchall()]
            return {
                "location": loc_dict,
                "inventory": stock,
            }

        raise HTTPException(status_code=400, detail=f"Unhandled entity type '{entity_type}'")
