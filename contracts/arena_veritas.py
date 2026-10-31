# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
# ArenaVeritas: AI-verified esports/speedrun integrity settlement desk.
# AVT prize custody vault, native anti-cheat bonds, protest challenge window,
# 4 consensus verdict bands, zero-winner/timeout refunds. Funded payables never
# revert: failures on value-bearing calls credit refundable_balances instead.
from dataclasses import dataclass

from genlayer import *

BAND_VERIFIED = "VERIFIED_CHAMPION_PAYOUT"
BAND_SPLIT = "SPLIT_DRAW_SETTLEMENT"
BAND_VIOLATION = "RULE_VIOLATION_PENALTY"
BAND_CHEAT = "CHEAT_DISQUALIFICATION_SLASH"
BAND_VOID = "VOID_NO_CONTEST_REFUND"
STATUS_OPEN = "OPEN"
STATUS_ACTIVE = "ACTIVE"
STATUS_VERIFIED = "VERIFIED"
STATUS_SETTLED = "SETTLED"
STATUS_VOID = "VOID"
STATUS_REFUNDED = "REFUNDED"

BPS_GRID_STEP = 500
BPS_MAX = 10000
CHAMPION_INTEGRITY_FLOOR_BPS = 8500
CHAMPION_ANOMALY_CEILING_BPS = 1000
CHEAT_ANOMALY_THRESHOLD_BPS = 3000
RULE_VIOLATION_BOND_SLASH_BPS = 1000
VIOLATION_CHAMPION_SHARE_BPS = 7500

MAX_PRIZE_AVT = 10**24
MAX_BOND_WEI = 10**20
MIN_SUBMISSION_WINDOW = 300
MAX_SUBMISSION_WINDOW = 2419200
MIN_MATCH_WINDOW = 60
MAX_MATCH_WINDOW = 604800
MIN_PROTEST_WINDOW = 300
MAX_PROTEST_WINDOW = 86400
MIN_VERIFICATION_TIMEOUT = 3600
MAX_VERIFICATION_TIMEOUT = 2419200
MAX_MATCH_ID_LEN = 64
MAX_TITLE_LEN = 120
MAX_URL_LEN = 2048
MAX_REASON_LEN = 500

ZERO_ADDRESS = Address("0x0000000000000000000000000000000000000000")
ERROR_EXPECTED = "[EXPECTED]"
ERROR_TRANSIENT = "[TRANSIENT]"
ERROR_LLM = "[LLM_ERROR]"

COMPARATIVE_PRINCIPLE = (
    "Require 100 percent exact equality on every field: verdict_band, "
    "verified_winner_slot, quantized_integrity_baseline_bps, "
    "quantized_anomaly_bps, derived_champion_payout, derived_runner_up_payout, "
    "derived_bond_slash. Any difference means disagreement."
)


def _quantize_bps(raw: int) -> int:
    """Snap onto the discrete 500 bps grid, clamped to 0..10000."""
    raw = max(0, min(raw, BPS_MAX))
    remainder = raw % BPS_GRID_STEP
    return min(raw + BPS_GRID_STEP - remainder if remainder * 2 >= BPS_GRID_STEP else raw - remainder, BPS_MAX)


def _days_from_civil(year: int, month: int, day: int) -> int:
    """Deterministic days-since-epoch (Hinnant civil algorithm, int only)."""
    shifted = year - (1 if month <= 2 else 0)
    era = (shifted if shifted >= 0 else shifted - 399) // 400
    yoe = shifted - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468


def _parse_iso_epoch(stamp: str) -> int:
    """Parse ISO-8601 datetime to unix epoch, fail closed on malformed input."""
    if not isinstance(stamp, str) or len(stamp) < 19:
        raise gl.vm.UserError(f"{ERROR_EXPECTED} bad datetime stamp")
    body, sep = stamp, ""
    for cut in ("T", " "):
        if cut in body:
            body, sep = body.split(cut, 1)
            break
    else:
        raise gl.vm.UserError(f"{ERROR_EXPECTED} bad datetime separator")
    offset_secs = 0
    if sep.endswith("Z") or sep.endswith("z"):
        sep = sep[:-1]
    else:
        for sign_char, sign in (("+", 1), ("-", -1)):
            if sign_char in sep[2:]:
                idx = sep.index(sign_char, 2)
                zone, sep = sep[idx + 1:], sep[:idx]
                zh, zm = zone.split(":", 1) if ":" in zone else (zone, "0")
                offset_secs = sign * (int(zh) * 3600 + int(zm) * 60)
                break
    sep = sep.split(".", 1)[0]
    parts = body.split("-")
    if len(parts) != 3 or len(sep.split(":")) != 3:
        raise gl.vm.UserError(f"{ERROR_EXPECTED} bad datetime shape")
    hour, minute, second = (int(x) for x in sep.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 60):
        raise gl.vm.UserError(f"{ERROR_EXPECTED} datetime component out of range")
    epoch = _days_from_civil(int(parts[0]), int(parts[1]), int(parts[2])) * 86400 + hour * 3600 + minute * 60 + second - offset_secs
    if epoch < 0: raise gl.vm.UserError(f"{ERROR_EXPECTED} datetime before unix epoch")
    return epoch


