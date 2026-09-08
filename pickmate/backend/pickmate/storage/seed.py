from pickmate.domain.models import Item


def inventory() -> list[Item]:
    rows = [
        ("CT-BLU", "blue cartons", "A-03", 40, "blue", "standard", ["blue boxes"]),
        ("CT-RED", "red cartons", "B-07", 32, "red", "standard", ["red boxes"]),
        ("CT-GRN", "green cartons", "A-04", 0, "green", "standard", ["green boxes"]),
        ("CT-YEL", "yellow cartons", "A-05", 2, "yellow", "standard", ["yellow boxes"]),
        ("CT-BLS", "small blue cartons", "A-02", 24, "blue", "small", ["small blue boxes"]),
        ("CT-RDL", "large red cartons", "B-08", 18, "red", "large", ["large red boxes"]),
        ("TP-CLR", "clear packing tape", "C-01", 60, "clear", "standard", ["clear tape"]),
        ("TP-BRN", "brown packing tape", "C-02", 45, "brown", "standard", ["brown tape"]),
        ("LB-WHT", "white shipping labels", "C-03", 120, "white", "standard", ["white labels"]),
        ("LB-FRG", "fragile labels", "C-04", 90, "red", "standard", ["fragile stickers"]),
        ("BG-SML", "small mailer bags", "D-01", 75, "white", "small", ["small mailers"]),
        ("BG-LRG", "large mailer bags", "D-02", 55, "white", "large", ["large mailers"]),
        ("WR-BBL", "bubble wrap rolls", "D-03", 16, "clear", "standard", ["bubble wrap"]),
        ("WR-STR", "stretch wrap rolls", "D-04", 21, "clear", "standard", ["stretch wrap"]),
        ("GL-SML", "small work gloves", "E-01", 30, "grey", "small", ["small gloves"]),
        ("GL-LRG", "large work gloves", "E-02", 28, "grey", "large", ["large gloves"]),
        ("BN-BLU", "blue storage bins", "F-01", 12, "blue", "standard", ["blue bins"]),
        ("BN-RED", "red storage bins", "F-02", 10, "red", "standard", ["red bins"]),
        ("EN-PAD", "padded envelopes", "F-03", 80, "brown", "standard", ["padded mailers"]),
        ("MK-BLK", "black marker pens", "F-04", 36, "black", "standard", ["black markers"]),
    ]
    return [
        Item(
            sku=sku,
            name=name,
            bin=location,
            available=stock,
            aliases=aliases,
            attributes={"color": color, "size": size},
        )
        for sku, name, location, stock, color, size, aliases in rows
    ]
