from datetime import datetime
from difflib import SequenceMatcher

Attachment = dict[str, dict]
Transaction = dict[str, dict]


# --------- Reference handling ----------------

def normalize_ref(ref):
    """Normalize reference numbers for comparison.

    - treat value as string
    - ignore spaces and leading zeros
    - handle optional RF prefix
    """
    if not ref:
        return None
    ref = str(ref).upper()
    if ref.startswith("RF"):
        ref = ref[2:]
    ref = ref.replace(" ", "")
    ref = ref.lstrip("0")
    return ref.lower() or None


def get_transaction_reference(transaction: Transaction) -> str | None:
    raw = transaction.get("reference")
    return normalize_ref(raw)


def get_attachment_reference(attachment: Attachment) -> str | None:
    data = attachment.get("data") or {}
    raw = data.get("reference")
    return normalize_ref(raw)


# ------------- Basic field helpers -------------------


def get_transaction_amount(transaction: Transaction) -> float | None:
    return transaction.get("amount")  # type: ignore[return-value]


def get_attachment_amount(attachment: Attachment) -> float | None:
    data = attachment.get("data") or {}
    return data.get("total_amount")


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_transaction_date(transaction: Transaction) -> datetime | None:
    return parse_date(transaction.get("date"))  # type: ignore[return-value]


def get_attachment_date(attachment: Attachment) -> datetime | None:
    data = attachment.get("data") or {}
    # invoices have invoicing_date / due_date, receipts have receiving_date
    date_str = (
        data.get("invoicing_date")
        or data.get("receiving_date")
        or data.get("due_date")
    )
    return parse_date(date_str)


def normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    s = name.strip().lower()
    # strip common Finnish company suffixes
    for suffix in (" oyj", " oy", " ab", " tmi"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    return s or None


def get_transaction_name(transaction: Transaction) -> str | None:
    # in the fixture this field is called "contact"
    return normalize_name(transaction.get("contact"))  # type: ignore[return-value]


def get_attachment_counterparty(attachment: Attachment) -> str | None:
    data = attachment.get("data") or {}
    issuer = normalize_name(data.get("issuer"))
    recipient = normalize_name(data.get("recipient"))
    supplier = normalize_name(data.get("supplier"))

    company = normalize_name("Example Company Oy")

    candidates = [n for n in (issuer, recipient, supplier) if n and n != company]
    return candidates[0] if candidates else None


# ------------- Scoring ----------------


def amount_score(transaction: Transaction, attachment: Attachment) -> float:
    tx_amount = get_transaction_amount(transaction)
    att_amount = get_attachment_amount(attachment)

    if tx_amount is None or att_amount is None:
        return 0.0

    # Compare absolute values (outgoing payments are negative in the statement)
    diff = abs(abs(tx_amount) - abs(att_amount))
    if diff < 0.01:
        return 1.0
    if diff <= 1.0:
        return 0.6
    return 0.0


def date_score(transaction: Transaction, attachment: Attachment) -> float:
    tx_date = get_transaction_date(transaction)
    att_date = get_attachment_date(attachment)

    if tx_date is None or att_date is None:
        return 0.0

    days = abs((tx_date - att_date).days)
    if days <= 2:
        return 1.0
    if days <= 5:
        return 0.8
    if days <= 10:
        return 0.5
    if days <= 20:
        return 0.2
    return 0.0


def name_score(transaction: Transaction, attachment: Attachment) -> float:
    """Return a similarity-based name score in [0, 1].

    We use a strict threshold so that a small typo
    (like Meittiläinen vs Meikäläinen) is weaker than an exact match.
    """
    tx_name = get_transaction_name(transaction)
    att_name = get_attachment_counterparty(attachment)

    if not tx_name and not att_name:
        return 0.0
    if not tx_name or not att_name:
        return 0.0

    similarity = SequenceMatcher(None, tx_name, att_name).ratio()

    # perfect (or near-perfect) match
    if similarity >= 0.98:
        return 1.0
    # fairly close, but not identical
    if similarity >= 0.90:
        return 0.6

    # below this we consider the names too different to trust
    return 0.0


def match_score(transaction: Transaction, attachment: Attachment) -> float:
    """Heuristic score for pairs without reference numbers.

    Rules:
    - amount must match strongly
    - date must be reasonably close
    - if both sides have a name, the name must give a positive score
    """
    a = amount_score(transaction, attachment)
    d = date_score(transaction, attachment)
    n = name_score(transaction, attachment)

    tx_name = get_transaction_name(transaction)
    att_name = get_attachment_counterparty(attachment)
    has_both_names = bool(tx_name and att_name)

    # amount is a hard requirement
    if a < 1.0:
        return 0.0

    # date must give at least some signal
    if d <= 0.0:
        return 0.0

    # when both names exist they must agree (n > 0)
    if has_both_names and n <= 0.0:
        return 0.0

    # combine the three equally
    return 3.0 * a + 3.0 * d + 3.0 * n


# ---------- Main matching functions ---------------------------


def find_attachment(
    transaction: Transaction,
    attachments: list[Attachment],
) -> Attachment | None:
    """Find the best matching attachment for a given transaction."""
    # 1) reference-based matching
    tx_ref = get_transaction_reference(transaction)
    if tx_ref is not None:
        ref_matches: list[Attachment] = []
        for attachment in attachments:
            att_ref = get_attachment_reference(attachment)
            if att_ref is None:
                continue
            if att_ref == tx_ref:
                ref_matches.append(attachment)

        if len(ref_matches) == 1:
            return ref_matches[0]
        if len(ref_matches) > 1:
            # ambiguous reference -> safer to skip
            return None

    # 2) heuristic fallback (amount + date + name),
    #    only when both sides do not have a reference
    best: Attachment | None = None
    best_score = 0.0
    second_best = 0.0

    for attachment in attachments:
        att_ref = get_attachment_reference(attachment)

        if tx_ref is not None or att_ref is not None:
            # do not guess for items that have explicit references
            continue

        score = match_score(transaction, attachment)
        if score > best_score:
            second_best = best_score
            best_score = score
            best = attachment
        elif score > second_best:
            second_best = score

    THRESHOLD = 3.5
    MARGIN = 1.0

    if best is None:
        return None
    if best_score < THRESHOLD:
        return None
    if best_score - second_best < MARGIN:
        return None

    return best


def find_transaction(
    attachment: Attachment,
    transactions: list[Transaction],
) -> Transaction | None:
    """Find the best matching transaction for a given attachment."""
    # 1) reference-based matching
    att_ref = get_attachment_reference(attachment)
    if att_ref is not None:
        ref_matches: list[Transaction] = []
        for transaction in transactions:
            tx_ref = get_transaction_reference(transaction)
            if tx_ref is None:
                continue
            if tx_ref == att_ref:
                ref_matches.append(transaction)

        if len(ref_matches) == 1:
            return ref_matches[0]
        if len(ref_matches) > 1:
            return None

    # 2) heuristic fallback, again only when both sides lack references
    best: Transaction | None = None
    best_score = 0.0
    second_best = 0.0

    for transaction in transactions:
        tx_ref = get_transaction_reference(transaction)

        if att_ref is not None or tx_ref is not None:
            continue

        score = match_score(transaction, attachment)
        if score > best_score:
            second_best = best_score
            best_score = score
            best = transaction
        elif score > second_best:
            second_best = score

    THRESHOLD = 3.5
    MARGIN = 1.0

    if best is None:
        return None
    if best_score < THRESHOLD:
        return None
    if best_score - second_best < MARGIN:
        return None

    return best