def _derive_band(integrity_q: int, anomaly_q: int, technical_draw: bool, rule_violation: bool, cheat_confirmed: bool) -> str:
    """Deterministic mapping from quantized evidence to one verdict band."""
    if technical_draw: return BAND_SPLIT
    if cheat_confirmed or anomaly_q >= CHEAT_ANOMALY_THRESHOLD_BPS: return BAND_CHEAT
    if integrity_q >= CHAMPION_INTEGRITY_FLOOR_BPS and anomaly_q <= CHAMPION_ANOMALY_CEILING_BPS and not rule_violation:
        return BAND_VERIFIED
    return BAND_VIOLATION


def _derive_payouts(band: str, prize: int, bond: int) -> tuple[int, int, int]:
    """(champion, runner_up, bond_slash) derived exactly from the band."""
    if band == BAND_VERIFIED: return prize, 0, 0
    if band == BAND_SPLIT: return prize // 2, prize - prize // 2, 0
    if band == BAND_VIOLATION: return prize * VIOLATION_CHAMPION_SHARE_BPS // 10000, 0, bond * RULE_VIOLATION_BOND_SLASH_BPS // 10000
    if band == BAND_CHEAT: return prize, 0, bond
    if band == BAND_VOID: return 0, 0, 0
    raise gl.vm.UserError(f"{ERROR_EXPECTED} unknown verdict band {band}")


def _valid_url(target: str) -> bool:
    return (isinstance(target, str) and 0 < len(target) <= MAX_URL_LEN
            and (target.startswith("https://") or target.startswith("http://")) and " " not in target)


def _coerce_bps(raw: object, field: str) -> int:
    """Fail-closed numeric coercion for LLM-extracted bps values."""
    try:
        text = str(raw).strip().replace("%", "")
        dot = text.find(".")
        frac = len(text) - dot - 1 if dot >= 0 else 0
        if frac > 0: text = text.replace(".", "")
        value = int(text) // (10 ** frac) if frac > 0 else int(text)
    except Exception:
        raise gl.vm.UserError(f"{ERROR_LLM} non numeric {field}")
    if value < 0 or value > 100 * BPS_MAX:
        raise gl.vm.UserError(f"{ERROR_LLM} {field} out of range")
    return min(value, BPS_MAX)


def _coerce_flag(raw: object, field: str) -> bool:
    if isinstance(raw, bool): return raw
    if isinstance(raw, int): return raw != 0
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in ("true", "yes", "1"): return True
        if low in ("false", "no", "0", ""): return False
    raise gl.vm.UserError(f"{ERROR_LLM} unparseable flag {field}")


@allow_storage
@dataclass
class MatchRecord:
    match_id: str
    title: str
    game: str
    organizer: Address
    finalist_a: Address
    finalist_b: Address
    telemetry_url: str
    rulebook_url: str
    status: str
    prize_pool_avt: u256
    bond_required_wei: u256
    protest_bond_wei: u256
    submission_close_epoch: u256
    match_close_epoch: u256
    protest_deadline_epoch: u256
    verification_timeout_epoch: u256
    bond_a_wei: u256
    bond_b_wei: u256
    telemetry_submitted_a: bool
    telemetry_submitted_b: bool
    verdict_band: str
    verified_winner_slot: str
    quantized_integrity_baseline_bps: u256
    quantized_anomaly_bps: u256
    derived_champion_payout: u256
    derived_runner_up_payout: u256
    derived_bond_slash: u256
    protest_filed: bool
    protest_target_slot: str
    protestant: Address
    protest_bond_escrow_wei: u256
    refund_claimed: bool


@gl.evm.contract_interface
class IAVTCustodyToken:
    """EVM face of the external AVT custody token for cross-checking."""

    class View:
        def balanceOf(self, holder: Address, /) -> u256: ...

    class Write:
        def transfer(self, to: Address, amount: u256, /) -> bool: ...


