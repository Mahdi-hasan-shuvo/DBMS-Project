"""Demo data generator.

Builds ~4 months of realistic history by running every purchase and sale
through services.inventory, so stock always equals purchases minus sales.
Dates are relative to today, which keeps dashboards and alerts meaningful.
"""
import datetime
import random

from services.inventory import InventoryError, create_purchase, create_sale

CATEGORIES = [
    ("Antibiotic", "Bacterial infection treatments"),
    ("Analgesic", "Pain relief and fever reducers"),
    ("Cardiovascular", "Heart and blood pressure medicines"),
    ("Antidiabetic", "Blood glucose control"),
    ("Respiratory", "Asthma, COPD and cough"),
    ("Gastrointestinal", "Acid, ulcer and digestion"),
    ("Antihistamine", "Allergy relief"),
    ("Vitamins & Supplements", "Nutritional supplements"),
    ("Dermatology", "Skin creams and ointments"),
    ("Antiviral", "Viral infection treatments"),
    ("Hormones", "Endocrine and hormone therapy"),
    ("Antiseptic", "Wound care and disinfectants"),
    ("Neurology", "Nervous system and sleep"),
    ("Ophthalmic", "Eye drops and ointments"),
]

# name, generic, form, category, manufacturer, cost, price, reorder level, popularity
MEDICINES = [
    ("Amoxil 500mg", "Amoxicillin Trihydrate", "Capsule", "Antibiotic", "GlaxoSmithKline", 8.50, 14.20, 50, 9),
    ("Augmentin 625mg", "Amoxicillin + Clavulanic Acid", "Tablet", "Antibiotic", "GlaxoSmithKline", 14.00, 22.50, 40, 6),
    ("Zithromax 500mg", "Azithromycin Dihydrate", "Tablet", "Antibiotic", "Pfizer Inc.", 12.50, 21.00, 30, 5),
    ("Ciprobay 500mg", "Ciprofloxacin", "Tablet", "Antibiotic", "Bayer", 9.20, 15.80, 30, 4),
    ("Ceftriaxone 1g", "Ceftriaxone Sodium", "Injection", "Antibiotic", "Novartis", 18.00, 27.00, 20, 2),
    ("Doxycap 100mg", "Doxycycline Hyclate", "Capsule", "Antibiotic", "Square Pharma", 4.10, 7.50, 30, 3),
    ("Panadol Extra", "Paracetamol + Caffeine", "Caplet", "Analgesic", "Haleon Consumer", 2.10, 4.50, 100, 10),
    ("Napa 500mg", "Paracetamol", "Tablet", "Analgesic", "Beximco Pharma", 0.90, 1.80, 120, 10),
    ("Brufen 400mg", "Ibuprofen", "Tablet", "Analgesic", "Abbott", 2.60, 5.20, 60, 7),
    ("Voltaren 50mg", "Diclofenac Sodium", "Tablet", "Analgesic", "Novartis", 4.80, 8.90, 40, 4),
    ("Tramadol 50mg", "Tramadol Hydrochloride", "Capsule", "Analgesic", "Sun Pharma", 6.40, 11.00, 25, 2),
    ("Lipitor 20mg", "Atorvastatin Calcium", "Film Tablet", "Cardiovascular", "Pfizer Inc.", 18.00, 29.50, 40, 6),
    ("Norvasc 5mg", "Amlodipine Besylate", "Tablet", "Cardiovascular", "Pfizer Inc.", 9.80, 16.40, 40, 6),
    ("Cozaar 50mg", "Losartan Potassium", "Tablet", "Cardiovascular", "Organon", 11.20, 18.90, 30, 5),
    ("Ecosprin 75mg", "Aspirin (low dose)", "Tablet", "Cardiovascular", "USV Ltd.", 1.20, 2.60, 60, 6),
    ("Concor 5mg", "Bisoprolol Fumarate", "Tablet", "Cardiovascular", "Merck KGaA", 7.40, 12.80, 30, 3),
    ("Glucophage 850mg", "Metformin Hydrochloride", "Tablet", "Antidiabetic", "Merck Sante", 6.20, 11.00, 80, 8),
    ("Amaryl 2mg", "Glimepiride", "Tablet", "Antidiabetic", "Sanofi", 8.90, 14.60, 30, 4),
    ("Januvia 100mg", "Sitagliptin", "Tablet", "Antidiabetic", "MSD", 32.00, 48.00, 20, 3),
    ("Lantus SoloStar", "Insulin Glargine 100 IU/mL", "Pen", "Antidiabetic", "Sanofi", 38.00, 56.00, 12, 2),
    ("Ventolin Evohaler 100mcg", "Salbutamol Sulfate", "Inhaler", "Respiratory", "GlaxoSmithKline", 9.80, 16.00, 25, 5),
    ("Seretide 250", "Fluticasone + Salmeterol", "Inhaler", "Respiratory", "GlaxoSmithKline", 28.00, 42.00, 15, 2),
    ("Montair 10mg", "Montelukast Sodium", "Tablet", "Respiratory", "Cipla", 7.60, 13.20, 30, 4),
    ("Benadryl Syrup", "Diphenhydramine", "Syrup 100ml", "Respiratory", "Johnson & Johnson", 3.40, 6.20, 30, 4),
    ("Nexium 40mg", "Esomeprazole Magnesium", "Delayed Release", "Gastrointestinal", "AstraZeneca", 22.00, 35.00, 20, 5),
    ("Omeprazole 20mg", "Omeprazole", "Capsule", "Gastrointestinal", "Square Pharma", 2.40, 4.80, 60, 8),
    ("Motilium 10mg", "Domperidone", "Tablet", "Gastrointestinal", "Janssen", 3.10, 5.90, 30, 3),
    ("Imodium 2mg", "Loperamide", "Capsule", "Gastrointestinal", "Johnson & Johnson", 3.80, 7.10, 25, 3),
    ("Cetirizine 10mg", "Cetirizine Hydrochloride", "Film Coated", "Antihistamine", "Sun Pharma", 1.50, 3.80, 50, 7),
    ("Allegra 120mg", "Fexofenadine", "Tablet", "Antihistamine", "Sanofi", 6.70, 11.90, 30, 4),
    ("Claritin 10mg", "Loratadine", "Tablet", "Antihistamine", "Bayer", 4.20, 7.80, 30, 3),
    ("Centrum Adults", "Multivitamin + Minerals", "Tablet", "Vitamins & Supplements", "Haleon Consumer", 9.00, 15.50, 25, 4),
    ("Calcium-D 500", "Calcium Carbonate + Vit D3", "Tablet", "Vitamins & Supplements", "Opsonin Pharma", 3.20, 6.00, 40, 5),
    ("Vitamin C 1000mg", "Ascorbic Acid", "Effervescent", "Vitamins & Supplements", "Bayer", 4.50, 8.20, 40, 4),
    ("Fefol", "Ferrous Sulfate + Folic Acid", "Capsule", "Vitamins & Supplements", "GSK", 2.20, 4.40, 40, 3),
    ("Betnovate Cream", "Betamethasone Valerate", "Cream 20g", "Dermatology", "GlaxoSmithKline", 3.60, 6.80, 20, 2),
    ("Fucidin Cream", "Fusidic Acid", "Cream 15g", "Dermatology", "LEO Pharma", 6.10, 10.90, 20, 2),
    ("Zovirax 400mg", "Acyclovir", "Tablet", "Antiviral", "GlaxoSmithKline", 10.40, 17.60, 20, 2),
    ("Tamiflu 75mg", "Oseltamivir", "Capsule", "Antiviral", "Roche", 24.00, 38.00, 15, 1),
    ("Eltroxin 50mcg", "Levothyroxine Sodium", "Tablet", "Hormones", "Aspen", 3.90, 7.20, 30, 4),
    ("Dexamethasone 4mg", "Dexamethasone", "Tablet", "Hormones", "Incepta", 1.10, 2.40, 30, 2),
    ("Savlon Liquid", "Chloroxylenol", "Liquid 500ml", "Antiseptic", "ACI Ltd.", 3.00, 5.50, 20, 3),
    ("Betadine 10%", "Povidone-Iodine", "Solution 100ml", "Antiseptic", "Mundipharma", 3.70, 6.90, 20, 2),
    ("Rivotril 0.5mg", "Clonazepam", "Tablet", "Neurology", "Roche", 4.60, 8.40, 20, 2),
    ("Gabapentin 300mg", "Gabapentin", "Capsule", "Neurology", "Pfizer Inc.", 8.20, 14.10, 20, 2),
    ("Systane Ultra", "Polyethylene Glycol Eye Drops", "Drops 10ml", "Ophthalmic", "Alcon", 7.30, 12.40, 15, 2),
    ("Moxiflox Eye Drops", "Moxifloxacin 0.5%", "Drops 5ml", "Ophthalmic", "Incepta", 3.30, 6.20, 15, 1),
]

