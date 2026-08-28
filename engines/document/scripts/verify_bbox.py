import json, sys, os

print("--- verify_bbox starting ---", flush=True)

if len(sys.argv) < 3:
    sys.exit("usage: verify_bbox.py <out_dir> <pdf_path> [page_no]")

OUT, PDF = sys.argv[1], sys.argv[2]
PAGE = int(sys.argv[3]) if len(sys.argv) > 3 else 1
print(f"cwd:  {os.getcwd()}", flush=True)
print(f"out:  {OUT}  exists={os.path.isdir(OUT)}", flush=True)
print(f"pdf:  {PDF}  exists={os.path.isfile(PDF)}", flush=True)

if not os.path.isdir(OUT):
    sys.exit(f"FATAL: output dir not found: {OUT}")
if not os.path.isfile(PDF):
    sys.exit(f"FATAL: pdf not found: {PDF}\nAvailable in samples/:\n  " +
             "\n  ".join(sorted(os.listdir("samples"))))

import pymupdf
print(f"pymupdf {pymupdf.__doc__}", flush=True)

items = json.load(open(f"{OUT}/text_items.json"))
pages = {p["page_no"]: p for p in json.load(open(f"{OUT}/pages.json"))}
print(f"loaded {len(items)} text items, {len(pages)} pages", flush=True)

if PAGE not in pages:
    sys.exit(f"FATAL: page {PAGE} not in pages.json (have {sorted(pages)[:5]}...)")

doc = pymupdf.open(PDF)
print(f"pdf has {doc.page_count} pages", flush=True)
page = doc[PAGE - 1]
W, H = pages[PAGE]["width"], pages[PAGE]["height"]
sx, sy = page.rect.width / W, page.rect.height / H
print(f"json page dims {W}x{H} | pdf rect {page.rect.width}x{page.rect.height}", flush=True)

n = 0
for it in items:
    if it.get("page_no") != PAGE or not it.get("bbox"):
        continue
    b = it["bbox"]
    x0 = b["l"] * sx
    y0 = (H - b["t"]) * sy       # FLIP: BOTTOMLEFT -> TOPLEFT
    x1 = b["r"] * sx
    y1 = (H - b["b"]) * sy       # FLIP
    page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(1, 0, 0), width=0.8)
    n += 1

if n == 0:
    sys.exit(f"FATAL: 0 items matched page_no == {PAGE}")

dest = os.path.abspath(f"bbox_check_p{PAGE}.png")
page.get_pixmap(dpi=110).save(dest)
print(f"OK: drew {n} boxes -> {dest}", flush=True)


# import json, sys, pymupdf

# OUT = sys.argv[1]          # e.g. out/Policy_Star_Comprehensive_Insurance_Policy_V_21_3a414ab104
# PDF = sys.argv[2]          # e.g. samples/policy_a_digital.pdf
# PAGE = int(sys.argv[3]) if len(sys.argv) > 3 else 1

# items = json.load(open(f"{OUT}/text_items.json"))
# pages = {p["page_no"]: p for p in json.load(open(f"{OUT}/pages.json"))}

# doc = pymupdf.open(PDF)
# page = doc[PAGE - 1]
# W, H = pages[PAGE]["width"], pages[PAGE]["height"]
# sx, sy = page.rect.width / W, page.rect.height / H

# n = 0
# for it in items:
#     if it["page_no"] != PAGE or not it.get("bbox"):
#         continue
#     b = it["bbox"]
#     x0 = b["l"] * sx
#     y0 = (H - b["t"]) * sy      # FLIP
#     x1 = b["r"] * sx
#     y1 = (H - b["b"]) * sy      # FLIP
#     page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(1, 0, 0), width=0.8)
#     n += 1

# page.get_pixmap(dpi=110).save(f"bbox_check_p{PAGE}.png")
# print(f"drew {n} boxes -> bbox_check_p{PAGE}.png")