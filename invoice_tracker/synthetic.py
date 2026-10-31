"""Synthetic invoice generator.

Creates realistic-looking PDF (and a few .eml) invoices from fictional
suppliers, with deliberately planted problems, plus a ground-truth JSON file
used by the tests.

This module describes "the world" (what the suppliers actually send). It is
intentionally independent from the extractor's config so the extractor can't
cheat by reading the generator's data.
"""
from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

BUYER = [
    "Aurora Biosciences AB",
    "Attn: Accounts Payable",
    "Dag Hammarskjölds väg 54",
    "752 37 Uppsala, Sweden",
]

SV_MONTHS = ["jan", "feb", "mars", "apr", "maj", "juni",
             "juli", "aug", "sep", "okt", "nov", "dec"]
EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------
# Supplier definitions
# --------------------------------------------------------------------------

@dataclass
class Supplier:
    key: str
    name: str
    category: str               # ground-truth category
    currency: str
    address: List[str]
    email: str
    inv_fmt: str                # format string taking {n}
    date_fmt: str               # iso | en_long | de | us | sv_long | eu_slash
    num_fmt: str                # en | se | de
    vat_rate: float
    vat_label: str
    labels: Dict[str, str]      # invoice_no, date, due, po, total, customer
    style: Dict[str, str]       # header, fields, font, accent, title, cur_pos
    catalog: List[Tuple[str, float, float, int, int]]  # desc, pmin, pmax, qmin, qmax
    count: int


