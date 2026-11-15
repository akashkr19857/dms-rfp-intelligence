"""Download the public RFP documents used by the demo and build the fictional knowledge base.

    python data/download_data.py
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RFPS = {
    "champaign_CCMS.pdf": "https://champaigncountyil.gov/bid_documents/2025/RFP2025-007_Court_Case_Management_System/"
                          "Champaign%20County%20CCMS%20RFP%20Specification.pdf",
    "detroit_RFP184578.pdf": "https://detroitmi.gov/sites/detroitmi.localhost/files/2024-06/"
                             "RFP%20184578-2%20-%20ARPA%20-%20DoIT%20-%20Physical%20Records%20Management%20Software.pdf",
    "tacoma_PI24-0143F.pdf": "https://cityoftacoma.org/UserFiles/Servers/Server_6/File/cms/Purchasing/FormalBids/PI24-0143F.pdf",
}


def main() -> None:
    out = HERE / "rfps"
    out.mkdir(exist_ok=True)
    for name, url in RFPS.items():
        dest = out / name
        if dest.exists():
            print(f"have {name}")
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (DMS RFP Intelligence demo)"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        if not data.startswith(b"%PDF"):
            raise SystemExit(f"{name}: download did not return a PDF; get it manually from {url}")
        dest.write_bytes(data)
        print(f"downloaded {name} ({len(data) // 1024} KB)")
    if not (HERE / "knowledge_base").exists() or not any((HERE / "knowledge_base").iterdir()):
        subprocess.run([sys.executable, str(HERE / "make_knowledge_base.py")], check=True)


if __name__ == "__main__":
    main()