class ArenaVeritas(gl.Contract):
    admin: Address
    paused: bool
    avt_token_address: Address
    token_symbol: str
    vault_custody_balance: u256
    native_custody_balance: u256
    token_balances: TreeMap[Address, u256]
    refundable_balances: TreeMap[Address, u256]
    last_payable_rejection: TreeMap[Address, str]
    escrowed_prize_total_avt: u256
    escrowed_bond_total_wei: u256
    escrowed_protest_total_wei: u256
    refundable_total_wei: u256
    token_ledger_total_avt: u256
    total_paid_out_avt: u256
    total_refunds_released_wei: u256
    matches: TreeMap[str, MatchRecord]
    match_ids_order: DynArray[str]
    settlement_count: u256
    void_count: u256
    abandoned_refund_count: u256

    def __init__(self, avt_token_address: str, token_symbol: str):
        self.admin = gl.message.sender_address
        self.paused = False
        if not 0 < len(token_symbol) <= 16:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} bad token symbol")
        self.avt_token_address = Address(avt_token_address)
        self.token_symbol = token_symbol

    @gl.private
    def _now(self) -> u256:
        return _parse_iso_epoch(gl.message_raw["datetime"])

    @gl.private
    def _credit_refundable(self, holder: Address, amount: u256) -> None:
        self.refundable_balances[holder] = self.refundable_balances.get(holder, 0) + amount
        self.refundable_total_wei += amount

    @gl.private
    def _reject_or_soft_fail(self, sender: Address, amount: u256, reason: str) -> dict:
        if amount == 0:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} {reason}")
        self._credit_refundable(sender, amount)
        self.native_custody_balance += amount
        self.last_payable_rejection[sender] = reason
        return {"ok": False, "soft_fail": True, "rejected_reason": reason, "refunded_wei": amount, "refundable_balance": self.refundable_balances.get(sender, 0)}

    @gl.private
    def _require_match(self, match_id: str) -> MatchRecord:
        if match_id not in self.matches: raise gl.vm.UserError(f"{ERROR_EXPECTED} unknown match id")
        return self.matches[match_id]

    @gl.private
    def _slot_of(self, rec: MatchRecord, who: Address) -> str:
        if who == rec.finalist_a: return "FINALIST_A"
        if who == rec.finalist_b: return "FINALIST_B"
        return ""

    @gl.private
    def _opposite_slot(self, slot: str) -> str:
        return "FINALIST_B" if slot == "FINALIST_A" else "FINALIST_A"

    @gl.private
    def _address_in_slot(self, rec: MatchRecord, slot: str) -> Address:
        return rec.finalist_a if slot == "FINALIST_A" else rec.finalist_b

    @gl.private
    def _credit_avt(self, holder: Address, amount: u256) -> None:
        self.token_balances[holder] = self.token_balances.get(holder, 0) + amount
        self.token_ledger_total_avt += amount

    @gl.private
    def _move_bond_to_refundable(self, holder: Address, amount: u256) -> None:
        self.escrowed_bond_total_wei -= amount
        self._credit_refundable(holder, amount)

    @gl.private
    def _move_protest_to_refundable(self, holder: Address, amount: u256) -> None:
        self.escrowed_protest_total_wei -= amount
        self._credit_refundable(holder, amount)

    @gl.private
    def _release_refundable(self, sender: Address, amount: u256) -> dict:
        balance = self.refundable_balances.get(sender, 0)
        if balance == 0: raise gl.vm.UserError(f"{ERROR_EXPECTED} no refundable balance")
        if amount == 0: amount = balance
        if amount > balance: raise gl.vm.UserError(f"{ERROR_EXPECTED} amount exceeds refundable balance")
        self.refundable_balances[sender] = balance - amount
        self.refundable_total_wei -= amount
        self.native_custody_balance -= amount
        self.total_refunds_released_wei += amount
        return {"ok": True, "released_wei": amount, "remaining_refundable": self.refundable_balances.get(sender, 0)}

    @gl.public.write.payable
    def fund_prize_vault_payable(self) -> dict:
        sender = gl.message.sender_address
        value = gl.message.value
        if value <= 0: raise gl.vm.UserError(f"{ERROR_EXPECTED} funding requires value > 0")
        if self.paused: return self._reject_or_soft_fail(sender, value, "contract paused")
        if value > MAX_PRIZE_AVT * 10: return self._reject_or_soft_fail(sender, value, "funding exceeds ceiling")
        self.vault_custody_balance += value
        self.token_balances[sender] = self.token_balances.get(sender, 0) + value
        self.token_ledger_total_avt += value
        self.last_payable_rejection[sender] = ""
        return {"ok": True, "avt_credited": value, "avt_balance": self.token_balances.get(sender, 0), "vault_custody_balance": self.vault_custody_balance}

    @gl.public.write.payable
    def register_tournament_payable(
        self, match_id: str, title: str, game: str, prize_pool_avt: u256,
        bond_required_wei: u256, protest_bond_wei: u256,
        telemetry_report_url: str, rulebook_url: str,
        submission_window_secs: u256, match_window_secs: u256,
        protest_window_secs: u256, verification_timeout_secs: u256,
        finalist_a: Address, finalist_b: Address,
    ) -> dict:
        sender = gl.message.sender_address
        value = gl.message.value
        checks = (
            (not self.paused, "contract paused"),
            (0 < len(match_id) <= MAX_MATCH_ID_LEN, "bad match id length"), (match_id not in self.matches, "duplicate match id"),
            (0 < len(title) <= MAX_TITLE_LEN, "bad title length"), (0 < len(game) <= 48, "bad game length"),
            (_valid_url(telemetry_report_url) and _valid_url(rulebook_url), "bad verification url"),
            (0 < prize_pool_avt <= MAX_PRIZE_AVT, "prize pool outside bounds"), (0 < bond_required_wei <= MAX_BOND_WEI, "bond required outside bounds"),
            (0 < protest_bond_wei <= MAX_BOND_WEI, "protest bond outside bounds"),
            (MIN_SUBMISSION_WINDOW <= submission_window_secs <= MAX_SUBMISSION_WINDOW, "submission window outside bounds"),
            (MIN_MATCH_WINDOW <= match_window_secs <= MAX_MATCH_WINDOW, "match window outside bounds"),
            (MIN_PROTEST_WINDOW <= protest_window_secs <= MAX_PROTEST_WINDOW, "protest window outside bounds"),
            (MIN_VERIFICATION_TIMEOUT <= verification_timeout_secs <= MAX_VERIFICATION_TIMEOUT, "verification timeout window outside bounds"),
            (finalist_a != ZERO_ADDRESS and finalist_b != ZERO_ADDRESS, "zero address finalist"), (finalist_a != finalist_b, "finalists must be distinct"),
        )
        for ok, msg in checks:
            if not ok: return self._reject_or_soft_fail(sender, value, msg)
        now = self._now()
        if value > 0:
            if value != prize_pool_avt: return self._reject_or_soft_fail(sender, value, "sent value must equal prize pool exactly")
            self.vault_custody_balance += value
        else:
            credit = self.token_balances.get(sender, 0)
            if credit < prize_pool_avt: raise gl.vm.UserError(f"{ERROR_EXPECTED} insufficient AVT vault credit for escrow")
            self.token_balances[sender] = credit - prize_pool_avt
            self.token_ledger_total_avt -= prize_pool_avt
        self.escrowed_prize_total_avt += prize_pool_avt
        sub_close = now + submission_window_secs
        self.matches[match_id] = MatchRecord(
            match_id, title, game, sender, finalist_a, finalist_b, telemetry_report_url, rulebook_url, STATUS_OPEN,
            prize_pool_avt, bond_required_wei, protest_bond_wei,
            sub_close, sub_close + match_window_secs, sub_close + match_window_secs + protest_window_secs,
            sub_close + match_window_secs + protest_window_secs + verification_timeout_secs,
            0, 0, False, False, "", "", 0, 0, 0, 0, 0, False, "", ZERO_ADDRESS, 0, False,
        )
        self.match_ids_order.append(match_id)
        self.last_payable_rejection[sender] = ""
        rec = self.matches[match_id]
        return {
            "ok": True, "match_id": match_id, "status": STATUS_OPEN,
            "submission_close_epoch": rec.submission_close_epoch, "match_close_epoch": rec.match_close_epoch,
            "protest_deadline_epoch": rec.protest_deadline_epoch, "verification_timeout_epoch": rec.verification_timeout_epoch,
        }

    @gl.public.write.payable
    def post_competitor_bond_payable(self, match_id: str) -> dict:
        sender = gl.message.sender_address
        value = gl.message.value
        reason = ""
        slot = ""
        if self.paused: reason = "contract paused"
        elif match_id in self.matches:
            rec = self.matches[match_id]
            slot = self._slot_of(rec, sender)
            now = self._now()
            if slot == "": reason = "caller is not a listed finalist"
            elif rec.status not in (STATUS_OPEN, STATUS_ACTIVE): reason = "registration closed for this bracket"
            elif now > rec.submission_close_epoch: reason = "bond deadline passed"
            elif (slot == "FINALIST_A" and rec.bond_a_wei > 0) or (slot == "FINALIST_B" and rec.bond_b_wei > 0): reason = "bond already posted for this slot"
            elif value < rec.bond_required_wei: reason = "insufficient bond value"
        else:
            reason = "unknown match id"
        if reason != "":
            return self._reject_or_soft_fail(sender, value, reason)
        rec = self.matches[match_id]
        accepted = rec.bond_required_wei
        surplus = value - accepted
        if slot == "FINALIST_A":
            rec.bond_a_wei = accepted
        else:
            rec.bond_b_wei = accepted
        if rec.bond_a_wei > 0 and rec.bond_b_wei > 0 and rec.status == STATUS_OPEN:
            rec.status = STATUS_ACTIVE
        self.matches[match_id] = rec
        self.native_custody_balance += accepted
        self.escrowed_bond_total_wei += accepted
        if surplus > 0:
            self._credit_refundable(sender, surplus)
            self.native_custody_balance += surplus
        self.last_payable_rejection[sender] = ""
        return {"ok": True, "slot": slot, "bond_locked_wei": accepted, "surplus_refunded_wei": surplus, "status": rec.status}
    @gl.public.write.payable
    def file_anti_cheat_protest_payable(self, match_id: str, protest_target_slot: str, reason_text: str) -> dict:
        sender = gl.message.sender_address
        value = gl.message.value
        reason = ""
        if len(reason_text) > MAX_REASON_LEN: reason = "protest reason too long"
        elif match_id not in self.matches: reason = "unknown match id"
        else:
            rec = self.matches[match_id]
            now = self._now()
            own_slot = self._slot_of(rec, sender)
            if self.paused: reason = "contract paused"
            elif own_slot == "": reason = "only listed finalists may file protests"
            elif protest_target_slot not in ("FINALIST_A", "FINALIST_B"): reason = "bad protest target slot"
            elif own_slot != self._opposite_slot(protest_target_slot): reason = "self protest is not permitted"
            elif rec.status not in (STATUS_ACTIVE, STATUS_VERIFIED): reason = "protest requires an active or verified bracket"
            elif now < rec.match_close_epoch: reason = "protest window not open yet"
            elif now >= rec.protest_deadline_epoch: reason = "protest window closed"
            elif rec.protest_filed: reason = "a protest is already filed for this bracket"
            elif value < rec.protest_bond_wei: reason = "insufficient protest bond"
        if reason != "":
            return self._reject_or_soft_fail(sender, value, reason)
        rec = self.matches[match_id]
        accepted = rec.protest_bond_wei
        surplus = value - accepted
        rec.protest_filed = True
        rec.protest_target_slot = protest_target_slot
        rec.protestant = sender
        rec.protest_bond_escrow_wei = accepted
        self.matches[match_id] = rec
        self.native_custody_balance += accepted
        self.escrowed_protest_total_wei += accepted
        if surplus > 0:
            self._credit_refundable(sender, surplus)
            self.native_custody_balance += surplus
        self.last_payable_rejection[sender] = ""
        return {"ok": True, "protest_target_slot": protest_target_slot, "protest_bond_locked_wei": accepted, "surplus_refunded_wei": surplus, "protest_deadline_epoch": rec.protest_deadline_epoch}

    @gl.public.write
    def submit_tournament_telemetry(self, match_id: str, replay_note: str) -> dict:
        sender = gl.message.sender_address
        rec = self._require_match(match_id)
        slot = self._slot_of(rec, sender)
        if slot == "": raise gl.vm.UserError(f"{ERROR_EXPECTED} caller is not a finalist")
        now = self._now()
        if rec.status not in (STATUS_OPEN, STATUS_ACTIVE): raise gl.vm.UserError(f"{ERROR_EXPECTED} bracket not live")
        if now > rec.match_close_epoch: raise gl.vm.UserError(f"{ERROR_EXPECTED} telemetry window closed")
        if len(replay_note) > MAX_REASON_LEN: raise gl.vm.UserError(f"{ERROR_EXPECTED} replay note too long")
        if slot == "FINALIST_A":
            rec.telemetry_submitted_a = True
        else:
            rec.telemetry_submitted_b = True
        self.matches[match_id] = rec
        return {"ok": True, "match_id": match_id, "slot": slot, "telemetry_submitted_a": rec.telemetry_submitted_a, "telemetry_submitted_b": rec.telemetry_submitted_b}

    @gl.public.write
    def set_paused(self, value: bool) -> dict:
        if gl.message.sender_address != self.admin:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only admin may pause")
        self.paused = value
        return {"ok": True, "paused": self.paused}

    @gl.public.write
    def mark_void_no_contest(self, match_id: str) -> dict:
        """Zero winner bracket: fewer than two bonded finalists after the
        submission deadline; enables full escrow and bond refunds."""
        rec = self._require_match(match_id)
        now = self._now()
        if rec.status not in (STATUS_OPEN, STATUS_ACTIVE): raise gl.vm.UserError(f"{ERROR_EXPECTED} bracket already decided")
        if now <= rec.submission_close_epoch: raise gl.vm.UserError(f"{ERROR_EXPECTED} submission window still open")
        if rec.bond_a_wei > 0 and rec.bond_b_wei > 0: raise gl.vm.UserError(f"{ERROR_EXPECTED} contest has two bonded finalists")
        rec.status = STATUS_VOID
        rec.verdict_band, rec.verified_winner_slot = BAND_VOID, "NONE"
        rec.derived_champion_payout, rec.derived_runner_up_payout, rec.derived_bond_slash = 0, 0, 0
        self.matches[match_id] = rec
        self.void_count += 1
        return {"ok": True, "match_id": match_id, "status": STATUS_VOID}

    @gl.public.write
    def verify_match_telemetry(self, match_id: str) -> dict:
        rec = self._require_match(match_id)
        now = self._now()
        if rec.status != STATUS_ACTIVE: raise gl.vm.UserError(f"{ERROR_EXPECTED} verification requires an ACTIVE bracket")
        if now < rec.match_close_epoch: raise gl.vm.UserError(f"{ERROR_EXPECTED} match has not closed yet")
        submitted = rec.telemetry_submitted_a or rec.telemetry_submitted_b
        if not submitted and now < rec.submission_close_epoch: raise gl.vm.UserError(f"{ERROR_EXPECTED} no finalist telemetry and window still open")
        mid, telemetry_url, rulebook_url = rec.match_id, rec.telemetry_url, rec.rulebook_url
        prize, bond = rec.prize_pool_avt, rec.bond_required_wei
        a_tag, b_tag = str(rec.finalist_a), str(rec.finalist_b)

        def leader_fn() -> dict:
            telemetry_page = gl.nondet.web.render(telemetry_url, mode="text")
            rulebook_page = gl.nondet.web.render(rulebook_url, mode="text")
            if not isinstance(telemetry_page, str) or len(telemetry_page) < 24: raise gl.vm.UserError(f"{ERROR_TRANSIENT} empty telemetry render")
            if not isinstance(rulebook_page, str) or len(rulebook_page) < 16: raise gl.vm.UserError(f"{ERROR_TRANSIENT} empty rulebook render")
            prompt = (
                "ArenaVeritas integrity desk: judge the live telemetry, replay "
                "and bracket page against the rulebook. Return JSON: "
                "integrity_baseline_bps (int 0..10000 telemetry integrity), "
                "anomaly_index_bps (int 0..10000 input/frame anomaly; aimbot, "
                "macro, splice raise it), technical_draw_verified (verified "
                "server interruption or dead heat), rule_violation (minor "
                "settings infraction), cheat_confirmed (concrete cheat "
                "evidence), compliant_slot (FINALIST_A or FINALIST_B). "
                "FINALIST_A=" + a_tag + ", FINALIST_B=" + b_tag + ". "
                "Integrity >= " + str(CHAMPION_INTEGRITY_FLOOR_BPS)
                + " and anomaly <= " + str(CHAMPION_ANOMALY_CEILING_BPS)
                + " means clean champion; anomaly >= "
                + str(CHEAT_ANOMALY_THRESHOLD_BPS) + " or cheat evidence "
                "means disqualification.\n\n=== RULEBOOK ===\n"
                + rulebook_page[:4000] + "\n\n=== TELEMETRY ===\n"
                + telemetry_page[:8000] + "\n"
            )
            analysis = gl.nondet.exec_prompt(prompt, response_format="json")
            if not isinstance(analysis, dict): raise gl.vm.UserError(f"{ERROR_LLM} LLM returned non dict")
            integrity_q = _quantize_bps(_coerce_bps(analysis.get("integrity_baseline_bps", analysis.get("integrity")), "integrity_baseline_bps"))
            anomaly_q = _quantize_bps(_coerce_bps(analysis.get("anomaly_index_bps", analysis.get("anomaly")), "anomaly_index_bps"))
            draw = _coerce_flag(analysis.get("technical_draw_verified", False), "technical_draw_verified")
            violation = _coerce_flag(analysis.get("rule_violation", False), "rule_violation")
            cheat = _coerce_flag(analysis.get("cheat_confirmed", False), "cheat_confirmed")
            band = _derive_band(integrity_q, anomaly_q, draw, violation, cheat)
            if band == BAND_SPLIT: winner_slot = "DRAW"
            else:
                raw_slot = str(analysis.get("compliant_slot", "")).strip().upper()
                if raw_slot not in ("FINALIST_A", "FINALIST_B"): raise gl.vm.UserError(f"{ERROR_LLM} bad compliant_slot")
                winner_slot = raw_slot
            champion, runner, slash = _derive_payouts(band, prize, bond)
            return {
                "verdict_band": band, "verified_winner_slot": winner_slot, "quantized_integrity_baseline_bps": integrity_q,
                "quantized_anomaly_bps": anomaly_q, "derived_champion_payout": champion,
                "derived_runner_up_payout": runner, "derived_bond_slash": slash, "reasoning": str(analysis.get("reasoning", ""))[:600],
            }

        verdict = gl.eq_principle.prompt_comparative(leader_fn, COMPARATIVE_PRINCIPLE)
        fresh = self.matches[mid]
        if fresh.status != STATUS_ACTIVE: raise gl.vm.UserError(f"{ERROR_EXPECTED} bracket state moved mid verify")
        fresh.status = STATUS_VERIFIED
        fresh.verdict_band, fresh.verified_winner_slot = verdict["verdict_band"], verdict["verified_winner_slot"]
        fresh.quantized_integrity_baseline_bps, fresh.quantized_anomaly_bps = verdict["quantized_integrity_baseline_bps"], verdict["quantized_anomaly_bps"]
        fresh.derived_champion_payout, fresh.derived_runner_up_payout, fresh.derived_bond_slash = verdict["derived_champion_payout"], verdict["derived_runner_up_payout"], verdict["derived_bond_slash"]
        self.matches[mid] = fresh
        return {"ok": True, "match_id": mid, "status": STATUS_VERIFIED, "verdict_band": fresh.verdict_band, "verified_winner_slot": fresh.verified_winner_slot, "quantized_integrity_baseline_bps": fresh.quantized_integrity_baseline_bps, "quantized_anomaly_bps": fresh.quantized_anomaly_bps, "protest_deadline_epoch": fresh.protest_deadline_epoch}

    @gl.private
    def _compute_match_settlement_view(self, rec: MatchRecord) -> dict:
        now, band = self._now(), rec.verdict_band
        champion, runner, slash = rec.derived_champion_payout, rec.derived_runner_up_payout, rec.derived_bond_slash
        derived_ok = True
        if band in (BAND_VERIFIED, BAND_SPLIT, BAND_VIOLATION, BAND_CHEAT, BAND_VOID):
            re_c, re_r, re_s = _derive_payouts(band, rec.prize_pool_avt, rec.bond_required_wei)
            derived_ok = (re_c, re_r, re_s) == (champion, runner, slash)
        submitted = rec.telemetry_submitted_a or rec.telemetry_submitted_b
        return {
            "match_id": rec.match_id, "title": rec.title, "game": rec.game,
            "organizer": str(rec.organizer),
            "finalist_a": str(rec.finalist_a), "finalist_b": str(rec.finalist_b),
            "telemetry_url": rec.telemetry_url, "rulebook_url": rec.rulebook_url,
            "status": rec.status, "verdict_band": band,
            "verified_winner_slot": rec.verified_winner_slot,
            "quantized_integrity_baseline_bps": rec.quantized_integrity_baseline_bps,
            "quantized_anomaly_bps": rec.quantized_anomaly_bps,
            "champion_payout_avt": champion, "runner_up_payout_avt": runner, "bond_slash_wei": slash,
            "prize_pool_avt": rec.prize_pool_avt, "bond_a_wei": rec.bond_a_wei, "bond_b_wei": rec.bond_b_wei,
            "protest_bond_wei": rec.protest_bond_wei, "protest_filed": rec.protest_filed,
            "submission_close_epoch": rec.submission_close_epoch, "match_close_epoch": rec.match_close_epoch,
            "protest_deadline_epoch": rec.protest_deadline_epoch, "verification_timeout_epoch": rec.verification_timeout_epoch,
            "derived_consistency_ok": derived_ok,
            "can_post_bond": now <= rec.submission_close_epoch and rec.status in (STATUS_OPEN, STATUS_ACTIVE),
            "can_verify": rec.status == STATUS_ACTIVE and now >= rec.match_close_epoch and (submitted or now >= rec.submission_close_epoch),
            "can_protest": rec.protest_deadline_epoch > now >= rec.match_close_epoch and rec.status in (STATUS_ACTIVE, STATUS_VERIFIED),
            "can_settle": rec.status == STATUS_VERIFIED and now >= rec.protest_deadline_epoch,
            "can_abandon_refund": (rec.status == STATUS_VOID or (now >= rec.verification_timeout_epoch and rec.status in (STATUS_OPEN, STATUS_ACTIVE))) and not rec.refund_claimed,
        }

    @gl.public.write
    def claim_tournament_settlement(self, match_id: str) -> dict:
        rec = self._require_match(match_id)
        now = self._now()
        if rec.status != STATUS_VERIFIED: raise gl.vm.UserError(f"{ERROR_EXPECTED} bracket is not VERIFIED")
        if now < rec.protest_deadline_epoch: raise gl.vm.UserError(f"{ERROR_EXPECTED} protest window still open, settlement locked")
        view = self._compute_match_settlement_view(rec)
        if not view["derived_consistency_ok"]: raise gl.vm.UserError(f"{ERROR_EXPECTED} derived payout drift")
        band, prize = rec.verdict_band, rec.prize_pool_avt
        champion, runner, slash = rec.derived_champion_payout, rec.derived_runner_up_payout, rec.derived_bond_slash
        winner_slot = rec.verified_winner_slot
        if band == BAND_SPLIT:
            self._credit_avt(rec.finalist_a, champion)
            self._credit_avt(rec.finalist_b, runner)
        else:
            self._credit_avt(self._address_in_slot(rec, winner_slot), champion)
            if band == BAND_VIOLATION: self._credit_avt(rec.organizer, prize - champion)
        self.escrowed_prize_total_avt -= prize
        self.total_paid_out_avt += champion + runner
        violator_slot = self._opposite_slot(winner_slot) if band in (BAND_VIOLATION, BAND_CHEAT) else ""
        for slot_name, bond_amt in (("FINALIST_A", rec.bond_a_wei), ("FINALIST_B", rec.bond_b_wei)):
            if bond_amt == 0: continue
            holder = self._address_in_slot(rec, slot_name)
            keep = (bond_amt - min(slash, bond_amt)) if slot_name == violator_slot else bond_amt
            if keep > 0: self._move_bond_to_refundable(holder, keep)
            slashed = bond_amt - keep
            if slashed > 0:
                clean_addr = self._address_in_slot(rec, self._opposite_slot(slot_name))
                if rec.protest_filed and rec.protest_target_slot == slot_name:
                    self._move_bond_to_refundable(clean_addr, slashed - slashed // 2)
                    self._move_bond_to_refundable(rec.protestant, slashed // 2)
                else:
                    self._move_bond_to_refundable(clean_addr, slashed)
        if rec.protest_filed and rec.protest_bond_escrow_wei > 0:
            upheld = band in (BAND_VIOLATION, BAND_CHEAT) and rec.protest_target_slot == violator_slot
            pay_to = rec.protestant if upheld else self._address_in_slot(rec, rec.protest_target_slot)
            self._move_protest_to_refundable(pay_to, rec.protest_bond_escrow_wei)
            rec.protest_bond_escrow_wei = 0
        rec.status = STATUS_SETTLED
        self.matches[match_id] = rec
        self.settlement_count += 1
        if self.vault_custody_balance != self.escrowed_prize_total_avt + self.token_ledger_total_avt: raise gl.vm.UserError(f"{ERROR_EXPECTED} AVT custody invariant broken")
        if self.native_custody_balance != self.escrowed_bond_total_wei + self.escrowed_protest_total_wei + self.refundable_total_wei: raise gl.vm.UserError(f"{ERROR_EXPECTED} native custody invariant broken")
        return {"ok": True, "match_id": match_id, "status": STATUS_SETTLED, "verdict_band": band, "champion_payout_avt": champion, "bond_slash_wei": slash}

    @gl.public.write
    def claim_abandoned_match_refund(self, match_id: str) -> dict:
        """Unverified past verification_timeout_epoch, or void zero-winner
        brackets: refund 100 percent of escrow, bonds and protest bonds."""
        rec = self._require_match(match_id)
        now = self._now()
        eligible = rec.status == STATUS_VOID or (now >= rec.verification_timeout_epoch and rec.status in (STATUS_OPEN, STATUS_ACTIVE))
        if not eligible or rec.refund_claimed: raise gl.vm.UserError(f"{ERROR_EXPECTED} abandoned refund not eligible")
        self.escrowed_prize_total_avt -= rec.prize_pool_avt
        self._credit_avt(rec.organizer, rec.prize_pool_avt)
        if rec.bond_a_wei > 0:
            self._move_bond_to_refundable(rec.finalist_a, rec.bond_a_wei)
            rec.bond_a_wei = 0
        if rec.bond_b_wei > 0:
            self._move_bond_to_refundable(rec.finalist_b, rec.bond_b_wei)
            rec.bond_b_wei = 0
        if rec.protest_filed and rec.protest_bond_escrow_wei > 0:
            self._move_protest_to_refundable(rec.protestant, rec.protest_bond_escrow_wei)
            rec.protest_bond_escrow_wei = 0
        rec.status, rec.verdict_band, rec.refund_claimed = STATUS_REFUNDED, BAND_VOID, True
        self.matches[match_id] = rec
        self.abandoned_refund_count += 1
        return {"ok": True, "match_id": match_id, "status": STATUS_REFUNDED, "organizer_prize_refunded_avt": rec.prize_pool_avt}

    @gl.public.write
    def withdraw_refund(self, amount: u256) -> dict:
        return self._release_refundable(gl.message.sender_address, amount)

    @gl.public.write
    def claim_refundable_balance(self) -> dict:
        return self._release_refundable(gl.message.sender_address, 0)

    @gl.public.view
    def get_custody_accounting_summary(self) -> dict:
        return {
            "vault_custody_balance_avt": self.vault_custody_balance, "escrowed_prize_total_avt": self.escrowed_prize_total_avt,
            "token_ledger_total_avt": self.token_ledger_total_avt, "native_custody_balance_wei": self.native_custody_balance,
            "escrowed_bond_total_wei": self.escrowed_bond_total_wei, "escrowed_protest_total_wei": self.escrowed_protest_total_wei,
            "refundable_total_wei": self.refundable_total_wei, "total_paid_out_avt": self.total_paid_out_avt,
            "total_refunds_released_wei": self.total_refunds_released_wei, "settlement_count": self.settlement_count,
            "void_count": self.void_count, "abandoned_refund_count": self.abandoned_refund_count,
            "avt_invariant_balanced": self.vault_custody_balance == self.escrowed_prize_total_avt + self.token_ledger_total_avt,
            "native_invariant_balanced": self.native_custody_balance == self.escrowed_bond_total_wei + self.escrowed_protest_total_wei + self.refundable_total_wei,
        }

    @gl.public.view
    def get_match(self, match_id: str) -> dict:
        return self._compute_match_settlement_view(self._require_match(match_id))

    @gl.public.view
    def get_tournament_leaderboard(self) -> list:
        rows = []
        index = 0
        while index < len(self.match_ids_order) and index < 64:
            rows.append(self._compute_match_settlement_view(self.matches[self.match_ids_order[index]]))
            index += 1
        return rows

    @gl.public.view
    def get_refundable_balance(self, holder: Address) -> u256:
        return self.refundable_balances.get(holder, 0)

    @gl.public.view
    def get_avt_balance(self, holder: Address) -> u256:
        return self.token_balances.get(holder, 0)

    @gl.public.view
    def get_last_payable_rejection(self, holder: Address) -> str:
        return self.last_payable_rejection.get(holder, "")

    @gl.public.view
    def external_avt_custody_probe(self) -> dict:
        """Probe the external AVT token balance of this IC to cross-check
        internal custody accounting."""
        balance = IAVTCustodyToken(self.avt_token_address).view().balanceOf(gl.message.contract_address)
        return {"avt_token": str(self.avt_token_address), "external_balance": balance, "internal_vault_custody": self.vault_custody_balance}