SUPPLIERS: List[Supplier] = [
    Supplier(
        key="nordvik", name="Nordvik Labware AB", category="lab_consumables",
        currency="SEK",
        address=["Kungsgatan 12", "411 19 Göteborg, Sweden", "Org.nr 556712-4410"],
        email="faktura@nordviklabware.se",
        inv_fmt="NL-2026-{n:04d}", date_fmt="iso", num_fmt="se",
        vat_rate=0.25, vat_label="Moms 25%",
        labels=dict(invoice_no="Fakturanummer", date="Fakturadatum", due="Förfallodatum",
                    po="Er referens / PO", total="Att betala", customer="Kundnummer"),
        style=dict(header="left", fields="lines", font="Helvetica",
                   accent="#1f6f8b", title="FAKTURA", cur_pos="suffix"),
        catalog=[
            ("Filter pipette tips 200 uL, racked (10x96)", 450, 650, 2, 8),
            ("Microcentrifuge tubes 1.5 mL (500 pcs)", 220, 320, 2, 10),
            ("Serological pipettes 10 mL, sterile (200)", 780, 980, 1, 4),
            ("Nitrile gloves size M (10x100)", 900, 1200, 1, 4),
            ("Cryovials 2 mL, external thread (500)", 1100, 1500, 1, 3),
            ("96-well PCR plates, skirted (50)", 1300, 1700, 1, 3),
        ],
        count=7,
    ),
    Supplier(
        key="pipetteco", name="PipetteCo Scientific Ltd", category="lab_consumables",
        currency="EUR",
        address=["Unit 4, Sandyford Business Park", "Dublin 18, Ireland", "VAT IE 9823117K"],
        email="accounts@pipetteco.ie",
        inv_fmt="INV-{n:05d}", date_fmt="en_long", num_fmt="en",
        vat_rate=0.0, vat_label="VAT 0% (reverse charge)",
        labels=dict(invoice_no="Invoice No.", date="Invoice Date", due="Due Date",
                    po="PO Number", total="Total Due", customer="Account"),
        style=dict(header="right", fields="table", font="Helvetica",
                   accent="#8b1f4b", title="INVOICE", cur_pos="prefix"),
        catalog=[
            ("Single-channel pipette 20-200 uL", 180, 260, 1, 4),
            ("Low-retention tips 10 uL (960)", 45, 70, 2, 12),
            ("Reagent reservoirs 25 mL (100)", 60, 90, 1, 5),
            ("Pipette stand, carousel", 90, 130, 1, 2),
        ],
        count=5,
    ),
    Supplier(
        key="bioreagent", name="BioReagent Supply GmbH", category="lab_consumables",
        currency="EUR",
        address=["Industriestraße 31", "69115 Heidelberg, Germany", "USt-IdNr. DE281734455"],
        email="rechnung@bioreagent-supply.de",
        inv_fmt="BRS/26/{n:05d}", date_fmt="de", num_fmt="de",
        vat_rate=0.0, vat_label="USt 0% - Reverse Charge",
        labels=dict(invoice_no="Invoice #", date="Date", due="Payable by",
                    po="Purchase Order", total="Amount Due", customer="Customer ID"),
        style=dict(header="band", fields="lines", font="Times-Roman",
                   accent="#2e7d32", title="INVOICE / RECHNUNG", cur_pos="suffix"),
        catalog=[
            ("Fetal bovine serum, heat-inactivated 500 mL", 380, 520, 1, 3),
            ("DMEM high glucose 500 mL (10)", 140, 190, 1, 4),
            ("Trypsin-EDTA 0.25% 100 mL (10)", 95, 130, 1, 3),
            ("Taq DNA polymerase 500 U", 160, 240, 1, 3),
            ("Agarose, molecular grade 500 g", 210, 280, 1, 2),
        ],
        count=6,
    ),
    Supplier(
        key="kalibra", name="Kalibra Instrument Services AB", category="instrument_service",
        currency="SEK",
        address=["Rapsgatan 7", "754 50 Uppsala, Sweden", "Org.nr 556901-2287"],
        email="invoices@kalibra.se",
        inv_fmt="KIS-{n:05d}", date_fmt="iso", num_fmt="se",
        vat_rate=0.25, vat_label="VAT 25%",
        labels=dict(invoice_no="Invoice number", date="Invoice date", due="Due date",
                    po="PO", total="Total amount", customer="Customer no"),
        style=dict(header="right", fields="table", font="Helvetica",
                   accent="#e07b00", title="INVOICE", cur_pos="suffix"),
        catalog=[
            ("Annual calibration - analytical balance", 3800, 5200, 1, 2),
            ("Preventive maintenance visit - HPLC", 14000, 19000, 1, 1),
            ("On-site service, technician hours", 1250, 1450, 2, 8),
            ("Travel flat fee", 1500, 1500, 1, 1),
            ("Replacement part: pump seal kit", 2200, 3100, 1, 2),
        ],
        count=6,
    ),
    Supplier(
        key="spectracare", name="SpectraCare Field Service Inc.", category="instrument_service",
        currency="USD",
        address=["2200 Research Blvd, Suite 400", "Rockville, MD 20850, USA", "EIN 52-1873340"],
        email="billing@spectracare.com",
        inv_fmt="SC-{n:05d}", date_fmt="us", num_fmt="en",
        vat_rate=0.0, vat_label="Sales tax",
        labels=dict(invoice_no="Inv #", date="Date", due="Terms",
                    po="Customer PO", total="TOTAL", customer="Cust. ID"),
        style=dict(header="left", fields="strip", font="Courier",
                   accent="#37474f", title="SERVICE INVOICE", cur_pos="symbol"),
        catalog=[
            ("Service contract - spectrophotometer (quarterly)", 2400, 2900, 1, 1),
            ("Field service engineer, labor (hr)", 185, 225, 2, 6),
            ("Deuterium lamp replacement", 520, 640, 1, 1),
            ("Travel & expenses", 300, 450, 1, 1),
        ],
        count=5,
    ),
    Supplier(
        key="coldchain", name="ColdChain Logistics AB", category="shipping",
        currency="SEK",
        address=["Terminalvägen 3", "195 87 Märsta, Sweden", "Org.nr 556455-9031"],
        email="ekonomi@coldchainlogistics.se",
        inv_fmt="CCL 2026 {n:04d}", date_fmt="sv_long", num_fmt="se",
        vat_rate=0.25, vat_label="Moms 25%",
        labels=dict(invoice_no="Faktura nr", date="Datum", due="Förfaller",
                    po="Ordernr / PO", total="Summa att betala", customer="Kund nr"),
        style=dict(header="band", fields="table", font="Helvetica",
                   accent="#0d47a1", title="FAKTURA", cur_pos="suffix"),
        catalog=[
            ("Dry ice shipment, 20 kg", 950, 1300, 1, 2),
            ("Temperature-controlled courier (2-8 C)", 1400, 2100, 1, 2),
            ("Return of cold-chain boxes", 300, 450, 1, 1),
            ("Fuel surcharge", 80, 160, 1, 1),
        ],
        count=4,
    ),
    Supplier(
        key="baltic", name="Baltic Freight Express OÜ", category="shipping",
        currency="EUR",
        address=["Peterburi tee 46", "11415 Tallinn, Estonia", "KMKR EE101928374"],
        email="invoice@balticfreight.ee",
        inv_fmt="BFE{n:06d}", date_fmt="eu_slash", num_fmt="en",
        vat_rate=0.0, vat_label="VAT 0% reverse charge",
        labels=dict(invoice_no="Invoice No", date="Issue date", due="Due",
                    po="PO ref.", total="Grand total", customer="Client code"),
        style=dict(header="left", fields="lines", font="Helvetica",
                   accent="#6a1b9a", title="INVOICE", cur_pos="prefix"),
        catalog=[
            ("Air freight, express parcel", 85, 220, 1, 3),
            ("Customs clearance fee", 35, 60, 1, 1),
            ("Pallet transport, Riga-Stockholm", 380, 560, 1, 1),
            ("Insurance surcharge", 12, 25, 1, 1),
        ],
        count=4,
    ),
]


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def fmt_number(x: float, style: str) -> str:
    s = f"{x:,.2f}"  # 1,234.50
    if style == "en":
        return s
    if style == "se":
        return s.replace(",", " ").replace(".", ",")
    if style == "de":
        return s.replace(",", "#").replace(".", ",").replace("#", ".")
    raise ValueError(style)


