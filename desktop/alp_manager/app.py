"""ALP Manager — Tkinter desktop UI over the headless Controller.

Threading model: every Controller call (ADB can block) runs on a worker
thread and the result is marshalled back to the UI main thread via `after`.
Tk widgets are only ever touched from the main thread.
"""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from .controller import Controller
from backend.recovery import RECOVERY_MODES

MODE_HINTS = {
    "R1_RESTORE_POINT": "Restore point: clear applied restrictions (probe-verified, requires 2nd approver)",
    "R2_REPROVISION": "Re-provision: plan only (needs matching hardware/DPC in the field)",
    "R3_LAB_FLASH": "Lab flash of firmware: ALWAYS REFUSED (governance LAB_ONLY)",
    "R4_DIAGNOSTIC": "Diagnostic: read-only bundle + report file (no approvals)",
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ALP Manager — Android Lockdown Platform")
        self.geometry("1180x760")
        self.ctl = Controller()
        self._async_lock = threading.Lock()

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True)

        self._tab_session = ttk.Frame(self._nb)
        self._tab_devices = ttk.Frame(self._nb)
        self._tab_apply = ttk.Frame(self._nb)
        self._tab_recovery = ttk.Frame(self._nb)
        self._tab_audit = ttk.Frame(self._nb)
        for name, tab in (("Session", self._tab_session), ("Devices", self._tab_devices),
                          ("Apply policy", self._tab_apply), ("Recovery", self._tab_recovery),
                          ("Audit", self._tab_audit)):
            self._nb.add(tab, text=name)

        self._build_session()
        self._build_devices()
        self._build_apply()
        self._build_recovery()
        self._build_audit()
        self._refresh_session_state()
        self._async(self._refresh_devices, self._devices_loaded)

    # ------------------------------------------------------------------
    # async plumbing
    # ------------------------------------------------------------------
    def _async(self, fn, on_done=None, on_err=None):
        def runner():
            try:
                result = fn()
            except Exception as ex:  # noqa: BLE001 — surfaced to UI
                result = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
            try:
                self.after(0, lambda: on_done and on_done(result))
            except (tk.TclError, RuntimeError):
                pass  # window already closed

        threading.Thread(target=runner, daemon=True).start()

    @staticmethod
    def _fmt(res) -> str:
        return json.dumps(res, indent=2, ensure_ascii=False)

    @staticmethod
    def _set_text(widget: tk.Text, text: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ------------------------------------------------------------------
    # Session tab
    # ------------------------------------------------------------------
    def _build_session(self):
        frame = self._tab_session
        self._sess_status = ttk.Label(frame, text="")
        self._sess_status.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=4)

        self._sess_state = ttk.Label(frame, text="detecting…")
        self._sess_state.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=2)

        box = ttk.LabelFrame(frame, text="Authenticate", padding=8)
        box.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=6)

        ttk.Label(box, text="Username").grid(row=0, column=0, sticky="e", padx=4)
        self._sess_user = ttk.Entry(box, width=24)
        self._sess_user.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(box, text="Password").grid(row=1, column=0, sticky="e", padx=4)
        self._sess_pass = ttk.Entry(box, width=24, show="*")
        self._sess_pass.grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(box, text="TOTP code").grid(row=2, column=0, sticky="e", padx=4)
        self._sess_totp = ttk.Entry(box, width=24)
        self._sess_totp.grid(row=2, column=1, sticky="w", padx=4)

        self._sess_btn = ttk.Button(box, text="Bootstrap first admin", command=self._bootstrap)
        self._sess_btn.grid(row=3, column=1, sticky="w")
        ttk.Button(box, text="Login", command=self._login).grid(row=3, column=2, sticky="w")
        ttk.Button(frame, text="Logout", command=self._logout).grid(row=4, column=0, sticky="w", padx=8)
        ttk.Button(frame, text="Disable MFA / session help", command=self._whoami).grid(row=4, column=1, sticky="w")

        self._sess_log = scrolledtext.ScrolledText(frame, height=8, state="disabled")
        self._sess_log.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=8, pady=6)
        frame.columnconfigure(2, weight=1)
        frame.rowconfigure(5, weight=1)

    def _refresh_session_state(self):
        if self.ctl.needs_bootstrap():
            self._sess_state.configure(text="No administrators registered — bootstrap required.")
            self._sess_btn.configure(state="normal")
        else:
            self._sess_btn.configure(state="disabled")
            self._sess_state.configure(text="Administrators registered — login with TOTP.")

    def _whoami(self):
        self._async(self.ctl.whoami, lambda r: self._set_text(self._sess_log, r if isinstance(r, str) else self._fmt(r)))

    def _bootstrap(self):
        user = self._sess_user.get().strip()
        pw = self._sess_pass.get()
        if not user or not pw:
            messagebox.showerror("Bootstrap", "username and password required")
            return
        self._async(lambda: self.ctl.bootstrap(user, pw), self._bootstrap_done)

    def _bootstrap_done(self, res):
        self._set_text(self._sess_log, self._fmt(res))
        if res.get("ok"):
            messagebox.showinfo(
                "Bootstrap complete",
                "Scan/enter the TOTP URI in your authenticator, then login.\n\n"
                + res.get("totp_uri", ""))
            self._refresh_session_state()
            self._sess_log.configure(state="normal")
            self._sess_log.insert("end", "\n\nSecret (backup): " + res.get("secret", "") + "\n")
            self._sess_log.configure(state="disabled")

    def _login(self):
        user = self._sess_user.get().strip()
        pw = self._sess_pass.get()
        code = self._sess_totp.get().strip()
        if not user or not pw or not code:
            messagebox.showerror("Login", "username, password and TOTP code are required")
            return
        self._async(lambda: self.ctl.login(user, pw, code), self._login_done)

    def _login_done(self, res):
        self._set_text(self._sess_log, self._fmt(res))
        if res.get("ok"):
            self._sess_status.configure(text=f"Signed in: {res.get('display_name')} ({res.get('role_id')})")
            self._async(self._refresh_devices)
        else:
            self._sess_status.configure(text=res.get("error", "login failed"))

    def _logout(self):
        self._async(self.ctl.logout, lambda r: (self._sess_status.configure(text="Logged out"), self._refresh_session_state()))

    # ------------------------------------------------------------------
    # Devices tab
    # ------------------------------------------------------------------
    def _build_devices(self):
        frame = self._tab_devices
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=8, pady=4)
        ttk.Label(top, text="ADB:").pack(side="left")
        self._adb_label = ttk.Label(top, text="…")
        self._adb_label.pack(side="left", padx=4)
        ttk.Button(top, text="Refresh ADB/devices", command=lambda: self._async(self._refresh_devices, self._devices_loaded)).pack(side="left", padx=8)
        ttk.Button(top, text="Generate device report", command=self._report).pack(side="left", padx=8)

        cols = ("id", "serial", "model", "android", "state", "owner", "compliance")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        for c, w, title in (("id", 130, "device_id"), ("serial", 140, "serial"),
                            ("model", 150, "model"), ("android", 80, "Android"),
                            ("state", 120, "enrollment_state"),
                            ("owner", 80, "device_owner"), ("compliance", 110, "compliance")):
            self._tree.heading(c, text=title)
            self._tree.column(c, width=w)
        self._tree.pack(fill="both", expand=True, padx=8, pady=4)

        ops = ttk.LabelFrame(frame, text="Enroll / probe / classify", padding=8)
        ops.pack(fill="x", padx=8, pady=4)
        ttk.Label(ops, text="Serial").grid(row=0, column=0, sticky="e")
        self._enroll_serial = ttk.Entry(ops, width=28)
        self._enroll_serial.grid(row=0, column=1)
        ttk.Label(ops, text="device_id (optional)").grid(row=0, column=2, sticky="e")
        self._enroll_did = ttk.Entry(ops, width=18)
        self._enroll_did.grid(row=0, column=3)
        self._enroll_lab = tk.BooleanVar(value=False)
        ttk.Checkbutton(ops, text="lab", variable=self._enroll_lab).grid(row=0, column=4)
        ttk.Button(ops, text="Enroll", command=self._enroll).grid(row=0, column=5, padx=4)
        ttk.Button(ops, text="Probe (live read)", command=self._probe).grid(row=0, column=6)
        ttk.Button(ops, text="Classify (vendor/version)", command=self._classify).grid(row=0, column=7)

        self._dev_log = scrolledtext.ScrolledText(frame, height=10, state="disabled")
        self._dev_log.pack(fill="both", expand=True, padx=8, pady=4)

    def _refresh_devices(self):
        return {"devices": self.ctl.devices(), "adb": self.ctl.adb_status()}

    def _devices_loaded(self, res):
        if not isinstance(res, dict) or "devices" not in res:
            self._set_text(self._dev_log, self._fmt(res))
            return
        adb = res.get("adb", {})
        self._adb_label.configure(text=f"{adb.get('configured')} — attached: {', '.join(adb.get('devices', []) or ['none'])}")
        self._tree.delete(*self._tree.get_children())
        for d in res["devices"]:
            self._tree.insert("", "end", values=(
                d.get("device_id", ""), d.get("serial", ""), d.get("model", ""),
                d.get("android_version", ""), d.get("enrollment_state", ""),
                d.get("device_owner_state", ""), d.get("compliance_state", "")))
        self._populate_combos()

    def _selected_device(self) -> dict:
        did = self._selected_device_id()
        if not did:
            return {}
        return next((d for d in self.ctl.devices() if d["device_id"] == did), {})

    def _selected_device_id(self) -> str:
        sel = self._tree.selection()
        if not sel:
            return ""
        return self._tree.item(sel[0], "values")[0]

    def _enroll(self):
        serial = self._enroll_serial.get().strip()
        if not serial:
            messagebox.showerror("Enroll", "serial required")
            return
        did = self._enroll_did.get().strip()
        lab = self._enroll_lab.get()
        self._async(lambda: self.ctl.enroll(serial, did, lab),
                    lambda r: (self._set_text(self._dev_log, self._fmt(r)), self._async(self._refresh_devices, self._devices_loaded)))

    def _probe(self):
        dev = self._selected_device()
        if not dev or not dev.get("serial"):
            messagebox.showerror("Probe", "select an enrolled device with a serial")
            return
        self._async(lambda: self.ctl.probe(dev["serial"]),
                    lambda r: self._set_text(self._dev_log, self._fmt(r)))

    def _classify(self):
        dev = self._selected_device()
        if not dev:
            messagebox.showerror("Classify", "select a device row first")
            return
        self._async(lambda: self.ctl.classify(
            dev.get("manufacturer", "") or "", dev.get("model", "") or "",
            dev.get("android_version", 0) or 0, dev.get("api_level", 0) or 0,
            dev.get("build_fingerprint", "") or ""),
            lambda r: self._set_text(self._dev_log, self._fmt(r) if isinstance(r, dict) else str(r)))

    def _report(self):
        did = self._selected_device_id()
        if not did:
            messagebox.showerror("Report", "select a device row first")
            return
        self._async(lambda: self.ctl.generate_device_report(did),
                    lambda r: self._set_text(self._dev_log, self._fmt(r)))

    # ------------------------------------------------------------------
    # Apply tab
    # ------------------------------------------------------------------
    def _build_apply(self):
        frame = self._tab_apply
        box = ttk.LabelFrame(frame, text="Apply policy (Director AD-4, ADB channel)", padding=8)
        box.pack(fill="x", padx=8, pady=6)
        ttk.Label(box, text="Device").grid(row=0, column=0, sticky="e")
        self._apply_dev = ttk.Combobox(box, state="readonly", width=30)
        self._apply_dev.grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="Policy").grid(row=0, column=2, sticky="e")
        self._apply_pol = ttk.Combobox(box, state="readonly", width=22)
        self._apply_pol.grid(row=0, column=3, sticky="w")
        ttk.Label(box, text="MFA code (operator)").grid(row=1, column=0, sticky="e")
        self._apply_mfa = ttk.Entry(box, width=30)
        self._apply_mfa.grid(row=1, column=1, sticky="w")
        ttk.Label(box, text="Lane subset (optional, comma)").grid(row=1, column=2, sticky="e")
        self._apply_sub = ttk.Entry(box, width=22)
        self._apply_sub.grid(row=1, column=3, sticky="w")
        ttk.Button(box, text="Apply now", command=self._apply).grid(row=2, column=1, sticky="w", pady=4)

        hint = ttk.Label(frame, text="PASS only ever comes from a REAL_DEVICE observation with an evidence_id. "
                                     "SIMULATED never passes; R3 flash is always refused.", foreground="#7a5c00")
        hint.pack(fill="x", padx=8)
        self._apply_log = scrolledtext.ScrolledText(frame, height=28, state="disabled")
        self._apply_log.pack(fill="both", expand=True, padx=8, pady=4)
        frame.columnconfigure(1, weight=1)

    def _apply(self):
        did = self._apply_dev.get()
        pol = self._apply_pol.get()
        mfa = self._apply_mfa.get().strip()
        subset = self._apply_sub.get().strip()
        if not did or not pol:
            messagebox.showerror("Apply", "device and policy required")
            return
        if not mfa:
            messagebox.showerror("Apply", "an MFA-verified actor is mandatory for APPLY")
            return
        self._async(lambda: self.ctl.apply(did, pol.split()[0], mfa, real=True, lane_subset=subset),
                    lambda r: self._set_text(self._apply_log, self._fmt(r)))

    # ------------------------------------------------------------------
    # Recovery tab
    # ------------------------------------------------------------------
    def _build_recovery(self):
        frame = self._tab_recovery
        box = ttk.LabelFrame(frame, text="Recovery engine (R1..R4)", padding=8)
        box.pack(fill="x", padx=8, pady=6)
        ttk.Label(box, text="Device").grid(row=0, column=0, sticky="e")
        self._rec_dev = ttk.Combobox(box, state="readonly", width=26)
        self._rec_dev.grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="Mode").grid(row=0, column=2, sticky="e")
        self._rec_mode = ttk.Combobox(box, state="readonly", width=20, values=list(RECOVERY_MODES))
        self._rec_mode.grid(row=0, column=3, sticky="w")
        self._rec_mode.set("R1_RESTORE_POINT")
        self._rec_mode.bind("<<ComboboxSelected>>", lambda _e: self._mode_hint())
        ttk.Label(box, text="MFA code (operator)").grid(row=1, column=0, sticky="e")
        self._rec_mfa = ttk.Entry(box, width=26)
        self._rec_mfa.grid(row=1, column=1, sticky="w")
        ttk.Label(box, text="Reason").grid(row=1, column=2, sticky="e")
        self._rec_reason = ttk.Entry(box, width=22)
        self._rec_reason.grid(row=1, column=3, sticky="w")

        ttk.Label(box, text="Approver user (2nd approver for R1/R2)").grid(row=2, column=0, sticky="e")
        self._rec_aprv = ttk.Entry(box, width=26)
        self._rec_aprv.grid(row=2, column=1, sticky="w")
        ttk.Label(box, text="Approver MFA").grid(row=2, column=2, sticky="e")
        self._rec_aprv_mfa = ttk.Entry(box, width=22)
        self._rec_aprv_mfa.grid(row=2, column=3, sticky="w")

        self._rec_skip = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="skip approval", variable=self._rec_skip).grid(row=3, column=1, sticky="w")
        ttk.Button(box, text="Run recovery", command=self._recover).grid(row=3, column=3, sticky="w")

        self._rec_hint = ttk.Label(frame, text="", foreground="#3a6ea5")
        self._rec_hint.pack(fill="x", padx=8)
        self._rec_log = scrolledtext.ScrolledText(frame, height=24, state="disabled")
        self._rec_log.pack(fill="both", expand=True, padx=8, pady=4)

    def _mode_hint(self):
        mode = self._rec_mode.get()
        self._rec_hint.configure(text=MODE_HINTS.get(mode, ""))

    def _recover(self):
        did = self._rec_dev.get()
        mode = self._rec_mode.get()
        mfa = self._rec_mfa.get().strip()
        if not did or not mode:
            messagebox.showerror("Recovery", "device and mode required")
            return
        if not mfa:
            messagebox.showerror("Recovery", "MFA code required for recovery")
            return
        self._async(lambda: self.ctl.recover(
            did, mode, mfa,
            approver_user=self._rec_aprv.get().strip(),
            approver_mfa=self._rec_aprv_mfa.get().strip(),
            reason=self._rec_reason.get().strip(),
            skip_approval=self._rec_skip.get(),
            exec_=True),
            lambda r: self._set_text(self._rec_log, self._fmt(r)))

    # ------------------------------------------------------------------
    # Audit tab
    # ------------------------------------------------------------------
    def _build_audit(self):
        frame = self._tab_audit
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=8, pady=4)
        ttk.Label(top, text="Tail").pack(side="left")
        self._audit_tail = ttk.Entry(top, width=8)
        self._audit_tail.insert(0, "50")
        self._audit_tail.pack(side="left", padx=4)
        ttk.Button(top, text="Refresh audit", command=self._audit).pack(side="left", padx=6)
        ttk.Button(top, text="Tamper check", command=self._tamper).pack(side="left", padx=6)
        self._audit_status = ttk.Label(top, text="")
        self._audit_status.pack(side="left", padx=12)

        self._audit_log = scrolledtext.ScrolledText(frame, height=28, state="disabled")
        self._audit_log.pack(fill="both", expand=True, padx=8, pady=4)

    def _audit(self):
        def run():
            try:
                n = int(self._audit_tail.get().strip() or "50")
            except ValueError:
                n = 50
            return self.ctl.audit(tail=n)
        self._async(run, lambda rows: self._set_text(
            self._audit_log, "\n".join(self._fmt_row(r) for r in rows) or "_empty_"))

    @staticmethod
    def _fmt_row(r) -> str:
        return (f"#{r.get('entry_id')} {r.get('created_at')}  {r.get('username') or r.get('role_code') or '-'}  "
                f"{r.get('action')} -> {r.get('result') or '-'}  device={r.get('device_id') or '-'}  "
                f"detail={r.get('detail') or ''}")

    def _tamper(self):
        self._async(self.ctl.tamper_check,
                    lambda res: (self._set_text(self._audit_log, self._fmt(res)),
                                 self._audit_status.configure(
                                     text="chain broken" if res.get("broken") else "chain intact")))

    # ------------------------------------------------------------------
    # populating shared combos
    # ------------------------------------------------------------------
    def _populate_combos(self):
        devs = self.ctl.devices()
        ids = [f"{d['device_id']} [{d.get('serial') or ''}]" for d in devs]
        for cb in (self._apply_dev, self._rec_dev):
            cb.configure(values=ids)
            if ids and not cb.get():
                cb.set(ids[0])
        pols = self.ctl.policies()
        pol_ids = [f"{p['policy_id']} — {p['display_name']} ({p['status']})" for p in pols]
        self._apply_pol.configure(values=pol_ids)
        if pol_ids:
            self._apply_pol.set(pol_ids[0])


def main():
    App().mainloop()