SUPPLIERS = [
    ("Apex Pharma Logistics", "Marcus Sterling", "Boston", "742 Evergreen Blvd, Suite 400", "Net 30", "Active"),
    ("Greenline Medical Distributors", "Sarah Jenkins", "Philadelphia", "120 Industrial Parkway, Pier 9", "Net 15", "Active"),
    ("Northstar Pharma Supplies", "David Ross", "New York", "235 E 42nd St, Logistics Wing", "Net 30", "Active"),
    ("MedLife Wholesale Corp", "Elena Rostova", "Chicago", "88 North Riverside Plaza", "COD", "On Hold"),
    ("Coastal Vaccines Express", "Liam O'Connor", "San Diego", "5900 Pacific Center Blvd", "Net 30", "Active"),
    ("Sunrise Generics Ltd.", "Priya Nair", "Houston", "410 Commerce Street", "Net 45", "Active"),
    ("BlueRiver Healthcare Supply", "Tom Becker", "Denver", "77 Riverfront Ave", "Net 30", "Active"),
    ("Delta Cold-Chain Logistics", "Aisha Rahman", "Atlanta", "19 Peachtree Center", "Net 15", "Active"),
    ("Metro Pharma Traders", "Kenji Watanabe", "Seattle", "1200 Harbor Way", "Net 30", "Active"),
    ("Unity Drug House", "Rafael Ortiz", "Miami", "56 Biscayne Plaza", "COD", "Active"),
    ("Prime Care Distributors", "Grace Kim", "Dallas", "900 Elm Street", "Net 30", "On Hold"),
    ("Evergreen Medical Wholesale", "Omar Haddad", "Phoenix", "33 Desert Ridge Rd", "Net 45", "Active"),
]

