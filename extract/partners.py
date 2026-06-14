"""Partner registry.

Maps each partner to its Halo client_id, TeamGPS company name, and local
transcript folder. `client_id` may be left None — build_partner will resolve it
at runtime via Halo's `/api/Client?search=` (and print the discovered id so it
can be pinned here for speed/accuracy later).

`halo_search` / `teamgps_company` default to `name` when omitted.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Partner:
    name: str                                  # canonical display name
    transcript_dir: str                        # folder under Transcripts/
    client_id: Optional[int] = None            # Halo client id (None -> resolve)
    halo_search: Optional[str] = None          # override Halo client search term
    teamgps_company: Optional[str] = None       # override TeamGPS company filter
    ticket_search: str = "Service Call"        # review-ticket summary search term

    def __post_init__(self):
        self.halo_search = self.halo_search or self.name
        self.teamgps_company = self.teamgps_company or self.name


# Only Logically's client_id (106) is known from the SOP; the rest resolve by
# name search on first run.
PARTNERS = [
    Partner("Logically", "Logically", client_id=106),
    Partner("Alliance InfoSystems", "Alliance InfoSystems", teamgps_company="Alliance InfoSystems LLC"),  # TeamGPS company carries the "LLC" suffix
    Partner("Computer Weavers", "Computer Weavers"),
    Partner("ION247", "ION247"),
    Partner("Liongard", "Liongard"),
    Partner("Milner", "Milner"),
    Partner("MSPCorp", "MSPCorp", halo_search="MSP Corp", teamgps_company="MSP Corp"),
    Partner("Premier Technologies", "Premier Technologies"),
    Partner("Realtime IT", "Realtime IT", client_id=147,
            teamgps_company="RealTime, LLC"),  # Halo + TeamGPS both "RealTime, LLC"
    Partner("Stasmayer", "Stasmayer", teamgps_company="Stasmayer Inc."),  # TeamGPS carries "Inc."
]

BY_NAME = {p.name.lower(): p for p in PARTNERS}


def get(name: str) -> Partner:
    p = BY_NAME.get(name.lower())
    if not p:
        raise KeyError(f"Unknown partner '{name}'. Known: {[p.name for p in PARTNERS]}")
    return p
