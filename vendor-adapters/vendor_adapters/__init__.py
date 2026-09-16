"""Vendor Adapters — Core interface + Generic + Samsung (Knox-gated, honest).

Execution plan references: EXECUTE §22, §23. The adapter layer extends a
resolved policy row with vendor-specific mechanisms ONLY when the mechanism can
be proven available (SDK present, licensed). Nothing is assumed.

Every Knox/enterprise claim stays `VENDOR_DEPENDENT` (or `UNKNOWN`) until the
device/evidence proves it. Samsung-specific code never leaks into the core —
it lives here and only here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class VendorAdapter(ABC):
    vendor_id: str = "generic"

    @abstractmethod
    def enhance(self, row) -> None:
        """Hook: augment a ResolvedRow with vendor mechanisms/notes."""
        raise NotImplementedError

    @property
    @abstractmethod
    def status(self) -> str:
        """e.g. READY | GATED | UNKNOWN"""
        raise NotImplementedError


class GenericAdapter(VendorAdapter):
    vendor_id = "generic"

    def enhance(self, row) -> None:
        row.fallback = row.fallback or "generic restrictions"
        return None

    @property
    def status(self) -> str:
        return "READY (base mechanisms only — no vendor APIs)"


class SamsungAdapter(VendorAdapter):
    """Samsung/Knox adapter.

    Knox Enterprise APIs require the Samsung Enterprise SDK to be present ON the
    device (system app `com.samsung.knox.enterprise`), which we never assume.
    We gate every use behind a runtime capability check.
    """
    vendor_id = "samsung"
    _knox_sdk_present: bool = False

    def set_knox_present(self, present: bool) -> None:
        self._knox_sdk_present = present   # set only from device evidence, never guessed

    def enhance(self, row) -> None:
        if not self._knox_sdk_present:
            # No SDK detected: base DPM path only, honest label.
            if row.supported == "SUPPORTED":
                row.supported = "VENDOR_DEPENDENT"   # never pretend Knox without SDK
            return
        # SDK present: offer vendor-specific extras where meaningful.
        k_map = {
            "CAMERA": ["knox_camera_deactivate"],
            "MICROPHONE": ["knox_mic_restriction"],
            "SCREEN_CAPTURE": ["knox_block_screen_capture"],
            "USB": ["knox_disable_usb_host_port"],
        }
        extra = k_map.get(row.feature)
        if extra:
            row.method = ";".join([row.method, ";".join(extra)]) if row.method else ";".join(extra)
            row.supported = "VENDOR_DEPENDENT"

    @property
    def status(self) -> str:
        if self._knox_sdk_present:
            return "READY (Knox SDK detected)"
        return "GATED (Knox SDK not detected on device — base DPM only)"