FIRST = ["James", "Eleanor", "Marcus", "Sophia", "Carlos", "Ayesha", "Rahim", "Fatima", "Daniel", "Olivia",
         "Noah", "Mia", "Tanvir", "Nusrat", "Ethan", "Isabella", "Arif", "Sadia", "Lucas", "Amelia",
         "Kamal", "Farzana", "Henry", "Chloe", "Imran", "Mehjabin", "Leo", "Grace", "Hasan", "Tahmina",
         "Samuel", "Zara", "Rafiq", "Laila", "Owen", "Ruby"]
LAST = ["Harrison", "Vance", "Reed", "Patel", "Mendez", "Rahman", "Hossain", "Akter", "Brooks", "Turner",
        "Islam", "Chowdhury", "Ahmed", "Khan", "Foster", "Bennett", "Sarker", "Begum", "Ward", "Hughes"]
CITIES = ["Springfield", "Riverdale", "West End", "Oakwood", "Lakeside", "Hillview", "Dhanmondi", "Uttara"]
STREETS = ["Evergreen Terrace", "Oakridge Ave", "Beacon St", "Cypress Blvd", "Highland Crest", "Lake Road",
           "Park Lane", "Maple Drive"]
ALLERGIES = [None, None, None, None, "Penicillin", "Codeine", "Latex", "Aspirin sensitivity", "Sulfa drugs"]


def _phone(rng):
    return f"+1 (555) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}"


