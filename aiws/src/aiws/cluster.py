"""The homelab view: Proxmox resources (read-only API token), workers and
the inference front-door, in one place. Dashboard only: nothing here
schedules or changes anything."""
import httpx

from aiws import config, jobs, models


def proxmox():
    s = (config.settings().get("proxmox") or {})
    url = s.get("url")
    token = models.secret("AIWS_PVE_TOKEN")  # quay@pve!dash=<uuid>, role PVEAuditor
    if not url or not token:
        return {"configured": False}
    try:
        with httpx.Client(verify=s.get("verify_tls", False), timeout=6,
                          headers={"Authorization": f"PVEAPIToken={token}"}) as c:
            res = c.get(f"{url}/api2/json/cluster/resources").json()["data"]
            st = c.get(f"{url}/api2/json/cluster/status").json()["data"]
    except Exception as e:
        return {"configured": True, "error": str(e)}
    cluster = next((x for x in st if x["type"] == "cluster"), {})
    nodes = [{"name": r["node"], "status": r.get("status"),
              "cpu": round(r.get("cpu", 0) * 100, 1),
              "mem_used_gb": round(r.get("mem", 0) / 2**30, 1),
              "mem_total_gb": round(r.get("maxmem", 0) / 2**30, 1)}
             for r in res if r["type"] == "node"]
    guests = [{"vmid": r["vmid"], "name": r.get("name"), "node": r["node"],
               "type": r["type"], "status": r.get("status"),
               "mem_used_gb": round(r.get("mem", 0) / 2**30, 2),
               "mem_max_gb": round(r.get("maxmem", 0) / 2**30, 2)}
              for r in res if r["type"] in ("qemu", "lxc")]
    return {"configured": True, "cluster": cluster.get("name"),
            "quorate": bool(cluster.get("quorate")), "nodes": nodes,
            "guests": sorted(guests, key=lambda g: g["vmid"])}


def overview():
    ws = []
    for w in jobs.workers().values():
        p = jobs.probe(w)
        ws.append({"name": w["name"], "host": w.get("host") or "this machine",
                   "tags": w.get("tags", []), **p})
    return {"workers": ws, "proxmox": proxmox()}
