import json, sys, urllib.parse, importlib
api = importlib.import_module(sys.argv[1]); specs = json.load(open(sys.argv[2]))
only = set(sys.argv[3].split("|")) if len(sys.argv) > 3 else None
ok, bad = [], []
for s in specs:
    if only and s["name"] not in only: continue
    data = {"editor_mode": "Visual", "layout_json": json.dumps(s["layout"], ensure_ascii=False)}
    if s.get("preview_data"): data["preview_data"] = s["preview_data"]
    try:
        d = api.req("PUT", "/api/resource/Label%20Template/" + urllib.parse.quote(s["name"]), {"data": data})["data"]
        assert d["editor_mode"] == "Visual" and (d["html_template"] or "").startswith("<!-- visual-layout")
        r = api.call("erpnext.devices.doctype.label_template.label_template.render_template_preview", label_template=s["name"], sample=1)
        assert r and r.get("image_base64")
        ok.append(s["name"])
    except Exception as e:
        bad.append((s["name"], str(e)[:150], getattr(e, "read", lambda: b"")().decode(errors="replace")[:300]))
print(sys.argv[1], len(ok), "saved; failed:", bad)