def seed_demo_data(db, today=None, rng_seed=42):
    rng = random.Random(rng_seed)
    today = today or datetime.date.today()
    now = datetime.datetime.now()

    # ---------------------------------------------------------- master data
    cat_ids = {}
    for name, desc in CATEGORIES:
        cat_ids[name] = db.execute(
            "INSERT INTO categories (category_name, description) VALUES (?, ?)", (name, desc)).lastrowid

    supplier_ids = []
    for name, contact, city, addr, terms, status in SUPPLIERS:
        slug = name.split()[0].lower()
        supplier_ids.append(db.execute(
            "INSERT INTO suppliers (supplier_name, contact_person, phone, email, address, city, "
            "payment_terms, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, contact, _phone(rng), f"orders@{slug}-pharma.example.com", addr, city, terms, status),
        ).lastrowid)
    active_suppliers = [sid for sid, s in zip(supplier_ids, SUPPLIERS) if s[5] == "Active"]

    # Special expiry situations so alerts have something to show
    special_expiry = {"Ceftriaxone 1g": 12, "Augmentin 625mg": 21, "Betnovate Cream": 6, "Tamiflu 75mg": 27,
                      "Lantus SoloStar": 45, "Zovirax 400mg": 60, "Fucidin Cream": 75, "Seretide 250": 84,
                      "Dexamethasone 4mg": -14, "Moxiflox Eye Drops": -40}
    out_of_stock = {"Zithromax 500mg", "Tramadol 50mg", "Gabapentin 300mg"}
    low_stock = {"Amoxil 500mg", "Glucophage 850mg", "Ventolin Evohaler 100mcg", "Concor 5mg",
                 "Montair 10mg", "Rivotril 0.5mg"}

    meds = []
    for idx, (name, generic, form, cat, mfr, cost, price, reorder, pop) in enumerate(MEDICINES):
        days = special_expiry.get(name, rng.randint(240, 900))
        expiry = (today + datetime.timedelta(days=days)).isoformat()
        sku = f"{''.join(ch for ch in name if ch.isalpha())[:3].upper()}-{101 + idx}"
        med_id = db.execute(
            "INSERT INTO medicines (category_id, medicine_name, generic_name, dosage_form, manufacturer, sku, "
            "batch_no, cost_price, price, stock_quantity, reorder_level, expiry_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (cat_ids[cat], name, generic, form, mfr, sku, f"LOT-{rng.randint(1000, 9999)}",
             cost, price, reorder, expiry),
        ).lastrowid
        meds.append({"id": med_id, "name": name, "cost": cost, "reorder": reorder, "pop": pop})

    customer_ids = []
    used = set()
    while len(customer_ids) < 36:
        first, last = rng.choice(FIRST), rng.choice(LAST)
        if (first, last) in used:
            continue
        used.add((first, last))
        gender = "Female" if first in {"Eleanor", "Sophia", "Ayesha", "Fatima", "Olivia", "Mia", "Nusrat",
                                       "Isabella", "Sadia", "Amelia", "Farzana", "Chloe", "Mehjabin", "Grace",
                                       "Tahmina", "Zara", "Laila", "Ruby"} else "Male"
        dob = today - datetime.timedelta(days=rng.randint(18 * 365, 80 * 365))
        ctype = rng.choices(["General", "Chronic Rx", "Insured"], weights=[5, 3, 2])[0]
        created = (now - datetime.timedelta(days=rng.randint(0, 150))).strftime("%Y-%m-%d %H:%M:%S")
        customer_ids.append(db.execute(
            "INSERT INTO customers (customer_name, gender, date_of_birth, phone, email, address, city, "
            "customer_type, allergies, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{first} {last}", gender, dob.isoformat(), _phone(rng),
             f"{first.lower()}.{last.lower()}@mail.example.com",
             f"{rng.randint(10, 999)} {rng.choice(STREETS)}", rng.choice(CITIES), ctype,
             rng.choice(ALLERGIES), created),
        ).lastrowid)

    # ------------------------------------------------------------- history
    targets = low_stock | out_of_stock

    def buy(day, med_list, status="Received", offset=999):
        by_supplier = {}
        for m in med_list:
            by_supplier.setdefault(rng.choice(active_suppliers), []).append(m)
        for sid, group in by_supplier.items():
            # Items destined to run short are always bought in small lots
            items = [{"medicine_id": m["id"],
                      "quantity": (m["reorder"] * 2 if m["name"] in targets
                                   else max(m["reorder"] * rng.randint(3, 6), 40)),
                      "unit_price": round(m["cost"] * rng.uniform(0.95, 1.05), 2)} for m in group]
            create_purchase(db, sid, items, purchase_date=day.isoformat(),
                            invoice_no=f"SUP-INV-{rng.randint(10000, 99999)}",
                            status=status, shipping_cost=rng.choice([0, 0, 15, 25]))

    def current_stock(med_id):
        return db.scalar("SELECT stock_quantity FROM medicines WHERE medicine_id = ?", (med_id,), 0)

    weights = [m["pop"] for m in meds]
    start = today - datetime.timedelta(days=120)
    buy(start, meds)

    for offset in range(119, -1, -1):
        day = today - datetime.timedelta(days=offset)
        if offset % 7 == 3 and offset > 2:
            restock = [m for m in meds if current_stock(m["id"]) < m["reorder"] * 2
                       and not (offset < 30 and (m["name"] in low_stock or m["name"] in out_of_stock))]
            if restock:
                buy(day, restock, offset=offset)
        if offset > 60:
            continue
        n_sales = rng.randint(4, 9) + (3 if day.weekday() in (3, 4) else 0)
        times = sorted(rng.randint(9 * 60, 21 * 60) for _ in range(n_sales))
        for minute in times:
            stamp = datetime.datetime.combine(day, datetime.time(minute // 60, minute % 60, rng.randint(0, 59)))
            if stamp > now:
                continue
            chosen = {}
            for med in rng.choices(meds, weights=weights, k=rng.randint(1, 4)):
                chosen[med["id"]] = rng.randint(1, 5)
            items = [{"medicine_id": mid, "quantity": q} for mid, q in chosen.items()
                     if current_stock(mid) >= q]
            if not items:
                continue
            customer = None if rng.random() < 0.35 else rng.choice(customer_ids)
            method = rng.choices(["Cash", "Card", "Mobile Banking", "Insurance"], weights=[5, 3, 2, 1])[0]
            try:
                create_sale(db, items, customer_id=customer, payment_method=method,
                            discount_percent=rng.choice([0, 0, 0, 0, 5, 10]),
                            prescription_ref=(f"RX-{day.year}-{rng.randint(1000, 9999)}"
                                              if rng.random() < 0.3 else None),
                            sale_date=stamp.strftime("%Y-%m-%d %H:%M:%S"))
            except InventoryError:
                pass  # e.g. item expired on that date - skip, like a real cashier would

        if 1 <= offset <= 20:
            # Run designated items down gradually (small daily ward orders) so the alert
            # pages show realistic shortages without one giant sale distorting the charts.
            stamp = datetime.datetime.combine(day, datetime.time(20, 30)).strftime("%Y-%m-%d %H:%M:%S")
            for m in meds:
                if m["name"] not in targets:
                    continue
                goal = 0 if m["name"] in out_of_stock else max(m["reorder"] // 3, 1)
                excess = current_stock(m["id"]) - goal
                qty = -(-excess // offset) if excess > 0 else 0  # ceil(excess / days left)
                if qty:
                    try:
                        create_sale(db, [{"medicine_id": m["id"], "quantity": qty}], payment_method="Insurance",
                                    prescription_ref=f"WARD-{day.strftime('%m%d')}", sale_date=stamp)
                    except InventoryError:
                        pass

    # Two drafts awaiting delivery (no stock impact until received)
    draft_meds = [m for m in meds if m["name"] in low_stock | out_of_stock]
    for sid, group in ((active_suppliers[0], draft_meds[:4]), (active_suppliers[1], draft_meds[4:])):
        if group:
            create_purchase(db, sid, [{"medicine_id": m["id"], "quantity": m["reorder"] * 4,
                                       "unit_price": m["cost"]} for m in group],
                            purchase_date=today.isoformat(), notes="Awaiting delivery - verify cold chain",
                            status="Draft")