def fmt_money(x: float, sup: Supplier) -> str:
    n = fmt_number(x, sup.num_fmt)
    pos = sup.style["cur_pos"]
    if pos == "prefix":
        return f"{sup.currency} {n}"
    if pos == "symbol":
        return f"${n}"
    return f"{n} {sup.currency}"


def fmt_date(d: date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "en_long":
        return f"{d.day:02d} {EN_MONTHS[d.month - 1]} {d.year}"
    if style == "de":
        return d.strftime("%d.%m.%Y")
    if style == "us":
        return d.strftime("%m/%d/%Y")
    if style == "eu_slash":
        return d.strftime("%d/%m/%Y")
    if style == "sv_long":
        return f"{d.day} {SV_MONTHS[d.month - 1]} {d.year}"
    raise ValueError(style)


# --------------------------------------------------------------------------
# Invoice spec
# --------------------------------------------------------------------------

@dataclass
class LineItem:
    description: str
    qty: int
    unit_price: float

    @property
    def amount(self) -> float:
        return round(self.qty * self.unit_price, 2)


@dataclass
class InvoiceSpec:
    supplier_key: str
    invoice_number: str
    invoice_date: Optional[date]
    due_date: date
    po_number: Optional[str]
    customer_no: str
    items: List[LineItem]
    vat_rate: float
    filename: str = ""
    planted: List[str] = field(default_factory=list)
    duplicate_of: Optional[str] = None
    as_eml: bool = False

    @property
    def subtotal(self) -> float:
        return round(sum(i.amount for i in self.items), 2)

    @property
    def vat(self) -> float:
        return round(self.subtotal * self.vat_rate, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.vat, 2)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _bold(font: str) -> str:
    return {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold",
            "Courier": "Courier-Bold"}[font]


def render_pdf(spec: InvoiceSpec, sup: Supplier, path: Path) -> None:
    W, H = A4
    st = sup.style
    font, bold = st["font"], _bold(st["font"])
    accent = colors.HexColor(st["accent"])
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(f"{sup.name} {spec.invoice_number}")
    c.setAuthor(sup.name)

    # ---- header -------------------------------------------------------
    if st["header"] == "band":
        c.setFillColor(accent)
        c.rect(0, H - 95, W, 95, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(bold, 20)
        c.drawString(40, H - 48, sup.name)
        c.setFont(font, 9)
        c.drawString(40, H - 66, "  |  ".join(sup.address))
        c.drawString(40, H - 80, sup.email)
        c.setFont(bold, 16)
        c.drawRightString(W - 40, H - 130, st["title"])
        c.setFillColor(colors.black)
        top = H - 150
    elif st["header"] == "left":
        c.setFillColor(accent)
        c.roundRect(40, H - 100, 52, 52, 6, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(bold, 18)
        initials = "".join(w[0] for w in sup.name.split()[:2])
        c.drawCentredString(66, H - 81, initials)
        c.setFillColor(colors.black)
        c.setFont(bold, 15)
        c.drawString(104, H - 62, sup.name)
        c.setFont(font, 8.5)
        for i, line in enumerate(sup.address + [sup.email]):
            c.drawString(104, H - 76 - i * 11, line)
        c.setFillColor(accent)
        c.setFont(bold, 18)
        c.drawRightString(W - 40, H - 128, st["title"])
        c.setFillColor(colors.black)
        top = H - 150
    else:  # right
        c.setFillColor(accent)
        c.setFont(bold, 26)
        c.drawString(40, H - 70, st["title"])
        c.setFillColor(colors.black)
        c.setFont(bold, 14)
        c.drawRightString(W - 40, H - 55, sup.name)
        c.setFont(font, 8.5)
        for i, line in enumerate(sup.address + [sup.email]):
            c.drawRightString(W - 40, H - 70 - i * 11, line)
        c.setStrokeColor(accent)
        c.setLineWidth(2)
        c.line(40, H - 125, W - 40, H - 125)
        top = H - 150

    # ---- bill-to ------------------------------------------------------
    c.setFont(bold, 9)
    c.drawString(40, top, "Bill to:" if sup.num_fmt != "se" else "Faktureringsadress:")
    c.setFont(font, 9)
    for i, line in enumerate(BUYER):
        c.drawString(40, top - 13 - i * 12, line)

    # ---- header fields ------------------------------------------------
    L = sup.labels
    fields: List[Tuple[str, str]] = [(L["invoice_no"], spec.invoice_number)]
    if spec.invoice_date is not None:
        fields.append((L["date"], fmt_date(spec.invoice_date, sup.date_fmt)))
    if sup.key == "spectracare":
        fields.append((L["due"], "Net 30"))
    else:
        fields.append((L["due"], fmt_date(spec.due_date, sup.date_fmt)))
    if spec.po_number is not None:
        fields.append((L["po"], spec.po_number))
    fields.append((L["customer"], spec.customer_no))

    if st["fields"] == "lines":
        x = W - 270
        for i, (lab, val) in enumerate(fields):
            y = top - i * 14
            c.setFont(bold, 9)
            c.drawString(x, y, f"{lab}:")
            c.setFont(font, 9)
            c.drawString(x + 115, y, val)
        y_after = top - 75
    elif st["fields"] == "table":
        x, w1, w2, rh = W - 280, 110, 130, 16
        c.setStrokeColor(colors.grey)
        c.setLineWidth(0.5)
        for i, (lab, val) in enumerate(fields):
            y = top + 4 - i * rh
            c.setFillColor(colors.HexColor("#eeeeee"))
            c.rect(x, y - rh + 4, w1, rh, fill=1, stroke=1)
            c.setFillColor(colors.white)
            c.rect(x + w1, y - rh + 4, w2, rh, fill=1, stroke=1)
            c.setFillColor(colors.black)
            c.setFont(bold, 8.5)
            c.drawString(x + 4, y - 7, lab)
            c.setFont(font, 8.5)
            c.drawString(x + w1 + 4, y - 7, val)
        y_after = top - 80
    else:  # strip: labels in one row, values beneath
        y = top - 70
        c.setFillColor(colors.HexColor("#eceff1"))
        c.rect(40, y - 22, W - 80, 34, fill=1, stroke=0)
        c.setFillColor(colors.black)
        colw = (W - 80) / len(fields)
        for i, (lab, val) in enumerate(fields):
            cx = 46 + i * colw
            c.setFont(bold, 8)
            c.drawString(cx, y, lab)
            c.setFont(font, 9)
            c.drawString(cx, y - 14, val)
        y_after = y - 40

    # ---- line items ---------------------------------------------------
    y = min(y_after, top - 90) - 10
    cols = [40, 330, 400, W - 40]  # desc, qty, unit (right), amount (right)
    c.setFillColor(accent)
    c.rect(40, y - 4, W - 80, 16, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(bold, 9)
    sv = sup.num_fmt == "se" and sup.key != "kalibra"
    hdr = (["Beskrivning", "Antal", "À-pris", "Belopp"] if sv
           else ["Description", "Qty", "Unit price", "Amount"])
    c.drawString(cols[0] + 4, y, hdr[0])
    c.drawRightString(cols[1] + 20, y, hdr[1])
    c.drawRightString(cols[2] + 70, y, hdr[2])
    c.drawRightString(cols[3] - 4, y, hdr[3])
    c.setFillColor(colors.black)
    c.setFont(font, 9)
    y -= 18
    for it in spec.items:
        c.drawString(cols[0] + 4, y, it.description)
        c.drawRightString(cols[1] + 20, y, str(it.qty))
        c.drawRightString(cols[2] + 70, y, fmt_number(it.unit_price, sup.num_fmt))
        c.drawRightString(cols[3] - 4, y, fmt_number(it.amount, sup.num_fmt))
        y -= 15
    c.setStrokeColor(colors.grey)
    c.line(40, y + 6, W - 40, y + 6)

    # ---- totals -------------------------------------------------------
    y -= 14
    sub_label = "Summa exkl. moms" if sv else "Subtotal"
    rows = [(sub_label, fmt_number(spec.subtotal, sup.num_fmt)),
            (sup.vat_label, fmt_number(spec.vat, sup.num_fmt))]
    for lab, val in rows:
        c.setFont(font, 9)
        c.drawString(W - 260, y, lab)
        c.drawRightString(W - 44, y, val)
        y -= 14
    y -= 6
    c.setFillColor(colors.HexColor("#f2f2f2"))
    c.rect(W - 265, y - 6, 225, 20, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont(bold, 11)
    c.drawString(W - 260, y, L["total"])
    c.drawRightString(W - 44, y, fmt_money(spec.total, sup))

    # ---- footer -------------------------------------------------------
    c.setFont(font, 7.5)
    c.setFillColor(colors.HexColor("#555555"))
    foot = [
        f"Payment terms: 30 days net. Please quote the invoice number with your payment.",
        f"Bank: IBAN SE45 5000 0000 0583 9825 7466  BIC ESSESESS  |  {sup.email}",
    ]
    if sup.currency == "USD":
        foot.insert(0, "All amounts in USD.")
    for i, line in enumerate(foot):
        c.drawString(40, 50 - i * 10, line)
    c.showPage()
    c.save()


def write_eml(pdf_path: Path, eml_path: Path, spec: InvoiceSpec, sup: Supplier) -> None:
    msg = EmailMessage()
    msg["From"] = f"{sup.name} <{sup.email}>"
    msg["To"] = "ap@aurorabio.se"
    msg["Subject"] = f"Invoice {spec.invoice_number} from {sup.name}"
    d = spec.invoice_date or spec.due_date
    msg["Date"] = format_datetime(datetime(d.year, d.month, d.day, 9, 30, tzinfo=timezone.utc))
    msg["Message-ID"] = f"<{spec.invoice_number.replace(' ', '')}@{sup.email.split('@')[1]}>"
    msg.set_content(
        f"Dear customer,\n\nPlease find attached invoice {spec.invoice_number}.\n\n"
        f"Kind regards,\n{sup.name} accounts team\n"
    )
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf",
                       filename=pdf_path.name)
    eml_path.write_bytes(bytes(msg))


# --------------------------------------------------------------------------
# Building the dataset
# --------------------------------------------------------------------------

def _make_items(rng: random.Random, sup: Supplier, n_min: int = 1, n_max: int = 3) -> List[LineItem]:
    picks = rng.sample(sup.catalog, k=rng.randint(n_min, min(n_max, len(sup.catalog))))
    items = []
    for desc, pmin, pmax, qmin, qmax in picks:
        price = round(rng.uniform(pmin, pmax), 0 if sup.currency == "SEK" else 2)
        items.append(LineItem(desc, rng.randint(qmin, qmax), price))
    return items


def build_specs(seed: int = 42) -> List[InvoiceSpec]:
    rng = random.Random(seed)
    start = date(2026, 5, 1)
    span = (date(2026, 10, 28) - start).days
    used_pos = set()

    def new_po() -> str:
        while True:
            po = f"4500{rng.randint(100000, 999999)}"
            if po not in used_pos:
                used_pos.add(po)
                return po

    specs: List[InvoiceSpec] = []
    by_sup: Dict[str, List[InvoiceSpec]] = {}
    for sup in SUPPLIERS:
        dates = sorted(start + timedelta(days=rng.randint(0, span)) for _ in range(sup.count))
        n0 = rng.randint(100, 900)
        cust = f"{rng.randint(10000, 99999)}"
        lst = []
        for i, d in enumerate(dates):
            spec = InvoiceSpec(
                supplier_key=sup.key,
                invoice_number=sup.inv_fmt.format(n=n0 + i * rng.randint(3, 40)),
                invoice_date=d,
                due_date=d + timedelta(days=30),
                po_number=new_po(),
                customer_no=cust,
                items=_make_items(rng, sup),
                vat_rate=sup.vat_rate,
            )
            lst.append(spec)
        by_sup[sup.key] = lst
        specs.extend(lst)

    # --- planted problems --------------------------------------------
    # Unusually large amounts (suppliers with enough history for outlier stats)
    big = by_sup["nordvik"][4]
    big.items = [LineItem("Annual bulk order - filter pipette tips, full pallet (400x96)", 40, 1180.0)]
    big.planted.append("unusual_amount")
    big2 = by_sup["kalibra"][3]
    big2.items = [LineItem("Major repair - HPLC pump module replacement", 1, 148500.0),
                  LineItem("On-site service, technician hours", 16, 1395.0)]
    big2.planted.append("unusual_amount")

    # Missing fields
    m1 = by_sup["spectracare"][2]
    m1.po_number = None
    m1.planted.append("missing_po_number")
    m2 = by_sup["coldchain"][1]
    m2.po_number = None
    m2.planted.append("missing_po_number")
    m3 = by_sup["bioreagent"][3]
    m3.invoice_date = None
    m3.planted.append("missing_invoice_date")

    # Delivered by email
    by_sup["kalibra"][1].as_eml = True
    by_sup["baltic"][2].as_eml = True

    # Filenames for base set
    sup_by_key = {s.key: s for s in SUPPLIERS}
    for i, s in enumerate(specs):
        slug = s.invoice_number.replace("/", "-").replace(" ", "_")
        style = i % 3
        if style == 0:
            s.filename = f"{s.supplier_key}_{slug}"
        elif style == 1:
            s.filename = f"invoice_{slug}"
        else:
            s.filename = f"scan_{i + 1:04d}"
        s.filename += ".eml" if s.as_eml else ".pdf"

    # Exact duplicates: the supplier re-sent the same PDF
    for src, name in [(by_sup["pipetteco"][1], "Fwd_resend"),
                      (by_sup["baltic"][0], "reminder_copy")]:
        dup = InvoiceSpec(**{**asdict_shallow(src), "planted": ["duplicate_exact"],
                             "duplicate_of": src.filename, "as_eml": False})
        dup.filename = f"{name}_{Path(src.filename).stem}.pdf"
        specs.append(dup)

    # Near-duplicate: same supplier + PO, slightly different amount, new invoice no.
    orig = by_sup["bioreagent"][1]
    near = InvoiceSpec(**{**asdict_shallow(orig), "planted": ["duplicate_near"],
                          "duplicate_of": orig.filename, "as_eml": False})
    near.invoice_number = sup_by_key["bioreagent"].inv_fmt.format(
        n=int(orig.invoice_number.split("/")[-1]) + 3)
    near.invoice_date = orig.invoice_date + timedelta(days=6)
    near.due_date = near.invoice_date + timedelta(days=30)
    near.items = [LineItem(it.description, it.qty, round(it.unit_price * 1.02, 2))
                  for it in orig.items]
    near.filename = f"bioreagent_{near.invoice_number.replace('/', '-')}.pdf"
    specs.append(near)

    return specs


def asdict_shallow(spec: InvoiceSpec) -> dict:
    """Shallow field copy (keeps LineItem objects, copies the list)."""
    d = {f: getattr(spec, f) for f in spec.__dataclass_fields__}
    d["items"] = list(spec.items)
    d["planted"] = list(spec.planted)
    return d


def generate(out_dir: Path, seed: int = 42, clean: bool = True) -> List[dict]:
    """Render all invoices into out_dir and write _ground_truth.json."""
    out_dir = Path(out_dir)
    if clean and out_dir.exists():
        for p in out_dir.iterdir():
            if p.is_file() and (p.suffix in {".pdf", ".eml"} or p.name == "_ground_truth.json"):
                p.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    sup_by_key = {s.key: s for s in SUPPLIERS}
    specs = build_specs(seed)
    truth = []
    rendered: Dict[str, Path] = {}
    for s in specs:
        sup = sup_by_key[s.supplier_key]
        target = out_dir / s.filename
        if "duplicate_exact" in s.planted:
            src = rendered[s.duplicate_of]
            if src.suffix == ".pdf":
                shutil.copyfile(src, target)
            else:
                render_pdf(s, sup, target)
        elif s.as_eml:
            tmp_pdf = out_dir / (Path(s.filename).stem + ".pdf.tmp")
            render_pdf(s, sup, tmp_pdf)
            final_pdf_name = tmp_pdf.with_suffix("")  # .pdf
            tmp_pdf.rename(final_pdf_name)
            write_eml(final_pdf_name, target, s, sup)
            final_pdf_name.unlink()
        else:
            render_pdf(s, sup, target)
        rendered[s.filename] = target
        truth.append({
            "source_file": s.filename,
            "supplier": sup.name,
            "invoice_number": s.invoice_number,
            "invoice_date": s.invoice_date.isoformat() if s.invoice_date else None,
            "total_amount": s.total,
            "currency": sup.currency,
            "po_number": s.po_number,
            "category": sup.category,
            "line_items": [i.description for i in s.items],
            "planted": s.planted,
            "duplicate_of": s.duplicate_of,
        })
    (out_dir / "_ground_truth.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False))
    return truth
